use super::*;
use anyhow::Context;
use std::io::Cursor;

struct Trace<'a> {
    source: Cursor<&'a [u8]>,
    reads: &'a mut Vec<[usize; 2]>,
}

impl Read for Trace<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        let read = self.source.read(bytes)?;
        self.reads.push([bytes.len(), read]);
        Ok(read)
    }
}

pub(super) fn run() -> Result<serde_json::Value> {
    const EXACT: u64 = 41_209;
    const RETAINED: usize = 8_224;
    ensure!((prefix::C, prefix::L, prefix::U) == (16, 12, 32));
    let wire = format!(
        r#"{{"input":"/input.csv","output":"{}"}}"#,
        "x".repeat(8_200)
    );
    let mut legacy_reads = Vec::with_capacity(3);
    let legacy: Job = serde_json::from_reader(io::BufReader::with_capacity(
        BUFFER_BYTES,
        Trace {
            source: Cursor::new(wire.as_bytes()),
            reads: &mut legacy_reads,
        },
    ))?;
    ensure!(
        legacy_reads == [[8_192, 8_192], [8_192, 42], [8_192, 0]],
        "unexpected buffered baseline: {legacy_reads:?}"
    );
    let pool = process_memory()?;
    let initial = pool.reservation_counts().0;
    let retained_owner = DecodedJob::decode_buffered(Cursor::new(wire.as_bytes()), pool.clone())?;
    let baseline = pool.reservation_counts().0;
    ensure!(baseline == initial + RETAINED as u64);
    let mut reads = Vec::with_capacity(3);
    let mut evidence = Vec::new();
    for available in [8_219, EXACT, EXACT - 1, EXACT] {
        let mut competitor = Grant::new(pool.clone());
        let competing = pool.admission_limit() - baseline - available;
        competitor.grow(competing as usize)?;
        reads.clear();
        census::begin();
        let decoded = DecodedJob::decode_buffered(
            Trace {
                source: Cursor::new(wire.as_bytes()),
                reads: &mut reads,
            },
            pool.clone(),
        );
        let mut live = 0;
        let mut first = 0;
        census::census(|c| {
            live = c.live;
            first = c.first_request;
        });
        let reserved = pool.reservation_counts().0 - baseline - competing;
        let result = match decoded {
            Ok(owner) => {
                let output_matches = owner.job().output == legacy.output;
                drop(owner);
                Ok(output_matches)
            }
            Err(error) => Err(error),
        };
        let (after, peak, violations) = census::end();
        ensure!(
            (after, violations) == (0, 0),
            "decode lost admission/drop ordering"
        );
        ensure!(pool.reservation_counts().0 == baseline + competing);
        if available == EXACT {
            ensure!(result? && live == RETAINED && reserved == RETAINED as u64);
            ensure!(reads == legacy_reads && first == BUFFER_BYTES && peak > RETAINED);
        } else {
            ensure!(result.err().is_some_and(|e| matches!(
                e.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            )));
            ensure!(live == 0 && reserved == 0);
            if available < BUFFER_BYTES as u64 + prefix::DEFAULTS as u64 {
                ensure!(reads.is_empty() && peak == 0);
            } else {
                ensure!(reads == legacy_reads[..2] && first == BUFFER_BYTES);
                ensure!(peak > BUFFER_BYTES);
            }
        }
        drop(competitor);
        ensure!(pool.reservation_counts().0 == baseline);
        evidence.push(serde_json::json!({
            "available_bytes": available,
            "requested_layout_peak_bytes": peak,
            "first_allocation_bytes": first,
            "borrowed_job_bytes": reserved,
            "source_reads": reads,
        }));
    }
    ensure!(retained_owner.job().output == legacy.output);
    drop(retained_owner);
    ensure!(pool.reservation_counts().0 == initial);
    for wire in [
        br#"{"input":"/input.csv","output":]"#.as_slice(),
        br#"{"input":"/input.csv","unexpected":true}"#.as_slice(),
        br#"{"input":"/input.csv"} trailing"#.as_slice(),
    ] {
        let legacy = serde_json::from_reader::<_, Job>(io::BufReader::with_capacity(
            BUFFER_BYTES,
            Cursor::new(wire),
        ))
        .unwrap_err();
        let error = DecodedJob::decode_buffered(Cursor::new(wire), pool.clone())
            .err()
            .context("malformed test Job decoded")?;
        let actual = error
            .downcast_ref::<serde_json::Error>()
            .context("WASI decoder wrapped or replaced the JSON error")?;
        ensure!(
            (
                actual.classify(),
                actual.line(),
                actual.column(),
                format!("{error:#}")
            ) == (
                legacy.classify(),
                legacy.line(),
                legacy.column(),
                legacy.to_string()
            )
        );
        ensure!(pool.reservation_counts().0 == initial);
    }
    Ok(serde_json::json!({
        "layout_bytes": [prefix::C, prefix::L, prefix::U],
        "construction_bytes": EXACT,
        "retained_bytes": RETAINED,
        "malformed_error_parity": true,
        "cases": evidence,
    }))
}
