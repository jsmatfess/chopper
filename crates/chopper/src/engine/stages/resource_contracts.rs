use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

fn stat(operation: usize) -> StageStats {
    StageStats {
        operation,
        input_groups: 3,
        output_groups: 5,
        smallest_group: 0,
        largest_group: 19,
        empty_groups: 1,
    }
}
fn build(memory: Reservation) -> Result<Stages> {
    let mut stages = Stages::new(64, memory)?;
    stages.extend((1..65).map(stat))?;
    Ok(stages)
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let required =
        64 * std::mem::size_of::<StageStats>() + Shared::<Vec<StageStats>>::controller_bytes();
    let canonical = serde_json::to_vec(&(1..65).map(stat).collect::<Vec<_>>())?;
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
                let error = result.err().context("stage edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "stage denial type changed"
                );
            } else {
                let mut stages = result?;
                ensure!(
                    stages.len() == 64
                        && stages.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&stages)? == canonical,
                    "stage bytes/schema changed"
                );
                ensure!(
                    stages.push(stat(65)).is_err()
                        && stages.len() == 64
                        && workspace.used() == required as u64,
                    "stage limit allowed growth"
                );
                let copy = stages.clone();
                ensure!(
                    std::ptr::eq(stages.as_ptr(), copy.as_ptr())
                        && workspace.used() == required as u64,
                    "stage clone copied allocation"
                );
                drop(stages);
                ensure!(
                    copy.len() == 64 && workspace.used() == required as u64,
                    "stage clone lost grant"
                );
                let decoded: Stages = serde_json::from_slice(&canonical)?;
                ensure!(
                    decoded.reserved_bytes() == 0 && serde_json::to_vec(&decoded)? == canonical,
                    "stage caller schema changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "stage edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = build(Reservation::for_workspace(workspace.clone()))?;
    let error = build(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing stages accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "stage competition lost owner"
    );
    drop(first);
    drop(build(Reservation::for_workspace(workspace.clone()))?);
    ensure!(workspace.used() == 0, "stage retry leaked");
    let mut building = Stages::new(64, Reservation::for_workspace(workspace.clone()))?;
    building.push(stat(1))?;
    let alias = building.clone();
    ensure!(
        building.push(stat(2)).is_err() && building.len() == 1 && alias.len() == 1,
        "shared stage mutation accepted"
    );
    drop(alias);
    building.push(stat(2))?;
    ensure!(
        building.len() == 2 && workspace.used() == required as u64,
        "unique stage append failed"
    );
    drop(building);
    let zero = Stages::new(0, Reservation::for_workspace(workspace.clone()))?;
    ensure!(
        zero.is_empty() && zero.capacity() == 0 && workspace.used() == 0,
        "zero stage allocation"
    );
    #[cfg(not(target_os = "wasi"))]
    {
        let stages = build(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = stages.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(stages);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent stage drop leaked"
        );
    }
    Ok(
        json!({"required_bytes":required,"local_shared_edges":6,"max_64_stages":true,"logical_limit_no_growth":true,"shared_clone_and_last_drop":true,"shared_mutation_rejected_then_unique_retry":true,"competing_owner_retry":true,"zero_operations_no_allocation":true,"caller_json_unchanged":true,"public_lifetimes":lifetimes()?}),
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
            panic!("stage denial read CSV")
        }
        fn next_compact_record_into_reserved(
            &mut self,
            _: &mut chopper_core::csv::CompactRecord,
            _: &mut impl FnMut(usize) -> Result<()>,
        ) -> Result<bool> {
            panic!("stage denial read compact CSV")
        }
    }
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let job = Job {
        random_seed: Some(String::new()),
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
    let required =
        64 * std::mem::size_of::<StageStats>() + Shared::<Vec<StageStats>>::controller_bytes();
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
    let error = result.err().context("pre-read stage denial accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && ctx.used() == 0
            && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "pre-read stage denial lost type or grant"
    );
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "pre-read stage context leaked"
    );
    for execute in [false, true] {
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let output = dir
            .path()
            .join(if execute { "published" } else { "discarded" });
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("stage-owner".into()),
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
            "public stage semantics/clone changed"
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
                Err(std::io::Error::other("stage serializer sentinel"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let before = pool.usage().reserved_bytes;
        ensure!(
            serde_json::to_writer(Reject, &copy.stages).is_err()
                && pool.usage().reserved_bytes == before,
            "stage serializer failure lost owner"
        );
        if execute {
            let result = prepared.execute()?;
            ensure!(
                result.stages.len() == 2
                    && std::ptr::eq(result.stages.as_ptr(), copy.stages.as_ptr()),
                "execution copied stage owner"
            );
            drop(result);
            ensure!(
                output.join("manifest.jsonl").is_file(),
                "stage publication missing"
            );
        } else {
            drop(prepared);
            ensure!(!output.try_exists()?, "discarded stages published");
        }
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained,
            "returned stage grant lost"
        );
        drop(copy);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "final stage clone retained grant"
        );
        drop(ctx);
        ensure!(pool.usage().reserved_bytes == 0, "stage context leaked");
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
                random_seed: Some("stage-cleanup".into()),
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
        let error = result.err().context("stage failure case prepared")?;
        ensure!(
            !output.try_exists()?
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&temporary)?.next().is_none(),
            "stage failed/cancelled scan leaked"
        );
        ensure!(
            if cancellation {
                observed.load(std::sync::atomic::Ordering::Relaxed)
                    && format!("{error:#}").contains("cancel")
            } else {
                format!("{error:#}").contains("unterminated quoted field")
            },
            "stage failure did not reach intended populated scan"
        );
    }
    dir.close()?;
    Ok(
        json!({"denial_before_csv_read":true,"malformed_and_populated_scan_cancellation_cleanup":true,"prepared_drop_and_execute":true,"serialization_failure":true,"exact_logical_stage_counts":true,"last_analysis_clone_release":true}),
    )
}
#[cfg(test)]
#[test]
fn stage_stats_admission_and_shared_lifetime() -> Result<()> {
    run().map(|_| ())
}
