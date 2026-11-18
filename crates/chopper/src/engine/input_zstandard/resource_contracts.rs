use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::io::Cursor;
mod modern;

const LEGACY: &[u8] =
    include_bytes!("../../../../../vendor/zstd-sys-2.1.1/chopper-tests/legacy.zst");
const EXPECTED: &[u8] =
    include_bytes!("../../../../../vendor/zstd-sys-2.1.1/chopper-tests/expected.txt");
const LIMIT: usize = 16 * 1024 * 1024;

fn frames() -> Result<Vec<&'static [u8]>> {
    let mut result = Vec::new();
    let mut remaining = LEGACY;
    while !remaining.is_empty() {
        // The fixture slice remains valid for the pointer/length scan.
        let count = unsafe {
            zstd_sys::ZSTD_findFrameCompressedSize(remaining.as_ptr().cast(), remaining.len())
        };
        ensure!(
            unsafe { zstd_sys::ZSTD_isError(count) } == 0 && count > 0 && count <= remaining.len(),
            "legacy fixture frame scan failed"
        );
        result.push(&remaining[..count]);
        remaining = &remaining[count..];
    }
    ensure!(
        result.len() == 5
            && result
                .iter()
                .enumerate()
                .all(|(index, frame)| frame[0] == 0x24 + index as u8),
        "legacy fixture versions changed"
    );
    Ok(result)
}

fn decode(bytes: &[u8], deny: Option<usize>) -> Result<(Vec<u8>, usize, usize)> {
    let workspace = Arc::new(Workspace::new(LIMIT));
    let mut actual = Vec::new();
    let mut requests = 0;
    let mut peak_payload = 0;
    let result = drive_control(
        Cursor::new(bytes),
        25,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            reader.read_to_end(&mut actual)?;
            Ok(())
        },
        |state| state.deny_at = deny,
        |state| {
            requests = state.requests;
            peak_payload = state.peak_payload;
            assert_eq!(state.payload, 0, "C payload leaked");
            assert_eq!(state.reserved(), 0, "C allocation header leaked");
            if deny.is_none() {
                assert_eq!(state.requests, state.frees, "C allocation/free imbalance");
            }
        },
    );
    ensure!(workspace.used() == 0, "Zstandard operation leaked");
    result?;
    Ok((actual, requests, peak_payload))
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("input.zst");
    let job = Job {
        input: path.to_string_lossy().into_owned(),
        ..Job::default()
    };
    let legacy_frames = frames()?;
    let sample = &EXPECTED[..EXPECTED.len() / 5];
    ensure!(
        EXPECTED.chunks(sample.len()).all(|part| part == sample),
        "legacy expected fixture changed"
    );
    let (actual, requests, legacy_peak) = decode(LEGACY, None)?;
    ensure!(actual == EXPECTED, "legacy corpus parity changed");
    let mut denied = 0;
    for at in 1..=requests {
        let error = decode(LEGACY, Some(at))
            .err()
            .context("injected decoder allocation denial accepted")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ),
            "C allocation denial lost type"
        );
        denied += 1;
    }
    let prefix = zstd::stream::encode_all(b"".as_slice(), 0)?;
    let mut cases = Vec::new();
    for (index, frame) in legacy_frames.iter().enumerate() {
        let mut encoded = prefix.clone();
        encoded.extend_from_slice(frame);
        std::fs::write(&path, &encoded)?;
        let workspace = Arc::new(Workspace::new(LIMIT));
        let mut initial = 0;
        let mut retained = 0;
        with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                initial = workspace.used();
                let mut actual = Vec::new();
                reader.read_to_end(&mut actual)?;
                ensure!(actual == sample, "legacy version bytes changed");
                retained = workspace.used();
                ensure!(retained >= initial, "EOF released context storage");
                drop(reader);
                ensure!(
                    workspace.used() == fixed_capacity::<InputBuffer<File>>() as u64,
                    "reader drop retained C/input buffers or lost its live controller"
                );
                Ok(())
            },
        )?;
        let required = workspace.peak() as usize;
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
                let result = with_input(
                    &job,
                    Reservation::for_workspace(workspace.clone()),
                    |mut reader| {
                        let mut actual = Vec::new();
                        reader.read_to_end(&mut actual)?;
                        ensure!(actual == sample, "decoder edge changed bytes");
                        Ok(())
                    },
                );
                if limit < required {
                    let error = result.err().context("Zstandard dynamic edge accepted")?;
                    ensure!(
                        matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                        "dynamic decoder denial lost type"
                    );
                } else {
                    result?;
                }
                ensure!(
                    workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                    "dynamic decoder edge leaked"
                );
            }
        }
        let pool = Arc::new(MemoryPool::new(required as u64));
        let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let mut competitor =
            Reservation::for_workspace(Arc::new(Workspace::shared(1, pool.clone())));
        competitor.resize(1)?;
        let result = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                let mut bytes = Vec::new();
                reader.read_to_end(&mut bytes)?;
                ensure!(bytes == sample, "competing reader changed bytes");
                Ok(())
            },
        );
        ensure!(
            matches!(
                result
                    .err()
                    .context("competing decoder admitted")?
                    .downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && pool.usage().reserved_bytes == 1,
            "decoder competitor changed"
        );
        drop(competitor);
        with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                let mut actual = Vec::new();
                reader.read_to_end(&mut actual)?;
                ensure!(actual == sample, "decoder retry changed bytes");
                Ok(())
            },
        )?;
        let error = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| -> Result<()> {
                reader.read_exact(&mut [0; 1])?;
                anyhow::bail!("cancelled")
            },
        )
        .err()
        .context("decoder consumer failure lost")?;
        ensure!(
            error.to_string() == "cancelled"
                && workspace.used() == 0
                && pool.usage().reserved_bytes == 0,
            "decoder consumer cleanup changed"
        );
        cases.push(json!({"format_version":index+4,"initial_reserved_bytes":initial,"retained_eof_bytes":retained,"required_peak_bytes":required,"local_shared_edges":6,"competitor_release_retry":true,"consumer_failure_cleanup":true,"final_reserved_bytes":0}));
    }
    let mut combined = prefix.clone();
    combined.extend_from_slice(LEGACY);
    std::fs::write(&path, &combined)?;
    let workspace = Arc::new(Workspace::new(LIMIT));
    with_input(
        &job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut bytes = Vec::new();
            reader.read_to_end(&mut bytes)?;
            ensure!(
                bytes == EXPECTED,
                "public legacy concatenation parity changed"
            );
            Ok(())
        },
    )?;
    let mut errors = Vec::new();
    for (index, frame) in legacy_frames.iter().enumerate() {
        let mut broken = prefix.clone();
        broken.extend_from_slice(frame);
        broken.pop();
        std::fs::write(&path, broken)?;
        let result = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |mut reader| {
                std::io::copy(&mut reader, &mut std::io::sink())?;
                Ok(())
            },
        );
        ensure!(
            result.is_err() && workspace.used() == 0,
            "truncated legacy accepted or leaked"
        );
        errors.push(index + 4);
    }
    let standard = modern::run(&job, &path)?;
    dir.close()?;
    Ok(
        json!({"contract":"zstandard-input-codec-admission-v1","fixture_versions":[4,5,6,7,8],"legacy_constructor_and_buffer_denials":denied,"legacy_peak_payload_bytes":legacy_peak,"cases":cases,"public_modern_then_legacy_parity":true,"truncated_versions_cleanup":errors,"final_reserved_bytes":0,"standard_case":standard}),
    )
}

#[test]
fn zstandard_input_codec_admission() {
    println!("{}", run().unwrap());
}
