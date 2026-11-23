use std::{
    fs,
    path::Path,
    process::{Command, Output},
};

fn validate(dir: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_chopper"))
        .current_dir(dir)
        .args(["validate", "--config", "job.json"])
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn validates_saved_job_without_input_or_work_directory() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(
        dir.path().join("job.json"),
        r#"{"input":"missing.csv","output":"out","resources":{"temp_dir":"work"}}"#,
    )
    .unwrap();

    let result = validate(dir.path(), &[]);
    assert_eq!(
        result.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_eq!(result.stdout, b"Configuration is valid.\n");
    assert!(result.stderr.is_empty());
    let result = validate(dir.path(), &["--json"]);
    assert_eq!(result.status.code(), Some(0));
    assert!(result.stderr.is_empty());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&result.stdout).unwrap(),
        serde_json::json!({"valid": true, "error": null}),
    );
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}

#[test]
fn terminal_diagnostics_name_the_config_and_field() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("job.json"), r#"{"input":"missing.csv"}"#).unwrap();

    let result = validate(dir.path(), &[]);
    assert_eq!(result.status.code(), Some(1));
    assert!(result.stdout.is_empty());
    let stderr = String::from_utf8(result.stderr).unwrap();
    for expected in ["job.json", "output path is required", "/output"] {
        assert!(stderr.contains(expected), "{stderr}");
    }
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}

#[test]
fn unreadable_config_has_a_machine_readable_failure() {
    let dir = tempfile::tempdir().unwrap();
    let result = validate(dir.path(), &["--json"]);
    assert_eq!(result.status.code(), Some(1));
    assert!(result.stderr.is_empty());
    let report: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(report["valid"], false);
    assert_eq!(report["error"]["code"], "config_read");
    assert_eq!(report["error"]["path"], serde_json::Value::Null);
}

#[test]
fn malformed_json_has_position_without_field_path() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("job.json"), "{\n").unwrap();

    let result = validate(dir.path(), &["--json"]);
    assert_eq!(result.status.code(), Some(1));
    assert!(result.stderr.is_empty());
    let report: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(report["valid"], false);
    assert_eq!(report["error"]["code"], "json_syntax");
    assert_eq!(report["error"]["path"], serde_json::Value::Null);
    assert_eq!(report["error"]["line"], 2);
    assert!(report["error"]["column"].is_number());
}

#[test]
fn strict_decoding_reports_fields_and_containing_operations() {
    let dir = tempfile::tempdir().unwrap();
    for (wire, path, message) in [
        (
            r#"{"input":"missing.csv","output":"out","typo/~":true}"#,
            "/typo~1~0",
            "unknown field",
        ),
        (
            r#"{"input":"missing.csv","output":"out","limits":{"rows":"10"}}"#,
            "/limits/rows",
            "invalid type",
        ),
        (
            r#"{"input":"missing.csv","output":"out","operations":[{"type":"balanced","files":2},{"type":"balanced","files":"2"}]}"#,
            "/operations/1",
            "invalid type",
        ),
    ] {
        fs::write(dir.path().join("job.json"), wire).unwrap();
        let result = validate(dir.path(), &["--json"]);
        assert_eq!(result.status.code(), Some(1));
        assert!(result.stderr.is_empty());
        let report: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(report["valid"], false);
        assert_eq!(report["error"]["code"], "json_schema", "{report}");
        assert_eq!(report["error"]["path"], path, "{report}");
        assert!(report["error"]["message"]
            .as_str()
            .unwrap()
            .contains(message));
    }
}

#[test]
fn rejects_invalid_config_values_at_their_field_paths() {
    let dir = tempfile::tempdir().unwrap();
    for (fields, path, message) in [
        (
            r#""version":2"#,
            "/version",
            "unsupported configuration version",
        ),
        (
            r#""operations":[{"type":"assign","groups":[{"name":"a","percent":"bad"}]}]"#,
            "/operations/0/groups/0/percent",
            "invalid percentage",
        ),
        (
            r#""operations":[{"type":"assign","groups":[{"name":"a","percent":"50"}]}]"#,
            "/operations/0/groups",
            "percentages must sum exactly to 100",
        ),
        (
            r#""operations":[{"type":"assign","groups":[{"name":"a","percent":"50"},{"name":"a","percent":"50"}]}]"#,
            "/operations/0/groups/1/name",
            "allocation names must be nonempty and unique",
        ),
        (
            r#""limits":{"compressed_bytes":10000}"#,
            "/limits/compressed_bytes",
            "requires output compression",
        ),
        (
            r#""operations":[{"type":"partition","columns":[]}]"#,
            "/operations/0/columns",
            "partition requires columns",
        ),
    ] {
        fs::write(
            dir.path().join("job.json"),
            format!(r#"{{"input":"missing.csv","output":"out",{fields}}}"#),
        )
        .unwrap();
        let result = validate(dir.path(), &["--json"]);
        assert_eq!(result.status.code(), Some(1));
        assert!(result.stderr.is_empty());
        let report: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(report["valid"], false);
        assert_eq!(report["error"]["code"], "invalid_config", "{report}");
        assert_eq!(report["error"]["path"], path, "{report}");
        assert_eq!(report["error"]["line"], serde_json::Value::Null);
        assert!(report["error"]["message"]
            .as_str()
            .unwrap()
            .contains(message));
    }
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}
