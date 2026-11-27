use chopper::{
    core::{Column, CsvTrim, InputDialect, Job, Operation, Resources},
    engine,
};
use std::{
    fs,
    path::Path,
    sync::{atomic::AtomicBool, Arc},
};

fn run(job: Job) -> anyhow::Result<chopper::engine::Analysis> {
    engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}

fn chunks(path: &Path) -> anyhow::Result<Vec<Vec<u8>>> {
    let mut files = fs::read_dir(path)?
        .map(|entry| entry.map(|entry| entry.path()))
        .collect::<Result<Vec<_>, _>>()?;
    files.retain(|path| path.extension().is_some_and(|ext| ext == "csv"));
    files.sort();
    files.into_iter().map(|path| Ok(fs::read(path)?)).collect()
}

#[test]
fn dialect_changes_the_input_schema_used_by_preview_and_run() -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("data.csv");
    fs::write(
        &input,
        concat!(
            "Generated report\r\n",
            "# Ignore a comment\r\n",
            "index; team ; text \r\n",
            "; ;\r\n",
            "1; A ;\" héllo\r\n# still text \"\r\n",
            "#skip, this \"\r\n",
            "2; A ;keep\r\n",
        ),
    )?;
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        output: dir.path().join("out").to_string_lossy().into_owned(),
        input_dialect: InputDialect {
            trim: CsvTrim::Both,
            comment_prefix: Some("#".into()),
            skip_rows: 1,
            skip_columns: 1,
            skip_blank_rows: true,
        },
        resources: Resources {
            workers: 1,
            ..Resources::default()
        },
        ..Job::default()
    };
    assert_eq!(engine::sniff_csv(&job)?["settings"]["delimiter"], ";");
    job.input_csv.delimiter = ';';
    let preview = engine::input_preview(&job)?;
    assert_eq!(preview["header"], serde_json::json!(["team", "text"]));
    assert_eq!(
        preview["preview"],
        serde_json::json!([["A", "héllo\r\n# still text"], ["A", "keep"]])
    );
    for operations in [
        vec![],
        vec![Operation::Partition {
            columns: vec![Column::Name("team".into())],
        }],
    ] {
        job.operations = operations;
        let output = dir.path().join(format!("out-{}", job.operations.len()));
        job.output = output.to_string_lossy().into_owned();
        assert_eq!(run(job.clone())?.rows, 2);
        assert_eq!(
            chunks(&output)?,
            [b"team,text\nA,\"h\xc3\xa9llo\r\n# still text\"\nA,keep\n".to_vec()]
        );
    }
    Ok(())
}

#[test]
fn every_chunk_preserves_literal_leading_feff_and_accounts_for_its_quotes() -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("data.csv");
    fs::write(&input, "a,x\n\"\u{feff}value\",x\n")?;
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Job::default()
    };
    job.input_csv.headers = false;
    job.output_csv.headers = false;
    job.output_csv.quote = '\'';
    job.limits.rows = Some(1);
    for encoding in ["utf-8", "utf-16le", "utf-16be"] {
        let output = dir.path().join(encoding);
        job.output = output.to_string_lossy().into_owned();
        job.output_csv.encoding = encoding.into();
        let encoded = |s| chopper::core::csv::encode(s, encoding).unwrap();
        let expected = [encoded("a,x\n"), encoded("'\u{feff}value',x\n")];
        job.limits.bytes = Some(expected[1].len() as u64);
        let result = run(job.clone())?;
        assert_eq!(chunks(&output)?, expected);
        assert_eq!(
            result.output_csv_bytes,
            expected.iter().map(|x| x.len() as u64).sum::<u64>()
        );

        let rejected = dir.path().join(format!("{encoding}-over-cap"));
        job.output = rejected.to_string_lossy().into_owned();
        job.limits.bytes = Some(expected[1].len() as u64 - 1);
        assert!(
            format!("{:#}", run(job.clone()).unwrap_err()).contains("exceeds output byte limit")
        );
        assert!(!rejected.exists());
    }

    fs::write(&input, "\"\u{feff}name\",note\n1,x\n")?;
    let output = dir.path().join("header");
    job.output = output.to_string_lossy().into_owned();
    job.input_csv.headers = true;
    job.output_csv.headers = true;
    job.output_csv.encoding = "utf-8".into();
    job.limits.bytes = None;
    run(job)?;
    assert_eq!(chunks(&output)?, ["'\u{feff}name',note\n1,x\n".as_bytes()]);
    Ok(())
}
