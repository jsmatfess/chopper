use serde_json::{json, Value};
use std::{fs, process::Command};

#[test]
fn split_rejects_overflowing_memory_before_input() {
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args([
            "split",
            "missing.csv",
            "--output",
            "unused-output",
            "--memory-mb",
            "18446744073709551615",
            "--yes",
        ])
        .output()
        .unwrap();
    assert!(!result.status.success());
    let stderr = String::from_utf8_lossy(&result.stderr);
    assert!(stderr.contains("memory_mb must be between"), "{stderr}");
    assert!(!stderr.contains("panicked"), "{stderr}");
}

#[test]
fn automatic_cli_overrides_work_without_seed_input() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, "id\n1\n2\n").unwrap();
    let config = dir.path().join("job.json");
    for command in ["run", "analyze", "split"] {
        let output = dir.path().join(command);
        fs::write(
            &config,
            json!({"input":input,"output":output,"resources":{"memory_mb":512,"workers":3,"max_record_bytes":1048576}})
            .to_string(),
        )
        .unwrap();
        let mut cli = Command::new(env!("CARGO_BIN_EXE_chopper"));
        cli.env("CHOPPER_MEMORY_LIMIT_MB", "64").arg(command);
        if command == "split" {
            cli.arg(&input).arg("--output").arg(&output);
        } else {
            cli.arg("--config").arg(&config);
        }
        cli.args(["--memory-mb", "auto", "--workers", "1"]);
        if command != "analyze" {
            cli.arg("--yes");
        }
        let result = cli.output().unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        let analysis: Value = serde_json::from_slice(&result.stdout).unwrap();
        if command == "analyze" {
            assert_eq!(analysis["rows"], 2);
            assert!(analysis.get("output_files").is_none());
            assert!(analysis.get("seed").is_none());
            assert!(!output.exists());
            continue;
        }
        // Scripted decoding now retains a positive, sub-half-MiB source grant
        // while Auto observes headroom. The unchanged floor(F/(MiB/2)) formula
        // resolves 127 MiB; split keeps its separate caller-construction path.
        let expected_mb = if command == "split" { 128 } else { 127 };
        assert_eq!(analysis["memory_budget_bytes"], expected_mb * 1024 * 1024);
        assert_eq!(analysis["workers"], 1);
        assert_eq!(
            analysis["algorithm_version"],
            chopper::core::ALGORITHM_VERSION
        );
        assert!(analysis["seed"].as_str().unwrap().len() == 64);
        if command != "analyze" {
            let manifest = fs::read_to_string(output.join("manifest.jsonl")).unwrap();
            let record: Value = manifest
                .lines()
                .map(|s| serde_json::from_str::<Value>(s).unwrap())
                .find(|v| v["type"] == "job")
                .unwrap();
            assert_eq!(record["config"]["resources"]["memory_mb"], "auto");
            assert!(record["config"].get("seed").is_none());
            assert_eq!(record["algorithm_version"], analysis["algorithm_version"]);
        }
    }
}

#[test]
fn omitted_resources_and_explicit_advanced_values_are_effective() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let source = directory.path().join("input.csv");
    fs::write(&source, "id\n1\n2\n3\n4\n")?;
    for (name, overrides) in [
        ("default", &[][..]),
        ("advanced", &["--memory-mb", "128", "--workers", "2"][..]),
    ] {
        let output = directory.path().join(name);
        let run = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .env("CHOPPER_MEMORY_LIMIT_MB", "256")
            .args(["run", "--input"])
            .arg(&source)
            .arg("--output")
            .arg(&output)
            .args(["--rows", "1", "--yes"])
            .args(overrides)
            .output()?;
        assert!(
            run.status.success(),
            "{}",
            String::from_utf8_lossy(&run.stderr)
        );
        let report: Value = serde_json::from_slice(&run.stdout)?;
        assert_eq!(report["rows"], 4);
        assert_eq!(report["auto_plan"]["version"], 2);
        assert_eq!(
            report["auto_plan"]["effective_workers"],
            if name == "default" { 1 } else { 2 }
        );
        assert_eq!(
            report["auto_plan"]["effective_memory_bytes"],
            if name == "default" { 256 } else { 128 } * 1024 * 1024
        );
        assert_eq!(report["auto_plan"]["measurements"]["peak_writer_slots"], 1);
    }
    Ok(())
}

#[test]
fn prepared_publication_uses_bounded_writers_and_matching_analysis_can_limit_workers(
) -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let source = directory.path().join("input.csv");
    let config = directory.path().join("job.json");
    let profile = directory.path().join("profile.json");
    fs::write(&source, "id\n1\n2\n3\n4\n")?;
    let run = |action: &str, extras: &[&str]| -> anyhow::Result<Value> {
        let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .env("CHOPPER_MEMORY_LIMIT_MB", "256")
            .arg(action)
            .arg("--config")
            .arg(&config)
            .args(extras)
            .output()?;
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        Ok(serde_json::from_slice(&result.stdout)?)
    };
    for (name, workers) in [("explicit", 2), ("auto", 0)] {
        if workers == 0 && cfg!(windows) {
            continue;
        }
        fs::write(
            &config,
            json!({
                "input": source, "output": directory.path().join(name),
                "operations": [{"type": "shuffle", "strategy": "uniform"}],
                "compression": "gzip", "limits": {"rows": 1},
                "resources": {"memory_mb": 256, "workers": workers}
            })
            .to_string(),
        )?;
        let result = if workers == 0 {
            fs::write(&profile, run("analyze", &[])?.to_string())?;
            run("run", &["--analysis", profile.to_str().unwrap(), "--yes"])?
        } else {
            run("run", &["--yes"])?
        };
        assert_eq!(result["output_files"], 4);
        let plan = &result["auto_plan"];
        if workers == 0 {
            assert_eq!(plan["worker_limit_from_analyze"], true);
            assert_eq!(plan["effective_workers"], 1);
            assert_eq!(plan["measurements"]["peak_writer_slots"], 1);
        } else {
            assert_eq!(plan["effective_workers"], 2);
            assert_eq!(plan["measurements"]["peak_writer_slots"], 2);
        }
    }
    Ok(())
}
