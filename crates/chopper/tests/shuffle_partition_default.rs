use anyhow::Result;
use chopper::{core::*, engine, resources::MemoryPool};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    sync::{atomic::AtomicBool, Arc},
};
fn fixture(rows: usize, width: usize) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let mut text = String::from("id,key,text\n");
    for id in 0..rows {
        text.push_str(&format!("{id},{},{}\n", id % 7, "x".repeat(width)));
    }
    fs::write(&input, text)?;
    Ok((
        dir,
        Job {
            input: input.to_string_lossy().into(),
            random_seed: Some("adaptive-contract".into()),
            resources: Resources {
                memory_mb: 32.into(),
                workers: 1,
                max_record_bytes: 1048576,
                ..Default::default()
            },
            ..Default::default()
        },
    ))
}
fn run(job: Job) -> Result<engine::Analysis> {
    engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}
fn inspect(path: &str) -> Result<(BTreeSet<usize>, BTreeMap<String, usize>)> {
    let mut ids = BTreeSet::new();
    let mut counts = BTreeMap::new();
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        if entry.path().extension().is_some_and(|x| x == "csv") {
            let text = fs::read_to_string(entry.path())?;
            let mut group = None;
            for row in text.lines().skip(1) {
                let fields = row.split(',').collect::<Vec<_>>();
                assert!(ids.insert(fields[0].parse()?));
                assert!(group.as_ref().is_none_or(|x| x == fields[1]));
                group = Some(fields[1].to_owned());
                *counts.entry(fields[1].to_owned()).or_default() += 1;
            }
        }
    }
    Ok((ids, counts))
}
#[test]
fn fused_auto_partition_preserves_membership_stages_and_caps() -> Result<()> {
    for downstream in [false, true] {
        let (_dir, mut job) = fixture(700, 31)?;
        job.output = std::path::Path::new(&job.input)
            .with_file_name("result")
            .to_string_lossy()
            .into();
        job.operations = vec![
            Operation::Shuffle {
                strategy: Shuffle::Auto,
            },
            Operation::Partition {
                columns: vec![Column::Name("key".into())],
            },
        ];
        if downstream {
            job.operations.push(Operation::Balanced { files: 2 });
        }
        job.limits.rows = Some(if downstream { 60 } else { 17 });
        job.limits.bytes = Some(if downstream { 4096 } else { 1000 });
        let pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
        let result = engine::run_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        assert_eq!(result.rows, 700);
        assert_eq!(result.stages[0].output_groups, 1);
        assert_eq!(result.stages[1].output_groups, 7);
        if downstream {
            assert_eq!(result.stages[2].output_groups, 14);
        }
        let (ids, counts) = inspect(&job.output)?;
        assert_eq!(ids, (0..700).collect());
        assert_eq!(counts.values().copied().collect::<Vec<_>>(), vec![100; 7]);
        for entry in fs::read_dir(&job.output)? {
            let entry = entry?;
            if entry.path().extension().is_some_and(|x| x == "csv") {
                let text = fs::read_to_string(entry.path())?;
                assert!(text.lines().count() <= if downstream { 61 } else { 18 });
                assert!(text.len() <= if downstream { 4096 } else { 1000 });
            }
        }
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, 0);
    }
    Ok(())
}
#[test]
fn automatic_shuffle_handles_a_parent_larger_than_resident_memory() -> Result<()> {
    let (_dir, mut job) = fixture(24000, 512)?;
    job.output = std::path::Path::new(&job.input)
        .with_file_name("result")
        .to_string_lossy()
        .into();
    job.operations = vec![Operation::Shuffle {
        strategy: Shuffle::Auto,
    }];
    let result = run(job.clone())?;
    assert_eq!(result.rows, 24000);
    assert!(result.diagnostics["sort_runs"].as_u64().unwrap() > 0);
    let text = fs::read_dir(&job.output)?
        .filter_map(Result::ok)
        .find(|e| e.path().extension().is_some_and(|x| x == "csv"))
        .unwrap();
    let ids = fs::read_to_string(text.path())?
        .lines()
        .skip(1)
        .map(|r| r.split(',').next().unwrap().parse::<usize>().unwrap())
        .collect::<BTreeSet<_>>();
    assert_eq!(ids, (0..24000).collect());
    Ok(())
}
