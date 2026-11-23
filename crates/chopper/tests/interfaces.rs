use std::{
    fs,
    process::{Command, Stdio},
};

#[test]
fn cli_requires_confirmation_and_runs_configured_job() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.csv");
    fs::write(&input, "id\n1\n2\n3\n").unwrap();
    let output = temp.path().join("result");
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--input"])
        .arg(&input)
        .arg("--output")
        .arg(&output)
        .args(["--rows", "2"])
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("--yes"));
    assert!(!output.exists());
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--input"])
        .arg(&input)
        .arg("--output")
        .arg(&output)
        .args(["--rows", "2", "--yes"])
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let analysis: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(analysis["output_files"], 2);
    assert!(output.join("manifest.jsonl").is_file());
}

#[test]
fn cli_run_requires_confirmation_before_reading_input() {
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("job.json");
    fs::write(
        &config,
        serde_json::json!({
            "input": temp.path().join("missing.csv"),
            "output": temp.path().join("result")
        })
        .to_string(),
    )
    .unwrap();
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .arg("run")
        .arg("--config")
        .arg(config)
        .stdin(Stdio::null())
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("requires --yes"));
    assert!(result.stdout.is_empty());
    assert!(!temp.path().join("result").exists());
}

#[test]
fn cli_rejects_obsolete_saved_jobs_before_input_io() {
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("obsolete.json");
    let output = temp.path().join("result");
    for operation in [
        serde_json::json!({"type":"shuffle","strategy":"buffer"}),
        serde_json::json!({"type":"shuffle","strategy":"radix"}),
        serde_json::json!({"type":"shuffle","strategy":"prefix_distribution"}),
        serde_json::json!({"type":"shuffle","strategy":"uniform","buffer_rows":7}),
    ] {
        fs::write(
            &config,
            serde_json::json!({"input":"missing.csv","output":output,"operations":[operation]})
                .to_string(),
        )
        .unwrap();
        for command in ["analyze", "run"] {
            let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
                .arg(command)
                .arg("--config")
                .arg(&config)
                .stdin(Stdio::null())
                .output()
                .unwrap();
            assert!(!result.status.success());
            let error = String::from_utf8_lossy(&result.stderr);
            assert!(
                error.contains("unknown variant `buffer`")
                    || error.contains("unknown variant `radix`")
                    || error.contains("unknown variant `prefix_distribution`")
                    || error.contains("unknown field `buffer_rows`"),
                "{error}"
            );
            assert!(!output.exists());
        }
    }
}

fn removed_experiment_requests() -> Vec<(serde_json::Value, &'static str)> {
    let mut cases = Vec::new();
    for _ in [0] {
        for (field, value, expected) in [
            (
                "full_shuffle_algorithm",
                serde_json::json!("independent_buckets_v1"),
                "unknown variant `independent_buckets_v1`",
            ),
            (
                "full_shuffle_rng",
                serde_json::json!("blake3_xof_v1"),
                "unknown variant `blake3_xof_v1`",
            ),
            (
                "resources",
                serde_json::json!({"shuffle_rng_buffer_bytes":64}),
                "unknown field `shuffle_rng_buffer_bytes`",
            ),
        ] {
            let mut body = serde_json::json!({"input":"missing.csv"});
            body[field] = value;
            cases.push((body, expected));
        }
    }
    cases
}
#[test]
fn cli_rejects_removed_experiments_before_input_io() {
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("obsolete.json");
    for (mut body, expected) in removed_experiment_requests() {
        let output = temp.path().join("result");
        body["output"] = serde_json::json!(output);
        fs::write(&config, body.to_string()).unwrap();
        for command in ["analyze", "run"] {
            let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
                .arg(command)
                .arg("--config")
                .arg(&config)
                .stdin(Stdio::null())
                .output()
                .unwrap();
            assert!(!result.status.success());
            let error = String::from_utf8_lossy(&result.stderr);
            assert!(error.contains(expected), "{error}");
            assert!(!output.exists());
        }
    }
}

#[test]
fn analyze_returns_input_statistics_without_executing_the_pipeline() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.csv");
    let output = temp.path().join("result");
    let config = temp.path().join("job.json");
    fs::write(&input, "id\n1\n2\n3\n").unwrap();
    fs::write(
        &config,
        serde_json::json!({
            "input":input,"output":output,"operations":[{"type":"balanced","files":100}],
            "resources":{"memory_mb":32,"workers":1,"max_record_bytes":1024}
        })
        .to_string(),
    )
    .unwrap();
    let analyze = || {
        Command::new(env!("CARGO_BIN_EXE_chopper"))
            .args(["analyze", "--config"])
            .arg(&config)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    };
    let result = analyze();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let statistics: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(statistics["rows"], 3);
    assert!(statistics.get("output_files").is_none());
    assert!(!output.exists());
    let run = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--yes", "--config"])
        .arg(&config)
        .output()
        .unwrap();
    assert!(
        !run.status.success(),
        "Run must enforce exact group feasibility"
    );
    assert!(!output.exists());
    fs::write(&input, "id\n1\n2\n").unwrap();
    let changed = analyze();
    assert!(changed.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&changed.stdout).unwrap()["rows"],
        2
    );
    assert!(!output.exists());
}
