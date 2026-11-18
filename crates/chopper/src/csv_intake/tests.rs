use super::*;
use crate::{resources::MemoryPool, storage::Workspace};
use std::{
    io::Cursor,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};

#[test]
fn owned_and_compact_share_decoding_header_width_and_record_numbers() -> Result<()> {
    for compact in [false, true] {
        for headers in [false, true] {
            let space = Arc::new(Workspace::new(1024 * 1024));
            let settings = CsvSettings {
                headers,
                ..Default::default()
            };
            let mut input = Intake::new(
                b"a,b\n1,\"x\ny\"\n2,z\n3\n".as_slice(),
                &settings,
                1024,
                Reservation::for_workspace(space.clone()),
            )?;
            let header = input.header()?;
            assert_eq!(header.is_some(), headers);
            let mut rows = Vec::new();
            loop {
                let result = if compact {
                    input.next_compact(|| Ok(()), |m, n| m.resize(n))
                } else {
                    input.next_owned(|| Ok(()))
                };
                match result {
                    Ok(true) => rows.push(if compact {
                        input
                            .compact()
                            .fields()
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    } else {
                        input.owned().clone()
                    }),
                    Ok(false) => panic!("width error was accepted"),
                    Err(error) => {
                        assert_eq!(error.to_string(), "CSV record 4 has 1 fields, expected 2");
                        break;
                    }
                }
            }
            assert_eq!(rows.len(), if headers { 2 } else { 3 });
            assert_eq!(input.columns(), 2);
            assert!(!input.next_owned(|| panic!("terminal parser called check"))?);
            assert!(!input.next_compact(
                || panic!("terminal parser called check"),
                |_, _| panic!("terminal parser reserved")
            )?);
            drop(header);
            drop(input);
            assert_eq!(space.used(), 0);
        }
    }
    Ok(())
}

#[test]
fn profile_prefix_defers_width_error_and_transfers_header_without_copying() -> Result<()> {
    let space = Arc::new(Workspace::new(1024 * 1024));
    let mut input = Intake::new(
        b"a,b\n1\n".as_slice(),
        &CsvSettings::default(),
        1024,
        Reservation::for_workspace(space.clone()),
    )?;
    let header = input.header()?.unwrap();
    let retained = header.memory.bytes();
    assert_eq!(header.fields, vec!["a", "b"]);
    assert!(input.prefetch()?);
    assert_eq!(input.columns(), 2);
    let ptr = input.owned().as_ptr();
    assert!(input.next_owned(|| Ok(())).is_err());
    assert_eq!(input.owned().as_ptr(), ptr);
    drop(input);
    assert_eq!(space.used(), retained);
    drop(header);
    assert_eq!(space.used(), 0);
    Ok(())
}

#[test]
fn denial_and_consumer_failure_keep_live_storage_admitted_until_drop() -> Result<()> {
    for shared in [false, true] {
        let pool = Arc::new(MemoryPool::new(4 * 1024 * 1024));
        let space = Arc::new(if shared {
            Workspace::shared(4 * 1024 * 1024, pool.clone())
        } else {
            Workspace::new(4 * 1024 * 1024)
        });
        let mut input = Intake::new(
            b"a,b\n1,x\n".as_slice(),
            &CsvSettings::default(),
            1024,
            Reservation::for_workspace(space.clone()),
        )?;
        drop(input.header()?);
        assert!(input.next_owned(|| Ok(()))?);
        let used = space.used();
        let failure: Result<()> = input.consume_owned(|_| anyhow::bail!("consumer sentinel"));
        assert_eq!(failure.unwrap_err().to_string(), "consumer sentinel");
        assert_eq!(space.used(), used);
        assert!(!input.next_owned(|| panic!("failed consumer resumed input"))?);
        drop(input);
        assert_eq!(space.used(), 0);
    }
    Ok(())
}

struct DropWitness {
    source: Cursor<Vec<u8>>,
    space: Arc<Workspace>,
    drops: Arc<AtomicUsize>,
}
impl Read for DropWitness {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        self.source.read(bytes)
    }
}
impl Drop for DropWitness {
    fn drop(&mut self) {
        assert!(
            self.space.used() >= SOURCE_BUFFER as u64,
            "source outlived its grant"
        );
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn source_drops_before_grant_after_success_parse_error_and_denial() -> Result<()> {
    for mode in 0..3 {
        let space = Arc::new(Workspace::new(1024 * 1024));
        let drops = Arc::new(AtomicUsize::new(0));
        let source = DropWitness {
            source: Cursor::new(if mode == 1 {
                b"\"unterminated".to_vec()
            } else {
                b"a,b\n".to_vec()
            }),
            space: space.clone(),
            drops: drops.clone(),
        };
        let mut input = Intake::new(
            source,
            &CsvSettings::default(),
            1024,
            Reservation::for_workspace(space.clone()),
        )?;
        let mut competitor = input.reservation();
        if mode == 2 {
            competitor.resize(1024 * 1024 - space.used() as usize)?;
        }
        let result = input.next_owned(|| Ok(()));
        assert_eq!(result.is_ok(), mode == 0);
        if mode != 0 {
            assert!(!input.next_owned(|| panic!("failed read resumed"))?);
        }
        drop(input);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        drop(competitor);
        assert_eq!(space.used(), 0);
    }
    Ok(())
}

#[test]
fn utf16_and_empty_header_cases_match_both_record_representations() -> Result<()> {
    for compact in [false, true] {
        for text in ["", "a,b\n", "a,b\n1,界\n"] {
            let space = Arc::new(Workspace::new(1024 * 1024));
            let bytes: Vec<u8> = [0xff, 0xfe]
                .into_iter()
                .chain(text.encode_utf16().flat_map(u16::to_le_bytes))
                .collect();
            let settings = CsvSettings {
                encoding: "UTF-16LE".into(),
                ..Default::default()
            };
            let mut input = Intake::new(
                bytes.as_slice(),
                &settings,
                1024,
                Reservation::for_workspace(space.clone()),
            )?;
            let header = input.header()?;
            assert_eq!(header.is_some(), !text.is_empty());
            let next = if compact {
                input.next_compact(|| Ok(()), |m, n| m.resize(n))?
            } else {
                input.next_owned(|| Ok(()))?
            };
            assert_eq!(next, text.contains('界'));
            if next {
                let fields = if compact {
                    input
                        .compact()
                        .fields()
                        .map(str::to_owned)
                        .collect::<Vec<_>>()
                } else {
                    input.owned().clone()
                };
                assert_eq!(fields, ["1", "界"]);
            }
            drop(header);
            drop(input);
            assert_eq!(space.used(), 0);
        }
    }
    Ok(())
}

#[test]
fn cancellation_checkpoint_precedes_width_validation_and_cannot_resume() -> Result<()> {
    for compact in [false, true] {
        let space = Arc::new(Workspace::new(1024 * 1024));
        let mut input = Intake::new(
            b"a,b\n1\n".as_slice(),
            &CsvSettings::default(),
            1024,
            Reservation::for_workspace(space.clone()),
        )?;
        drop(input.header()?);
        let result = if compact {
            input.next_compact(|| anyhow::bail!("cancel checkpoint"), |m, n| m.resize(n))
        } else {
            input.next_owned(|| anyhow::bail!("cancel checkpoint"))
        };
        assert_eq!(result.unwrap_err().to_string(), "cancel checkpoint");
        assert!(!input.next_owned(|| panic!("cancelled intake resumed"))?);
        assert!(space.used() > SOURCE_BUFFER as u64);
        drop(input);
        assert_eq!(space.used(), 0);
    }
    Ok(())
}

#[test]
fn compact_handoff_retains_same_storage_under_independent_admission() -> Result<()> {
    struct Retained {
        row: CompactRecord,
        _memory: Reservation,
    }
    let space = Arc::new(Workspace::new(1024 * 1024));
    let settings = CsvSettings {
        headers: false,
        ..Default::default()
    };
    let mut input = Intake::new(
        "1,界\n".as_bytes(),
        &settings,
        1024,
        Reservation::for_workspace(space.clone()),
    )?;
    assert!(input.next_compact(|| Ok(()), |m, n| m.resize(n))?);
    let pointer = input.compact().encoded_fields().as_ptr();
    let mut memory = input.reservation();
    let retained = input.consume_compact(|record| {
        memory.resize(record.capacity())?;
        Ok(Retained {
            row: std::mem::take(record),
            _memory: memory,
        })
    })?;
    assert_eq!(retained.row.encoded_fields().as_ptr(), pointer);
    drop(input);
    assert_eq!(space.used(), retained.row.capacity() as u64);
    assert_eq!(retained.row.fields().collect::<Vec<_>>(), ["1", "界"]);
    drop(retained);
    assert_eq!(space.used(), 0);
    Ok(())
}

struct Counted<P> {
    parser: P,
    calls: Arc<AtomicUsize>,
}
impl<P: Records> Records for Counted<P> {
    fn record_number(&self) -> u64 {
        self.parser.record_number()
    }
    fn scratch_capacity(&self) -> usize {
        self.parser.scratch_capacity()
    }
    fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.parser.next_record_into_reserved(fields, reserve)
    }
    fn next_compact_record_into_reserved(
        &mut self,
        fields: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.parser
            .next_compact_record_into_reserved(fields, reserve)
    }
}

#[test]
fn eof_and_parse_error_are_terminal_and_prefetch_is_not_a_second_read() -> Result<()> {
    for bytes in [b"1,x\n".as_slice(), b"\"unterminated".as_slice()] {
        let space = Arc::new(Workspace::new(1024 * 1024));
        let calls = Arc::new(AtomicUsize::new(0));
        let parser = Counted {
            parser: Parser::new(Cursor::new(bytes), CsvSettings::default(), 1024),
            calls: calls.clone(),
        };
        let mut input =
            Intake::from_parser(parser, Reservation::for_workspace(space.clone()), false);
        if input.prefetch().is_ok() {
            assert!(input.prefetch()?);
            assert_eq!(calls.load(Ordering::SeqCst), 1);
            assert!(input.next_owned(|| Ok(()))?);
            assert!(!input.next_owned(|| Ok(()))?);
        }
        let count = calls.load(Ordering::SeqCst);
        assert!(!input.next_owned(|| panic!("terminal checkpoint"))?);
        assert!(!input.prefetch()?);
        assert_eq!(calls.load(Ordering::SeqCst), count);
        drop(input);
        assert_eq!(space.used(), 0);
    }
    Ok(())
}

#[test]
fn representation_cannot_change_with_owned_or_compact_storage_live() -> Result<()> {
    for owned_first in [false, true] {
        let space = Arc::new(Workspace::new(1024 * 1024));
        let calls = Arc::new(AtomicUsize::new(0));
        let parser = Counted {
            parser: Parser::new(
                Cursor::new(b"1,a\n2,b\n".as_slice()),
                CsvSettings::default(),
                1024,
            ),
            calls: calls.clone(),
        };
        let mut input =
            Intake::from_parser(parser, Reservation::for_workspace(space.clone()), false);
        let error = if owned_first {
            assert!(input.prefetch()?);
            input
                .next_compact(
                    || Ok(()),
                    |_, _| panic!("mixed representation reserved memory"),
                )
                .unwrap_err()
        } else {
            assert!(input.next_compact(|| Ok(()), |m, n| m.resize(n))?);
            input.next_owned(|| Ok(())).unwrap_err()
        };
        assert_eq!(
            error.to_string(),
            "CSV intake cannot change record representation"
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let retained = space.used();
        assert!(retained > 0);
        assert!(!input.prefetch()?);
        assert!(!input.next_owned(|| panic!("mixed representation resumed"))?);
        assert_eq!(space.used(), retained);
        drop(input);
        assert_eq!(space.used(), 0);
    }
    Ok(())
}
