//! A real pathname unlink error must stop a prepared job before publication.
use super::*;

#[cfg(any(windows, target_os = "linux", target_os = "wasi"))]
pub(super) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let fixture_directory = dir.path().to_owned();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("output");
    let temporary = dir.path().join("temporary");
    std::fs::create_dir(&temporary)?;
    std::fs::write(&input, b"id\n1\n")?;
    let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
    let prepared = prepare_with_memory_pool(
        Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("cleanup-resource-contract".into()),
            resources: chopper_core::Resources {
                memory_mb: 32.into(),
                workers: 1,
                max_record_bytes: 64 * 1024,
                temp_bytes: Some(8 * 1024 * 1024),
                temp_dir: Some(temporary.to_string_lossy().into_owned()),
                ..Default::default()
            },
            ..Job::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let ctx = prepared.ctx.clone();
    let workspace = ctx.dir.path().to_owned();
    let baseline = ctx.used();
    let failed_path = ctx.force_cleanup_error_for_test()?;
    ensure!(
        ctx.used() == baseline + 3,
        "failed unlink released orphan bytes"
    );
    ensure!(
        ctx.diagnostics()["temporary_cleanup_failures"] == 1,
        "failed unlink was not recorded"
    );
    let error = ctx
        .check()
        .err()
        .context("cleanup failure must stop context")?;
    let message = error.to_string();
    ensure!(
        message.contains("temporary cleanup failed")
            && message.contains(&failed_path.to_string_lossy().to_string()),
        "cleanup error lost its path: {error:#}"
    );
    let error = prepared
        .execute()
        .err()
        .context("cleanup failure must prevent publication")?;
    ensure!(
        error.to_string().contains("temporary cleanup failed"),
        "publication failed for an unrelated reason: {error:#}"
    );
    ensure!(
        !output.try_exists()?,
        "failed job published an output directory"
    );
    ensure!(
        ctx.used() == 3,
        "orphan bytes changed after prepared job drop"
    );
    let retained = pool.usage().reserved_bytes;
    let directory = ctx.directory_reserved_bytes();
    let paths = ctx.diagnostics()["temporary_path_reserved_bytes"]
        .as_u64()
        .context("missing file path charge")?;
    ensure!(
        paths > 0 && directory > 0,
        "failed path/directory lost retained owners"
    );
    ensure!(
        retained == paths + directory && ctx.diagnostics()["workspace_reserved_bytes"] == retained,
        "unexpected owner remained after prepared job drop"
    );
    ensure!(
        failed_path.is_dir(),
        "fault directory was unexpectedly removed"
    );
    ensure!(
        std::fs::metadata(failed_path.with_extension("retained"))?.len() == 3,
        "orphan data was not retained"
    );
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "cleanup context leaked capacity"
    );
    ensure!(
        !workspace.try_exists()?,
        "job workspace survived final context drop"
    );
    ensure!(
        std::fs::read_dir(&temporary)?.next().is_none(),
        "temporary workspace leaked"
    );
    for entry in std::fs::read_dir(dir.path())? {
        let name = entry?.file_name();
        ensure!(
            name == "input.csv" || name == "temporary",
            "publication staging leaked"
        );
    }
    dir.close()?;
    ensure!(
        !fixture_directory.try_exists()?,
        "cleanup fixture directory leaked"
    );
    Ok(json!({
        "contract": "temporary-unlink-publication-resource-contract-v1",
        "supported": true, "actual_unlink_failures": 1,
        "orphan_bytes_after_prepared_drop": 3,
        "path_reserved_bytes_until_context_drop": paths,
        "directory_reserved_bytes_until_context_drop": directory,
        "workspace_reserved_bytes_until_context_drop": retained,
        "path_rich_error": true, "publication_rejected": true,
        "output_directory_absent": true, "staging_removed": true,
        "orphan_data_retained_until_context_drop": true,
        "workspace_removed_on_context_drop": true,
        "fixture_directory_removed": true, "final_reserved_bytes": 0,
    }))
}

#[cfg(not(any(windows, target_os = "linux", target_os = "wasi")))]
pub(super) fn run() -> Result<serde_json::Value> {
    Ok(json!({
        "contract": "temporary-unlink-publication-resource-contract-v1",
        "supported": false,
        "reason": "No validated pathname-failure fixture for this target",
    }))
}

#[cfg(all(test, any(windows, target_os = "linux")))]
mod tests {
    #[test]
    fn actual_unlink_failure_blocks_publication_and_retains_orphan_owner() -> anyhow::Result<()> {
        super::run()?;
        Ok(())
    }
}
