use std::process::Command;

#[test]
fn native_server_and_picker_commands_are_rejected() {
    let help = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(help.status.success());
    let help = String::from_utf8_lossy(&help.stdout);
    for command in ["run", "split", "analyze", "guide", "example"] {
        assert!(help
            .lines()
            .any(|line| line.split_whitespace().next() == Some(command)));
    }
    for command in ["serve", "pick-path", "profile"] {
        assert!(!help
            .lines()
            .any(|line| line.split_whitespace().next() == Some(command)));
        let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .args([command, "--help"])
            .output()
            .unwrap();
        assert_eq!(result.status.code(), Some(2));
        assert!(result.stdout.is_empty());
        let error = String::from_utf8_lossy(&result.stderr);
        assert!(
            error.contains(&format!("unrecognized subcommand '{command}'")),
            "{error}"
        );
    }
}

#[test]
fn removed_reproducibility_flag_is_rejected() {
    for command in ["run", "analyze", "split"] {
        let output = Command::new(env!("CARGO_BIN_EXE_chopper"))
            .args([command, "--reproducible"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(String::from_utf8_lossy(&output.stderr)
            .contains("unexpected argument '--reproducible'"));
    }
}

#[test]
fn seed_option_and_saved_job_fields_are_rejected() {
    let output = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["split", "input.csv", "--seed", "obsolete"])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("unexpected argument '--seed'"));
    for field in ["seed", "random_seed"] {
        let error =
            serde_json::from_value::<chopper_core::Job>(serde_json::json!({field:"obsolete"}))
                .unwrap_err();
        assert!(error.to_string().contains("unknown field"));
    }
    let job = chopper_core::Job {
        random_seed: Some("internal-test-control".into()),
        ..Default::default()
    };
    let json = serde_json::to_value(job).unwrap();
    assert!(json.get("seed").is_none());
    assert!(json.get("random_seed").is_none());
}
