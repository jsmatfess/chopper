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
