//! Actual parser admission, immutable retry and archive/member lifetime controls.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::io::{Cursor, Write};

const CSV: &[u8] = b"id\n1\n";
const LIMIT: usize = 16 * 1024 * 1024;

fn archive(name: &str, entries: usize, data: &[u8], comment: &[u8]) -> Result<Vec<u8>> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    writer.set_raw_comment(comment.to_vec().into_boxed_slice());
    let options =
        zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored);
    writer.start_file(name, options)?;
    writer.write_all(data)?;
    for index in 1..entries {
        writer.start_file(format!("entry-{index}.bin"), options)?;
    }
    Ok(writer.finish()?.into_inner())
}
fn u16_at(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes(bytes[offset..offset + 2].try_into().unwrap())
}
fn u32_at(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}
fn end(bytes: &[u8]) -> usize {
    bytes
        .windows(4)
        .rposition(|chunk| chunk == b"PK\x05\x06")
        .unwrap()
}
fn decorated(mut bytes: Vec<u8>, extra: &[u8], comment: &[u8], cp437: bool) -> Vec<u8> {
    let eocd = end(&bytes);
    let central = u32_at(&bytes, eocd + 16) as usize;
    let name = u16_at(&bytes, central + 28) as usize;
    let length = u32_at(&bytes, eocd + 12);
    assert_eq!(u16_at(&bytes, central + 30), 0);
    assert_eq!(u16_at(&bytes, central + 32), 0);
    if cp437 {
        let flags = u16_at(&bytes, central + 8) & !0x800;
        bytes[central + 8..central + 10].copy_from_slice(&flags.to_le_bytes());
        bytes[6..8].copy_from_slice(&flags.to_le_bytes());
    }
    bytes[central + 30..central + 32].copy_from_slice(&(extra.len() as u16).to_le_bytes());
    bytes[central + 32..central + 34].copy_from_slice(&(comment.len() as u16).to_le_bytes());
    let insert = central + 46 + name;
    bytes.splice(insert..insert, extra.iter().chain(comment).copied());
    let eocd = eocd + extra.len() + comment.len();
    bytes[eocd + 12..eocd + 16]
        .copy_from_slice(&(length + extra.len() as u32 + comment.len() as u32).to_le_bytes());
    bytes
}
fn fallback(mut bytes: Vec<u8>, count: u16, comment: usize) -> Vec<u8> {
    let mut fake = [0u8; 22];
    fake[..4].copy_from_slice(b"PK\x05\x06");
    fake[8..10].copy_from_slice(&count.to_le_bytes());
    fake[10..12].copy_from_slice(&count.to_le_bytes());
    fake[20..22].copy_from_slice(&(comment as u16).to_le_bytes());
    bytes.extend_from_slice(&fake);
    bytes.resize(bytes.len() + comment, b'x');
    bytes
}
fn zip64(mut bytes: Vec<u8>, extension: usize) -> Vec<u8> {
    let eocd = end(&bytes);
    let original = bytes[eocd..].to_vec();
    let count = u16_at(&original, 10) as u64;
    let length = u32_at(&original, 12) as u64;
    let offset = u32_at(&original, 16) as u64;
    bytes.truncate(eocd);
    bytes.extend_from_slice(b"PK\x06\x06");
    bytes.extend_from_slice(&(44 + extension as u64).to_le_bytes());
    bytes.extend_from_slice(&[45, 0, 45, 0]);
    bytes.extend_from_slice(&[0; 8]);
    for value in [count, count, length, offset] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes.resize(bytes.len() + extension, 0);
    bytes.extend_from_slice(b"PK\x06\x07");
    bytes.extend_from_slice(&0u32.to_le_bytes());
    bytes.extend_from_slice(&(eocd as u64).to_le_bytes());
    bytes.extend_from_slice(&1u32.to_le_bytes());
    let start = bytes.len();
    bytes.extend_from_slice(&original);
    bytes[start + 8..start + 12].fill(0xff);
    bytes[start + 12..start + 20].fill(0xff);
    bytes
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let source_owner = Arc::new(Workspace::new(8192));
    let mut source = InputBuffer::new(CSV, 8192, Reservation::for_workspace(source_owner.clone()))?;
    ensure!(
        source.reader.capacity() == 8192 && source_owner.used() == 8192,
        "ZIP source buffer charge changed"
    );
    std::io::copy(&mut source, &mut std::io::sink())?;
    ensure!(
        source_owner.used() == 8192,
        "EOF released ZIP source buffer"
    );
    drop(source);
    ensure!(source_owner.used() == 0, "ZIP source buffer leaked");
    #[cfg(target_os = "wasi")]
    let fixture = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let fixture = tempfile::tempdir()?;
    let fixture_path = fixture.path().to_owned();
    let basic = archive("sample.csv", 1, CSV, b"")?;
    let mut timestamp = Vec::new();
    for _ in 0..128 {
        timestamp.extend_from_slice(&[0x55, 0x54, 1, 0, 0]);
    }
    let mut underreported = archive("sample.csv", 64, CSV, b"")?;
    let mut ntfs = Vec::new();
    for _ in 0..64 {
        ntfs.extend_from_slice(&[0x0a, 0, 32, 0, 0, 0, 0, 0, 1, 0, 24, 0]);
        for value in [1u64, 2, 3] {
            ntfs.extend_from_slice(&value.to_le_bytes());
        }
    }
    let eocd = end(&underreported);
    underreported[eocd + 12..eocd + 16].fill(0);
    let cases = vec![
        ("basic", basic.clone()),
        ("many", archive("sample.csv", 64, CSV, b"")?),
        (
            "fallback",
            fallback(archive("sample.csv", 64, CSV, b"")?, 1, 0),
        ),
        (
            "failed_large_candidate",
            fallback(basic.clone(), 400, 40000),
        ),
        ("underreported", underreported),
        (
            "utf8",
            decorated(
                archive(&("界".repeat(2000) + ".csv"), 1, CSV, b"archive-comment")?,
                &[],
                &vec![0xff; 4096],
                false,
            ),
        ),
        (
            "cp437",
            decorated(
                archive(&("é".repeat(2000) + ".csv"), 1, CSV, b"")?,
                &[],
                &vec![0x82; 4096],
                true,
            ),
        ),
        (
            "timestamps",
            decorated(basic.clone(), &timestamp, b"", false),
        ),
        (
            "malformed_extra_scratch",
            decorated(basic.clone(), &[0xfe, 0xff, 0xff, 0xff], b"", false),
        ),
        ("ntfs", decorated(basic.clone(), &ntfs, b"", false)),
        ("zip64", zip64(basic.clone(), 65536)),
        (
            "archive_comment",
            archive("sample.csv", 1, CSV, &vec![b'c'; 60000])?,
        ),
    ];
    let mut reports = Vec::new();
    let mut callback_denials = 0usize;
    let mut basic_retained = 0;
    for (name, bytes) in cases {
        let legacy = zip::ZipArchive::new(Cursor::new(&bytes))?;
        let legacy_names = legacy.file_names().map(str::to_owned).collect::<Vec<_>>();
        let mut requests = 0usize;
        let mut parser_peak = 0;
        let admitted = zip::ZipArchive::new_with_metadata_budget(Cursor::new(&bytes), |bytes| {
            requests += 1;
            parser_peak = parser_peak.max(bytes);
            Ok(())
        })?;
        ensure!(
            admitted.file_names().map(str::to_owned).collect::<Vec<_>>() == legacy_names
                && admitted.comment() == legacy.comment(),
            "ZIP budget changed accepted metadata"
        );
        drop(admitted);
        drop(legacy);
        if name == "fallback" || name == "zip64" || name == "failed_large_candidate" {
            for denied_at in 1..=requests {
                let mut calls = 0usize;
                let result = zip::ZipArchive::new_with_metadata_budget(Cursor::new(&bytes), |_| {
                    calls += 1;
                    if calls == denied_at {
                        Err(std::io::Error::other("budget sentinel"))
                    } else {
                        Ok(())
                    }
                });
                let error = result
                    .err()
                    .context("ZIP budget error fell back to success")?;
                ensure!(
                    error.to_string().contains("budget sentinel") && calls == denied_at,
                    "ZIP denial continued directory fallback or allocation"
                );
                callback_denials += 1;
            }
        }
        let input = fixture.path().join(name);
        std::fs::write(&input, &bytes)?;
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            resources: Resources {
                memory_mb: 32.into(),
                max_record_bytes: 2 * 1024 * 1024,
                ..Default::default()
            },
            ..Default::default()
        };
        let workspace = Arc::new(Workspace::new(LIMIT));
        let mut retained = 0;
        with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                retained = workspace.used();
                ensure!(retained > 8192, "ZIP metadata missing");
                let mut actual = Vec::new();
                reader.read_to_end(&mut actual)?;
                ensure!(
                    actual == CSV && workspace.used() == retained,
                    "ZIP EOF changed bytes or released metadata"
                );
                Ok(())
            },
        )?;
        let required = workspace.peak() as usize;
        ensure!(workspace.used() == 0, "ZIP success leaked");
        if name == "basic" {
            basic_retained = retained;
        }
        if name == "failed_large_candidate" {
            ensure!(
                (parser_peak + 8192) as u64 > retained - reader_capacity() as u64
                    && retained == basic_retained,
                "failed ZIP candidate kept its dead metadata allowance"
            );
        }
        if name == "zip64" {
            ensure!(
                retained >= basic_retained + 65536,
                "ZIP64 extension was not charged"
            );
        }
        if name == "archive_comment" {
            ensure!(
                retained >= basic_retained + 60000,
                "EOCD comment was not charged"
            );
        }
        if name == "utf8" || name == "cp437" {
            ensure!(
                retained > basic_retained + 16000,
                "decoded ZIP text envelope was not charged"
            );
        }
        if name == "timestamps" || name == "ntfs" {
            ensure!(
                retained > basic_retained + 4096,
                "parsed extra-field envelope was not charged"
            );
        }
        if name == "many" {
            ensure!(
                retained >= 128 * 1024 + 8192 + 64 * 512,
                "ZIP descriptor/map envelope was not charged"
            );
        }
        for delta in [-1isize, 0, 1] {
            let limit = required.saturating_add_signed(delta);
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let owner = Arc::new(Workspace::shared(LIMIT, pool.clone()));
            let mut called = false;
            let result = with_input(
                &job,
                Reservation::for_workspace(owner.clone()),
                |mut reader| {
                    called = true;
                    let mut value = Vec::new();
                    reader.read_to_end(&mut value)?;
                    ensure!(value == CSV, "ZIP bytes changed");
                    Ok(())
                },
            );
            ensure!(
                result.is_ok() == (delta >= 0) && called == (delta >= 0),
                "{name}: ZIP shared edge {delta}: {result:?}"
            );
            if delta < 0 {
                ensure!(
                    matches!(
                        result.unwrap_err().downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "ZIP shared denial lost type"
                );
            }
            ensure!(
                pool.usage().reserved_bytes == 0 && owner.used() == 0,
                "ZIP shared denial/success leaked"
            );
        }
        let local = Arc::new(Workspace::new(required - 1));
        let mut called = false;
        let error = with_input(&job, Reservation::for_workspace(local.clone()), |_| {
            called = true;
            Ok(())
        })
        .err()
        .context("ZIP local edge succeeded")?;
        ensure!(
            !called
                && matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Local)
                )
                && local.used() == 0,
            "ZIP local denial changed: {error:#}"
        );
        let pool = Arc::new(MemoryPool::new(required as u64));
        let live = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let mut competitor =
            Reservation::for_workspace(Arc::new(Workspace::shared(1, pool.clone())));
        competitor.resize(1)?;
        let error = with_input::<()>(&job, Reservation::for_workspace(live.clone()), |_| {
            anyhow::bail!("denied ZIP called consumer")
        })
        .err()
        .context("competing ZIP owner failed to deny")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && pool.usage().reserved_bytes == 1,
            "ZIP denial lost competitor"
        );
        drop(competitor);
        with_input(
            &job,
            Reservation::for_workspace(live.clone()),
            |mut reader| {
                let mut value = Vec::new();
                reader.read_to_end(&mut value)?;
                ensure!(value == CSV, "immutable ZIP retry changed bytes");
                Ok(())
            },
        )?;
        let error = with_input::<()>(&job, Reservation::for_workspace(live.clone()), |_| {
            anyhow::bail!("consumer sentinel")
        })
        .err()
        .context("ZIP consumer error lost")?;
        ensure!(
            error.to_string() == "consumer sentinel" && pool.usage().reserved_bytes == 0,
            "ZIP consumer failure leaked"
        );
        ensure!(std::fs::read(&input)? == bytes, "ZIP source changed");
        reports.push(json!({"name":name,"required_peak_bytes":required,"parser_requested_peak_bytes":parser_peak,"retained_at_eof_bytes":retained,"fixture_blake3":blake3::hash(&bytes).to_hex().to_string(),"shared_edges":3,"typed_local_denials":1,"typed_shared_denials":2,"release_retries":1,"consumer_error_cleanup":true,"final_reserved_bytes":0}));
    }
    // CRC failure happens after successful metadata admission/member borrowing.
    let input = fixture.path().join("bad-crc");
    let mut bad = basic.clone();
    let central = u32_at(&bad, end(&bad) + 16) as usize;
    bad[14..18].copy_from_slice(&0u32.to_le_bytes());
    bad[central + 16..central + 20].copy_from_slice(&0u32.to_le_bytes());
    std::fs::write(&input, &bad)?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Default::default()
    };
    let owner = Arc::new(Workspace::new(LIMIT));
    let mut called = false;
    let error = with_input::<()>(
        &job,
        Reservation::for_workspace(owner.clone()),
        |mut reader| {
            called = true;
            ensure!(owner.used() > 8192, "CRC error lost metadata owner");
            let mut bytes = Vec::new();
            reader.read_to_end(&mut bytes)?;
            anyhow::bail!("corrupt ZIP unexpectedly reached EOF")
        },
    )
    .err()
    .context("bad ZIP CRC accepted")?;
    ensure!(
        called && !error.to_string().contains("unexpectedly") && owner.used() == 0,
        "ZIP CRC error leaked metadata or changed validation"
    );
    let input = fixture.path().join("cancelled-profile");
    let mut data = b"id\n".to_vec();
    for _ in 0..65537 {
        data.extend_from_slice(b"1\n");
    }
    std::fs::write(&input, archive("sample.csv", 1, &data, b"")?)?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        resources: Resources {
            memory_mb: 32.into(),
            max_record_bytes: 2 * 1024 * 1024,
            workers: 1,
            ..Default::default()
        },
        ..Default::default()
    };
    let pool = Arc::new(MemoryPool::new(LIMIT as u64));
    let mut cache = crate::profile::ProfileCache::with_memory_pool(pool.clone());
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    let error = cache
        .profile(
            &job,
            cancel.clone(),
            Arc::new(move |progress| {
                if progress.rows >= 65536 {
                    signal.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }),
        )
        .err()
        .context("ZIP profile cancellation did not stop")?;
    ensure!(
        cancel.load(std::sync::atomic::Ordering::Relaxed)
            && format!("{error:#}").contains("cancel"),
        "ZIP profile did not reach cancellation while reading"
    );
    drop(cache);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "cancelled ZIP profile leaked metadata"
    );
    fixture.close()?;
    ensure!(!fixture_path.try_exists()?, "ZIP fixture leaked");
    Ok(
        json!({"contract":"zip-metadata-admission-resource-contract-v1","cases":reports,"source_buffer_bytes":8192,"reader_allowance_bytes":reader_capacity(),"terminal_callback_denials":callback_denials,"crc_error_cleanup":true,"public_profile_cancellation_cleanup":true,"fixture_directory_removed":true,"scope":"conservative constructor/retained metadata plus separately owned member-reader allowance; excludes other codecs/runtime/RSS"}),
    )
}

#[cfg(test)]
#[test]
fn zip_metadata_edges_retry_and_eof_owners() -> Result<()> {
    let report = run()?;
    println!("CHOPPER_ZIP_METADATA_CONTRACT {report}");
    Ok(())
}
