use super::*;
use crate::{resources::MemoryPool, storage::Workspace};
use std::{io::Write, path::Path, sync::Mutex};

const MEMORY: u64 = 32 * 1024 * 1024;
const ROWS: usize = 70_003;
const CAP: usize = 128 * 1024;
const SEED: &str = "probabilistic-fusion-prepared-spill-v1";

fn job(input: &Path, output: &Path, temp: &Path, memory_mb: u64) -> Job {
    Job {
        input: input.to_string_lossy().into(),
        output: output.to_string_lossy().into(),
        random_seed: Some(SEED.into()),
        operations: vec![
            Operation::Partition {
                columns: vec![Column::Name("region".into())],
            },
            Operation::AssignProbabilistic {
                groups: [("major", "80"), ("minor", "20"), ("empty", "0")]
                    .into_iter()
                    .map(|(name, percent)| Allocation {
                        name: name.into(),
                        percent: percent.into(),
                    })
                    .collect(),
                strata: vec![Column::Name("stratum".into())],
            },
            Operation::Shuffle {
                strategy: Shuffle::Uniform,
            },
        ],
        limits: chopper_core::Limits {
            rows: Some(2000),
            bytes: Some(CAP as u64),
            ..Default::default()
        },
        resources: Resources {
            memory_mb: memory_mb.into(),
            workers: 1,
            max_record_bytes: 16 * 1024,
            temp_dir: Some(temp.to_string_lossy().into()),
            ..Default::default()
        },
        ..Default::default()
    }
}

fn execute(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<MemoryPool>,
    physical: Option<physical::Sink>,
) -> Result<(Analysis, serde_json::Value)> {
    job.validate()?;
    let mut input_reads = 0;
    let result = process_using(
        job.into(),
        cancel,
        notify,
        pool,
        physical,
        ProcessingMode::Prepare,
        |job, ctx, p, b, s| {
            input_reads += 1;
            with_input(job, Reservation::new(ctx), |mut source| {
                ingest_options(source.as_mut(), job, ctx, p, b, s)
            })
        },
    );
    assert_eq!(input_reads, 1, "raw input must not be replayed");
    let result = result?;
    let Processed::Snapshot(ref prepared) = result else {
        panic!("only the existing snapshot output path is in this comparison");
    };
    let counters = prepared.ctx.clone();
    let analysis = result.publish()?.into_analysis();
    let counters = counters.diagnostics();
    Ok((analysis, counters))
}

#[test]
fn prepared_spill_fusion_contracts() -> Result<()> {
    let work = tempfile::tempdir()?;
    let input = work.path().join("input.csv");
    let mut fixture = std::io::BufWriter::new(std::fs::File::create(&input)?);
    writeln!(fixture, "id,region,stratum,payload")?;
    let payload = "x".repeat(512);
    for id in 0..ROWS {
        writeln!(fixture, "{id},{},{},{payload}", id % 4, id % 7)?;
    }
    fixture.flush()?;
    drop(fixture);
    let output = work.path().join("output");
    let temp = work.path().join("temp");
    std::fs::create_dir(&temp)?;
    let mut reference = None;
    for mode in ["serial", "fused", "retry", "cancel"] {
        SERIAL_CONTROL.with(|serial| serial.set(mode == "serial"));
        let pool = Arc::new(MemoryPool::new(MEMORY));
        let peer = Arc::new(Mutex::new(Reservation::for_workspace(Arc::new(
            Workspace::shared(MEMORY as usize, pool.clone()),
        ))));
        let reports = Arc::new(Mutex::new(Vec::new()));
        let physical: physical::Sink = {
            let reports = reports.clone();
            Arc::new(move |fact| {
                reports.lock().unwrap().push(fact);
                true
            })
        };
        let retries = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let injected = Arc::new(AtomicBool::new(false));
        let cancel = Arc::new(AtomicBool::new(false));
        let notify: Notify = {
            use std::sync::atomic::Ordering::Relaxed;
            let (peer, pool, retries, injected, cancel) = (
                peer.clone(),
                pool.clone(),
                retries.clone(),
                injected.clone(),
                cancel.clone(),
            );
            Arc::new(move |progress| {
                if progress.phase == "Retrying probabilistic assignment and shuffle" {
                    retries.fetch_add(1, Relaxed);
                    peer.lock().unwrap().resize(0).unwrap();
                }
                let mode_phase = (mode == "retry" || mode == "cancel")
                    && progress.phase == "Before prepared probabilistic spill";
                if mode_phase && !injected.swap(true, Relaxed) {
                    let spare = if mode == "emission-denial" { 0 } else { 65_535 };
                    let free = MEMORY - pool.usage().reserved_bytes;
                    peer.lock()
                        .unwrap()
                        .resize((free - spare) as usize)
                        .unwrap();
                    if mode == "cancel" {
                        cancel.store(true, Relaxed);
                    }
                }
            })
        };
        let result = execute(
            job(&input, &output, &temp, 32),
            cancel,
            notify,
            pool.clone(),
            Some(physical),
        );
        use std::sync::atomic::Ordering::Relaxed;
        assert_eq!(
            retries.load(Relaxed),
            usize::from(mode == "retry"),
            "{mode}"
        );
        assert_eq!(injected.load(Relaxed), matches!(mode, "retry" | "cancel"));
        match mode {
            "cancel" => {
                let error = result.expect_err("cancelled before fallback");
                assert!(format!("{error:#}").contains("job cancelled"));
            }
            _ => {
                let (analysis, diagnostics) = result?;
                println!("{mode}: {diagnostics}");
                let fingerprint = verify(&output, analysis, &payload)?;
                if let Some(expected) = &reference {
                    assert_eq!(expected, &fingerprint, "exact seeded parity in {mode}");
                } else {
                    reference = Some(fingerprint);
                }
                std::fs::remove_dir_all(&output)?;
                let reports = reports.lock().unwrap();
                if mode != "serial" {
                    assert!(
                        reports.iter().any(|fact| {
                            fact.kind == Kind::Spill
                                && fact.operations == [2, 3]
                                && fact.status == Status::Completed
                        }),
                        "external fused sort maps to operations 2 and 3"
                    );
                    assert!(reports.iter().any(|fact| {
                        fact.kind == Kind::ProbabilisticMembership
                            && fact.operations == [2, 0]
                            && fact.status == Status::Completed
                    }));
                }
                assert_eq!(
                    reports.iter().any(|fact| fact.kind == Kind::Fallback),
                    mode == "retry"
                );
            }
        }
        assert!(!output.exists());
        assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
        assert_eq!(std::fs::read_dir(work.path())?.count(), 2);
        let mut peer = peer.lock().unwrap();
        assert_eq!(pool.usage().reserved_bytes, peer.bytes());
        peer.resize(0)?;
        assert_eq!(pool.usage().reserved_bytes, 0);
    }
    Ok(())
}

fn verify(
    output: &Path,
    analysis: Analysis,
    payload: &str,
) -> Result<(serde_json::Value, Vec<String>)> {
    let mut logical = serde_json::to_value(analysis)?;
    for key in [
        "temp_bytes",
        "peak_temp_bytes",
        "analysis_seconds",
        "timings",
        "diagnostics",
    ] {
        logical.as_object_mut().unwrap().remove(key);
    }
    assert_eq!(logical["rows"].as_u64(), Some(ROWS as u64));
    assert_eq!(logical["groups"].as_u64(), Some(12));
    let manifest = std::fs::read_to_string(output.join("manifest.jsonl"))?;
    let mut seen = vec![false; ROWS];
    let mut fingerprints = Vec::new();
    let mut empty = 0;
    let mut order = std::collections::BTreeMap::new();
    for line in manifest.lines().skip(1) {
        let record: serde_json::Value = serde_json::from_str(line)?;
        let lineage = record["lineage"].as_array().context("missing lineage")?;
        assert_eq!(lineage.len(), 2);
        assert_eq!(lineage[0]["operation"].as_u64(), Some(0));
        assert_eq!(lineage[1]["operation"].as_u64(), Some(1));
        let partition = lineage[0]["values"][0]
            .as_str()
            .context("missing partition value")?;
        let group = lineage[1]["allocation"]
            .as_str()
            .context("missing allocation name")?;
        let member = random::algorithm_domain(
            &random::json_domain(SEED, 1, &[&lineage[0]])?,
            "probabilistic-allocation-v1",
        );
        let shuffle = random::json_domain(SEED, 2, lineage)?;
        let path = record["path"].as_str().context("missing output path")?;
        let csv = std::fs::read(output.join(path))?;
        assert!(csv.len() <= CAP);
        assert_eq!(record["csv_bytes"].as_u64(), Some(csv.len() as u64));
        assert_eq!(record["stored_bytes"].as_u64(), Some(csv.len() as u64));
        let mut rows = std::str::from_utf8(&csv)?.lines();
        assert_eq!(rows.next(), Some("id,region,stratum,payload"));
        let mut count = 0;
        for row in rows {
            let fields: Vec<_> = row.split(',').collect();
            assert_eq!(fields.len(), 4);
            let id: usize = fields[0].parse()?;
            assert!(!std::mem::replace(&mut seen[id], true));
            assert_eq!(fields[1], partition);
            assert_eq!(fields[1].parse::<usize>()?, id % 4);
            assert_eq!(fields[2].parse::<usize>()?, id % 7);
            assert_eq!(fields[3], payload);
            let expected = random::categorical_views(
                &member,
                id as u64,
                fields.iter().copied(),
                &[2],
                &[80_000_000, 20_000_000, 0],
            );
            assert_eq!(group, ["major", "minor", "empty"][expected]);
            let block = random::block(&shuffle, id as u64, 0);
            let key: [u8; 16] = block[..16].try_into().unwrap();
            if let Some((previous_key, previous_id)) =
                order.insert((partition.to_owned(), group.to_owned()), (key, id as u64))
            {
                assert!(
                    previous_key < key
                        || (previous_key == key
                            && random::compare_ties(&shuffle, previous_id, id as u64).is_lt())
                );
            }
            count += 1;
        }
        if count == 0 {
            assert_eq!(group, "empty");
            empty += 1;
        }
        assert!(count <= 2000);
        assert_eq!(record["rows"].as_u64(), Some(count));
        fingerprints.push(format!("{line} {}", blake3::hash(&csv)));
    }
    assert!(seen.into_iter().all(|value| value));
    assert_eq!(empty, 4);
    assert_eq!(std::fs::read_dir(output)?.count(), fingerprints.len() + 1);
    Ok((logical, fingerprints))
}

#[test]
fn fused_prepared_parent_sink_denial_is_terminal() -> Result<()> {
    #[derive(Default)]
    struct DenyAfterOne {
        attempts: usize,
    }
    impl RowSink for DenyAfterOne {
        fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
            Group {
                offset: 0,
                rows: 0,
                lineage,
                exact,
            }
        }
        fn row(&mut self, group: &mut Group, _: &Row) -> Result<()> {
            self.attempts += 1;
            if self.attempts == 2 {
                return Err(MemoryAdmission::Local.into());
            }
            group.rows += 1;
            Ok(())
        }
        fn end(&mut self, _: Group) -> Result<()> {
            Ok(())
        }
    }
    let dir = tempfile::tempdir()?;
    let temp = dir.path().join("temp");
    std::fs::create_dir(&temp)?;
    let job = job(
        &dir.path().join("input.csv"),
        &dir.path().join("output"),
        &temp,
        32,
    );
    let retries = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let notify = {
        let retries = retries.clone();
        Arc::new(move |p: crate::storage::Progress| {
            if p.phase == "Retrying probabilistic assignment and shuffle" {
                retries.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            }
        })
    };
    let pool = Arc::new(MemoryPool::new(MEMORY));
    let ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        notify,
        pool.clone(),
    )?;
    let mut input = String::from("id,region,stratum,payload\n");
    use std::fmt::Write as _;
    for id in 0..128 {
        writeln!(input, "{id},0,0,value")?;
    }
    let ingested = ingest(Box::new(input.as_bytes()), &job, &ctx)?;
    let mut sink = DenyAfterOne::default();
    let error = Plan::at(&job, 1)
        .unwrap()
        .apply(&ingested.dataset, &job, &ingested.analysis, &ctx, &mut sink)
        .expect_err("sink denial is terminal");
    assert!(matches!(
        error.downcast_ref::<MemoryAdmission>(),
        Some(MemoryAdmission::Local)
    ));
    assert_eq!(sink.attempts, 2);
    assert_eq!(retries.load(std::sync::atomic::Ordering::Relaxed), 0);
    drop(ingested);
    drop(ctx);
    assert_eq!(pool.usage().reserved_bytes, 0);
    assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
    Ok(())
}

#[test]
#[ignore = "requires an explicit pinned benchmark job"]
fn measure_prepared_spill_fusion() -> Result<()> {
    let config = std::env::var_os("CHOPPER_PROBABILISTIC_FUSION_CONFIG").context("missing job")?;
    let arm = std::env::var("CHOPPER_PROBABILISTIC_FUSION_ARM")?;
    ensure!(arm == "serial" || arm == "fused", "unknown arm");
    SERIAL_CONTROL.with(|serial| serial.set(arm == "serial"));
    let mut job: Job = serde_json::from_slice(&std::fs::read(config)?)?;
    job.random_seed = Some(SEED.into());
    let shared = std::env::var("CHOPPER_PROBABILISTIC_FUSION_SHARED_BYTES")?.parse()?;
    let pool = Arc::new(MemoryPool::new(shared));
    let retries = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let notify = {
        let retries = retries.clone();
        Arc::new(move |p: crate::storage::Progress| {
            if p.phase == "Retrying probabilistic assignment and shuffle" {
                retries.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            }
        })
    };
    let start = std::time::Instant::now();
    let (analysis, diagnostics) = execute(
        job,
        Arc::new(AtomicBool::new(false)),
        notify,
        pool.clone(),
        None,
    )?;
    let elapsed = start.elapsed().as_secs_f64();
    println!(
        "MEASUREMENT {}",
        serde_json::json!({"arm": arm, "elapsed_seconds": elapsed, "rows": analysis.rows,
            "files": analysis.output_files, "output_csv_bytes": analysis.output_csv_bytes,
            "retries": retries.load(std::sync::atomic::Ordering::Relaxed),
            "diagnostics": diagnostics, "peak_reserved_bytes": pool.usage().peak_reserved_bytes})
    );
    drop(analysis);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}
#[test]
fn matched_held_peer_during_probabilistic_fusion() -> Result<()> {
    let work = tempfile::tempdir()?;
    let input = work.path().join("input.csv");
    let mut fixture = std::io::BufWriter::new(std::fs::File::create(&input)?);
    writeln!(fixture, "id,region,stratum,payload")?;
    let payload = "x".repeat(512);
    for id in 0..ROWS {
        writeln!(fixture, "{id},{},{},{payload}", id % 4, id % 7)?;
    }
    fixture.flush()?;
    drop(fixture);
    let output = work.path().join("output");
    let temp = work.path().join("temp");
    std::fs::create_dir(&temp)?;
    let mut expected = None;
    for peer_mib in [24, 28, 30] {
        for serial in [true, false] {
            SERIAL_CONTROL.with(|control| control.set(serial));
            let pool = Arc::new(MemoryPool::new(MEMORY));
            let peer = Arc::new(Mutex::new(Reservation::for_workspace(Arc::new(
                Workspace::shared(MEMORY as usize, pool.clone()),
            ))));
            let attempts = Arc::new(std::sync::atomic::AtomicUsize::new(0));
            let retries = Arc::new(std::sync::atomic::AtomicUsize::new(0));
            use std::sync::atomic::Ordering::Relaxed;
            let notify: Notify = {
                let (peer, attempts, retries) = (peer.clone(), attempts.clone(), retries.clone());
                Arc::new(move |progress| {
                    if progress.phase == "Preparing operation 2 of 3" {
                        assert_eq!(attempts.fetch_add(1, Relaxed), 0);
                        peer.lock().unwrap().resize(peer_mib * 1024 * 1024).unwrap();
                    }
                    if progress.phase == "Retrying probabilistic assignment and shuffle" {
                        retries.fetch_add(1, Relaxed);
                    }
                })
            };
            let result = execute(
                job(&input, &output, &temp, 32),
                Arc::new(AtomicBool::new(false)),
                notify,
                pool.clone(),
                None,
            );
            let state = match result {
                Ok((analysis, diagnostics)) => {
                    println!("diagnostics serial={serial} peer_mib={peer_mib} {diagnostics}");
                    let fingerprint = verify(&output, analysis, &payload)?;
                    if let Some(expected) = &expected {
                        assert_eq!(&fingerprint, expected);
                    } else {
                        expected = Some(fingerprint);
                    }
                    std::fs::remove_dir_all(&output)?;
                    "complete"
                }
                Err(error) => {
                    assert!(
                        error.downcast_ref::<MemoryAdmission>().is_some(),
                        "{error:#}"
                    );
                    println!("denial serial={serial} peer_mib={peer_mib} {error:#}");
                    "denied"
                }
            };
            assert_eq!(attempts.load(Relaxed), 1);
            let mut peer = peer.lock().unwrap();
            assert_eq!(peer.bytes(), (peer_mib * 1024 * 1024) as u64);
            assert_eq!(pool.usage().reserved_bytes, peer.bytes());
            assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
            assert!(!output.exists());
            assert_eq!(std::fs::read_dir(work.path())?.count(), 2);
            println!(
                "frontier serial={serial} peer_mib={peer_mib} state={state} retries={}",
                retries.load(Relaxed)
            );
            peer.resize(0)?;
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
    }
    Ok(())
}
