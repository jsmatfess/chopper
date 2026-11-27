//! Shared assertions for native and the separate test-only WASI reactor.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

const LIMIT: usize = 4 * 1024 * 1024;
const TEXT: &str = "name;note\r\nAlice;\"a,b\"\r\nBob;\"c,d\"\r\n";

fn utf16(text: &str, big: bool) -> Vec<u8> {
    let mut bytes = if big {
        vec![0xfe, 0xff]
    } else {
        vec![0xff, 0xfe]
    };
    for unit in text.encode_utf16() {
        bytes.extend(if big {
            unit.to_be_bytes()
        } else {
            unit.to_le_bytes()
        });
    }
    bytes
}

fn parity(bytes: &[u8], delimiter: char, encoding: &str, bom: bool, crlf: bool) -> Result<()> {
    let workspace = Arc::new(Workspace::new(LIMIT));
    let mut job = Job::default();
    job.input_csv.headers = false;
    job.input_csv.escape = Some('\\');
    job.input_csv.skip_empty_lines = true;
    let result = sniff(bytes, &job, Reservation::for_workspace(workspace.clone()))?;
    let mut settings = job.input_csv;
    settings.delimiter = delimiter;
    settings.encoding = encoding.into();
    settings.bom = bom;
    settings.line_ending = if crlf { "crlf" } else { "lf" }.into();
    ensure!(
        result
            == json!({
                "settings": settings,
                "note": NOTE,
                "delimiter_status": "detected",
                "sample_bytes": bytes.len().min(SAMPLE),
            }),
        "sniff JSON parity failed: {result}"
    );
    ensure!(workspace.used() > 0, "sniff result lost admission");
    drop(result);
    ensure!(workspace.used() == 0, "sniff JSON path leaked");
    Ok(())
}

fn bom_and_boundary() -> Result<usize> {
    parity(TEXT.as_bytes(), ';', "utf-8", false, true)?;
    let mut bom = vec![0xef, 0xbb, 0xbf];
    bom.extend_from_slice(TEXT.as_bytes());
    parity(&bom, ';', "utf-8", true, true)?;
    for big in [false, true] {
        parity(
            &utf16(TEXT, big),
            ';',
            if big { "utf-16be" } else { "utf-16le" },
            true,
            true,
        )?;
    }
    // The bounded sample, not the complete source, ends inside a UTF-8 point.
    for point in ["é", "界", "😀"] {
        for cut in 1..point.len() {
            let mut bytes = b"a;b\n1;2\n\"".to_vec();
            bytes.resize(SAMPLE - cut, b'x');
            bytes.extend_from_slice(point.as_bytes());
            parity(&bytes, ';', "utf-8", false, false)?;
        }
    }
    for big in [false, true] {
        let mut bytes = utf16("a;b\n1;2\n\"", big);
        let x = if big {
            (b'x' as u16).to_be_bytes()
        } else {
            (b'x' as u16).to_le_bytes()
        };
        while bytes.len() < SAMPLE - 2 {
            bytes.extend(x);
        }
        bytes.extend(if big {
            0xd800u16.to_be_bytes()
        } else {
            0xd800u16.to_le_bytes()
        });
        bytes.extend(if big {
            0xdc00u16.to_be_bytes()
        } else {
            0xdc00u16.to_le_bytes()
        });
        parity(
            &bytes,
            ';',
            if big { "utf-16be" } else { "utf-16le" },
            true,
            false,
        )?;
    }
    Ok(12)
}

fn scoring() -> Result<()> {
    let workspace = Arc::new(Workspace::new(LIMIT));
    let result = sniff(
        b"a;b\n1;2\n\"unterminated".as_slice(),
        &Job::default(),
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        result["note"] == NO_MATCH && result["delimiter_status"] == "not_detected",
        "malformed sample changed the delimiter"
    );
    drop(result);
    let settings = CsvSettings {
        delimiter: ';',
        ..Default::default()
    };
    let mut source = "a;b\n".repeat(50);
    source.push_str("\"unterminated");
    ensure!(
        candidate_score(
            source.as_bytes(),
            false,
            settings.clone(),
            &Default::default(),
            Reservation::for_workspace(workspace.clone())
        )?
        .consistent
            == 50,
        "candidate read past50 rows"
    );
    let nine = format!("{}a;b;c\n", "a;b\n".repeat(9));
    ensure!(
        candidate_score(
            nine.as_bytes(),
            false,
            settings.clone(),
            &Default::default(),
            Reservation::for_workspace(workspace.clone())
        )?
        .consistent
            == 9,
        "90percent boundary changed"
    );
    let eight = format!("{}a;b;c\na;b;c\n", "a;b\n".repeat(8));
    ensure!(
        candidate_score(
            eight.as_bytes(),
            false,
            settings,
            &Default::default(),
            Reservation::for_workspace(workspace.clone())
        )?
        .consistent
            == 0,
        "inconsistent candidate accepted"
    );
    ensure!(workspace.used() == 0, "candidate scoring leaked");
    Ok(())
}

fn phase(index: usize, charge: Reservation) -> Result<()> {
    if index == 0 {
        // Fixture construction is outside the measured ownership boundary.
        // Cross the 8 KiB read chunk to exercise old/new allocation overlap.
        let source = TEXT.repeat(400);
        let mut owner = ChargedBytes::read(source.as_bytes(), charge, SAMPLE)?;
        let capacity = owner.bytes.capacity();
        ensure!(
            owner.charge.bytes() == capacity as u64 && capacity > 0,
            "raw owner charge missing at EOF"
        );
        owner.bytes.truncate(1);
        ensure!(
            owner.charge.bytes() == capacity as u64,
            "truncate released retained allocation"
        );
    } else if index == 1 {
        let text = TEXT.repeat(400);
        let source = utf16(&text, false);
        let raw = ChargedBytes::read(source.as_slice(), charge.sibling(), SAMPLE)?;
        let decoded = ChargedBytes::read(
            DecodeReader::new(raw.bytes.as_slice(), "utf-16le")?,
            charge,
            3 * SAMPLE,
        )?;
        ensure!(decoded.bytes == text.as_bytes(), "decoded sample changed");
        ensure!(
            raw.charge.bytes() == raw.bytes.capacity() as u64
                && decoded.charge.bytes() == decoded.bytes.capacity() as u64,
            "overlapping raw/decoded owner charge missing"
        );
        drop(raw);
        ensure!(
            decoded.charge.bytes() > 0,
            "raw drop released decoded owner"
        );
    } else {
        let decoded = ChargedBytes::read(TEXT.as_bytes(), charge.sibling(), 3 * SAMPLE)?;
        let settings = CsvSettings {
            delimiter: ';',
            ..Default::default()
        };
        ensure!(
            candidate_score(&decoded.bytes, false, settings, &Default::default(), charge)?
                .consistent
                == 3,
            "candidate score changed"
        );
        ensure!(
            decoded.charge.bytes() > 0,
            "candidate drop released decoded owner"
        );
    }
    Ok(())
}

fn admission() -> Result<Vec<serde_json::Value>> {
    let mut observations = Vec::new();
    for index in 0..3 {
        let probe = Arc::new(Workspace::new(LIMIT));
        phase(index, Reservation::for_workspace(probe.clone()))?;
        let peak = probe.peak();
        ensure!(peak > 0 && probe.used() == 0, "phase probe leaked");
        let local = Arc::new(Workspace::new(peak as usize - 1));
        let error = phase(index, Reservation::for_workspace(local.clone()))
            .err()
            .context("phase local grant should fail")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ),
            "phase lost local admission type"
        );
        ensure!(local.used() == 0, "phase local denial leaked");
        let pool = Arc::new(MemoryPool::new(peak + 7));
        let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let mut held = Reservation::for_workspace(Arc::new(Workspace::shared(8, pool.clone())));
        held.resize(8)?;
        let error = phase(index, Reservation::for_workspace(workspace.clone()))
            .err()
            .context("phase shared grant should fail")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ),
            "phase lost shared admission type"
        );
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 8,
            "phase denial damaged live owner"
        );
        drop(held);
        phase(index, Reservation::for_workspace(workspace.clone()))?;
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "phase fresh retry leaked"
        );
        observations
            .push(json!({"phase": (["raw", "decoded", "candidate"][index]), "peak_bytes":peak}));
    }
    Ok(observations)
}

fn full_sniff_retry() -> Result<()> {
    let job = Job::default();
    let probe = Arc::new(Workspace::new(LIMIT));
    let expected = sniff(
        TEXT.as_bytes(),
        &job,
        Reservation::for_workspace(probe.clone()),
    )?;
    let peak = probe.peak();
    let pool = Arc::new(MemoryPool::new(peak + 7));
    let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
    let mut held = Reservation::for_workspace(Arc::new(Workspace::shared(8, pool.clone())));
    held.resize(8)?;
    let error = sniff(
        TEXT.as_bytes(),
        &job,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("sniff should return denial, not different dialect")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ),
        "sniff swallowed admission"
    );
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 8,
        "sniff denial leaked"
    );
    drop(held);
    ensure!(
        sniff(
            TEXT.as_bytes(),
            &job,
            Reservation::for_workspace(workspace.clone())
        )? == expected,
        "fresh sniff retry changed JSON"
    );
    ensure!(pool.usage().reserved_bytes == 0, "sniff retry leaked");
    Ok(())
}

fn fragmented_reads() -> Result<()> {
    struct Fragmented<'a>(&'a [u8]);
    impl Read for Fragmented<'_> {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            let len = out.len().min(1);
            self.0.read(&mut out[..len])
        }
    }
    let workspace = Arc::new(Workspace::new(LIMIT));
    let owner = ChargedBytes::read(
        Fragmented(TEXT.as_bytes()),
        Reservation::for_workspace(workspace.clone()),
        SAMPLE,
    )?;
    ensure!(
        owner.bytes == TEXT.as_bytes() && owner.bytes.capacity() <= 2 * TEXT.len(),
        "fragmented reads grew by read count, not needed capacity"
    );
    ensure!(
        workspace.used() == owner.bytes.capacity() as u64,
        "fragmented owner capacity missing"
    );
    drop(owner);
    let job = Job::default();
    let expected = sniff(
        TEXT.as_bytes(),
        &job,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        sniff(
            Fragmented(TEXT.as_bytes()),
            &job,
            Reservation::for_workspace(workspace.clone())
        )? == expected,
        "fragmented sniff changed JSON"
    );
    drop(expected);
    ensure!(workspace.used() == 0, "fragmented sample leaked");
    Ok(())
}

fn errors_and_read_bound() -> Result<()> {
    let job = Job::default();
    let mut interior_invalid = vec![b'x'; SAMPLE];
    interior_invalid[12] = 0xff;
    for source in [
        vec![0xff],
        vec![0xc3],
        vec![0xff, 0xfe, b'a'],
        vec![0xff, 0xfe, 0x00, 0xd8],
        interior_invalid,
    ] {
        let workspace = Arc::new(Workspace::new(LIMIT));
        ensure!(
            sniff(
                source.as_slice(),
                &job,
                Reservation::for_workspace(workspace.clone())
            )
            .is_err(),
            "short invalid sequence was trimmed or accepted"
        );
        ensure!(workspace.used() == 0, "strict decode error leaked");
    }
    struct ReadError {
        sent: bool,
        workspace: Arc<Workspace>,
    }
    impl Read for ReadError {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            if self.sent {
                assert!(
                    self.workspace.used() > 0,
                    "source error did not exercise charged sample cleanup"
                );
                return Err(std::io::Error::other("cancelled"));
            }
            self.sent = true;
            let read = out.len().min(TEXT.len());
            out[..read].copy_from_slice(&TEXT.as_bytes()[..read]);
            Ok(read)
        }
    }
    let workspace = Arc::new(Workspace::new(LIMIT));
    let error = sniff(
        ReadError {
            sent: false,
            workspace: workspace.clone(),
        },
        &job,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("source error accepted")?;
    ensure!(
        format!("{error:#}").contains("cancelled") && workspace.used() == 0,
        "source error changed or leaked"
    );
    struct Counted<'a> {
        source: &'a [u8],
        count: &'a std::cell::Cell<usize>,
        interrupted: bool,
    }
    impl Read for Counted<'_> {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            if self.interrupted {
                self.interrupted = false;
                return Err(std::io::ErrorKind::Interrupted.into());
            }
            let read = self.source.read(out)?;
            self.count.set(self.count.get() + read);
            Ok(read)
        }
    }
    let mut bytes = b"a;b\n1;2\n\"".to_vec();
    bytes.resize(SAMPLE, b'x');
    bytes.extend([0xff; 100]);
    let count = std::cell::Cell::new(0);
    let source = Counted {
        source: &bytes,
        count: &count,
        interrupted: true,
    };
    sniff(source, &job, Reservation::for_workspace(workspace.clone()))?;
    ensure!(
        count.get() == SAMPLE && workspace.used() == 0,
        "sniff crossed bounded sample or leaked"
    );
    Ok(())
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let boundary_cases = bom_and_boundary()?;
    scoring()?;
    let phases = admission()?;
    full_sniff_retry()?;
    fragmented_reads()?;
    errors_and_read_bound()?;
    Ok(json!({
        "contract":"inspection-sniff-resource-contracts-v1", "sample_limit_bytes":SAMPLE,
        "capacity_phases":phases, "typed_local_denials":3, "typed_shared_denials":4,
        "fresh_owner_release_retries":4, "bom_boundary_cases":boundary_cases,
        "eof_truncate_owner_retained":true, "raw_decoded_overlap_charged":true,
        "typed_candidate_denial_propagates":true, "ordinary_syntax_suppressed":true,
        "score_ties_threshold_and_50_rows_preserved":true, "json_settings_preserved":true,
        "strict_decode_error_cleanup_cases":5, "source_error_cleanup":true,
        "fragmented_reads_preserve_capacity_and_json":true,
        "interrupted_read_retried":true, "sample_read_bound_verified":true, "final_reserved_bytes":0,
    }))
}

#[cfg(test)]
mod tests {
    #[test]
    fn sniff_shared_capacity_and_behavior_contract() -> anyhow::Result<()> {
        super::run()?;
        Ok(())
    }
}
