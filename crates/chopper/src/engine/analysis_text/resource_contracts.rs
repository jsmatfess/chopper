use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
const TEXT: &str = "seed,\"\n\u{754c}";
fn build(memory: Reservation) -> Result<AnalysisText> {
    AnalysisText::copy(TEXT, memory)
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let required = TEXT.len() + Shared::<String>::controller_bytes();
    let canonical = serde_json::to_vec(TEXT)?;
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
                let error = result.err().context("text edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "text denial type changed"
                );
            } else {
                let text = result?;
                ensure!(
                    text.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&text)? == canonical,
                    "text bytes/schema changed"
                );
                let copy = text.clone();
                ensure!(
                    std::ptr::eq(copy.as_ptr(), text.as_ptr())
                        && workspace.used() == required as u64,
                    "text clone copied storage/grant"
                );
                drop(text);
                ensure!(
                    copy.as_ref() == TEXT && workspace.used() == required as u64,
                    "text clone lost grant"
                );
                let decoded: AnalysisText = serde_json::from_slice(&canonical)?;
                ensure!(
                    decoded == copy && decoded.reserved_bytes() == 0,
                    "caller text schema changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "text edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = build(Reservation::for_workspace(workspace.clone()))?;
    let error = build(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing text accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "text competition lost owner"
    );
    drop(first);
    drop(build(Reservation::for_workspace(workspace.clone()))?);
    let empty = AnalysisText::copy("", Reservation::for_workspace(workspace.clone()))?;
    ensure!(
        empty.is_empty() && empty.capacity() == 0 && workspace.used() == 0,
        "empty text allocated"
    );
    #[cfg(not(target_os = "wasi"))]
    {
        let text = build(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = text.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(text);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent text final drop leaked"
        );
    }
    Ok(
        json!({"required_bytes":required,"local_shared_edges":6,"json_text_unchanged":true,"shared_clone_and_last_drop":true,"competing_owner_retry":true,"empty_no_allocation":true,"public_lifetimes":lifetimes()?}),
    )
}

fn lifetimes() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n")?;
    // Deny the shared controller after vector admission, before even a header
    // read. Any accidental parser invocation fails this contract immediately.
    struct NeverRead;
    impl records::Records for NeverRead {
        fn record_number(&self) -> u64 {
            0
        }
        fn scratch_capacity(&self) -> usize {
            0
        }
        fn next_record_into_reserved(
            &mut self,
            _: &mut Vec<String>,
            _: &mut impl FnMut(usize) -> Result<()>,
        ) -> Result<bool> {
            panic!("text denial read CSV")
        }
        fn next_compact_record_into_reserved(
            &mut self,
            _: &mut chopper_core::csv::CompactRecord,
            _: &mut impl FnMut(usize) -> Result<()>,
        ) -> Result<bool> {
            panic!("text denial read compact CSV")
        }
    }
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let job = Job {
        random_seed: Some("s".repeat(4096)),
        operations: (0..64)
            .map(|_| Operation::Shuffle {
                strategy: Shuffle::Uniform,
            })
            .collect(),
        resources: Resources {
            temp_dir: Some(dir.path().to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let required = 4096 + Shared::<String>::controller_bytes();
    let held = 64 * 1024 * 1024 - ctx.directory_reserved_bytes() - (required as u64 - 1);
    pool.acquire(held)?;
    let result = ingest_records(
        Intake::preadmitted_parser(NeverRead, Reservation::new(&ctx), job.input_csv.headers),
        &job,
        &ctx,
        false,
        false,
        false,
    );
    pool.release(held);
    let error = result.err().context("pre-read text denial accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && ctx.used() == 0
            && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "pre-read text denial lost type or grant"
    );
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "pre-read text context leaked"
    );
    for execute in [false, true] {
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let output = dir
            .path()
            .join(if execute { "published" } else { "discarded" });
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("text-owner".into()),
            operations: vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
            ],
            resources: Resources {
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Default::default()
            },
            ..Default::default()
        };
        let prepared = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let ctx = prepared.ctx.clone();
        let copy = prepared.analysis.clone();
        ensure!(
            copy.stages.len() == 2
                && copy.stages[0].operation == 1
                && copy.stages[1].operation == 2
                && copy.stages[0].output_groups == 2
                && copy.stages[1].output_groups == 2
                && std::ptr::eq(copy.stages.as_ptr(), prepared.analysis.stages.as_ptr()),
            "public text semantics/clone changed"
        );
        ensure!(
            copy.seed.as_ref() == "text-owner"
                && copy.logical_digest.len() == 64
                && copy.accuracy.contains("complete strict validation")
                && std::ptr::eq(copy.seed.as_ptr(), prepared.analysis.seed.as_ptr())
                && std::ptr::eq(
                    copy.logical_digest.as_ptr(),
                    prepared.analysis.logical_digest.as_ptr()
                )
                && std::ptr::eq(copy.accuracy.as_ptr(), prepared.analysis.accuracy.as_ptr()),
            "public text values/identity changed"
        );
        let retained = copy.warnings.reserved_bytes()
            + copy.timings.reserved_bytes()
            + copy.diagnostics.reserved_bytes()
            + copy.text_reserved_bytes()
            + copy.stages.reserved_bytes()
            + copy.preview.reserved_bytes()
            + copy.column_values.reserved_bytes()
            + copy.header.as_ref().map_or(0, Header::reserved_bytes);
        struct Reject;
        impl std::io::Write for Reject {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("text serializer sentinel"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let before = pool.usage().reserved_bytes;
        ensure!(
            serde_json::to_writer(Reject, &copy.logical_digest).is_err()
                && pool.usage().reserved_bytes == before,
            "text serializer failure lost owner"
        );
        if execute {
            let result = prepared.execute()?;
            ensure!(
                result.stages.len() == 2
                    && std::ptr::eq(result.stages.as_ptr(), copy.stages.as_ptr()),
                "execution copied text owner"
            );
            drop(result);
            ensure!(
                output.join("manifest.jsonl").is_file(),
                "text publication missing"
            );
        } else {
            drop(prepared);
            ensure!(!output.try_exists()?, "discarded texts published");
        }
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained,
            "returned text grant lost"
        );
        drop(copy);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "final text clone retained grant"
        );
        drop(ctx);
        ensure!(pool.usage().reserved_bytes == 0, "text context leaked");
    }
    let temporary = dir.path().join("failure-temporary");
    std::fs::create_dir(&temporary)?;
    for cancellation in [false, true] {
        let text = if cancellation {
            format!("id,key\n{}", "1,a\n".repeat(65_537))
        } else {
            "id,key\n1,a\n2,b\n3,\"unterminated".into()
        };
        std::fs::write(&input, text)?;
        let output = dir.path().join("failed-output");
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let observed = Arc::new(AtomicBool::new(false));
        let progress_seen = observed.clone();
        let result = prepare_with_memory_pool(
            Job {
                input: input.to_string_lossy().into_owned(),
                output: output.to_string_lossy().into_owned(),
                random_seed: Some("text-cleanup".into()),
                operations: vec![Operation::Partition {
                    columns: vec![Column::Index(1)],
                }],
                resources: Resources {
                    temp_dir: Some(temporary.to_string_lossy().into_owned()),
                    memory_mb: 32.into(),
                    max_record_bytes: 1024 * 1024,
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
                    progress_seen.store(true, std::sync::atomic::Ordering::Relaxed);
                    signal.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }),
            pool.clone(),
        );
        let error = result.err().context("text failure case prepared")?;
        ensure!(
            !output.try_exists()?
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&temporary)?.next().is_none(),
            "text failed/cancelled scan leaked"
        );
        ensure!(
            if cancellation {
                observed.load(std::sync::atomic::Ordering::Relaxed)
                    && format!("{error:#}").contains("cancel")
            } else {
                format!("{error:#}").contains("unterminated quoted field")
            },
            "text failure did not reach intended populated scan"
        );
    }
    dir.close()?;
    Ok(
        json!({"denial_before_csv_read":true,"malformed_and_populated_scan_cancellation_cleanup":true,"prepared_drop_and_execute":true,"serialization_failure":true,"exact_logical_stage_counts":true,"all_text_values_and_clone_identity":true,"last_analysis_clone_release":true}),
    )
}

#[cfg(test)]
#[test]
fn analysis_text_admission_and_shared_lifetime() -> Result<()> {
    run().map(|_| ())
}
