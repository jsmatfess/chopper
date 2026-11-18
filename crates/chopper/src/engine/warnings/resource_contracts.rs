use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
const VALUES: [&str; 3] = ["quoted,\"\n\u{754c}", "", "tail"];
fn fixture(memory: Reservation) -> Result<Warnings> {
    let mut builder = Builder::new(memory);
    for value in VALUES {
        builder.copy(value)?;
    }
    builder.finish()
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let root = MAX_WARNINGS * std::mem::size_of::<String>();
    let required = root
        + VALUES.iter().map(|s| s.len()).sum::<usize>()
        + Shared::<Vec<String>>::controller_bytes();
    let canonical = serde_json::to_vec(&VALUES)?;

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
            let result = fixture(Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = result.err().context("notes edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "notes denial lost type"
                );
            } else {
                let owner = result?;
                ensure!(
                    owner.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&owner)? == canonical,
                    "notes bytes/schema changed"
                );
                let copy = owner.clone();
                ensure!(
                    std::ptr::eq(copy.as_ptr(), owner.as_ptr())
                        && workspace.used() == required as u64,
                    "warning clone copied payload/grant"
                );
                drop(owner);
                ensure!(
                    workspace.used() == required as u64 && serde_json::to_vec(&copy)? == canonical,
                    "notes clone lost grant"
                );
                let decoded: Warnings = serde_json::from_slice(&canonical)?;
                ensure!(
                    decoded == copy && decoded.reserved_bytes() == 0,
                    "caller notes schema changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "notes edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = fixture(Reservation::for_workspace(workspace.clone()))?;
    let error = fixture(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing notes accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "notes competition changed live owner"
    );
    drop(first);
    drop(fixture(Reservation::for_workspace(workspace.clone()))?);
    ensure!(workspace.used() == 0, "notes retry leaked");
    #[cfg(not(target_os = "wasi"))]
    {
        let owner = fixture(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = owner.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(owner);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent notes last drop leaked"
        );
    }

    let workspace = Arc::new(Workspace::new(8192));
    let empty = Builder::new(Reservation::for_workspace(workspace.clone())).finish()?;
    ensure!(
        empty.is_empty() && empty.capacity() == 0 && workspace.used() == 0,
        "empty warnings allocated"
    );
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    for _ in 0..MAX_WARNINGS {
        builder.copy("w")?;
    }
    let before = workspace.used();
    ensure!(
        builder.copy("ninth").is_err()
            && builder.values.len() == MAX_WARNINGS
            && workspace.used() == before,
        "warning limit grew or changed builder"
    );
    drop(builder);
    ensure!(workspace.used() == 0, "warning bound leaked");
    let pool = Arc::new(MemoryPool::new(8192));
    let workspace = Arc::new(Workspace::shared(8192, pool.clone()));
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    builder.copy("ok")?;
    let held = 8192 - workspace.used() - 1;
    pool.acquire(held)?;
    let error = builder
        .copy("abc")
        .err()
        .context("partial warning copy admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && builder.values == ["ok"]
            && workspace.used() == (root + 2) as u64,
        "warning copy denial changed prior data/grant"
    );
    pool.release(held);
    builder.copy("abc")?;
    let result = builder.finish()?;
    ensure!(
        result[..] == ["ok", "abc"],
        "warning partial-copy retry changed result"
    );
    drop(result);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "warning partial-copy retry leaked"
    );
    Ok(
        json!({"required_bytes":required,"local_shared_edges":6,"shared_clone_and_last_drop":true,"competing_owner_retry":true,"caller_json_equal":true,"empty_no_allocation":true,"eighth_allowed_ninth_rejected":true,"partial_copy_denial_preserves_data_and_retry":true,"conditions":conditions()?,"public_lifetimes":lifetimes()?}),
    )
}

fn conditions() -> Result<serde_json::Value> {
    // Only inspect warning conditions here: the combined synthetic operations
    // need not form a valid executable job. Public jobs are checked below.
    let job = Job {
        operations: vec![
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
            },
            Operation::Interleaved { files: 1 },
            Operation::AssignProbabilistic {
                groups: vec![],
                strata: vec![],
            },
        ],
        limits: Limits {
            rows: Some(10),
            compressed_bytes: Some(1000),
            ..Default::default()
        },
        ..Default::default()
    };
    let mut analysis: Analysis = serde_json::from_value(
        json!({"algorithm_version":ALGORITHM_VERSION,"seed":"seed","rows":0,"columns":0,"header":null,"preview":[],"logical_digest":"digest","groups":0,"output_files":u64::MAX,"output_csv_bytes":0,"largest_record_bytes":0,"temp_bytes":0,"peak_temp_bytes":0,"memory_budget_bytes":0,"workers":1,"analysis_seconds":0.0,"stages":[{"operation":1,"input_groups":1,"output_groups":1,"smallest_group":0,"largest_group":0,"empty_groups":1}],"warnings":[],"accuracy":"exact"}),
    )?;
    let workspace = Arc::new(Workspace::new(8192));
    let result = build(
        &job,
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let expected=["Flexible full shuffles retain this prepared result for confirmation/export. A recorded seed alone does not guarantee replay across resource plans, runtimes or builds.","Some named allocation groups contain no data rows; their outputs contain only the configured header/BOM.","This job creates 18446744073709551615 CSV files/members.","Compressed target is advisory: boundaries conservatively assume no compression plus 5% and 128 bytes overhead. Actual compressed size may exceed target. For ZIP this targets each member, not the whole archive.","Balanced groups retain exact counts through shuffling. Hard caps that require extra chunks are rejected.","Probabilistic allocation uses target percentages, not exact quotas. Small strata may receive no rows in a destination; displayed counts are the actual prepared results.","Interleaved splitting distributes consecutive rows across parts. Concatenating the files does not restore input order.","Fisher–Yates v1 is a uniform in-memory shuffle with a different seeded order from random-key v1. Every group must fit the resident shuffle budget."];
    let expected = &expected[1..];
    ensure!(
        result.len() == expected.len()
            && result
                .iter()
                .map(String::as_str)
                .eq(expected.iter().copied()),
        "all warning text/order or u64 formatting changed"
    );
    drop(result);
    analysis.output_files = 10_000;
    analysis.stages = Stages::default();
    let empty = build(
        &Job::default(),
        &analysis,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        empty.is_empty() && workspace.used() == 0,
        "inactive warning conditions allocated"
    );
    Ok(
        json!({"all_eight_conditions_in_original_order":true,"max_u64_message_exact":true,"inactive_conditions_no_allocation":true}),
    )
}

fn lifetimes() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n")?;
    let job = |output: &std::path::Path| Job {
        input: input.to_string_lossy().into_owned(),
        output: output.to_string_lossy().into_owned(),
        random_seed: Some("notes-owner".into()),
        operations: vec![Operation::Interleaved { files: 1 }],
        limits: Limits {
            rows: Some(10),
            ..Default::default()
        },
        resources: Resources {
            temp_dir: Some(dir.path().to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    for execute in [false, true] {
        let output = dir
            .path()
            .join(if execute { "published" } else { "discarded" });
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let prepared = prepare_with_memory_pool(
            job(&output),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let ctx = prepared.ctx.clone();
        let copy = prepared.analysis.clone();
        ensure!(
            copy.warnings.len() == 2
                && copy.timings.len() == 3
                && copy.timings.values().all(|n| n.is_finite() && *n >= 0.0)
                && std::ptr::eq(copy.warnings.as_ptr(), prepared.analysis.warnings.as_ptr())
                && std::ptr::eq(
                    copy.timings
                        .get_key_value("final_serialization")
                        .unwrap()
                        .0
                        .as_ptr(),
                    prepared
                        .analysis
                        .timings
                        .get_key_value("final_serialization")
                        .unwrap()
                        .0
                        .as_ptr()
                ),
            "public warning/timing schema/clone changed"
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
                Err(std::io::Error::other("notes serializer sentinel"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let before = pool.usage().reserved_bytes;
        ensure!(
            serde_json::to_writer(Reject, &copy.warnings).is_err()
                && serde_json::to_writer(Reject, &copy.timings).is_err()
                && pool.usage().reserved_bytes == before,
            "notes serializer failure lost owner"
        );
        if execute {
            let result = prepared.execute()?;
            ensure!(
                result.warnings == copy.warnings && result.timings == copy.timings,
                "returned notes changed"
            );
            drop(result);
            let mut csv = None;
            for entry in std::fs::read_dir(&output)? {
                let path = entry?.path();
                if path.extension() == Some(std::ffi::OsStr::new("csv")) {
                    ensure!(csv.is_none(), "notes publication has extra CSV files");
                    csv = Some(path);
                }
            }
            ensure!(
                std::fs::read(csv.context("notes output CSV missing")?)?
                    == b"id,key\n1,a\n2,b\n3,a\n",
                "notes publication CSV changed"
            );
        } else {
            drop(prepared);
            ensure!(!output.try_exists()?, "discarded notes published");
        }
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained,
            "Analysis lost live notes grant"
        );
        let warnings = copy.warnings.clone();
        let timings = copy.timings.clone();
        let warning_bytes = warnings.reserved_bytes();
        let timing_bytes = timings.reserved_bytes();
        drop(copy);
        ensure!(
            pool.usage().reserved_bytes
                == ctx.directory_reserved_bytes() + warning_bytes + timing_bytes,
            "independent notes lost owner"
        );
        drop(warnings);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + timing_bytes,
            "warning last drop leaked"
        );
        drop(timings);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "timing last drop leaked"
        );
        drop(ctx);
        ensure!(pool.usage().reserved_bytes == 0, "notes context leaked");
    }
    let output = dir.path().join("cancelled");
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let prepared =
        prepare_with_memory_pool(job(&output), cancel.clone(), Arc::new(|_| {}), pool.clone())?;
    let ctx = prepared.ctx.clone();
    ensure!(
        prepared.analysis.warnings.reserved_bytes() > 0
            && prepared.analysis.timings.reserved_bytes() > 0,
        "cancel control lacks live notes"
    );
    cancel.store(true, std::sync::atomic::Ordering::Relaxed);
    let error = prepared
        .execute()
        .err()
        .context("cancelled notes execution succeeded")?;
    ensure!(
        error.to_string().contains("cancel")
            && !output.try_exists()?
            && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "ready cancellation leaked notes/output"
    );
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "cancelled notes context leaked"
    );
    dir.close()?;
    Ok(
        json!({"analysis_and_independent_payload_clones":true,"prepared_drop_and_execute":true,"serialization_failures":true,"exact_csv_publication":true,"ready_snapshot_cancellation_cleanup":true,"last_warning_then_timing_release":true,"final_reserved_bytes":0}),
    )
}
#[cfg(test)]
#[test]
fn analysis_warning_admission_and_lifetime() -> Result<()> {
    println!("CHOPPER_WARNING_CONTRACT {}", run()?);
    Ok(())
}
