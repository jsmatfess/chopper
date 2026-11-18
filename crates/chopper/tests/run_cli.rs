//! Real CLI coverage: ordering, Job manifest parity, prompt and failure cleanup.
use serde_json::Value;
use std::{
    fs,
    path::Path,
    process::{Command, Stdio},
};

fn csv_rows(output: &Path) -> Vec<Vec<u64>> {
    let mut files = vec![];
    for file in fs::read_dir(output).unwrap() {
        let path = file.unwrap().path();
        if path.extension().is_some_and(|extension| extension == "csv") {
            files.push(
                fs::read_to_string(path)
                    .unwrap()
                    .lines()
                    .skip(1)
                    .map(|line| line.split(',').next().unwrap().parse().unwrap())
                    .collect::<Vec<_>>(),
            );
        }
    }
    files.sort();
    files
}
#[test]
fn pipeline_order_changes_membership_and_matches_json_execution() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(
        &input,
        "id,country\n0,A\n1,A\n2,A\n3,A\n4,B\n5,B\n6,B\n7,B\n",
    )
    .unwrap();
    for (name, steps, expected) in [
        (
            "partition-first",
            vec![
                "--step",
                "partition",
                "--column",
                "country",
                "--step",
                "balanced",
                "--files",
                "2",
            ],
            vec![vec![0, 1], vec![2, 3], vec![4, 5], vec![6, 7]],
        ),
        (
            "balanced-first",
            vec![
                "--step",
                "balanced",
                "--files",
                "2",
                "--step",
                "partition",
                "--column",
                "country",
            ],
            vec![vec![0, 1, 2, 3], vec![4, 5, 6, 7]],
        ),
    ] {
        let output = dir.path().join(name);
        let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .arg("run")
            .arg("--input")
            .arg(&input)
            .args(steps)
            .arg("--output")
            .arg(&output)
            .arg("--yes")
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_eq!(csv_rows(&output), expected);
        let manifest = fs::read_to_string(output.join("manifest.jsonl")).unwrap();
        let record: Value = serde_json::from_str(manifest.lines().next().unwrap()).unwrap();
        let mut job = record["config"].clone();
        let json_output = dir.path().join(format!("{name}-json"));
        job["output"] = json_output.to_string_lossy().as_ref().into();
        let config = dir.path().join("job.json");
        fs::write(&config, serde_json::to_vec(&job).unwrap()).unwrap();
        let json = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .arg("run")
            .arg("--config")
            .arg(config)
            .arg("--yes")
            .output()
            .unwrap();
        assert!(
            json.status.success(),
            "{}",
            String::from_utf8_lossy(&json.stderr)
        );
        assert_eq!(csv_rows(&json_output), expected);
    }
}
#[test]
fn pipeline_confirmation_validation_and_failed_input_never_publish() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let output = dir.path().join("result");
    let run = |extra: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_chopper"))
            .args(["run", "--input"])
            .arg(&input)
            .arg("--output")
            .arg(&output)
            .args(extra)
            .stdin(Stdio::null())
            .output()
            .unwrap()
    };
    let prompt = run(&[]);
    assert!(!prompt.status.success());
    assert!(String::from_utf8_lossy(&prompt.stderr).contains("requires --yes"));
    let invalid = run(&["--step", "shuffle", "--by", "country", "--yes"]);
    assert!(!invalid.status.success());
    assert!(String::from_utf8_lossy(&invalid.stderr).contains("does not apply"));
    assert!(!output.exists());
    fs::write(&input, "id,country\n0,A\n1,B,extra\n").unwrap();
    let failed = run(&["--rows", "1", "--yes"]);
    assert!(!failed.status.success());
    assert!(!output.exists());
    assert_eq!(
        fs::read_dir(dir.path()).unwrap().count(),
        1,
        "failed Run cleans private staging"
    );
    let help = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--help"])
        .output()
        .unwrap();
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("--step"));
    assert!(String::from_utf8_lossy(&help.stdout).contains("--config"));
    let help = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .arg("--help")
        .output()
        .unwrap();
    let root_help = String::from_utf8_lossy(&help.stdout);
    assert!(!root_help
        .lines()
        .any(|line| line.trim_start().starts_with("pipeline ")));
    let removed = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .arg("pipeline")
        .output()
        .unwrap();
    assert!(!removed.status.success());
    assert!(String::from_utf8_lossy(&removed.stderr).contains("unrecognized subcommand"));
}
