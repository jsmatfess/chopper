#![cfg(not(target_os = "wasi"))]

use chopper::job::{
    Allocation, CalculatedColumn, Column, Compression, ExecutionControl, Job, JobSettings, Limits,
    Operation, Pipeline, Resources, Shuffle,
};
use serde_json::{json, Value};
use std::{
    fs,
    io::{BufWriter, Read, Write},
    path::Path,
    process::Command,
    thread,
    time::{Duration, Instant},
};

#[test]
fn composed_job_publishes_capped_files_and_replays_from_cli() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let input = root.path().join("input.csv");
    fs::write(&input, "id,country\r\n1,CA\r\n2,US\r\n3,CA\r\n4,US\r\n")?;
    let partition =
        Pipeline::default().then(Operation::partition(vec![Column::Name("country".into())]));
    let pipeline = partition.then(Operation::shuffle(Shuffle::Uniform));
    let job = Job::new(JobSettings {
        operations: pipeline.into_operations(),
        limits: Limits {
            bytes: Some(18),
            ..Limits::default()
        },
        ..JobSettings::for_files(
            input.to_str().unwrap(),
            root.path().join("rust").to_str().unwrap(),
        )
    });

    let report = job.run(None)?;
    assert_eq!(
        (
            report.rows,
            report.columns,
            report.groups,
            report.output_files
        ),
        (4, 2, 2, 4)
    );
    assert_eq!(
        report.manifest_path,
        root.path().join("rust/manifest.jsonl")
    );
    check_manifest(&report.manifest_path, Some(report.output_csv_bytes))?;

    let recipes = root.path().join("recipes");
    fs::create_dir(&recipes)?;
    Job::new(JobSettings {
        input: "input.csv".into(),
        output: "cli".into(),
        ..job.settings().clone()
    })
    .save(recipes.join("job.json"))?;
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .current_dir(root.path())
        .args(["run", "--config", "recipes/job.json", "--yes", "--summary"])
        .output()?;
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    check_manifest(&root.path().join("cli/manifest.jsonl"), None)
}

fn check_manifest(manifest: &Path, expected_bytes: Option<u64>) -> anyhow::Result<()> {
    let mut rows = Vec::new();
    let mut bytes = 0;
    for line in fs::read_to_string(manifest)?.lines().skip(1) {
        let entry: serde_json::Value = serde_json::from_str(line)?;
        assert_eq!(entry["type"], "output");
        let csv = fs::read_to_string(
            manifest
                .parent()
                .unwrap()
                .join(entry["path"].as_str().unwrap()),
        )?;
        assert!(csv.len() <= 18);
        assert_eq!(entry["csv_bytes"], csv.len() as u64);
        assert_eq!(entry["rows"], 1);
        bytes += csv.len() as u64;
        let mut lines = csv.lines();
        assert_eq!(lines.next(), Some("id,country"));
        let row = lines.next().unwrap();
        assert!(lines.next().is_none());
        let (_, country) = row.split_once(',').unwrap();
        assert_eq!(entry["lineage"][0]["values"][0], country);
        rows.push(row.to_owned());
    }
    rows.sort();
    assert_eq!(rows, ["1,CA", "2,US", "3,CA", "4,US"]);
    if let Some(expected) = expected_bytes {
        assert_eq!(bytes, expected);
    }
    Ok(())
}

#[test]
fn reusable_pipeline_round_trips_all_operations_and_preserves_column_types() -> anyhow::Result<()> {
    let prefix = Pipeline::new().then(Operation::partition(vec![Column::Name("0".into())]));
    let split = Pipeline::new()
        .then(Operation::balanced(2))
        .then(Operation::interleaved(2));
    let alloc = || {
        vec![Allocation {
            name: "left".into(),
            percent: "100".into(),
        }]
    };
    let assigned = prefix
        .then(Operation::assign(alloc(), vec![Column::Index(0)]))
        .then(Operation::assign_probabilistic(alloc(), vec![]));
    let complete = assigned
        .then(Operation::shuffle(Shuffle::Uniform))
        .then(split);
    let sibling = prefix.then(Operation::partition(vec![Column::Index(0)]));
    assert_eq!(prefix.operations().len(), 1);
    assert_eq!(sibling.operations().len(), 2);
    assert_eq!(assigned.operations().len(), 3);

    let root = tempfile::tempdir()?;
    let saved = root.path().join("all-operations.json");
    let complete = Job::new(JobSettings {
        input: "sample.csv".into(),
        output: "out".into(),
        operations: complete.into_operations(),
        ..JobSettings::default()
    });
    complete.validate()?;
    complete.save(&saved)?;
    let original = fs::read(&saved)?;
    assert_eq!(complete.save(&saved).unwrap_err().code(), "config_write");
    assert_eq!(fs::read(&saved)?, original);
    let loaded = Job::load(saved)?;
    let expected = json!([
        {"type":"partition", "columns":["0"]},
        {"type":"assign", "groups":[{"name":"left","percent":"100"}], "strata":[0]},
        {"type":"assign_probabilistic", "groups":[{"name":"left","percent":"100"}], "strata":[]},
        {"type":"shuffle", "strategy":"uniform"},
        {"type":"balanced", "files":2},
        {"type":"interleaved", "files":2}
    ]);
    assert_eq!(
        serde_json::to_value(&loaded.settings().operations)?,
        expected
    );
    Ok(())
}

#[test]
fn loaded_jobs_keep_dialect_calculations_and_limits_with_gzip_and_zip_input() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    let fixture = b"id\t0\tqty\r\nx\tCA\t2\r\nx\tUS\t3\r\n";
    for extension in ["gz", "zip"] {
        let input = root.path().join(format!("input.csv.{extension}"));
        let file = fs::File::create(&input)?;
        let zip_member = if extension == "zip" {
            let mut archive = zip::ZipWriter::new(file);
            archive.start_file(
                "table.csv",
                zip::write::SimpleFileOptions::default()
                    .compression_method(zip::CompressionMethod::Deflated),
            )?;
            archive.write_all(fixture)?;
            archive.finish()?;
            Some("table.csv".into())
        } else {
            let mut gzip = flate2::write::GzEncoder::new(file, flate2::Compression::default());
            gzip.write_all(fixture)?;
            gzip.finish()?;
            None
        };
        let output = root.path().join(extension);
        let mut settings = JobSettings {
            input: input.to_str().unwrap().into(),
            output: output.to_str().unwrap().into(),
            zip_member,
            operations: Pipeline::new()
                .then(Operation::partition(vec![Column::Name("0".into())]))
                .into_operations(),
            calculated_columns: vec![CalculatedColumn {
                name: "twice".into(),
                expression: "NUMBER(qty) * 2".into(),
            }],
            compression: Compression::Gzip,
            limits: Limits {
                bytes: Some(30),
                rows: Some(1),
                compressed_bytes: None,
            },
            resources: Resources {
                memory_mb: 64.into(),
                workers: 1,
                max_files: 10,
                max_record_bytes: 4096,
                ..Resources::default()
            },
            ..JobSettings::default()
        };
        settings.input_csv.delimiter = '\t';
        settings.output_csv.delimiter = '|';
        let requested = serde_json::to_value(&settings)?;
        let saved = root.path().join(format!("{extension}.json"));
        Job::new(settings).save(&saved)?;
        let loaded = Job::load(saved)?;
        assert_eq!(serde_json::to_value(loaded.settings())?, requested);
        let report = loaded.run(None)?;
        assert_eq!((report.rows, report.groups, report.output_files), (2, 2, 2));
        let mut outputs = Vec::new();
        for line in fs::read_to_string(&report.manifest_path)?.lines().skip(1) {
            let entry: Value = serde_json::from_str(line)?;
            let path = output.join(entry["path"].as_str().unwrap());
            let mut csv = String::new();
            flate2::read::GzDecoder::new(fs::File::open(path)?).read_to_string(&mut csv)?;
            assert_eq!(entry["csv_bytes"], csv.len() as u64);
            assert!(csv.len() <= 30);
            let mut lines = csv.lines();
            assert_eq!(lines.next(), Some("id|0|qty|twice"));
            let row = lines.next().unwrap();
            assert_eq!(
                entry["lineage"][0]["values"][0],
                row.split('|').nth(1).unwrap()
            );
            outputs.push(row.to_owned());
        }
        outputs.sort();
        assert_eq!(outputs, ["x|CA|2|4", "x|US|3|6"]);
    }
    Ok(())
}

#[test]
fn validation_analysis_and_run_return_structured_outcomes() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let input = root.path().join("input.csv");
    let output = root.path().join("out");
    let temp = root.path().join("temp");
    let settings = JobSettings {
        input: input.to_str().unwrap().into(),
        output: output.to_str().unwrap().into(),
        resources: Resources {
            temp_dir: Some(temp.to_str().unwrap().into()),
            ..Resources::default()
        },
        operations: vec![Operation::partition(vec![Column::Name("country".into())])],
        limits: Limits {
            bytes: Some(18),
            ..Limits::default()
        },
        ..JobSettings::default()
    };
    let job = Job::new(settings.clone());
    job.validate()?;
    assert_eq!(root.path().read_dir()?.count(), 0);
    let invalid = Job::new(JobSettings {
        limits: Limits {
            bytes: Some(0),
            ..Limits::default()
        },
        ..settings.clone()
    });
    let error = invalid.validate().unwrap_err();
    assert_eq!(error.code(), "invalid_config");
    assert_eq!(error.path(), Some("/limits/bytes"));
    assert!(!error.to_string().is_empty());
    assert_eq!(invalid.run(None).unwrap_err().code(), error.code());
    assert_eq!(invalid.analyze(None).err().unwrap().code(), error.code());
    assert_eq!(root.path().read_dir()?.count(), 0);

    let error = Job::from_json("{\"resources\": {\"memory_mb\": false}}")
        .err()
        .unwrap();
    assert_eq!(error.code(), "json_schema");
    assert_eq!(error.path(), Some("/resources/memory_mb"));
    assert_eq!(error.line(), Some(1));
    assert!(error.column().is_some());
    assert_eq!(Job::from_json("{").err().unwrap().code(), "json_syntax");

    fs::create_dir(&temp)?;
    fs::write(&input, "id,country\n1,CA\n2,US\n")?;
    let profile = job.analyze(None)?;
    assert_eq!(profile.rows(), 2);
    assert_eq!(profile.columns(), 2);
    assert_eq!(profile.stages()[0].input_distinct_keys, Some(2));
    assert!(profile.stages()[0].distinct_exact);
    assert!(!output.exists());
    assert_eq!(temp.read_dir()?.count(), 0);

    // An occupied destination survives early rejection. Run must also reject a
    // replacement input record whose serialized bytes cannot fit the cap.
    fs::create_dir(&output)?;
    fs::write(output.join("sentinel"), "keep")?;
    let error = job.run(None).unwrap_err();
    assert_eq!(error.code(), "destination");
    assert_eq!(fs::read_to_string(output.join("sentinel"))?, "keep");
    fs::remove_file(output.join("sentinel"))?;
    fs::write(&input, "id,country\n1234567890,US\n")?;
    assert_eq!(job.run(None).unwrap_err().code(), "record_limit");
    assert_eq!(output.read_dir()?.count(), 0);
    assert_eq!(temp.read_dir()?.count(), 0);

    fs::write(&input, "id,country\n1,CA\n2,US\n3,CA\n")?;
    assert_eq!(job.run(None)?.rows, 3);
    Ok(())
}

#[test]
fn controls_cancel_live_jobs_without_affecting_other_executions() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let input = root.path().join("many.csv");
    let mut fixture = BufWriter::new(fs::File::create(&input)?);
    writeln!(fixture, "id,country")?;
    for row in 0..300_000 {
        writeln!(fixture, "{row},CA")?;
    }
    fixture.flush()?;
    drop(fixture);
    let settings = |name: &str| JobSettings {
        input: input.to_str().unwrap().into(),
        output: root.path().join(name).to_str().unwrap().into(),
        operations: vec![Operation::shuffle(Shuffle::Uniform)],
        resources: Resources {
            memory_mb: 64.into(),
            workers: 1,
            temp_dir: Some(root.path().join("temp").to_str().unwrap().into()),
            max_record_bytes: 4096,
            ..Resources::default()
        },
        ..JobSettings::default()
    };
    let temp = root.path().join("temp");
    fs::create_dir(&temp)?;
    let analyze = Job::new(settings("analyze"));
    let analyze_control = ExecutionControl::new();
    thread::scope(|scope| {
        let scanning = scope.spawn(|| analyze.analyze(Some(&analyze_control)));
        wait_for_rows(&analyze_control);
        analyze_control.cancel();
        assert_eq!(scanning.join().unwrap().err().unwrap().code(), "cancelled");
    });
    assert!(!root.path().join("analyze").exists());
    assert_eq!(temp.read_dir()?.count(), 0);

    let first = Job::new(settings("cancelled"));
    let second = Job::new(settings("completed"));
    let first_control = ExecutionControl::new();
    let second_control = ExecutionControl::new();
    let completed = thread::scope(|scope| -> anyhow::Result<_> {
        let cancelling = scope.spawn(|| first.run(Some(&first_control)));
        let completing = scope.spawn(|| second.run(Some(&second_control)));
        wait_for_rows(&first_control);
        wait_for_rows(&second_control);
        first_control.cancel();
        assert_eq!(cancelling.join().unwrap().unwrap_err().code(), "cancelled");
        Ok(completing.join().unwrap()?)
    })?;
    assert_eq!(first_control.progress().phase.as_str(), "Cancelled");
    assert_eq!(first_control.progress().temp_bytes, 0);
    assert_eq!(second_control.progress().phase.as_str(), "Complete");
    assert_eq!(second_control.progress().rows, 300_000);
    assert_eq!(
        first.run(Some(&first_control)).unwrap_err().code(),
        "control_in_use"
    );
    assert!(!root.path().join("cancelled").exists());
    second_control.cancel();
    assert_eq!(completed.rows, 300_000);
    assert!(completed.manifest_path.is_file());
    assert_eq!(temp.read_dir()?.count(), 0);
    assert_eq!(root.path().read_dir()?.count(), 3);
    Ok(())
}

fn wait_for_rows(control: &ExecutionControl) {
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        let progress = control.progress();
        assert!(
            !matches!(progress.phase.as_str(), "Complete" | "Failed" | "Cancelled"),
            "{progress:?}"
        );
        if progress.rows > 0 {
            return;
        }
        assert!(Instant::now() < deadline, "no live progress: {progress:?}");
        thread::sleep(Duration::from_millis(1));
    }
}
