use super::*;
use std::sync::atomic::Ordering;
pub(super) mod arrow_census;

// Fixed correctness-only decoder witness; thread-local counters prevent races.
// Callback path uses only TLS Cells/arithmetic and System: no lock/format/unwind.
mod manifest_heap_witness {
    use std::alloc::{GlobalAlloc, Layout, System};
    #[derive(Clone, Copy, Default, Debug)]
    pub(super) struct Counts {
        pub live: isize,
        pub peak: usize,
        pub largest: usize,
        pub pair: usize,
        pub negative: bool,
        pub carrier_live: isize,
        pub carrier_peak: usize,
    }
    thread_local! {
        static ENABLED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
        static CARRIER_SIZE: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
        static COUNTS: std::cell::Cell<Counts> = const { std::cell::Cell::new(Counts {
            live: 0, peak: 0, largest: 0, pair: 0, negative: false, carrier_live: 0, carrier_peak: 0,
        }) };
    }
    pub(super) struct Probe;
    impl Probe {
        pub fn start() -> Self {
            COUNTS.with(|slot| slot.set(Counts::default()));
            CARRIER_SIZE.with(|slot| slot.set(0));
            ENABLED.with(|slot| slot.set(true));
            Self
        }
        pub fn carriers(size: usize) -> Self {
            let probe = Self::start();
            CARRIER_SIZE.with(|slot| slot.set(size));
            probe
        }
        pub fn finish(self) -> Counts {
            ENABLED.with(|slot| slot.set(false));
            COUNTS.with(std::cell::Cell::get)
        }
    }
    impl Drop for Probe {
        fn drop(&mut self) {
            let _ = ENABLED.try_with(|slot| slot.set(false));
        }
    }
    fn event(old: usize, new: usize, success: bool, realloc: bool) {
        let _ = ENABLED.try_with(|enabled| {
            if enabled.get() {
                let _ = COUNTS.try_with(|slot| {
                    let mut c = slot.get();
                    let size = CARRIER_SIZE.with(std::cell::Cell::get);
                    if size != 0 {
                        c.carrier_peak = c
                            .carrier_peak
                            .max(c.carrier_live.max(0) as usize + usize::from(new == size));
                        if success {
                            c.carrier_live += isize::from(new == size) - isize::from(old == size);
                        }
                    }
                    c.largest = c.largest.max(new);
                    if realloc {
                        c.pair = c.pair.max(old.saturating_add(new));
                    }
                    c.peak = c.peak.max((c.live.max(0) as usize).saturating_add(new));
                    if success {
                        c.live = c
                            .live
                            .saturating_add(new as isize)
                            .saturating_sub(old as isize);
                    }
                    c.negative |= c.live < 0;
                    slot.set(c);
                });
            }
        });
    }
    pub(super) struct Allocator;
    // SAFETY: pointers/layouts pass unchanged to System; counters do not allocate.
    unsafe impl GlobalAlloc for Allocator {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            let p = unsafe { System.alloc(layout) };
            event(0, layout.size(), !p.is_null(), false);
            super::arrow_census::event(0, p as usize, 0, layout.size(), layout.align(), 1);
            p
        }
        unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
            let p = unsafe { System.alloc_zeroed(layout) };
            event(0, layout.size(), !p.is_null(), false);
            super::arrow_census::event(0, p as usize, 0, layout.size(), layout.align(), 2);
            p
        }
        unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
            let p = unsafe { System.realloc(pointer, layout, size) };
            event(layout.size(), size, !p.is_null(), true);
            super::arrow_census::event(
                pointer as usize,
                p as usize,
                layout.size(),
                size,
                layout.align(),
                3,
            );
            p
        }
        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            event(layout.size(), 0, true, false);
            super::arrow_census::event(pointer as usize, 0, layout.size(), 0, layout.align(), 4);
            unsafe { System.dealloc(pointer, layout) }
        }
    }
}
#[global_allocator]
static MANIFEST_WITNESS_ALLOCATOR: manifest_heap_witness::Allocator =
    manifest_heap_witness::Allocator;

#[test]
fn manifest_error_relocation_and_closing_delimiter_carriers() {
    // A syntax-only rejection allocates exactly its ErrorImpl, retained in Err.
    let probe = manifest_heap_witness::Probe::start();
    let syntax = serde_json::from_slice::<Manifest>(b"!");
    let held = probe.finish();
    let size = held.live as usize;
    assert!(size > 0 && size <= MANIFEST_ERROR_CARRIER);
    assert_eq!(held.peak, size);
    drop(syntax);
    let wrong = "x".repeat(1000);
    for (name, input) in [
        ("relocation", format!("{{\"headers\":\"{wrong}\"}}")),
        ("ret-end-map", format!("{{\"{wrong}\":null}}")),
        ("ret-end-seq", format!("[\"{wrong}\",0]")),
    ] {
        let probe = manifest_heap_witness::Probe::carriers(size);
        let result = serde_json::from_slice::<Manifest>(input.as_bytes());
        let rejected = result.is_err();
        drop(result);
        let counts = probe.finish();
        eprintln!("carrier {name}: box={size} requested={counts:?}");
        assert!(rejected);
        assert!(!counts.negative);
        assert_eq!(counts.live, 0);
        assert_eq!(counts.carrier_live, 0);
        assert_eq!(counts.carrier_peak, 2);
        assert!(counts.peak <= MANIFEST_DECODE_BYTES - (MAX_MANIFEST + 1));
    }
}

#[test]
fn manifest_production_decoder_fixed_allocation_regressions() -> Result<()> {
    let (_root, job) = fixture(b"id\n1\n")?;
    let pool = pool();
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let baseline = pool.usage().reserved_bytes;
    let mut del = b"{\"headers\":\"".to_vec();
    del.extend(std::iter::repeat_n(0x7f, 8000));
    del.extend_from_slice(b"\"}");
    assert_eq!(del.len(), 8014);
    let cases = [
        ("original-DEL-wrong-bool", del),
        ("digest-wrong-type", b"{\"source_blake3\":false}".to_vec()),
        (
            "escaped-unknown-key",
            format!("{{\"{}\":false}}", "\\u007f".repeat(1300)).into_bytes(),
        ),
        (
            "escaped-unknown-variant",
            format!("{{\"format\":\"{}\"}}", "\\u007f".repeat(1300)).into_bytes(),
        ),
        ("syntax-truncation", b"{\"source_blake3\":\"abc\\u".to_vec()),
        // Wrong scalar relocates a custom error, then the outer map checks EOF.
        (
            "relocation-map-close",
            b"{\"headers\":false,\"version\":\"wrong\"".to_vec(),
        ),
        // Unknown key rejects before consuming colon; ret and end_map both err.
        (
            "ret-end-map",
            b"{\"unknown\":{\"nested\":[1,2,3]}}".to_vec(),
        ),
        // Sequence field rejects before the outer end_seq sees a comma.
        ("ret-end-sequence", b"[\"wrong\",0]".to_vec()),
        (
            "enum-object-error",
            b"{\"format\":{\"unknown\":null}}".to_vec(),
        ),
    ];
    for (name, bytes) in cases {
        assert!(bytes.len() <= MAX_MANIFEST);
        let probe = manifest_heap_witness::Probe::start();
        let result = decode_manifest(bytes.as_slice(), &ctx);
        let rejected = result.is_err();
        drop(result);
        let counts = probe.finish();
        eprintln!(
            "manifest decoder {name}: input={} grant={} requested={counts:?}",
            bytes.len(),
            MANIFEST_DECODE_BYTES
        );
        assert!(rejected, "{name} accepted");
        assert!(!counts.negative, "probe scope lost an allocation owner");
        assert_eq!(counts.live, 0, "{name} last allocation owner leaked");
        assert!(
            counts.peak <= MANIFEST_DECODE_BYTES,
            "{name} simultaneous requested heap exceeded admission"
        );
        assert!(
            counts.pair <= MANIFEST_DECODE_BYTES - (MAX_MANIFEST + 1),
            "{name} input plus realloc pair exceeded admission"
        );
        assert_eq!(pool.usage().reserved_bytes, baseline);
    }
    drop(ctx);
    clean(&job, &pool);
    Ok(())
}

#[test]
fn construction_owners_admit_before_clone_and_release_after_payloads() -> Result<()> {
    for shared in [false, true] {
        let (_root, mut job) = fixture(b"id,value\n0,0007\n")?;
        job.zip_member = Some("selected/\u{754c}.csv".repeat(20));
        job.input.reserve(1024);
        let pool = pool();
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let baseline = pool.usage().reserved_bytes;
        let path = Path::new("a/\u{754c}/\u{1f600}/source.partial");
        let mut held = Reservation::new(&ctx);
        let hold = if shared {
            pool.usage().limit_bytes - baseline
        } else {
            ctx.memory as u64 / 2
                - ctx.diagnostics()["workspace_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        };
        if shared {
            pool.acquire(hold)?;
        } else {
            held.resize(hold as usize)?;
        }
        let before = pool.usage().reserved_bytes;
        assert!(FrozenJob::new(&job, path, &ctx).is_err());
        assert!(AdmittedPath::new(path, Some("manifest.json"), &ctx).is_err());
        assert_eq!(pool.usage().reserved_bytes, before);
        if shared {
            pool.release(hold);
        } else {
            drop(held);
        }
        let owner = FrozenJob::new(&job, path, &ctx)?;
        assert_eq!(owner.value.input, path.to_string_lossy());
        assert_eq!(owner.value.zip_member, job.zip_member);
        assert_eq!(
            owner._grant.bytes(),
            job_owner::capacity(&owner.value)? as u64
        );
        let admitted = AdmittedPath::new(path, Some("manifest.json"), &ctx)?;
        assert_eq!(admitted.value, path.join("manifest.json"));
        assert_eq!(
            pool.usage().reserved_bytes,
            baseline + owner._grant.bytes() + admitted._grant.bytes()
        );
        drop(admitted);
        drop(owner);
        assert_eq!(pool.usage().reserved_bytes, baseline);
        drop(ctx);
        clean(&job, &pool);
    }
    Ok(())
}

type ConsumingCheckpoint = Box<dyn FnMut(u64)>;
type CopyCheckpoint = Box<dyn FnOnce(u64)>;

thread_local! {
    static BEFORE_PRIVATE_FILE: std::cell::RefCell<Option<Box<dyn FnOnce()>>> = std::cell::RefCell::new(None);
    static CONSUMING: std::cell::RefCell<Option<ConsumingCheckpoint>> = std::cell::RefCell::new(None);
    static AFTER_AUTHENTICATION: std::cell::RefCell<Option<Box<dyn FnOnce()>>> = std::cell::RefCell::new(None);
    static COPY_BLOCK: std::cell::RefCell<Option<CopyCheckpoint>> = std::cell::RefCell::new(None);
    static AFTER_BINDING: std::cell::RefCell<Option<Box<dyn FnOnce()>>> =
        std::cell::RefCell::new(None);
}

// A hook can remain pending when preparation returns early. Keep cleanup on
// the installing thread and release captured owners on errors and unwinding.
struct Checkpoints(std::marker::PhantomData<std::rc::Rc<()>>);

impl Checkpoints {
    fn new() -> Self {
        Self(std::marker::PhantomData)
    }
}

impl Drop for Checkpoints {
    fn drop(&mut self) {
        BEFORE_PRIVATE_FILE.with(|slot| drop(slot.borrow_mut().take()));
        CONSUMING.with(|slot| drop(slot.borrow_mut().take()));
        AFTER_AUTHENTICATION.with(|slot| drop(slot.borrow_mut().take()));
        COPY_BLOCK.with(|slot| drop(slot.borrow_mut().take()));
        AFTER_BINDING.with(|slot| drop(slot.borrow_mut().take()));
    }
}

#[test]
fn checkpoint_scope_releases_pending_and_consuming_owners_on_error_and_unwind() -> Result<()> {
    for unwind in [false, true] {
        let (_root, job) = fixture(b"id,value\n0,0007\n")?;
        let pool = pool();
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let baseline = pool.usage().reserved_bytes;
        let owner = std::rc::Rc::new(());
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<()> {
            let _checkpoints = Checkpoints::new();
            let mut held = Reservation::new(&ctx);
            held.resize(123)?;
            let captured = owner.clone();
            CONSUMING.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move |_| {
                    let _ = (&held, &captured);
                    panic!("checkpoint guard unwind control");
                }));
            });
            for slot in [&BEFORE_PRIVATE_FILE, &AFTER_AUTHENTICATION, &AFTER_BINDING] {
                let captured = owner.clone();
                slot.with(|slot| {
                    *slot.borrow_mut() = Some(Box::new(move || drop(captured)));
                });
            }
            let captured = owner.clone();
            COPY_BLOCK.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move |_| drop(captured)));
            });
            if unwind {
                consuming(0);
            }
            anyhow::bail!("checkpoint guard early error control")
        }));
        if unwind {
            assert!(result.is_err());
        } else {
            assert!(result.unwrap().is_err());
        }
        assert_eq!(std::rc::Rc::strong_count(&owner), 1);
        assert_eq!(pool.usage().reserved_bytes, baseline);
        BEFORE_PRIVATE_FILE.with(|slot| assert!(slot.borrow().is_none()));
        CONSUMING.with(|slot| assert!(slot.borrow().is_none()));
        AFTER_AUTHENTICATION.with(|slot| assert!(slot.borrow().is_none()));
        COPY_BLOCK.with(|slot| assert!(slot.borrow().is_none()));
        AFTER_BINDING.with(|slot| assert!(slot.borrow().is_none()));
        drop(ctx);
        clean(&job, &pool);
    }
    Ok(())
}

pub(super) fn after_binding() {
    let checkpoint = AFTER_BINDING.with(|slot| slot.borrow_mut().take());
    if let Some(checkpoint) = checkpoint {
        checkpoint();
    }
}

pub(super) fn before_private_file() {
    let checkpoint = BEFORE_PRIVATE_FILE.with(|slot| slot.borrow_mut().take());
    if let Some(checkpoint) = checkpoint {
        checkpoint();
    }
}

pub(super) fn after_authentication() {
    let checkpoint = AFTER_AUTHENTICATION.with(|slot| slot.borrow_mut().take());
    if let Some(checkpoint) = checkpoint {
        checkpoint();
    }
}
pub(super) fn copy_block(count: u64) {
    let checkpoint = COPY_BLOCK.with(|slot| slot.borrow_mut().take());
    if let Some(checkpoint) = checkpoint {
        checkpoint(count);
    }
}

#[test]
fn artifact_header_changed_after_binding_is_rejected_before_publication() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let _checkpoints = Checkpoints::new();
        let source = b"id,value\n0,0007\n1,null\n";
        let (root, job) = fixture(source)?;
        let pool = pool();
        let cache = root.path().join("cache");
        drop(create_at(&job, &cache, format, pool.clone())?);
        clean(&job, &pool);
        let artifact = cache.join("records.bin");
        let original = std::fs::read(&artifact)?;
        let manifest = std::fs::read(cache.join("manifest.json"))?;
        let matches: Vec<_> = original
            .windows(5)
            .enumerate()
            .filter_map(|(i, bytes)| (bytes == b"value").then_some(i))
            .collect();
        assert_eq!(matches.len(), 1, "unique header payload for {format:?}");
        let mut changed = original.clone();
        changed[matches[0]..matches[0] + 5].copy_from_slice(b"other");
        let local_evidence = tempfile::tempdir()?;
        let evidence = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
            .map(PathBuf::from)
            .unwrap_or_else(|| local_evidence.path().to_owned())
            .join(root.path().file_name().unwrap())
            .join(format!("{format:?}"));
        std::fs::create_dir_all(evidence.parent().unwrap())?;
        std::fs::create_dir(&evidence)?;
        std::fs::write(evidence.join("input.csv"), source)?;
        std::fs::write(evidence.join("manifest.json"), &manifest)?;
        std::fs::write(evidence.join("records-original.bin"), &original)?;
        std::fs::write(evidence.join("records-changed.bin"), &changed)?;
        let changed_hash = blake3::hash(&changed).to_hex().to_string();
        let original_hash = blake3::hash(&original).to_hex().to_string();
        let hook_artifact = artifact.clone();
        AFTER_BINDING.with(|slot| {
            assert!(slot.borrow().is_none());
            *slot.borrow_mut() = Some(Box::new(move || {
                std::fs::write(hook_artifact, changed).unwrap();
            }));
        });
        let result = prepared(job.clone(), Some(&cache), pool.clone());
        AFTER_BINDING.with(|slot| assert!(slot.borrow().is_none(), "checkpoint reached"));
        let rejected = result.is_err();
        let observation = match &result {
            Ok(prepared) => {
                let (bytes, metadata) = identity(prepared)?;
                std::fs::write(evidence.join("unexpected-prepared.csv"), bytes)?;
                serde_json::json!({"accepted_metadata": metadata})
            }
            Err(error) => serde_json::json!({"error": format!("{error:#}")}),
        };
        drop(result);
        clean(&job, &pool);
        assert_eq!(std::fs::read(&job.input)?, source);
        assert_eq!(std::fs::read(cache.join("manifest.json"))?, manifest);
        assert_eq!(
            blake3::hash(&std::fs::read(&artifact)?).to_hex().as_str(),
            changed_hash
        );
        assert!(!cache.join("source.partial").exists());
        assert!(!cache.join("manifest.partial").exists());
        let observation = serde_json::json!({
            "format": format, "rejected": rejected, "observation": observation,
            "original_artifact_blake3": original_hash,
            "changed_artifact_blake3": changed_hash,
            "source_blake3": blake3::hash(source).to_hex().to_string(),
            "manifest_blake3": blake3::hash(&manifest).to_hex().to_string(),
            "header_offset": matches[0], "pool_after_drop": pool.usage().reserved_bytes,
            "temp_entries_after_drop": 0, "output_exists": false,
            "completed_cache_preserved": true
        });
        std::fs::write(
            evidence.join("observation.json"),
            serde_json::to_vec_pretty(&observation)?,
        )?;
        eprintln!("{observation}");
        assert!(
            rejected,
            "{format:?}: changed artifact header was accepted after binding validation"
        );
    }
    Ok(())
}

fn fixture(bytes: &[u8]) -> Result<(tempfile::TempDir, Job)> {
    let root = tempfile::tempdir()?;
    let input = root.path().join("input.csv");
    let temp = root.path().join("temp");
    std::fs::create_dir(&temp)?;
    std::fs::write(&input, bytes)?;
    let job = Job {
        input: input.to_string_lossy().into(),
        output: root.path().join("output").to_string_lossy().into(),
        seed: Some("direct-input-test-v1".into()),
        resources: Resources {
            memory_mb: 32,
            workers: 1,
            max_record_bytes: 1048576,
            temp_dir: Some(temp.to_string_lossy().into()),
            ..Default::default()
        },
        limits: Limits {
            rows: Some(5),
            bytes: Some(2048),
            ..Default::default()
        },
        ..Default::default()
    };
    Ok((root, job))
}
fn pool() -> Arc<crate::resources::MemoryPool> {
    Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024))
}
fn create_at(
    job: &Job,
    path: &Path,
    format: Format,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Created> {
    create(
        job,
        path,
        format,
        32 * 1024 * 1024,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool,
    )
}
fn prepared(
    job: Job,
    path: Option<&Path>,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Prepared> {
    let cancel = Arc::new(AtomicBool::new(false));
    let notify: Notify = Arc::new(|_| {});
    match path {
        Some(path) => prepare(job, path, cancel, notify, pool),
        None => super::super::prepare_with_memory_pool(job, cancel, notify, pool),
    }
}
fn identity(prepared: &Prepared) -> Result<(Vec<u8>, serde_json::Value)> {
    let mut bytes = Vec::new();
    prepared
        .output_plan
        .data
        .reader()?
        .read_to_end(&mut bytes)?;
    Ok((
        bytes,
        serde_json::json!([
            prepared.analysis.rows,
            prepared.analysis.columns,
            prepared.analysis.header,
            prepared.analysis.logical_digest,
            prepared.analysis.groups,
            prepared.analysis.output_files,
            prepared.analysis.output_csv_bytes,
            prepared.analysis.stages
        ]),
    ))
}
fn clean(job: &Job, pool: &crate::resources::MemoryPool) {
    assert_eq!(pool.usage().reserved_bytes, 0);
    assert_eq!(
        std::fs::read_dir(job.resources.temp_dir.as_ref().unwrap())
            .unwrap()
            .count(),
        0
    );
    assert!(!Path::new(&job.output).exists());
}

#[test]
fn direct_readers_match_csv_text_scopes_caps_and_header_conventions() -> Result<()> {
    let values = [
        "",
        "0007",
        "null",
        "NA",
        "2026-10-20",
        "界\0\n\"\\",
        " ",
        "a,b",
    ];
    let mut source = chopper_core::csv::serialize(
        &["id".into(), "key".into(), "same".into(), "same".into()],
        &Default::default(),
    )?;
    for i in 0..64 {
        source.extend(chopper_core::csv::serialize(
            &[
                i.to_string(),
                (i % 4).to_string(),
                values[i % values.len()].into(),
                values[(i + 1) % values.len()].into(),
            ],
            &Default::default(),
        )?);
    }
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let (root, mut job) = fixture(&source)?;
        let pool = pool();
        let cache = root.path().join("cache");
        create_at(&job, &cache, format, pool.clone())?;
        for operations in [
            vec![],
            vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
                Operation::Balanced { files: 4 },
            ],
        ] {
            job.operations = operations;
            for encoding in ["utf-8", "utf-16le"] {
                job.output_csv.encoding = encoding.into();
                let baseline = prepared(job.clone(), None, pool.clone())?;
                let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
                assert_eq!(
                    identity(&candidate)?,
                    identity(&baseline)?,
                    "{format:?}/{encoding}"
                );
                drop(candidate);
                drop(baseline);
                clean(&job, &pool);
            }
        }
    }
    for (source, headers) in [
        (b"".as_slice(), true),
        (b"left,right\n", true),
        (b"1,0007\n2,null\n", false),
        (b",\n0007,null\n", true),
    ] {
        for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
            let (root, mut job) = fixture(source)?;
            job.input_csv.headers = headers;
            job.output_csv.headers = headers;
            let pool = pool();
            let cache = root.path().join("cache");
            create_at(&job, &cache, format, pool.clone())?;
            let baseline = prepared(job.clone(), None, pool.clone())?;
            let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
            assert_eq!(
                identity(&candidate)?,
                identity(&baseline)?,
                "{format:?}/{headers}/{source:?}"
            );
            drop(candidate);
            drop(baseline);
            clean(&job, &pool);
        }
    }
    Ok(())
}

#[test]
fn binding_rejects_changed_source_settings_and_artifact_without_removing_cache() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let (root, job) = fixture(b"id,value\n0,0007\n1,null\n")?;
        let pool = pool();
        let cache = root.path().join("cache");
        create_at(&job, &cache, format, pool.clone())?;
        let original = std::fs::read(&job.input)?;
        std::fs::write(&job.input, b"id,value\n0,0008\n1,null\n")?;
        assert!(format!(
            "{:#}",
            prepared(job.clone(), Some(&cache), pool.clone())
                .err()
                .unwrap()
        )
        .contains("source changed"));
        std::fs::write(&job.input, &original)?;
        let mut changed = job.clone();
        changed.input_csv.skip_empty_lines = true;
        assert!(format!(
            "{:#}",
            prepared(changed, Some(&cache), pool.clone()).err().unwrap()
        )
        .contains("settings/member changed"));
        let path = cache.join("records.bin");
        let mut bytes = std::fs::read(&path)?;
        bytes[0] ^= 1;
        std::fs::write(&path, bytes)?;
        assert!(format!(
            "{:#}",
            prepared(job.clone(), Some(&cache), pool.clone())
                .err()
                .unwrap()
        )
        .contains("artifact changed"));
        assert!(cache.join("manifest.json").exists());
        clean(&job, &pool);
    }
    Ok(())
}

#[test]
fn conversion_denial_cancellation_and_existing_paths_keep_ownership_clean() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let (root, job) = fixture(b"id,value\n0,0007\n1,null\n")?;
        let pool = pool();
        let cache = root.path().join("cache");
        assert!(create(
            &job,
            &cache,
            format,
            1,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone()
        )
        .is_err());
        assert!(!cache.exists());
        clean(&job, &pool);
        assert!(create(
            &job,
            &cache,
            format,
            1000000,
            Arc::new(AtomicBool::new(true)),
            Arc::new(|_| {}),
            pool.clone()
        )
        .is_err());
        assert!(!cache.exists());
        clean(&job, &pool);
        let denied = Arc::new(crate::resources::MemoryPool::new(512 * 1024));
        assert!(create_at(&job, &cache, format, denied.clone()).is_err());
        assert!(!cache.exists());
        clean(&job, &denied);
        let created = create_at(&job, &cache, format, pool.clone())?;
        let manifest_bytes = std::fs::metadata(cache.join("manifest.json"))?.len();
        assert_eq!(
            created.peak_snapshot_bytes,
            created.artifact_bytes + created.source_bytes.max(manifest_bytes)
        );
        assert!(!cache.join("source.partial").exists());
        assert_eq!(
            pool.usage().reserved_bytes,
            created.diagnostics.reserved_bytes()
        );
        let peak_snapshot_bytes = created.peak_snapshot_bytes;
        drop(created);
        assert_eq!(pool.usage().reserved_bytes, 0);
        std::fs::remove_dir_all(&cache)?;
        assert!(create(
            &job,
            &cache,
            format,
            peak_snapshot_bytes - 1,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone()
        )
        .is_err());
        assert!(!cache.exists());
        clean(&job, &pool);
        std::fs::create_dir(&cache)?;
        std::fs::write(cache.join("keep"), b"owned by caller")?;
        assert!(create_at(&job, &cache, format, pool.clone()).is_err());
        assert_eq!(std::fs::read(cache.join("keep"))?, b"owned by caller");
        clean(&job, &pool);
    }
    Ok(())
}

fn replace_artifact(cache: &Path, bytes: &[u8]) -> Result<()> {
    std::fs::write(cache.join("records.bin"), bytes)?;
    let mut manifest: Manifest =
        serde_json::from_slice(&std::fs::read(cache.join("manifest.json"))?)?;
    manifest.artifact_bytes = bytes.len() as u64;
    manifest.artifact_blake3 = blake3::hash(bytes).to_hex().to_string();
    std::fs::write(cache.join("manifest.json"), serde_json::to_vec(&manifest)?)?;
    Ok(())
}
#[test]
fn malformed_lengths_utf8_and_logical_bindings_fail_before_publication() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let (root, job) = fixture(b"id,value\n0,0007\n1,null\n")?;
        let pool = pool();
        let cache = root.path().join("cache");
        create_at(&job, &cache, format, pool.clone())?;
        let original = std::fs::read(cache.join("records.bin"))?;
        let mut bytes = original.clone();
        match format {
            Format::CompactRowsV1 => bytes[16..20].copy_from_slice(&u32::MAX.to_le_bytes()),
            Format::ArrowIpcV1 => {
                let end = bytes.len() - 10;
                bytes[end..end + 4].copy_from_slice(&u32::MAX.to_le_bytes());
            }
        }
        replace_artifact(&cache, &bytes)?;
        assert!(prepared(job.clone(), Some(&cache), pool.clone()).is_err());
        clean(&job, &pool);
        if format == Format::CompactRowsV1 {
            let mut bytes = original.clone();
            bytes[36] = 255;
            replace_artifact(&cache, &bytes)?;
            assert!(format!(
                "{:#}",
                prepared(job.clone(), Some(&cache), pool.clone())
                    .err()
                    .unwrap()
            )
            .contains("UTF-8"));
            clean(&job, &pool);
        }
        replace_artifact(&cache, &original)?;
        let mut manifest: Manifest =
            serde_json::from_slice(&std::fs::read(cache.join("manifest.json"))?)?;
        manifest.logical_digest = "00".repeat(32);
        std::fs::write(cache.join("manifest.json"), serde_json::to_vec(&manifest)?)?;
        assert!(format!(
            "{:#}",
            prepared(job.clone(), Some(&cache), pool.clone())
                .err()
                .unwrap()
        )
        .contains("logical records"));
        clean(&job, &pool);
    }
    Ok(())
}

#[test]
fn conversion_binds_the_immutable_bytes_parsed_even_if_source_changes_and_reverts() -> Result<()> {
    let count = 150000;
    let mut source = String::from("id,value\n");
    for i in 0..count {
        source.push_str(&format!("{i:06},x\n"));
    }
    let (root, mut job) = fixture(source.as_bytes())?;
    job.limits.rows = Some(1000000);
    job.limits.bytes = Some(10000000);
    let pool = pool();
    let baseline = prepared(job.clone(), None, pool.clone())?;
    let expected = baseline.analysis.logical_digest.clone();
    drop(baseline);
    let input = job.input.clone();
    let notify: Notify = Arc::new(move |progress| {
        if progress.phase == "Creating parsed input snapshot"
            && [65536, 131072].contains(&progress.rows)
        {
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .open(&input)
                .unwrap();
            file.seek(SeekFrom::Start(9 + 90000 * 9 + 7)).unwrap();
            file.write_all(if progress.rows == 65536 { b"z" } else { b"x" })
                .unwrap();
        }
    });
    let cache = root.path().join("cache");
    create(
        &job,
        &cache,
        Format::CompactRowsV1,
        32 * 1024 * 1024,
        Arc::new(AtomicBool::new(false)),
        notify,
        pool.clone(),
    )?;
    assert_eq!(std::fs::read(&job.input)?, source.as_bytes());
    let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
    assert_eq!(
        candidate.analysis.logical_digest, expected,
        "snapshot consumed mutable source bytes between matching before/after hashes"
    );
    drop(candidate);
    assert_eq!(pool.usage().reserved_bytes, expected.reserved_bytes());
    drop(expected);
    clean(&job, &pool);
    Ok(())
}

#[test]
fn late_conversion_cancel_and_output_cap_failure_leave_no_publishable_job() -> Result<()> {
    let mut source = String::from("id,value\n");
    for i in 0..70000 {
        source.push_str(&format!("{i},x\n"));
    }
    let (root, job) = fixture(source.as_bytes())?;
    let pool = pool();
    let cache = root.path().join("cache");
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    let error = create(
        &job,
        &cache,
        Format::CompactRowsV1,
        32000000,
        cancel,
        Arc::new(move |p| {
            if p.rows >= 65536 {
                signal.store(true, Ordering::Relaxed);
            }
        }),
        pool.clone(),
    )
    .err()
    .unwrap();
    assert!(format!("{error:#}").contains("cancel"));
    assert!(!cache.exists());
    clean(&job, &pool);
    create_at(&job, &cache, Format::CompactRowsV1, pool.clone())?;
    let mut limited = job.clone();
    limited.limits.bytes = Some(1);
    assert!(prepared(limited, Some(&cache), pool.clone()).is_err());
    assert!(cache.join("manifest.json").exists());
    clean(&job, &pool);
    Ok(())
}

#[test]
fn diagnostic_denial_does_not_commit_snapshot_manifest() -> Result<()> {
    let (root, job) = fixture(
        b"id
1
",
    )?;
    let pool = pool();
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let cache = root.path().join("denied-commit");
    std::fs::create_dir(&cache)?;
    let owner = OwnedDirectory {
        path: AdmittedPath::new(&cache, None, &ctx)?,
        armed: true,
    };
    let completion = AdmittedPath::new(&cache, Some("manifest.json"), &ctx)?;
    let partial = cache.join("manifest.partial");
    std::fs::write(&partial, b"pending manifest")?;
    let held = pool.usage().limit_bytes - pool.usage().reserved_bytes;
    pool.acquire(held)?;
    let result = commit_manifest(&ctx, &partial, &completion.value);
    pool.release(held);
    let error = result
        .err()
        .context("diagnostic commit denial was accepted")?;
    assert!(matches!(
        error.downcast_ref::<crate::resources::MemoryAdmission>(),
        Some(crate::resources::MemoryAdmission::Shared { .. })
    ));
    assert!(
        !cache.join("manifest.json").try_exists()?,
        "diagnostic denial published the completion manifest"
    );
    assert!(partial.is_file());
    drop(owner);
    assert!(!cache.try_exists()?);
    drop(completion);
    drop(ctx);
    clean(&job, &pool);
    Ok(())
}

pub(super) fn consuming(record: u64) {
    CONSUMING.with(|slot| {
        if let Some(callback) = slot.borrow_mut().as_mut() {
            callback(record);
        }
    });
}

fn assert_published_original(job: &Job, original: &[u8]) -> Result<()> {
    let mut csvs = Vec::new();
    fn visit(path: &Path, csvs: &mut Vec<Vec<u8>>) -> Result<()> {
        for entry in std::fs::read_dir(path)? {
            let path = entry?.path();
            if path.is_dir() {
                visit(&path, csvs)?;
            } else if path.extension().is_some_and(|extension| extension == "csv") {
                csvs.push(std::fs::read(path)?);
            }
        }
        Ok(())
    }
    visit(Path::new(&job.output), &mut csvs)?;
    assert_eq!(csvs, vec![original.to_vec()]);
    assert!(Path::new(&job.output).join("manifest.jsonl").is_file());
    Ok(())
}

#[test]
fn authenticated_private_replay_survives_replacement_mutation_and_revert_and_publishes(
) -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        for mode in 0..3 {
            let checkpoints = Checkpoints::new();
            let source = b"id,value\n0,0007\n1,null\n";
            let (root, job) = fixture(source)?;
            let pool = pool();
            let cache = root.path().join("cache");
            drop(create_at(&job, &cache, format, pool.clone())?);
            let baseline = prepared(job.clone(), None, pool.clone())?;
            let expected = identity(&baseline)?;
            drop(baseline);
            clean(&job, &pool);
            let path = cache.join("records.bin");
            let original = std::fs::read(&path)?;
            let manifest = std::fs::read(cache.join("manifest.json"))?;
            let mut changed = original.clone();
            for (needle, replacement) in [
                (b"value".as_slice(), b"other".as_slice()),
                (b"0007".as_slice(), b"9999".as_slice()),
            ] {
                let offsets: Vec<_> = original
                    .windows(needle.len())
                    .enumerate()
                    .filter_map(|(i, b)| (b == needle).then_some(i))
                    .collect();
                assert_eq!(offsets.len(), 1);
                changed[offsets[0]..offsets[0] + needle.len()].copy_from_slice(replacement);
            }
            if mode < 2 {
                let path = path.clone();
                let changed = changed.clone();
                AFTER_AUTHENTICATION.with(|slot| {
                    *slot.borrow_mut() = Some(Box::new(move || {
                        if mode == 0 {
                            // Cross-platform replacement after the private authentication.
                            let moved = path.with_extension("caller-original");
                            std::fs::rename(&path, moved).unwrap();
                        }
                        std::fs::write(path, changed).unwrap();
                    }))
                });
            } else {
                let path = path.clone();
                let changed = changed.clone();
                let original = original.clone();
                CONSUMING.with(|slot| {
                    *slot.borrow_mut() = Some(Box::new(move |record| {
                        if record == 0 {
                            std::fs::write(&path, &changed).unwrap();
                        }
                        if record == 2 {
                            std::fs::write(&path, &original).unwrap();
                        }
                    }))
                });
            }
            let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
            drop(checkpoints);
            assert_eq!(identity(&candidate)?, expected, "{format:?}/mode{mode}");
            let analysis_owner = candidate.analysis.clone();
            let diagnostic_owner = candidate.analysis.diagnostics.clone();
            let result = candidate.execute()?;
            assert_published_original(&job, source)?;
            assert_eq!(std::fs::read(cache.join("manifest.json"))?, manifest);
            assert_eq!(
                std::fs::read(&path)?,
                if mode == 2 { original } else { changed }
            );
            drop(result);
            drop(analysis_owner);
            assert_eq!(
                pool.usage().reserved_bytes,
                diagnostic_owner.reserved_bytes()
            );
            drop(diagnostic_owner);
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert_eq!(
                std::fs::read_dir(job.resources.temp_dir.as_ref().unwrap())?.count(),
                0
            );
        }
    }
    Ok(())
}

#[test]
fn private_copy_disk_edges_and_memory_denial_retry_preserve_cache() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        let (root, job) = fixture(b"id,value\n0,0007\n1,null\n")?;
        let pool = pool();
        let cache = root.path().join("cache");
        drop(create_at(&job, &cache, format, pool.clone())?);
        let artifact = std::fs::read(cache.join("records.bin"))?;
        std::fs::write(cache.join("keep"), b"caller sentinel")?;
        for delta in [-1i64, 0, 1] {
            let mut resources = job.resources.clone();
            resources.temp_bytes = Some((artifact.len() as i64 + delta) as u64);
            let ctx = Context::with_memory_pool(
                &resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let manifest = binding(&cache, &job, &ctx)?;
            let result = authenticated_artifact(&cache, &manifest, &ctx);
            assert_eq!(result.is_ok(), delta >= 0, "{format:?}/disk{delta}");
            if let Ok(file) = &result {
                assert_eq!(file.len(), artifact.len() as u64);
                assert_eq!(ctx.used(), file.len());
            }
            drop(result);
            assert_eq!(ctx.used(), 0);
            drop(manifest);
            drop(ctx);
            clean(&job, &pool);
        }
        for shared in [false, true] {
            let _checkpoints = Checkpoints::new();
            let ctx = Context::with_memory_pool(
                &job.resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let manifest = binding(&cache, &job, &ctx)?;
            let scratch = 65536 + std::mem::size_of::<blake3::Hasher>();
            // Leave insufficient capacity first for scratch, then for the admitted path.
            for slack in [scratch - 1, scratch] {
                let used = ctx.diagnostics()["workspace_reserved_bytes"]
                    .as_u64()
                    .unwrap();
                let held_bytes = if shared {
                    pool.usage().limit_bytes - pool.usage().reserved_bytes - slack as u64
                } else {
                    ctx.memory as u64 / 2 - used - slack as u64
                };
                let mut held = Reservation::new(&ctx);
                if shared {
                    pool.acquire(held_bytes)?;
                } else {
                    held.resize(held_bytes as usize)?;
                }
                let before = pool.usage().reserved_bytes;
                let error = authenticated_artifact(&cache, &manifest, &ctx)
                    .err()
                    .context("copy memory denial accepted")?;
                assert!(matches!(
                    (
                        shared,
                        error.downcast_ref::<crate::resources::MemoryAdmission>()
                    ),
                    (true, Some(crate::resources::MemoryAdmission::Shared { .. }))
                        | (false, Some(crate::resources::MemoryAdmission::Local))
                ));
                assert_eq!(pool.usage().reserved_bytes, before);
                assert_eq!(ctx.used(), 0);
                if shared {
                    pool.release(held_bytes);
                } else {
                    drop(held);
                }
                let retry = authenticated_artifact(&cache, &manifest, &ctx)?;
                drop(retry);
                assert_eq!(ctx.used(), 0);
            }
            let owner = std::rc::Rc::new(std::cell::RefCell::new(None::<Reservation>));
            let retained = owner.clone();
            let context = ctx.clone();
            let process_pool = pool.clone();
            let shared_held = std::rc::Rc::new(std::cell::Cell::new(0u64));
            let held_count = shared_held.clone();
            BEFORE_PRIVATE_FILE.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move || {
                    if shared {
                        let bytes =
                            process_pool.usage().limit_bytes - process_pool.usage().reserved_bytes;
                        process_pool.acquire(bytes).unwrap();
                        held_count.set(bytes);
                    } else {
                        let used = context.diagnostics()["workspace_reserved_bytes"]
                            .as_u64()
                            .unwrap();
                        let mut held = Reservation::new(&context);
                        held.resize(context.memory / 2 - used as usize).unwrap();
                        *retained.borrow_mut() = Some(held);
                    }
                }))
            });
            let error = authenticated_artifact(&cache, &manifest, &ctx)
                .err()
                .context("private file path denial accepted")?;
            assert!(matches!(
                (
                    shared,
                    error.downcast_ref::<crate::resources::MemoryAdmission>()
                ),
                (true, Some(crate::resources::MemoryAdmission::Shared { .. }))
                    | (false, Some(crate::resources::MemoryAdmission::Local))
            ));
            owner.borrow_mut().take();
            if shared {
                pool.release(shared_held.get());
            }
            let retry = authenticated_artifact(&cache, &manifest, &ctx)?;
            drop(retry);
            assert_eq!(ctx.used(), 0);
            drop(manifest);
            drop(ctx);
            clean(&job, &pool);
        }
        assert_eq!(std::fs::read(cache.join("records.bin"))?, artifact);
        assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
    }
    Ok(())
}

#[test]
fn private_replay_cancellation_boundaries_cleanup_and_postcommit_success() -> Result<()> {
    let mut source = String::from("id,value\n");
    for i in 0..8192 {
        source.push_str(&format!("{i},0007\n"));
    }
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        for boundary in 0..5 {
            let checkpoints = Checkpoints::new();
            let (root, mut job) = fixture(source.as_bytes())?;
            job.limits.rows = Some(10000);
            job.limits.bytes = Some(1000000);
            let pool = pool();
            let cache = root.path().join("cache");
            drop(create_at(&job, &cache, format, pool.clone())?);
            let artifact = std::fs::read(cache.join("records.bin"))?;
            let cancel = Arc::new(AtomicBool::new(false));
            let signal = cancel.clone();
            match boundary {
                0 => COPY_BLOCK.with(|slot| {
                    let length = artifact.len() as u64;
                    *slot.borrow_mut() = Some(Box::new(move |copied| {
                        assert!(copied > 0 && copied < length, "mid-copy checkpoint");
                        signal.store(true, Ordering::Relaxed);
                    }))
                }),
                1 => AFTER_AUTHENTICATION.with(|slot| {
                    *slot.borrow_mut() = Some(Box::new(move || {
                        signal.store(true, Ordering::Relaxed);
                    }))
                }),
                2 => CONSUMING.with(|slot| {
                    *slot.borrow_mut() = Some(Box::new(move |record| {
                        if record == 1 {
                            signal.store(true, Ordering::Relaxed);
                        }
                    }))
                }),
                _ => (),
            }
            let signal = cancel.clone();
            let notify: Notify = Arc::new(move |progress| {
                if boundary == 4 && progress.phase == "Complete" {
                    signal.store(true, Ordering::Relaxed);
                }
            });
            let result = prepare(job.clone(), &cache, cancel.clone(), notify, pool.clone());
            drop(checkpoints);
            if boundary < 3 {
                assert!(
                    format!("{:#}", result.err().context("cancelled prepare accepted")?)
                        .contains("cancel")
                );
                clean(&job, &pool);
            } else {
                let ready = result?;
                if boundary == 3 {
                    cancel.store(true, Ordering::Relaxed);
                }
                let result = ready.execute();
                if boundary == 3 {
                    assert!(result.is_err());
                    clean(&job, &pool);
                } else {
                    drop(result?);
                    assert!(cancel.load(Ordering::Relaxed));
                    assert_published_original(&job, source.as_bytes())?;
                    assert_eq!(pool.usage().reserved_bytes, 0);
                    assert_eq!(
                        std::fs::read_dir(job.resources.temp_dir.as_ref().unwrap())?.count(),
                        0
                    );
                }
            }
            assert_eq!(std::fs::read(cache.join("records.bin"))?, artifact);
            assert!(cache.join("manifest.json").is_file());
        }
    }
    Ok(())
}

// Sequential gate: a failure unwinds immediately before the next control runs.
#[test]
fn authenticated_replay_focused_gates() -> Result<()> {
    artifact_header_changed_after_binding_is_rejected_before_publication()?;
    authenticated_private_replay_survives_replacement_mutation_and_revert_and_publishes()?;
    private_copy_disk_edges_and_memory_denial_retry_preserve_cache()?;
    private_replay_cancellation_boundaries_cleanup_and_postcommit_success()?;
    Ok(())
}

fn sample_manifest() -> Manifest {
    Manifest {
        version: 1,
        format: Format::CompactRowsV1,
        source_blake3: "0".repeat(64),
        settings_blake3: "1".repeat(64),
        artifact_blake3: "2".repeat(64),
        logical_digest: "3".repeat(64),
        source_bytes: 5,
        artifact_bytes: 64,
        records: 2,
        data_rows: 1,
        columns: 1,
        headers: true,
        maximum_record_bytes: 1048576,
    }
}
fn construction_seam(seam: usize, job: &Job, path: &Path, ctx: &Context) -> Result<()> {
    match seam {
        0 => {
            let owner = FrozenJob::new(job, path, ctx)?;
            assert_eq!(
                owner._grant.bytes(),
                job_owner::capacity(&owner.value)? as u64
            );
            assert_eq!(owner.value.input, path.to_string_lossy());
            assert_eq!(owner.value.zip_member, job.zip_member);
        }
        1 => {
            let owner = AdmittedPath::new(path, Some("manifest.json"), ctx)?;
            assert_eq!(owner.value, path.join("manifest.json"));
            assert_eq!(owner._grant.bytes(), owner.value.capacity() as u64);
        }
        2 => {
            let mut grant = Reservation::new(ctx);
            let settings = clone_parser_settings(job, &mut grant)?;
            assert_eq!(
                grant.bytes(),
                (settings.encoding.capacity() + settings.line_ending.capacity()) as u64
            );
        }
        3 => {
            let mut grant = Reservation::new(ctx);
            grant.resize(4 * 64)?;
            let hashes = [
                blake3::hash(b"a"),
                blake3::hash(b"b"),
                blake3::hash(b"c"),
                blake3::hash(b"d"),
            ];
            let text = hashes.map(|h| h.to_hex().to_string());
            assert!(text.iter().all(|s| s.capacity() == 64));
            assert_eq!(
                text.iter().map(String::capacity).sum::<usize>() as u64,
                grant.bytes()
            );
        }
        4 => {
            let input = serde_json::to_vec(&sample_manifest())?;
            let owner = decode_manifest(input.as_slice(), ctx)?;
            assert_eq!(owner._grant.bytes(), 256);
            assert_eq!(owner.string_capacity(), 256);
        }
        5 => {
            let manifest = sample_manifest();
            let output = encode_manifest(&manifest, ctx)?;
            assert_eq!(output.value.capacity(), MAX_MANIFEST);
            let decoded: Manifest = serde_json::from_slice(&output.value)?;
            assert_eq!(decoded.logical_digest, manifest.logical_digest);
        }
        _ => unreachable!(),
    }
    Ok(())
}
#[test]
fn manifest_construction_admission_edges_and_last_owner_release() -> Result<()> {
    let (_root, mut job) = fixture(b"id\n1\n")?;
    job.zip_member = Some("selected/\u{754c}/member.csv".repeat(12));
    job.input.reserve(1024);
    let text = format!("a/{}/\u{1f600}/source.partial", "\u{754c}".repeat(40));
    let path = Path::new(&text);
    for seam in 0..6 {
        let measure = pool();
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            measure.clone(),
        )?;
        let base = measure.usage().reserved_bytes;
        construction_seam(seam, &job, path, &ctx)?;
        let required = measure.usage().peak_reserved_bytes - base;
        assert!(required > 0);
        assert_eq!(measure.usage().reserved_bytes, base);
        drop(ctx);
        clean(&job, &measure);
        eprintln!("construction seam={seam} observed required={required}");
        for shared in [false, true] {
            for delta in [-1i64, 0, 1] {
                let pool = pool();
                let ctx = Context::with_memory_pool(
                    &job.resources,
                    Arc::new(AtomicBool::new(false)),
                    Arc::new(|_| {}),
                    pool.clone(),
                )?;
                let base = pool.usage().reserved_bytes;
                let local = ctx.diagnostics()["workspace_reserved_bytes"]
                    .as_u64()
                    .unwrap();
                let available = (required as i64 + delta) as u64;
                let hold = if shared {
                    pool.usage().limit_bytes - base - available
                } else {
                    ctx.memory as u64 / 2 - local - available
                };
                let mut held = Reservation::new(&ctx);
                if shared {
                    pool.acquire(hold)?;
                } else {
                    held.resize(hold as usize)?;
                }
                let before = pool.usage().reserved_bytes;
                let result = construction_seam(seam, &job, path, &ctx);
                assert_eq!(
                    result.is_ok(),
                    delta >= 0,
                    "seam={seam}/shared={shared}/delta={delta}: {result:?}"
                );
                assert_eq!(pool.usage().reserved_bytes, before);
                drop(result);
                if shared {
                    pool.release(hold);
                } else {
                    drop(held);
                }
                construction_seam(seam, &job, path, &ctx)?;
                assert_eq!(pool.usage().reserved_bytes, base);
                drop(ctx);
                clean(&job, &pool);
            }
        }
    }
    let pool = pool();
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let base = pool.usage().reserved_bytes;
    let input = serde_json::to_vec(&sample_manifest())?;
    let owner = Arc::new(decode_manifest(input.as_slice(), &ctx)?);
    let sibling = owner.clone();
    drop(owner);
    assert_eq!(pool.usage().reserved_bytes, base + 256);
    drop(sibling);
    assert_eq!(pool.usage().reserved_bytes, base);
    let mut excessive = sample_manifest();
    excessive.logical_digest = "\u{7f}".repeat(MAX_MANIFEST);
    assert!(encode_manifest(&excessive, &ctx).is_err());
    assert_eq!(pool.usage().reserved_bytes, base);
    drop(ctx);
    clean(&job, &pool);
    Ok(())
}

#[test]
fn manifest_frozen_metadata_and_bounded_read_controls() -> Result<()> {
    let (root, job) = fixture(b"id,value\n0,0007\n1,null\n")?;
    let pool = pool();
    let cache = root.path().join("cache");
    drop(create_at(
        &job,
        &cache,
        Format::CompactRowsV1,
        pool.clone(),
    )?);
    clean(&job, &pool);
    let original = std::fs::read(cache.join("manifest.json"))?;
    let artifact = std::fs::read(cache.join("records.bin"))?;
    std::fs::write(cache.join("keep"), b"caller sentinel")?;
    let mut cases: Vec<(&str, Option<Vec<u8>>, bool)> = vec![("missing-completion", None, false)];
    let mut padded = original.clone();
    padded.resize(MAX_MANIFEST, b' ');
    cases.push(("valid-8192", Some(padded.clone()), true));
    padded.push(b' ');
    cases.push(("invalid-8193", Some(padded), false));
    cases.push((
        "truncated",
        Some(original[..original.len() - 1].to_vec()),
        false,
    ));
    let mut unknown = original[..original.len() - 1].to_vec();
    unknown.extend_from_slice(b",\"unknown\":0}");
    cases.push(("unknown", Some(unknown), false));
    let mut duplicate = original[..original.len() - 1].to_vec();
    duplicate.extend_from_slice(b",\"version\":1}");
    cases.push(("duplicate", Some(duplicate), false));
    for (name, field, replacement) in [
        ("unsupported-version", "version", serde_json::json!(2)),
        (
            "unsupported-format",
            "format",
            serde_json::json!("unknown_v1"),
        ),
        (
            "malformed-digest",
            "source_blake3",
            serde_json::json!("g".repeat(64)),
        ),
        (
            "overlong-digest",
            "logical_digest",
            serde_json::json!("0".repeat(65)),
        ),
        (
            "impossible-counts",
            "data_rows",
            serde_json::json!(u64::MAX),
        ),
        ("header-arithmetic", "records", serde_json::json!(0)),
        ("width-1025", "columns", serde_json::json!(1025)),
        (
            "max-record-incompatible",
            "maximum_record_bytes",
            serde_json::json!(1048577),
        ),
        (
            "settings-mismatch",
            "settings_blake3",
            serde_json::json!("0".repeat(64)),
        ),
    ] {
        // Test-fixture Value is caller-owned, outside production decode.
        let mut value: serde_json::Value = serde_json::from_slice(&original)?;
        value[field] = replacement;
        cases.push((name, Some(serde_json::to_vec(&value)?), false));
    }
    for (name, bytes, accepted) in cases {
        if let Some(bytes) = &bytes {
            std::fs::write(cache.join("manifest.json"), bytes)?;
        } else {
            std::fs::remove_file(cache.join("manifest.json"))?;
        }
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let base = pool.usage().reserved_bytes;
        let result = binding(&cache, &job, &ctx);
        assert_eq!(result.is_ok(), accepted, "metadata {name}");
        if let Ok(owner) = &result {
            assert_eq!(owner._grant.bytes(), owner.string_capacity() as u64);
        }
        drop(result);
        assert_eq!(pool.usage().reserved_bytes, base);
        drop(ctx);
        clean(&job, &pool);
        assert_eq!(std::fs::read(cache.join("records.bin"))?, artifact);
        assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
        assert!(!cache.join("manifest.partial").exists());
        match bytes {
            Some(bytes) => assert_eq!(std::fs::read(cache.join("manifest.json"))?, bytes),
            None => assert!(!cache.join("manifest.json").exists()),
        }
        eprintln!("metadata case {name}: accepted={accepted}");
    }
    std::fs::write(cache.join("manifest.json"), &original)?;
    let mut changed = job.clone();
    changed.zip_member = Some("selected.csv".into());
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    assert!(binding(&cache, &changed, &ctx).is_err());
    drop(ctx);
    clean(&job, &pool);

    struct Chunks<'a> {
        bytes: &'a [u8],
        reads: usize,
        consumed: usize,
    }
    impl Read for Chunks<'_> {
        fn read(&mut self, output: &mut [u8]) -> std::io::Result<usize> {
            self.reads += 1;
            if self.reads == 2 {
                return Err(std::io::ErrorKind::Interrupted.into());
            }
            let n = 7.min(output.len()).min(self.bytes.len());
            output[..n].copy_from_slice(&self.bytes[..n]);
            self.bytes = &self.bytes[n..];
            self.consumed += n;
            Ok(n)
        }
    }
    for length in [MAX_MANIFEST, MAX_MANIFEST + 1] {
        let mut bytes = original.clone();
        bytes.resize(length, b' ');
        let mut chunks = Chunks {
            bytes: &bytes,
            reads: 0,
            consumed: 0,
        };
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let result = decode_manifest(&mut chunks, &ctx);
        assert_eq!(result.is_ok(), length == MAX_MANIFEST);
        assert_eq!(chunks.consumed, length);
        assert!(chunks.reads > 1000);
        drop(result);
        drop(ctx);
        clean(&job, &pool);
    }
    // Valid/rehashed artifact at the supported width isolates the inclusive bound.
    let source = format!(
        "{}\n{}\n",
        (0..1024)
            .map(|i| format!("c{i}"))
            .collect::<Vec<_>>()
            .join(","),
        vec!["x"; 1024].join(",")
    );
    let (wide_root, wide_job) = fixture(source.as_bytes())?;
    let wide_cache = wide_root.path().join("cache");
    drop(create_at(
        &wide_job,
        &wide_cache,
        Format::CompactRowsV1,
        pool.clone(),
    )?);
    let ctx = Context::with_memory_pool(
        &wide_job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let manifest = binding(&wide_cache, &wide_job, &ctx)?;
    assert_eq!(manifest.columns, 1024);
    drop(manifest);
    drop(ctx);
    clean(&wide_job, &pool);
    Ok(())
}
thread_local! {
    static MANIFEST_CAPTURE: std::cell::RefCell<Option<PathBuf>> = const { std::cell::RefCell::new(None) };
}
struct ManifestCapture;
impl ManifestCapture {
    fn new(path: PathBuf) -> Self {
        MANIFEST_CAPTURE.with(|slot| *slot.borrow_mut() = Some(path));
        Self
    }
}
impl Drop for ManifestCapture {
    fn drop(&mut self) {
        MANIFEST_CAPTURE.with(|slot| slot.borrow_mut().take());
    }
}
fn preserve_fixture(directory: &Path, name: &str, bytes: &[u8]) -> Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(directory.join(name))?;
    file.write_all(bytes)?;
    std::fs::write(
        directory.join(format!("{name}.blake3")),
        blake3::hash(bytes).to_hex().as_bytes(),
    )?;
    Ok(())
}
pub(super) fn preserve_created_manifest(bytes: &[u8]) -> Result<()> {
    MANIFEST_CAPTURE.with(|slot| {
        if let Some(path) = slot.borrow().as_ref() {
            preserve_fixture(path, "manifest.json", bytes)?;
        }
        Ok(())
    })
}

#[test]
fn construction_empty_nonempty_unicode_selected_member_both_formats() -> Result<()> {
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        for source in [b"".as_slice(), b"id,value\n0,0007\n"] {
            let (root, mut job) = fixture(source)?;
            let path = root
                .path()
                .join("\u{754c}\u{1f600}-long-input-selected-member.zip");
            let member = "selected/\u{754c}\u{1f600}.csv";
            let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
            zip.start_file(member, zip::write::SimpleFileOptions::default())?;
            zip.write_all(source)?;
            zip.start_file("other.csv", zip::write::SimpleFileOptions::default())?;
            zip.write_all(b"ignored\n")?;
            let zip_bytes = zip.finish()?.into_inner();
            let evidence_parent = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
                .map(PathBuf::from)
                .unwrap_or_else(std::env::temp_dir);
            std::fs::create_dir_all(&evidence_parent)?;
            let evidence = tempfile::Builder::new()
                .prefix("selected-member-")
                .tempdir_in(evidence_parent)?
                .keep();
            preserve_fixture(&evidence, "source.csv", source)?;
            preserve_fixture(&evidence, "input.zip", &zip_bytes)?;
            std::fs::write(&path, zip_bytes)?;
            job.input = path.to_string_lossy().into_owned();
            job.zip_member = Some(member.into());
            job.input_csv.line_ending = "crlf".into();
            preserve_fixture(&evidence, "job.json", &serde_json::to_vec(&job)?)?;
            let _capture = ManifestCapture::new(evidence);
            let pool = pool();
            let cache = root.path().join("\u{754c}\u{1f600}-snapshot");
            let created = create_at(&job, &cache, format, pool.clone())?;
            let diagnostic = created.diagnostics.clone();
            drop(created);
            assert_eq!(pool.usage().reserved_bytes, diagnostic.reserved_bytes());
            drop(diagnostic);
            clean(&job, &pool);
            let baseline = prepared(job.clone(), None, pool.clone())?;
            let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
            assert_eq!(identity(&candidate)?, identity(&baseline)?);
            drop(candidate);
            drop(baseline);
            clean(&job, &pool);
        }
    }
    Ok(())
}
#[test]
fn ipc_footer_error_is_static_after_prepare_owners_drop() -> Result<()> {
    let source = b"id,value\n0,0007\n1,null\n";
    let (root, job) = fixture(source)?;
    let pool = pool();
    let cache = root.path().join("cache");
    create_at(&job, &cache, Format::ArrowIpcV1, pool.clone())?;
    std::fs::write(cache.join("keep"), b"caller sentinel")?;
    let original = std::fs::read(cache.join("records.bin"))?;
    let original_manifest = std::fs::read(cache.join("manifest.json"))?;
    let mut mutated = original.clone();
    let footer_length = u32::from_le_bytes(
        mutated[mutated.len() - 10..mutated.len() - 6]
            .try_into()
            .unwrap(),
    ) as usize;
    let footer_start = mutated.len() - 10 - footer_length;
    mutated[footer_start..footer_start + 4].copy_from_slice(&u32::MAX.to_le_bytes());
    let mut manifest: Manifest = serde_json::from_slice(&original_manifest)?;
    manifest.artifact_bytes = mutated.len() as u64;
    manifest.artifact_blake3 = blake3::hash(&mutated).to_hex().to_string();
    let changed_manifest = serde_json::to_vec(&manifest)?;
    let parent = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    std::fs::create_dir_all(&parent)?;
    let evidence = tempfile::Builder::new()
        .prefix("ipc-footer-held-error-")
        .tempdir_in(parent)?
        .keep();
    for (name, bytes) in [
        ("input.csv", source.as_slice()),
        ("original.bin", original.as_slice()),
        ("mutated.bin", mutated.as_slice()),
        ("original-manifest.json", original_manifest.as_slice()),
        ("mutated-manifest.json", changed_manifest.as_slice()),
        ("job.json", serde_json::to_vec(&job)?.as_slice()),
    ] {
        preserve_fixture(&evidence, name, bytes)?;
    }
    assert_ne!(original, mutated);
    assert_eq!(
        u32::from_le_bytes(mutated[footer_start..footer_start + 4].try_into().unwrap()),
        u32::MAX
    );
    assert!(u32::MAX as usize > mutated.len());
    std::fs::write(cache.join("records.bin"), &mutated)?;
    std::fs::write(cache.join("manifest.json"), &changed_manifest)?;
    let error = match prepared(job.clone(), Some(&cache), pool.clone()) {
        Err(error) => error,
        Ok(unexpected) => {
            let exported = identity(&unexpected);
            match &exported {
                Ok((bytes, metadata)) => {
                    preserve_fixture(&evidence, "unexpected-prepared.bin", bytes)?;
                    preserve_fixture(
                        &evidence,
                        "unexpected-metadata.json",
                        &serde_json::to_vec(metadata)?,
                    )?;
                }
                Err(error) => preserve_fixture(
                    &evidence,
                    "unexpected-export-error.txt",
                    format!("{error:#}").as_bytes(),
                )?,
            }
            drop(unexpected);
            clean(&job, &pool);
            assert_eq!(std::fs::read(cache.join("records.bin"))?, mutated);
            assert_eq!(
                std::fs::read(cache.join("manifest.json"))?,
                changed_manifest
            );
            assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
            panic!("malformed footer accepted; export and cleanup preserved");
        }
    };
    // prepare has returned: every job/context/decoder owner is gone while error lives.
    assert_eq!(error.to_string(), "invalid IPC footer verification");
    clean(&job, &pool);
    assert_eq!(std::fs::read(cache.join("records.bin"))?, mutated);
    assert_eq!(
        std::fs::read(cache.join("manifest.json"))?,
        changed_manifest
    );
    assert_eq!(std::fs::read(cache.join("keep"))?, b"caller sentinel");
    preserve_fixture(&evidence, "held-error.txt", error.to_string().as_bytes())?;
    drop(error);
    clean(&job, &pool);
    Ok(())
}
mod decoder_gates;
pub(super) mod lifecycle;
