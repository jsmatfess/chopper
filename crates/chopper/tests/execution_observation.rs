use chopper::{core::*, engine, observation::Status};
use std::{
    fs,
    sync::{atomic::AtomicBool, Arc},
};

#[test]
fn observed_limits_run_preserves_csv_caps_and_observer_failure_is_optional() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b\n3,c\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        random_seed: Some("fixed".into()),
        ..Default::default()
    };
    job.limits.rows = Some(2);
    job.limits.bytes = Some(15);
    let mut snapshots = Vec::new();
    for attempt in 0..3 {
        job.output = dir
            .path()
            .join(format!("out{attempt}"))
            .to_string_lossy()
            .into();
        let cancel = Arc::new(AtomicBool::new(false));
        let notify = Arc::new(|_| {});
        let result = match attempt {
            0 => engine::run(job.clone(), cancel, notify),
            1 => engine::run_observed(job.clone(), cancel, notify, &mut |s| {
                snapshots.push(s);
                true
            }),
            _ => engine::run_observed(job.clone(), cancel, notify, &mut |_| false),
        }
        .unwrap();
        assert_eq!(result.rows, 3);
    }
    for entry in fs::read_dir(dir.path().join("out0")).unwrap() {
        let entry = entry.unwrap();
        if entry.path().extension().is_some_and(|s| s == "csv") {
            let expected = fs::read(entry.path()).unwrap();
            assert!(expected.len() <= 15);
            for attempt in 1..3 {
                assert_eq!(
                    expected,
                    fs::read(
                        dir.path()
                            .join(format!("out{attempt}"))
                            .join(entry.file_name())
                    )
                    .unwrap()
                );
            }
        }
    }
    let last = snapshots.last().unwrap();
    assert_eq!(last.read.status, Status::Completed);
    assert_eq!(last.write.status, Status::Completed);
    assert_eq!(last.read.rows, 3);
    assert_eq!(last.write.rows, 3);
}

#[test]
fn malformed_input_attributes_read_failure_and_does_not_publish() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b,extra\n").unwrap();
    let output = dir.path().join("out");
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("fixed".into()),
        ..Default::default()
    };
    let mut snapshots = Vec::new();
    assert!(engine::run_observed(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        &mut |s| {
            snapshots.push(s);
            true
        }
    )
    .is_err());
    assert!(!output.exists());
    let last = snapshots.last().unwrap();
    assert_eq!(last.read.status, Status::Failed);
    assert_eq!(last.write.status, Status::Interrupted);
}

#[test]
fn prepared_partition_shuffle_reports_actual_resident_fusion() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("fixed".into()),
        ..Default::default()
    };
    job.operations = vec![
        Operation::Partition {
            columns: vec![Column::Name("key".into())],
        },
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
    ];
    job.limits.rows = Some(2);
    job.limits.bytes = Some(15);
    let mut baseline_job = job.clone();
    baseline_job.output = dir.path().join("baseline").to_string_lossy().into();
    engine::run(
        baseline_job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .unwrap();
    let mut rejected_job = job.clone();
    rejected_job.output = dir.path().join("rejected").to_string_lossy().into();
    engine::run_with_observations(
        rejected_job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(|_| false),
    )
    .unwrap();
    for entry in fs::read_dir(&baseline_job.output).unwrap() {
        let entry = entry.unwrap();
        if entry.path().extension().is_some_and(|s| s == "csv") {
            let bytes = fs::read(entry.path()).unwrap();
            assert!(bytes.len() <= 15);
            assert_eq!(
                bytes,
                fs::read(std::path::Path::new(&rejected_job.output).join(entry.file_name()))
                    .unwrap()
            );
        }
    }
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let received = facts.clone();
    let analysis = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    assert_eq!(analysis.rows, 3);
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::ResidentSort && f.operations == [1, 2] && f.rows == 3));
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Serialize && f.operations == [3, 0]));
}

#[test]
fn cancelling_prepared_observation_preserves_finished_work_and_cleans_output() {
    use chopper::observation::physical::Kind;
    use std::sync::{atomic::Ordering, Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n").unwrap();
    let output = dir.path().join("out");
    let cancel = Arc::new(AtomicBool::new(false));
    let stopped = cancel.clone();
    let facts = Arc::new(Mutex::new(Vec::new()));
    let seen = facts.clone();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("fixed".into()),
        operations: vec![
            Operation::Partition {
                columns: vec![Column::Name("key".into())],
            },
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
            },
        ],
        ..Default::default()
    };
    assert!(engine::run_with_observations(
        job,
        cancel,
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            if fact.kind == Kind::FisherYates && fact.status == Status::Active {
                stopped.store(true, Ordering::Relaxed);
            }
            seen.lock().unwrap().push(fact);
            true
        })
    )
    .is_err());
    assert!(!output.exists());
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|fact| fact.kind == Kind::Read && fact.status == Status::Completed));
    assert!(facts
        .iter()
        .any(|fact| fact.kind == Kind::FisherYates && fact.status == Status::Interrupted));
}

#[test]
fn external_sort_reports_spill_merge_and_grouping_handoff_reuse() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let mut source = String::from("id,key,payload\n");
    for id in 0..40000 {
        source.push_str(&format!(
            "{id},{},{}\n",
            if id >= 32000 { id % 96 } else { id % 3 },
            "x".repeat(256)
        ));
    }
    fs::write(&input, source).unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("external-fixed".into()),
        operations: vec![Operation::Partition {
            columns: vec![Column::Name("key".into())],
        }],
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 1048576,
            ..Default::default()
        },
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let received = facts.clone();
    let analysis = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    assert_eq!(analysis.rows, 40000);
    let facts = facts.lock().unwrap();
    for kind in [
        Kind::Spill,
        Kind::MergeTraversal,
        Kind::Fallback,
        Kind::Reuse,
    ] {
        assert!(
            facts
                .iter()
                .any(|f| f.kind == kind && f.status == Status::Completed),
            "missing {kind:?}"
        );
    }
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Routing && f.status == Status::HandedOff));
    assert!(facts.iter().any(|f| f.kind == Kind::MergeTraversal
        && f.sources
            .iter()
            .flatten()
            .any(|id| facts.iter().any(|s| s.id == *id && s.kind == Kind::Reuse))));
}

#[test]
fn supported_budget_forces_materialized_hierarchical_merges() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("wide.csv");
    let mut source = String::from("id,key\n");
    let prefix = "k".repeat(1800000);
    for id in 0..12 {
        source.push_str(&format!("{id},{prefix}{id:02}\n"));
    }
    fs::write(&input, source).unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("hierarchy-fixed".into()),
        operations: vec![Operation::Partition {
            columns: vec![Column::Name("key".into())],
        }],
        limits: Limits {
            bytes: Some(2097152),
            ..Default::default()
        },
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 2097152,
            grouping: Grouping::Sort,
            ..Default::default()
        },
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let received = facts.clone();
    let analysis = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    assert_eq!(analysis.rows, 12);
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::HierarchicalMerge && f.status == Status::Completed));
    for traversal in facts
        .iter()
        .filter(|f| f.kind == Kind::MergeTraversal && f.status == Status::Completed)
    {
        assert!(
            !traversal.sources.iter().flatten().any(|id| facts
                .iter()
                .any(|f| f.id == *id && matches!(f.kind, Kind::Spill | Kind::Reuse))),
            "final traversal must reference materialized runs, not their ancestors"
        );
    }
    assert_eq!(
        facts
            .iter()
            .filter(|f| f.kind == Kind::Spill && f.status == Status::Completed)
            .map(|f| f.rows)
            .sum::<u64>(),
        12
    );
    assert_eq!(
        facts
            .iter()
            .filter(|f| f.kind == Kind::MergeTraversal && f.status == Status::Completed)
            .map(|f| f.rows)
            .sum::<u64>(),
        12
    );
}

#[test]
fn cancelling_final_merge_is_interrupted_and_retains_spill_work() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::{atomic::Ordering, Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let source = "id,key,payload\n".to_owned()
        + &(0..40000)
            .map(|id| format!("{id},{},{}\n", id % 96, "x".repeat(256)))
            .collect::<String>();
    fs::write(&input, source).unwrap();
    let output = dir.path().join("out");
    let cancel = Arc::new(AtomicBool::new(false));
    let stop = cancel.clone();
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let received = facts.clone();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("cancel-merge".into()),
        operations: vec![Operation::Shuffle {
            strategy: Shuffle::Uniform,
        }],
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 1048576,
            ..Default::default()
        },
        ..Default::default()
    };
    let error = engine::run_with_observations(
        job,
        cancel,
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            if fact.kind == Kind::MergeTraversal && fact.status == Status::Active {
                stop.store(true, Ordering::Relaxed);
            }
            received.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("job cancelled"));
    assert!(!output.exists());
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Spill && f.status == Status::Completed));
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::MergeTraversal && f.status == Status::Interrupted));
    assert!(!facts
        .iter()
        .any(|f| f.kind == Kind::MergeTraversal && f.status == Status::Failed));
}

#[test]
fn allocation_observations_report_actual_groups_and_zero_quota() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{collections::BTreeMap, sync::Mutex};
    for probabilistic in [false, true] {
        for stratified in [false, true] {
            let dir = tempfile::tempdir().unwrap();
            let input = dir.path().join("input.csv");
            fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n").unwrap();
            let groups = vec![
                Allocation {
                    name: "treatment".into(),
                    percent: "50".into(),
                },
                Allocation {
                    name: "control".into(),
                    percent: "50".into(),
                },
                Allocation {
                    name: "zero".into(),
                    percent: "0".into(),
                },
            ];
            let strata = if stratified {
                vec![Column::Name("key".into())]
            } else {
                vec![]
            };
            let operation = if probabilistic {
                Operation::AssignProbabilistic { groups, strata }
            } else {
                Operation::Assign { groups, strata }
            };
            let output = dir.path().join("out");
            let job = Job {
                input: input.to_string_lossy().into(),
                output: output.to_string_lossy().into(),
                random_seed: Some("allocation-fixed".into()),
                operations: vec![operation],
                ..Default::default()
            };
            let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
            let seen = facts.clone();
            let analysis = engine::run_with_observations(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(move |fact| {
                    seen.lock().unwrap().push(fact);
                    true
                }),
            )
            .unwrap();
            assert_eq!(analysis.rows, 6);
            let outputs = fs::read_to_string(output.join("manifest.jsonl")).unwrap();
            let mut counts = BTreeMap::new();
            for record in outputs
                .lines()
                .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
                .filter(|v| v["type"] == "output")
            {
                let count = fs::read_to_string(output.join(record["path"].as_str().unwrap()))
                    .unwrap()
                    .lines()
                    .count()
                    - 1;
                let name = record["lineage"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find_map(|v| v["allocation"].as_str())
                    .unwrap()
                    .to_owned();
                *counts.entry(name).or_insert(0usize) += count;
            }
            assert_eq!(counts["zero"], 0);
            if !probabilistic {
                assert_eq!(counts["treatment"], if stratified { 4 } else { 3 });
            }
            let facts = facts.lock().unwrap();
            let kind = if probabilistic {
                Kind::ProbabilisticMembership
            } else {
                Kind::ExactMembership
            };
            let fact = facts
                .iter()
                .find(|f| f.kind == kind && f.status == Status::Completed)
                .unwrap();
            assert_eq!(fact.rows, 6);
            assert_eq!(fact.groups, 3);
            assert_eq!(
                fact.empty_groups,
                counts.values().filter(|count| **count == 0).count() as u64
            );
            if stratified && !probabilistic {
                assert!(facts
                    .iter()
                    .any(|f| f.kind == Kind::Stratification && f.role == 1));
            }
        }
    }
}

fn observed_split(operations: Vec<Operation>) -> Vec<chopper::observation::physical::Fact> {
    use chopper::observation::physical::Fact;
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n").unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("split-fixed".into()),
        operations,
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let analysis = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    assert_eq!(analysis.rows, 6);
    Arc::try_unwrap(facts).unwrap().into_inner().unwrap()
}

#[test]
fn balanced_intermediate_observes_shared_ranges_without_row_copies() {
    use chopper::observation::physical::Kind;
    let facts = observed_split(vec![
        Operation::Balanced { files: 2 },
        Operation::Shuffle {
            strategy: Shuffle::FisherYates,
        },
    ]);
    let range = facts
        .iter()
        .find(|f| f.kind == Kind::SharedRanges && f.status == Status::Completed)
        .unwrap();
    assert_eq!(range.operations, [1, 0]);
    assert_eq!((range.rows, range.groups), (6, 2));
    assert_eq!(&range.memberships[..2], &[3, 3]);
    let staged = facts
        .iter()
        .find(|f| {
            f.kind == Kind::DatasetMaterialize
                && f.operations == [1, 0]
                && f.status == Status::Completed
        })
        .unwrap();
    assert_eq!(staged.rows, 0, "shared ranges only write metadata");
    assert!(staged.sources.contains(&Some(range.id)));
}

#[test]
fn interleaved_observes_encounter_membership_and_actual_groups() {
    use chopper::observation::physical::Kind;
    let facts = observed_split(vec![Operation::Interleaved { files: 3 }]);
    let membership = facts
        .iter()
        .find(|f| f.kind == Kind::InterleavedMembership && f.status == Status::Completed)
        .unwrap();
    assert_eq!(membership.operations, [1, 0]);
    assert_eq!((membership.rows, membership.groups), (6, 3));
    assert_eq!(&membership.memberships[..3], &[2, 2, 2]);
}

#[test]
fn terminal_balanced_observes_consecutive_emission() {
    use chopper::observation::physical::Kind;
    let facts = observed_split(vec![Operation::Balanced { files: 3 }]);
    let traversal = facts
        .iter()
        .find(|f| f.kind == Kind::BalancedTraversal && f.status == Status::Completed)
        .unwrap();
    assert_eq!(traversal.operations, [1, 0]);
    assert_eq!((traversal.rows, traversal.groups), (6, 3));
    assert_eq!(&traversal.memberships[..3], &[2, 2, 2]);
}

#[test]
fn full_shuffle_balanced_observes_one_fused_traversal() {
    use chopper::observation::physical::Kind;
    for strategy in [Shuffle::Uniform, Shuffle::FisherYates] {
        let producer = if strategy == Shuffle::FisherYates {
            Kind::FisherYates
        } else {
            Kind::ResidentSort
        };
        let facts = observed_split(vec![
            Operation::Shuffle { strategy },
            Operation::Balanced { files: 3 },
        ]);
        let traversal = facts
            .iter()
            .find(|f| f.kind == Kind::FusedBalanced && f.status == Status::Completed)
            .unwrap();
        assert_eq!(traversal.operations, [2, 0]);
        assert_eq!((traversal.rows, traversal.groups), (6, 3));
        assert_eq!(&traversal.memberships[..3], &[2, 2, 2]);
        assert!(traversal.sources.iter().flatten().any(|id| facts
            .iter()
            .any(|f| f.id == *id && f.kind == producer && f.operations == [1, 0])));
    }
}
#[test]
fn cancellation_at_shared_ranges_preserves_input_and_cleans_private_output() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::{atomic::Ordering, Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("out");
    fs::write(&input, b"id\n1\n2\n3\n4\n").unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("cancel-split".into()),
        operations: vec![
            Operation::Balanced { files: 2 },
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
            },
        ],
        ..Default::default()
    };
    let cancel = Arc::new(AtomicBool::new(false));
    let stop = cancel.clone();
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let error = engine::run_with_observations(
        job,
        cancel,
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            if fact.kind == Kind::SharedRanges && fact.status == Status::Active {
                stop.store(true, Ordering::Relaxed);
            }
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("job cancelled"));
    assert!(!output.exists());
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Read && f.status == Status::Completed));
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::SharedRanges && f.status == Status::Interrupted && f.rows == 0));
    assert!(!facts
        .iter()
        .any(|f| f.kind == Kind::SharedRanges && f.status == Status::Failed));
}

#[test]
fn direct_gzip_input_reports_actual_decoded_bytes_and_keeps_csv_parity() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{io::Write, sync::Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("misleading.csv");
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(b"id\n1\n2\n").unwrap();
    fs::write(&input, encoder.finish().unwrap()).unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("codec-fixed".into()),
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let mut snapshots = Vec::new();
    engine::run_observed_with_physical(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        &mut |snapshot| {
            snapshots.push(snapshot);
            true
        },
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    let facts = facts.lock().unwrap();
    let decode = facts
        .iter()
        .find(|f| f.kind == Kind::GzipInput && f.status == Status::Completed)
        .unwrap();
    assert_eq!(decode.bytes, 7);
    assert_eq!(decode.operations, [0, 0]);
    assert_eq!(snapshots.last().unwrap().read.rows, 2);
    job.output = dir.path().join("disabled").to_string_lossy().into();
    engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {})).unwrap();
    for entry in fs::read_dir(dir.path().join("out")).unwrap() {
        let entry = entry.unwrap();
        if entry.path().extension().is_some_and(|x| x == "csv") {
            assert_eq!(
                fs::read(entry.path()).unwrap(),
                fs::read(dir.path().join("disabled").join(entry.file_name())).unwrap()
            );
        }
    }
}

#[test]
fn direct_zstandard_and_zip_inputs_report_selected_decoded_bytes() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{
        io::{Cursor, Write},
        sync::Mutex,
    };
    let mut archive = zip::ZipWriter::new(Cursor::new(Vec::new()));
    archive
        .start_file(
            "selected.csv",
            zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated),
        )
        .unwrap();
    archive.write_all(b"id\n1\n2\n").unwrap();
    archive
        .start_file("ignored.txt", zip::write::SimpleFileOptions::default())
        .unwrap();
    archive.write_all(b"not a csv").unwrap();
    for (encoded, kind) in [
        (
            zstd::stream::encode_all(&b"id\n1\n2\n"[..], 0).unwrap(),
            Kind::ZstandardInput,
        ),
        (archive.finish().unwrap().into_inner(), Kind::ZipInput),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("misleading.csv");
        let output = dir.path().join("out");
        fs::write(&input, encoded).unwrap();
        let job = Job {
            input: input.to_string_lossy().into(),
            output: output.to_string_lossy().into(),
            random_seed: Some("codec-fixed".into()),
            ..Default::default()
        };
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        let analysis = engine::run_observed_with_physical(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            &mut |_| true,
            Arc::new(move |fact| {
                seen.lock().unwrap().push(fact);
                true
            }),
        )
        .unwrap();
        assert_eq!(analysis.rows, 2);
        let facts = facts.lock().unwrap();
        let decode = facts
            .iter()
            .find(|f| f.kind == kind && f.status == Status::Completed)
            .unwrap();
        assert_eq!(decode.bytes, 7);
        assert_eq!(decode.operations, [0, 0]);
    }
}

#[test]
fn direct_gzip_output_counts_encoded_csv_bytes_at_actual_compressor() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{io::Read, sync::Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("out");
    fs::write(&input, b"id\n1\n2\n").unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("codec-output".into()),
        compression: Compression::Gzip,
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    engine::run_observed_with_physical(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        &mut |_| true,
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    let facts = facts.lock().unwrap();
    let encode = facts
        .iter()
        .find(|f| f.kind == Kind::GzipOutput && f.status == Status::Completed)
        .unwrap();
    assert_eq!(encode.bytes, 7);
    assert_eq!(encode.operations, [1, 0]);
    assert_eq!(encode.source, Some(1));
    let path = fs::read_dir(output)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "gz"))
        .unwrap();
    let mut decoded = Vec::new();
    flate2::read::GzDecoder::new(fs::File::open(path).unwrap())
        .read_to_end(&mut decoded)
        .unwrap();
    assert_eq!(decoded, b"id\n1\n2\n");
}

#[test]
fn zstandard_and_zip_output_observe_csv_compression_and_archive_bytes_separately() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    for (compression, kind) in [
        (Compression::Zstd, Kind::ZstandardOutput),
        (Compression::Zip, Kind::ZipDeflate),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("input.csv");
        let output = dir.path().join("out");
        fs::write(&input, b"id\n1\n2\n").unwrap();
        let job = Job {
            input: input.to_string_lossy().into(),
            output: output.to_string_lossy().into(),
            random_seed: Some("codec-output".into()),
            compression,
            ..Default::default()
        };
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        engine::run_observed_with_physical(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            &mut |_| true,
            Arc::new(move |fact| {
                seen.lock().unwrap().push(fact);
                true
            }),
        )
        .unwrap();
        let facts = facts.lock().unwrap();
        let encode = facts
            .iter()
            .find(|f| f.kind == kind && f.status == Status::Completed)
            .unwrap();
        assert_eq!(encode.bytes, 7);
        assert_eq!(encode.operations, [1, 0]);
        if compression == Compression::Zip {
            let archive = facts
                .iter()
                .find(|f| f.kind == Kind::ZipArchive && f.status == Status::Completed)
                .unwrap();
            assert_eq!(
                archive.bytes,
                fs::metadata(output.join("outputs.zip")).unwrap().len()
            );
            assert_eq!(archive.runs, 2);
            assert_eq!(archive.operations, [1, 0]);
            assert_eq!(archive.source, Some(encode.id));
            assert!(
                !archive.sources.contains(&Some(1)),
                "archive consumes deflated members, not raw CSV"
            );
        } else {
            let path = fs::read_dir(output)
                .unwrap()
                .map(|e| e.unwrap().path())
                .find(|p| p.extension().is_some_and(|e| e == "zst"))
                .unwrap();
            assert_eq!(
                zstd::stream::decode_all(fs::File::open(path).unwrap()).unwrap(),
                b"id\n1\n2\n"
            );
        }
    }
}

#[test]
fn corrupt_gzip_is_attributed_without_publishing_or_changing_error_placement() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{io::Write, sync::Mutex};
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(b"id\n1\n2\n").unwrap();
    let mut bytes = encoder.finish().unwrap();
    let checksum = bytes.len() - 8;
    bytes[checksum] ^= 1;
    fs::write(&input, bytes).unwrap();
    let mut messages = Vec::new();
    for observing in [false, true] {
        let output = dir
            .path()
            .join(if observing { "observed" } else { "disabled" });
        let job = Job {
            input: input.to_string_lossy().into(),
            output: output.to_string_lossy().into(),
            random_seed: Some("corrupt-codec".into()),
            ..Default::default()
        };
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        let result = if observing {
            engine::run_observed_with_physical(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                &mut |_| true,
                Arc::new(move |fact| {
                    seen.lock().unwrap().push(fact);
                    true
                }),
            )
        } else {
            engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
        };
        messages.push(format!("{:#}", result.unwrap_err()));
        assert!(!output.exists());
        if observing {
            let facts = facts.lock().unwrap();
            assert!(facts
                .iter()
                .any(|f| f.kind == Kind::GzipInput && f.status == Status::Failed));
            assert!(!facts
                .iter()
                .any(|f| f.kind == Kind::GzipInput && f.status == Status::Completed));
        }
    }
    assert_eq!(messages[0], messages[1]);
}

#[test]
fn rejected_codec_observation_and_codec_boundary_cancellation_preserve_ownership() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{
        io::Write,
        sync::{atomic::Ordering, Mutex},
    };
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(b"id\n1\n2\n").unwrap();
    fs::write(&input, encoder.finish().unwrap()).unwrap();
    let make_job = |name: &str| Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join(name).to_string_lossy().into(),
        random_seed: Some("optional-codec".into()),
        compression: Compression::Gzip,
        ..Default::default()
    };
    engine::run(
        make_job("disabled"),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .unwrap();
    engine::run_observed_with_physical(
        make_job("rejected"),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        &mut |_| false,
        Arc::new(|_| false),
    )
    .unwrap();
    for entry in fs::read_dir(dir.path().join("disabled")).unwrap() {
        let entry = entry.unwrap();
        if entry.path().extension().is_some_and(|x| x == "gz") {
            assert_eq!(
                fs::read(entry.path()).unwrap(),
                fs::read(dir.path().join("rejected").join(entry.file_name())).unwrap()
            );
        }
    }
    for (index, kind) in [Kind::GzipInput, Kind::GzipOutput].into_iter().enumerate() {
        let job = make_job(&format!("cancel{index}"));
        let output = job.output.clone();
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        let error = engine::run_observed_with_physical(
            job,
            cancel,
            Arc::new(|_| {}),
            &mut |_| true,
            Arc::new(move |fact| {
                if fact.kind == kind && fact.status == Status::Active {
                    stop.store(true, Ordering::Relaxed);
                }
                seen.lock().unwrap().push(fact);
                true
            }),
        )
        .unwrap_err();
        assert!(format!("{error:#}").contains("job cancelled"));
        assert!(!std::path::Path::new(&output).exists());
        let facts = facts.lock().unwrap();
        assert!(facts
            .iter()
            .any(|f| f.kind == kind && f.status == Status::Interrupted));
        assert!(!facts
            .iter()
            .any(|f| f.kind == kind && f.status == Status::Failed));
    }
}

#[test]
fn direct_output_construction_error_is_attributed_without_failing_input() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("out");
    fs::write(&input, b"id\n1\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("output-failure".into()),
        ..Default::default()
    };
    job.limits.bytes = Some(2);
    let mut snapshots = Vec::new();
    let error = engine::run_observed(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        &mut |snapshot| {
            snapshots.push(snapshot);
            true
        },
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("header/BOM exceeds output byte limit"));
    assert!(!output.exists());
    let last = snapshots.last().unwrap();
    assert_eq!(last.write.status, Status::Failed);
    assert_eq!(last.read.status, Status::Interrupted);
}

#[test]
fn prepared_csv_cap_failure_keeps_measured_serialization_rows_and_output_mapping() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("out");
    fs::write(&input, b"id\n1\n2\n3\n4\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("serialization-failure".into()),
        operations: vec![Operation::Balanced { files: 2 }],
        ..Default::default()
    };
    job.limits.rows = Some(1);
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let error = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("balanced group cannot satisfy final row/byte limits"));
    assert!(!output.exists());
    let facts = facts.lock().unwrap();
    let failed = facts
        .iter()
        .find(|f| f.kind == Kind::Serialize && f.status == Status::Failed)
        .unwrap();
    assert_eq!(failed.operations, [2, 0]);
    assert_eq!(failed.rows, 1);
    assert!(!facts
        .iter()
        .any(|f| f.kind == Kind::Serialize && f.status == Status::Completed));
}

#[test]
fn prepared_output_prefix_failure_reports_only_started_serialization() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id\n1\n2\n3\n4\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("prefix-failure".into()),
        operations: vec![Operation::Balanced { files: 2 }],
        ..Default::default()
    };
    job.limits.bytes = Some(2);
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    assert!(engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        })
    )
    .is_err());
    let facts = facts.lock().unwrap();
    assert!(facts.iter().any(|f| f.kind == Kind::Serialize
        && f.status == Status::Failed
        && f.operations == [2, 0]
        && f.rows == 0));
    assert!(!facts.iter().any(|f| f.kind == Kind::BalancedTraversal));
}

#[test]
fn private_materialization_failure_preserves_completed_work_and_existing_destination() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("out");
    fs::write(&input, b"id\n1\n2\n").unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some("publication-failure".into()),
        operations: vec![Operation::Shuffle {
            strategy: Shuffle::Uniform,
        }],
        ..Default::default()
    };
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let occupied = output.clone();
    assert!(engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            if fact.kind == Kind::Materialize && fact.status == Status::Active {
                fs::write(&occupied, b"existing destination").unwrap();
            }
            seen.lock().unwrap().push(fact);
            true
        })
    )
    .is_err());
    assert_eq!(fs::read(output).unwrap(), b"existing destination");
    let facts = facts.lock().unwrap();
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Serialize && f.status == Status::Completed));
    assert!(facts
        .iter()
        .any(|f| f.kind == Kind::Materialize && f.status == Status::Failed));
    assert!(!facts
        .iter()
        .any(|f| f.kind == Kind::Materialize && f.status == Status::Completed));
}

#[test]
fn named_empty_output_ceiling_error_is_attributed_to_final_output() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id\n1\n").unwrap();
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("empty-output-failure".into()),
        operations: vec![Operation::Assign {
            groups: vec![
                Allocation {
                    name: "treatment".into(),
                    percent: "100".into(),
                },
                Allocation {
                    name: "zero".into(),
                    percent: "0".into(),
                },
            ],
            strata: vec![],
        }],
        ..Default::default()
    };
    job.resources.max_files = 1;
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let seen = facts.clone();
    let error = engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap_err();
    assert!(format!("{error:#}").contains("max_files"));
    let facts = facts.lock().unwrap();
    assert!(facts.iter().any(|f| f.kind == Kind::Serialize
        && f.status == Status::Failed
        && f.operations == [2, 0]
        && f.rows == 1));
}

#[test]
fn prepared_input_errors_report_actual_completed_rows_without_publishing() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    for input_text in ["id,key\n1,a\n2,b,extra\n", "id,key\n1,a\n2,\"unfinished\n"] {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("input.csv");
        let output = dir.path().join("out");
        fs::write(&input, input_text).unwrap();
        let job = Job {
            input: input.to_string_lossy().into(),
            output: output.to_string_lossy().into(),
            random_seed: Some("prepared-read-failure".into()),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }],
            ..Default::default()
        };
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        assert!(engine::run_with_observations(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(move |fact| {
                seen.lock().unwrap().push(fact);
                true
            })
        )
        .is_err());
        assert!(!output.exists());
        let facts = facts.lock().unwrap();
        assert!(facts
            .iter()
            .any(|f| f.kind == Kind::Read && f.status == Status::Failed && f.rows == 1));
        assert!(!facts
            .iter()
            .any(|f| f.kind == Kind::Read && f.status == Status::Completed));
    }
}

#[test]
fn input_and_exact_allocation_publish_rows_before_their_attempt_finishes() {
    use chopper::observation::physical::{Fact, Kind};
    use std::{sync::Mutex, time::Duration};
    let mut missing = Vec::new();
    for (target, fused) in [
        (Kind::ExactMembership, false),
        (Kind::Read, false),
        (Kind::ExactMembership, true),
    ] {
        let downstream = if fused {
            Kind::Serialize
        } else if target == Kind::Read {
            Kind::DatasetMaterialize
        } else {
            Kind::Routing
        };
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("input.csv");
        let mut csv = String::from("id,key,padding\n");
        for row in 0..16384 {
            csv.push_str(&format!("{row},value{},{}\n", row % 2, "x".repeat(1024)));
        }
        fs::write(&input, csv).unwrap();
        let mut job = Job {
            input: input.to_string_lossy().into(),
            output: dir.path().join("output").to_string_lossy().into(),
            resources: Resources {
                memory_mb: 32.into(),
                workers: 1,
                max_record_bytes: 1048576,
                ..Default::default()
            },
            operations: vec![Operation::Assign {
                groups: vec![
                    Allocation {
                        name: "a".into(),
                        percent: "50".into(),
                    },
                    Allocation {
                        name: "b".into(),
                        percent: "50".into(),
                    },
                ],
                strata: vec![],
            }],
            ..Default::default()
        };
        if fused {
            job.operations.insert(
                0,
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
            );
        }
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let received = facts.clone();
        engine::run_with_observations(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(move |fact| {
                // Open the real progress throttle without needing a slow or large input.
                if fact.kind == downstream && fact.status == Status::Active && fact.rows == 0 {
                    std::thread::sleep(Duration::from_millis(110));
                }
                received.lock().unwrap().push(fact);
                true
            }),
        )
        .unwrap();
        let facts = facts.lock().unwrap();
        if !facts.iter().any(|f| {
            f.kind == target
                && f.status == Status::Active
                && f.rows > 0
                && f.rows < 16384
                && f.seconds > 0.0
        }) {
            missing.push((target, fused));
        }
        assert!(facts
            .iter()
            .any(|f| f.kind == target && f.status == Status::Completed && f.rows == 16384));
    }
    assert!(
        missing.is_empty(),
        "{missing:?} must report real rows before completion"
    );
}

#[test]
fn logical_stage_finalization_follows_all_parent_attempts_and_precedes_the_next_stage() {
    use chopper::observation::physical::{Fact, Kind};
    use std::sync::Mutex;
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n7,a\n8,b\n").unwrap();
    let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
    let received = facts.clone();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("output").to_string_lossy().into(),
        operations: vec![
            Operation::Partition {
                columns: vec![Column::Name("key".into())],
            },
            Operation::Assign {
                groups: vec![
                    Allocation {
                        name: "a".into(),
                        percent: "50".into(),
                    },
                    Allocation {
                        name: "b".into(),
                        percent: "50".into(),
                    },
                ],
                strata: vec![],
            },
            Operation::Interleaved { files: 2 },
        ],
        ..Default::default()
    };
    engine::run_with_observations(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }),
    )
    .unwrap();
    let facts = facts.lock().unwrap();
    let stages = facts
        .iter()
        .filter(|f| f.kind == Kind::StageComplete)
        .map(|f| f.operations[0])
        .collect::<Vec<_>>();
    assert_eq!(stages, vec![0, 1, 2, 3, 4]);
    let allocation = facts
        .iter()
        .enumerate()
        .filter(|(_, f)| f.kind == Kind::ExactMembership && f.status == Status::Completed)
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    assert_eq!(allocation.len(), 2);
    let finalized = facts
        .iter()
        .position(|f| f.kind == Kind::StageComplete && f.operations[0] == 2)
        .unwrap();
    assert!(allocation.iter().all(|i| *i < finalized));
    assert!(
        facts
            .iter()
            .position(|f| f.kind == Kind::InterleavedMembership)
            .unwrap()
            > finalized
    );
}
