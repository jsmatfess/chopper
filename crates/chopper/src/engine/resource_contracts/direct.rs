//! Run the direct-publication ownership recipe on both native and WASI layouts.
use super::*;

pub(super) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let output = dir.path().join("output");
    let temp = dir.path().join("temp");
    std::fs::create_dir(&temp)?;
    std::fs::write(&input, b"id,key\n1,a\n2,b\n")?;
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        output: output.to_string_lossy().into_owned(),
        random_seed: Some("direct-resource-contract".into()),
        ..Job::default()
    };
    job.resources.memory_mb = 32.into();
    job.resources.workers = 1;
    job.resources.max_record_bytes = 2 * 1024 * 1024;
    job.resources.temp_dir = Some(temp.to_string_lossy().into_owned());
    job.limits.rows = Some(1);
    let clean = || -> Result<()> {
        ensure!(!output.exists(), "denied direct output was published");
        ensure!(
            std::fs::read_dir(&temp)?.count() == 0,
            "direct denial leaked temporary data"
        );
        for entry in std::fs::read_dir(dir.path())? {
            ensure!(
                !entry?
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".chopper-staging-"),
                "direct denial leaked staging"
            );
        }
        Ok(())
    };
    let pool = Arc::new(MemoryPool::new(32 * 1024 * 1024));
    let mut owner =
        Reservation::for_workspace(Arc::new(Workspace::shared(32 * 1024 * 1024, pool.clone())));
    owner.resize(32 * 1024 * 1024)?;
    let attempt = |job: Job, pool| {
        run_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool,
        )
    };
    let error = attempt(job.clone(), pool.clone())
        .err()
        .context("expected direct shared denial")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ),
        "wrong direct shared denial: {error:#}"
    );
    ensure!(
        pool.usage().reserved_bytes == 32 * 1024 * 1024,
        "direct denial changed competing owner"
    );
    clean()?;
    drop(owner);
    let analysis = attempt(job.clone(), pool.clone())?;
    ensure!(
        analysis.rows == 2 && analysis.output_files == 2,
        "direct retry counts changed"
    );
    ensure!(
        std::fs::read(output.join("part-00000001.csv"))? == b"id,key\n1,a\n",
        "direct retry fields changed"
    );
    let clone = analysis.clone();
    let retained = pool.usage().reserved_bytes;
    ensure!(retained > 0, "returned direct analysis missing admission");
    drop(analysis);
    ensure!(
        pool.usage().reserved_bytes == retained,
        "direct clone released admission early"
    );
    drop(clone);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "direct final clone leaked admission"
    );
    std::fs::remove_dir_all(&output)?;

    // Late-wide serialization overlap exceeds the local 32 MiB job envelope.
    std::fs::write(
        &input,
        format!(
            "{}\n{}\n",
            "h".repeat(1_900_000),
            '"'.to_string().repeat(1_900_000)
        ),
    )?;
    job.input_csv.quote = '\'';
    job.output_csv.encoding = "utf-16le".into();
    job.compression = Compression::Gzip;
    let pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
    let error = attempt(job.clone(), pool.clone())
        .err()
        .context("expected direct local denial")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ),
        "wrong direct local denial: {error:#}"
    );
    ensure!(
        pool.usage().reserved_bytes == 0,
        "local denial leaked admission"
    );
    clean()?;
    job.resources.memory_mb = 128.into();
    drop(attempt(job, pool.clone())?);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "wide direct retry leaked admission"
    );
    dir.close()?;
    Ok(
        json!({"contract":"direct-run-resource-contract-v1", "shared_denial_retry":true,
        "local_denial_retry":true, "final_clone_release":true, "failure_cleanup":true,
        "fixture_directory_removed":true}),
    )
}

#[cfg(test)]
#[test]
fn direct_publication_admission_and_cleanup() -> Result<()> {
    run().map(|_| ())
}
