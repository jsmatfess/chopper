use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

fn fields() -> Vec<String> {
    vec!["quoted,\"\n\u{754c}".into(), String::new(), "third".into()]
}
fn build(memory: Reservation) -> Result<Preview> {
    let mut builder = Builder::new(memory);
    for _ in 0..2 {
        let fields = fields();
        let bytes = fields.iter().map(String::len).sum();
        builder.consider(FieldViews::owned(&fields), bytes)?;
    }
    builder.finish()
}
fn expected() -> usize {
    8 * std::mem::size_of::<Vec<String>>()
        + 2 * (3 * std::mem::size_of::<String>() + fields().iter().map(String::len).sum::<usize>())
        + Shared::<Vec<Vec<String>>>::controller_bytes()
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let required = expected();
    let canonical = serde_json::to_vec(&vec![fields(), fields()])?;
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(required + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = build(Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = result.err().context("preview edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "preview denial lost type"
                );
            } else {
                let preview = result?;
                ensure!(
                    preview.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&preview)? == canonical,
                    "preview capacity or serialization changed"
                );
                let clone = preview.clone();
                ensure!(
                    std::ptr::eq(preview.as_ptr(), clone.as_ptr())
                        && workspace.used() == required as u64,
                    "preview clone copied admitted rows"
                );
                drop(preview);
                ensure!(
                    clone.len() == 2 && workspace.used() == required as u64,
                    "preview clone lost live grant"
                );
                drop(clone);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "preview edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = build(Reservation::for_workspace(workspace.clone()))?;
    let error = build(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing preview accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "preview competition changed live owner"
    );
    drop(first);
    drop(build(Reservation::for_workspace(workspace.clone()))?);
    ensure!(pool.usage().reserved_bytes == 0, "preview retry leaked");

    #[cfg(not(target_os = "wasi"))]
    {
        let preview = build(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let clone = preview.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(clone);
                });
            }
            drop(preview);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent last preview drop leaked"
        );
    }

    // A zero-payload CSV row still needs a String descriptor for every field.
    let wide = vec![String::new(); 100_001];
    let root = 8 * std::mem::size_of::<Vec<String>>();
    let descriptors = wide.len() * std::mem::size_of::<String>();
    let workspace = Arc::new(Workspace::new(root + descriptors - 1));
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let error = builder
        .consider(FieldViews::owned(&wide), 0)
        .err()
        .context("empty-field descriptor edge accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ) && builder.values.is_empty()
            && workspace.used() == root as u64,
        "empty-field denial allocated row or lost root owner"
    );
    drop(builder);
    ensure!(workspace.used() == 0, "descriptor denial leaked");

    let workspace = Arc::new(Workspace::new(root + 2 * std::mem::size_of::<String>() + 7));
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let partial = vec!["abc".into(), "12345".into()];
    ensure!(
        builder.consider(FieldViews::owned(&partial), 8).is_err()
            && builder.values.is_empty()
            && workspace.used() == root as u64,
        "partial preview copy leaked or published row"
    );
    drop(builder);
    ensure!(workspace.used() == 0, "partial preview drop leaked");

    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let oversized = vec!["x".repeat(32 * 1024 + 1)];
    builder.consider(FieldViews::owned(&oversized), oversized[0].len())?;
    ensure!(
        builder.values.is_empty() && workspace.used() == 0,
        "skipped preview row allocated"
    );
    for _ in 0..10 {
        let fields = fields();
        builder.consider(
            FieldViews::owned(&fields),
            fields.iter().map(String::len).sum(),
        )?;
    }
    let preview = builder.finish()?;
    ensure!(preview.len() == 8, "preview row selection changed");
    let decoded: Preview = serde_json::from_slice(&serde_json::to_vec(&preview)?)?;
    ensure!(
        decoded == preview && decoded.reserved_bytes() == 0,
        "caller deserialization schema changed"
    );
    drop(decoded);
    drop(preview);
    ensure!(workspace.used() == 0, "selection preview leaked");
    let empty = Builder::new(Reservation::for_workspace(workspace.clone())).finish()?;
    ensure!(
        empty.is_empty() && empty.reserved_bytes() == 0 && workspace.used() == 0,
        "empty preview allocated"
    );
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let boundary = vec!["x".repeat(32 * 1024)];
    builder.consider(FieldViews::owned(&boundary), 32 * 1024)?;
    let skipped = fields();
    builder.consider(
        FieldViews::owned(&skipped),
        skipped.iter().map(String::len).sum(),
    )?;
    let empty_field = vec![String::new()];
    builder.consider(FieldViews::owned(&empty_field), 0)?;
    let boundary = builder.finish()?;
    ensure!(
        boundary.len() == 2 && boundary[0][0].len() == 32 * 1024 && boundary[1][0].is_empty(),
        "exact preview payload boundary changed"
    );
    drop(boundary);
    ensure!(workspace.used() == 0, "payload boundary leaked");

    Ok(
        json!({"contract":"analysis-preview-owner-v1","retained_fixture_bytes":required,"local_shared_edges":6,"clone_shares_rows_and_grant":true,"native_concurrent_last_drop":cfg!(not(target_os="wasi")),"competing_owner_release_retry":true,"empty_field_descriptors_admitted_before_copy":true,"partial_copy_denial_preserves_builder":true,"selection_limits_preserved":true,"caller_deserialization_equal":true,"empty_preview_no_allocation":true,"public_preparation":preparation()?,"final_reserved_bytes":0}),
    )
}

fn preparation() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,text\n1,first\n2,last\n")?;
    let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
    let prepared = prepare_with_memory_pool(
        Job {
            input: input.to_string_lossy().into_owned(),
            output: dir.path().join("output").to_string_lossy().into_owned(),
            random_seed: Some("preview-owner".into()),
            resources: Resources {
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let ctx = prepared.ctx.clone();
    let copied = prepared.analysis.clone();
    let retained = copied.preview.reserved_bytes();
    let retained_text = copied.text_reserved_bytes();
    let retained_diagnostics = copied.diagnostics.reserved_bytes();
    let retained_notes = copied.warnings.reserved_bytes() + copied.timings.reserved_bytes();
    let retained_header = copied.header.as_ref().map_or(0, Header::reserved_bytes);
    ensure!(
        retained > 0 && std::ptr::eq(copied.preview.as_ptr(), prepared.analysis.preview.as_ptr()),
        "Analysis clone did not share preview"
    );
    struct Reject;
    impl std::io::Write for Reject {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("preview serialization sentinel"))
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let before = pool.usage().reserved_bytes;
    ensure!(
        serde_json::to_writer(Reject, &copied.preview).is_err()
            && pool.usage().reserved_bytes == before,
        "serialization failure released live preview"
    );
    let analysis = prepared.execute()?;
    ensure!(
        ctx.diagnostics()["workspace_reserved_bytes"]
            == ctx.directory_reserved_bytes()
                + retained
                + retained_header
                + retained_text
                + retained_notes
                + retained_diagnostics
            && std::fs::read(dir.path().join("output/part-00000001.csv"))?
                == b"id,text\n1,first\n2,last\n",
        "execution preview ownership or CSV changed"
    );
    drop(analysis);
    ensure!(
        pool.usage().reserved_bytes
            == ctx.directory_reserved_bytes()
                + retained
                + retained_header
                + retained_text
                + retained_notes
                + retained_diagnostics,
        "returned Analysis drop released sibling preview"
    );
    drop(copied);
    ensure!(
        pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "last Analysis clone retained preview"
    );
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "public preview cleanup leaked"
    );
    let temporary = dir.path().join("failure-temporary");
    std::fs::create_dir(&temporary)?;
    for cancellation in [false, true] {
        let text = if cancellation {
            format!("id,text\n{}", "1,first\n".repeat(65_537))
        } else {
            "id,text\n1,first\n2,last\n3,\"unterminated".into()
        };
        std::fs::write(&input, text)?;
        let cancel = Arc::new(AtomicBool::new(false));
        let observed = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let progress_observed = observed.clone();
        let output = dir.path().join("failed-output");
        let error = prepare_with_memory_pool(
            Job {
                input: input.to_string_lossy().into_owned(),
                output: output.to_string_lossy().into_owned(),
                random_seed: Some("preview-failure".into()),
                resources: Resources {
                    temp_dir: Some(temporary.to_string_lossy().into_owned()),
                    ..Resources::default()
                },
                ..Job::default()
            },
            cancel,
            Arc::new(move |progress| {
                if cancellation
                    && progress.phase == "Reading and validating CSV"
                    && progress.rows >= 65_536
                {
                    progress_observed.store(true, std::sync::atomic::Ordering::Relaxed);
                    signal.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }),
            pool.clone(),
        )
        .err()
        .context("preview failure case prepared")?;
        ensure!(
            !output.try_exists()?
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&temporary)?.next().is_none(),
            "failed/cancelled ingestion retained preview or workspace"
        );
        if !cancellation {
            ensure!(
                format!("{error:#}").contains("unterminated quoted field"),
                "malformed preview case failed before parser rejection"
            );
        }
        if cancellation {
            ensure!(
                observed.load(std::sync::atomic::Ordering::Relaxed)
                    && format!("{error:#}").contains("cancel"),
                "preview cancellation did not reach populated scan"
            );
        }
    }
    dir.close()?;
    Ok(
        json!({"analysis_clone_shares_preview":true,"serialization_failure_retains_owner":true,"execute_csv_parity":true,"retained_after_execute_and_sibling_drop":true,"last_clone_release":true,"malformed_and_populated_scan_cancellation_cleanup":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

#[test]
fn analysis_preview_capacity_and_shared_lifetime() {
    println!("{}", run().unwrap());
}
