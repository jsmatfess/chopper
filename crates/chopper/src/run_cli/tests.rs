use super::*;
fn parsed(args: &[&str]) -> Result<Job> {
    let matches = command().try_get_matches_from(
        ["run", "--input", "input.csv", "--output", "results"]
            .into_iter()
            .chain(args.iter().copied()),
    )?;
    parse(&matches).map(|(job, _)| job)
}
#[test]
fn ordered_steps_preserve_all_public_job_fields() {
    let job = parsed(&[
        "--step",
        "partition",
        "--column",
        "123",
        "--column-index",
        "2",
        "--column",
        "a,b",
        "--memory-mb",
        "512",
        "--workers",
        "2",
        "--grouping",
        "sort",
        "--step",
        "assign",
        "--group",
        "x,=y=40",
        "--group",
        "z=60",
        "--stratum-index",
        "1",
        "--stratum",
        "0",
        "--step",
        "shuffle",
        "--strategy",
        "fisher_yates",
        "--step",
        "partition",
        "--by",
        "country,segment",
        "--step",
        "assign_probabilistic",
        "--groups",
        "yes=25,no=75",
        "--strata",
        "country,segment",
        "--step",
        "balanced",
        "--files",
        "3",
        "--step",
        "interleaved",
        "--files",
        "2",
        "--job-version",
        "1",
        "--zip-member",
        "dir/input.csv",
        "--compression",
        "zip",
        "--rows",
        "100",
        "--bytes",
        "1MiB",
        "--compressed-bytes",
        "512KB",
        "--temp-dir",
        "temporary files",
        "--temp-bytes",
        "2GB",
        "--max-files",
        "2000",
        "--max-record-bytes",
        "1048576",
        "--full-shuffle-rng",
        "blake3_counter_v1",
        "--full-shuffle-algorithm",
        "adaptive_v1",
        "--input-encoding",
        "utf-16le",
        "--input-headers",
        "true",
        "--input-delimiter",
        "\t",
        "--input-quote",
        "'",
        "--input-escape",
        "\\",
        "--input-line-ending",
        "crlf",
        "--input-bom",
        "true",
        "--input-skip-empty-lines",
        "true",
        "--output-encoding",
        "windows-1252",
        "--output-headers",
        "false",
        "--output-delimiter",
        ";",
        "--output-quote",
        "'",
        "--output-escape",
        "\\",
        "--output-line-ending",
        "crlf",
        "--output-bom",
        "false",
        "--output-skip-empty-lines",
        "true",
    ])
    .unwrap();
    let expected = serde_json::json!({
        "version":1,"input":"input.csv","output":"results","zip_member":"dir/input.csv","compression":"zip",
        "operations":[
            {"type":"partition","columns":["123",2,"a,b"]},
            {"type":"assign","groups":[{"name":"x,=y","percent":"40"},{"name":"z","percent":"60"}],"strata":[1,"0"]},
            {"type":"shuffle","strategy":"fisher_yates"},{"type":"partition","columns":["country","segment"]},
            {"type":"assign_probabilistic","groups":[{"name":"yes","percent":"25"},{"name":"no","percent":"75"}],"strata":["country","segment"]},
            {"type":"balanced","files":3},{"type":"interleaved","files":2}],
        "input_csv":{"encoding":"utf-16le","headers":true,"delimiter":"\t","quote":"'","escape":"\\","line_ending":"crlf","bom":true,"skip_empty_lines":true},
        "output_csv":{"encoding":"windows-1252","headers":false,"delimiter":";","quote":"'","escape":"\\","line_ending":"crlf","bom":false,"skip_empty_lines":true},
        "limits":{"rows":100,"bytes":1048576,"compressed_bytes":512000},
        "resources":{"memory_mb":512,"workers":2,"grouping":"sort","max_files":2000,"max_record_bytes":1048576,"temp_dir":"temporary files","temp_bytes":2000000000u64}
    });
    let json_job: Job = serde_json::from_value(expected).unwrap();
    assert_eq!(
        serde_json::to_value(job).unwrap(),
        serde_json::to_value(json_job).unwrap()
    );
}
#[test]
fn global_position_does_not_change_stage_options_and_defaults_match_json() {
    let first = parsed(&[
        "--memory-mb",
        "auto",
        "--step",
        "shuffle",
        "--strategy",
        "auto",
        "--step",
        "partition",
        "--column",
        "-leading",
    ])
    .unwrap_err();
    assert!(first.to_string().contains("unexpected argument"));
    let first = parsed(&[
        "--memory-mb",
        "auto",
        "--step",
        "shuffle",
        "--strategy",
        "auto",
        "--step",
        "partition",
        "--column=-leading",
    ])
    .unwrap();
    let last = parsed(&[
        "--step",
        "shuffle",
        "--strategy",
        "auto",
        "--step",
        "partition",
        "--memory-mb",
        "auto",
        "--column=-leading",
    ])
    .unwrap();
    assert_eq!(
        serde_json::to_value(first).unwrap(),
        serde_json::to_value(last).unwrap()
    );
    let expected = Job {
        input: "input.csv".into(),
        output: "results".into(),
        resources: Resources::automatic(),
        ..Job::default()
    };
    assert_eq!(
        serde_json::to_value(parsed(&[]).unwrap()).unwrap(),
        serde_json::to_value(expected).unwrap()
    );
}
#[test]
fn rejects_wrong_scope_duplicates_missing_values_and_obsolete_options() {
    for args in [
        vec!["--column", "country"],
        vec!["--step", "shuffle", "--by", "country"],
        vec!["--step", "partition", "--strata", "country"],
        vec!["--step", "balanced", "--files", "2", "--files", "3"],
        vec![
            "--step",
            "shuffle",
            "--strategy",
            "auto",
            "--strategy",
            "uniform",
        ],
        vec!["--step", "unknown"],
        vec!["--step", "balanced"],
        vec!["--step", "assign"],
        vec!["--step", "partition"],
        vec!["--input-quote", "xx"],
        vec!["--seed", "anything"],
        vec!["--step", "shuffle", "--strategy", "buffer"],
        vec!["--memory-mb", "256", "--memory-mb", "512"],
        vec!["--step", "assign", "--group", "missing-percent"],
        vec!["--step", "partition", "--column-index", "-1"],
    ] {
        assert!(parsed(&args).is_err(), "{args:?}");
    }
    let mut args = vec![];
    for _ in 0..65 {
        args.extend(["--step", "shuffle"]);
    }
    assert!(parsed(&args).unwrap_err().to_string().contains("64"));
}

#[test]
fn hosted_generator_fixture_round_trips_through_real_clap_parser() {
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/fixtures/run-cli.json")).unwrap();
    let args: Vec<&str> = fixture["args"]
        .as_array()
        .unwrap()
        .iter()
        .map(|arg| arg.as_str().unwrap())
        .collect();
    let matches = command().try_get_matches_from(args).unwrap();
    let (actual, yes) = parse(&matches).unwrap();
    let expected: Job = serde_json::from_value(fixture["job"].clone()).unwrap();
    assert!(yes);
    assert_eq!(
        serde_json::to_value(actual).unwrap(),
        serde_json::to_value(expected).unwrap()
    );
}

#[test]
fn config_form_retains_admitted_owner_and_existing_resource_overrides() {
    let mut imported = Job {
        input: "input.csv".into(),
        output: "results".into(),
        ..Job::default()
    };
    imported.resources.memory_mb = 512.into();
    imported.resources.workers = 3;
    let file = tempfile::NamedTempFile::new().unwrap();
    serde_json::to_writer(file.as_file(), &imported).unwrap();
    for overrides in [vec![], vec!["--memory-mb", "auto", "--workers", "2"]] {
        let matches = command()
            .try_get_matches_from(
                ["run", "-c", file.path().to_str().unwrap()]
                    .into_iter()
                    .chain(overrides.iter().copied()),
            )
            .unwrap();
        let owner = source(&matches).unwrap();
        assert!(matches!(&owner, crate::CliJob::Decoded(_)));
        let job = owner.job();
        assert_eq!(
            job.resources.memory_mb,
            if overrides.is_empty() {
                MemoryBudget::MiB(512)
            } else {
                MemoryBudget::Auto
            }
        );
        assert_eq!(
            job.resources.workers,
            if overrides.is_empty() { 3 } else { 2 }
        );
    }
}
#[test]
fn config_conflicts_with_every_job_building_flag_before_file_io() {
    for &(flag, _) in GLOBAL.iter().chain(LOCAL) {
        if matches!(flag, "memory-mb" | "workers") {
            continue;
        }
        let args = [
            "run",
            "--config",
            "missing.json",
            &format!("--{flag}"),
            "value",
        ];
        let error = command()
            .try_get_matches_from(args)
            .unwrap_err()
            .to_string();
        assert!(error.contains("cannot be used with"), "{flag}: {error}");
    }
    for prefix in ["input", "output"] {
        for &(suffix, _) in CSV {
            let flag = format!("--{prefix}-{suffix}");
            let error = command()
                .try_get_matches_from(["run", "--config", "missing.json", &flag, "value"])
                .unwrap_err()
                .to_string();
            assert!(error.contains("cannot be used with"), "{flag}: {error}");
        }
    }
    for args in [
        vec!["run"],
        vec!["run", "--input", "input.csv"],
        vec!["run", "--output", "results"],
    ] {
        assert!(command().try_get_matches_from(args).is_err());
    }
}
