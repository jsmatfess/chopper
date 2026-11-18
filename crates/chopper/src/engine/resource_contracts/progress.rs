use super::*;
use std::sync::atomic::Ordering as AtomicOrdering;
#[test]
fn progress_real_producers() -> Result<()> {
    run().map(|_| ())
}
pub(super) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id\n1\n2\n")?;
    let mut profile_job = Job {
        input: input.to_string_lossy().into_owned(),
        ..Default::default()
    };
    profile_job.resources.workers = 1;
    profile_job.resources.temp_dir = Some(dir.path().to_string_lossy().into_owned());
    let profile_pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
    let mut cache = crate::profile::ProfileCache::with_memory_pool(profile_pool.clone());
    let profile_events = Arc::new(std::sync::Mutex::new(Vec::new()));
    let profile = cache.profile(&profile_job, Arc::new(AtomicBool::new(false)), {
        let events = profile_events.clone();
        Arc::new(move |p| {
            events.lock().unwrap().push(p);
        })
    })?;
    ensure!(
        profile_events
            .lock()
            .unwrap()
            .last()
            .is_some_and(|p| p.phase == "Input profile complete"
                && p.phase.capacity() == 0
                && p.phase.reserved_bytes() == 0),
        "real profile phase allocated"
    );
    drop(profile);
    cache.clear();
    ensure!(
        profile_pool.usage().reserved_bytes == 0,
        "profile control leaked"
    );
    for direct in [false, true] {
        let output = dir.path().join(if direct { "direct" } else { "prepared" });
        let mut job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("progress-contract".into()),
            ..Default::default()
        };
        job.resources.memory_mb = 32.into();
        job.resources.workers = 1;
        job.resources.temp_dir = Some(dir.path().to_string_lossy().into_owned());
        job.resources.max_record_bytes = 1024;
        if direct {
            job.limits.rows = Some(1);
        } else {
            job.operations.push(Operation::Balanced { files: 2 });
        }
        let pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let events = Arc::new(std::sync::Mutex::new(Vec::new()));
        let notify: Notify = {
            let events = events.clone();
            Arc::new(move |p| {
                events.lock().unwrap().push(p);
            })
        };
        let pressure = Arc::new(std::sync::Mutex::new(None));
        let committed = Arc::new(AtomicBool::new(false));
        let _reset = crate::output::commit_test_hook::install({
            let pool = pool.clone();
            let pressure = pressure.clone();
            let cancel = cancel.clone();
            let committed = committed.clone();
            move |_| {
                // Admission and cancellation are forced only AFTER real commit.
                let mut owner = Reservation::for_workspace(Arc::new(Workspace::shared(
                    128 * 1024 * 1024,
                    pool.clone(),
                )));
                owner
                    .resize((pool.usage().limit_bytes - pool.usage().reserved_bytes) as usize)
                    .unwrap();
                *pressure.lock().unwrap() = Some(owner);
                cancel.store(true, AtomicOrdering::Relaxed);
                committed.store(true, AtomicOrdering::Relaxed);
            }
        });
        let analysis = if direct {
            run_with_memory_pool(job, cancel, notify, pool.clone())?
        } else {
            prepare_with_memory_pool(job, cancel, notify, pool.clone())?.execute()?
        };
        ensure!(
            committed.load(AtomicOrdering::Relaxed) && output.is_dir(),
            "publication hook not reached"
        );
        let events = events.lock().unwrap();
        let complete = events.last().context("missing complete")?;
        ensure!(
            complete.phase == "Complete"
                && complete.phase.capacity() == 0
                && complete.phase.reserved_bytes() == 0
                && complete.rows == 2,
            "postcommit complete changed"
        );
        if !direct {
            ensure!(
                events.iter().any(
                    |p| p.phase == "Preparing operation 1 of 1" && p.phase.reserved_bytes() > 0
                ),
                "real formatted prepare event missing grant"
            );
        }
        ensure!(
            analysis.rows == 2 && analysis.output_files == 2,
            "publication counts changed"
        );
        drop(events);
        drop(analysis);
        pressure.lock().unwrap().take();
    }
    Ok(json!({"prepared_direct_commit_zero_admission_cancel":2,"real_formatted_prepare":true}))
}
