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
fn validates_calculation_syntax_without_opening_a_csv() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("job.json");
    fs::write(&path, r#"{"input":"missing.csv","output":"out","calculated_columns":[{"name":"label","expression":"UPPER([missing header])"}]}"#).unwrap();
    assert!(validate(dir.path(), &[]).status.success());
    fs::write(&path, r#"{"input":"missing.csv","output":"out","calculated_columns":[{"name":"label","expression":"SAFE.REGEX_MATCH(a, \"[\")"}]}"#).unwrap();
    let failed = validate(dir.path(), &["--json"]);
    assert_eq!(failed.status.code(), Some(1));
    let report: serde_json::Value = serde_json::from_slice(&failed.stdout).unwrap();
    assert_eq!(report["error"]["path"], "/calculated_columns/0/expression");
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
            r#""resources":{"temp_bytes":0}"#,
            "/resources/temp_bytes",
            "temp_bytes must be positive",
        ),
        (
            r#""operations":[{"type":"partition","columns":[]}]"#,
            "/operations/0/columns",
            "partition requires columns",
        ),
        (
            r#""output_csv":{"encoding":"windows-1252","bom":true}"#,
            "/output_csv/bom",
            "BOM is only supported for UTF encodings",
        ),
        (
            r#""input_csv":{"headers":false},"output_csv":{"headers":false},"operations":[{"type":"partition","columns":[0,"1"]}]"#,
            "/operations/0/columns/1",
            "name selection requires headers",
        ),
        (
            r#""input_csv":{"headers":false},"output_csv":{"headers":false},"operations":[{"type":"assign","groups":[{"name":"a","percent":"100"}],"strata":["region"]}]"#,
            "/operations/0/strata/0",
            "name selection requires headers",
        ),
        (
            r#""input_csv":{"headers":false},"output_csv":{"headers":false},"operations":[{"type":"assign_probabilistic","groups":[{"name":"a","percent":"100"}],"strata":["region"]}]"#,
            "/operations/0/strata/0",
            "name selection requires headers",
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

#[test]
fn accepts_headerless_indices_and_utf_bom_aliases() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(
        dir.path().join("job.json"),
        r#"{"input":"missing.csv","output":"out","input_csv":{"headers":false},"output_csv":{"headers":false,"encoding":"utf8","bom":true},"operations":[{"type":"partition","columns":[0]},{"type":"assign","groups":[{"name":"a","percent":"100"}],"strata":[1]}]}"#,
    )
    .unwrap();
    let result = validate(dir.path(), &["--json"]);
    assert_eq!(result.status.code(), Some(0), "{result:?}");
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}
