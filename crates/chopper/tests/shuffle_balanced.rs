//! Fusion must preserve the realized parent permutation, not merely conservation.
use anyhow::Result;
use chopper::{
    core::{csv::Parser, *},
    engine,
};
use serde_json::{json, Value};
use std::{
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

fn fixture(rows: usize, width: usize) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let mut text = String::from("id,text\n");
    for id in 0..rows {
        text.push_str(&format!("{id},\"界,{id}\"\"\n{}\"\n", "x".repeat(width)));
    }
    fs::write(&input, text)?;
    fs::create_dir(dir.path().join("temp"))?;
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("out").to_string_lossy().into(),
        random_seed: Some("fused-fy-balanced-contract".into()),
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
fn run(job: Job) -> Result<engine::Analysis> {
    engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}
type OutputGroups = Vec<(Vec<Value>, Vec<Vec<String>>)>;

fn outputs(job: &Job) -> Result<OutputGroups> {
    let mut groups: Vec<(Vec<Value>, Vec<Vec<String>>)> = Vec::new();
    for line in fs::read_to_string(Path::new(&job.output).join("manifest.jsonl"))?
        .lines()
        .skip(1)
    {
        let record: Value = serde_json::from_str(line)?;
        let path = Path::new(&job.output).join(record["path"].as_str().unwrap());
        assert_eq!(
            fs::metadata(&path)?.len(),
            record["csv_bytes"].as_u64().unwrap()
        );
        if let Some(limit) = job.limits.bytes {
            assert!(fs::metadata(&path)?.len() <= limit);
        }
        let mut parser = Parser::new(
            std::io::Cursor::new(fs::read(path)?),
            Default::default(),
            1048576,
        );
        assert_eq!(parser.next_record()?.unwrap(), ["id", "text"]);
        let mut rows = Vec::new();
        while let Some(row) = parser.next_record()? {
            rows.push(row);
        }
        assert_eq!(rows.len() as u64, record["rows"].as_u64().unwrap());
        if let Some(limit) = job.limits.rows {
            assert!(rows.len() as u64 <= limit);
        }
        let lineage: Vec<Value> = serde_json::from_value(record["lineage"].clone())?;
        if groups.last().is_some_and(|group| group.0 == lineage) {
            groups.last_mut().unwrap().1.extend(rows);
        } else {
            groups.push((lineage, rows));
        }
    }
    Ok(groups)
}
fn split(
    groups: Vec<(Vec<Value>, Vec<Vec<String>>)>,
    step: usize,
    files: usize,
) -> Vec<(Vec<Value>, Vec<Vec<String>>)> {
    let mut result = Vec::new();
    for (lineage, rows) in groups {
        let mut start = 0;
        for part in 0..files {
            let n = rows.len() / files + usize::from(part < rows.len() % files);
            let mut child = lineage.clone();
            child.push(json!({"operation":step,"part":part + 1}));
            result.push((child, rows[start..start + n].to_vec()));
            start += n;
        }
    }
    result
}
#[test]
fn fused_root_and_retained_ranges_preserve_realized_order_lineage_stats_and_caps() -> Result<()> {
    for retained in [false, true] {
        for leading_uniform in [false, true] {
            for downstream in [false, true] {
                let (dir, mut reference) = fixture(19, 8)?;
                if retained {
                    reference.operations.push(Operation::Balanced { files: 2 });
                }
                if leading_uniform {
                    reference.operations.push(Operation::Shuffle {
                        strategy: Shuffle::Uniform,
                    });
                }
                reference.operations.push(Operation::Shuffle {
                    strategy: Shuffle::FisherYates,
                });
                let step = reference.operations.len();
                let mut job = reference.clone();
                reference.output = dir.path().join("reference").to_string_lossy().into();
                run(reference.clone())?;
                let mut expected = split(outputs(&reference)?, step, 3);
                job.operations.push(Operation::Balanced { files: 3 });
                if downstream {
                    job.operations.push(Operation::Balanced { files: 2 });
                    expected = split(expected, step + 1, 2);
                }
                job.limits.rows = Some(7);
                job.limits.bytes = Some(4096);
                let analysis = run(job.clone())?;
                assert_eq!(outputs(&job)?, expected);
                assert_eq!(analysis.rows, 19);
                assert_eq!(analysis.groups, expected.len() as u64);
                assert_eq!(analysis.stages.len(), job.operations.len());
                for (index, stage) in analysis.stages.iter().enumerate() {
                    assert_eq!(stage.operation, index + 1);
                }
                let stage = &analysis.stages[step];
                assert_eq!(
                    (stage.input_groups, stage.output_groups),
                    (if retained { 2 } else { 1 }, if retained { 6 } else { 3 })
                );
                assert_eq!(
                    (stage.smallest_group, stage.largest_group),
                    if retained { (3, 4) } else { (6, 7) }
                );
                assert_eq!(
                    analysis.diagnostics["fisher_yates_calls"],
                    if retained { 2 } else { 1 }
                );
                assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
            }
        }
    }
    Ok(())
}
#[test]
fn fused_failures_never_publish_or_fall_back_from_resident_shuffle() -> Result<()> {
    for mode in ["rows", "cap", "resident"] {
        let (dir, mut job) = fixture(
            if mode == "resident" { 1000 } else { 19 },
            if mode == "resident" { 12000 } else { 8 },
        )?;
        job.operations = vec![
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
            },
            Operation::Balanced {
                files: if mode == "rows" { 32 } else { 3 },
            },
        ];
        if mode == "cap" {
            job.limits.bytes = Some(10);
        }
        let error = format!("{:#}", run(job.clone()).unwrap_err());
        assert!(
            error.contains(match mode {
                "rows" => "nonempty balanced",
                "cap" => "limit",
                _ => "Fisher",
            }),
            "{error}"
        );
        assert!(!Path::new(&job.output).exists());
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}
#[test]
fn cancellation_at_fused_traversal_cleans_all_owned_output() -> Result<()> {
    use chopper::observation::{physical::Kind, Status};
    let (dir, mut job) = fixture(19, 8)?;
    job.operations = vec![
        Operation::Shuffle {
            strategy: Shuffle::FisherYates,
        },
        Operation::Balanced { files: 3 },
    ];
    let cancel = Arc::new(AtomicBool::new(false));
    let stop = cancel.clone();
    let result = engine::run_with_observations(
        job.clone(),
        cancel,
        Arc::new(|_| {}),
        Arc::new(move |fact| {
            if fact.kind == Kind::FusedBalanced && fact.status == Status::Active {
                stop.store(true, Ordering::SeqCst);
            }
            true
        }),
    );
    assert!(format!("{:#}", result.unwrap_err()).contains("cancel"));
    assert!(!Path::new(&job.output).exists());
    assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    Ok(())
}

#[cfg(feature = "experimental-terminal-shuffle")]
#[test]
fn external_shuffle_direct_matches_snapshot_and_cleans_cancelled_output() -> Result<()> {
    let (dir, mut job) = fixture(100003, 256)?;
    job.operations = vec![
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Balanced { files: 7 },
    ];
    job.limits.rows = Some(20000);
    job.limits.bytes = Some(8 * 1024 * 1024);
    let mut snapshot = job.clone();
    snapshot.output = dir.path().join("snapshot").to_string_lossy().into();
    let expected = engine::prepare(
        snapshot.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?
    .execute()?;
    let actual = run(job.clone())?;
    assert_eq!(outputs(&job)?, outputs(&snapshot)?);
    assert_eq!(actual.logical_digest, expected.logical_digest);
    assert_eq!(
        serde_json::to_value(&actual.stages)?,
        serde_json::to_value(&expected.stages)?
    );
    assert_eq!(actual.output_csv_bytes, expected.output_csv_bytes);
    assert_eq!(actual.output_files, expected.output_files);
    fs::remove_dir_all(&job.output)?;
    let cancel = Arc::new(AtomicBool::new(false));
    let cancellation = cancel.clone();
    let error = engine::run(
        job.clone(),
        cancel,
        Arc::new(move |p| {
            if p.phase == "Finalizing direct terminal output" {
                cancellation.store(true, Ordering::Relaxed);
            }
        }),
    )
    .expect_err("cancel before publication");
    assert!(format!("{error:#}").contains("job cancelled"));
    assert!(!Path::new(&job.output).exists());
    assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    assert_eq!(
        fs::read_dir(dir.path())?.count(),
        3,
        "input, temp, snapshot only"
    );
    Ok(())
}
