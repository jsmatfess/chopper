//! Public-path contracts for the range candidate once the lead registers/wires it.
use anyhow::{Context as _, Result};
use chopper::{
    core::{csv::Parser, *},
    engine,
    resources::MemoryPool,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    sync::{atomic::AtomicBool, Arc},
};

fn allocations() -> Vec<Allocation> {
    [("first", "50"), ("zero", "0"), ("last", "50")]
        .into_iter()
        .map(|(name, percent)| Allocation {
            name: name.into(),
            percent: percent.into(),
        })
        .collect()
}
fn fixture() -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let mut text = "id,text\n".to_owned();
    for id in 0..30 {
        text.push_str(&format!("{id},\"界,{id}\"\"\nend\"\n"));
    }
    fs::write(&input, text)?;
    fs::create_dir(dir.path().join("temp"))?;
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("result").to_string_lossy().into(),
        random_seed: Some("range-public-contract".into()),
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 1048576,
            temp_dir: Some(dir.path().join("temp").to_string_lossy().into()),
            ..Default::default()
        },
        ..Default::default()
    };
    Ok((dir, job))
}
fn pair(strategy: Shuffle) -> Vec<Operation> {
    vec![
        Operation::Shuffle { strategy },
        Operation::Assign {
            groups: allocations(),
            strata: vec![],
        },
    ]
}
fn records(job: &Job) -> Result<Vec<serde_json::Value>> {
    fs::read_to_string(std::path::Path::new(&job.output).join("manifest.jsonl"))?
        .lines()
        .map(|line| Ok(serde_json::from_str(line)?))
        .collect()
}
#[test]
fn root_and_visible_retained_pair_keep_fields_quotas_stages_lineage_and_caps() -> Result<()> {
    for strategy in [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates] {
        for retained in [false, true] {
            for downstream in [false, true] {
                let (dir, mut job) = fixture()?;
                if retained {
                    job.operations.push(Operation::Balanced { files: 1 });
                }
                job.operations.extend(pair(strategy));
                if downstream {
                    job.operations.push(Operation::Assign {
                        groups: vec![
                            Allocation {
                                name: "a".into(),
                                percent: "25".into(),
                            },
                            Allocation {
                                name: "b".into(),
                                percent: "75".into(),
                            },
                        ],
                        strata: vec![],
                    });
                }
                job.limits.rows = Some(3);
                job.limits.bytes = Some(120);
                let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
                let analysis = engine::run_with_memory_pool(
                    job.clone(),
                    Arc::new(AtomicBool::new(false)),
                    Arc::new(|_| {}),
                    pool.clone(),
                )?;
                let offset = usize::from(retained);
                assert_eq!(analysis.stages.len(), job.operations.len());
                for (i, stage) in analysis.stages.iter().enumerate() {
                    assert_eq!(stage.operation, i + 1);
                }
                let shuffle = &analysis.stages[offset];
                assert_eq!(
                    (
                        shuffle.input_groups,
                        shuffle.output_groups,
                        shuffle.smallest_group,
                        shuffle.largest_group
                    ),
                    (1, 1, 30, 30)
                );
                let assignment = &analysis.stages[offset + 1];
                assert_eq!(
                    (
                        assignment.input_groups,
                        assignment.output_groups,
                        assignment.smallest_group,
                        assignment.largest_group,
                        assignment.empty_groups
                    ),
                    (1, 3, 0, 15, 1)
                );
                if downstream {
                    assert_eq!(analysis.stages[offset + 2].output_groups, 6);
                }
                let mut ids = BTreeSet::new();
                let mut counts = BTreeMap::<String, u64>::new();
                let mut nested = BTreeMap::<(String, String), u64>::new();
                for entry in records(&job)? {
                    if entry["type"] != "output" {
                        continue;
                    }
                    let lineage = entry["lineage"].as_array().unwrap();
                    if retained {
                        assert_eq!(lineage[0], serde_json::json!({"operation":0,"part":1}));
                    }
                    assert_eq!(lineage[offset]["operation"], offset + 1);
                    let name = lineage[offset]["allocation"].as_str().unwrap();
                    *counts.entry(name.into()).or_default() += entry["rows"].as_u64().unwrap();
                    if downstream {
                        assert_eq!(lineage[offset + 1]["operation"], offset + 2);
                        let child = lineage[offset + 1]["allocation"].as_str().unwrap();
                        *nested.entry((name.into(), child.into())).or_default() +=
                            entry["rows"].as_u64().unwrap();
                    }
                    let bytes = fs::read(
                        std::path::Path::new(&job.output).join(entry["path"].as_str().unwrap()),
                    )?;
                    assert!(bytes.len() <= 120);
                    assert_eq!(bytes.len() as u64, entry["csv_bytes"].as_u64().unwrap());
                    let mut parser = Parser::new(bytes.as_slice(), job.output_csv.clone(), 1048576);
                    assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
                    let mut rows = 0;
                    while let Some(fields) = parser.next_record()? {
                        let id = fields[0].parse::<u64>()?;
                        assert!(ids.insert(id));
                        assert_eq!(fields[1], format!("界,{id}\"\nend"));
                        rows += 1;
                    }
                    assert!(rows <= 3);
                    assert_eq!(rows, entry["rows"].as_u64().unwrap());
                }
                assert_eq!(ids, (0..30).collect());
                assert_eq!(
                    counts,
                    BTreeMap::from([
                        ("first".into(), 15),
                        ("zero".into(), 0),
                        ("last".into(), 15)
                    ])
                );
                if downstream {
                    assert_eq!(
                        nested,
                        BTreeMap::from([
                            (("first".into(), "a".into()), 4),
                            (("first".into(), "b".into()), 11),
                            (("zero".into(), "a".into()), 0),
                            (("zero".into(), "b".into()), 0),
                            (("last".into(), "a".into()), 4),
                            (("last".into(), "b".into()), 11),
                        ])
                    );
                }
                drop(analysis);
                assert_eq!(pool.usage().reserved_bytes, 0);
                assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
            }
        }
    }
    Ok(())
}
#[test]
fn prepared_confirmation_uses_retained_snapshot_and_rejects_existing_destination() -> Result<()> {
    for existing in [false, true] {
        let (dir, mut job) = fixture()?;
        job.operations = pair(Shuffle::Uniform);
        let prepared = engine::prepare(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let expected = if existing {
            Vec::new()
        } else {
            let mut reference = job.clone();
            reference.output = dir.path().join("reference").to_string_lossy().into();
            engine::run(
                reference.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            records(&reference)?
                .into_iter()
                .filter(|entry| entry["type"] == "output")
                .map(|entry| {
                    let name = entry["path"].as_str().unwrap().to_owned();
                    Ok((
                        name.clone(),
                        fs::read(std::path::Path::new(&reference.output).join(name))?,
                    ))
                })
                .collect::<Result<Vec<_>>>()?
        };
        fs::write(&job.input, "broken,source\n\"unterminated")?;
        if existing {
            fs::create_dir(&job.output)?;
            fs::write(std::path::Path::new(&job.output).join("sentinel"), "keep")?;
            assert!(prepared.execute().is_err());
            assert_eq!(
                fs::read_to_string(std::path::Path::new(&job.output).join("sentinel"))?,
                "keep"
            );
            assert_eq!(fs::read_dir(&job.output)?.count(), 1);
        } else {
            assert_eq!(prepared.execute()?.rows, 30);
            for (name, bytes) in expected {
                assert_eq!(
                    fs::read(std::path::Path::new(&job.output).join(name))?,
                    bytes
                );
            }
            assert_eq!(
                records(&job)?
                    .iter()
                    .filter(|r| r["type"] == "output")
                    .map(|r| r["rows"].as_u64().unwrap())
                    .sum::<u64>(),
                30
            );
        }
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}
#[test]
fn malformed_cancel_disk_and_impossible_caps_release_all_owners_without_publication() -> Result<()>
{
    for mode in ["malformed", "cancel", "disk", "cap"] {
        let (dir, mut job) = fixture()?;
        job.operations = pair(Shuffle::Uniform);
        if mode == "malformed" {
            fs::write(&job.input, "id,text\n0,\"unterminated")?;
        }
        if mode == "disk" {
            job.resources.temp_bytes = Some(1);
        }
        if mode == "cap" {
            job.limits.bytes = Some(1);
        }
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let error = engine::run_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(mode == "cancel")),
            Arc::new(|_| {}),
            pool.clone(),
        )
        .err()
        .context("expected failure")?;
        let message = format!("{error:#}");
        assert!(
            match mode {
                "cancel" => message.contains("cancel"),
                "malformed" => message.contains("quoted") || message.contains("unterminated"),
                "disk" => message.contains("temporary-space"),
                _ => message.contains("byte"),
            },
            "{mode}: {message}"
        );
        assert!(!std::path::Path::new(&job.output).exists());
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}

#[test]
fn physical_range_counts_follow_actual_permutation_without_assignment_sort() -> Result<()> {
    use chopper::observation::{physical::Kind, Status};
    use std::sync::Mutex;
    for strategy in [Shuffle::Uniform, Shuffle::FisherYates] {
        for retained in [false, true] {
            let (_dir, mut job) = fixture()?;
            if retained {
                job.operations.push(Operation::Balanced { files: 1 });
            }
            job.operations.extend(pair(strategy));
            let facts = Arc::new(Mutex::new(Vec::new()));
            let capture = facts.clone();
            let analysis = engine::run_with_observations(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(move |fact| {
                    capture.lock().unwrap().push(fact);
                    true
                }),
            )?;
            let facts = facts.lock().unwrap();
            let shuffle = usize::from(retained) + 1;
            let assignment = shuffle + 1;
            let membership = facts
                .iter()
                .find(|fact| {
                    fact.kind == Kind::ExactMembership
                        && fact.operations == [assignment, 0]
                        && fact.status == Status::Completed
                })
                .context("range observation missing")?;
            assert_eq!(
                (membership.rows, membership.groups, membership.empty_groups),
                (30, 3, 1)
            );
            assert_eq!(&membership.memberships[..3], &[15, 0, 15]);
            let producer = facts
                .iter()
                .find(|fact| Some(fact.id) == membership.source && fact.status == Status::Completed)
                .context("permutation source missing")?;
            assert_eq!(producer.operations, [shuffle, assignment]);
            assert_eq!(
                producer.kind,
                if strategy == Shuffle::FisherYates {
                    Kind::FisherYates
                } else {
                    Kind::ResidentSort
                }
            );
            assert!(!facts.iter().any(|fact| fact.operations[0] == assignment
                && matches!(fact.kind, Kind::ResidentSort | Kind::Routing | Kind::Spill)));
            assert_eq!(analysis.stages.len(), assignment);
        }
    }
    Ok(())
}

#[test]
fn named_empty_allocation_still_fails_a_later_balanced_nonempty_request() -> Result<()> {
    let (dir, mut job) = fixture()?;
    job.operations = pair(Shuffle::Uniform);
    job.operations.push(Operation::Balanced { files: 1 });
    let error = engine::run(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .err()
    .context("empty balanced child must fail")?;
    assert!(format!("{error:#}").contains("nonempty balanced"));
    assert!(!std::path::Path::new(&job.output).exists());
    assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    Ok(())
}

fn ordered_output_ids(job: &Job) -> Result<BTreeMap<String, Vec<u64>>> {
    let mut groups = BTreeMap::<String, Vec<u64>>::new();
    let mut seen = BTreeSet::new();
    for entry in records(job)? {
        if entry["type"] != "output" {
            continue;
        }
        let bytes =
            fs::read(std::path::Path::new(&job.output).join(entry["path"].as_str().unwrap()))?;
        let mut parser = Parser::new(bytes.as_slice(), job.output_csv.clone(), 1048576);
        assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
        let group = groups
            .entry(serde_json::to_string(&entry["lineage"])?)
            .or_default();
        while let Some(fields) = parser.next_record()? {
            let id = fields[0].parse::<u64>()?;
            assert!(seen.insert(id));
            assert_eq!(fields[1], format!("界,{id}\"\nend"));
            group.push(id);
        }
    }
    assert_eq!(seen, (0..30).collect());
    Ok(groups)
}

#[test]
fn downstream_interleaving_preserves_each_realized_child_encounter_order() -> Result<()> {
    for retained in [false, true] {
        for strategy in [Shuffle::Uniform, Shuffle::FisherYates] {
            let (_dir, mut job) = fixture()?;
            if retained {
                job.operations.push(Operation::Balanced { files: 2 });
            }
            job.operations.extend([
                Operation::Shuffle { strategy },
                Operation::Assign {
                    groups: [("a", "33"), ("b", "67")]
                        .into_iter()
                        .map(|(name, percent)| Allocation {
                            name: name.into(),
                            percent: percent.into(),
                        })
                        .collect(),
                    strata: vec![],
                },
            ]);
            engine::run(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            let before = ordered_output_ids(&job)?;
            job.output.push_str("-interleaved");
            let split_step = job.operations.len();
            job.operations.push(Operation::Interleaved { files: 2 });
            engine::run(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            for (lineage, actual) in ordered_output_ids(&job)? {
                let mut lineage: Vec<serde_json::Value> = serde_json::from_str(&lineage)?;
                let split = lineage.pop().unwrap();
                assert_eq!(split["operation"], split_step);
                let part = split["part"].as_u64().unwrap() as usize - 1;
                let parent = &before[&serde_json::to_string(&lineage)?];
                assert_eq!(
                    actual,
                    parent
                        .iter()
                        .copied()
                        .skip(part)
                        .step_by(2)
                        .collect::<Vec<_>>()
                );
            }
        }
    }
    Ok(())
}

#[test]
fn external_ingestion_ranges_keep_last_original_shuffle_and_actual_merge_source() -> Result<()> {
    use chopper::observation::{physical::Kind, Status};
    use std::sync::Mutex;
    let (_dir, mut job) = fixture()?;
    let mut csv = String::from("id,text\n");
    for id in 0..50003 {
        csv.push_str(&format!("{id},{}\n", "x".repeat(192)));
    }
    fs::write(&job.input, csv)?;
    job.operations = vec![
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Shuffle {
            strategy: Shuffle::Auto,
        },
        Operation::Assign {
            groups: allocations(),
            strata: vec![],
        },
    ];
    let facts = Arc::new(Mutex::new(Vec::new()));
    let captured = facts.clone();
    let analysis = engine::run_with_observations(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            captured.lock().unwrap().push(fact);
            true
        }),
    )?;
    assert_eq!(analysis.stages.len(), 3);
    assert!(analysis.diagnostics["sort_runs"].as_u64().unwrap() > 0);
    let facts = facts.lock().unwrap();
    assert!(facts.iter().any(|f| f.kind == Kind::Elided
        && f.operations == [1, 0]
        && f.rows == 0
        && f.source.is_none()));
    let membership = facts
        .iter()
        .find(|f| {
            f.kind == Kind::ExactMembership
                && f.operations == [3, 0]
                && f.status == Status::Completed
        })
        .unwrap();
    assert_eq!((membership.rows, membership.groups), (50003, 3));
    let producer = facts
        .iter()
        .find(|f| Some(f.id) == membership.source && f.status == Status::Completed)
        .unwrap();
    assert_eq!(
        (producer.kind, producer.operations),
        (Kind::MergeTraversal, [2, 3])
    );
    let domain = chopper::core::random::domain(job.random_seed.as_deref().unwrap(), 1, "[]");
    // Test-owned key storage pins this producer, not a cross-plan seed promise.
    let mut expected: Vec<_> = (0..50003u64)
        .map(|id| {
            (
                chopper::core::random::block(&domain, id, 0)[..16].to_vec(),
                id,
            )
        })
        .collect();
    expected.sort_by(|(a_key, a), (b_key, b)| {
        a_key
            .cmp(b_key)
            .then_with(|| chopper::core::random::compare_ties(&domain, *a, *b))
    });
    let expected: Vec<_> = expected.into_iter().map(|(_, id)| id).collect();
    let mut actual = BTreeMap::<String, Vec<u64>>::new();
    let mut seen = BTreeSet::new();
    for entry in records(&job)? {
        if entry["type"] != "output" {
            continue;
        }
        let bytes =
            fs::read(std::path::Path::new(&job.output).join(entry["path"].as_str().unwrap()))?;
        let mut parser = Parser::new(bytes.as_slice(), job.output_csv.clone(), 1048576);
        assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
        let name = entry["lineage"].as_array().unwrap().last().unwrap()["allocation"]
            .as_str()
            .unwrap();
        let target = actual.entry(name.into()).or_default();
        while let Some(row) = parser.next_record()? {
            let id = row[0].parse::<u64>()?;
            assert!(seen.insert(id));
            target.push(id);
            assert_eq!(row[1], "x".repeat(192));
        }
    }
    assert_eq!(actual["first"], expected[..25002]);
    assert!(actual["zero"].is_empty());
    assert_eq!(actual["last"], expected[25002..]);
    assert_eq!(seen, (0..50003).collect());
    Ok(())
}
