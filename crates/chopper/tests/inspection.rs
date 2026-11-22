use chopper::{core::Job, engine};
use std::io::{Cursor, Write};

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
    std::fs::write(&input, format!("note\n{}\n", "x".repeat(32769)))?;
    assert_eq!(
        engine::input_preview(&job)?["preview"],
        serde_json::json!([])
    );
    Ok(())
}
