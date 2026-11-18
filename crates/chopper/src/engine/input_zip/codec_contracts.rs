use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::io::{Cursor, Write};

const LIMIT: usize = 16 * 1024 * 1024;
const CSV: &[u8] = b"id\n1\n";
fn fixture(entries: &[(&str, zip::CompressionMethod, &[u8])]) -> Result<Vec<u8>> {
    let mut archive = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, compression, bytes) in entries {
        archive.start_file(
            *name,
            zip::write::SimpleFileOptions::default().compression_method(*compression),
        )?;
        archive.write_all(bytes)?;
    }
    Ok(archive.finish()?.into_inner())
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    use zip::CompressionMethod::{Deflated, Stored};
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("input.zip");
    let mut job = Job {
        input: path.to_string_lossy().into_owned(),
        ..Job::default()
    };
    let mut cases = Vec::new();
    for (name, entries, selection, expected) in [
        ("stored", vec![("data.CSV", Stored, CSV)], None, CSV),
        (
            "deflated-unicode",
            vec![("界.CsV", Deflated, CSV)],
            None,
            CSV,
        ),
        (
            "mixed-lookup",
            vec![
                ("other.bin", Deflated, b"other".as_slice()),
                ("data.csv", Stored, CSV),
            ],
            None,
            CSV,
        ),
        (
            "explicit",
            vec![
                ("first.csv", Stored, b"other".as_slice()),
                ("selected.csv", Deflated, CSV),
            ],
            Some("selected.csv"),
            CSV,
        ),
        (
            "empty",
            vec![("data.csv", Deflated, b"".as_slice())],
            None,
            b"".as_slice(),
        ),
        (
            "directory",
            vec![
                ("dir.csv/", Stored, b"".as_slice()),
                ("dir.csv/data.CSV", Deflated, CSV),
            ],
            None,
            CSV,
        ),
    ] {
        let bytes = fixture(&entries)?;
        std::fs::write(&path, &bytes)?;
        job.zip_member = selection.map(str::to_owned);
        let workspace = Arc::new(Workspace::new(LIMIT));
        let mut retained = 0;
        with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                retained = workspace.used();
                ensure!(
                    retained >= (8192 + reader_capacity()) as u64,
                    "ZIP codec missing"
                );
                let mut actual = Vec::new();
                reader.read_to_end(&mut actual)?;
                ensure!(
                    actual == expected && workspace.used() == retained,
                    "ZIP EOF parity/ownership changed"
                );
                drop(reader);
                ensure!(
                    workspace.used() == retained,
                    "archive scope lost reader allowance"
                );
                Ok(())
            },
        )?;
        let required = workspace.peak() as usize;
        ensure!(workspace.used() == 0, "ZIP success leaked");
        for shared in [false, true] {
            for limit in [required - 1, required, required + 1] {
                let pool = Arc::new(MemoryPool::new(if shared {
                    limit as u64
                } else {
                    u64::MAX
                }));
                let workspace = Arc::new(if shared {
                    Workspace::shared(LIMIT, pool.clone())
                } else {
                    Workspace::new(limit)
                });
                let mut called = false;
                let result = with_input(
                    &job,
                    Reservation::for_workspace(workspace.clone()),
                    |mut reader| {
                        called = true;
                        let mut actual = Vec::new();
                        reader.read_to_end(&mut actual)?;
                        ensure!(actual == expected, "ZIP edge parity changed");
                        Ok(())
                    },
                );
                ensure!(called == (limit >= required), "denied ZIP called consumer");
                if limit < required {
                    let error = result.err().context("ZIP codec edge accepted")?;
                    ensure!(
                        matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                        "ZIP codec denial lost type"
                    );
                } else {
                    result?;
                }
                ensure!(
                    workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                    "ZIP codec edge leaked"
                );
            }
        }
        let pool = Arc::new(MemoryPool::new(required as u64));
        let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let mut competitor =
            Reservation::for_workspace(Arc::new(Workspace::shared(1, pool.clone())));
        competitor.resize(1)?;
        let denied = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |_| -> Result<()> { anyhow::bail!("denied consumer") },
        )
        .err()
        .context("ZIP competitor did not deny")?;
        ensure!(
            matches!(
                denied.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && workspace.used() == 0
                && pool.usage().reserved_bytes == 1,
            "ZIP competitor ownership changed"
        );
        drop(competitor);
        with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                let mut actual = Vec::new();
                reader.read_to_end(&mut actual)?;
                ensure!(actual == expected, "ZIP retry parity changed");
                Ok(())
            },
        )?;
        let error = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| -> Result<()> {
                if !expected.is_empty() {
                    reader.read_exact(&mut [0; 1])?;
                }
                anyhow::bail!("cancelled")
            },
        )
        .err()
        .context("ZIP consumer failure accepted")?;
        ensure!(
            error.to_string() == "cancelled"
                && workspace.used() == 0
                && pool.usage().reserved_bytes == 0,
            "ZIP retry/consumer cleanup changed"
        );
        cases.push(json!({"name":name,"local_shared_edges":6,"retained_bytes":retained,"required_peak_bytes":required,"competitor_release_retry":true,"partial_consumer_failure_cleanup":true,"final_reserved_bytes":0}));
    }
    let basic = fixture(&[("data.csv", Deflated, CSV)])?;
    let mut crc = basic.clone();
    let central = crc.windows(4).position(|b| b == b"PK\x01\x02").unwrap();
    crc[central + 16..central + 20].fill(0);
    let mut deflate = basic.clone();
    let start = 30 + "data.csv".len();
    deflate[start] = 0xff;
    let mut unsupported = fixture(&[("other.bin", Stored, b"other"), ("data.csv", Deflated, CSV)])?;
    let central = unsupported
        .windows(4)
        .position(|b| b == b"PK\x01\x02")
        .unwrap();
    unsupported[central + 10..central + 12].copy_from_slice(&99u16.to_le_bytes());
    unsupported[8..10].copy_from_slice(&99u16.to_le_bytes());
    let mut encrypted = fixture(&[("other.bin", Stored, b"other"), ("data.csv", Deflated, CSV)])?;
    let central = encrypted
        .windows(4)
        .position(|b| b == b"PK\x01\x02")
        .unwrap();
    encrypted[central + 8] |= 1;
    encrypted[6] |= 1;
    let multiple = fixture(&[("one.csv", Stored, CSV), ("two.CSV", Deflated, CSV)])?;
    let directory = fixture(&[("dir.csv/", Stored, b"")])?;
    let mut errors = Vec::new();
    for (name, bytes, selection, consumer_expected) in [
        ("bad-crc", crc, None, true),
        ("bad-deflate", deflate, None, true),
        ("unsupported-unrelated", unsupported, None, false),
        ("encrypted-unrelated", encrypted, None, false),
        ("multiple-csv", multiple, None, false),
        ("selected-directory", directory, Some("dir.csv/"), false),
        ("missing-selected", basic, Some("absent.csv"), false),
    ] {
        std::fs::write(&path, &bytes)?;
        job.zip_member = selection.map(str::to_owned);
        // Keep by_index selection failures for unrelated invalid members;
        // selecting by raw metadata alone would change this behavior.
        let workspace = Arc::new(Workspace::new(LIMIT));
        let mut called = false;
        let result = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                called = true;
                let retained = workspace.used();
                let result = std::io::copy(&mut reader, &mut std::io::sink());
                ensure!(
                    workspace.used() == retained,
                    "ZIP decode error released allowance"
                );
                result?;
                Ok(())
            },
        );
        ensure!(
            result.is_err() && called == consumer_expected && workspace.used() == 0,
            "{name}: ZIP error/cleanup changed"
        );
        errors.push(name);
    }
    let mut csv = b"id\n".to_vec();
    for _ in 0..65537 {
        csv.extend_from_slice(b"1\n");
    }
    std::fs::write(&path, fixture(&[("data.csv", Deflated, &csv)])?)?;
    job.zip_member = None;
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
        .context("deflated ZIP profile did not cancel")?;
    ensure!(
        cancel.load(std::sync::atomic::Ordering::Relaxed)
            && format!("{error:#}").contains("cancel"),
        "ZIP cancellation did not reach decoded rows"
    );
    drop(cache);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "deflated ZIP profile cancellation leaked"
    );
    dir.close()?;
    Ok(
        json!({"contract":"zip-reader-codec-admission-v1","reader_allowance_bytes":reader_capacity(),"cases":cases,"malformed_and_selection_cleanup":errors,"public_profile_cancellation_cleanup":true,"final_reserved_bytes":0}),
    )
}

#[test]
fn zip_reader_codec_admission() {
    println!("{}", run().unwrap());
}
