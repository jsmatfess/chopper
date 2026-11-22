//! Grouped direct publication must respect competing owners until commit.
use super::*;
use crate::{
    resources::{MemoryAdmission, MemoryPool},
    storage::Workspace,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Mutex,
};

#[test]
fn terminal_competing_owner_and_cancellation() -> Result<()> {
    const MIB: u64 = 1024 * 1024;
    let mut kinds = vec![0];
    if cfg!(feature = "experimental-terminal-shuffle") {
        kinds.push(1);
    }
    if cfg!(all(
        feature = "experimental-terminal-routing",
        not(target_os = "wasi")
    )) {
        kinds.extend([2, 3, 4, 5]);
    }
    for kind in kinds {
        for mode in ["held", "released", "denied", "cancelled"] {
            for direct in [false, true] {
                let dir = tempfile::tempdir()?;
                let input = dir.path().join("input.csv");
                let mut text = String::from("id,text,key\n");
                for id in 0..65537 {
                    text.push_str(&format!("{id},value-{id},{}\n", id % 8));
                }
                std::fs::write(&input, text)?;
                let temp = dir.path().join("temp");
                std::fs::create_dir(&temp)?;
                let job = Job {
                    input: input.to_string_lossy().into(),
                    output: dir.path().join("out").to_string_lossy().into(),
                    operations: if kind == 1 {
                        vec![
                            Operation::Shuffle {
                                strategy: Shuffle::Uniform,
                            },
                            Operation::Balanced { files: 8 },
                        ]
                    } else if kind == 2 {
                        vec![Operation::Interleaved { files: 8 }]
                    } else if kind == 3 {
                        vec![Operation::AssignProbabilistic {
                            groups: (0..8)
                                .map(|i| chopper_core::Allocation {
                                    name: format!("group-{i}"),
                                    percent: "12.5".into(),
                                })
                                .collect(),
                            strata: vec![],
                        }]
                    } else if kind == 5 {
                        vec![Operation::Assign {
                            groups: (0..8)
                                .map(|i| chopper_core::Allocation {
                                    name: format!("group-{i}"),
                                    percent: "12.5".into(),
                                })
                                .collect(),
                            strata: vec![chopper_core::Column::Name("key".into())],
                        }]
                    } else if kind == 4 {
                        vec![Operation::Partition {
                            columns: vec![chopper_core::Column::Name("key".into())],
                        }]
                    } else {
                        vec![Operation::Balanced { files: 8 }]
                    },
                    resources: chopper_core::Resources {
                        memory_mb: 32.into(),
                        workers: 1,
                        max_record_bytes: 10000,
                        temp_dir: Some(temp.to_string_lossy().into()),
                        ..Default::default()
                    },
                    ..Default::default()
                };
                let pool = Arc::new(MemoryPool::new(32 * MIB));
                let space = Arc::new(Workspace::shared(32 * MIB as usize, pool.clone()));
                let owner = Arc::new(Mutex::new(Reservation::for_workspace(space.clone())));
                let visits = Arc::new(AtomicUsize::new(0));
                let injected = Arc::new(AtomicBool::new(false));
                let finalized = Arc::new(AtomicBool::new(false));
                let cancel = Arc::new(AtomicBool::new(false));
                let notify: Notify = {
                    let (owner, pool, visits, injected, finalized, cancel) = (
                        owner.clone(),
                        pool.clone(),
                        visits.clone(),
                        injected.clone(),
                        finalized.clone(),
                        cancel.clone(),
                    );
                    Arc::new(move |p| {
                        if (p.phase == "Reading and validating CSV"
                            || p.phase == "Reading and writing CSV")
                            && p.rows == 0
                        {
                            visits.fetch_add(1, Ordering::Relaxed);
                        }
                        if p.phase == "Serializing output" {
                            assert!(!injected.swap(true, Ordering::Relaxed));
                            owner.lock().unwrap().resize((16 * MIB) as usize).unwrap();
                        }
                        if p.phase
                            == if direct {
                                "Finalizing direct terminal output"
                            } else {
                                "Finalizing output snapshot"
                            }
                        {
                            finalized.store(true, Ordering::Relaxed);
                            let mut grant = owner.lock().unwrap();
                            if mode == "released" {
                                grant.resize(0).unwrap();
                            }
                            if mode == "denied" || mode == "cancelled" {
                                let usage = pool.usage();
                                let target =
                                    grant.bytes() + usage.limit_bytes - usage.reserved_bytes;
                                grant.resize(target as usize).unwrap();
                            }
                            if mode == "cancelled" {
                                cancel.store(true, Ordering::Relaxed);
                            }
                        }
                    })
                };
                let result = if direct {
                    run_with_memory_pool(job.clone(), cancel, notify, pool.clone())
                } else {
                    prepare_with_memory_pool(job.clone(), cancel, notify, pool.clone())
                        .and_then(|p| p.execute())
                };
                assert_eq!(visits.load(Ordering::Relaxed), 1, "no raw-input replay");
                assert!(injected.load(Ordering::Relaxed));
                assert!(finalized.load(Ordering::Relaxed));
                if mode == "held" || mode == "released" {
                    let analysis = result?;
                    assert_eq!(analysis.rows, 65537);
                    assert_eq!(analysis.groups, 8);
                    assert_eq!(analysis.output_files, 8);
                    drop(analysis);
                    std::fs::remove_dir_all(&job.output)?;
                } else {
                    let error = result.expect_err("terminal denial or cancellation");
                    if mode == "cancelled" {
                        assert!(format!("{error:#}").contains("job cancelled"), "{error:#}");
                    } else {
                        assert!(
                            matches!(
                                error.downcast_ref::<MemoryAdmission>(),
                                Some(MemoryAdmission::Shared { .. })
                            ),
                            "{error:#}"
                        );
                    }
                    assert!(!std::path::Path::new(&job.output).exists());
                }
                assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
                assert_eq!(
                    std::fs::read_dir(dir.path())?.count(),
                    2,
                    "no private staging remains"
                );
                let held = owner.lock().unwrap().bytes();
                assert_eq!(
                    pool.usage().reserved_bytes,
                    held,
                    "only competitor survives"
                );
                assert_eq!(space.used(), held);
                owner.lock().unwrap().resize(0)?;
                assert_eq!(pool.usage().reserved_bytes, 0);
            }
        }
    }
    Ok(())
}
