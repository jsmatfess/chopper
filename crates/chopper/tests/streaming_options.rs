use anyhow::Result;
use chopper::{
    core::*,
    engine::{self, Analysis, Prepared},
};
use std::{
    fs,
    path::Path,
    sync::{atomic::AtomicBool, Arc},
};

fn setup(text: &str) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    fs::write(dir.path().join("input.csv"), text)?;
    let job = Job {
        input: dir.path().join("input.csv").to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("browser-contract-test".into()),
        resources: Resources {
            memory_mb: 32.into(),
            max_record_bytes: 1024 * 1024,
            workers: 1,
            ..Default::default()
        },
        ..Default::default()
    };
    Ok((dir, job))
}
fn prepare(job: Job) -> Result<Prepared> {
    engine::prepare(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}
fn run(job: Job) -> Result<(Analysis, Vec<String>)> {
    let out = job.output.clone();
    let prepared = prepare(job)?;
    let ctx = prepared.ctx.clone();
    let analysis = prepared.execute()?;
    assert_eq!(
        ctx.diagnostics()["workspace_reserved_bytes"],
        ctx.diagnostics()["directory_path_reserved_bytes"]
            .as_u64()
            .unwrap()
            + analysis.preview.reserved_bytes()
            + analysis.warnings.reserved_bytes()
            + analysis.timings.reserved_bytes()
            + analysis.diagnostics.reserved_bytes()
            + analysis.text_reserved_bytes()
            + analysis.stages.reserved_bytes()
            + analysis.column_values.reserved_bytes()
            + analysis
                .header
                .as_ref()
                .map_or(0, |header| header.reserved_bytes())
    );
    assert_eq!(ctx.diagnostics()["temporary_path_reserved_bytes"], 0);
    let mut files = vec![];
    for line in fs::read_to_string(Path::new(&out).join("manifest.jsonl"))?.lines() {
        let entry: serde_json::Value = serde_json::from_str(line)?;
        if entry["type"] == "output" {
            files.push(fs::read_to_string(
                Path::new(&out).join(entry["path"].as_str().unwrap()),
            )?);
        }
    }
    fs::remove_dir_all(out)?;
    Ok((analysis, files))
}
fn ids(files: &[String]) -> Vec<Vec<u64>> {
    files
        .iter()
        .map(|s| {
            s.lines()
                .skip(1)
                .map(|line| line.split(',').next().unwrap().parse().unwrap())
                .collect()
        })
        .collect()
}
fn allocations() -> Vec<Allocation> {
    vec![
        Allocation {
            name: "treatment".into(),
            percent: "80".into(),
        },
        Allocation {
            name: "control".into(),
            percent: "20".into(),
        },
    ]
}
fn fisher() -> Operation {
    Operation::Shuffle {
        strategy: Shuffle::FisherYates,
    }
}

#[test]
fn buffered_fisher_yates_matches_block_word_oracle_across_budgets_and_workers() -> Result<()> {
    // Preserve the historical fixture; derive the new stream independently from block words.
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/fisher-yates-v1.json"))?;
    let (_dir, mut job) = setup(fixture["input"].as_str().unwrap())?;
    job.random_seed = Some(fixture["seed"].as_str().unwrap().into());
    job.operations = vec![fisher()];
    let domain = random::algorithm_domain(
        &random::domain(fixture["seed"].as_str().unwrap(), 0, "[]"),
        "fisher-yates-v1",
    );
    let mut expected: Vec<u64> = (0..fixture["ids"].as_array().unwrap().len() as u64).collect();
    let mut word = 0u64;
    for i in (1..expected.len()).rev() {
        let bound = i as u64 + 1;
        let threshold = ((1u128 << 64) % bound as u128) as u64;
        let draw = loop {
            let bytes = random::block(&domain, word / 4, 0);
            let offset = (word % 4) as usize * 8;
            word += 1;
            let value = u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
            if value >= threshold {
                break value % bound;
            }
        };
        expected.swap(i, draw as usize);
    }
    for (memory, workers) in [(32, 1), (64, 4)] {
        job.resources.memory_mb = memory.into();
        job.resources.workers = workers;
        let (analysis, files) = run(job.clone())?;
        assert_eq!(ids(&files), vec![expected.clone()]);
        assert_eq!(analysis.diagnostics["fisher_yates_calls"], 1);
        assert_eq!(
            analysis.diagnostics["workspace_reserved_bytes"],
            analysis.preview.reserved_bytes()
                + analysis.warnings.reserved_bytes()
                + analysis.timings.reserved_bytes()
                + analysis.diagnostics.reserved_bytes()
                + analysis.text_reserved_bytes()
                + analysis.stages.reserved_bytes()
                + analysis.column_values.reserved_bytes()
                + analysis.diagnostics["prepared_job_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["temporary_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["directory_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["input_header_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        );
    }
    Ok(())
}

#[test]
fn full_shuffles_preserve_empty_singleton_and_duplicate_payload_groups() -> Result<()> {
    for strategy in [Shuffle::Uniform, Shuffle::FisherYates] {
        // The zero-weight allocation materializes an empty group. The partition
        // produces a singleton alongside a group of duplicate payloads.
        let (_dir, mut job) =
            setup("id,k,payload\n0,a,duplicate\n1,b,duplicate\n2,b,duplicate\n3,b,duplicate\n")?;
        job.operations = vec![
            Operation::Partition {
                columns: vec![Column::Name("k".into())],
            },
            Operation::Assign {
                groups: vec![
                    Allocation {
                        name: "empty".into(),
                        percent: "0".into(),
                    },
                    Allocation {
                        name: "all".into(),
                        percent: "100".into(),
                    },
                ],
                strata: vec![],
            },
            Operation::Shuffle { strategy },
        ];
        let (analysis, files) = run(job.clone())?;
        let groups = ids(&files);
        assert_eq!(groups.len(), 4);
        assert!(groups[0].is_empty());
        assert_eq!(groups[1], [0]);
        assert!(groups[2].is_empty());
        let mut last = groups[3].clone();
        last.sort_unstable();
        assert_eq!(last, [1, 2, 3]);
        assert_eq!(analysis.stages.last().unwrap().empty_groups, 2);
        assert_eq!(
            analysis.diagnostics["workspace_reserved_bytes"],
            analysis.preview.reserved_bytes()
                + analysis.warnings.reserved_bytes()
                + analysis.timings.reserved_bytes()
                + analysis.diagnostics.reserved_bytes()
                + analysis.text_reserved_bytes()
                + analysis.stages.reserved_bytes()
                + analysis.column_values.reserved_bytes()
                + analysis.diagnostics["prepared_job_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["temporary_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["directory_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["input_header_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        );
        job.resources.workers = 4;
        job.resources.memory_mb = 64.into();
        assert_eq!(run(job)?.1, files);

        let (_dir, mut empty_job) = setup("id,k,payload\n")?;
        empty_job.operations = vec![Operation::Shuffle { strategy }];
        let (analysis, files) = run(empty_job)?;
        assert!(files.is_empty());
        assert_eq!(analysis.output_files, 0);
        assert_eq!(analysis.stages[0].empty_groups, 1);
    }
    Ok(())
}

#[test]
fn full_shuffles_enforce_strict_caps_and_cancel_without_publication() -> Result<()> {
    for strategy in [Shuffle::Uniform, Shuffle::FisherYates] {
        let (_dir, mut job) =
            setup("id,payload\n0,duplicate\n1,duplicate\n2,duplicate\n3,duplicate\n")?;
        job.operations = vec![
            Operation::Shuffle { strategy },
            Operation::Balanced { files: 2 },
        ];
        // Every output is an eleven-byte header plus two twelve-byte records.
        for (rows, bytes) in [(1, 35), (2, 34)] {
            job.limits.rows = Some(rows);
            job.limits.bytes = Some(bytes);
            assert!(prepare(job.clone()).is_err());
            assert!(!Path::new(&job.output).exists());
        }
        job.limits.rows = Some(2);
        job.limits.bytes = Some(35);
        let (_, files) = run(job.clone())?;
        assert!(files.iter().all(|file| file.len() == 35));
        let mut conserved = ids(&files).into_iter().flatten().collect::<Vec<_>>();
        conserved.sort_unstable();
        assert_eq!(conserved, [0, 1, 2, 3]);

        let cancelled = Arc::new(AtomicBool::new(false));
        let prepared = engine::prepare(job.clone(), cancelled.clone(), Arc::new(|_| {}))?;
        cancelled.store(true, std::sync::atomic::Ordering::Relaxed);
        assert!(prepared.execute().is_err());
        assert!(!Path::new(&job.output).exists());
    }
    Ok(())
}

#[test]
fn interleaved_first_and_nested_preserve_subsequence_and_exact_balance() -> Result<()> {
    let (_dir, mut job) = setup("id,k\n0,a\n1,b\n2,a\n3,b\n4,a\n5,b\n6,a\n")?;
    job.operations = vec![Operation::Interleaved { files: 3 }];
    let (analysis, files) = run(job.clone())?;
    assert_eq!(ids(&files), vec![vec![0, 3, 6], vec![1, 4], vec![2, 5]]);
    assert_eq!(
        (
            analysis.stages[0].smallest_group,
            analysis.stages[0].largest_group
        ),
        (2, 3)
    );
    job.operations.insert(
        0,
        Operation::Partition {
            columns: vec![Column::Name("k".into())],
        },
    );
    assert_eq!(
        ids(&run(job.clone())?.1),
        vec![vec![0, 6], vec![2], vec![4], vec![1], vec![3], vec![5]]
    );
    job.operations = vec![
        Operation::Interleaved { files: 2 },
        Operation::Partition {
            columns: vec![Column::Name("k".into())],
        },
    ];
    assert_eq!(ids(&run(job)?.1), vec![vec![0, 2, 4, 6], vec![1, 3, 5]]);
    Ok(())
}

#[test]
fn interleaved_keeps_nonempty_and_hard_cap_contracts() -> Result<()> {
    let (_dir, mut job) = setup("id\n0\n1\n2\n3\n4\n")?;
    job.operations = vec![Operation::Interleaved { files: 6 }];
    assert!(prepare(job.clone())
        .err()
        .unwrap()
        .to_string()
        .contains("nonempty"));
    job.operations = vec![Operation::Interleaved { files: 2 }];
    job.limits.rows = Some(2);
    assert!(prepare(job.clone()).is_err());
    job.limits.rows = Some(3);
    job.limits.bytes = Some(8); // header plus three rows needs nine bytes
    assert!(prepare(job.clone()).is_err());
    job.limits.bytes = Some(9);
    assert_eq!(run(job.clone())?.0.output_files, 2);
    assert!(!Path::new(&job.output).exists());
    Ok(())
}

#[test]
fn probabilistic_zero_weights_empty_inputs_and_stratum_validation() -> Result<()> {
    let (dir, mut job) = setup("id,k\n0,a\n1,b\n2,a\n")?;
    job.operations = vec![Operation::AssignProbabilistic {
        groups: vec![
            Allocation {
                name: "none".into(),
                percent: "0".into(),
            },
            Allocation {
                name: "all".into(),
                percent: "100".into(),
            },
        ],
        strata: vec![Column::Name("k".into())],
    }];
    let (a, files) = run(job.clone())?;
    assert_eq!(ids(&files), vec![vec![], vec![0, 1, 2]]);
    assert_eq!(a.stages[0].empty_groups, 1);
    fs::write(dir.path().join("input.csv"), "id,k\n")?;
    assert_eq!(run(job.clone())?.1, vec!["id,k\n", "id,k\n"]);
    if let Operation::AssignProbabilistic { strata, .. } = &mut job.operations[0] {
        *strata = vec![Column::Name("missing".into())];
    }
    assert!(prepare(job).is_err());
    Ok(())
}

#[test]
fn probabilistic_is_reproducible_across_routing_sorting_and_budgets() -> Result<()> {
    let mut text = String::from("id,k,payload\n");
    for i in 0..30000 {
        text.push_str(&format!("{i},unique-{i},{}\n", "x".repeat(256)));
    }
    let (_dir, mut job) = setup(&text)?;
    job.operations = vec![Operation::AssignProbabilistic {
        groups: allocations(),
        strata: vec![Column::Name("k".into())],
    }];
    let (a, reference) = run(job.clone())?;
    assert!(a.diagnostics["routed_groupings"].as_u64().unwrap() > 0);
    let membership = ids(&reference);
    for group in &membership {
        assert!(group.windows(2).all(|w| w[0] < w[1]));
    }
    let mut all: Vec<_> = membership.into_iter().flatten().collect();
    all.sort_unstable();
    assert_eq!(all, (0..30000).collect::<Vec<_>>());
    job.resources.grouping = Grouping::Sort;
    let (sorted, actual) = run(job.clone())?;
    assert!(sorted.diagnostics["sort_runs"].as_u64().unwrap() > 0);
    assert_eq!(actual, reference);
    job.resources.memory_mb = 64.into();
    job.resources.workers = 2;
    assert_eq!(run(job)?.1, reference);
    Ok(())
}

#[test]
fn new_options_compose_with_exact_operations_and_repeat_across_budgets() -> Result<()> {
    let mut text = String::from("id,country,segment\n");
    for i in 0..120 {
        text.push_str(&format!(
            "{i},{},{}\n",
            if i % 2 == 1 { "US" } else { "GB" },
            i % 3
        ));
    }
    let (_dir, mut job) = setup(&text)?;
    job.operations = vec![
        fisher(),
        Operation::Interleaved { files: 2 },
        Operation::AssignProbabilistic {
            groups: allocations(),
            strata: vec![Column::Name("segment".into())],
        },
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
    ];
    let (analysis, reference) = run(job.clone())?;
    assert_eq!(analysis.stages.len(), 4);
    assert_eq!(analysis.output_files, 4);
    assert_eq!(analysis.diagnostics["fisher_yates_calls"], 1);
    assert_eq!(analysis.diagnostics["fisher_yates_rows"], 120);
    assert!(
        analysis.diagnostics["fisher_yates_seconds"]
            .as_f64()
            .unwrap()
            >= 0.0
    );
    let mut all: Vec<_> = ids(&reference).into_iter().flatten().collect();
    all.sort_unstable();
    assert_eq!(all, (0..120).collect::<Vec<_>>());
    job.resources.memory_mb = 64.into();
    job.resources.workers = 2;
    assert_eq!(run(job.clone())?.1, reference);
    job.operations = vec![Operation::Balanced { files: 2 }, fisher()];
    let (analysis, files) = run(job)?;
    assert_eq!(analysis.diagnostics["fisher_yates_calls"], 2);
    assert_eq!(analysis.diagnostics["fisher_yates_rows"], 120);
    assert_eq!(analysis.diagnostics["sort_calls"], 0);
    let groups = ids(&files);
    assert!(groups[0].iter().all(|id| *id < 60));
    assert!(groups[1].iter().all(|id| *id >= 60));
    Ok(())
}

#[test]
fn mixed_group_shuffle_spills_only_large_groups_and_preserves_budget_worker_parity() -> Result<()> {
    let large = 18_000;
    let small = 24;
    let payload = "x".repeat(600);
    let mut text = String::from("id,k,payload\n");
    for id in 0..large + small {
        let key = if id < small {
            format!("small{}", id / 3)
        } else {
            "large".into()
        };
        text.push_str(&format!("{id},{key},{payload}\n"));
    }
    let (_dir, mut job) = setup(&text)?;
    job.operations = vec![
        Operation::Partition {
            columns: vec![Column::Name("k".into())],
        },
        // Retain groups before shuffling, exercising per-group selection rather
        // than the separate fused partition/random-key sort.
        Operation::Interleaved { files: 1 },
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Balanced { files: 2 },
    ];
    let mut reference = None;
    let mut stages = None;
    let mut digest = None;
    for (memory, workers) in [(128, 1), (32, 1), (32, 4)] {
        job.resources.memory_mb = memory.into();
        job.resources.workers = workers;
        let (analysis, files) = run(job.clone())?;
        assert_eq!(analysis.output_files, 18);
        assert!(analysis.diagnostics["resident_sorts"].as_u64().unwrap() >= 8);
        assert_eq!(
            analysis.diagnostics["sort_runs"].as_u64().unwrap() > 0,
            memory == 32
        );
        assert_eq!(
            analysis.diagnostics["workspace_reserved_bytes"],
            analysis.preview.reserved_bytes()
                + analysis.warnings.reserved_bytes()
                + analysis.timings.reserved_bytes()
                + analysis.diagnostics.reserved_bytes()
                + analysis.text_reserved_bytes()
                + analysis.stages.reserved_bytes()
                + analysis.column_values.reserved_bytes()
                + analysis.diagnostics["prepared_job_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["temporary_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["directory_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + analysis.diagnostics["input_header_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        );
        let actual_stages = serde_json::to_value(&analysis.stages)?;
        if let Some(reference) = &reference {
            assert_eq!(&files, reference);
            assert_eq!(stages.as_ref(), Some(&actual_stages));
            assert_eq!(digest.as_ref(), Some(&analysis.logical_digest));
        } else {
            let groups = ids(&files);
            let mut conserved = groups.iter().flatten().copied().collect::<Vec<_>>();
            conserved.sort_unstable();
            assert_eq!(conserved, (0..large + small).collect::<Vec<_>>());
            assert!(groups[..2].iter().flatten().all(|id| *id >= small));
            for (index, pair) in groups[2..].as_chunks::<2>().0.iter().enumerate() {
                assert!(pair.iter().flatten().all(|id| *id / 3 == index as u64));
            }
            reference = Some(files);
            stages = Some(actual_stages);
            digest = Some(analysis.logical_digest);
        }
    }
    Ok(())
}

#[test]
fn resident_shuffle_rejects_oversized_groups_without_publishing() -> Result<()> {
    let mut text = String::from("id,payload\n");
    for i in 0..30000 {
        text.push_str(&format!("{i},{}\n", "x".repeat(256)));
    }
    let (_dir, mut job) = setup(&text)?;
    job.operations = vec![fisher()];
    let error = prepare(job.clone()).err().unwrap();
    assert!(format!("{error:#}").contains("resident shuffle memory budget"));
    assert!(!Path::new(&job.output).exists());
    job.resources.memory_mb = 64.into();
    let (analysis, files) = run(job)?;
    assert_eq!(analysis.diagnostics["sort_runs"], 0);
    assert_eq!(ids(&files)[0].len(), 30000);
    Ok(())
}

#[test]
fn new_ingestion_paths_still_reject_malformed_csv() -> Result<()> {
    for operation in [
        fisher(),
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Interleaved { files: 1 },
        Operation::AssignProbabilistic {
            groups: allocations(),
            strata: vec![],
        },
    ] {
        let (_dir, mut job) = setup("id\n\"unterminated")?;
        job.operations = vec![operation];
        assert!(prepare(job.clone()).is_err());
        assert!(!Path::new(&job.output).exists());
    }
    Ok(())
}

#[test]
fn streaming_router_falls_back_for_many_destinations_without_changing_membership() -> Result<()> {
    let mut text = String::from("id,k\n");
    for i in 0..1000 {
        text.push_str(&format!("{i},x\n"));
    }
    let (_dir, mut job) = setup(&text)?;
    job.operations = vec![Operation::Interleaved { files: 70 }];
    let (a, reference) = run(job.clone())?;
    assert_eq!(a.diagnostics["routing_fallbacks"], 1);
    assert!(a.diagnostics["routing_reused_runs"].as_u64().unwrap() > 0);
    for (index, group) in ids(&reference).iter().enumerate() {
        assert_eq!(*group, (index as u64..1000).step_by(70).collect::<Vec<_>>());
    }
    job.resources.grouping = Grouping::Sort;
    assert_eq!(run(job)?.1, reference);
    Ok(())
}
