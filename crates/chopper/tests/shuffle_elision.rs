//! Public-path candidate controls. These require shuffle_elision::ENABLED=true.
use anyhow::{Context as _, Result};
use chopper::{
    core::{csv::Parser, random, *},
    engine,
    observation::{
        physical::{Fact, Kind},
        Status,
    },
    resources::MemoryPool,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};

fn shuffle(strategy: Shuffle) -> Operation {
    Operation::Shuffle { strategy }
}
fn fixture(rows: usize) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let mut text = "id,text\n".to_owned();
    for id in 0..rows {
        text.push_str(&format!("{id},\"界,{id}\"\"\nend\"\n"));
    }
    fs::write(&input, text)?;
    fs::create_dir(dir.path().join("temp"))?;
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("mixed-elision-contract".into()),
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
fn observed(job: &Job) -> Result<(engine::Analysis, Vec<Fact>)> {
    let facts = Arc::new(Mutex::new(Vec::new()));
    let seen = facts.clone();
    let analysis = engine::run_with_observations(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }),
    )?;
    let facts = facts.lock().unwrap().clone();
    Ok((analysis, facts))
}
// Return encounter order per logical lineage; parse real quoted/multiline CSV.
fn outputs(job: &Job, rows: usize) -> Result<BTreeMap<String, Vec<usize>>> {
    let mut groups = BTreeMap::<String, Vec<usize>>::new();
    let mut ids = BTreeSet::new();
    for line in fs::read_to_string(Path::new(&job.output).join("manifest.jsonl"))?.lines() {
        let entry: serde_json::Value = serde_json::from_str(line)?;
        if entry["type"] != "output" {
            continue;
        }
        let bytes = fs::read(Path::new(&job.output).join(entry["path"].as_str().unwrap()))?;
        assert_eq!(bytes.len() as u64, entry["csv_bytes"].as_u64().unwrap());
        if let Some(cap) = job.limits.bytes {
            assert!(bytes.len() as u64 <= cap);
        }
        let mut parser = Parser::new(
            bytes.as_slice(),
            job.output_csv.clone(),
            job.resources.max_record_bytes,
        );
        assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
        let target = groups
            .entry(serde_json::to_string(&entry["lineage"])?)
            .or_default();
        let mut count = 0;
        while let Some(fields) = parser.next_record()? {
            let id = fields[0].parse::<usize>()?;
            assert!(ids.insert(id), "duplicate {id}");
            assert_eq!(fields[1], format!("界,{id}\"\nend"));
            target.push(id);
            count += 1;
        }
        assert_eq!(count, entry["rows"].as_u64().unwrap());
        if let Some(cap) = job.limits.rows {
            assert!(count <= cap);
        }
    }
    assert_eq!(ids, (0..rows).collect());
    Ok(groups)
}
fn source_free_elided(facts: &[Fact], operation: usize) {
    let finished: Vec<_> = facts
        .iter()
        .filter(|f| {
            f.kind == Kind::Elided
                && f.operations == [operation, 0]
                && f.status == Status::Completed
        })
        .collect();
    assert_eq!(finished.len(), 1, "operation {operation}");
    let fact = finished[0];
    assert_eq!((fact.rows, fact.bytes, fact.runs), (0, 0, 0));
    assert_eq!(fact.source, None);
    assert_eq!(fact.sources, [None; 4]);
    assert!(!fact.source_omitted);
}

#[test]
fn all_nine_pairs_and_mixed_triples_keep_final_method_original_indices_and_parents() -> Result<()> {
    let methods = [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates];
    let mut sequences = Vec::new();
    for a in methods {
        for b in methods {
            sequences.push(vec![a, b]);
        }
    }
    sequences.extend([
        vec![Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates],
        vec![Shuffle::FisherYates, Shuffle::Auto, Shuffle::FisherYates],
        vec![Shuffle::Auto, Shuffle::FisherYates, Shuffle::Auto],
        vec![Shuffle::Uniform, Shuffle::Auto, Shuffle::Uniform],
    ]);
    for parents in [0, 1, 8] {
        for sequence in &sequences {
            let (dir, mut job) = fixture(80)?;
            if parents > 0 {
                job.operations.push(Operation::Balanced { files: parents });
            }
            job.operations.extend(sequence.iter().copied().map(shuffle));
            let offset = usize::from(parents > 0);
            let count = parents.max(1);
            let (analysis, facts) = observed(&job)?;
            assert_eq!(analysis.rows, 80);
            assert_eq!(analysis.groups, count);
            assert_eq!(analysis.stages.len(), job.operations.len());
            for (i, stage) in analysis.stages.iter().enumerate() {
                assert_eq!(stage.operation, i + 1);
                if i >= offset {
                    assert_eq!(
                        (
                            stage.input_groups,
                            stage.output_groups,
                            stage.smallest_group,
                            stage.largest_group,
                            stage.empty_groups
                        ),
                        (count, count, 80 / count, 80 / count, 0)
                    );
                }
            }
            let expected_calls = sequence
                .iter()
                .filter(|s| **s == Shuffle::FisherYates)
                .count() as u64
                * count;
            assert_eq!(
                analysis.diagnostics["fisher_yates_calls"].as_u64(),
                Some(expected_calls)
            );
            assert_eq!(
                analysis.diagnostics["fisher_yates_rows"].as_u64(),
                Some(expected_calls * 80 / count)
            );
            for (i, strategy) in sequence.iter().enumerate() {
                let operation = offset + i + 1;
                if *strategy != Shuffle::FisherYates && i + 1 < sequence.len() {
                    source_free_elided(&facts, operation);
                    assert!(!facts.iter().any(|f| f.operations.contains(&operation)
                        && matches!(f.kind, Kind::ResidentSort | Kind::FisherYates)));
                } else {
                    let kind = if *strategy == Shuffle::FisherYates {
                        Kind::FisherYates
                    } else {
                        Kind::ResidentSort
                    };
                    let calls: Vec<_> = facts
                        .iter()
                        .filter(|f| {
                            f.kind == kind
                                && f.operations == [operation, 0]
                                && f.status == Status::Completed
                        })
                        .collect();
                    assert_eq!(calls.len() as u64, count);
                    assert_eq!(calls.iter().map(|f| f.rows).sum::<u64>(), 80);
                    assert!(!facts
                        .iter()
                        .any(|f| f.kind == Kind::Elided && f.operations == [operation, 0]));
                }
            }
            let groups = outputs(&job, 80)?;
            assert_eq!(groups.len() as u64, count);
            for (lineage, ids) in groups {
                let lineage: serde_json::Value = serde_json::from_str(&lineage)?;
                if parents == 0 {
                    assert_eq!(lineage, serde_json::json!([]));
                } else {
                    let part = lineage[0]["part"].as_u64().unwrap();
                    assert_eq!(lineage, serde_json::json!([{"operation":0,"part":part}]));
                    assert!(ids.iter().all(|id| *id as u64 / (80 / count) == part - 1));
                }
            }
            assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        }
    }
    Ok(())
}

#[test]
fn final_fisher_uses_original_domain_in_ingestion_and_each_retained_parent() -> Result<()> {
    for parents in [0, 1, 8] {
        let (_dir, mut job) = fixture(80)?;
        if parents > 0 {
            job.operations.push(Operation::Balanced { files: parents });
        }
        job.operations.extend([
            shuffle(Shuffle::Auto),
            shuffle(Shuffle::Uniform),
            shuffle(Shuffle::FisherYates),
        ]);
        observed(&job)?;
        let step = job.operations.len() - 1;
        for (lineage, actual) in outputs(&job, 80)? {
            let value: serde_json::Value = serde_json::from_str(&lineage)?;
            let start = if parents == 0 {
                0
            } else {
                (value[0]["part"].as_u64().unwrap() as usize - 1) * (80 / parents as usize)
            };
            let mut expected: Vec<_> = (start..start + actual.len()).collect();
            let domain = random::domain(job.random_seed.as_deref().unwrap(), step as u64, &lineage);
            let mut rng = random::Random::new(random::algorithm_domain(&domain, "fisher-yates-v1"));
            for i in (1..expected.len()).rev() {
                expected.swap(i, rng.below(i as u64 + 1) as usize);
            }
            assert_eq!(actual, expected);
        }
    }
    Ok(())
}

#[test]
fn downstream_balanced_interleaved_and_exact_quotas_use_realized_parent_order() -> Result<()> {
    for parents in [0, 8] {
        for interleaved in [false, true] {
            let (_dir, mut job) = fixture(80)?;
            if parents > 0 {
                job.operations.push(Operation::Balanced { files: parents });
            }
            job.operations
                .extend([shuffle(Shuffle::Auto), shuffle(Shuffle::FisherYates)]);
            observed(&job)?;
            let original = outputs(&job, 80)?;
            job.output.push_str("-split");
            let step = job.operations.len();
            job.operations.push(if interleaved {
                Operation::Interleaved { files: 2 }
            } else {
                Operation::Balanced { files: 2 }
            });
            job.limits.rows = Some(2);
            job.limits.bytes = Some(100);
            let error = observed(&job)
                .err()
                .context("exact split must reject restrictive caps")?;
            assert!(format!("{error:#}").contains("exact file count"));
            assert!(!Path::new(&job.output).exists());
            // A terminal exact split cannot create extra cap chunks. Retain
            // that rejection above, then test ordering with fitting caps.
            job.limits.rows = Some(40);
            job.limits.bytes = Some(4096);
            observed(&job)?;
            for (lineage, actual) in outputs(&job, 80)? {
                let mut lineage: Vec<serde_json::Value> = serde_json::from_str(&lineage)?;
                let split = lineage.pop().unwrap();
                assert_eq!(split["operation"], step);
                let part = split["part"].as_u64().unwrap() as usize - 1;
                let before = &original[&serde_json::to_string(&lineage)?];
                let expected: Vec<_> = before
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| {
                        if interleaved {
                            i % 2 == part
                        } else {
                            i / (before.len() / 2) == part
                        }
                    })
                    .map(|(_, id)| *id)
                    .collect();
                assert_eq!(actual, expected);
            }
        }
    }
    let (_dir, mut job) = fixture(80)?;
    job.operations = vec![
        Operation::Balanced { files: 8 },
        shuffle(Shuffle::Uniform),
        shuffle(Shuffle::FisherYates),
        Operation::Assign {
            groups: [("a", "30"), ("zero", "0"), ("b", "70")]
                .into_iter()
                .map(|(name, percent)| Allocation {
                    name: name.into(),
                    percent: percent.into(),
                })
                .collect(),
            strata: vec![],
        },
    ];
    job.limits.rows = Some(2);
    job.limits.bytes = Some(100);
    let (analysis, _) = observed(&job)?;
    assert_eq!(analysis.stages[3].output_groups, 24);
    assert_eq!(analysis.stages[3].empty_groups, 8);
    for (lineage, ids) in outputs(&job, 80)? {
        let lineage: serde_json::Value = serde_json::from_str(&lineage)?;
        let part = lineage[0]["part"].as_u64().unwrap() as usize;
        assert!(ids.iter().all(|id| id / 10 == part - 1));
        assert_eq!(lineage[1]["operation"], 3);
        assert_eq!(
            ids.len(),
            match lineage[1]["allocation"].as_str().unwrap() {
                "a" => 3,
                "zero" => 0,
                "b" => 7,
                _ => panic!("unexpected allocation"),
            }
        );
    }
    Ok(())
}

#[test]
fn upstream_partition_and_assignment_fusions_are_honest_bypass_controls() -> Result<()> {
    for assign in [false, true] {
        let (_dir, mut job) = fixture(80)?;
        job.operations.push(if assign {
            Operation::Assign {
                groups: vec![Allocation {
                    name: "all".into(),
                    percent: "100".into(),
                }],
                strata: vec![],
            }
        } else {
            Operation::Partition {
                columns: vec![Column::Name("id".into())],
            }
        });
        job.operations
            .extend([shuffle(Shuffle::Uniform), shuffle(Shuffle::FisherYates)]);
        let (analysis, facts) = observed(&job)?;
        assert_eq!(analysis.stages.len(), 3);
        assert!(!facts
            .iter()
            .any(|f| f.kind == Kind::Elided && f.operations == [2, 0]));
        assert!(facts.iter().any(|f| f.operations == [1, 2]
            && f.status == Status::Completed
            && f.kind == Kind::ResidentSort));
        assert_eq!(
            analysis.diagnostics["fisher_yates_calls"].as_u64(),
            Some(if assign { 1 } else { 80 })
        );
        outputs(&job, 80)?;
    }
    Ok(())
}

#[test]
fn prepared_mixed_snapshot_survives_source_mutation_and_existing_destination_rejection(
) -> Result<()> {
    for existing in [false, true] {
        let (dir, mut job) = fixture(80)?;
        job.operations = vec![shuffle(Shuffle::Auto), shuffle(Shuffle::FisherYates)];
        let mut control = job.clone();
        control.output.push_str("-control");
        observed(&control)?;
        let expected = outputs(&control, 80)?;
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let prepared = engine::prepare_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let retained = prepared.analysis.clone();
        fs::write(&job.input, "broken,source\n\"unterminated")?;
        if existing {
            fs::create_dir(&job.output)?;
            fs::write(Path::new(&job.output).join("sentinel"), "keep")?;
            assert!(prepared.execute().is_err());
            assert_eq!(
                fs::read_to_string(Path::new(&job.output).join("sentinel"))?,
                "keep"
            );
            assert_eq!(fs::read_dir(&job.output)?.count(), 1);
        } else {
            assert_eq!(prepared.execute()?.rows, 80);
            assert_eq!(outputs(&job, 80)?, expected);
            for entry in fs::read_dir(&control.output)? {
                let entry = entry?;
                if entry.path().extension().is_some_and(|ext| ext == "csv") {
                    assert_eq!(
                        fs::read(entry.path())?,
                        fs::read(Path::new(&job.output).join(entry.file_name()))?
                    );
                }
            }
        }
        assert!(pool.usage().reserved_bytes > 0);
        drop(retained);
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}

#[test]
fn earlier_and_final_explicit_resident_denial_are_terminal_and_clean() -> Result<()> {
    for methods in [
        vec![Shuffle::FisherYates, Shuffle::Auto],
        vec![Shuffle::FisherYates, Shuffle::Uniform],
        vec![Shuffle::Auto, Shuffle::FisherYates],
    ] {
        for retained in [false, true] {
            let (dir, mut job) = fixture(0)?;
            // Valid records, deliberately beyond the resident quarter-budget ceiling.
            let mut file = fs::File::create(&job.input)?;
            use std::io::Write;
            writeln!(file, "id,text")?;
            for id in 0..40 {
                writeln!(file, "{id},{}", "x".repeat(256 * 1024))?;
            }
            drop(file);
            job.operations = methods.iter().copied().map(shuffle).collect();
            if retained {
                job.operations.insert(0, Operation::Balanced { files: 1 });
            }
            let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
            let error = engine::run_with_memory_pool(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )
            .err()
            .context("resident request must fail")?;
            assert!(format!("{error:#}").contains("Fisher–Yates"), "{error:#}");
            assert!(!Path::new(&job.output).exists());
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        }
    }
    Ok(())
}

#[test]
fn first_and_late_wide_root_records_and_shared_denial_release_actual_capacity() -> Result<()> {
    for wide_at in [0, 17] {
        for shared in [64 * 1024 * 1024, 512 * 1024] {
            let (dir, mut job) = fixture(0)?;
            let mut file = fs::File::create(&job.input)?;
            use std::io::Write;
            writeln!(file, "id,text")?;
            for id in 0..20 {
                writeln!(
                    file,
                    "{id},{}",
                    if id == wide_at {
                        "w".repeat(512 * 1024)
                    } else {
                        "tiny".into()
                    }
                )?;
            }
            drop(file);
            job.operations = vec![shuffle(Shuffle::Uniform), shuffle(Shuffle::FisherYates)];
            let pool = Arc::new(MemoryPool::new(shared));
            let result = engine::run_with_memory_pool(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            );
            if shared < 1024 * 1024 {
                assert!(result.is_err());
                assert!(!Path::new(&job.output).exists());
            } else {
                assert_eq!(result?.rows, 20);
                let mut ids = BTreeSet::new();
                for entry in fs::read_dir(&job.output)? {
                    let entry = entry?;
                    if entry.path().extension().is_some_and(|ext| ext == "csv") {
                        let bytes = fs::read(entry.path())?;
                        let mut parser = Parser::new(
                            bytes.as_slice(),
                            job.output_csv.clone(),
                            job.resources.max_record_bytes,
                        );
                        assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
                        while let Some(fields) = parser.next_record()? {
                            let id = fields[0].parse::<usize>()?;
                            assert!(ids.insert(id));
                            assert_eq!(
                                fields[1],
                                if id == wide_at {
                                    "w".repeat(512 * 1024)
                                } else {
                                    "tiny".into()
                                }
                            );
                        }
                    }
                }
                assert_eq!(ids, (0..20).collect());
            }
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        }
    }
    Ok(())
}

#[test]
fn malformed_caps_disk_and_cancellation_do_not_publish_or_replay() -> Result<()> {
    for mode in ["malformed", "cap", "disk", "cancel"] {
        let (dir, mut job) = fixture(80)?;
        job.operations = vec![shuffle(Shuffle::Auto), shuffle(Shuffle::FisherYates)];
        if mode == "malformed" {
            fs::write(&job.input, "id,text\n0,\"unterminated")?;
        }
        if mode == "cap" {
            job.limits.bytes = Some(1);
        }
        if mode == "disk" {
            job.resources.temp_bytes = Some(1);
        }
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let error = engine::run_with_observations(
            job.clone(),
            cancel,
            Arc::new(|_| {}),
            Arc::new(move |fact| {
                if mode == "cancel"
                    && fact.kind == Kind::FisherYates
                    && fact.status == Status::Active
                {
                    stop.store(true, Ordering::Relaxed);
                }
                true
            }),
        )
        .err()
        .context("expected terminal failure")?;
        let text = format!("{error:#}");
        assert!(
            match mode {
                "malformed" => text.contains("quoted") || text.contains("unterminated"),
                "cap" => text.contains("byte"),
                "disk" => text.contains("temporary-space"),
                _ => text.contains("cancel"),
            },
            "{mode}: {text}"
        );
        assert!(!Path::new(&job.output).exists());
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}

#[test]
fn empty_singleton_and_operation_barriers_preserve_stages() -> Result<()> {
    for rows in [0, 1] {
        let (_dir, mut job) = fixture(rows)?;
        job.operations = vec![shuffle(Shuffle::Auto), shuffle(Shuffle::FisherYates)];
        let (analysis, facts) = observed(&job)?;
        assert_eq!(analysis.stages.len(), 2);
        assert_eq!(analysis.rows, rows as u64);
        source_free_elided(&facts, 1);
        outputs(&job, rows)?;
    }
    for barrier in [
        Operation::Balanced { files: 8 },
        Operation::Interleaved { files: 8 },
        Operation::Partition {
            columns: vec![Column::Name("id".into())],
        },
        Operation::Assign {
            groups: vec![Allocation {
                name: "all".into(),
                percent: "100".into(),
            }],
            strata: vec![],
        },
        Operation::AssignProbabilistic {
            groups: vec![Allocation {
                name: "all".into(),
                percent: "100".into(),
            }],
            strata: vec![],
        },
    ] {
        let (_dir, mut job) = fixture(80)?;
        job.operations = vec![
            shuffle(Shuffle::Auto),
            barrier,
            shuffle(Shuffle::FisherYates),
        ];
        let (analysis, facts) = observed(&job)?;
        assert_eq!(analysis.stages.len(), 3);
        assert!(!facts.iter().any(|f| f.kind == Kind::Elided));
        assert!(facts.iter().any(|f| f.kind == Kind::FisherYates
            && f.operations == [3, 0]
            && f.status == Status::Completed));
        outputs(&job, 80)?;
    }
    Ok(())
}

#[test]
fn fisher_dependencies_describe_ingestion_retained_and_intermediate_work() -> Result<()> {
    for retained in [false, true] {
        for intermediate in [false, true] {
            let (_dir, mut job) = fixture(80)?;
            if retained {
                job.operations.push(Operation::Balanced { files: 1 });
            }
            job.operations
                .extend([shuffle(Shuffle::Auto), shuffle(Shuffle::FisherYates)]);
            let fisher_operation = job.operations.len();
            if intermediate {
                job.operations.push(Operation::Interleaved { files: 2 });
            }
            let (_, facts) = observed(&job)?;
            let fisher = facts
                .iter()
                .find(|f| f.kind == Kind::FisherYates && f.status == Status::Completed)
                .unwrap();
            assert_eq!(fisher.operations, [fisher_operation, 0]);
            assert!(fisher
                .sources
                .iter()
                .flatten()
                .any(|id| facts.iter().any(|f| f.id == *id
                    && f.kind
                        == if retained {
                            Kind::DatasetMaterialize
                        } else {
                            Kind::Read
                        })));
            let consumer_kind = if intermediate {
                Kind::DatasetMaterialize
            } else {
                Kind::Serialize
            };
            assert!(facts.iter().any(|f| f.kind == consumer_kind
                && f.status == Status::Completed
                && f.sources.contains(&Some(fisher.id))));
            assert!(!facts
                .iter()
                .any(|f| f.kind == Kind::ResidentSort && f.operations.contains(&fisher_operation)));
        }
    }
    Ok(())
}

#[test]
fn combined_root_and_retained_ranges_cut_the_original_final_fisher_permutation() -> Result<()> {
    for parents in [0, 1, 8] {
        let (_dir, mut job) = fixture(80)?;
        if parents > 0 {
            job.operations.push(Operation::Balanced { files: parents });
        }
        let fisher_step = job.operations.len() + 1;
        job.operations.extend([
            shuffle(Shuffle::Auto),
            shuffle(Shuffle::FisherYates),
            Operation::Assign {
                groups: [("a", "37"), ("zero", "0"), ("b", "63")]
                    .into_iter()
                    .map(|(name, percent)| Allocation {
                        name: name.into(),
                        percent: percent.into(),
                    })
                    .collect(),
                strata: vec![],
            },
        ]);
        let (analysis, facts) = observed(&job)?;
        assert_eq!(analysis.stages.len(), fisher_step + 2);
        source_free_elided(&facts, fisher_step);
        for (lineage, actual) in outputs(&job, 80)? {
            let mut lineage: Vec<serde_json::Value> = serde_json::from_str(&lineage)?;
            let allocation = lineage.pop().unwrap();
            assert_eq!(allocation["operation"], fisher_step + 1);
            let n = if parents == 0 {
                80
            } else {
                80 / parents as usize
            };
            let start = if parents == 0 {
                0
            } else {
                (lineage[0]["part"].as_u64().unwrap() as usize - 1) * n
            };
            let mut permutation: Vec<_> = (start..start + n).collect();
            let domain = random::domain(
                job.random_seed.as_deref().unwrap(),
                fisher_step as u64,
                &serde_json::to_string(&lineage)?,
            );
            let mut rng = random::Random::new(random::algorithm_domain(&domain, "fisher-yates-v1"));
            for i in (1..n).rev() {
                permutation.swap(i, rng.below(i as u64 + 1) as usize);
            }
            // Independent fixed outcomes for 37/0/63 on these two parent sizes.
            let first = if n == 80 {
                30
            } else {
                assert_eq!(n, 10);
                4
            };
            let expected = match allocation["allocation"].as_str().unwrap() {
                "a" => &permutation[..first],
                "zero" => &permutation[0..0],
                "b" => &permutation[first..],
                _ => panic!("unknown allocation"),
            };
            assert_eq!(actual, expected);
        }
    }
    Ok(())
}
