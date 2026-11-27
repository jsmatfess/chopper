use chopper::{core::Job, engine};
use std::io::{Cursor, Write};

#[test]
fn sniff_preserves_an_explicit_encoding_and_declines_ambiguous_or_invalid_suggestions(
) -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("input.csv");
    let mut job = Job {
        input: path.to_string_lossy().into(),
        ..Job::default()
    };
    for text in [
        "id;last,first\n1;Doe,Jane\n",
        "id|last,first,city\n1|Doe,Jane,Paris\n",
    ] {
        std::fs::write(&path, text)?;
        let suggestion = engine::sniff_csv(&job)?;
        assert_eq!(suggestion["settings"]["delimiter"], ",");
        assert!(suggestion["note"]
            .as_str()
            .unwrap()
            .contains("More than one delimiter"));
    }
    std::fs::write(&path, "|id|;|note|\n|1|;|a|\n")?;
    job.input_csv.quote = '|';
    assert_eq!(engine::sniff_csv(&job)?["settings"]["delimiter"], ";");

    job.input_csv.quote = '"';
    job.input_csv.encoding = "windows-1252".into();
    std::fs::write(&path, b"id;note\n1;caf\xe9\n")?;
    let suggestion = engine::sniff_csv(&job)?;
    assert_eq!(suggestion["settings"]["encoding"], "windows-1252");
    assert_eq!(suggestion["settings"]["delimiter"], ";");

    let utf16: Vec<u8> = "id;note\n1;plain\n"
        .encode_utf16()
        .flat_map(u16::to_le_bytes)
        .collect();
    std::fs::write(&path, utf16)?;
    job.input_csv.encoding = "utf-8".into();
    assert!(engine::sniff_csv(&job)
        .unwrap_err()
        .to_string()
        .contains("UTF-16LE"));
    job.input_csv.encoding = "utf-16le".into();
    let suggestion = engine::sniff_csv(&job)?;
    assert_eq!(suggestion["settings"]["encoding"], "utf-16le");
    assert_eq!(suggestion["settings"]["delimiter"], ";");
    Ok(())
}

#[test]
fn sniff_uses_complete_records_and_their_line_endings() -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("source.csv");
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Job::default()
    };
    for text in [
        "id;note\n",
        "id;note\n1;\"unterminated",
        "id;note\n1;text\n2;\"broken",
    ] {
        std::fs::write(&input, text)?;
        let result = engine::sniff_csv(&job)?;
        assert_eq!(result["settings"]["delimiter"], ",");
        assert!(result["note"].as_str().unwrap().contains("No delimiter"));
    }

    let mut clipped = format!("{};note\n1;", "x".repeat(64)).into_bytes();
    clipped.resize(65536, b'x');
    clipped.extend(b"\n2;last\n");
    std::fs::write(&input, clipped)?;
    assert_eq!(engine::sniff_csv(&job)?["settings"]["delimiter"], ",");

    job.input_dialect.skip_rows = 1;
    job.input_dialect.comment_prefix = Some("#".into());
    job.input_csv.line_ending = "crlf".into();
    std::fs::write(
        &input,
        "preamble\r\n# outside\r\nid;note\n1;\"first\r\nsecond\"\n2;last",
    )?;
    let result = engine::sniff_csv(&job)?;
    assert_eq!(result["settings"]["delimiter"], ";");
    assert_eq!(result["settings"]["line_ending"], "lf");

    job.input_csv.line_ending = "lf".into();
    std::fs::write(&input, "preamble\r\nid;note\n1;a\r\n2;b")?;
    let result = engine::sniff_csv(&job)?;
    assert_eq!(result["settings"]["delimiter"], ";");
    assert_eq!(result["settings"]["line_ending"], "lf");
    Ok(())
}

#[test]
fn sniff_flags_utf32_signatures_before_selecting_utf16() -> anyhow::Result<()> {
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("source.csv");
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Job::default()
    };
    for (bom, encoding) in [(b"\xff\xfe\0\0", "UTF-32LE"), (b"\0\0\xfe\xff", "UTF-32BE")] {
        std::fs::write(&input, bom)?;
        assert!(engine::sniff_csv(&job)
            .unwrap_err()
            .to_string()
            .contains(encoding));
    }
    let mut utf16 = b"\xff\xfe".to_vec();
    utf16.extend("\0id;note\n1;a\n".encode_utf16().flat_map(u16::to_le_bytes));
    std::fs::write(&input, utf16)?;
    job.input_csv.encoding = "utf-16le".into();
    let result = engine::sniff_csv(&job)?;
    assert_eq!(result["settings"]["encoding"], "utf-16le");
    assert_eq!(result["settings"]["delimiter"], ";");
    Ok(())
}

fn representations(source: &[u8]) -> anyhow::Result<Vec<(&'static str, Vec<u8>)>> {
    let mut gzip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    gzip.write_all(source)?;
    let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
    zip.start_file("sample.csv", zip::write::SimpleFileOptions::default())?;
    zip.write_all(source)?;
    Ok(vec![
        ("plain", source.to_vec()),
        ("gzip", gzip.finish()?),
        ("zip", zip.finish()?.into_inner()),
    ])
}

#[test]
fn public_inspection_preserves_bom_dialect_and_headers_through_input_adapters() -> anyhow::Result<()>
{
    let text = "name;note\r\nAlice;\"a,b\"\r\nBob;\"c,d\"\r\n";
    let mut source = vec![0xfe, 0xff];
    for unit in text.encode_utf16() {
        source.extend_from_slice(&unit.to_be_bytes());
    }
    let directory = tempfile::tempdir()?;
    for (kind, bytes) in representations(&source)? {
        // The adapter must follow the signature rather than the path extension.
        let path = directory.path().join(format!("{kind}.data"));
        std::fs::write(&path, bytes)?;
        let mut job = Job {
            input: path.to_string_lossy().into_owned(),
            output: directory
                .path()
                .join("unused-output")
                .to_string_lossy()
                .into_owned(),
            ..Job::default()
        };
        job.input_csv.headers = false;
        let suggestion = engine::sniff_csv(&job)?;
        assert_eq!(suggestion["settings"]["encoding"], "utf-16be", "{kind}");
        assert_eq!(suggestion["settings"]["bom"], true, "{kind}");
        assert_eq!(suggestion["settings"]["delimiter"], ";", "{kind}");
        assert_eq!(suggestion["settings"]["line_ending"], "crlf", "{kind}");
        assert_eq!(suggestion["settings"]["headers"], false, "{kind}");
        assert_eq!(job.input_csv.delimiter, ',');
        job.input_csv = serde_json::from_value(suggestion["settings"].clone())?;
        let columns = engine::input_columns(&job)?;
        assert_eq!(columns["columns"], 2, "{kind}");
        assert!(columns["header"].is_null(), "{kind}");
        assert_eq!(columns["input_is_zip"], kind == "zip", "{kind}");
        job.input_csv.headers = true;
        assert_eq!(
            engine::input_columns(&job)?["header"],
            serde_json::json!(["name", "note"])
        );
        let preview = engine::input_preview(&job)?;
        assert_eq!(
            preview["preview"],
            serde_json::json!([["Alice", "a,b"], ["Bob", "c,d"]]),
            "{kind}"
        );
        assert_eq!(
            preview["header"],
            serde_json::json!(["name", "note"]),
            "{kind}"
        );
        job.input_csv.headers = false;
        assert_eq!(
            engine::input_preview(&job)?["preview"][0],
            serde_json::json!(["name", "note"]),
            "{kind}"
        );
        assert!(!std::path::Path::new(&job.output).exists());
    }
    // Inspection must not prepare a workspace or create output artifacts.
    assert_eq!(std::fs::read_dir(directory.path())?.count(), 3);
    Ok(())
}

#[test]
fn public_sniff_sample_limit_applies_to_decompressed_bytes() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let mut source = b"a;b\n1;2\n".repeat(8192);
    assert_eq!(source.len(), 65536);
    // Strict UTF-8 decoding would reject this byte if sampling read beyond its cap.
    source.push(0xff);
    for (kind, bytes) in representations(&source)? {
        let path = directory.path().join(format!("{kind}.data"));
        std::fs::write(&path, bytes)?;
        let job = Job {
            input: path.to_string_lossy().into_owned(),
            ..Job::default()
        };
        let result = engine::sniff_csv(&job)?;
        assert_eq!(result["settings"]["delimiter"], ";", "{kind}");
        assert_eq!(result["settings"]["encoding"], "utf-8", "{kind}");
    }
    Ok(())
}

#[test]
fn preview_is_bounded_and_does_not_validate_unseen_records() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let input = directory.path().join("sample.csv");
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Job::default()
    };
    std::fs::write(
        &input,
        format!("id,note\n{}\"unterminated", "1,hello\n".repeat(8)),
    )?;
    let sample = engine::input_preview(&job)?;
    assert_eq!(sample["columns"], 2);
    assert_eq!(sample["preview"].as_array().unwrap().len(), 8);
    std::fs::write(&input, "id,note\n1\n")?;
    assert!(engine::input_preview(&job).is_err());
    for (source, header) in [
        ("", serde_json::Value::Null),
        ("id,note\n", serde_json::json!(["id", "note"])),
    ] {
        std::fs::write(&input, source)?;
        let sample = engine::input_preview(&job)?;
        assert_eq!(sample["header"], header);
        assert_eq!(sample["preview"], serde_json::json!([]));
    }
    std::fs::write(&input, format!("note\n{}\nsmall\n", "x".repeat(32769)))?;
    let sample = engine::input_preview(&job)?;
    assert_eq!(sample["preview"], serde_json::json!([["small"]]));
    assert_eq!(sample["preview_row_numbers"], serde_json::json!([2]));
    Ok(())
}

#[test]
fn formula_sample_continues_from_its_byte_boundary() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let input = directory.path().join("sample.csv");
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Job::default()
    };
    let wide = "x".repeat(600_000);
    std::fs::write(
        &input,
        format!("tag,note\nfirst,{wide}\nsecond,{wide}\nthird,small\n"),
    )?;
    let mut batches = Vec::new();
    engine::sample_formula_rows(
        &job,
        |batch| {
            let value = serde_json::to_value(batch)?;
            let rows = value["rows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| {
                    (
                        row[0].as_u64().unwrap(),
                        row[1][0].as_str().unwrap().to_owned(),
                    )
                })
                .collect::<Vec<_>>();
            batches.push((rows, value["done"].as_bool().unwrap()));
            Ok(())
        },
        || Ok(true),
    )?;
    assert_eq!(
        batches,
        [
            (vec![(1, "first".to_owned())], false),
            (
                vec![(2, "second".to_owned()), (3, "third".to_owned())],
                true
            ),
        ]
    );
    Ok(())
}
