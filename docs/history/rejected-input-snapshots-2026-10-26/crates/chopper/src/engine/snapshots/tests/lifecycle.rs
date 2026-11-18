use super::*;
use std::{cell::RefCell, rc::Rc};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(in crate::engine::snapshots) enum Stage {
    Frozen,
    Row,
    BeforeFinish,
    ManifestPartial,
}
type StageHook = Box<dyn FnMut(Stage)>;
type HashHook = Box<dyn FnMut(&Path, bool, u64, blake3::Hash)>;
type CleanupHook = Box<dyn FnMut(&Path)>;
thread_local! {
    static STAGE: RefCell<Option<StageHook>> = RefCell::new(None);
    static HASH: RefCell<Option<HashHook>> = RefCell::new(None);
    static CLEANUP: RefCell<Option<CleanupHook>> = RefCell::new(None);
    static DENY_CLEANUP: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}
struct Scope;
impl Drop for Scope {
    fn drop(&mut self) {
        STAGE.with(|slot| drop(slot.borrow_mut().take()));
        HASH.with(|slot| drop(slot.borrow_mut().take()));
        CLEANUP.with(|slot| drop(slot.borrow_mut().take()));
        DENY_CLEANUP.with(|slot| slot.set(false));
    }
}
pub(in crate::engine::snapshots) fn checkpoint(stage: Stage) {
    STAGE.with(|slot| {
        if let Some(hook) = slot.borrow_mut().as_mut() {
            hook(stage);
        }
    });
}
pub(in crate::engine::snapshots) fn hash_block(
    path: &Path,
    copying: bool,
    count: u64,
    hash: blake3::Hash,
) {
    HASH.with(|slot| {
        if let Some(hook) = slot.borrow_mut().as_mut() {
            hook(path, copying, count, hash);
        }
    });
}
pub(in crate::engine::snapshots) fn before_cleanup(path: &Path) -> std::io::Result<()> {
    CLEANUP.with(|slot| {
        if let Some(hook) = slot.borrow_mut().as_mut() {
            hook(path);
        }
    });
    if DENY_CLEANUP.with(std::cell::Cell::get) {
        return Err(std::io::ErrorKind::PermissionDenied.into());
    }
    Ok(())
}

fn capture(directory: &Path, cache: &Path, label: &str) -> Result<()> {
    std::fs::create_dir_all(directory.join(label))?;
    if cache.exists() {
        for file in std::fs::read_dir(cache)? {
            let file = file?;
            if file.file_type()?.is_dir() {
                capture(
                    &directory.join(label),
                    &file.path(),
                    file.file_name().to_str().unwrap(),
                )?;
            } else {
                assert!(file.file_type()?.is_file());
                std::fs::copy(file.path(), directory.join(label).join(file.file_name()))?;
            }
        }
    }
    Ok(())
}

#[test]
fn deterministic_source_cancellation_and_cleanup_gates() -> Result<()> {
    // Declared selection: .tools/e3-lifecycle-20261025-r17/scenarios.md.
    const CASES: [&str; 12] = [
        "stale",
        "replacement",
        "copy-mutation",
        "revert",
        "hash-transition",
        "copy-cancel",
        "row-cancel",
        "footer-cancel",
        "manifest-cancel",
        "replay-hash-cancel",
        "orphan-source",
        "orphan-partial",
    ];
    let mut original = b"id,value\n".to_vec();
    for _ in 0..1300 {
        original.extend_from_slice(
            b"0001,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
        );
    }
    assert!(original.len() > 65536 && original.len() < 2 * 65536);
    let mut changed = original.clone();
    changed[20] = b'b';
    assert_eq!(original.len(), changed.len());
    assert_ne!(original, changed);
    for format in [Format::CompactRowsV1, Format::ArrowIpcV1] {
        for name in CASES {
            let (root, mut job) = fixture(&original)?;
            if name == "revert" {
                job.limits.rows = Some(1000000);
                job.limits.bytes = Some(1000000);
            }
            let pool = pool();
            let cache = root.path().join("cache");
            let sentinel = root.path().join("unrelated");
            std::fs::write(&sentinel, b"unrelated caller sentinel")?;
            let evidence_root = std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
                .map(PathBuf::from)
                .unwrap_or_else(|| root.path().join("evidence"));
            let evidence = evidence_root.join(format!("lifecycle-{format:?}-{name}"));
            std::fs::create_dir_all(&evidence)?;
            std::fs::write(evidence.join("source-before.csv"), &original)?;
            std::fs::write(evidence.join("source-changed.csv"), &changed)?;
            std::fs::write(
                evidence.join("post-prepared-cache.bin"),
                b"caller changed cache after Prepared",
            )?;
            std::fs::write(evidence.join("job.json"), serde_json::to_vec(&job)?)?;
            let replay = matches!(
                name,
                "stale" | "replacement" | "hash-transition" | "replay-hash-cancel"
            );
            if replay {
                drop(create_at(&job, &cache, format, pool.clone())?);
            }
            capture(&evidence, &cache, "before")?;
            let expected = if name == "revert" {
                let baseline = prepared(job.clone(), None, pool.clone())?;
                let identity = identity(&baseline)?;
                std::fs::write(evidence.join("expected-output.bin"), &identity.0)?;
                std::fs::write(
                    evidence.join("expected-metadata.json"),
                    serde_json::to_vec(&identity.1)?,
                )?;
                drop(baseline);
                Some(identity)
            } else {
                None
            };
            clean(&job, &pool);
            if name == "stale" {
                let before = std::fs::metadata(&job.input)?;
                std::fs::write(&job.input, &changed)?;
                std::fs::OpenOptions::new()
                    .write(true)
                    .open(&job.input)?
                    .set_times(std::fs::FileTimes::new().set_modified(before.modified()?))?;
                let after = std::fs::metadata(&job.input)?;
                assert_eq!(before.len(), after.len());
                assert_eq!(before.modified()?, after.modified()?);
                assert_eq!(std::fs::read(&job.input)?, changed);
            } else if name == "replacement" {
                let replacement = root.path().join("replacement.csv");
                std::fs::write(&replacement, &changed)?;
                std::fs::rename(&job.input, root.path().join("prior-source.csv"))?;
                std::fs::rename(replacement, &job.input)?;
                assert_eq!(
                    std::fs::read(root.path().join("prior-source.csv"))?,
                    original
                );
                assert_eq!(std::fs::read(&job.input)?, changed);
            }
            std::fs::write(
                evidence.join("source-at-call.csv"),
                std::fs::read(&job.input)?,
            )?;
            let cancel = Arc::new(AtomicBool::new(false));
            let hit = Rc::new(std::cell::Cell::new(false));
            let observed = Rc::new(RefCell::new(Vec::new()));
            let scope = Scope;
            let cleanup_pool = pool.clone();
            let cleanup_cache = cache.clone();
            let cleanup_evidence = evidence.clone();
            CLEANUP.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move |path| {
                    assert_eq!(path, cleanup_cache);
                    assert!(cleanup_pool.usage().reserved_bytes >= path.as_os_str().len() as u64);
                    capture(&cleanup_evidence, path, "at-cleanup").unwrap();
                    std::fs::write(
                        cleanup_evidence.join("cleanup-reserved.txt"),
                        cleanup_pool.usage().reserved_bytes.to_string(),
                    )
                    .unwrap();
                }))
            });
            let source = PathBuf::from(&job.input);
            let c = cancel.clone();
            let h = hit.clone();
            let observations = observed.clone();
            let original_hook = original.clone();
            let changed_hook = changed.clone();
            let hook_evidence = evidence.clone();
            let frozen = cache.join("source.partial");
            HASH.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move |path, copying, count, digest| {
                    if path != source {
                        return;
                    }
                    observations
                        .borrow_mut()
                        .push((copying, count, digest.to_hex().to_string()));
                    let selected =
                        matches!(name, "copy-mutation" | "copy-cancel" | "orphan-source")
                            && copying
                            || matches!(name, "hash-transition" | "replay-hash-cancel") && !copying;
                    if !selected || h.replace(true) {
                        return;
                    }
                    assert_eq!(count, 65536);
                    assert_eq!(digest, blake3::hash(&original_hook[..65536]));
                    if name == "copy-mutation" {
                        std::fs::write(&source, &changed_hook).unwrap();
                        assert_eq!(std::fs::read(&source).unwrap(), changed_hook);
                        // The prefix was already written to the frozen file.
                        assert_eq!(std::fs::read(&frozen).unwrap(), original_hook[..65536]);
                    } else if name == "hash-transition" {
                        let mut tail_changed = original_hook.clone();
                        tail_changed[70000] = b'b';
                        assert_ne!(tail_changed, original_hook);
                        std::fs::write(
                            hook_evidence.join("source-hash-transition.csv"),
                            &tail_changed,
                        )
                        .unwrap();
                        std::fs::write(&source, &tail_changed).unwrap();
                        assert_eq!(std::fs::read(&source).unwrap(), tail_changed);
                    } else {
                        c.store(true, Ordering::Relaxed);
                        assert_eq!(std::fs::read(&source).unwrap(), original_hook);
                        if name == "orphan-source" {
                            assert!(frozen.exists());
                            DENY_CLEANUP.with(|slot| slot.set(true));
                        }
                    }
                }))
            });
            let c = cancel.clone();
            let h = hit.clone();
            let source = PathBuf::from(&job.input);
            let changed_hook = changed.clone();
            let original_hook = original.clone();
            let hook_cache = cache.clone();
            let hook_evidence = evidence.clone();
            STAGE.with(|slot| {
                *slot.borrow_mut() = Some(Box::new(move |stage| {
                    if stage == Stage::Frozen {
                        let bytes = std::fs::read(hook_cache.join("source.partial")).unwrap();
                        std::fs::write(hook_evidence.join("source-frozen.csv"), &bytes).unwrap();
                        assert_eq!(bytes, original_hook);
                    }
                    let selected = name == "revert" && stage == Stage::Frozen
                        || name == "row-cancel" && stage == Stage::Row
                        || name == "footer-cancel" && stage == Stage::BeforeFinish
                        || matches!(name, "manifest-cancel" | "orphan-partial")
                            && stage == Stage::ManifestPartial;
                    if !selected || h.replace(true) {
                        return;
                    }
                    if name == "revert" {
                        std::fs::write(&source, &changed_hook).unwrap();
                        assert_eq!(std::fs::read(&source).unwrap(), changed_hook);
                        std::fs::write(&source, &original_hook).unwrap();
                        assert_eq!(std::fs::read(&source).unwrap(), original_hook);
                    } else {
                        assert!(!hook_cache.join("manifest.json").exists());
                        capture(&hook_evidence, &hook_cache, "checkpoint").unwrap();
                        c.store(true, Ordering::Relaxed);
                        if name == "orphan-partial" {
                            assert!(hook_cache.join("records.bin").exists());
                            assert!(hook_cache.join("manifest.partial").exists());
                            DENY_CLEANUP.with(|slot| slot.set(true));
                        }
                    }
                }))
            });
            if replay {
                let result = prepare(
                    job.clone(),
                    &cache,
                    cancel.clone(),
                    Arc::new(|_| {}),
                    pool.clone(),
                );
                let error = match result {
                    Err(error) => error,
                    Ok(unexpected) => {
                        let (bytes, metadata) = identity(&unexpected)?;
                        std::fs::write(evidence.join("unexpected-prepared.bin"), bytes)?;
                        std::fs::write(
                            evidence.join("unexpected-metadata.json"),
                            serde_json::to_vec(&metadata)?,
                        )?;
                        panic!("{format:?}/{name}: replay unexpectedly succeeded");
                    }
                };
                std::fs::write(evidence.join("error.txt"), format!("{error:#}"))?;
                if name != "replay-hash-cancel" {
                    assert!(error.to_string().contains("source changed"));
                }
                clean(&job, &pool);
                drop(error);
                for file in std::fs::read_dir(evidence.join("before"))? {
                    let file = file?;
                    assert_eq!(
                        std::fs::read(file.path())?,
                        std::fs::read(cache.join(file.file_name()))?
                    );
                }
            } else {
                let result = create(
                    &job,
                    &cache,
                    format,
                    32 * 1024 * 1024,
                    cancel.clone(),
                    Arc::new(|_| {}),
                    pool.clone(),
                );
                if name == "revert" {
                    let created = result?;
                    let final_diagnostics = created.diagnostics.clone();
                    assert_eq!(
                        pool.usage().reserved_bytes,
                        final_diagnostics.reserved_bytes()
                    );
                    drop(created);
                    assert_eq!(
                        pool.usage().reserved_bytes,
                        final_diagnostics.reserved_bytes()
                    );
                    drop(final_diagnostics);
                    clean(&job, &pool);
                    drop(scope);
                    capture(&evidence, &cache, "before-prepare")?;
                    let candidate = prepared(job.clone(), Some(&cache), pool.clone())?;
                    let actual = identity(&candidate)?;
                    std::fs::write(evidence.join("actual-output.bin"), &actual.0)?;
                    std::fs::write(
                        evidence.join("actual-metadata.json"),
                        serde_json::to_vec(&actual.1)?,
                    )?;
                    assert_eq!(actual, expected.unwrap());
                    // Prepared's admitted encoded output is authoritative. Both
                    // mutable caller inputs may change without altering export.
                    std::fs::write(&job.input, &changed)?;
                    std::fs::write(
                        cache.join("records.bin"),
                        b"caller changed cache after Prepared",
                    )?;
                    assert_eq!(std::fs::read(&job.input)?, changed);
                    assert_eq!(
                        std::fs::read(cache.join("records.bin"))?,
                        b"caller changed cache after Prepared"
                    );
                    drop(candidate.execute()?);
                    assert_published_original(&job, &original)?;
                    assert_eq!(pool.usage().reserved_bytes, 0);
                    assert_eq!(
                        std::fs::read_dir(job.resources.temp_dir.as_ref().unwrap())?.count(),
                        0
                    );
                    capture(&evidence, Path::new(&job.output), "published")?;
                    assert!(cache.join("manifest.json").exists());
                    assert!(hit.get());
                    std::fs::write(
                        evidence.join("observed-hash-blocks.json"),
                        serde_json::to_vec(&*observed.borrow())?,
                    )?;
                    std::fs::write(
                        evidence.join("source-after.csv"),
                        std::fs::read(&job.input)?,
                    )?;
                    capture(&evidence, &cache, "after")?;
                    assert_eq!(std::fs::read(&sentinel)?, b"unrelated caller sentinel");
                    eprintln!("R17 {format:?}/{name}: passed; exact publication after source/cache changes and final diagnostic clone released");
                    continue;
                }
                let error = match result {
                    Err(error) => error,
                    Ok(_) => {
                        capture(&evidence, &cache, "unexpected-created")?;
                        panic!("{format:?}/{name}: creation unexpectedly succeeded");
                    }
                };
                std::fs::write(evidence.join("error.txt"), format!("{error:#}"))?;
                assert!(!cache.join("manifest.json").exists());
                let orphan = matches!(name, "orphan-source" | "orphan-partial");
                assert_eq!(cache.exists(), orphan);
                if orphan {
                    assert!(error.to_string().contains("caller cleanup required"));
                    assert!(format!("{error:#}").contains("cancel"));
                    capture(&evidence, &cache, "orphan")?;
                } else if name == "copy-mutation" {
                    assert!(error.to_string().contains("source changed"));
                }
                clean(&job, &pool);
                drop(error);
                if orphan {
                    // Only this fixture's exact, newly owned path; preserve raw
                    // orphan bytes before the caller explicitly removes it.
                    assert_eq!(cache.parent(), Some(root.path()));
                    std::fs::remove_dir_all(&cache)?;
                    DENY_CLEANUP.with(|slot| slot.set(false));
                    cancel.store(false, Ordering::Relaxed);
                    drop(STAGE.with(|slot| slot.borrow_mut().take()));
                    drop(HASH.with(|slot| slot.borrow_mut().take()));
                    drop(create_at(&job, &cache, format, pool.clone())?);
                    assert!(cache.join("manifest.json").exists());
                }
            }
            if !matches!(name, "stale" | "replacement") {
                assert!(hit.get(), "{name} checkpoint missed");
            }
            if name == "hash-transition" {
                let transitions = observed.borrow();
                let (_, count, digest) = transitions.last().unwrap();
                let actual = std::fs::read(&job.input)?;
                assert_eq!(*count, actual.len() as u64);
                assert_eq!(*digest, blake3::hash(&actual).to_hex().to_string());
                assert_ne!(actual, original);
            }
            std::fs::write(
                evidence.join("observed-hash-blocks.json"),
                serde_json::to_vec(&*observed.borrow())?,
            )?;
            std::fs::write(
                evidence.join("source-after.csv"),
                std::fs::read(&job.input)?,
            )?;
            capture(&evidence, &cache, "after")?;
            assert_eq!(std::fs::read(&sentinel)?, b"unrelated caller sentinel");
            drop(scope);
            clean(&job, &pool);
            eprintln!("R17 {format:?}/{name}: passed; fixture and observed stream preserved");
        }
    }
    Ok(())
}
