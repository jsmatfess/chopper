use serde_json::{json, Value};
use std::{fs, process::Command};

#[test]
fn analyze_summary_contains_only_scan_status_and_counts() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("PRIVATE_SOURCE.csv");
    let output = dir.path().join("PRIVATE_DESTINATION");
    let config = dir.path().join("PRIVATE_CONFIG.json");
    fs::write(
        &input,
        "PRIVATE_HEADER,other\nPRIVATE_VALUE,1\nPRIVATE_VALUE,2\n",
    )
    .unwrap();
    fs::write(
        &config,
        serde_json::to_vec(&json!({"input": input, "output": output})).unwrap(),
    )
    .unwrap();

    let analyze = |args: &[&str]| {
        let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .arg("analyze")
            .arg("--config")
            .arg(&config)
            .args(args)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        serde_json::from_slice::<Value>(&result.stdout).unwrap()
    };
    let summary = analyze(&["--summary"]);
    assert_eq!(
        summary,
        json!({"status": "analyzed", "rows": 2, "columns": 2})
    );
    let full = analyze(&[]);
    assert_eq!(full["header"][0], "PRIVATE_HEADER");
    assert_eq!(full["preview"][0][0], "PRIVATE_VALUE");
    assert!(full["auto_observations"].is_object());
    assert!(!output.exists());

    let advice = dir.path().join("summary.json");
    fs::write(&advice, serde_json::to_vec(&summary).unwrap()).unwrap();
    let run = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--config"])
        .arg(&config)
        .arg("--analysis")
        .arg(advice)
        .arg("--yes")
        .output()
        .unwrap();
    let stderr = String::from_utf8_lossy(&run.stderr);
    assert!(run.status.success(), "{stderr}");
    assert!(!stderr.contains("Analyze advice unavailable"), "{stderr}");
    let report: Value = serde_json::from_slice(&run.stdout).unwrap();
    assert_eq!(report["header"][0], "PRIVATE_HEADER");
    assert!(report["auto_plan"].is_object());
    assert!(output.join("manifest.jsonl").is_file());
}

#[test]
fn run_summary_reports_published_counts_in_all_run_forms() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("PRIVATE_SOURCE.csv");
    let csv = "PRIVATE_HEADER,other\nPRIVATE_PARTITION,PRIVATE_VALUE\n";
    fs::write(&input, csv).unwrap();

    for form in ["config", "ordered", "split"] {
        let output = dir.path().join(format!("PRIVATE_DESTINATION_{form}"));
        let mut command = Command::new(env!("CARGO_BIN_EXE_chopper"));
        match form {
            "config" => {
                let config = dir.path().join("PRIVATE_CONFIG.json");
                fs::write(
                    &config,
                    serde_json::to_vec(&json!({
                        "input": input,
                        "output": output,
                        "operations": [{"type": "partition", "columns": ["PRIVATE_HEADER"]}]
                    }))
                    .unwrap(),
                )
                .unwrap();
                command.args(["run", "--config"]).arg(config);
            }
            "ordered" => {
                command
                    .args(["run", "--input"])
                    .arg(&input)
                    .arg("--output")
                    .arg(&output)
                    .args([
                        "--step",
                        "partition",
                        "--summary",
                        "--column",
                        "PRIVATE_HEADER",
                    ]);
            }
            "split" => {
                command
                    .arg("split")
                    .arg(&input)
                    .arg("--output")
                    .arg(&output)
                    .args(["--by", "PRIVATE_HEADER"]);
            }
            _ => unreachable!(),
        }
        if form != "ordered" {
            command.arg("--summary");
        }
        let result = command.arg("--yes").output().unwrap();
        assert!(
            result.status.success(),
            "{form}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_eq!(
            serde_json::from_slice::<Value>(&result.stdout).unwrap(),
            json!({
                "status": "published", "rows": 1, "columns": 2, "groups": 1,
                "output_files": 1, "output_csv_bytes": csv.len()
            }),
            "{form}"
        );

        let manifest = fs::read_to_string(output.join("manifest.jsonl")).unwrap();
        for sentinel in [
            "PRIVATE_SOURCE",
            "PRIVATE_DESTINATION",
            "PRIVATE_HEADER",
            "PRIVATE_PARTITION",
        ] {
            assert!(manifest.contains(sentinel), "{form}: {sentinel}");
        }
        let csv_path = fs::read_dir(&output)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|path| path.extension().is_some_and(|extension| extension == "csv"))
            .unwrap();
        assert_eq!(fs::read_to_string(csv_path).unwrap(), csv, "{form}");
    }
}
