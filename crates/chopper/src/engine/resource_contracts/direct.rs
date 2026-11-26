//! Run the direct-publication ownership recipe on both native and WASI layouts.
use super::*;

fn partition_shuffle_writer_boundary(root: &std::path::Path) -> Result<()> {
    use crate::engine::run_route::hosted_partition_shuffle_buffer as choose;
    const KIB: usize = 1024;
    const MIB: usize = 1024 * KIB;
    let output = root.join("partition-output");
    let mut job = Job {
        output: output.to_string_lossy().into_owned(),
        operations: vec![
            Operation::Partition {
                columns: vec![chopper_core::Column::Index(0)],
            },
            Operation::Shuffle {
                strategy: Shuffle::Uniform,
            },
        ],
        ..Job::default()
    };
    job.resources.memory_mb = 32.into();
    job.resources.workers = 1;
    job.resources.max_record_bytes = MIB;
    job.resources.temp_dir = Some(root.to_string_lossy().into_owned());
    let pool = Arc::new(MemoryPool::new(32 * MIB as u64));
    let mut ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let at_size = 96 * MIB as u64;
    ensure!(
        choose(&job, &ctx, at_size).is_none(),
        "Prepare was eligible"
    );
    ctx.auto_run = true;
    ensure!(
        choose(&job, &ctx, at_size - 1).is_none(),
        "small job was eligible"
    );
    job.limits.bytes = Some(64 * KIB as u64);
    ensure!(
        choose(&job, &ctx, at_size) == Some(64 * KIB),
        "chunk cap did not bound the buffer"
    );
    job.limits.bytes = None;

    job.operations.swap(0, 1);
    ensure!(
        choose(&job, &ctx, at_size) == Some(512 * KIB),
        "Uniform then Partition did not select buffered output"
    );
    job.operations[0] = Operation::Shuffle {
        strategy: Shuffle::FisherYates,
    };
    ensure!(
        choose(&job, &ctx, at_size).is_none(),
        "Fisher–Yates was eligible"
    );
    job.operations[0] = Operation::Shuffle {
        strategy: Shuffle::Auto,
    };

    let row = Row {
        id: 0,
        ordinal: 0,
        key: Vec::new(),
        fields: vec!["a".into(), "1".into()],
    };
    let emit = |writer: &mut output::PlanWriter<'_>| -> Result<()> {
        let mut group = writer.begin(Vec::new(), false);
        writer.row(&mut group, &row)?;
        writer.end(group)
    };
    // Hold a producer charge and an independent shared grant through emission.
    let mut producer = Reservation::new(&ctx);
    producer.resize(6 * MIB)?;
    let before_peer = pool.usage().reserved_bytes;
    let mut peer = Reservation::for_workspace(Arc::new(Workspace::shared(32 * MIB, pool.clone())));
    let required = (3 * MIB + 512 * KIB) as u64;
    for free in [required, required - 1, 400 * KIB as u64] {
        peer.resize((32 * MIB as u64 - before_peer - free) as usize)?;
        let held = pool.usage().reserved_bytes;
        ensure!(
            ctx.working_headroom() == free,
            "incorrect simulated headroom"
        );
        let buffer = choose(&job, &ctx, at_size);
        ensure!(
            buffer == (free == required).then_some(512 * KIB),
            "wrong late route"
        );
        if let Some(buffer) = buffer {
            let mut writer = output::PlanWriter::direct_grouped_buffered(&job, None, &ctx, buffer)?;
            emit(&mut writer)?;
            let (publication, files, bytes) = writer.finish_direct()?;
            ensure!((files, bytes) == (1, 4), "direct output counts changed");
            drop(publication);
        } else {
            if free < 512 * KIB as u64 {
                let mut forced =
                    output::PlanWriter::direct_grouped_buffered(&job, None, &ctx, 512 * KIB)?;
                let error = emit(&mut forced).unwrap_err();
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "expected typed first-writer denial: {error:#}"
                );
                drop(forced);
            }
            let mut writer = output::PlanWriter::new(&job, None, &ctx)?;
            emit(&mut writer)?;
            let plan = writer.finish()?;
            let mut data = Vec::new();
            plan.data.reader()?.read_to_end(&mut data)?;
            ensure!(
                data == b"a,1\n",
                "snapshot decline changed the encoded bytes"
            );
        }
        ensure!(
            pool.usage().reserved_bytes == held,
            "writer changed producer or peer grants"
        );
        ensure!(!output.exists(), "writer unexpectedly committed output");
        for entry in std::fs::read_dir(root)? {
            ensure!(
                !entry?
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".chopper-staging-"),
                "writer leaked staging"
            );
        }
    }
    Ok(())
}

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
    partition_shuffle_writer_boundary(dir.path())?;
    dir.close()?;
    Ok(
        json!({"contract":"direct-run-resource-contract-v1", "shared_denial_retry":true,
        "local_denial_retry":true, "final_clone_release":true, "failure_cleanup":true,
        "partition_shuffle_writer_boundary":true, "fixture_directory_removed":true}),
    )
}

#[cfg(test)]
#[test]
fn direct_publication_admission_and_cleanup() -> Result<()> {
    run().map(|_| ())
}
