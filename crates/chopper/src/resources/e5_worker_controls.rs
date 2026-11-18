//! Untimed complete-Run controls, never compiled into the measurement executable.
use super::*;
use crate::storage::{context_test_hook, Reservation, Workspace};
use chopper_core::{Job, Operation, Shuffle};
use std::sync::atomic::{AtomicBool, AtomicUsize};

const MIB: u64 = 1024 * 1024;

fn scenario(
    workers: usize,
    expected_workers: usize,
    shared: bool,
    phase: &'static str,
    cancelled: bool,
) -> Result<serde_json::Value> {
    println!("E5 scenario workers={workers} shared={shared} phase={phase} cancelled={cancelled}");
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let output = dir.path().join("output");
    let temp = dir.path().join("temp");
    std::fs::create_dir(&temp)?;
    // Direct serialization emits a progress event only after 65536 written rows.
    let direct = phase == "Serializing output";
    let rows = if direct { 65537 } else { 5000 };
    let mut text = String::from("id,key,payload\r\n");
    for id in 0..rows {
        if direct && id == 65536 {
            text.push_str(&format!("{id},heavy,{}\r\n", "x".repeat(32768)));
        } else {
            text.push_str(&format!("{id},heavy,xxxxxxxx\r\n"));
        }
    }
    std::fs::write(&input, text)?;
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        output: output.to_string_lossy().into_owned(),
        random_seed: Some("e5-workers-held-fixed-v1".into()),
        operations: if direct {
            vec![]
        } else {
            vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }]
        },
        ..Job::default()
    };
    job.resources.memory_mb = 256.into();
    job.resources.workers = workers;
    job.resources.max_record_bytes = MIB as usize;
    job.resources.temp_bytes = Some(256 * MIB);
    job.resources.temp_dir = Some(temp.to_string_lossy().into_owned());
    job.limits.rows = Some(2000);
    job.limits.bytes = Some(262144);
    // Local controls need an aggregate pool larger than the 128 MiB local cap,
    // otherwise Shared wins first. Shared controls use the frozen 64 MiB pool.
    let limit = if shared { 64 * MIB } else { 256 * MIB };
    let pool = Arc::new(MemoryPool::new(limit));
    let workspace = Arc::new(Mutex::new(None::<Arc<Workspace>>));
    let resolved = Arc::new(AtomicUsize::new(0));
    let captured = workspace.clone();
    let observed = resolved.clone();
    let _reset = context_test_hook::install(move |workspace, workers| {
        observed.store(workers, Ordering::Relaxed);
        *captured.lock().unwrap() = Some(workspace);
    });
    let owner = Arc::new(Mutex::new(None::<Reservation>));
    let retained = Arc::new(AtomicU64::new(0));
    let injection = Arc::new(Mutex::new(None));
    let visits = Arc::new(Mutex::new(Vec::new()));
    let cancel = Arc::new(AtomicBool::new(false));
    let notify = {
        let (pool, workspace, owner, retained, visits, cancel, injection) = (
            pool.clone(),
            workspace.clone(),
            owner.clone(),
            retained.clone(),
            visits.clone(),
            cancel.clone(),
            injection.clone(),
        );
        Arc::new(move |progress: crate::storage::Progress| {
            visits.lock().unwrap().push(progress.phase.clone());
            if progress.phase == phase {
                assert_eq!(
                    progress.rows,
                    if direct {
                        65536
                    } else if phase == "Ready for confirmation" {
                        5000
                    } else {
                        0
                    },
                    "freeze the injection at the actual emission boundary"
                );
                assert!(
                    owner.lock().unwrap().is_none(),
                    "no retry after denial/emission"
                );
                let local = workspace.lock().unwrap().as_ref().unwrap().clone();
                let (space, bytes) = if shared {
                    (
                        Arc::new(Workspace::shared(limit as usize, pool.clone())),
                        limit - pool.usage().reserved_bytes,
                    )
                } else {
                    let bytes = 128 * MIB - local.used();
                    (local, bytes)
                };
                let mut grant = Reservation::for_workspace(space);
                grant.resize(bytes as usize).unwrap();
                retained.store(bytes, Ordering::Relaxed);
                *injection.lock().unwrap() = Some(serde_json::json!({
                    "phase": phase, "rows": progress.rows, "cancelled": cancelled,
                    "pool_limit_bytes": limit, "local_limit_bytes": 128 * MIB,
                    "grant_bytes": bytes,
                    "remaining_bytes": if shared { limit - pool.usage().reserved_bytes } else { 128 * MIB - space_used(&workspace) },
                }));
                *owner.lock().unwrap() = Some(grant);
                if cancelled {
                    cancel.store(true, Ordering::Relaxed);
                }
            }
        })
    };
    let error = crate::engine::run_with_memory_pool(job, cancel, notify, pool.clone())
        .expect_err("injected complete Run must fail");
    assert_eq!(resolved.load(Ordering::Relaxed), expected_workers);
    assert!(
        retained.load(Ordering::Relaxed) > 0,
        "injection must be reached"
    );
    if cancelled {
        assert!(format!("{error:#}").contains("job cancelled"), "{error:#}");
    } else {
        assert!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) == shared,
            "{error:#}"
        );
        if !shared {
            assert!(
                matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Local)
                ),
                "{error:#}"
            );
        }
    }
    assert!(!output.exists(), "no partial publication");
    assert_eq!(std::fs::read_dir(&temp)?.count(), 0, "owned temp cleanup");
    assert_eq!(
        std::fs::read_dir(dir.path())?.count(),
        2,
        "input and empty temp only; no staging"
    );
    assert_eq!(
        pool.usage().reserved_bytes,
        retained.load(Ordering::Relaxed),
        "only competitor survives"
    );
    let local = workspace.lock().unwrap().take().unwrap();
    assert_eq!(
        local.used(),
        if shared {
            0
        } else {
            retained.load(Ordering::Relaxed)
        }
    );
    let visits = visits.lock().unwrap();
    assert_eq!(visits.iter().filter(|v| v.as_str() == phase).count(), 1);
    assert!(!visits
        .iter()
        .any(|v| v.starts_with("Retrying") || v == "Complete"));
    if direct {
        assert_eq!(
            visits
                .iter()
                .filter(|v| v.as_str() == "Reading and writing CSV")
                .count(),
            1
        );
    }
    drop(owner.lock().unwrap().take());
    assert_eq!(local.used(), 0);
    assert_eq!(pool.usage().reserved_bytes, 0, "final grants released");
    let mut record = injection.lock().unwrap().take().unwrap();
    record["error"] = serde_json::json!(if cancelled {
        "cancelled"
    } else if shared {
        "shared"
    } else {
        "local"
    });
    record["cleanup_verified"] = serde_json::json!(true);
    Ok(record)
}

fn space_used(workspace: &Mutex<Option<Arc<Workspace>>>) -> u64 {
    workspace.lock().unwrap().as_ref().unwrap().used()
}

#[test]
fn complete_run_worker_denials() -> Result<()> {
    // Ordinary regression checks also run on smaller CI hosts. The benchmark
    // harness separately requires four CPUs and rejects non-four-worker Auto
    // records; these portable controls do not relax its frozen eligibility.
    let automatic_workers = std::thread::available_parallelism()
        .map(usize::from)
        .unwrap_or(1)
        .min(4);
    for (id, workers, shared) in [
        ("D1", 1, false),
        ("D2", 0, false),
        ("D3", 1, true),
        ("D4", 0, true),
    ] {
        let expected_workers = if workers == 0 {
            automatic_workers
        } else {
            workers
        };
        // Denial before operation emission, at publication, and after direct
        // output emission; cancellation at publication overrides admission.
        let mut scenarios = Vec::new();
        for phase in [
            "Reading and validating CSV",
            "Ready for confirmation",
            "Serializing output",
        ] {
            scenarios.push(scenario(workers, expected_workers, shared, phase, false)?);
        }
        scenarios.push(scenario(
            workers,
            expected_workers,
            shared,
            "Ready for confirmation",
            true,
        )?);
        println!(
            "E5_WORKER_CONTROL {}",
            serde_json::json!({
                "id": id, "kind": if shared { "shared" } else { "local" },
                "requested_workers": workers, "resolved_workers": expected_workers,
                "memory_mb":256, "passed":true, "scenarios": scenarios
            })
        );
    }
    Ok(())
}
