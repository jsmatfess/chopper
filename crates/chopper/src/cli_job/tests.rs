use super::{census::*, *};
use std::io::Cursor;

fn ample() -> Arc<MemoryPool> {
    Arc::new(MemoryPool::new(128 * 1024 * 1024))
}
fn wire_cases() -> Vec<Vec<u8>> {
    let mut cases = vec![
        br#"{}"#.to_vec(), br#"[]"#.to_vec(),
        br#"{"input_csv":{},"output_csv":{},"resources":{"memory_mb":"auto"}}"#.to_vec(),
        br#"{"input":"\u00e9\u96ea\ud83e\udd80","operations":[{"type":"shuffle"},{"files":2,"type":"balanced"},{"type":"interleaved","files":2}]}"#.to_vec(),
        br#"{"operations":[{"columns":[0,"0","snow",1],"type":"partition"},{"groups":[{"name":"a","percent":"100"}],"strata":[0],"type":"assign"},{"type":"assign_probabilistic","groups":[["b","100"]]}]}"#.to_vec(),
        br#"{"calculated_columns":[{"name":"value","expression":"SAFE.NUMBER(a)"},{"name":"more","expression":"value + 2"}]}"#.to_vec(),
        br#"[1,"in","out",null,[],[],"none",[["partition",[0,"name"]],["assign",[["a","100"]],[]]],[],[]]"#.to_vec(),
    ];
    for n in [0, 1, 2, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33, 65, 129, 257] {
        cases.push(
            format!(
                r#"{{"input":"{}","operations":[{{"columns":[{}],"type":"partition"}}]}}"#,
                "x".repeat(n),
                (0..n).map(|i| i.to_string()).collect::<Vec<_>>().join(",")
            )
            .into_bytes(),
        );
    }
    cases
}
#[test]
fn requested_layouts_before_delivery_and_drop_before_release() -> Result<()> {
    println!(
        "CLI_JOB_LAYOUT C={} L={} U={} Operation={} Allocation={}",
        prefix::C,
        prefix::L,
        prefix::U,
        std::mem::size_of::<chopper_core::Operation>(),
        std::mem::size_of::<chopper_core::Allocation>()
    );
    for (wire, track_paths) in wire_cases()
        .into_iter()
        .flat_map(|wire| [(wire.clone(), false), (wire, true)])
    {
        let pool = ample();
        begin();
        let owner = DecodedJob::decode(Cursor::new(&wire), pool.clone(), track_paths);
        // Successful payload construction is the covered census. Serde/anyhow
        // error objects are deliberately tested separately below.
        let owner = match owner {
            Ok(owner) => owner,
            Err(error) => {
                end();
                panic!("{}: {error:#}", String::from_utf8_lossy(&wire));
            }
        };
        let mut retained = 0;
        census(|c| retained = c.live);
        assert_eq!(retained, engine::job_capacity(owner.job())?);
        drop(owner);
        let (live, peak, violations) = end();
        assert_eq!(
            (live, violations),
            (0, 0),
            "wire={} peak={peak}",
            String::from_utf8_lossy(&wire)
        );
        assert_eq!(pool.usage().reserved_bytes, 0);
    }
    Ok(())
}

#[derive(Clone)]
struct TraceReader<'a> {
    bytes: &'a [u8],
    offset: usize,
    calls: Vec<(usize, usize)>,
    interrupt: Option<usize>,
    fail: Option<usize>,
}
impl Read for TraceReader<'_> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        self.calls.push((self.offset, out.len()));
        if self.interrupt == Some(self.offset) {
            self.interrupt = None;
            return Err(io::ErrorKind::Interrupted.into());
        }
        if self.fail == Some(self.offset) {
            return Err(io::ErrorKind::Other.into());
        }
        if self.offset == self.bytes.len() {
            return Ok(0);
        }
        out[0] = self.bytes[self.offset];
        self.offset += 1;
        Ok(1)
    }
}
fn trace(bytes: &[u8]) -> TraceReader<'_> {
    TraceReader {
        bytes,
        offset: 0,
        calls: vec![],
        interrupt: None,
        fail: None,
    }
}
#[test]
fn legacy_reader_errors_values_positions_and_consumption() -> Result<()> {
    let mut cases = wire_cases();
    for wire in [
        r#"{"input":"one","input":"two",BROKEN"#,
        r#"{"unknown":0, BROKEN"#,
        r#"{"input_csv":{"encoding":"a","encoding":"b"}}"#,
        r#"{"operations":[{"columns":[0],"type":"partition","type":"shuffle"}]}"#,
        r#"{"operations":[{"type":"partition","columns":[{}]}]}"#,
        r#"{"operations":[{"type":"assign","groups":[0,0,0,0,0]}]}"#,
        r#"{"input":"\u12\"[]{}"}"#,
        r#"{"input":"\ud800x"}"#,
        r#"{"input":"\uZZZZ"}"#,
        r#"{"resources":{"memory_mb":[]}}"#,
        r#"{"operations":[["balanced",2,3]]}"#,
        r#"{"operations":[{"type":"balanced"}]}"#,
        r#"{"operations":[{"type":"assign","groups":[{"name":"missing-percent"}]}]}"#,
        r#"{} trailing"#,
        "",
        "{",
        "{} \n\t ",
    ] {
        cases.push(wire.as_bytes().to_vec());
    }
    cases.push(b"{\"input\":\"\xff\"}".to_vec());
    cases.push(
        format!(
            "{{\"operations\":[{{\"columns\":{}0{},\"type\":\"partition\"}}]}}",
            "[".repeat(140),
            "]".repeat(140)
        )
        .into_bytes(),
    );
    for (wire, track_paths) in cases
        .into_iter()
        .flat_map(|wire| [(wire.clone(), false), (wire, true)])
    {
        for (interrupt, fail) in [
            (None, None),
            (Some(0), None),
            (Some(4), None),
            (None, Some(0)),
            (None, Some(10)),
            (None, Some(wire.len())),
        ] {
            let mut legacy = trace(&wire);
            legacy.interrupt = interrupt;
            legacy.fail = fail;
            let mut adapted = legacy.clone();
            let old = serde_json::from_reader::<_, Job>(&mut legacy).context("read job JSON");
            let new = DecodedJob::decode(&mut adapted, ample(), track_paths);
            match (old, new) {
                (Ok(old), Ok(new)) => {
                    assert_eq!(
                        serde_json::to_value(&old)?,
                        serde_json::to_value(new.job())?
                    );
                    assert_eq!(
                        old.validate().err().map(|e| e.to_string()),
                        new.job().validate().err().map(|e| e.to_string())
                    );
                }
                (Err(old), Err(new)) => {
                    assert_eq!(format!("{old:#}"), format!("{new:#}"), "wire={wire:?}")
                }
                _ => panic!("legacy/adapted result differs for {wire:?}"),
            }
            assert_eq!(legacy.calls, adapted.calls, "wire={wire:?}");
            assert_eq!(legacy.offset, adapted.offset);
        }
    }
    Ok(())
}

#[test]
fn shared_edges_sticky_denial_eof_and_competing_owners() -> Result<()> {
    for wire in wire_cases() {
        let mut prefix = prefix::Prefix::default();
        let required = wire
            .iter()
            .fold(prefix::DEFAULTS, |_, b| prefix.advance(*b).unwrap());
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let mut source = trace(&wire);
            let result = DecodedJob::decode(&mut source, pool.clone(), false);
            assert_eq!(result.is_ok(), limit >= required);
            if let Err(error) = &result {
                assert!(matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Shared { .. })
                ));
            }
            drop(result);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
    }
    let pool = Arc::new(MemoryPool::new(28));
    let mut grant = Grant::new(pool.clone());
    grant.grow(28)?;
    let mut source = trace(b"{anything");
    let mut reader = AdmittedReader {
        source: &mut source,
        prefix: prefix::Prefix::default(),
        grant: &mut grant,
        denial: None,
        track_paths: false,
    };
    let mut out = [0];
    assert!(reader.read(&mut out).is_err());
    for _ in 0..5 {
        assert!(reader.read(&mut out).is_err());
    }
    assert!(reader.denial.is_some());

    assert_eq!(source.offset, 1);
    assert_eq!(source.calls.len(), 1);
    drop(grant);
    // Empty EOF needs only defaults. No speculative next-byte grant.
    let mut grant = Grant::new(pool);
    grant.grow(28)?;
    let mut reader = AdmittedReader {
        source: Cursor::new([]),
        prefix: prefix::Prefix::default(),
        grant: &mut grant,
        denial: None,
        track_paths: false,
    };
    assert_eq!(reader.read(&mut out)?, 0);
    assert!(reader.denial.is_none());
    let wire = br#"{"input":"retain"}"#;
    let probe = ample();
    let owner = DecodedJob::decode(Cursor::new(wire), probe.clone(), false)?;
    let retained = engine::job_capacity(owner.job())?;
    drop(owner);
    let mut prefix = prefix::Prefix::default();
    for b in wire {
        prefix.advance(*b).unwrap();
    }
    let pool = Arc::new(MemoryPool::new((prefix.required + retained - 1) as u64));
    let first = DecodedJob::decode(Cursor::new(wire), pool.clone(), false)?;
    assert!(DecodedJob::decode(Cursor::new(wire), pool.clone(), false).is_err());
    assert_eq!(pool.usage().reserved_bytes, retained as u64);
    drop(first);
    let retry = DecodedJob::decode(Cursor::new(wire), pool.clone(), false)?;
    drop(retry);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}

// Reference event generator: it constructs JSON and schedules semantic lexical
// events, then recomputes the whole reference sum from retained container records
// for every emitted byte. It does not scan bytes or share the incremental lexer.
#[derive(Clone, Copy)]
enum Event {
    None,
    Text(usize),
    Open(bool, Option<usize>),
    Comma(usize),
}
#[test]
fn independent_prefix_event_oracle_and_checked_fallback() {
    let mut wire = Vec::new();
    let mut events = Vec::new();
    let mut emit = |text: &[u8], event: Event| {
        for (i, b) in text.iter().enumerate() {
            wire.push(*b);
            events.push(if i == 0 { event } else { Event::None });
        }
    };
    emit(b"{", Event::Open(false, None)); // reference container 0
    emit(b"\"", Event::None);
    for i in 1..=10 {
        emit(b"x", Event::Text(i));
    }
    emit(b"\":[", Event::None); // array opener has its own event below
    *events.last_mut().unwrap() = Event::Open(true, None); // reference 1
    for count in 1..=9 {
        if count > 1 {
            wire.push(b',');
            events.push(Event::Comma(1));
        }
        wire.push(b'{');
        events.push(Event::Open(false, Some(1))); // reference 2..10
        for b in b"\"k\":" {
            wire.push(*b);
            events.push(if *b == b'k' {
                Event::Text(1)
            } else {
                Event::None
            });
        }
        wire.push(b'[');
        events.push(Event::Open(true, None)); // nested array 3,5,...
        let nested = 2 * count + 1;
        for k in 0..count {
            if k > 0 {
                wire.push(b',');
                events.push(Event::Comma(nested));
            }
            wire.push(b'0');
            events.push(Event::None);
        }
        wire.extend_from_slice(b"]}");
        events.extend_from_slice(&[Event::None, Event::None]);
    }
    wire.extend_from_slice(b"]}");
    events.extend_from_slice(&[Event::None, Event::None]);
    let mut reference: Vec<(bool, usize, usize)> = vec![];
    let mut q = 0;
    let mut h = 0;
    let mut prefix = prefix::Prefix::default();
    for (b, event) in wire.iter().zip(events) {
        match event {
            Event::None => {}
            Event::Text(n) => {
                q += 1;
                h = h.max(n);
            }
            Event::Open(array, parent) => {
                if let Some(parent) = parent {
                    reference[parent].2 += 1;
                }
                reference.push((array, 1, 0));
            }
            Event::Comma(index) => reference[index].1 += 1,
        }
        let g = |n: usize, s| if n == 0 { 0 } else { s * (3 * n).max(4) };
        let expected = 28
            + q
            + if h == 0 {
                0
            } else {
                let p = h.next_power_of_two().max(8);
                p + p / 2
            }
            + reference
                .iter()
                .map(|&(array, k, c)| {
                    if array {
                        g(k, prefix::C)
                            + (k * prefix::U)
                                .min(1_048_576)
                                .max(g(k, prefix::L))
                                .max(g(c, prefix::U))
                    } else {
                        g(k, 2 * prefix::C)
                    }
                })
                .sum::<usize>();
        assert_eq!(
            prefix.advance(*b),
            Some(expected),
            "prefix byte {}",
            prefix.bytes
        );
        assert_eq!((prefix.text, prefix.longest), (q, h));
    }
    // Escaped quote/backslash/raw Unicode interiors, independently enumerated.
    let mut p = prefix::Prefix::default();
    for (i, b) in b"\"a\\\"b\\\\c\"".iter().enumerate() {
        p.advance(*b).unwrap();
        assert_eq!(p.text, i.min(7));
    }
    let mut p = prefix::Prefix::default();
    for _ in 0..129 {
        p.advance(b'[').unwrap();
    }
    assert!(p.fallback);
    let previous = p.required;
    p.advance(b',').unwrap();
    let bytes = 130usize;
    let pow = bytes.next_power_of_two();
    let expected =
        28 + bytes + pow + pow / 2 + (prefix::C + prefix::U) * (4 * 129 + 3) + 2 * prefix::C * 3;
    assert_eq!(p.required, previous.max(expected));
    p.bytes = usize::MAX;
    assert!(p.advance(b' ').is_none());
}

#[test]
#[allow(clippy::vec_init_then_push)] // Exercise the actual first-push growth, not vec! allocation.
fn allowance_negative_controls_and_constructor_intermediates() -> Result<()> {
    // Defaults are exact copies, not Vec's minimum-eight growth. Removing one
    // pair of CSV defaults (14 bytes) from the 28 term fails independently.
    begin();
    observe_grant(28);
    let a = Job::default();
    let b = Job::default();
    let mut live = 0;
    census(|c| live = c.live);
    assert_eq!(live, 28);
    assert!(live > 14);
    drop((a, b));
    assert_eq!(end().0, 0);
    // Actual byte-vector realloc: removing old-block overlap underbounds 8->16.
    begin();
    observe_grant(24);
    let mut scratch = Vec::<u8>::new();
    scratch.extend_from_slice(b"12345678");
    scratch.push(b'9');
    let (_, peak, violations) = end();
    assert_eq!(peak, 24);
    assert_eq!(violations, 0);
    assert!(peak > 16);
    drop(scratch);
    // Content's exact cautious hint is obtained before scalar Allocation rejects.
    // Observe only its first requested layout; error internals are excluded.
    use serde::__private229::de::{Content, ContentDeserializer};
    use serde::Deserialize;
    let content = Content::Seq((0..37).map(|_| Content::U64(0)).collect());
    begin();
    observe_grant(usize::MAX);
    let error = Vec::<chopper_core::Allocation>::deserialize(ContentDeserializer::<
        serde::de::value::Error,
    >::new(content))
    .unwrap_err();
    let mut first = 0;
    census(|c| first = c.first_request);
    end();
    assert_eq!(first, 37 * std::mem::size_of::<chopper_core::Allocation>());
    assert!(
        first > 0,
        "removing eager hint term would admit zero typed bytes"
    );
    drop(error);
    // A child's owned allocation can exist before parent push. Removing the
    // enabled pending slot underbounds the first parent allocation.
    begin();
    observe_grant(4 * std::mem::size_of::<String>() + 7);
    let pending = String::from("pending");
    let mut parent = Vec::with_capacity(0);
    parent.push(pending);
    let mut live = 0;
    census(|c| live = c.live);
    assert!(live > 7);
    drop(parent);
    assert_eq!(end().0, 0);
    Ok(())
}

#[test]
fn metadata_open_order_and_stream_length_divergence() -> Result<()> {
    use std::cell::Cell;
    let opens = Cell::new(0);
    let pools = Cell::new(0);
    for length in [1_048_575, 1_048_576, 1_048_577] {
        let result = DecodedJob::open_after_metadata(
            length,
            || {
                opens.set(opens.get() + 1);
                Ok(Cursor::new(b"{}"))
            },
            || {
                pools.set(pools.get() + 1);
                Ok(ample())
            },
            false,
        );
        if length > 1_048_576 {
            assert_eq!(
                result.err().unwrap().to_string(),
                "configuration exceeds 1 MiB"
            );
        } else {
            drop(result?);
        }
    }
    assert_eq!((opens.get(), pools.get()), (2, 2));
    let error = DecodedJob::open_after_metadata(
        0,
        || -> io::Result<Cursor<&[u8]>> { Err(io::ErrorKind::PermissionDenied.into()) },
        || panic!("pool before open"),
        false,
    );
    assert!(!format!("{:#}", error.err().unwrap()).contains("read job JSON"));
    // A virtual reader has tiny storage but reports over 1 MiB of whitespace.
    // Metadata length zero must not create an actual-read cap.
    struct Grown {
        left: usize,
        first: usize,
    }
    impl Read for Grown {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            if self.first < 2 {
                out[0] = b"{}"[self.first];
                self.first += 1;
                Ok(1)
            } else if self.left > 0 {
                self.left -= 1;
                out[0] = b' ';
                Ok(1)
            } else {
                Ok(0)
            }
        }
    }
    let owner = DecodedJob::open_after_metadata(
        0,
        || {
            Ok(Grown {
                left: 1_048_600,
                first: 0,
            })
        },
        || Ok(ample()),
        false,
    )?;
    assert!(owner.job().operations.is_empty());
    Ok(())
}

#[test]
fn source_lifetime_profile_run_prepare_cancel_and_unwind() -> Result<()> {
    use std::sync::atomic::{AtomicU64, Ordering};
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"a\n1\n2\n")?;
    for (mode, track_paths) in [
        ("profile", false),
        ("run", false),
        ("prepare", false),
        ("cancel", false),
        ("unwind", false),
        ("unwind", true),
        ("decline", false),
        ("denied", false),
        ("prepare-denied", false),
    ] {
        let output = dir.path().join(mode);
        let wire = serde_json::to_vec(
            &serde_json::json!({"input":input,"output":output,"resources":{"memory_mb":32,"max_record_bytes":1024,"workers":1},"operations":if mode=="prepare" {serde_json::json!([{"type":"balanced","files":1}])} else {serde_json::json!([])}}),
        )?;
        let pool = ample();
        let owner = DecodedJob::decode(Cursor::new(&wire), pool.clone(), track_paths)?;
        let source = owner._grant.bytes as u64;
        let minimum = Arc::new(AtomicU64::new(u64::MAX));
        let progress_min = minimum.clone();
        let observed = pool.clone();
        let notify: Notify = Arc::new(move |_| {
            let used = observed.usage().reserved_bytes;
            assert!(used >= source);
            progress_min.fetch_min(used, Ordering::Relaxed);
            if mode == "unwind" {
                panic!("injected callback unwind");
            }
        });
        let cancel = Arc::new(AtomicBool::new(mode == "cancel"));
        match mode {
            "denied" | "prepare-denied" => {
                let mut competitor = Grant::new(pool.clone());
                competitor.grow(128 * 1024 * 1024 - source as usize)?;
                let result = if mode == "denied" {
                    owner.run(cancel, notify).map(|_| ())
                } else {
                    owner.analyze(cancel, notify).map(|_| ())
                };
                assert!(result.is_err());
                assert_eq!(pool.usage().reserved_bytes, competitor.bytes as u64);
                drop(competitor);
            }
            "profile" => {
                let mut cache = crate::profile::ProfileCache::with_memory_pool(pool.clone());
                let profile = cache.profile(owner.job(), cancel, notify)?;
                assert!(pool.usage().reserved_bytes >= source);
                drop(profile);
                cache.clear();
                assert_eq!(pool.usage().reserved_bytes, source);
                drop(owner);
            }
            "prepare" => {
                // A direct engine prepared result establishes independently that
                // both exact configuration grants coexist after preparation.
                let prepared = engine::prepare_with_memory_pool(
                    owner.job().clone(),
                    cancel.clone(),
                    notify.clone(),
                    pool.clone(),
                )?;
                assert_eq!(
                    prepared.job.reserved_bytes(),
                    engine::job_capacity(&prepared.job)? as u64
                );
                assert!(pool.usage().reserved_bytes >= source + prepared.job.reserved_bytes());
                drop(prepared);
                drop(owner.analyze(cancel, notify)?);
            }
            "decline" => drop(owner), // prompt's early error drops this same owner
            "unwind" => {
                assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(
                    || owner.run(cancel, notify)
                ))
                .is_err());
            }
            "cancel" => {
                assert!(owner.run(cancel, notify).is_err());
            }
            _ => drop(owner.run(cancel, notify)?),
        }
        assert_eq!(pool.usage().reserved_bytes, 0, "mode {mode}");
        if matches!(mode, "profile" | "run" | "prepare") {
            assert!(minimum.load(Ordering::Relaxed) >= source);
            assert_ne!(minimum.load(Ordering::Relaxed), u64::MAX);
        }
    }
    Ok(())
}

#[test]
fn every_enabling_prefix_boundary_and_no_denial_allocation() -> Result<()> {
    let wire =
        br#"{"input":"123456789\u96ea","operations":[{"columns":[0,1,2,3,4],"type":"partition"}]}"#;
    let mut expected = prefix::Prefix::default();
    let mut previous = 28;
    for (index, byte) in wire.iter().enumerate() {
        let required = expected.advance(*byte).unwrap();
        if required == previous {
            continue;
        }
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let mut grant = Grant::new(pool.clone());
            grant.grow(28)?;
            let mut source = Cursor::new(wire);
            let mut reader = AdmittedReader {
                source: &mut source,
                prefix: prefix::Prefix::default(),
                grant: &mut grant,
                denial: None,
                track_paths: false,
            };
            let mut out = [0];
            for _ in 0..index {
                assert_eq!(reader.read(&mut out)?, 1);
            }
            begin();
            observe_grant(usize::MAX);
            let next = reader.read(&mut out);
            let (_, peak, _) = end();
            assert_eq!(peak, 0, "denial transport must allocate no carrier");
            assert_eq!(next.is_ok(), limit >= required);
            if limit < required {
                assert!(reader.denial.is_some());
                assert!(reader.read(&mut out).is_err());
            }

            assert_eq!(source.position(), (index + 1) as u64);
            drop(grant);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        previous = required;
    }
    Ok(())
}

#[test]
fn tracked_paths_require_the_extra_allowance_before_delivering_a_byte() -> Result<()> {
    let map = br#"{"input":"retain","resources":{"workers"#;
    // The last byte raises Q to 27: input (5), retain (6), resources (9), workers (7).
    // Deep inputs reach the reader's fallback even though serde can reject their depth.
    let deep = [b'['; 129];
    for (wire, extra) in [(&map[..], 2 * 27), (&deep[..], 2 * deep.len())] {
        let mut prefix = prefix::Prefix::default();
        let untracked = wire
            .iter()
            .fold(prefix::DEFAULTS, |_, byte| prefix.advance(*byte).unwrap());
        let required = untracked + extra;
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let mut grant = Grant::new(pool.clone());
            grant.grow(prefix::DEFAULTS)?;
            let mut source = Cursor::new(wire);
            let mut reader = AdmittedReader {
                source: &mut source,
                prefix: prefix::Prefix::default(),
                grant: &mut grant,
                denial: None,
                track_paths: true,
            };
            let mut out = [0];
            for _ in 1..wire.len() {
                assert_eq!(reader.read(&mut out)?, 1);
            }
            begin();
            observe_grant(usize::MAX);
            let next = reader.read(&mut out);
            let (_, peak, _) = end();
            assert_eq!(peak, 0, "tracked denial transport must allocate no carrier");
            assert_eq!(next.is_ok(), limit >= required);
            if limit < required {
                assert!(matches!(reader.denial, Some(Denial::Shared(_))));
                assert!(reader.read(&mut out).is_err());
            } else {
                assert_eq!(grant.bytes, required);
            }
            assert_eq!(source.position(), wire.len() as u64);
            drop(grant);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
    }
    Ok(())
}

#[test]
fn partial_payloads_destroy_before_denied_grant_release() -> Result<()> {
    // Stop recording new allocations at the byte withheld on denial. All
    // existing payload allocations remain in the pointer census until freed;
    // serde/anyhow errors constructed afterward are explicit exclusions.
    struct Stop<'a> {
        source: Cursor<&'a [u8]>,
        withheld: usize,
    }
    impl Read for Stop<'_> {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            let position = self.source.position() as usize;
            let n = self.source.read(out)?;
            if position == self.withheld {
                census(|c| c.enabled = false);
            }
            Ok(n)
        }
    }
    for (wire, track_paths) in wire_cases()
        .into_iter()
        .flat_map(|wire| [(wire.clone(), false), (wire, true)])
    {
        let mut prefix = prefix::Prefix::default();
        let mut previous = 28;
        for (index, b) in wire.iter().enumerate() {
            let mut required = prefix.advance(*b).unwrap();
            if track_paths {
                assert!(!prefix.fallback, "control must use the lexical bound");
                required += 2 * prefix.text;
            }
            if required == previous {
                continue;
            }
            let pool = Arc::new(MemoryPool::new((required - 1) as u64));
            let source = Stop {
                source: Cursor::new(wire.as_slice()),
                withheld: index,
            };
            begin();
            let result = DecodedJob::decode(source, pool.clone(), track_paths);
            let (live, _, violations) = end();
            let error = result.err().context("denial expected")?;
            assert_eq!(
                (live, violations),
                (0, 0),
                "partial drop byte {index}, tracked {track_paths}"
            );
            assert!(error.downcast_ref::<MemoryAdmission>().is_some());
            assert_eq!(pool.usage().reserved_bytes, 0);
            previous = required;
        }
    }
    Ok(())
}

#[test]
fn typed_cautious_hint_cap_and_non_power_growth_controls() {
    use serde::de::{
        value::{Error, U64Deserializer},
        Deserialize, SeqAccess, Visitor,
    };
    struct Hint(usize);
    impl<'de> SeqAccess<'de> for Hint {
        type Error = Error;
        fn next_element_seed<T: serde::de::DeserializeSeed<'de>>(
            &mut self,
            seed: T,
        ) -> std::result::Result<Option<T::Value>, Error> {
            seed.deserialize(U64Deserializer::new(0)).map(Some)
        }
        fn size_hint(&self) -> Option<usize> {
            Some(self.0)
        }
    }
    // Obtain Vec's visitor using a minimal sequence deserializer with a false
    // hint. No large Content fixture or successful large job is constructed.
    struct Hinted(usize);
    impl<'de> serde::Deserializer<'de> for Hinted {
        type Error = Error;
        fn deserialize_any<V: Visitor<'de>>(
            self,
            visitor: V,
        ) -> std::result::Result<V::Value, Error> {
            visitor.visit_seq(Hint(self.0))
        }
        serde::forward_to_deserialize_any! {bool i8 i16 i32 i64 u8 u16 u32 u64 f32 f64 char str string bytes byte_buf option unit unit_struct newtype_struct seq tuple tuple_struct map struct enum identifier ignored_any}
    }
    let s = std::mem::size_of::<chopper_core::Allocation>();
    for n in [
        1,
        3,
        4,
        5,
        1_048_576 / s - 1,
        1_048_576 / s,
        1_048_576 / s + 1,
    ] {
        begin();
        observe_grant(usize::MAX);
        let error = Vec::<chopper_core::Allocation>::deserialize(Hinted(n)).unwrap_err();
        let mut first = 0;
        census(|c| first = c.first_request);
        end();
        assert_eq!(first, n.min(1_048_576 / s) * s);
        drop(error);
    }
    // Check the growth lemma against actual non-power-of-two starting capacities.
    for initial in [1, 2, 3, 5, 7] {
        let mut v = Vec::<chopper_core::Column>::with_capacity(initial);
        v.resize_with(initial, || chopper_core::Column::Index(0));
        // Census must include the old block; create it within the window.
        drop(v);
        begin();
        observe_grant(usize::MAX);
        let mut v = Vec::<chopper_core::Column>::with_capacity(initial);
        v.resize_with(initial, || chopper_core::Column::Index(0));
        v.push(chopper_core::Column::Index(0));
        let (_, peak, _) = end();
        assert!(peak <= ((3 * (initial + 1)).max(4)) * prefix::L);
        assert!(
            peak > v.capacity() * prefix::L,
            "removing old-block term must fail"
        );
        drop(v);
    }
}

#[test]
fn content_into_iter_retains_source_while_typed_destination_allocates() -> Result<()> {
    use serde::{
        __private229::de::{Content, ContentDeserializer},
        Deserialize,
    };
    for n in [1, 3, 4, 5, 37] {
        begin();
        observe_grant(usize::MAX);
        let mut source = Vec::with_capacity(n);
        for _ in 0..n {
            source.push(Content::U64(0));
        }
        let source_bytes = source.capacity() * prefix::C;
        let columns =
            Vec::<chopper_core::Column>::deserialize(
                ContentDeserializer::<serde::de::value::Error>::new(Content::Seq(source)),
            )?;
        let typed_bytes = columns.capacity() * prefix::L;
        let mut live = 0;
        census(|c| live = c.live);
        let (_, peak, _) = end();
        assert_eq!(live, typed_bytes);
        assert_eq!(peak, source_bytes + typed_bytes);
        assert!(
            peak > typed_bytes,
            "removing retained Content source must fail"
        );
        drop(columns);
    }
    Ok(())
}
