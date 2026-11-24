use anyhow::Result;
use chopper::{
    core::*,
    engine::{self, Prepared},
    storage::{Context, Row, SortOrder, Sorter},
};
use std::{
    fs::{self, File},
    io::{Read, Write},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tempfile::TempDir;

fn fixture(text: &str) -> (TempDir, Job) {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    fs::write(&input, text).unwrap();
    let job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("result").to_string_lossy().into(),
        random_seed: Some("test-seed".into()),
        ..Job::default()
    };
    (dir, job)
}
fn prepare(job: Job) -> Result<Prepared> {
    engine::prepare(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}

#[test]
fn saved_job_tests_membership_with_typed_values_and_nulls() -> Result<()> {
    let (dir, mut job) =
        fixture("region,alternate,amount\nNORTH,WEST,12\nSOUTH,NORTH,0\nWEST,WEST,5\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"listed","expression":"region in (\"NORTH\", alternate) AND NOT (NUMBER(amount) IN (0, 1 + 1))"},
        {"name":"nullable","expression":"NUMBER(amount) IN (NULL, 12, 5)"},
        {"name":"short_circuit","expression":"1 IN (1, 1 / 0)"},
        {"name":"strict_types","expression":"SAFE(amount IN (12))"}
    ]))?;
    prepare(job.clone())?.execute()?;
    assert_eq!(
        fs::read_to_string(dir.path().join("result/part-00000001.csv"))?,
        concat!(
            "region,alternate,amount,listed,nullable,short_circuit,strict_types\n",
            "NORTH,WEST,12,true,true,true,\"\"\n",
            "SOUTH,NORTH,0,false,\"\",true,\"\"\n",
            "WEST,WEST,5,true,true,true,\"\"\n",
        )
    );
    for invalid in [
        "region IN ()",
        "region IN \"NORTH\"",
        "region IN (\"NORTH\",)",
    ] {
        job.calculated_columns = vec![CalculatedColumn {
            name: "listed".into(),
            expression: invalid.into(),
        }];
        assert!(job.validate().is_err(), "{invalid}");
    }
    Ok(())
}

#[test]
fn saved_job_partitions_and_exports_a_calculated_column() -> Result<()> {
    let (dir, mut job) = fixture("id,Sales Region\n1, north \n2, south\n3,NORTH\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name": "region", "expression": "upper(TRIM([Sales Region]))"}
    ]))?;
    job.operations = serde_json::from_value(serde_json::json!([
        {"type": "partition", "columns": ["region"]}
    ]))?;
    let prepared = prepare(job)?;
    assert_eq!(prepared.analysis.groups, 2);
    prepared.execute()?;
    let output = dir.path().join("result");
    let mut csv = fs::read_dir(output)?
        .filter_map(|entry| {
            let path = entry.expect("list result file").path();
            (path.extension().and_then(|ext| ext.to_str()) == Some("csv")).then_some(path)
        })
        .map(fs::read_to_string)
        .collect::<std::io::Result<Vec<_>>>()?;
    csv.sort();
    assert_eq!(
        csv,
        [
            "id,Sales Region,region\n1, north ,NORTH\n3,NORTH,NORTH\n",
            "id,Sales Region,region\n2, south,SOUTH\n"
        ]
    );
    Ok(())
}

#[test]
fn saved_job_chains_typed_calculations_and_keeps_null_distinct() -> Result<()> {
    let (dir, mut job) = fixture("id,amount\n1,120\n2,invalid\n3,\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"band", "expression":"IFS(IS_NULL(numeric), \"missing\", numeric >= 100, \"large\", \"small\")"},
        {"name":"numeric", "expression":"SAFE.NUMBER(amount)"}
    ]))?;
    job.operations = serde_json::from_value(serde_json::json!([
        {"type":"balanced", "files":1}
    ]))?;
    prepare(job)?.execute()?;
    let csv = fs::read_to_string(dir.path().join("result/split-1-part-00000001.csv"))?;
    assert_eq!(
        csv,
        "id,amount,band,numeric\n1,120,large,120\n2,invalid,missing,\"\"\n3,\"\",missing,\"\"\n"
    );
    Ok(())
}

#[test]
fn saved_job_extracts_utc_and_local_timestamp_days() -> Result<()> {
    let (dir, mut job) = fixture("source\n2026-11-23T00:30:00.123456789+02:00\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"ts","expression":"TIMESTAMP_PARSE(source)"},
        {"name":"utc_day","expression":"TIMESTAMP_EXTRACT(ts, \"day\")"},
        {"name":"local_day","expression":"TIMESTAMP_EXTRACT(ts, \"day\", \"local\")"}
    ]))?;
    job.operations = serde_json::from_value(serde_json::json!([
        {"type":"balanced","files":1}
    ]))?;
    prepare(job)?.execute()?;
    assert_eq!(
        fs::read_to_string(dir.path().join("result/split-1-part-00000001.csv"))?,
        "source,ts,utc_day,local_day\n2026-11-23T00:30:00.123456789+02:00,2026-11-22T22:30:00.123456789Z,22,23\n"
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn large_terminal_calculations_match_snapshot_bytes_and_clean_cancelled_output() -> Result<()> {
    let (dir, mut job) = fixture("");
    {
        let mut input = std::io::BufWriter::new(File::create(&job.input)?);
        writeln!(input, "id,amount,when,payload")?;
        let payload = "x".repeat(512 * 1024);
        for id in 0..256 {
            let amount = if id % 2 == 0 { "2" } else { "invalid" };
            writeln!(
                input,
                "{id},{amount},2026-11-23T00:30:00.123456789+02:00,{payload}"
            )?;
        }
        input.flush()?;
    }
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"day","expression":"TIMESTAMP_EXTRACT(ts, \"day\", \"local\")"},
        {"name":"amount_number","expression":"SAFE.NUMBER(amount)"},
        {"name":"ts","expression":"TIMESTAMP_PARSE(when)"},
        {"name":"classified","expression":"IF(IS_NULL(amount_number), \"missing\", TEXT(amount_number))"}
    ]))?;
    job.resources.workers = 1;
    job.limits.rows = Some(16);
    let byte_cap = 8 * 1024 * 1024;
    job.limits.bytes = Some(byte_cap);
    let snapshot_output = dir.path().join("snapshot");
    let mut snapshot = job.clone();
    snapshot.output = snapshot_output.to_string_lossy().into();
    let snapshot = prepare(snapshot)?.execute()?;

    let published_directly = Arc::new(AtomicBool::new(false));
    let phase = published_directly.clone();
    let direct = engine::run(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |progress| {
            if progress.phase == "Finalizing direct terminal output" {
                phase.store(true, Ordering::Relaxed);
            }
        }),
    )?;
    assert!(published_directly.load(Ordering::Relaxed));
    assert_eq!(direct.output_files, 18);
    assert_eq!(direct.output_files, snapshot.output_files);
    assert_eq!(direct.output_csv_bytes, snapshot.output_csv_bytes);
    assert_eq!(direct.groups, snapshot.groups);

    let output = dir.path().join("result");
    for index in 1..=direct.output_files {
        let name = format!("part-{index:08}.csv");
        let direct_csv = fs::read(output.join(&name))?;
        assert!(direct_csv.len() as u64 <= byte_cap);
        assert_eq!(direct_csv, fs::read(snapshot_output.join(&name))?);
    }

    let mut failing = job.clone();
    failing.output = dir.path().join("failed").to_string_lossy().into();
    failing.calculated_columns = vec![CalculatedColumn {
        name: "late_error".into(),
        expression: r#"IF(NUMBER(id) = 255, NUMBER("invalid"), 1)"#.into(),
    }];
    let failure = engine::run(failing, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
        .expect_err("the last formula should fail");
    assert!(format!("{failure:#}").contains("input record 256, calculated column \"late_error\""));
    assert_eq!(fs::read_dir(dir.path())?.count(), 3);

    job.output = dir.path().join("cancelled").to_string_lossy().into();
    let cancel = Arc::new(AtomicBool::new(false));
    let cancel_before_publish = cancel.clone();
    let cancelled = engine::run(
        job,
        cancel,
        Arc::new(move |progress| {
            if progress.phase == "Finalizing direct terminal output" {
                cancel_before_publish.store(true, Ordering::Relaxed);
            }
        }),
    );
    assert!(format!("{:#}", cancelled.expect_err("Run should cancel")).contains("cancel"));
    assert_eq!(fs::read_dir(dir.path())?.count(), 3);
    Ok(())
}

#[cfg(all(target_os = "linux", not(feature = "experimental-constant-partition")))]
#[test]
fn large_calculated_partition_matches_the_staged_snapshot() -> Result<()> {
    let (dir, mut job) = fixture("");
    let mut input = std::io::BufWriter::new(File::create(&job.input)?);
    writeln!(input, "id,amount,payload")?;
    let padding = "x".repeat(512 * 1024);
    for id in 0..256 {
        let amount = if id % 2 == 0 { "12" } else { "missing" };
        writeln!(input, "{id},{amount},{padding}")?;
    }
    input.into_inner()?;
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"band","expression":"IF(IS_NULL(value), \"missing\", TEXT(value))"},
        {"name":"value","expression":"SAFE.NUMBER(amount)"}
    ]))?;
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("band".into())],
    }];
    job.resources.grouping = Grouping::Auto;
    job.resources.memory_mb = MemoryBudget::MiB(256);
    job.resources.workers = 1;
    let temp = dir.path().join("temp");
    fs::create_dir(&temp)?;
    job.resources.temp_dir = Some(temp.to_string_lossy().into());
    let cap = 8 * 1024 * 1024;
    job.limits.bytes = Some(cap);
    let staged_output = dir.path().join("staged");
    let mut staged = job.clone();
    staged.output = staged_output.to_string_lossy().into();
    let staged = prepare(staged)?.execute()?;
    let fused = engine::run(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?;
    assert_eq!(fused.groups, 2);
    assert_eq!(
        serde_json::to_value(&fused.stages)?,
        serde_json::to_value(&staged.stages)?
    );
    assert_eq!(fused.output_files, staged.output_files);
    assert_eq!(fused.output_csv_bytes, staged.output_csv_bytes);

    let mut files = 0;
    for entry in fs::read_dir(&staged_output)? {
        let entry = entry?;
        if entry.path().extension().is_some_and(|ext| ext == "csv") {
            let expected = fs::read(entry.path())?;
            assert!(expected.len() as u64 <= cap);
            assert_eq!(
                fs::read(dir.path().join("result").join(entry.file_name()))?,
                expected
            );
            files += 1;
        }
    }
    assert_eq!(files, fused.output_files);

    let cancelled_output = dir.path().join("cancelled");
    job.output = cancelled_output.to_string_lossy().into();
    let cancel = Arc::new(AtomicBool::new(false));
    let request_cancel = cancel.clone();
    let failure = engine::run(
        job,
        cancel,
        Arc::new(move |progress| {
            if progress.phase == "Preparing operation 1 of 1" {
                request_cancel.store(true, Ordering::Relaxed);
            }
        }),
    )
    .expect_err("cancelled partition should fail");
    assert!(format!("{failure:#}").contains("cancelled"));
    assert!(!cancelled_output.exists());
    assert_eq!(fs::read_dir(temp)?.count(), 0);
    Ok(())
}

#[test]
fn calculated_column_binding_follows_the_available_schema() -> Result<()> {
    let (_dir, mut job) = fixture("Name,Name,br]acket\na,b,x\n");
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("copy".into())],
    }];
    job.calculated_columns = vec![CalculatedColumn {
        name: "copy".into(),
        expression: String::new(),
    }];
    for (invalid, expected) in [
        ("Name", "missing or ambiguous"),
        ("name", "missing or ambiguous"),
        ("copy", "cyclic"),
        ("$3", "cyclic"),
    ] {
        job.calculated_columns[0].expression = invalid.into();
        let failure = prepare(job.clone()).err().unwrap();
        assert!(format!("{failure:#}").contains(expected), "{failure:#}");
    }
    for valid in ["$1", "[br]]acket]"] {
        job.calculated_columns[0].expression = valid.into();
        assert_eq!(prepare(job.clone())?.analysis.groups, 1);
    }
    job.input_csv.headers = false;
    job.output_csv.headers = false;
    job.calculated_columns[0].expression = "$1".into();
    assert_eq!(prepare(job)?.analysis.groups, 2);
    Ok(())
}

#[test]
fn calculation_growth_and_cancellation_clean_temporary_output() -> Result<()> {
    for cancel in [false, true] {
        let (dir, mut job) = fixture("source\naaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n");
        job.resources.max_record_bytes = 128;
        let temp = dir.path().join("temp");
        fs::create_dir(&temp)?;
        job.resources.temp_dir = Some(temp.to_string_lossy().into());
        job.calculated_columns = vec![CalculatedColumn {
            name: "expanded".into(),
            expression: "REGEX_REPLACE(source, \"a\", \"12345678\")".into(),
        }];
        let stopped = Arc::new(AtomicBool::new(false));
        let flag = stopped.clone();
        let result = engine::run(
            job,
            stopped,
            Arc::new(move |progress| {
                if cancel && progress.phase.as_str() == "Evaluating calculated columns" {
                    flag.store(true, Ordering::Relaxed);
                }
            }),
        );
        let error = format!("{:#}", result.unwrap_err());
        assert!(
            error.contains(if cancel {
                "job cancelled"
            } else {
                "maximum record size"
            }),
            "{error}"
        );
        assert!(!dir.path().join("result").exists());
        assert_eq!(fs::read_dir(temp)?.count(), 0);
    }
    Ok(())
}

#[test]
fn saved_job_replaces_regex_captures_and_matches_unicode_wildcards() -> Result<()> {
    let (dir, mut job) = fixture("source\nÉTÉ-123-45\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"masked","expression":"REGEX_REPLACE(source, \"([0-9]+)\", \"<$1>\")"},
        {"name":"matches","expression":"ILIKE(masked, \"été-.*\")"}
    ]))?;
    prepare(job)?.execute()?;
    assert_eq!(
        fs::read_to_string(dir.path().join("result/part-00000001.csv"))?,
        "source,masked,matches\nÉTÉ-123-45,ÉTÉ-<123>-<45>,true\n"
    );
    Ok(())
}

#[test]
fn saved_job_groups_by_extracted_text_and_exports_date_arithmetic() -> Result<()> {
    let (dir, mut job) = fixture("code,date\nA-012,2024-01-31\nA-002,2024-02-03\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"code_prefix","expression":"REGEX_EXTRACT(code, \"([A-Z]+)-([0-9]+)\", capture)"},
        {"name":"capture","expression":"NUMBER(LEFT(\"11\", 1))"},
        {"name":"next_month","expression":"DATE_ADD_MONTHS(DATE_PARSE(date), 1)"},
        {"name":"weeks","expression":"DATE_ISO_WEEK(next_month)"}
    ]))?;
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("code_prefix".into())],
    }];
    let prepared = prepare(job)?;
    assert_eq!(prepared.analysis.groups, 1);
    prepared.execute()?;
    let file = fs::read_dir(dir.path().join("result"))?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .find(|path| path.extension().is_some_and(|ext| ext == "csv"))
        .expect("calculated CSV output");
    assert_eq!(
        fs::read_to_string(file)?,
        concat!(
            "code,date,code_prefix,capture,next_month,weeks\n",
            "A-012,2024-01-31,A,1,2024-02-29,9\n",
            "A-002,2024-02-03,A,1,2024-03-03,9\n",
        )
    );
    Ok(())
}

#[test]
fn saved_job_keeps_unicode_wildcard_width_and_subnormal_bucket_boundaries() -> Result<()> {
    let (dir, mut job) = fixture("letter,amount\nİ,-5e-324\nΟΣ,5e-324\ni̇,-0\n");
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"one_scalar","expression":r#"ILIKE(letter, ".")"#},
        {"name":"case_match","expression":r#"ILIKE(letter, "οσ")"#},
        {"name":"band","expression":"BUCKET(NUMBER(amount), 2)"},
        {"name":"is_below_zero","expression":"band < 0"}
    ]))?;
    prepare(job)?.execute()?;
    assert_eq!(
        fs::read_to_string(dir.path().join("result/part-00000001.csv"))?,
        concat!(
            "letter,amount,one_scalar,case_match,band,is_below_zero\n",
            "İ,-5e-324,true,false,-2,true\n",
            "ΟΣ,5e-324,false,true,0,false\n",
            "i̇,-0,false,false,0,false\n",
        )
    );
    Ok(())
}

#[test]
fn calculated_values_survive_sort_spill_without_changing_csv_output() -> Result<()> {
    use std::fmt::Write as _;
    let mut text = String::from("id,source,payload\n");
    let payload = "x".repeat(1200);
    for id in 0..18000 {
        let source = if id % 2 == 0 {
            "2026-11-23T00:30:00+02:00"
        } else {
            "2026-11-22T22:30:00Z"
        };
        writeln!(&mut text, "{id},{source},{payload}").unwrap();
    }
    let (dir, mut job) = fixture(&text);
    job.resources.grouping = Grouping::Sort;
    job.resources.max_record_bytes = 1024 * 1024;
    job.resources.workers = 1;
    job.calculated_columns = serde_json::from_value(serde_json::json!([
        {"name":"ts","expression":"TIMESTAMP_PARSE(source)"},
        {"name":"rank","expression":"NUMBER(id) + 1"},
        {"name":"bucket","expression":"IF(rank > 0, TIMESTAMP_EXTRACT(ts, \"day\", \"local\"), NULL)"}
    ]))?;
    job.operations = serde_json::from_value(serde_json::json!([
        {"type":"partition","columns":["ts"]}
    ]))?;
    let mut results = Vec::new();
    for memory in [256, 32] {
        let output = dir.path().join(format!("memory-{memory}"));
        job.resources.memory_mb = memory.into();
        job.output = output.to_string_lossy().into();
        let prepared = prepare(job.clone())?;
        assert_eq!(prepared.analysis.groups, 1);
        assert_eq!(
            prepared.analysis.diagnostics["sort_runs"].as_u64().unwrap() > 0,
            memory == 32
        );
        prepared.execute()?;
        let csv = fs::read_dir(&output)?
            .filter_map(|entry| {
                let path = entry.ok()?.path();
                (path.extension().and_then(|ext| ext.to_str()) == Some("csv")).then_some(path)
            })
            .next()
            .unwrap();
        let data = fs::read_to_string(csv)?;
        let mut lines = data.lines();
        assert_eq!(lines.next(), Some("id,source,payload,ts,rank,bucket"));
        assert!(lines
            .next()
            .unwrap()
            .ends_with(",2026-11-22T22:30:00Z,1,23"));
        assert!(lines
            .next()
            .unwrap()
            .ends_with(",2026-11-22T22:30:00Z,2,22"));
        assert_eq!(data.lines().count(), 18001);
        results.push(blake3::hash(data.as_bytes()));
    }
    assert_eq!(results[0], results[1]);
    Ok(())
}

#[test]
fn adaptive_grouping_matches_sorting_through_late_shape_changes() -> Result<()> {
    for shape in [
        "small",
        "low_cardinality",
        "late_keys",
        "late_reorder",
        "unique",
    ] {
        let mut expected = Vec::new();
        let mut ctx = Context::new(
            &Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        ctx.memory = 4 * 1024 * 1024;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        let count = if shape == "small" { 12 } else { 18000 };
        for id in 0..count {
            let key = if shape == "unique" || (shape == "late_keys" && id >= 15000) {
                id
            } else {
                id % 3
            };
            let ordinal = if shape == "late_reorder" && id >= 15000 {
                id - 15000
            } else {
                id
            };
            let row = Row {
                id,
                ordinal,
                key: key.to_be_bytes().to_vec(),
                fields: vec![format!("{id},\"\n界{}", "x".repeat(160)), String::new()],
            };
            expected.push(row.clone());
            sorter.push(row)?;
        }
        expected.sort_by(|a, b| SortOrder::Key.compare(a, b));
        let actual: Vec<_> = sorter.finish()?.collect::<Result<_>>()?;
        for (a, b) in actual.iter().zip(&expected) {
            assert_eq!(
                (a.id, a.ordinal, &a.key, &a.fields),
                (b.id, b.ordinal, &b.key, &b.fields),
                "{shape}"
            );
        }
        assert_eq!(actual.len(), expected.len());
        assert!(
            ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap()
                > 0
        );
        drop(actual);
        let d = ctx.diagnostics();
        assert_eq!(
            d["workspace_reserved_bytes"], d["directory_path_reserved_bytes"],
            "{shape}"
        );
        assert_eq!(ctx.used(), 0, "{shape}");
        match shape {
            "small" => assert_eq!(d["resident_sorts"], 1),
            "low_cardinality" => {
                assert_eq!(d["routed_groupings"], 1);
                assert_eq!(d["sort_runs"], 0);
            }
            "late_keys" | "late_reorder" => {
                assert_eq!(d["routing_fallbacks"], 1);
                assert!(d["routing_reused_runs"].as_u64().unwrap() > 0);
                assert_eq!(d["merge_operations"], 1);
                assert_eq!(
                    d["merge_inputs"].as_u64().unwrap(),
                    d["sort_runs"].as_u64().unwrap() + 1,
                    "all reused buckets must consume a single merge input"
                );
                // These fixtures fit one final merge. Reusing bucket files means
                // each row is written once, even when the shape changes late.
                // Normalize compact physical blocks back to v1 logical traffic.
                assert_eq!(
                    d["temporary_bytes_written"].as_u64().unwrap()
                        + d["compact_spill_source_bytes"].as_u64().unwrap()
                        - d["compact_spill_stored_bytes"].as_u64().unwrap(),
                    expected.iter().map(Row::disk_len).sum::<u64>()
                );
                assert!(d["sort_runs"].as_u64().unwrap() > 0);
            }
            "unique" => {
                assert_eq!(d["routing_fallbacks"], 0);
                assert!(d["sort_runs"].as_u64().unwrap() > 0);
            }
            _ => unreachable!(),
        }
    }
    Ok(())
}

#[test]
fn adaptive_workspaces_and_files_release_on_cancellation_and_budget_errors() -> Result<()> {
    for cancel_job in [false, true] {
        let cancelled = Arc::new(AtomicBool::new(false));
        let mut ctx = Context::new(
            &Resources {
                temp_bytes: Some(if cancel_job { 100_000_000 } else { 1024 }),
                ..Resources::default()
            },
            cancelled.clone(),
            Arc::new(|_| {}),
        )?;
        ctx.memory = 4 * 1024 * 1024;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        let result = (|| -> Result<()> {
            for id in 0..20000 {
                if cancel_job && id == 10000 {
                    cancelled.store(true, Ordering::Relaxed);
                }
                sorter.push(Row {
                    id,
                    ordinal: id,
                    key: vec![0],
                    fields: vec!["x".repeat(256)],
                })?;
            }
            Ok(())
        })();
        assert!(result.is_err());
        drop(sorter);
        assert_eq!(ctx.used(), 0);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.diagnostics()["directory_path_reserved_bytes"]
        );
    }
    Ok(())
}

#[test]
fn cancelled_merge_releases_reused_bucket_files_and_workspace() -> Result<()> {
    let flag = Arc::new(AtomicBool::new(false));
    let mut ctx = Context::new(&Resources::default(), flag.clone(), Arc::new(|_| {}))?;
    ctx.memory = 4 * 1024 * 1024;
    let mut sorter = Sorter::new(&ctx, SortOrder::Key);
    for id in 0u64..18000 {
        let key = if id < 15000 { id % 3 } else { id };
        sorter.push(Row {
            id,
            ordinal: id,
            key: key.to_be_bytes().to_vec(),
            fields: vec!["x".repeat(256)],
        })?;
    }
    let mut rows = sorter.finish()?;
    assert!(ctx.diagnostics()["routing_reused_runs"].as_u64().unwrap() > 0);
    assert!(ctx.used() > 0);
    flag.store(true, Ordering::Relaxed);
    assert!(rows.next().unwrap().is_err());
    assert!(rows.next().is_none());
    drop(rows);
    assert_eq!(ctx.used(), 0);
    assert_eq!(
        ctx.diagnostics()["workspace_reserved_bytes"],
        ctx.diagnostics()["directory_path_reserved_bytes"]
    );
    Ok(())
}

#[test]
fn automatic_and_forced_sort_grouping_publish_identical_pipelines() -> Result<()> {
    let payload = "界".repeat(110);
    let mut text = String::from("id,country,stratum,payload\n");
    for id in 0..40000 {
        text.push_str(&format!(
            "{id},{},{},\"{payload},\"\"line\nend\"\n",
            id % 3,
            id % 5
        ));
    }
    let assign = |strata| Operation::Assign {
        groups: vec![
            Allocation {
                name: "treatment".into(),
                percent: "80".into(),
            },
            Allocation {
                name: "control".into(),
                percent: "20".into(),
            },
        ],
        strata,
    };
    let partition = Operation::Partition {
        columns: vec![Column::Name("country".into())],
    };
    for operations in [
        vec![partition.clone()],
        vec![assign(vec![])],
        vec![partition, assign(vec![])],
        vec![assign(vec![Column::Name("stratum".into())])],
    ] {
        let (dir, mut job) = fixture(&text);
        job.resources.memory_mb = 32.into();
        job.resources.max_record_bytes = 1024 * 1024;
        job.operations = operations;
        job.limits.rows = Some(7000);
        let auto = prepare(job.clone())?;
        assert!(
            auto.analysis.diagnostics["routed_groupings"]
                .as_u64()
                .unwrap()
                > 0
        );
        assert_eq!(
            auto.analysis.diagnostics["workspace_reserved_bytes"],
            auto.job.reserved_bytes()
                + auto.analysis.preview.reserved_bytes()
                + auto.analysis.warnings.reserved_bytes()
                + auto.analysis.timings.reserved_bytes()
                + auto.analysis.diagnostics.reserved_bytes()
                + auto.analysis.text_reserved_bytes()
                + auto.analysis.stages.reserved_bytes()
                + auto.analysis.column_values.reserved_bytes()
                + auto.analysis.diagnostics["temporary_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + auto.analysis.diagnostics["directory_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
                + auto
                    .analysis
                    .header
                    .as_ref()
                    .map_or(0, |fields| fields.reserved_bytes())
        );
        let stats = serde_json::to_value(&auto.analysis.stages)?;
        auto.execute()?;
        job.resources.grouping = Grouping::Sort;
        job.output = dir.path().join("sorted").to_string_lossy().into();
        let sorted = prepare(job)?;
        assert_eq!(sorted.analysis.diagnostics["routed_groupings"], 0);
        assert_eq!(stats, serde_json::to_value(&sorted.analysis.stages)?);
        sorted.execute()?;
        assert_eq!(
            csv_files(&dir.path().join("result")),
            csv_files(&dir.path().join("sorted"))
        );
        let entries = |name: &str| -> Result<Vec<serde_json::Value>> {
            fs::read_to_string(dir.path().join(name).join("manifest.jsonl"))?
                .lines()
                .skip(1)
                .map(|s| Ok(serde_json::from_str(s)?))
                .collect()
        };
        assert_eq!(entries("result")?, entries("sorted")?);
    }
    Ok(())
}
#[test]
fn column_picker_reads_only_the_first_record_without_preparing_operations() {
    let (dir, mut job) = fixture("\"country, region\",segment,segment\n\"unterminated");
    job.operations = vec![Operation::Partition { columns: vec![] }];
    let schema = engine::input_columns(&job).unwrap();
    assert_eq!(schema["columns"], 3);
    assert_eq!(
        schema["header"],
        serde_json::json!(["country, region", "segment", "segment"])
    );
    assert!(!dir.path().join("result").exists());
    job.input_csv.headers = false;
    let schema = engine::input_columns(&job).unwrap();
    assert_eq!(schema["columns"], 3);
    assert!(schema["header"].is_null());
    fs::write(&job.input, "").unwrap();
    assert_eq!(engine::input_columns(&job).unwrap()["columns"], 0);
}
fn csv_files(dir: &std::path::Path) -> Vec<Vec<u8>> {
    // Inspect contents in output order, independent of descriptive name sorting.
    let mut files: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "csv"))
        .collect();
    files.sort_by_key(|path| {
        path.file_stem()
            .unwrap()
            .to_str()
            .unwrap()
            .rsplit("part-")
            .next()
            .unwrap()
            .parse::<u64>()
            .unwrap()
    });
    files
        .into_iter()
        .map(|path| fs::read(path).unwrap())
        .collect()
}

#[test]
fn grouped_names_include_columns_allocations_and_splits_for_every_format() {
    for compression in [Compression::None, Compression::Gzip, Compression::Zip] {
        let (dir, mut job) = fixture("country,segment\nUS,retail\nUS,retail\n");
        job.compression = compression;
        job.operations = vec![
            Operation::Partition {
                columns: vec![Column::Index(0), Column::Name("segment".into())],
            },
            Operation::Assign {
                groups: vec![Allocation {
                    name: "treatment".into(),
                    percent: "100".into(),
                }],
                strata: vec![],
            },
            Operation::Balanced { files: 2 },
        ];
        prepare(job.clone()).unwrap().execute().unwrap();
        let manifest = fs::read_to_string(dir.path().join("result/manifest.jsonl")).unwrap();
        let mut archive = (compression == Compression::Zip).then(|| {
            zip::ZipArchive::new(File::open(dir.path().join("result/outputs.zip")).unwrap())
                .unwrap()
        });
        for (i, line) in manifest.lines().skip(1).enumerate() {
            let entry: serde_json::Value = serde_json::from_str(line).unwrap();
            let part = i + 1;
            let extension = match compression {
                Compression::Gzip => ".gz",
                _ => "",
            };
            let expected = format!("country-US-segment-retail-allocation-treatment-split-{part}-part-{part:08}.csv{extension}");
            assert_eq!(entry["path"], expected);
            if let Some(archive) = archive.as_mut() {
                assert!(archive.by_name(&expected).is_ok());
            } else {
                assert!(dir.path().join("result").join(expected).is_file());
            }
        }
    }
}

#[test]
fn headerless_repeated_grouping_and_limit_chunks_keep_distinct_names() {
    let (dir, mut job) = fixture("US,retail\nUS,retail\n");
    job.input_csv.headers = false;
    job.output_csv.headers = false;
    job.limits.rows = Some(1);
    job.operations = vec![
        Operation::Partition {
            columns: vec![Column::Index(0)],
        },
        Operation::Partition {
            columns: vec![Column::Index(1)],
        },
    ];
    prepare(job).unwrap().execute().unwrap();
    for index in 1..=2 {
        let name = format!("column-1-US-column-2-retail-part-{index:08}.csv");
        assert_eq!(
            fs::read(dir.path().join("result").join(name)).unwrap(),
            b"US,retail\n"
        );
    }
}

#[test]
fn grouped_names_are_safe_bounded_unique_and_preserve_original_lineage() {
    let long = "界".repeat(200);
    let input = format!("k\na/b\na\\b\n\"\"\nCON\n{long}\n");
    let (dir, mut job) = fixture(&input);
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Index(0)],
    }];
    job.limits.rows = Some(1);
    prepare(job).unwrap().execute().unwrap();
    let manifest = fs::read_to_string(dir.path().join("result/manifest.jsonl")).unwrap();
    let entries: Vec<serde_json::Value> = manifest
        .lines()
        .skip(1)
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(entries.len(), 5);
    let mut names = std::collections::HashSet::new();
    for entry in &entries {
        let name = entry["path"].as_str().unwrap();
        assert!(name.len() <= 210);
        assert!(!name
            .chars()
            .any(|c| c.is_control() || "<>:\"/\\|?*".contains(c)));
        assert!(names.insert(name));
        assert!(dir.path().join("result").join(name).is_file());
    }
    assert_eq!(
        names
            .iter()
            .filter(|name| name.starts_with("k-a_b-part-"))
            .count(),
        2
    );
    assert!(names.iter().any(|name| name.starts_with("k-empty-part-")));
    assert!(entries
        .iter()
        .any(|entry| entry["lineage"][0]["values"][0] == long));
}
fn groups() -> Vec<Allocation> {
    vec![
        Allocation {
            name: "treatment".into(),
            percent: "80".into(),
        },
        Allocation {
            name: "control".into(),
            percent: "20".into(),
        },
    ]
}

#[test]
fn balanced_preserves_order_and_rejects_impossible_caps() {
    let (dir, mut job) = fixture("id,x\n0,a\n1,b\n2,c\n3,d\n4,e\n");
    job.operations.push(Operation::Balanced { files: 2 });
    let p = prepare(job.clone()).unwrap();
    assert_eq!(p.analysis.output_files, 2);
    p.execute().unwrap();
    assert_eq!(
        csv_files(&dir.path().join("result")),
        vec![
            b"id,x\n0,a\n1,b\n2,c\n".to_vec(),
            b"id,x\n3,d\n4,e\n".to_vec()
        ]
    );
    job.limits.rows = Some(2);
    assert!(prepare(job.clone()).is_err());
    job.limits.rows = None;
    job.operations = vec![Operation::Balanced { files: 6 }];
    assert!(prepare(job).is_err());
}
#[test]
fn strict_byte_caps_count_actual_encoding_headers_and_quotes() {
    let (dir, mut job) = fixture("x,y\n1,\"a,b\"\n2,é\n");
    job.output_csv.encoding = "utf-16le".into();
    job.output_csv.bom = true;
    job.limits.bytes = Some(26);
    let p = prepare(job.clone()).unwrap();
    assert_eq!(p.analysis.output_files, 2);
    p.execute().unwrap();
    let files = csv_files(&dir.path().join("result"));
    assert!(files.iter().all(|f| f.len() <= 26));
    assert_eq!(files[0].len(), 26);
    job.limits.bytes = Some(25);
    assert!(prepare(job).is_err());
}
#[test]
fn partitions_do_not_coerce_values_or_lose_input_order() {
    let (dir, mut job) = fixture("id,k,v\n0,001,a\n1,1,b\n2,001,c\n3,1,d\n4,001,a\n");
    job.operations.push(Operation::Partition {
        columns: vec![Column::Name("k".into()), Column::Name("v".into())],
    });
    let p = prepare(job).unwrap();
    assert_eq!(p.analysis.groups, 4);
    p.execute().unwrap();
    let files = csv_files(&dir.path().join("result"));
    assert_eq!(
        String::from_utf8(files[0].clone()).unwrap(),
        "id,k,v\n0,001,a\n4,001,a\n"
    );
}
#[test]
fn allocation_is_exact_stratified_and_stable() {
    let input = format!(
        "id,k\n{}",
        (0..100)
            .map(|i| format!("{i},{}\n", i % 3))
            .collect::<String>()
    );
    let (dir, mut job) = fixture(&input);
    job.operations.push(Operation::Assign {
        groups: groups(),
        strata: vec![Column::Name("k".into())],
    });
    let p = prepare(job.clone()).unwrap();
    assert_eq!(p.analysis.output_files, 2);
    p.execute().unwrap();
    let files = csv_files(&dir.path().join("result"));
    let mut all = vec![];
    for file in &files {
        let ids: Vec<u64> = std::str::from_utf8(file)
            .unwrap()
            .lines()
            .skip(1)
            .map(|l| l.split(',').next().unwrap().parse().unwrap())
            .collect();
        assert!(ids.windows(2).all(|v| v[0] < v[1]));
        all.extend(ids);
    }
    all.sort();
    assert_eq!(all, (0..100).collect::<Vec<_>>());
    assert_eq!(
        std::str::from_utf8(&files[0]).unwrap().lines().count() - 1,
        79
    );
    job.output = dir.path().join("repeat").to_string_lossy().into();
    prepare(job).unwrap().execute().unwrap();
    assert_eq!(files, csv_files(&dir.path().join("repeat")));
}
#[test]
fn operation_order_changes_scope_and_shuffled_order_is_preserved() {
    let (dir, mut job) = fixture("id,k\n0,a\n1,b\n2,a\n3,b\n4,a\n5,b\n");
    job.operations = vec![
        Operation::Balanced { files: 2 },
        Operation::Partition {
            columns: vec![Column::Name("k".into())],
        },
    ];
    let p = prepare(job.clone()).unwrap();
    assert_eq!(p.analysis.groups, 4);
    p.execute().unwrap();
    assert_eq!(
        csv_files(&dir.path().join("result"))[0],
        b"id,k\n0,a\n2,a\n"
    );
    job.operations.reverse();
    job.output = dir.path().join("reversed").to_string_lossy().into();
    prepare(job).unwrap().execute().unwrap();
    assert_ne!(
        csv_files(&dir.path().join("result")),
        csv_files(&dir.path().join("reversed"))
    );
}
#[test]
fn uniform_shuffle_matches_across_external_runs_and_memory_budgets() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let mut file = std::io::BufWriter::new(File::create(&input).unwrap());
    writeln!(file, "id,payload").unwrap();
    let payload = "x".repeat(180);
    for i in 0..40_000 {
        writeln!(file, "{i},{payload}").unwrap();
    }
    file.flush().unwrap();
    drop(file);
    let mut job = Job {
        input: input.to_string_lossy().into(),
        output: dir.path().join("small").to_string_lossy().into(),
        random_seed: Some("stable".into()),
        ..Job::default()
    };
    job.resources.memory_mb = 32.into();
    job.resources.max_record_bytes = 1024 * 1024;
    job.operations = vec![
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Balanced { files: 3 },
    ];
    prepare(job.clone()).unwrap().execute().unwrap();
    job.resources.memory_mb = 128.into();
    job.output = dir.path().join("large").to_string_lossy().into();
    prepare(job).unwrap().execute().unwrap();
    let a = csv_files(&dir.path().join("small"));
    let b = csv_files(&dir.path().join("large"));
    assert_eq!(a, b);
    let mut ids: Vec<u64> = a
        .iter()
        .flat_map(|bytes| {
            std::str::from_utf8(bytes)
                .unwrap()
                .lines()
                .skip(1)
                .map(|l| l.split(',').next().unwrap().parse::<u64>().unwrap())
        })
        .collect();
    assert_ne!(ids, (0..40_000).collect::<Vec<_>>());
    ids.sort();
    assert_eq!(ids, (0..40_000).collect::<Vec<_>>());
}
#[test]
fn injected_shuffle_key_collisions_use_random_refinement() {
    let ctx = Context::new(
        &Resources {
            temp_bytes: Some(1),
            ..Resources::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .unwrap();
    let domain = random::domain("seed", 0, "scope");
    let mut sorter = Sorter::new(&ctx, SortOrder::Random(domain));
    for id in 0..100 {
        sorter
            .push(Row {
                id,
                ordinal: id,
                key: vec![0; 16],
                fields: vec![id.to_string()],
            })
            .unwrap();
    }
    let file = sorter.finish().unwrap();
    let actual: Vec<_> = file.map(|row| row.unwrap().id).collect();
    let mut expected: Vec<u64> = (0..100).collect();
    expected.sort_by(|a, b| random::compare_ties(&domain, *a, *b));
    assert_eq!(actual, expected);
    assert_ne!(actual, (0..100).collect::<Vec<_>>());
}
#[test]
fn all_compression_outputs_roundtrip_as_inputs() {
    for compression in [Compression::Gzip, Compression::Zip] {
        let (dir, mut job) = fixture("id,text\n0,\"a,b\"\n1,\"line\nline\"\n2,é\n");
        job.compression = compression;
        prepare(job.clone()).unwrap().execute().unwrap();
        let name = match compression {
            Compression::Gzip => "part-00000001.csv.gz",
            _ => "outputs.zip",
        };
        job.input = dir
            .path()
            .join("result")
            .join(name)
            .to_string_lossy()
            .into();
        job.output = dir.path().join("roundtrip").to_string_lossy().into();
        job.compression = Compression::None;
        let p = prepare(job).unwrap();
        assert_eq!(p.analysis.rows, 3);
        p.execute().unwrap();
        assert_eq!(
            csv_files(&dir.path().join("roundtrip"))[0],
            b"id,text\n0,\"a,b\"\n1,\"line\nline\"\n2,\xc3\xa9\n"
        );
    }
}
#[test]
fn zip_contains_all_csv_members_and_manifest_and_requires_selection() {
    let (dir, mut job) = fixture("id\n0\n1\n2\n");
    job.compression = Compression::Zip;
    job.limits.rows = Some(1);
    prepare(job.clone()).unwrap().execute().unwrap();
    let zip_path = dir.path().join("result/outputs.zip");
    let mut archive = zip::ZipArchive::new(File::open(&zip_path).unwrap()).unwrap();
    assert_eq!(archive.len(), 4);
    let mut text = String::new();
    archive
        .by_name("part-00000002.csv")
        .unwrap()
        .read_to_string(&mut text)
        .unwrap();
    assert_eq!(text, "id\n1\n");
    job.input = zip_path.to_string_lossy().into();
    assert!(prepare(job.clone()).is_err());
    job.zip_member = Some("part-00000002.csv".into());
    assert_eq!(prepare(job).unwrap().analysis.rows, 1);
}
#[test]
fn malformed_data_fails_and_never_publishes() {
    for input in ["a,b\n1\n", "a,b\n\"oops,x\n", "a,b\n\"x\"z,b\n"] {
        let (dir, job) = fixture(input);
        assert!(prepare(job).is_err());
        assert!(!dir.path().join("result").exists());
    }
}

#[test]
fn late_wide_parser_growth_preserves_shuffle_across_budgets_and_workers() -> Result<()> {
    let mut text = (0..33)
        .map(|i| format!("c{i}"))
        .collect::<Vec<_>>()
        .join(",");
    text.push('\n');
    for id in 0..12000 {
        text.push_str(&id.to_string());
        for _ in 0..32 {
            text.push_str(",0123456789");
        }
        text.push('\n');
    }
    text.push_str("12000,");
    text.push_str(&"x".repeat(2_050_000));
    for _ in 0..31 {
        text.push_str(",a");
    }
    text.push('\n');
    let mut reference = None;
    for memory in [32, 128] {
        for workers in [1, 4] {
            let (dir, mut job) = fixture(&text);
            job.resources.memory_mb = memory.into();
            job.resources.workers = workers;
            job.resources.max_record_bytes = 2 * 1024 * 1024;
            job.operations = vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }];
            let prepared = prepare(job)?;
            assert_eq!(prepared.analysis.rows, 12001);
            let digest = prepared.analysis.logical_digest.clone();
            prepared.execute()?;
            let output = csv_files(&dir.path().join("result"));
            if let Some((expected_digest, expected_output)) = &reference {
                assert_eq!(&digest, expected_digest);
                assert_eq!(&output, expected_output);
            } else {
                reference = Some((digest, output));
            }
        }
    }
    Ok(())
}
#[test]
fn cancellation_and_temp_budget_fail_cleanly() {
    let (dir, mut job) = fixture("id\n1\n2\n3\n");
    job.resources.temp_dir = Some(dir.path().to_string_lossy().into());
    job.resources.temp_bytes = Some(1);
    assert!(prepare(job.clone()).is_err());
    assert!(!dir.path().join("result").exists());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    job.resources.temp_bytes = None;
    let cancel = Arc::new(AtomicBool::new(false));
    let p = engine::prepare(job, cancel.clone(), Arc::new(|_| {})).unwrap();
    cancel.store(true, Ordering::Relaxed);
    assert!(p.execute().is_err());
    assert!(!dir.path().join("result").exists());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}
#[test]
fn prepared_snapshot_survives_source_change_and_refuses_overwrite() {
    let (dir, job) = fixture("id\n1\n2\n");
    let p = prepare(job.clone()).unwrap();
    fs::write(&job.input, "bad").unwrap();
    p.execute().unwrap();
    assert_eq!(csv_files(&dir.path().join("result"))[0], b"id\n1\n2\n");
    let p = prepare(job).unwrap();
    assert!(p.execute().is_err());
}
#[test]
fn empty_allocations_are_written_and_fanout_is_guarded() {
    let (dir, mut job) = fixture("id\n1\n");
    job.operations.push(Operation::Assign {
        groups: groups(),
        strata: vec![],
    });
    let p = prepare(job.clone()).unwrap();
    assert_eq!(p.analysis.output_files, 2);
    p.execute().unwrap();
    assert_eq!(csv_files(&dir.path().join("result"))[1], b"id\n");
    job.resources.max_files = 1;
    assert!(prepare(job).is_err());
}
#[test]
fn corrupted_gzip_trailer_is_rejected() {
    let (dir, mut job) = fixture("id\n1\n");
    let path = dir.path().join("bad.gz");
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(b"id\n1\n").unwrap();
    let mut bytes = encoder.finish().unwrap();
    let index = bytes.len() - 8;
    bytes[index] ^= 1;
    fs::write(&path, bytes).unwrap();
    job.input = path.to_string_lossy().into();
    assert!(prepare(job).is_err());
}

#[test]
fn all_operations_compose_with_strict_caps_and_zip() {
    let text = format!(
        "id,country,stratum\n{}",
        (0..600)
            .map(|i| format!("{i},{},{}\n", i % 3, i % 7))
            .collect::<String>()
    );
    let (dir, mut job) = fixture(&text);
    job.operations = vec![
        Operation::Partition {
            columns: vec![Column::Name("country".into())],
        },
        Operation::Assign {
            groups: groups(),
            strata: vec![Column::Name("stratum".into())],
        },
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
        Operation::Balanced { files: 2 },
    ];
    job.limits.rows = Some(100);
    job.limits.bytes = Some(1024);
    job.compression = Compression::Zip;
    let p = prepare(job).unwrap();
    assert_eq!(p.analysis.rows, 600);
    assert_eq!(p.analysis.output_files, 12);
    p.execute().unwrap();
    let mut archive =
        zip::ZipArchive::new(File::open(dir.path().join("result/outputs.zip")).unwrap()).unwrap();
    let mut ids = vec![];
    for index in 0..archive.len() {
        let mut member = archive.by_index(index).unwrap();
        if !member.name().ends_with(".csv") {
            continue;
        }
        assert!(member.size() <= 1024);
        let mut text = String::new();
        member.read_to_string(&mut text).unwrap();
        assert!(text.lines().count() - 1 <= 100);
        ids.extend(
            text.lines()
                .skip(1)
                .map(|l| l.split(',').next().unwrap().parse::<u64>().unwrap()),
        );
    }
    ids.sort();
    assert_eq!(ids, (0..600).collect::<Vec<_>>());
}

#[test]
fn removed_compression_is_rejected_before_parsing_csv() {
    let (_dir, job) = fixture("id\n1\n");
    for signature in [[0x28, 0xb5, 0x2f, 0xfd], [0x50, 0x2a, 0x4d, 0x18]] {
        fs::write(&job.input, signature).unwrap();
        let error = prepare(job.clone()).map(|_| ()).unwrap_err();
        assert!(format!("{error:#}").contains("Zstandard input is no longer supported"));
        assert!(!std::path::Path::new(&job.output).exists());
    }
    let error = serde_json::from_str::<Compression>(r#""zstd""#).unwrap_err();
    assert!(error.to_string().contains("Zstandard output compression"));
}

#[test]
fn accepts_empty_output_folder() -> Result<()> {
    let (_dir, job) = fixture("id\n1\n2\n");
    fs::create_dir(&job.output)?;
    prepare(job.clone())?.execute()?;
    assert_eq!(
        csv_files(std::path::Path::new(&job.output)),
        vec![b"id\n1\n2\n".to_vec()]
    );
    Ok(())
}

#[test]
fn preserves_files_added_to_empty_output_during_execution() -> Result<()> {
    let (_dir, job) = fixture(&format!("id\n{}", "1\n".repeat(65536)));
    fs::create_dir(&job.output)?;
    let marker = std::path::Path::new(&job.output).join("keep.txt");
    let marker_notify = marker.clone();
    let executing = Arc::new(AtomicBool::new(false));
    let flag = executing.clone();
    let prepared = engine::prepare(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |p| {
            if flag.load(Ordering::Relaxed) && p.phase == "Writing output" {
                fs::write(&marker_notify, "keep me").unwrap();
            }
        }),
    )?;
    executing.store(true, Ordering::Relaxed);
    assert!(prepared.execute().is_err());
    assert_eq!(fs::read_to_string(marker)?, "keep me");
    assert!(csv_files(std::path::Path::new(&job.output)).is_empty());
    Ok(())
}

#[test]
fn optimized_pipelines_preserve_records_stages_and_unchanged_v1_cases() {
    // Captured from the pre-optimization executable, not generated by this engine.
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/pipeline-v1.json")).unwrap();
    for (index, case) in fixture["cases"].as_array().unwrap().iter().enumerate() {
        let (dir, mut job) = self::fixture(fixture["input"].as_str().unwrap());
        job.random_seed = Some(fixture["seed"].as_str().unwrap().into());
        let mut operations = case["operations"].clone();
        if operations
            .as_array()
            .unwrap()
            .iter()
            .any(|op| op["strategy"] == "buffer")
        {
            // Historical approximate-shuffle cases remain in the immutable fixture.
            continue;
        }
        for op in operations.as_array_mut().unwrap() {
            op.as_object_mut().unwrap().remove("buffer_rows");
        }
        job.operations = serde_json::from_value(operations).unwrap();
        job.resources.workers = 4;
        let prepared = prepare(job).unwrap();
        assert_eq!(
            serde_json::to_value(&prepared.analysis.stages).unwrap(),
            case["stages"],
            "case {index}"
        );
        prepared.execute().unwrap();
        let manifest = fs::read_to_string(dir.path().join("result/manifest.jsonl")).unwrap();
        let mut actual = vec![];
        for line in manifest.lines().skip(1) {
            let mut entry: serde_json::Value = serde_json::from_str(line).unwrap();
            let contents = fs::read_to_string(
                dir.path()
                    .join("result")
                    .join(entry["path"].as_str().unwrap()),
            )
            .unwrap();
            entry["contents"] = contents.into();
            entry.as_object_mut().unwrap().remove("stored_bytes");
            actual.push(entry);
        }
        let changes_random_draws = case["operations"].as_array().unwrap().iter().any(|op| {
            matches!(op["type"].as_str(), Some("assign")) || op["strategy"] == "fisher_yates"
        });
        if changes_random_draws {
            let parse = |text: &str| {
                let mut parser =
                    csv::Parser::new(text.as_bytes(), CsvSettings::default(), 1024 * 1024);
                parser.next_record().unwrap(); // header
                let mut records = Vec::new();
                while let Some(row) = parser.next_record().unwrap() {
                    records.push(row);
                }
                records
            };
            let mut records = Vec::new();
            for entry in &actual {
                let rows = parse(entry["contents"].as_str().unwrap());
                assert_eq!(rows.len() as u64, entry["rows"].as_u64().unwrap());
                records.extend(rows);
            }
            let mut expected = parse(fixture["input"].as_str().unwrap());
            records.sort();
            expected.sort();
            assert_eq!(
                records, expected,
                "case {index}: exact fields and conservation"
            );
            let metadata = |entries: &[serde_json::Value]| {
                entries
                    .iter()
                    .map(|entry| {
                        (
                            entry["lineage"].clone(),
                            entry["rows"].clone(),
                            entry["path"].clone(),
                        )
                    })
                    .collect::<Vec<_>>()
            };
            assert_eq!(
                metadata(&actual),
                metadata(case["outputs"].as_array().unwrap()),
                "case {index}: exact quotas and lineage"
            );
        } else {
            assert_eq!(serde_json::json!(actual), case["outputs"], "case {index}");
        }
    }
}

#[test]
fn parallel_compression_preserves_chunk_contents_and_manifest_order() {
    for compression in [Compression::Gzip, Compression::Zip] {
        let input = format!(
            "id,text\n{}",
            (0..1000).map(|i| format!("{i},ééé\n")).collect::<String>()
        );
        let (dir, mut job) = fixture(&input);
        job.limits.rows = Some(111);
        job.compression = compression;
        job.resources.workers = 1;
        prepare(job.clone()).unwrap().execute().unwrap();
        job.output = dir.path().join("parallel").to_string_lossy().into();
        job.resources.workers = 4;
        prepare(job).unwrap().execute().unwrap();
        let a = fs::read_to_string(dir.path().join("result/manifest.jsonl")).unwrap();
        let b = fs::read_to_string(dir.path().join("parallel/manifest.jsonl")).unwrap();
        assert_eq!(
            a.lines().skip(1).collect::<Vec<_>>(),
            b.lines().skip(1).collect::<Vec<_>>()
        );
        for line in a.lines().skip(1) {
            let entry: serde_json::Value = serde_json::from_str(line).unwrap();
            let name = entry["path"].as_str().unwrap();
            if compression == Compression::Zip {
                let read = |folder: &str| {
                    let mut archive = zip::ZipArchive::new(
                        File::open(dir.path().join(folder).join("outputs.zip")).unwrap(),
                    )
                    .unwrap();
                    let mut contents = Vec::new();
                    archive
                        .by_name(name)
                        .unwrap()
                        .read_to_end(&mut contents)
                        .unwrap();
                    contents
                };
                assert_eq!(read("result"), read("parallel"));
            } else {
                assert_eq!(
                    fs::read(dir.path().join("result").join(name)).unwrap(),
                    fs::read(dir.path().join("parallel").join(name)).unwrap()
                );
            }
        }
    }
}

#[test]
fn multiway_merges_preserve_collision_refinement_across_levels() {
    let mut ctx = Context::new(
        &Resources::default(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .unwrap();
    // A reduced internal sort budget forces multiple merge levels on a small fixture.
    ctx.memory = 1024 * 1024;
    ctx.max_record = 4096;
    let domain = random::domain("merge-levels", 0, "[]");
    let mut sorter = Sorter::new(&ctx, SortOrder::Random(domain));
    for id in 0..12000 {
        sorter
            .push(Row {
                id,
                ordinal: id,
                key: vec![0; 16],
                fields: vec!["x".repeat(256)],
            })
            .unwrap();
    }
    let actual: Vec<_> = sorter
        .finish()
        .unwrap()
        .map(|row| row.unwrap().id)
        .collect();
    let mut expected: Vec<_> = (0..12000).collect();
    expected.sort_by(|a, b| random::compare_ties(&domain, *a, *b));
    assert_eq!(actual, expected);
    assert_eq!(
        ctx.used(),
        0,
        "merge runs must be released after consumption"
    );
}

#[test]
fn grouped_random_merge_refines_collisions_in_each_domain() {
    let mut ctx = Context::new(
        &Resources::default(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .unwrap();
    ctx.memory = 1024 * 1024;
    ctx.max_record = 4096;
    let domains: Vec<_> = (0..3)
        .map(|i| random::domain("group-collisions", 1, &i.to_string()))
        .collect();
    let mut sorter = Sorter::new(&ctx, SortOrder::GroupRandom);
    for id in 0..12000u64 {
        let group = (id % 3) as usize;
        let mut key = vec![group as u8];
        key.extend_from_slice(&[0; 16]);
        key.extend_from_slice(&domains[group]);
        sorter
            .push(Row {
                id,
                ordinal: id,
                key,
                fields: vec!["x".repeat(256)],
            })
            .unwrap();
    }
    let actual: Vec<_> = sorter
        .finish()
        .unwrap()
        .map(|row| row.unwrap().id)
        .collect();
    let mut expected: Vec<_> = (0..12000u64).collect();
    expected.sort_by(|a, b| {
        (a % 3)
            .cmp(&(b % 3))
            .then_with(|| random::compare_ties(&domains[(a % 3) as usize], *a, *b))
    });
    assert_eq!(actual, expected);
    assert_eq!(ctx.used(), 0);
}

#[test]
fn sniffing_is_optional_quote_aware_and_preserves_header_choice() {
    let (_dir, mut job) = fixture("name;note\r\nAlice;\"a,b\"\r\nBob;\"c,d\"\r\n");
    job.input_csv.headers = false;
    let result = engine::sniff_csv(&job).unwrap();
    assert_eq!(result["settings"]["delimiter"], ";");
    assert_eq!(result["settings"]["line_ending"], "crlf");
    assert_eq!(result["settings"]["headers"], false);
    assert_eq!(job.input_csv.delimiter, ',');
}

#[test]
fn sniffing_handles_utf16_bom_and_partial_utf8_sample_tail() {
    let (_dir, job) = fixture("");
    let text = "name\tvalue\r\nA\t1\r\nB\t2\r\n";
    let mut bytes = vec![0xff, 0xfe];
    for unit in text.encode_utf16() {
        bytes.extend(unit.to_le_bytes());
    }
    fs::write(&job.input, bytes).unwrap();
    let result = engine::sniff_csv(&job).unwrap();
    assert_eq!(result["settings"]["encoding"], "utf-16le");
    assert_eq!(result["settings"]["delimiter"], "\t");
    let mut text = "a;b\n1;2\n".to_string();
    text.push_str(&"x".repeat(65535 - text.len()));
    text.push('é');
    fs::write(&job.input, text).unwrap();
    assert!(engine::sniff_csv(&job).is_ok());
}

#[test]
fn selected_values_are_complete_or_explicitly_truncated() {
    let text = format!(
        "id,country\n{}",
        (0..120)
            .map(|i| format!("{i},{}\n", if i % 2 == 0 { "US" } else { "GB" }))
            .collect::<String>()
    );
    let (_dir, mut job) = fixture(&text);
    job.operations = vec![Operation::Assign {
        groups: vec![Allocation {
            name: "all".into(),
            percent: "100".into(),
        }],
        strata: vec![Column::Name("id".into()), Column::Name("country".into())],
    }];
    let prepared = prepare(job).unwrap();
    let values = &prepared.analysis.column_values;
    assert_eq!(values[0].values.len(), 100);
    assert!(values[0].truncated);
    assert_eq!(
        values[1].values.iter().cloned().collect::<Vec<_>>(),
        ["GB", "US"]
    );
    assert!(!values[1].truncated);
}

#[test]
fn prepared_header_reservation_lives_until_snapshot_is_dropped() -> Result<()> {
    for plain in [false, true] {
        let (dir, mut job) = fixture("identifier,text\n0,a\n1,b\n");
        if !plain {
            job.operations = vec![
                Operation::Balanced { files: 2 },
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
            ];
        }
        let prepared = prepare(job)?;
        let ctx = prepared.ctx.clone();
        let fields = prepared.analysis.header.as_ref().unwrap();
        let header_bytes = fields.reserved_bytes();
        let paths = ctx.diagnostics()["temporary_path_reserved_bytes"]
            .as_u64()
            .unwrap();
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            paths
                + prepared.job.reserved_bytes()
                + prepared.analysis.preview.reserved_bytes()
                + prepared.analysis.warnings.reserved_bytes()
                + prepared.analysis.timings.reserved_bytes()
                + prepared.analysis.diagnostics.reserved_bytes()
                + prepared.analysis.text_reserved_bytes()
                + prepared.analysis.stages.reserved_bytes()
                + prepared.analysis.column_values.reserved_bytes()
                + header_bytes
                + ctx.diagnostics()["directory_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        );
        assert!(!dir.path().join("result").exists());
        drop(prepared);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.diagnostics()["directory_path_reserved_bytes"]
        );
        assert_eq!(ctx.used(), 0);
    }
    Ok(())
}
