use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::io::Write;

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("input.gz");
    let job = Job {
        input: path.to_string_lossy().into_owned(),
        ..Job::default()
    };
    let mut encoder = flate2::GzBuilder::new()
        .extra(vec![7; 65535])
        .filename(vec![b'n'; 65535])
        .comment(vec![b'c'; 65535])
        .write(Vec::new(), Default::default());
    encoder.write_all(b"id\n1\n")?;
    let mut member = encoder.finish()?;
    // Add the optional header checksum to the maximum accepted metadata.
    let header_end = 10 + 2 + 65535 + 65536 + 65536;
    member[3] |= 2;
    let crc = (crc32fast::hash(&member[..header_end]) as u16).to_le_bytes();
    member.splice(header_end..header_end, crc);
    let mut concatenated = member.clone();
    concatenated.extend_from_slice(&member);
    std::fs::write(&path, &concatenated)?;
    let required = 8192 + capacity::<File>();
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(required + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let mut called = false;
            let result = with_input(
                &job,
                Reservation::for_workspace(workspace.clone()),
                |mut reader| {
                    called = true;
                    ensure!(workspace.used() == required as u64, "missing codec grant");
                    let mut decoded = Vec::new();
                    reader.read_to_end(&mut decoded)?;
                    ensure!(decoded == b"id\n1\nid\n1\n", "gzip member parity changed");
                    ensure!(workspace.used() == required as u64, "EOF released codec");
                    drop(reader);
                    ensure!(workspace.used() == 0, "reader drop retained codec grant");
                    Ok(())
                },
            );
            ensure!(
                called == (limit >= required),
                "denied reader reached consumer"
            );
            if limit < required {
                let error = result
                    .err()
                    .context("gzip admission unexpectedly succeeded")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "gzip denial lost type"
                );
            } else {
                result?;
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "gzip grant leaked"
            );
        }
    }
    // A denied constructor must not parse even the first header.
    struct Counted<R> {
        source: R,
        reads: Arc<std::sync::atomic::AtomicUsize>,
    }
    impl<R: Read> Read for Counted<R> {
        fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
            self.reads
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            self.source.read(bytes)
        }
    }
    let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let source = Counted {
        source: File::open(&path)?,
        reads: reads.clone(),
    };
    let workspace = Arc::new(Workspace::new(8192 + capacity::<Counted<File>>() - 1));
    let buffer = Reservation::for_workspace(workspace.clone());
    let codec = buffer.sibling();
    ensure!(
        admitted(InputBuffer::new(source, 8192, buffer)?, codec).is_err(),
        "constructor edge accepted"
    );
    ensure!(
        reads.load(std::sync::atomic::Ordering::Relaxed) == 0 && workspace.used() == 0,
        "denied constructor read or leaked"
    );

    let mut header_crc = member.clone();
    header_crc[header_end] ^= 1;
    let mut trailer_crc = member.clone();
    let trailer = trailer_crc.len() - 8;
    trailer_crc[trailer] ^= 1;
    let mut truncated = member.clone();
    truncated.pop();
    let mut reserved = member.clone();
    reserved[3] |= 0x80;
    let mut overlong = vec![0x1f, 0x8b, 8, 8, 0, 0, 0, 0, 0, 255];
    overlong.extend(std::iter::repeat_n(b'n', 65536));
    overlong.push(0);
    let mut errors = Vec::new();
    for (name, bytes) in [
        ("header-crc", header_crc),
        ("trailer-crc", trailer_crc),
        ("truncated", truncated),
        ("reserved-flags", reserved),
        ("overlong-name", overlong),
    ] {
        std::fs::write(&path, bytes)?;
        let workspace = Arc::new(Workspace::new(required));
        let result = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                let result = std::io::copy(&mut reader, &mut std::io::sink());
                ensure!(
                    workspace.used() == required as u64,
                    "codec error released live owner"
                );
                result?;
                Ok(())
            },
        );
        ensure!(
            result.is_err() && workspace.used() == 0,
            "{name}: error or cleanup changed"
        );
        errors.push(name);
    }
    std::fs::write(&path, member)?;
    for read_first in [false, true] {
        let workspace = Arc::new(Workspace::new(required));
        let error = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| -> Result<()> {
                if read_first {
                    reader.read_exact(&mut [0; 1])?;
                }
                anyhow::bail!("cancelled")
            },
        )
        .err()
        .context("consumer failure accepted")?;
        ensure!(
            error.to_string() == "cancelled" && workspace.used() == 0,
            "consumer cleanup changed"
        );
    }
    dir.close()?;
    Ok(json!({
        "contract": "gzip-codec-admission-v1", "codec_capacity_bytes": capacity::<File>(),
        "input_buffer_bytes": 8192, "header_allowance_bytes": HEADER_ALLOWANCE,
        "local_shared_edges": 6, "concatenated_maximum_headers_with_crc": true,
        "admission_before_header_read": true, "eof_owner_retained": true,
        "malformed_stream_cleanup": errors, "consumer_failure_checks": 2,
        "final_reserved_bytes": 0,
    }))
}

#[test]
fn gzip_codec_admission() {
    println!("{}", run().unwrap());
}
