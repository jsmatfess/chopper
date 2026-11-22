//! Native Run contracts for serial/default and opt-in plain publication.
use super::*;
use crate::{engine::run_with_memory_pool, resources::MemoryPool};
use chopper_core::{Limits, Resources, Shuffle};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    fs,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};

// Observe actual retained task capacity on the executing caller, without a
// global switch that could change another test's publication policy.
thread_local! {
    static BATCHES: RefCell<Option<Arc<Mutex<Vec<usize>>>>> = const { RefCell::new(None) };
}
pub(super) fn observe_batch(capacity: usize) {
    BATCHES.with(|slot| {
        if let Some(batches) = slot.borrow().as_ref() {
            batches.lock().unwrap().push(capacity);
        }
    });
}
struct Observation;
impl Observation {
    fn install(batches: Arc<Mutex<Vec<usize>>>) -> Self {
        BATCHES.with(|slot| {
            assert!(slot.borrow().is_none());
            *slot.borrow_mut() = Some(batches);
        });
        Self
    }
}
impl Drop for Observation {
    fn drop(&mut self) {
        BATCHES.with(|slot| slot.borrow_mut().take());
    }
}
const MEMORY: u64 = 128 * 1024 * 1024;
const ROWS: u64 = 43;
fn note(id: u64) -> String {
    format!("quoted \"界\",\nline-{id}")
}
fn fixture(workers: usize, single: bool) -> Result<(tempfile::TempDir, Job)> {
    let dir = tempfile::tempdir()?;
    let mut input = String::from("id,note\n");
    for id in 0..ROWS {
        input.push_str(&format!("{id},\"{}\"\n", note(id).replace('"', "\"\"")));
    }
    fs::write(dir.path().join("input.csv"), input)?;
    fs::create_dir(dir.path().join("temp"))?;
    let job = Job {
        input: dir.path().join("input.csv").to_string_lossy().into_owned(),
        output: dir.path().join("output").to_string_lossy().into_owned(),
        random_seed: Some("plain-publication-contract-v1".into()),
        // Two adjacent shuffles keep Run on the snapshot path even in the
        // terminal-shuffle experiment; the existing rewrite avoids duplicate work.
        operations: vec![
            Operation::Shuffle {
                strategy: Shuffle::Uniform
            };
            2
        ],
        limits: Limits {
            bytes: Some(if single { 16 * 1024 } else { 256 }),
            rows: if single { None } else { Some(3) },
            ..Default::default()
        },
        resources: Resources {
            memory_mb: 128.into(),
            workers,
            max_record_bytes: 1024 * 1024,
            temp_dir: Some(dir.path().join("temp").to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    Ok((dir, job))
}
fn clean(dir: &Path) -> Result<()> {
    assert_eq!(fs::read_dir(dir.join("temp"))?.count(), 0);
    assert!(!fs::read_dir(dir)?.any(|entry| entry
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".chopper-staging-")));
    Ok(())
}

#[test]
fn seeded_run_keeps_exact_csv_order_caps_and_only_needed_batch_slots() -> Result<()> {
    for single in [false, true] {
        let mut reference = None;
        for workers in [1, 4] {
            let (dir, job) = fixture(workers, single)?;
            let pool = Arc::new(MemoryPool::new(MEMORY));
            let batches = Arc::new(Mutex::new(Vec::new()));
            let _observe = Observation::install(batches.clone());
            let analysis = run_with_memory_pool(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            assert_eq!(analysis.workers, workers);
            assert_eq!(analysis.rows, ROWS);
            assert_eq!(
                analysis.output_files,
                if single { 1 } else { ROWS.div_ceil(3) }
            );
            let manifest = fs::read_to_string(Path::new(&job.output).join("manifest.jsonl"))?;
            let records: Vec<serde_json::Value> = manifest
                .lines()
                .map(serde_json::from_str)
                .collect::<std::result::Result<_, _>>()?;
            let records: Vec<_> = records
                .into_iter()
                .filter(|record| record["type"] == "output")
                .collect();
            assert_eq!(records.len() as u64, analysis.output_files);
            let mut bytes = BTreeMap::new();
            let mut ids = BTreeSet::new();
            for (index, record) in records.iter().enumerate() {
                let name = record["path"].as_str().unwrap();
                assert_eq!(name, format!("part-{:08}.csv", index + 1));
                let data = fs::read(Path::new(&job.output).join(name))?;
                assert!(data.len() as u64 <= job.limits.bytes.unwrap());
                assert_eq!(record["csv_bytes"], data.len() as u64);
                assert_eq!(record["stored_bytes"], data.len() as u64);
                let mut parser =
                    csv::Parser::new(data.as_slice(), job.output_csv.clone(), 1024 * 1024);
                assert_eq!(parser.next_record()?.unwrap(), ["id", "note"]);
                let mut count = 0;
                while let Some(fields) = parser.next_record()? {
                    assert_eq!(fields.len(), 2);
                    let id: u64 = fields[0].parse()?;
                    assert_eq!(fields[1], note(id));
                    assert!(ids.insert(id));
                    count += 1;
                }
                assert_eq!(record["rows"], count);
                assert!(job.limits.rows.is_none_or(|cap| count <= cap));
                bytes.insert(name.to_owned(), data);
            }
            assert_eq!(ids, (0..ROWS).collect());
            let logical = json!({"seed":analysis.seed,"digest":analysis.logical_digest,"header":analysis.header,"groups":analysis.groups,"bytes":analysis.output_csv_bytes,"accuracy":analysis.accuracy,"stages":analysis.stages});
            let actual = (bytes, records, logical);
            if let Some(expected) = &reference {
                assert_eq!(&actual, expected);
            } else {
                reference = Some(actual);
            }
            let batches = batches.lock().unwrap();
            let expected_max = if cfg!(feature = "experimental-plain-publication") && !single {
                workers
            } else {
                1
            };
            assert_eq!(batches.iter().copied().max(), Some(expected_max));
            assert_eq!(batches.iter().sum::<usize>() as u64, analysis.output_files);
            drop(analysis);
            assert_eq!(pool.usage().reserved_bytes, 0);
            clean(dir.path())?;
        }
    }
    Ok(())
}

#[test]
fn cancellation_after_written_prefix_joins_and_removes_private_output() -> Result<()> {
    let (dir, job) = fixture(4, false)?;
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    let pool = Arc::new(MemoryPool::new(MEMORY));
    let error = run_with_memory_pool(
        job.clone(),
        cancel.clone(),
        Arc::new(move |p| {
            if p.phase == "Writing output" && p.rows > 0 {
                signal.store(true, Ordering::Relaxed);
            }
        }),
        pool.clone(),
    )
    .unwrap_err();
    assert!(cancel.load(Ordering::Relaxed));
    assert!(format!("{error:#}").contains("cancel"), "{error:#}");
    assert!(!Path::new(&job.output).exists());
    assert_eq!(pool.usage().reserved_bytes, 0);
    clean(dir.path())
}

#[test]
fn shared_denial_after_written_prefix_releases_every_task_and_stage() -> Result<()> {
    let (dir, job) = fixture(4, false)?;
    let pool = Arc::new(MemoryPool::new(MEMORY));
    let grant = Arc::new(Mutex::new(Reservation::for_workspace(Arc::new(
        Workspace::shared(MEMORY as usize, pool.clone()),
    ))));
    let peer = grant.clone();
    let shared = pool.clone();
    let injected = Arc::new(AtomicBool::new(false));
    let once = injected.clone();
    let error = run_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |p| {
            if p.phase == "Writing output" && p.rows > 0 && !once.swap(true, Ordering::Relaxed) {
                let amount = MEMORY - shared.usage().reserved_bytes - 32 * 1024;
                peer.lock()
                    .unwrap()
                    .resize(usize::try_from(amount).unwrap())
                    .unwrap();
            }
        }),
        pool.clone(),
    )
    .unwrap_err();
    assert!(injected.load(Ordering::Relaxed));
    assert!(
        matches!(
            error.downcast_ref::<crate::resources::MemoryAdmission>(),
            Some(crate::resources::MemoryAdmission::Shared { .. })
        ),
        "{error:#}"
    );
    assert!(!Path::new(&job.output).exists());
    clean(dir.path())?;
    // Only the deliberate competing owner may remain after the failed Run.
    assert!(pool.usage().reserved_bytes > 0);
    drop(grant);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}
