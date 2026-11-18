use anyhow::Result;
use chopper::{
    core::*,
    engine::{self, Analysis},
    resources::MemoryPool,
};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fs,
    io::{Read, Write},
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

fn setup(input: &[u8]) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    fs::write(dir.path().join("input.csv"), input)?;
    fs::create_dir(dir.path().join("temp"))?;
    let job = Job {
        input: dir.path().join("input.csv").to_string_lossy().into(),
        output: dir.path().join("direct").to_string_lossy().into(),
        random_seed: Some("direct-test".into()),
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 1024 * 1024,
            temp_dir: Some(dir.path().join("temp").to_string_lossy().into()),
            ..Default::default()
        },
        ..Default::default()
    };
    Ok((dir, job))
}
fn run(job: Job) -> Result<Analysis> {
    engine::run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
}
fn manifest(output: &str) -> Result<Vec<Value>> {
    fs::read_to_string(Path::new(output).join("manifest.jsonl"))?
        .lines()
        .map(|line| Ok(serde_json::from_str(line)?))
        .collect()
}
fn csvs(output: &str, compression: Compression) -> Result<BTreeMap<String, Vec<u8>>> {
    let mut result = BTreeMap::new();
    if compression == Compression::Zip {
        let mut zip = zip::ZipArchive::new(fs::File::open(Path::new(output).join("outputs.zip"))?)?;
        for i in 0..zip.len() {
            let mut file = zip.by_index(i)?;
            let name = file.name().to_owned();
            let mut bytes = Vec::new();
            file.read_to_end(&mut bytes)?;
            if name == "manifest.jsonl" {
                assert_eq!(bytes, fs::read(Path::new(output).join(&name))?);
            } else {
                result.insert(name, bytes);
            }
        }
    } else {
        for record in manifest(output)?
            .into_iter()
            .filter(|r| r["type"] == "output")
        {
            let name = record["path"].as_str().unwrap();
            let bytes = fs::read(Path::new(output).join(name))?;
            let decoded = match compression {
                Compression::None => bytes,
                Compression::Gzip => {
                    let mut decoded = Vec::new();
                    flate2::read::GzDecoder::new(&bytes[..]).read_to_end(&mut decoded)?;
                    decoded
                }
                Compression::Zstd => zstd::stream::decode_all(&bytes[..])?,
                Compression::Zip => unreachable!(),
            };
            result.insert(name.into(), decoded);
        }
    }
    Ok(result)
}
fn stable(analysis: &Analysis) -> Result<Value> {
    let mut value = serde_json::to_value(analysis)?;
    for key in [
        "temp_bytes",
        "peak_temp_bytes",
        "analysis_seconds",
        "timings",
        "diagnostics",
    ] {
        value.as_object_mut().unwrap().remove(key);
    }
    Ok(value)
}
fn parity(job: Job) -> Result<Analysis> {
    let direct = run(job.clone())?;
    let direct_manifest = manifest(&job.output)?;
    assert_eq!(direct_manifest[0]["type"], "job");
    assert_eq!(
        direct_manifest[0]["analysis"],
        serde_json::to_value(&direct)?
    );
    let mut prepared_job = job.clone();
    prepared_job.output.push_str("-prepared");
    let prepared = engine::prepare(
        prepared_job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?
    .execute()?;
    assert_eq!(stable(&direct)?, stable(&prepared)?);
    assert_eq!(
        csvs(&job.output, job.compression)?,
        csvs(&prepared_job.output, job.compression)?
    );
    // Stored compressed sizes may differ with the encoder's write batching.
    let normalize = |records: Vec<Value>| {
        records
            .into_iter()
            .skip(1)
            .map(|mut r| {
                r.as_object_mut().unwrap().remove("stored_bytes");
                r
            })
            .collect::<Vec<_>>()
    };
    assert_eq!(
        normalize(direct_manifest),
        normalize(manifest(&prepared_job.output)?)
    );
    Ok(direct)
}
fn clean(dir: &Path, job: &Job) -> Result<()> {
    assert!(!Path::new(&job.output).exists());
    assert_eq!(fs::read_dir(dir.join("temp"))?.count(), 0);
    assert!(!fs::read_dir(dir)?.any(|e| e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".chopper-staging-")));
    Ok(())
}

#[test]
fn formats_caps_fields_digest_names_and_manifest_parity() -> Result<()> {
    for compression in [
        Compression::None,
        Compression::Gzip,
        Compression::Zstd,
        Compression::Zip,
    ] {
        let (_dir, mut job) = setup(
            "id,text\n1,\"comma,quote\"\"\"\n2,\"line\nbreak\"\n3,\u{754c}\u{1f600}\n4,\n"
                .as_bytes(),
        )?;
        job.compression = compression;
        job.limits.rows = Some(2);
        job.limits.bytes = Some(55);
        let analysis = parity(job)?;
        assert_eq!(analysis.rows, 4);
        assert!(analysis.output_files >= 2);
    }
    Ok(())
}

#[test]
fn utf16_bom_and_headerless_empty_parity() -> Result<()> {
    for encoding in ["utf-16le", "utf-16be"] {
        let (_dir, mut job) = setup("\u{540d},value\n\u{754c},\u{1f600}\na,b\n".as_bytes())?;
        job.input_csv.encoding = encoding.into();
        job.output_csv.encoding = encoding.into();
        job.output_csv.bom = true;
        let mut bytes = chopper::core::csv::bom(&job.output_csv)?;
        for row in [
            vec!["\u{540d}".into(), "value".into()],
            vec!["\u{754c}".into(), "\u{1f600}".into()],
            vec!["a".into(), "b".into()],
        ] {
            bytes.extend(chopper::core::csv::serialize(&row, &job.output_csv)?);
        }
        fs::write(&job.input, bytes)?;
        job.limits.rows = Some(1);
        job.limits.bytes = Some(40);
        let analysis = parity(job)?;
        assert_eq!(analysis.output_files, 2);
    }
    for bytes in [
        b"".as_slice(),
        b"a,b\n".as_slice(),
        b"1,2\n3,4\n".as_slice(),
    ] {
        for headers in [true, false] {
            let (_dir, mut job) = setup(bytes)?;
            job.input_csv.headers = headers;
            job.output_csv.headers = headers;
            parity(job)?;
        }
    }
    Ok(())
}

#[test]
fn late_wide_rows_and_soft_compressed_targets_match() -> Result<()> {
    let text = format!("a,b\n1,x\n2,{}\n3,z\n", "q".repeat(40000));
    let (_dir, mut job) = setup(text.as_bytes())?;
    job.limits.bytes = Some(41000);
    job.limits.compressed_bytes = Some(300);
    job.compression = Compression::Gzip;
    let analysis = parity(job)?;
    assert_eq!(analysis.rows, 3);
    assert_eq!(analysis.largest_record_bytes, 40001);
    Ok(())
}

#[test]
fn no_encoded_snapshot_spool() -> Result<()> {
    let text = format!("id,value\n{}", "1,abcdefghijklmnop\n".repeat(10000));
    for codec in [
        Compression::None,
        Compression::Gzip,
        Compression::Zstd,
        Compression::Zip,
    ] {
        let (dir, mut job) = setup(text.as_bytes())?;
        job.compression = codec;
        job.resources.temp_bytes = Some(4096);
        let analysis = run(job.clone())?;
        assert_eq!(analysis.rows, 10000);
        assert!(analysis.output_csv_bytes > 100000);
        assert!(analysis.peak_temp_bytes < 4096);
        let mut prepared_job = job.clone();
        prepared_job.output.push_str("-prepared");
        assert!(engine::prepare(
            prepared_job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {})
        )
        .is_err());
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        assert_eq!(manifest(&job.output)?.len(), 2);
    }
    Ok(())
}

#[test]
fn late_parse_width_cap_and_file_limit_errors_cleanup() -> Result<()> {
    for (text, rows, bytes, max_files) in [
        ("a,b\n1,x\n2,\"unterminated", Some(1), None, 100),
        ("a,b\n1,x\n2,y,z\n", Some(1), None, 100),
        ("a,b\n1,x\n2,xxxxxxxxxxxxxxxxxxx\n", Some(1), Some(12), 100),
        ("a,b\n1,x\n2,y\n", Some(1), None, 1),
        ("long-header,b\n1,x\n", None, Some(2), 100),
    ] {
        let (dir, mut job) = setup(text.as_bytes())?;
        job.limits.rows = rows;
        job.limits.bytes = bytes;
        job.resources.max_files = max_files;
        assert!(run(job.clone()).is_err());
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[test]
fn cancellation_and_mutation_never_publish_or_retry() -> Result<()> {
    for (mutate, codec) in [false, true].into_iter().flat_map(|m| {
        [
            Compression::None,
            Compression::Gzip,
            Compression::Zstd,
            Compression::Zip,
        ]
        .into_iter()
        .map(move |c| (m, c))
    }) {
        let text = format!("a,b\n{}", "1,x\n".repeat(65536));
        let (dir, mut job) = setup(text.as_bytes())?;
        job.compression = codec;
        let cancel = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let input = job.input.clone();
        let result = engine::run(
            job.clone(),
            cancel,
            Arc::new(move |progress| {
                if progress.phase == "Serializing output" {
                    if mutate {
                        fs::OpenOptions::new()
                            .append(true)
                            .open(&input)
                            .unwrap()
                            .write_all(b"2,y\n")
                            .unwrap();
                    } else {
                        signal.store(true, Ordering::Relaxed);
                    }
                }
            }),
        );
        assert!(result.is_err());
        let error = result.unwrap_err().to_string();
        assert!(
            if mutate {
                error.contains("input changed")
            } else {
                error.contains("cancel")
            },
            "{error}"
        );
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[test]
fn nonempty_pipeline_falls_back_to_exact_preparation() -> Result<()> {
    let (_dir, mut job) = setup(b"a,b\n1,x\n2,y\n3,z\n4,q\n")?;
    job.operations = vec![Operation::Balanced { files: 2 }];
    let analysis = parity(job)?;
    assert_eq!(analysis.stages.len(), 1);
    assert_eq!(analysis.groups, 2);
    Ok(())
}

#[test]
fn returned_analysis_clones_retain_admitted_owners() -> Result<()> {
    let (_dir, job) = setup(b"a,b\n1,x\n2,y\n")?;
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let analysis = engine::run_with_memory_pool(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    assert!(analysis.header.as_ref().unwrap().reserved_bytes() > 0);
    assert!(analysis.preview.reserved_bytes() > 0);
    assert!(analysis.text_reserved_bytes() > 0);
    assert!(analysis.timings.reserved_bytes() > 0);
    assert!(analysis.diagnostics.reserved_bytes() > 0);
    let cloned = analysis.clone();
    let reserved = pool.usage().reserved_bytes;
    drop(analysis);
    assert_eq!(pool.usage().reserved_bytes, reserved);
    drop(cloned);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}

#[test]
fn compressed_inputs_and_late_codec_corruption_cleanup() -> Result<()> {
    let text = b"a,b\n1,x\n2,y\n3,z\n";
    for codec in [Compression::Gzip, Compression::Zstd, Compression::Zip] {
        let (dir, mut job) = setup(text)?;
        let encoded = match codec {
            Compression::Gzip => {
                let mut encoder =
                    flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
                encoder.write_all(text)?;
                encoder.finish()?
            }
            Compression::Zstd => zstd::stream::encode_all(&text[..], 3)?,
            Compression::Zip => {
                let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
                zip.start_file(
                    "input.csv",
                    zip::write::SimpleFileOptions::default()
                        .compression_method(zip::CompressionMethod::Deflated),
                )?;
                zip.write_all(text)?;
                zip.finish()?.into_inner()
            }
            _ => unreachable!(),
        };
        fs::write(&job.input, &encoded)?;
        job.limits.rows = Some(1);
        parity(job.clone())?;
        // Truncated trailers/central directory must not publish any result.
        let mut corrupt = encoded.clone();
        corrupt.truncate(corrupt.len() - 3);
        fs::write(&job.input, corrupt)?;
        job.output = dir.path().join("corrupt").to_string_lossy().into();
        assert!(
            run(job.clone()).is_err(),
            "{codec:?} accepted truncated input"
        );
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[test]
fn all_output_codecs_late_failure_and_temp_denial_cleanup() -> Result<()> {
    for codec in [
        Compression::None,
        Compression::Gzip,
        Compression::Zstd,
        Compression::Zip,
    ] {
        let (dir, mut job) = setup(b"a,b\n1,x\n2,y,z\n")?;
        job.compression = codec;
        job.limits.rows = Some(1);
        assert!(run(job.clone()).is_err());
        clean(dir.path(), &job)?;
        fs::write(&job.input, b"a,b\n1,x\n2,y\n")?;
        job.resources.temp_bytes = Some(1);
        assert!(run(job.clone()).is_err());
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[test]
fn destination_race_preserves_other_writer_and_cleans_stage() -> Result<()> {
    for initially_empty in [false, true] {
        let text = format!("a,b\n{}", "1,x\n".repeat(65536));
        let (dir, job) = setup(text.as_bytes())?;
        if initially_empty {
            fs::create_dir(&job.output)?;
        }
        let output = job.output.clone();
        let result = engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |progress| {
                if progress.phase == "Serializing output" {
                    if !Path::new(&output).exists() {
                        fs::create_dir(&output).unwrap();
                    }
                    fs::write(Path::new(&output).join("other-writer"), b"preserve").unwrap();
                }
            }),
        );
        assert!(result.is_err());
        assert_eq!(
            fs::read(Path::new(&job.output).join("other-writer"))?,
            b"preserve"
        );
        assert_eq!(fs::read_dir(&job.output)?.count(), 1);
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        assert!(!fs::read_dir(dir.path())?.any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".chopper-staging-")));
    }
    Ok(())
}

#[test]
fn shared_denial_retained_owner_release_and_retry() -> Result<()> {
    let input = format!("{}\nx\n", "h".repeat(200000));
    let (_probe_dir, probe_job) = setup(input.as_bytes())?;
    let probe_pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let probe = engine::run_with_memory_pool(
        probe_job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        probe_pool.clone(),
    )?;
    let peak = probe_pool.usage().peak_reserved_bytes;
    let retained = probe_pool.usage().reserved_bytes;
    assert!(retained > 100000);
    drop(probe);
    let (dir, mut job) = setup(input.as_bytes())?;
    job.output = dir.path().join("first").to_string_lossy().into();
    let pool = Arc::new(MemoryPool::new(peak + retained / 2 + 4096));
    let first = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let reserved = pool.usage().reserved_bytes;
    job.output = dir.path().join("again").to_string_lossy().into();
    let denied = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )
    .map(|_| ())
    .expect_err("expected admission denial");
    assert!(
        denied
            .to_string()
            .contains("shared process memory admission"),
        "{denied:#}"
    );
    assert_eq!(pool.usage().reserved_bytes, reserved);
    clean(dir.path(), &job)?;
    drop(first);
    assert_eq!(pool.usage().reserved_bytes, 0);
    drop(engine::run_with_memory_pool(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}

#[test]
fn local_denial_releases_all_owners() -> Result<()> {
    let input = format!("{}\n{}\n", "h".repeat(1900000), "x".repeat(1900000));
    let (dir, mut job) = setup(input.as_bytes())?;
    job.resources.max_record_bytes = 2 * 1024 * 1024;
    job.output_csv.encoding = "utf-16le".into();
    job.compression = Compression::Zstd;
    let pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
    let error = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )
    .map(|_| ())
    .expect_err("expected admission denial");
    assert!(
        error
            .to_string()
            .contains("concurrent algorithm workspaces"),
        "{error:#}"
    );
    assert_eq!(pool.usage().reserved_bytes, 0);
    clean(dir.path(), &job)?;
    job.resources.memory_mb = 128.into();
    drop(engine::run_with_memory_pool(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}

#[test]
fn late_encoding_errors_and_existing_empty_destination_cleanup() -> Result<()> {
    for (input, encoding) in [
        (b"h\nx\n\xff\n".to_vec(), "utf-8"),
        (
            vec![0xff, 0xfe, b'h', 0, b'\n', 0, b'x', 0, b'\n', 0, 0, 0xd8],
            "utf-16le",
        ),
    ] {
        let (dir, mut job) = setup(&input)?;
        job.input_csv.encoding = encoding.into();
        job.limits.rows = Some(1);
        fs::create_dir(&job.output)?;
        assert!(run(job.clone()).is_err());
        assert_eq!(fs::read_dir(&job.output)?.count(), 0);
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        assert!(!fs::read_dir(dir.path())?.any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".chopper-staging-")));
    }
    let (dir, mut job) = setup("h\nx\n\u{754c}\n".as_bytes())?;
    job.output_csv.encoding = "windows-1252".into();
    job.limits.rows = Some(1);
    assert!(run(job.clone()).is_err());
    clean(dir.path(), &job)?;
    Ok(())
}
