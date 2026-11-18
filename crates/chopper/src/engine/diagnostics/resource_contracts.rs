use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
// These fixtures are caller-owned Serialize input. Admission covers the new
// snapshot, not the pre-existing input tree used by the contract harness.
fn source() -> serde_json::Value {
    json!({"kind":"quoted,\"\n\u{754c}","items":["first","",{"tail":"\u{754c}"}],"nested":{"flag":true,"nullable":null}})
}
fn fixture(memory: Reservation) -> Result<Diagnostics> {
    let source = source();
    Diagnostics::build(memory, |admitted| attempt(&source, admitted))
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let source = source();
    let canonical = serde_json::to_vec(&source)?;
    let allowance = source.serialize(Estimator)?.bytes;
    let retained = source.json_capacity()? + Shared::<serde_json::Value>::controller_bytes();
    let required = allowance.max(retained);
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
                let error = result.err().context("diagnostic edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "diagnostic edge lost denial type"
                );
            } else {
                let owner = result?;
                ensure!(
                    owner.reserved_bytes() == retained as u64
                        && workspace.used() == retained as u64
                        && workspace.peak() == required as u64
                        && serde_json::to_vec(&owner)? == canonical,
                    "diagnostic capacity/schema changed"
                );
                let copy = owner.clone();
                ensure!(
                    std::ptr::eq(&*owner, &*copy) && workspace.used() == retained as u64,
                    "diagnostic clone copied tree/grant"
                );
                drop(owner);
                ensure!(
                    serde_json::to_vec(&copy)? == canonical && workspace.used() == retained as u64,
                    "diagnostic copy lost grant"
                );
                let decoded: Diagnostics = serde_json::from_slice(&canonical)?;
                ensure!(
                    decoded == copy && decoded.reserved_bytes() == 0,
                    "caller diagnostic schema changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "diagnostic edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((retained + required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(retained + required, pool.clone()));
    let owner = fixture(Reservation::for_workspace(workspace.clone()))?;
    let error = fixture(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing diagnostics admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == retained as u64,
        "diagnostic competition lost live grant"
    );
    drop(owner);
    drop(fixture(Reservation::for_workspace(workspace.clone()))?);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "diagnostic retry leaked"
    );
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
            assert_eq!(workspace.used(), retained as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent diagnostic final drop leaked"
        );
    }
    Ok(
        json!({"construction_peak_bytes":required,"retained_bytes":retained,"local_shared_edge_checks":6,"shared_clone_and_last_drop":true,"caller_json_equal":true,"competing_owner_retry":true,"construction":construction()?,"source_parity":source_parity()?,"public_lifetimes":lifetimes()?}),
    )
}
fn construction() -> Result<serde_json::Value> {
    let source = json!({"text":"controller edge"});
    let payload = source.serialize(Estimator)?.bytes;
    let required = payload + Shared::<serde_json::Value>::controller_bytes();
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
            let mut built = false;
            let result =
                Diagnostics::build(Reservation::for_workspace(workspace.clone()), |admitted| {
                    let result = attempt(&source, admitted)?;
                    if matches!(result, Attempt::Built(_)) {
                        built = true;
                    }
                    Ok(result)
                });
            ensure!(
                built,
                "controller edge did not reach admitted tree construction"
            );
            if limit < required {
                let error = result
                    .err()
                    .context("diagnostic controller edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "controller denial lost type"
                );
            } else {
                let owner = result?;
                ensure!(
                    owner.reserved_bytes() == required as u64,
                    "controller grant changed"
                );
                drop(owner);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "controller denial/release leaked tree"
            );
        }
    }
    let small = json!({"value":"x"});
    let large = json!({"value":"x".repeat(4096)});
    let budget =
        large.serialize(Estimator)?.bytes + Shared::<serde_json::Value>::controller_bytes();
    let workspace = Arc::new(Workspace::new(budget));
    let mut visits = 0;
    let owner = Diagnostics::build(Reservation::for_workspace(workspace.clone()), |admitted| {
        visits += 1;
        attempt(if visits == 1 { &small } else { &large }, admitted)
    })?;
    ensure!(
        visits == 3 && owner == large,
        "changed source bypassed fresh preflight"
    );
    drop(owner);
    ensure!(workspace.used() == 0, "changed source retry leaked");
    let workspace = Arc::new(Workspace::new(
        small.serialize(Estimator)?.bytes + Shared::<serde_json::Value>::controller_bytes(),
    ));
    let mut visits = 0;
    let error = Diagnostics::build(Reservation::for_workspace(workspace.clone()), |admitted| {
        visits += 1;
        attempt(if visits == 1 { &small } else { &large }, admitted)
    })
    .err()
    .context("changed source denial accepted")?;
    ensure!(
        visits == 2
            && matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            )
            && workspace.used() == 0,
        "changed source denial leaked or built without admission"
    );
    struct Unsupported;
    impl std::fmt::Display for Unsupported {
        fn fmt(&self, _: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            panic!("unsupported display allocated during preflight")
        }
    }
    impl Serialize for Unsupported {
        fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
            s.collect_str(self)
        }
    }
    let error = Diagnostics::build(Reservation::for_workspace(workspace.clone()), |admitted| {
        attempt(&Unsupported, admitted)
    })
    .err()
    .context("unsupported source accepted")?;
    ensure!(
        error.to_string().contains("unsupported") && workspace.used() == 0,
        "unsupported source allocated/retained grant"
    );
    ensure!(
        Diagnostics::default().is_null() && Diagnostics::default().reserved_bytes() == 0,
        "default diagnostics allocated"
    );
    Ok(
        json!({"controller_edge_checks":6,"denied_after_tree_construction_cleanup":true,"source_growth_repreflight_and_retry":true,"source_growth_denial_cleanup":true,"unsupported_display_rejected_before_formatting":true,"absent_default_no_allocation":true}),
    )
}
fn source_parity() -> Result<serde_json::Value> {
    let resources = Resources::default();
    #[cfg(target_os = "wasi")]
    let resources = Resources {
        temp_dir: Some("/tmp".into()),
        ..resources
    };

    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let ctx = Context::with_memory_pool(
        &resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    ensure!(
        ctx.diagnostics() == crate::storage::diagnostics::legacy(&ctx),
        "borrowed diagnostic source changed legacy values"
    );
    #[cfg(feature = "experimental-shuffle-partition")]
    {
        for ordinal in 0..20 {
            crate::storage::decision_audit::DecisionRecord::new(
                &ctx,
                2,
                3,
                ordinal,
                &Group {
                    offset: 99,
                    rows: 2,
                    lineage: vec![],
                    exact: false,
                },
            )
            .finish(&ctx, None);
        }
        ensure!(
            ctx.diagnostics() == crate::storage::diagnostics::legacy(&ctx),
            "populated audit changed legacy values"
        );
    }
    let owner = Diagnostics::context(&ctx)?;
    let expected = crate::storage::diagnostics::legacy(&ctx);
    ensure!(
        owner == expected && owner["workspace_reserved_bytes"] == pool.usage().reserved_bytes,
        "captured diagnostics lost legacy values/self count"
    );
    #[cfg(feature = "experimental-shuffle-partition")]
    ensure!(
        owner["shuffle_partition_decisions"]["records"]
            .as_array()
            .unwrap()
            .len()
            == 16
            && owner["shuffle_partition_decisions"]["omitted_attempts"] == 4,
        "captured audit lost bounded records"
    );
    let retained = owner.reserved_bytes();
    let copy = owner.clone();
    drop(owner);
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == retained,
        "diagnostic copy retained source context/audit or lost own grant"
    );
    drop(copy);
    ensure!(pool.usage().reserved_bytes == 0, "captured context leaked");
    #[cfg(all(test, not(target_os = "wasi")))]
    {
        // This pool has a real pressure mutex. Admission during a borrowed visit
        // would deadlock; capture must release its guards before acquiring it.
        let pool = MemoryPool::pressure_test(
            64 * 1024 * 1024,
            Arc::new(std::sync::atomic::AtomicU64::new(128 * 1024 * 1024)),
        );
        let ctx = Context::with_memory_pool(
            &Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let owner = Diagnostics::context(&ctx)?;
        ensure!(
            owner == crate::storage::diagnostics::legacy(&ctx)
                && owner["process_memory"]["startup_observation"]["discovery"]
                    .as_str()
                    .is_some()
                && owner["process_memory"]["pressure_observation"]["discovery"]
                    .as_str()
                    .is_some(),
            "borrowed pressure observations changed"
        );
        drop(ctx);
        drop(owner);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "pressure-view capture leaked"
        );
    }
    Ok(
        json!({"all_legacy_fields_equal":true,"bounded_audit_records_preserved":cfg!(feature="experimental-shuffle-partition"),"context_and_original_audit_drop_before_snapshot":true,"self_inclusive_workspace_and_process_counts":true,"pressure_lock_capture_native":cfg!(all(test,not(target_os="wasi")))}),
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
        ensure!(
            std::ptr::eq(&*copy.diagnostics, &*prepared.analysis.diagnostics)
                && copy.diagnostics["analysis_diagnostics_reserved_bytes"]
                    == copy.diagnostics.reserved_bytes()
                && copy.diagnostics["workspace_reserved_bytes"] == pool.usage().reserved_bytes
                && copy.diagnostics["process_memory"]["reserved_bytes"]
                    == pool.usage().reserved_bytes,
            "diagnostic clone or final numeric slots changed"
        );
        for (key, value) in crate::storage::diagnostics::legacy(&ctx)
            .as_object()
            .unwrap()
        {
            ensure!(
                copy.diagnostics.get(key) == Some(value),
                "public diagnostic legacy field changed: {key}"
            );
        }
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
            serde_json::to_writer(Reject, &copy.diagnostics).is_err()
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
        let diagnostics = copy.diagnostics.clone();
        let bytes = diagnostics.reserved_bytes();
        drop(copy);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + bytes,
            "independent diagnostic clone lost grant"
        );
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == bytes,
            "diagnostic clone retained source context"
        );
        drop(diagnostics);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "last diagnostic clone retained grant"
        );

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
        json!({"analysis_and_independent_payload_clones":true,"prepared_drop_and_execute":true,"serialization_failures":true,"exact_csv_publication":true,"ready_snapshot_cancellation_cleanup":true,"last_diagnostic_after_context_release":true,"final_reserved_bytes":0}),
    )
}

#[cfg(test)]
#[test]
fn analysis_diagnostic_admission_and_lifetime() -> Result<()> {
    println!("CHOPPER_DIAGNOSTIC_CONTRACT {}", run()?);
    Ok(())
}
