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
        "auto_plan",
    ] {
        value.as_object_mut().unwrap().remove(key);
    }
    Ok(value)
}
fn parity(job: Job) -> Result<Analysis> {
    let direct = run(job.clone())?;
    let direct_manifest = manifest(&job.output)?;
    assert_eq!(direct_manifest[0]["type"], "job");
    // Compare parsed wire JSON on both sides; fractional timings can shift by
    // one float step in serde_json's default parser.
    let mut report = serde_json::from_slice::<Value>(&serde_json::to_vec(&direct)?)?;
    assert!(report
        .as_object_mut()
        .unwrap()
        .remove("auto_plan")
        .is_some());
    assert_eq!(direct_manifest[0]["analysis"], report);
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
    for compression in [Compression::None, Compression::Gzip, Compression::Zip] {
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
    for codec in [Compression::None, Compression::Gzip, Compression::Zip] {
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
        [Compression::None, Compression::Gzip, Compression::Zip]
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
    for codec in [Compression::Gzip, Compression::Zip] {
        let (dir, mut job) = setup(text)?;
        let encoded = match codec {
            Compression::Gzip => {
                let mut encoder =
                    flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
                encoder.write_all(text)?;
                encoder.finish()?
            }
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
    for codec in [Compression::None, Compression::Gzip, Compression::Zip] {
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
fn direct_zip_publishes_when_compressed_member_exceeds_temp_budget() -> Result<()> {
    let mut source = b"id,payload\n".to_vec();
    let mut state = 1u32;
    for row in 0..1024 {
        write!(source, "{row},")?;
        for _ in 0..512 {
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            source.push(b'a' + (state % 26) as u8);
        }
        source.push(b'\n');
    }
    let (_dir, mut job) = setup(&source)?;
    job.compression = Compression::Zip;
    let budget = 64 * 1024;
    job.resources.temp_bytes = Some(budget);
    job.limits.bytes = Some(source.len() as u64);
    let analysis = run(job.clone())?;
    assert_eq!(analysis.output_files, 1);
    assert_eq!(analysis.output_csv_bytes, source.len() as u64);
    assert!(analysis.peak_temp_bytes < budget);
    let mut archive =
        zip::ZipArchive::new(fs::File::open(Path::new(&job.output).join("outputs.zip"))?)?;
    let mut member = archive.by_name("part-00000001.csv")?;
    assert!(member.compressed_size() > budget);
    let mut decoded = Vec::new();
    member.read_to_end(&mut decoded)?;
    assert_eq!(decoded, source);
    Ok(())
}

#[test]
fn local_denial_releases_all_owners() -> Result<()> {
    let input = format!(
        "{}\n{}\n",
        "h".repeat(1900000),
        '"'.to_string().repeat(1900000)
    );
    let (dir, mut job) = setup(input.as_bytes())?;
    job.resources.max_record_bytes = 2 * 1024 * 1024;
    job.input_csv.quote = '\'';
    job.output_csv.encoding = "utf-16le".into();
    job.compression = Compression::Gzip;
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

#[test]
fn terminal_balanced_direct_matches_snapshot_names_bytes_lineage_and_analysis() -> Result<()> {
    for (headers, encoding, bom, workers) in [
        (true, "utf-8", false, 1),
        (false, "utf-8", false, 4),
        (true, "utf-16le", true, 0),
    ] {
        let (dir, mut job) = setup(
            "id,text\n1,\"comma,quote\"\"\"\n2,\"line\nbreak\"\n3,界\n4,\n5,last\n".as_bytes(),
        )?;
        job.operations = vec![Operation::Balanced { files: 2 }];
        job.input_csv.headers = headers;
        job.output_csv.headers = headers;
        job.output_csv.encoding = encoding.into();
        job.output_csv.bom = bom;
        job.resources.workers = workers;
        job.limits.rows = Some(3);
        job.limits.bytes = Some(4096);
        let result = parity(job.clone())?;
        assert_eq!(result.groups, 2);
        assert_eq!(result.output_files, 2);
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}

#[test]
fn terminal_balanced_late_errors_cancel_and_destination_race_never_publish_partial_output(
) -> Result<()> {
    for mode in ["encoding", "cap", "rows", "cancel-final", "race"] {
        let (dir, mut job) = setup("id,text\n1,first\n2,界\n3,last\n".as_bytes())?;
        job.operations = vec![Operation::Balanced {
            files: if mode == "rows" { 4 } else { 3 },
        }];
        if mode == "encoding" {
            job.output_csv.encoding = "windows-1252".into();
        }
        if mode == "cap" {
            job.limits.bytes = Some(10);
        }
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let result = engine::run(
            job.clone(),
            cancel,
            Arc::new(move |progress| {
                if progress.phase == "Finalizing direct terminal output" {
                    if mode == "cancel-final" {
                        stop.store(true, Ordering::SeqCst);
                    }
                    if mode == "race" {
                        fs::create_dir(&output).unwrap();
                        fs::write(Path::new(&output).join("other"), b"preserve").unwrap();
                    }
                }
            }),
        );
        assert!(result.is_err(), "{mode}");
        if mode == "race" {
            assert_eq!(fs::read(Path::new(&job.output).join("other"))?, b"preserve");
            assert_eq!(fs::read_dir(&job.output)?.count(), 1);
            fs::remove_dir_all(&job.output)?;
        }
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
fn run_counted_with_replacement(job: &Job, replacement: &'static [u8]) -> Result<Analysis> {
    let input = job.input.clone();
    let metadata = fs::metadata(&input)?;
    assert_eq!(metadata.len(), replacement.len() as u64);
    let modified = metadata.modified()?;
    engine::run(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |progress| {
            if progress.phase == "Writing counted Balanced CSV" {
                let mut file = fs::File::options()
                    .write(true)
                    .truncate(true)
                    .open(&input)
                    .unwrap();
                file.write_all(replacement).unwrap();
                file.set_times(fs::FileTimes::new().set_modified(modified))
                    .unwrap();
                assert_eq!(file.metadata().unwrap().modified().unwrap(), modified);
            }
        }),
    )
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_rejects_header_and_row_count_edits_with_restored_metadata() -> Result<()> {
    for (replacement, expected) in [
        (&b"ID,text\n1,first\n2,last!\n"[..], "header changed"),
        (&b"id,text\n1,firstabcdefgh\n"[..], "row count changed"),
        (&b"id,text\n1,a\n2,b\n3,cdefg\n"[..], "row count changed"),
    ] {
        let (dir, mut job) = setup(b"id,text\n1,first\n2,last!\n")?;
        job.operations = vec![Operation::Balanced { files: 2 }];
        let error = run_counted_with_replacement(&job, replacement)
            .expect_err("a changed header or row count cannot publish");
        assert!(format!("{error:#}").contains(expected), "{error:#}");
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_reports_the_digest_of_emitted_rows_after_a_same_count_edit() -> Result<()> {
    let (dir, mut job) = setup(b"id,text\n1,first\n2,last!\n")?;
    job.operations = vec![Operation::Balanced { files: 2 }];
    job.limits.bytes = Some(16);
    let direct = run_counted_with_replacement(&job, b"id,text\n1,other\n2,last!\n")?;
    let emitted = csvs(&job.output, Compression::None)?;
    assert_eq!(direct.rows, 2);
    assert_eq!(direct.output_files, 2);
    assert!(emitted.values().any(|bytes| bytes == b"id,text\n1,other\n"));
    assert_eq!(
        manifest(&job.output)?[0]["analysis"]["logical_digest"],
        serde_json::to_value(&direct.logical_digest)?
    );
    let mut reference = job.clone();
    reference.output.push_str("-prepared");
    let prepared = engine::prepare(
        reference.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?
    .execute()?;
    assert_eq!(direct.logical_digest, prepared.logical_digest);
    assert_eq!(emitted, csvs(&reference.output, Compression::None)?);
    assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_strictly_validates_csv_and_utf8_in_both_passes() -> Result<()> {
    for (bad, expected) in [
        (
            &b"id,text\n1,\"open\n2,last!\n"[..],
            "unterminated quoted field",
        ),
        (
            &b"id,text\n1,\xffirst\n2,last!\n"[..],
            "invalid byte sequence in selected input encoding",
        ),
    ] {
        for first_pass in [true, false] {
            let (dir, mut job) = setup(if first_pass {
                bad
            } else {
                b"id,text\n1,first\n2,last!\n"
            })?;
            job.operations = vec![Operation::Balanced { files: 2 }];
            let result = if first_pass {
                run(job.clone())
            } else {
                run_counted_with_replacement(&job, bad)
            };
            let error = result.expect_err("invalid counted input cannot publish");
            assert!(
                format!("{error:#}").to_ascii_lowercase().contains(expected),
                "{error:#}"
            );
            clean(dir.path(), &job)?;
        }
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_cancel_at_last_count_checkpoint_prevents_second_pass() -> Result<()> {
    let mut input = String::from("id,text\n");
    for id in 0..65536 {
        input.push_str(&format!("{id},value\n"));
    }
    let (dir, mut job) = setup(input.as_bytes())?;
    job.operations = vec![Operation::Balanced { files: 8 }];
    let cancel = Arc::new(AtomicBool::new(false));
    let stop = cancel.clone();
    let second = Arc::new(AtomicBool::new(false));
    let seen_second = second.clone();
    let error = engine::run(
        job.clone(),
        cancel,
        Arc::new(move |p| {
            if p.phase == "Counting and validating CSV" && p.rows == 65536 {
                stop.store(true, Ordering::SeqCst);
            }
            if p.phase == "Writing counted Balanced CSV" {
                seen_second.store(true, Ordering::SeqCst);
            }
        }),
    )
    .expect_err("count-pass cancellation");
    assert!(format!("{error:#}").contains("job cancelled"));
    assert!(!second.load(Ordering::SeqCst));
    clean(dir.path(), &job)?;
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_leaves_compressed_and_other_encoding_inputs_on_single_decode_path() -> Result<()>
{
    for mode in ["gzip", "utf-16le"] {
        let text = "id,text\n1,one\n2,two\n3,three\n";
        let (dir, mut job) = setup(text.as_bytes())?;
        if mode == "gzip" {
            let mut encoder =
                flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(text.as_bytes())?;
            fs::write(&job.input, encoder.finish()?)?; // Magic, not the .csv extension.
        } else {
            fs::write(&job.input, chopper::core::csv::encode(text, mode)?)?;
            job.input_csv.encoding = mode.into();
        }
        job.operations = vec![Operation::Balanced { files: 2 }];
        let counted = Arc::new(AtomicBool::new(false));
        let seen = counted.clone();
        let analysis = engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Counting and validating CSV" {
                    seen.store(true, Ordering::SeqCst);
                }
            }),
        )?;
        assert!(!counted.load(Ordering::SeqCst));
        assert_eq!((analysis.rows, analysis.output_files), (3, 2));
        fs::remove_dir_all(&job.output)?;
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-counted-codec-balanced",
    not(target_os = "wasi")
))]
#[test]
fn counted_balanced_output_codecs_preserve_snapshot_bytes_and_terminal_cleanup() -> Result<()> {
    let text = format!(
        "id,text\n{}",
        (0..129)
            .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 7))
            .collect::<String>()
    );
    for compression in [Compression::Gzip, Compression::Zip] {
        for encoding in ["utf-8", "utf-16le"] {
            let (_dir, mut job) = setup(text.as_bytes())?;
            job.operations = vec![Operation::Balanced { files: 4 }];
            job.compression = compression;
            job.output_csv.encoding = encoding.into();
            job.output_csv.bom = true;
            job.limits.rows = Some(33);
            job.limits.bytes = Some(4096);
            let counted = Arc::new(AtomicBool::new(false));
            let seen = counted.clone();
            engine::run(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(move |p| {
                    if p.phase == "Counting and validating CSV" {
                        seen.store(true, Ordering::SeqCst);
                    }
                }),
            )?;
            assert!(counted.load(Ordering::SeqCst));
            fs::remove_dir_all(&job.output)?;
            parity(job)?;
        }
        for mode in ["invalid", "cancel", "caps", "memory"] {
            let (dir, mut job) = setup(text.as_bytes())?;
            job.operations = vec![Operation::Balanced { files: 4 }];
            job.compression = compression;
            if mode == "invalid" {
                fs::write(&job.input, format!("{text}130,\"unterminated"))?;
            }
            if mode == "caps" {
                job.limits.rows = Some(1);
            }
            let pool = Arc::new(MemoryPool::new(if mode == "memory" {
                180_000
            } else {
                64 * 1024 * 1024
            }));
            let cancel = Arc::new(AtomicBool::new(false));
            let stop = cancel.clone();
            let result = engine::run_with_memory_pool(
                job.clone(),
                cancel,
                Arc::new(move |p| {
                    if mode == "cancel" && p.phase == "Finalizing direct terminal output" {
                        stop.store(true, Ordering::SeqCst);
                    }
                }),
                pool.clone(),
            );
            assert!(result.is_err(), "{compression:?}/{mode}");
            drop(result);
            assert_eq!(pool.usage().reserved_bytes, 0, "{compression:?}/{mode}");
            clean(dir.path(), &job)?;
        }
    }
    Ok(())
}

#[cfg(feature = "experimental-terminal-shuffle")]
#[test]
fn terminal_shuffle_direct_preserves_encoded_snapshot_parity() -> Result<()> {
    for (headers, encoding, bom) in [
        (true, "utf-8", false),
        (false, "utf-8", false),
        (true, "utf-16le", true),
    ] {
        let (_dir, mut job) = setup(
            "id,text\n1,\"comma,quote\"\"\"\n2,\"line\nbreak\"\n3,界\n4,\n5,last\n".as_bytes(),
        )?;
        job.input_csv.headers = headers;
        job.output_csv.headers = headers;
        job.output_csv.encoding = encoding.into();
        job.output_csv.bom = bom;
        job.operations = vec![
            Operation::Shuffle {
                strategy: Shuffle::Uniform,
            },
            Operation::Balanced { files: 2 },
        ];
        job.limits.rows = Some(3);
        job.limits.bytes = Some(4096);
        let result = parity(job)?;
        assert_eq!(result.output_files, 2);
    }
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-routing", not(target_os = "wasi")))]
fn routing_operations() -> Vec<Operation> {
    let groups = vec![
        Allocation {
            name: "none".into(),
            percent: "0".into(),
        },
        Allocation {
            name: "treatment".into(),
            percent: "50".into(),
        },
        Allocation {
            name: "control".into(),
            percent: "50".into(),
        },
    ];
    vec![
        Operation::Partition {
            columns: vec![Column::Name("text".into())],
        },
        Operation::Interleaved { files: 3 },
        Operation::AssignProbabilistic {
            groups: groups.clone(),
            strata: vec![],
        },
        Operation::AssignProbabilistic {
            groups: groups.clone(),
            strata: vec![Column::Name("text".into())],
        },
        Operation::Assign {
            groups,
            strata: vec![Column::Name("text".into())],
        },
    ]
}

#[cfg(all(feature = "experimental-terminal-routing", not(target_os = "wasi")))]
#[test]
fn terminal_routing_preserves_membership_empty_groups_bytes_caps_and_snapshot_contract(
) -> Result<()> {
    for operation in routing_operations() {
        for (rows, encoding, bom) in [
            (37, "utf-8", false),
            (37, "utf-16le", true),
            (0, "utf-8", false),
        ] {
            let mut text = String::from("id,text\n");
            for id in 0..rows {
                text.push_str(&format!("{id},\"界,{}\"\"\nline\"\n", id % 3));
            }
            let (dir, mut job) = setup(text.as_bytes())?;
            job.operations = vec![operation.clone()];
            job.output_csv.encoding = encoding.into();
            job.output_csv.bom = bom;
            job.limits.rows = Some(if matches!(operation, Operation::Interleaved { .. }) {
                13
            } else {
                3
            });
            job.limits.bytes = Some(4096);
            if rows == 0 && matches!(operation, Operation::Interleaved { .. }) {
                assert!(run(job.clone()).is_err());
                clean(dir.path(), &job)?;
            } else {
                let analysis = parity(job.clone())?;
                assert_eq!(analysis.rows, rows);
                assert_eq!(
                    analysis.groups,
                    if rows == 0 && matches!(operation, Operation::Partition { .. }) {
                        0
                    } else {
                        3
                    }
                );
                if matches!(
                    operation,
                    Operation::AssignProbabilistic { .. } | Operation::Assign { .. }
                ) {
                    assert!(analysis.stages[0].empty_groups >= 1);
                }
                assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
            }
        }
    }
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-routing", not(target_os = "wasi")))]
#[test]
fn terminal_routing_late_errors_cancel_and_destination_race_cleanup() -> Result<()> {
    for operation in routing_operations() {
        for mode in ["encoding", "cap", "cancel-final", "race"] {
            let (dir, mut job) = setup("id,text\n1,first\n2,界\n3,last\n".as_bytes())?;
            job.operations = vec![operation.clone()];
            if mode == "encoding" {
                job.output_csv.encoding = "windows-1252".into();
            }
            if mode == "cap" {
                job.limits.bytes = Some(10);
            }
            let cancel = Arc::new(AtomicBool::new(false));
            let stop = cancel.clone();
            let output = job.output.clone();
            let result = engine::run(
                job.clone(),
                cancel,
                Arc::new(move |progress| {
                    if progress.phase == "Finalizing direct terminal output" {
                        if mode == "cancel-final" {
                            stop.store(true, Ordering::SeqCst);
                        }
                        if mode == "race" {
                            fs::create_dir(&output).unwrap();
                            fs::write(Path::new(&output).join("other"), b"preserve").unwrap();
                        }
                    }
                }),
            );
            assert!(result.is_err(), "{mode}");
            if mode == "race" {
                assert_eq!(fs::read(Path::new(&job.output).join("other"))?, b"preserve");
                assert_eq!(fs::read_dir(&job.output)?.count(), 1);
                fs::remove_dir_all(&job.output)?;
            }
            clean(dir.path(), &job)?;
        }
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-balanced")]
#[test]
fn counted_balanced_releases_first_header_before_publication_but_retains_analysis_header(
) -> Result<()> {
    use std::sync::atomic::AtomicU64;
    let header = "h".repeat(512 * 1024);
    let (dir, mut job) = setup(format!("{header}\nx\ny\n").as_bytes())?;
    job.operations = vec![Operation::Balanced { files: 2 }];
    let pool = Arc::new(MemoryPool::new(32 * 1024 * 1024));
    let final_usage = Arc::new(AtomicU64::new(0));
    let observed = final_usage.clone();
    let watched = pool.clone();
    let analysis = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |p| {
            if p.phase == "Finalizing direct terminal output" {
                observed.store(watched.usage().reserved_bytes, Ordering::SeqCst);
            }
        }),
        pool.clone(),
    )?;
    let retained = analysis.header.as_ref().unwrap().reserved_bytes();
    let at_final = final_usage.load(Ordering::SeqCst);
    assert!(
        at_final > 0 && at_final < 2 * retained,
        "final={at_final}, oneheader={retained}"
    );
    assert_eq!(analysis.header.as_ref().unwrap()[0], header);
    drop(analysis);
    assert_eq!(pool.usage().reserved_bytes, 0);
    fs::remove_dir_all(&job.output)?;
    clean(dir.path(), &job)?;
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-routing", not(target_os = "wasi")))]
#[test]
fn terminal_partition_headerless_tuple_and_compressed_fallback_parity() -> Result<()> {
    for compression in [Compression::None, Compression::Gzip, Compression::Zip] {
        let (_dir, mut job) = setup(b"2,../a\n1,../a\n3,../a\n2,../a\n0,\n")?;
        job.input_csv.headers = false;
        job.output_csv.headers = false;
        job.compression = compression;
        job.operations = vec![Operation::Partition {
            columns: vec![Column::Index(1), Column::Index(0), Column::Index(1)],
        }];
        job.limits.rows = Some(1);
        job.limits.bytes = Some(64);
        let result = parity(job)?;
        assert_eq!((result.rows, result.groups, result.output_files), (5, 4, 5));
    }
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-routing", not(target_os = "wasi")))]
#[test]
fn unstratified_exact_assignment_keeps_snapshot_fallback() -> Result<()> {
    use std::sync::atomic::AtomicUsize;
    let (dir, mut job) = setup(b"id,text\n1,one\n2,two\n3,three\n")?;
    let mut operation = routing_operations()
        .into_iter()
        .find(|op| matches!(op, Operation::Assign { .. }))
        .unwrap();
    if let Operation::Assign { strata, .. } = &mut operation {
        strata.clear();
    }
    job.operations = vec![operation];
    let phases = Arc::new(AtomicUsize::new(0));
    let observed = phases.clone();
    let analysis = engine::run(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |p| {
            if p.phase == "Finalizing output snapshot" {
                observed.fetch_or(1, Ordering::Relaxed);
            }
            if p.phase == "Finalizing direct terminal output" {
                observed.fetch_or(2, Ordering::Relaxed);
            }
        }),
    )?;
    assert_eq!(phases.load(Ordering::Relaxed), 1);
    assert_eq!((analysis.rows, analysis.groups), (3, 3));
    fs::remove_dir_all(&job.output)?;
    clean(dir.path(), &job)?;
    parity(job)?;
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
fn fanout_operation() -> Operation {
    Operation::AssignProbabilistic {
        groups: vec![
            Allocation {
                name: "none/../empty".into(),
                percent: "0".into(),
            },
            Allocation {
                name: "all".into(),
                percent: "100".into(),
            },
        ],
        strata: vec![Column::Index(1)],
    }
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writers_canonical_multichunk_headerless_and_utf16_parity() -> Result<()> {
    for header in [false, true] {
        for encoding in ["utf-8", "utf-16le"] {
            let text = format!(
                "{}{}",
                if header { "id,text\n" } else { "" },
                (0..37)
                    .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 3))
                    .collect::<String>()
            );
            let (_dir, mut job) = setup(text.as_bytes())?;
            job.input_csv.headers = header;
            job.output_csv.headers = header;
            job.output_csv.encoding = encoding.into();
            job.output_csv.bom = true;
            job.operations = vec![fanout_operation()];
            job.limits.rows = Some(3);
            job.limits.bytes = Some(256);
            let analysis = parity(job)?;
            assert_eq!(
                (analysis.rows, analysis.groups, analysis.output_files),
                (37, 2, 14)
            );
            assert_eq!(analysis.stages[0].empty_groups, 1);
        }
    }
    for files in [1, 16, 17] {
        let (_dir, mut job) =
            setup(b"a\n0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n13\n14\n15\n16\n")?;
        job.operations = vec![Operation::Interleaved { files }];
        parity(job)?;
    }
    Ok(())
}

#[cfg(all(feature = "experimental-memory-final-writers", not(target_os = "wasi")))]
#[test]
fn memory_final_writers_preserve_high_fanout_bytes_and_budget_selection() -> Result<()> {
    for (memory, files, selected) in [
        (32, 64, true),
        (32, 128, true),
        (
            32,
            if cfg!(feature = "experimental-small-final-buffers") {
                257
            } else {
                129
            },
            false,
        ),
        (64, 256, true),
    ] {
        let text = format!(
            "id,text\n{}",
            (0..513)
                .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 7))
                .collect::<String>()
        );
        let (dir, mut job) = setup(text.as_bytes())?;
        job.resources.memory_mb = memory.into();
        job.operations = vec![Operation::Interleaved { files }];
        job.limits.rows = Some(16);
        job.limits.bytes = Some(2048);
        job.output_csv.encoding = "utf-16le".into();
        job.output_csv.bom = true;
        let direct = Arc::new(AtomicBool::new(false));
        let seen = direct.clone();
        let result = engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Reading and writing CSV" {
                    seen.store(true, Ordering::SeqCst);
                }
            }),
        )?;
        assert_eq!(
            direct.load(Ordering::SeqCst),
            selected,
            "{memory} MiB/{files} writers"
        );
        assert_eq!(result.groups, files);
        fs::remove_dir_all(&job.output)?;
        parity(job.clone())?;
        fs::remove_dir_all(&job.output)?;
        clean(dir.path(), &job)?;
    }
    let text = format!(
        "id,text\n{}",
        (0..513)
            .map(|i| format!("{i},{}\n", i % 7))
            .collect::<String>()
    );
    let (_dir, mut job) = setup(text.as_bytes())?;
    job.operations = vec![Operation::AssignProbabilistic {
        groups: (0..64)
            .map(|i| Allocation {
                name: format!("g{i:02}"),
                percent: "1.5625".into(),
            })
            .collect(),
        strata: vec![Column::Name("text".into())],
    }];
    parity(job)?;
    Ok(())
}

#[cfg(all(
    feature = "experimental-memory-final-writers",
    feature = "experimental-final-writer-chains",
    not(target_os = "wasi")
))]
#[test]
fn memory_final_writer_chains_and_high_fanout_denial_cleanup() -> Result<()> {
    let text = format!(
        "id,text\n{}",
        (0..1025).map(|i| format!("{i},x\n")).collect::<String>()
    );
    let (dir, mut job) = setup(text.as_bytes())?;
    job.resources.memory_mb = 64.into();
    job.operations = vec![
        Operation::Interleaved { files: 16 },
        Operation::Interleaved { files: 16 },
    ];
    parity(job.clone())?;
    fs::remove_dir_all(&job.output)?;
    clean(dir.path(), &job)?;
    for mode in ["shared", "files", "header"] {
        let (dir, mut job) = setup(text.as_bytes())?;
        job.operations = vec![Operation::Interleaved { files: 128 }];
        if mode == "files" {
            job.resources.max_files = 128;
            job.limits.rows = Some(4);
            job.operations = vec![Operation::AssignProbabilistic {
                groups: (0..128)
                    .map(|i| Allocation {
                        name: format!("g{i:03}"),
                        percent: if i == 127 { "100" } else { "0" }.into(),
                    })
                    .collect(),
                strata: vec![],
            }];
        }
        if mode == "header" {
            fs::write(
                &job.input,
                format!("id,{}\n{}", "h".repeat(192 * 1024), "0,x\n".repeat(128)),
            )?;
        }
        let pool = Arc::new(MemoryPool::new(if mode == "shared" {
            1024 * 1024
        } else {
            64 * 1024 * 1024
        }));
        let result = engine::run_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        );
        assert!(result.is_err(), "{mode}");
        if mode != "files" {
            let error = format!("{:#}", result.as_ref().unwrap_err());
            assert!(error.contains("memory"), "{mode}: {error}");
        }
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, 0, "{mode}");
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-release-final-header-scratch",
    feature = "experimental-memory-final-writers",
    not(target_os = "wasi")
))]
#[test]
fn shared_final_writer_headers_release_unused_encoder_capacity() -> Result<()> {
    for encoding in ["utf-8", "utf-16le"] {
        let input = format!(
            "id,{}\n{}",
            "h".repeat(96 * 1024),
            (0..129)
                .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 7))
                .collect::<String>()
        );
        let (_dir, mut job) = setup(input.as_bytes())?;
        job.resources.memory_mb = 64.into();
        job.operations = vec![Operation::Interleaved { files: 64 }];
        job.output_csv.encoding = encoding.into();
        job.output_csv.bom = true;
        job.limits.rows = Some(3);
        job.limits.bytes = Some(512 * 1024);
        let result = parity(job)?;
        assert_eq!((result.rows, result.groups), (129, 64));
        let diagnostics = serde_json::to_value(&result.diagnostics)?;
        assert!(
            diagnostics["peak_workspace_reserved_bytes"]
                .as_u64()
                .unwrap()
                < 24 * 1024 * 1024
        );
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-bounded-final-partition",
    not(target_os = "wasi")
))]
#[test]
fn bounded_final_partition_preserves_tuple_order_caps_headerless_and_empty_outputs() -> Result<()> {
    for headers in [false, true] {
        for encoding in ["utf-8", "utf-16le"] {
            let mut input = Vec::new();
            if headers {
                input.extend_from_slice(b"id,dup,dup\n");
            }
            let keys = ["z", "a\0", "a", "界", "", "a,\n\"", "aaa", "b"];
            for i in 0..257 {
                input.extend_from_slice(&csv::serialize(
                    &[
                        i.to_string(),
                        keys[(257 - i) % 8].into(),
                        format!("v{}", i % 3),
                    ],
                    &Default::default(),
                )?);
            }
            let (dir, mut job) = setup(&input)?;
            job.resources.memory_mb = 64.into();
            job.resources.max_files = 128;
            job.operations = vec![Operation::Partition {
                columns: vec![Column::Index(2), Column::Index(1), Column::Index(2)],
            }];
            job.input_csv.headers = headers;
            job.output_csv.headers = headers;
            job.output_csv.encoding = encoding.into();
            job.output_csv.bom = true;
            job.limits.rows = Some(3);
            job.limits.bytes = Some(512);
            let selected = Arc::new(AtomicBool::new(false));
            let observed = selected.clone();
            let result = engine::run(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(move |p| {
                    if p.phase == "Reading and writing CSV" {
                        observed.store(true, Ordering::SeqCst);
                    }
                }),
            )?;
            assert!(selected.load(Ordering::SeqCst));
            assert_eq!((result.rows, result.groups), (257, 24));
            fs::remove_dir_all(&job.output)?;
            parity(job.clone())?;
            fs::remove_dir_all(&job.output)?;
            clean(dir.path(), &job)?;
        }
    }
    let (_dir, mut job) = setup(b"id,key\n")?;
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Index(1)],
    }];
    job.resources.max_files = 8;
    let result = parity(job)?;
    assert_eq!((result.rows, result.groups, result.output_files), (0, 0, 0));
    Ok(())
}

#[cfg(all(
    feature = "experimental-bounded-final-partition",
    not(target_os = "wasi")
))]
#[test]
fn bounded_final_partition_limits_denial_races_and_declines_never_publish_partial_output(
) -> Result<()> {
    for mode in [
        "keys", "chunks", "local", "shared", "invalid", "cancel", "race",
    ] {
        let text = format!(
            "id,key\n{}",
            (0..131072)
                .map(|i| format!("{i},{}\n", i % 8))
                .collect::<String>()
        );
        let (dir, mut job) = setup(text.as_bytes())?;
        job.operations = vec![Operation::Partition {
            columns: vec![Column::Index(1)],
        }];
        job.resources.max_files = if mode == "keys" { 2 } else { 8 };
        if mode == "chunks" {
            job.limits.rows = Some(4);
        }
        if mode == "invalid" {
            fs::write(&job.input, format!("{text}1,\"unterminated"))?;
        }
        if mode == "local" {
            job.resources.max_record_bytes = 2 * 1024 * 1024;
            job.resources.max_files = 16;
            let mut file = fs::File::create(&job.input)?;
            file.write_all(b"id,key\n")?;
            for i in 0..16 {
                writeln!(file, "{i},{i}{}", "x".repeat(384 * 1024))?;
            }
        }
        let pool = Arc::new(MemoryPool::new(if mode == "shared" {
            180_000
        } else {
            64 * 1024 * 1024
        }));
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let result = engine::run_with_memory_pool(
            job.clone(),
            cancel,
            Arc::new(move |p| {
                if p.phase == "Serializing output" && p.rows == 65536 {
                    if mode == "cancel" {
                        stop.store(true, Ordering::SeqCst);
                    }
                    if mode == "race" {
                        fs::create_dir(&output).unwrap();
                    }
                }
            }),
            pool.clone(),
        );
        assert!(result.is_err(), "{mode}");
        if mode == "local" || mode == "shared" {
            assert!(format!("{:#}", result.as_ref().unwrap_err()).contains("memory"));
        }
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, 0, "{mode}");
        if mode == "race" {
            assert_eq!(fs::read_dir(&job.output)?.count(), 0);
            fs::remove_dir(&job.output)?;
        }
        clean(dir.path(), &job)?;
    }
    for mode in ["ceiling", "sort", "codec", "composed"] {
        let (dir, mut job) = setup(b"id,key\n0,b\n1,a\n2,b\n3,a\n")?;
        job.operations = vec![Operation::Partition {
            columns: vec![Column::Index(1)],
        }];
        job.resources.max_files = 64;
        if mode == "ceiling" {
            job.resources.max_files = 10000;
        }
        if mode == "sort" {
            job.resources.grouping = Grouping::Sort;
        }
        if mode == "codec" {
            job.compression = Compression::Gzip;
        }
        if mode == "composed" {
            job.operations.push(Operation::Shuffle {
                strategy: Shuffle::Uniform,
            });
        }
        let selected = Arc::new(AtomicBool::new(false));
        let observed = selected.clone();
        engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Reading and writing CSV" {
                    observed.store(true, Ordering::SeqCst);
                }
            }),
        )?;
        assert!(!selected.load(Ordering::SeqCst), "{mode}");
        fs::remove_dir_all(&job.output)?;
        parity(job.clone())?;
        fs::remove_dir_all(&job.output)?;
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writers_error_and_shared_denial_release_every_private_owner() -> Result<()> {
    for mode in [
        "invalid", "files", "rowcap", "cancel", "race", "source", "denied",
    ] {
        let (dir, mut job) = setup(b"id,text\n0,a\n1,b\n2,c\n3,d\n")?;
        job.operations = vec![fanout_operation()];
        if mode == "source" {
            fs::write(&job.input, format!("id,text\n{}", "1,a\n".repeat(70000)))?;
        }
        if mode == "invalid" {
            fs::write(&job.input, b"id,text\n0,a\n1,b\n2,\xff\n")?;
        }
        if mode == "files" {
            job.resources.max_files = 2;
            job.limits.rows = Some(1);
        }
        if mode == "rowcap" {
            job.operations = vec![Operation::Interleaved { files: 2 }];
            job.limits.rows = Some(1);
        }
        let pool = Arc::new(MemoryPool::new(if mode == "denied" {
            180_000
        } else {
            64 * 1024 * 1024
        }));
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let input = job.input.clone();
        let result = engine::run_with_memory_pool(
            job.clone(),
            cancel,
            Arc::new(move |p| {
                if p.phase == "Finalizing direct terminal output" {
                    if mode == "cancel" {
                        stop.store(true, Ordering::SeqCst);
                    }
                    if mode == "race" {
                        fs::create_dir(&output).unwrap();
                        fs::write(Path::new(&output).join("other"), b"keep").unwrap();
                    }
                }
                if mode == "source" && p.phase == "Serializing output" {
                    fs::write(&input, b"changed\n").unwrap();
                }
            }),
            pool.clone(),
        );
        assert!(result.is_err(), "{mode}");
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, 0, "{mode}");
        if mode == "race" {
            assert_eq!(fs::read(Path::new(&job.output).join("other"))?, b"keep");
            fs::remove_dir_all(&job.output)?;
        }
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writers_wide_rows_and_managed_temp_completion_boundary() -> Result<()> {
    let mut text = String::from("id,text\n");
    for id in 0..16 {
        text.push_str(&format!("{id},{}\n", "x".repeat(768 * 1024)));
    }
    let (dir, mut job) = setup(text.as_bytes())?;
    job.operations = vec![Operation::Interleaved { files: 16 }];
    job.output_csv.encoding = "utf-16le".into();
    job.output_csv.bom = true;
    job.resources.temp_bytes = Some(1024 * 1024);
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let result = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    );
    if cfg!(feature = "experimental-shared-final-serializer") {
        let analysis = result?;
        assert_eq!((analysis.rows, analysis.output_files), (16, 16));
        assert!(pool.usage().peak_reserved_bytes < 12 * 1024 * 1024);
        for record in manifest(&job.output)?.iter().skip(1) {
            let id = record["lineage"][0]["part"].as_u64().unwrap() - 1;
            let bytes = fs::read(Path::new(&job.output).join(record["path"].as_str().unwrap()))?;
            let mut expected = csv::bom(&job.output_csv)?;
            expected.extend(csv::encode(
                &format!("id,text\n{id},{}\n", "x".repeat(768 * 1024)),
                "utf-16le",
            )?);
            assert!(bytes == expected, "UTF16bytes forpart{} differ", id + 1);
        }
        drop(analysis);
        fs::remove_dir_all(&job.output)?;
    } else {
        let error = result.expect_err("pergroup encoded scratch must exceed32MiB");
        assert!(
            error
                .to_string()
                .contains("concurrent algorithm workspaces"),
            "{error:#}"
        );
    }
    assert_eq!(pool.usage().reserved_bytes, 0);
    clean(dir.path(), &job)?;
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writers_complete_without_managed_row_spool_capacity() -> Result<()> {
    let text = format!("id,text\n{}", "1,payload\n".repeat(131072));
    let (dir, mut job) = setup(text.as_bytes())?;
    job.operations = vec![Operation::Interleaved { files: 8 }];
    job.resources.temp_bytes = Some(128 * 1024);
    let result = run(job.clone())?;
    assert_eq!(result.rows, 131072);
    assert!(
        result.diagnostics["temporary_bytes_written"]
            .as_u64()
            .unwrap()
            < 16 * 1024
    );
    fs::remove_dir_all(&job.output)?;
    let error = engine::prepare(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )
    .err()
    .expect("snapshot route requires moremanagedspoolcapacity");
    assert!(error.to_string().contains("temporary"), "{error:#}");
    clean(dir.path(), &job)?;
    Ok(())
}

#[cfg(all(feature = "experimental-final-writer-chains", not(target_os = "wasi")))]
fn chain_operations() -> Vec<Vec<Operation>> {
    let prob = |strata, zero| Operation::AssignProbabilistic {
        groups: if zero {
            vec![
                Allocation {
                    name: "zero".into(),
                    percent: "0".into(),
                },
                Allocation {
                    name: "all".into(),
                    percent: "100".into(),
                },
            ]
        } else {
            vec![
                Allocation {
                    name: "a".into(),
                    percent: "25".into(),
                },
                Allocation {
                    name: "b".into(),
                    percent: "75".into(),
                },
            ]
        },
        strata: if strata {
            vec![Column::Name("text".into())]
        } else {
            vec![]
        },
    };
    vec![
        vec![
            Operation::Interleaved { files: 2 },
            Operation::Interleaved { files: 3 },
        ],
        vec![prob(false, false), prob(true, false)],
        vec![prob(true, true), prob(false, true)],
        vec![
            Operation::Interleaved { files: 2 },
            prob(true, false),
            Operation::Interleaved { files: 2 },
        ],
        vec![
            prob(false, false),
            Operation::Interleaved { files: 2 },
            prob(true, false),
        ],
        vec![
            Operation::Interleaved { files: 2 },
            prob(true, false),
            Operation::Interleaved { files: 2 },
            prob(false, false),
        ],
    ]
}

#[cfg(all(feature = "experimental-final-writer-chains", not(target_os = "wasi")))]
#[test]
fn final_writer_chains_preserve_parent_domains_counters_caps_and_every_stage() -> Result<()> {
    for operations in chain_operations() {
        for encoding in ["utf-8", "utf-16le"] {
            let text = format!(
                "id,text\n{}",
                (0..257)
                    .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 5))
                    .collect::<String>()
            );
            let (dir, mut job) = setup(text.as_bytes())?;
            job.operations = operations.clone();
            job.output_csv.encoding = encoding.into();
            job.output_csv.bom = true;
            job.limits.rows = Some(
                if matches!(operations.last(), Some(Operation::Interleaved { .. })) {
                    257
                } else {
                    3
                },
            );
            job.limits.bytes = Some(64 * 1024);
            let result = parity(job)?;
            assert_eq!(result.rows, 257);
            assert_eq!(result.stages.len(), operations.len());
            assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
        }
    }
    Ok(())
}

#[cfg(all(feature = "experimental-final-writer-chains", not(target_os = "wasi")))]
#[test]
fn final_writer_chains_errors_declines_and_empty_parent_rules() -> Result<()> {
    for mode in [
        "invalid",
        "files",
        "empty-parent",
        "cancel",
        "race",
        "denied",
    ] {
        let text = format!("id,text\n{}", "1,x\n".repeat(257));
        let (dir, mut job) = setup(text.as_bytes())?;
        job.operations = chain_operations().remove(0);
        if mode == "invalid" {
            fs::write(&job.input, format!("{text}2,\"unterminated"))?;
        }
        if mode == "files" {
            job.resources.max_files = 3;
        }
        if mode == "empty-parent" {
            job.operations = vec![fanout_operation(), Operation::Interleaved { files: 2 }];
        }
        let pool = Arc::new(MemoryPool::new(if mode == "denied" {
            180_000
        } else {
            64 * 1024 * 1024
        }));
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let result = engine::run_with_memory_pool(
            job.clone(),
            cancel,
            Arc::new(move |p| {
                if p.phase == "Finalizing direct terminal output" {
                    if mode == "cancel" {
                        stop.store(true, Ordering::SeqCst);
                    }
                    if mode == "race" {
                        fs::create_dir(&output).unwrap();
                        fs::write(Path::new(&output).join("other"), b"keep").unwrap();
                    }
                }
            }),
            pool.clone(),
        );
        assert!(result.is_err(), "{mode}");
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, 0, "{mode}");
        if mode == "race" {
            assert_eq!(fs::read(Path::new(&job.output).join("other"))?, b"keep");
            fs::remove_dir_all(&job.output)?;
        }
        clean(dir.path(), &job)?;
    }
    for mode in ["fanout", "depth", "sort", "codec"] {
        let (dir, mut job) = setup(format!("id,text\n{}", "1,x\n".repeat(1025)).as_bytes())?;
        job.operations = if mode == "fanout" {
            vec![
                Operation::Interleaved { files: 16 },
                Operation::Interleaved {
                    files: if cfg!(feature = "experimental-single-catalog-capacity") {
                        64
                    } else {
                        32
                    },
                },
            ]
        } else if mode == "depth" {
            vec![Operation::Interleaved { files: 1 }; 5]
        } else {
            chain_operations().remove(0)
        };
        if mode == "sort" {
            job.resources.grouping = Grouping::Sort;
        }
        if mode == "codec" {
            job.compression = Compression::Gzip;
        }
        let selected = Arc::new(AtomicBool::new(false));
        let observed = selected.clone();
        engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Finalizing direct terminal output" {
                    observed.store(true, Ordering::SeqCst);
                }
            }),
        )?;
        assert!(!selected.load(Ordering::SeqCst), "{mode}");
        fs::remove_dir_all(&job.output)?;
        parity(job)?;
        assert_eq!(fs::read_dir(dir.path().join("temp"))?.count(), 0);
    }
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writers_keep_original_destination_witness_for_empty_directory_races() -> Result<()> {
    let single = vec![Operation::Interleaved { files: 1 }];
    for operations in [single.clone(), vec![single[0].clone(), single[0].clone()]] {
        if operations.len() == 2 && !cfg!(feature = "experimental-final-writer-chains") {
            continue;
        }
        let text = format!("id,text\n{}", "1,x\n".repeat(131072));
        let (dir, mut job) = setup(text.as_bytes())?;
        job.operations = operations;
        let output = job.output.clone();
        let result = engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Serializing output" && p.rows == 65536 {
                    fs::create_dir(&output).unwrap();
                }
            }),
        );
        assert!(
            result.is_err(),
            "a directory created after first writer admission must survive"
        );
        assert!(Path::new(&job.output).is_dir());
        assert_eq!(fs::read_dir(&job.output)?.count(), 0);
        fs::remove_dir(&job.output)?;
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-shuffle", not(target_os = "wasi")))]
#[test]
fn native_terminal_shuffle_variants_and_partition_caps_snapshot_parity() -> Result<()> {
    for strategy in [Shuffle::Uniform, Shuffle::Auto, Shuffle::FisherYates] {
        for partition in [false, true] {
            if partition && strategy == Shuffle::FisherYates {
                continue;
            }
            for encoding in ["utf-8", "utf-16le"] {
                let text = format!(
                    "id,text\n{}",
                    (0..257)
                        .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 5))
                        .collect::<String>()
                );
                let (_dir, mut job) = setup(text.as_bytes())?;
                job.operations = vec![Operation::Shuffle { strategy }];
                if partition {
                    job.operations.push(Operation::Partition {
                        columns: vec![Column::Index(1), Column::Index(1)],
                    });
                }
                job.output_csv.encoding = encoding.into();
                job.output_csv.bom = true;
                job.limits.rows = Some(17);
                job.limits.bytes = Some(4096);
                let result = parity(job)?;
                assert_eq!(result.rows, 257);
                assert_eq!(result.groups, if partition { 5 } else { 1 });
            }
        }
    }
    Ok(())
}

#[cfg(all(feature = "experimental-terminal-shuffle", not(target_os = "wasi")))]
#[test]
fn native_terminal_shuffle_late_error_cancel_race_and_observed_fallback() -> Result<()> {
    for mode in ["invalid", "cap", "cancel", "race", "observed"] {
        let (dir, mut job) = setup(b"id,text\n0,x\n1,y\n2,x\n3,z\n")?;
        job.operations = vec![
            Operation::Shuffle {
                strategy: Shuffle::Uniform,
            },
            Operation::Partition {
                columns: vec![Column::Index(1)],
            },
        ];
        if mode == "invalid" {
            fs::write(&job.input, b"id,text\n0,x\n1,\xff\n")?;
        }
        if mode == "cap" {
            job.limits.bytes = Some(9);
        }
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let selected = Arc::new(AtomicBool::new(false));
        let seen = selected.clone();
        let notify = Arc::new(move |p: chopper::storage::Progress| {
            if p.phase == "Finalizing direct terminal output" {
                seen.store(true, Ordering::SeqCst);
                if mode == "cancel" {
                    stop.store(true, Ordering::SeqCst);
                }
                if mode == "race" {
                    fs::create_dir(&output).unwrap();
                    fs::write(Path::new(&output).join("other"), b"keep").unwrap();
                }
            }
        });
        let result = if mode == "observed" {
            engine::run_with_observations(job.clone(), cancel, notify, Arc::new(|_| true))
        } else {
            engine::run(job.clone(), cancel, notify)
        };
        if mode == "observed" {
            result?;
            assert!(!selected.load(Ordering::SeqCst));
            fs::remove_dir_all(&job.output)?;
        } else {
            assert!(result.is_err(), "{mode}");
            if mode == "race" {
                assert_eq!(fs::read(Path::new(&job.output).join("other"))?, b"keep");
                fs::remove_dir_all(&job.output)?;
            }
        }
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(feature = "experimental-final-writers", not(target_os = "wasi")))]
#[test]
fn final_writer_intake_codecs_encodings_and_late_corruption_parity() -> Result<()> {
    for mode in ["singleton", "chain", "partition", "exact"] {
        let chain = mode == "chain";
        if chain && !cfg!(feature = "experimental-final-writer-chains") {
            continue;
        }
        if mode == "partition" && !cfg!(feature = "experimental-bounded-final-partition") {
            continue;
        }
        if mode == "exact" && !cfg!(feature = "experimental-retained-exact-writers") {
            continue;
        }
        for codec in ["utf-16le", "gzip", "zip"] {
            let text = format!(
                "id,text\n{}",
                (0..37)
                    .map(|i| format!("{i},\"界,{}\"\"\nline\"\n", i % 3))
                    .collect::<String>()
            );
            let (dir, mut job) = setup(text.as_bytes())?;
            job.resources.max_files = 64;
            job.operations = if mode == "exact" {
                vec![Operation::Assign {
                    groups: vec![
                        Allocation {
                            name: "zero".into(),
                            percent: "0".into(),
                        },
                        Allocation {
                            name: "left".into(),
                            percent: "50".into(),
                        },
                        Allocation {
                            name: "right".into(),
                            percent: "50".into(),
                        },
                    ],
                    strata: vec![Column::Index(1)],
                }]
            } else if mode == "partition" {
                vec![Operation::Partition {
                    columns: vec![Column::Index(1)],
                }]
            } else if chain {
                vec![Operation::Interleaved { files: 2 }, fanout_operation()]
            } else {
                vec![fanout_operation()]
            };
            let bytes = match codec {
                "utf-16le" => {
                    job.input_csv.encoding = codec.into();
                    csv::encode(&text, codec)?
                }
                "gzip" => {
                    let mut e =
                        flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
                    e.write_all(text.as_bytes())?;
                    e.finish()?
                }
                "zip" => {
                    let mut e = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
                    e.start_file(
                        "input.csv",
                        zip::write::SimpleFileOptions::default()
                            .compression_method(zip::CompressionMethod::Deflated),
                    )?;
                    e.write_all(text.as_bytes())?;
                    e.finish()?.into_inner()
                }
                _ => unreachable!(),
            };
            fs::write(&job.input, &bytes)?;
            parity(job.clone())?;
            fs::write(&job.input, &bytes[..bytes.len() - 3])?;
            job.output = dir.path().join("corrupt").to_string_lossy().into();
            assert!(run(job.clone()).is_err(), "{codec},mode={mode}");
            clean(dir.path(), &job)?;
        }
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-bounded-final-partition",
    feature = "experimental-small-final-catalogs",
    not(target_os = "wasi")
))]
#[test]
fn small_fanout_catalog_preserves_long_lineage_and_multiple_chunks() -> Result<()> {
    let text = format!(
        "id,key\n{}",
        (0..25)
            .map(|i| format!("{i},{}{}\n", "界".repeat(512), i % 2))
            .collect::<String>()
    );
    let (_dir, mut job) = setup(text.as_bytes())?;
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Index(1)],
    }];
    job.resources.max_files = 64;
    job.limits.rows = Some(3);
    job.limits.bytes = Some(5000);
    let result = parity(job)?;
    assert_eq!(result.groups, 2);
    assert_eq!(result.output_files, 9);
    Ok(())
}

#[cfg(all(
    feature = "experimental-retained-exact-writers",
    not(target_os = "wasi")
))]
#[test]
fn retained_exact_writers_match_snapshot_for_strata_rounding_text_and_named_zeros() -> Result<()> {
    let text = format!(
        "id,key,text\n{}",
        (0..129)
            .map(|i| { format!("{},\"k\0{}\",\"界,{}\"\"\nline\"\n", 129 - i, i % 7, i % 3) })
            .collect::<String>()
    );
    for headers in [true, false] {
        for columns in [
            vec![Column::Index(1)],
            vec![Column::Index(1), Column::Index(2), Column::Index(1)],
            vec![Column::Index(1), Column::Index(0)],
        ] {
            let (_dir, mut job) = setup(text.as_bytes())?;
            if !headers {
                fs::write(&job.input, text.split_once('\n').unwrap().1)?;
            }
            job.input_csv.headers = headers;
            job.output_csv.headers = headers;
            job.output_csv.bom = true;
            job.operations = vec![Operation::Assign {
                groups: [
                    ("zero", "0"),
                    ("A", "33.333333"),
                    ("a", "33.333333"),
                    ("界", "33.333334"),
                ]
                .into_iter()
                .map(|(name, percent)| Allocation {
                    name: name.into(),
                    percent: percent.into(),
                })
                .collect(),
                strata: columns,
            }];
            job.limits.rows = Some(7);
            job.limits.bytes = Some(256);
            let selected = Arc::new(AtomicBool::new(false));
            let seen = selected.clone();
            let analysis = engine::run(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(move |p| {
                    if p.phase == "Preparing retained exact writers" {
                        seen.store(true, Ordering::SeqCst);
                    }
                }),
            )?;
            assert!(selected.load(Ordering::SeqCst));
            assert_eq!(analysis.groups, 4);
            let entries = manifest(&job.output)?;
            assert_eq!(entries[1]["rows"], 0);
            fs::remove_dir_all(&job.output)?;
            parity(job)?;
        }
    }
    for encoding in ["utf-8", "utf-16le"] {
        let (_dir, mut job) = setup(b"id,key,text\n")?;
        job.operations = vec![Operation::Assign {
            groups: vec![
                Allocation {
                    name: "left".into(),
                    percent: "50".into(),
                },
                Allocation {
                    name: "right".into(),
                    percent: "50".into(),
                },
            ],
            strata: vec![Column::Name("key".into())],
        }];
        job.output_csv.encoding = encoding.into();
        let result = parity(job)?;
        assert_eq!((result.rows, result.groups, result.output_files), (0, 2, 2));
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-retained-exact-writers",
    not(target_os = "wasi")
))]
#[test]
fn retained_exact_writer_preparation_denial_falls_back_without_csv_replay() -> Result<()> {
    use std::sync::atomic::AtomicUsize;
    let text = format!(
        "id,key\n{}",
        (0..2048)
            .map(|i| format!("{},k{i}\n", 2048 - i))
            .collect::<String>()
    );
    let (_dir, mut job) = setup(text.as_bytes())?;
    job.operations = vec![Operation::Assign {
        groups: vec![
            Allocation {
                name: "left".into(),
                percent: "50".into(),
            },
            Allocation {
                name: "right".into(),
                percent: "50".into(),
            },
        ],
        strata: vec![Column::Name("key".into())],
    }];
    let fallback = Arc::new(AtomicUsize::new(0));
    let source = Arc::new(AtomicUsize::new(0));
    let (seen_fallback, seen_source) = (fallback.clone(), source.clone());
    let pool = Arc::new(MemoryPool::new(2 * 1024 * 1024));
    let result = engine::run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |p| {
            if p.phase == "Using original exact allocation after preparation denial" {
                seen_fallback.fetch_add(1, Ordering::SeqCst);
            }
            if p.phase == "Reading and validating CSV" && p.rows == 0 {
                seen_source.fetch_add(1, Ordering::SeqCst);
            }
        }),
        pool.clone(),
    )?;
    assert_eq!(fallback.load(Ordering::SeqCst), 1);
    assert_eq!(source.load(Ordering::SeqCst), 1);
    assert_eq!(result.stages.len(), 1);
    assert_eq!((result.rows, result.groups), (2048, 2));
    drop(result);
    assert_eq!(pool.usage().reserved_bytes, 0);
    let original = csvs(&job.output, Compression::None)?;
    fs::remove_dir_all(&job.output)?;
    let expected = engine::prepare(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?
    .execute()?;
    assert_eq!(original, csvs(&job.output, Compression::None)?);
    drop(expected);
    Ok(())
}

#[cfg(all(
    feature = "experimental-retained-exact-writers",
    not(target_os = "wasi")
))]
#[test]
fn retained_exact_writers_keep_initial_witness_and_never_retry_emission() -> Result<()> {
    use std::sync::atomic::AtomicUsize;
    for mode in ["race", "cancel"] {
        let text = format!(
            "id,key\n{}",
            (0..65537)
                .map(|i| format!("{i},k{}\n", i % 8))
                .collect::<String>()
        );
        let (dir, mut job) = setup(text.as_bytes())?;
        job.operations = vec![Operation::Assign {
            groups: vec![
                Allocation {
                    name: "left".into(),
                    percent: "50".into(),
                },
                Allocation {
                    name: "right".into(),
                    percent: "50".into(),
                },
            ],
            strata: vec![Column::Name("key".into())],
        }];
        let cancel = Arc::new(AtomicBool::new(false));
        let stop = cancel.clone();
        let output = job.output.clone();
        let fallback = Arc::new(AtomicUsize::new(0));
        let seen = fallback.clone();
        let pool = Arc::new(MemoryPool::new(32 * 1024 * 1024));
        let result = engine::run_with_memory_pool(
            job.clone(),
            cancel,
            Arc::new(move |p| {
                if mode == "race" && p.phase == "Preparing retained exact writers" {
                    fs::create_dir(&output).unwrap();
                }
                if mode == "cancel" && p.phase == "Serializing output" && p.rows == 65536 {
                    stop.store(true, Ordering::SeqCst);
                }
                if p.phase == "Using original exact allocation after preparation denial" {
                    seen.fetch_add(1, Ordering::SeqCst);
                }
            }),
            pool.clone(),
        );
        assert!(result.is_err(), "{mode}");
        drop(result);
        assert_eq!(fallback.load(Ordering::SeqCst), 0);
        assert_eq!(pool.usage().reserved_bytes, 0);
        if mode == "race" {
            assert_eq!(fs::read_dir(&job.output)?.count(), 0);
            fs::remove_dir(&job.output)?;
        }
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(all(
    feature = "experimental-single-catalog-capacity",
    not(target_os = "wasi")
))]
#[test]
fn uncapped_single_catalog_capacity_preserves_512_writers_and_513_fallback() -> Result<()> {
    for (files, expected_direct) in [(512, true), (513, false)] {
        let text = format!(
            "id,text\n{}",
            (0..1025)
                .map(|i| format!("{i},界{}\n", i % 7))
                .collect::<String>()
        );
        let (dir, mut job) = setup(text.as_bytes())?;
        job.resources.memory_mb = 32.into();
        job.operations = vec![Operation::Interleaved { files }];
        let direct = Arc::new(AtomicBool::new(false));
        let seen = direct.clone();
        let result = engine::run(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |p| {
                if p.phase == "Reading and writing CSV" {
                    seen.store(true, Ordering::SeqCst);
                }
            }),
        )?;
        assert_eq!(direct.load(Ordering::SeqCst), expected_direct);
        assert_eq!(result.groups, files);
        fs::remove_dir_all(&job.output)?;
        clean(dir.path(), &job)?;
        parity(job.clone())?;
        fs::remove_dir_all(&job.output)?;
        clean(dir.path(), &job)?;
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-partition-balanced")]
#[test]
fn counted_partition_balanced_preserves_quotas_and_empty_root() -> Result<()> {
    for rows in [
        "",
        "1,界,z\n2,a,y\n3,界,z\n4,a,y\n5,界,z\n6,a,y\n7,界,z\n8,a,y\n9,界,z\n",
    ] {
        let text = format!("id,key,tag\n{rows}");
        let (_dir, mut job) = setup(text.as_bytes())?;
        job.resources.max_files = 16;
        job.operations = vec![
            Operation::Partition {
                columns: vec![Column::Index(1), Column::Index(2)],
            },
            Operation::Balanced { files: 2 },
        ];
        job.limits.bytes = Some(150);
        let result = parity(job)?;
        assert_eq!(result.output_files, if rows.is_empty() { 0 } else { 4 });
    }
    Ok(())
}

#[cfg(feature = "experimental-counted-partition-balanced")]
#[test]
fn counted_partition_balanced_cleans_too_small_capped_and_changed_inputs() -> Result<()> {
    let text = "id,key,payload\n1,a,0123456789\n2,b,0123456789\n3,a,0123456789\n4,b,0123456789\n5,b,0123456789\n";
    for mode in ["small", "byte-cap", "file-cap", "changed", "cancel"] {
        let (dir, mut job) = setup(text.as_bytes())?;
        job.resources.max_files = 16;
        job.operations = vec![
            Operation::Partition {
                columns: vec![Column::Index(1)],
            },
            Operation::Balanced {
                files: if mode == "small" { 3 } else { 2 },
            },
        ];
        if mode == "byte-cap" {
            job.limits.bytes = Some(35);
        } else if mode == "file-cap" {
            job.resources.max_files = 3;
        }
        let input = job.input.clone();
        let modified = fs::metadata(&input)?.modified()?;
        let cancel = Arc::new(AtomicBool::new(false));
        let request_cancel = cancel.clone();
        let result = engine::run(
            job.clone(),
            cancel,
            Arc::new(move |p| {
                if mode == "cancel" && p.phase == "Writing counted Balanced CSV" {
                    request_cancel.store(true, Ordering::SeqCst);
                }
                if mode == "changed" && p.phase == "Writing counted Balanced CSV" {
                    fs::write(&input, text.replace("0123456789", "9876543210")).unwrap();
                    fs::File::options()
                        .write(true)
                        .open(&input)
                        .unwrap()
                        .set_times(fs::FileTimes::new().set_modified(modified))
                        .unwrap();
                }
            }),
        );
        assert!(result.is_err(), "{mode}");
        clean(dir.path(), &job)?;
    }
    Ok(())
}
