//! Shared admission for charged capacities, independent of per-job ceilings.
//! This ledger does not include all allocations and does not bound RSS.
use anyhow::Result;
use serde::Serialize;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex, OnceLock,
};
#[cfg(all(test, not(target_os = "wasi")))]
mod e5_worker_controls;
mod host;
mod pressure;

/// Distinguish admission denial from malformed input and cancellation. Optional
/// workspaces may retry with less memory only after dropping the failed scan.
#[derive(Debug)]
pub(crate) enum MemoryAdmission {
    Local,
    Shared { limit: u64, startup: u64 },
}
impl std::fmt::Display for MemoryAdmission {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Local => f.write_str("concurrent algorithm workspaces exceed memory budget; increase memory_mb"),
            Self::Shared { limit, startup } => write!(f, "shared process memory admission limit exceeded (current {limit} bytes, startup ceiling {startup} bytes); release retained work or reduce concurrent work"),
        }
    }
}
impl std::error::Error for MemoryAdmission {}

#[derive(Debug)]
pub struct MemoryPool {
    used: AtomicU64,
    peak: AtomicU64,
    limit: u64,
    observation: Option<host::Observation>,
    pressure: Option<Mutex<pressure::Pressure>>,
}
#[derive(Debug, Serialize)]
pub struct MemoryUsage {
    pub limit_bytes: u64,
    pub reserved_bytes: u64,
    pub peak_reserved_bytes: u64,
    pub startup_observation: Option<host::Observation>,
    pub admission_limit_bytes: u64,
    pub pressure_baseline_reserved_bytes: Option<u64>,
    pub pressure_observation: Option<host::Observation>,
    pub pressure_rechecks: u64,
}
// Borrow discovery strings while serializing a snapshot. The public
// MemoryUsage remains an explicit caller-owned copy.
#[derive(Serialize)]
pub(crate) struct MemoryUsageView<'a> {
    limit_bytes: u64,
    reserved_bytes: u64,
    peak_reserved_bytes: u64,
    startup_observation: Option<&'a host::Observation>,
    admission_limit_bytes: u64,
    pressure_baseline_reserved_bytes: Option<u64>,
    pressure_observation: Option<&'a host::Observation>,
    pressure_rechecks: u64,
}
impl MemoryPool {
    /// A shared ceiling for tracked capacity. Owners retain their grants until
    /// drop; neither a smaller job nor a new pressure observation revokes them.
    pub fn new(limit_bytes: u64) -> Self {
        Self {
            used: AtomicU64::new(0),
            peak: AtomicU64::new(0),
            limit: limit_bytes,
            observation: None,
            pressure: None,
        }
    }
    pub fn usage(&self) -> MemoryUsage {
        let pressure = self.pressure.as_ref().map(|state| {
            state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        });
        MemoryUsage {
            limit_bytes: self.limit,
            reserved_bytes: self.used.load(Ordering::Relaxed),
            peak_reserved_bytes: self.peak.load(Ordering::Relaxed),
            startup_observation: self.observation.clone(),
            admission_limit_bytes: pressure.as_ref().map_or(self.limit, |p| p.limit),
            pressure_baseline_reserved_bytes: pressure.as_ref().map(|p| p.baseline),
            pressure_observation: pressure.as_ref().map(|p| p.observation.clone()),
            pressure_rechecks: pressure.as_ref().map_or(0, |p| p.rechecks),
        }
    }
    pub(crate) fn with_usage<R>(&self, run: impl FnOnce(MemoryUsageView<'_>) -> R) -> R {
        let pressure = self.pressure.as_ref().map(|state| {
            state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        });
        run(MemoryUsageView {
            limit_bytes: self.limit,
            reserved_bytes: self.used.load(Ordering::Relaxed),
            peak_reserved_bytes: self.peak.load(Ordering::Relaxed),
            startup_observation: self.observation.as_ref(),
            admission_limit_bytes: pressure.as_ref().map_or(self.limit, |p| p.limit),
            pressure_baseline_reserved_bytes: pressure.as_ref().map(|p| p.baseline),
            pressure_observation: pressure.as_ref().map(|p| &p.observation),
            pressure_rechecks: pressure.as_ref().map_or(0, |p| p.rechecks),
        })
    }
    /// Read the current shared ceiling without granting capacity or cloning diagnostics.
    pub(crate) fn admission_limit(&self) -> u64 {
        self.with_usage(|usage| usage.admission_limit_bytes)
    }

    /// Resolve without granting the observed free capacity.
    pub(crate) fn resolve_memory(&self, resources: &chopper_core::Resources) -> Result<u64> {
        self.resolve_memory_for_run(resources, [256, 256], 0)
    }

    pub(crate) fn resolve_memory_for_run(
        &self,
        resources: &chopper_core::Resources,
        auto_targets_mb: [u64; 2],
        job_credit: u64,
    ) -> Result<u64> {
        self.recheck_pressure();
        let mb = resources.memory_mb.as_mib().unwrap_or_else(|| {
            self.with_usage(|usage| {
                // The live, same-pool Job credit affects sizing only.
                let available_mb = usage
                    .admission_limit_bytes
                    .saturating_sub(usage.reserved_bytes.saturating_sub(job_credit))
                    / (1024 * 1024 / 2);
                // A target needs its full working allowance. Reuse a
                // calibrated lower tier when it still fits.
                auto_targets_mb
                    .into_iter()
                    .find(|&target| available_mb >= target)
                    .unwrap_or_else(|| available_mb.min(256))
            })
        });
        resources.validate_effective_memory(mb).map_err(|error| {
            anyhow::anyhow!("resolved memory budget {mb} MiB with max_record_bytes {} (record allowance requires at least {} MiB): {error}", resources.max_record_bytes, (resources.max_record_bytes as u64).saturating_mul(16).div_ceil(1024 * 1024))
        })?;
        #[cfg(target_os = "wasi")]
        anyhow::ensure!(mb <= 2048, "browser working memory is limited to 2048 MiB");
        Ok(mb)
    }
    pub(crate) fn reservation_counts(&self) -> (u64, u64) {
        (
            self.used.load(Ordering::Relaxed),
            self.peak.load(Ordering::Relaxed),
        )
    }
    /// Refresh only at safe boundaries, at most once a second. Static caller
    /// pools and runtimes without Linux observations retain their fixed policy.
    pub(crate) fn recheck_pressure(&self) {
        if let Some(state) = &self.pressure {
            let mut state = state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.refresh(
                self.limit,
                || self.used.load(Ordering::Relaxed),
                std::time::Instant::now(),
            );
        }
    }
    pub(crate) fn acquire(&self, bytes: u64) -> Result<()> {
        self.try_acquire(bytes).map_err(Into::into)
    }
    // Inline denial transport for prefix readers. Do not construct an anyhow
    // carrier until the decoder and its partial payloads have unwound.
    pub(crate) fn try_acquire(&self, bytes: u64) -> Result<(), MemoryAdmission> {
        // Serialize grants with rechecks so a stale pre-observation allowance
        // cannot escape after a lower admission limit has been published.
        let pressure = self.pressure.as_ref().map(|state| {
            state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        });
        let limit = pressure.as_ref().map_or(self.limit, |p| p.limit);
        let old = self
            .used
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |used| {
                used.checked_add(bytes).filter(|n| *n <= limit)
            })
            .map_err(|_| MemoryAdmission::Shared {
                limit,
                startup: self.limit,
            })?;
        self.peak.fetch_max(old + bytes, Ordering::Relaxed);
        Ok(())
    }
    pub(crate) fn release(&self, bytes: u64) {
        self.used.fetch_sub(bytes, Ordering::Relaxed);
    }
}
/// One ledger per native process or WASI engine instance. The optional native
/// environment setting is an upper ceiling in MiB, not an automatic job budget.
/// Host discovery only constrains admission; explicit job budgets stay unchanged.
pub(crate) fn process_memory() -> Result<Arc<MemoryPool>> {
    static MEMORY: OnceLock<Result<Arc<MemoryPool>, String>> = OnceLock::new();
    MEMORY
        .get_or_init(|| {
            let observation = host::observe();
            // Keep half of additional observed headroom outside the charged ledger.
            // Unknown platforms keep the historical default's half-budget allowance.
            #[cfg(not(target_os = "wasi"))]
            let limit = observation
                .headroom_bytes
                .map(|n| n / 2)
                .unwrap_or(128 * 1024 * 1024);
            // WASI has a known 2 GiB address-space ceiling, not host RAM discovery.
            #[cfg(target_os = "wasi")]
            let limit = 1024 * 1024 * 1024;
            #[cfg(not(target_os = "wasi"))]
            let limit = if let Some(value) = std::env::var_os("CHOPPER_MEMORY_LIMIT_MB") {
                let ceiling = value
                    .to_str()
                    .and_then(|s| s.parse::<u64>().ok())
                    .and_then(|n| n.checked_mul(1024 * 1024))
                    .filter(|n| *n > 0)
                    .ok_or_else(|| {
                        "CHOPPER_MEMORY_LIMIT_MB must be a positive MiB integer without overflow"
                            .to_owned()
                    })?;
                limit.min(ceiling)
            } else {
                limit
            };
            if limit == 0 {
                return Err("no memory headroom available for shared admission".to_owned());
            }
            let mut pool = MemoryPool::new(limit);
            #[cfg(target_os = "linux")]
            {
                pool.pressure = Some(Mutex::new(pressure::Pressure::new(
                    limit,
                    observation.clone(),
                    host::observe,
                )));
            }
            pool.observation = Some(observation);
            Ok(Arc::new(pool))
        })
        .as_ref()
        .cloned()
        .map_err(|e| anyhow::anyhow!(e.clone()))
}

#[cfg(test)]
impl MemoryPool {
    pub(crate) fn pressure_test(limit: u64, headroom: Arc<AtomicU64>) -> Arc<Self> {
        let observe = move || host::Observation {
            observed_unix_ms: None,
            host_available_bytes: Some(headroom.load(Ordering::Relaxed)),
            cgroup_headroom_bytes: None,
            headroom_bytes: Some(headroom.load(Ordering::Relaxed)),
            complete: true,
            discovery: "injected pressure observation, not OS pressure".into(),
        };
        let observation = observe();
        let mut pool = Self::new(limit);
        pool.observation = Some(observation.clone());
        pool.pressure = Some(Mutex::new(pressure::Pressure::new(
            limit,
            observation,
            observe,
        )));
        Arc::new(pool)
    }
    fn force_pressure_check(&self) {
        self.pressure.as_ref().unwrap().lock().unwrap().make_due();
        self.recheck_pressure();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{Reservation, Workspace};
    #[test]
    fn pressure_rechecks_grandfather_owners_and_preserve_local_aggregate_rollback() -> Result<()> {
        let headroom = Arc::new(AtomicU64::new(64));
        let pool = MemoryPool::pressure_test(128, headroom.clone());
        let local = Arc::new(Workspace::shared(128, pool.clone()));
        let mut first = Reservation::for_workspace(local.clone());
        first.resize(64)?;
        pool.force_pressure_check();
        assert_eq!(pool.usage().admission_limit_bytes, 96);
        assert_eq!(pool.usage().pressure_baseline_reserved_bytes, Some(64));
        let mut second = Reservation::for_workspace(local.clone());
        second.resize(32)?;
        assert!(second.resize(33).is_err());
        assert_eq!(local.used(), 96);
        assert_eq!(pool.usage().reserved_bytes, 96);
        headroom.store(0, Ordering::Relaxed);
        pool.force_pressure_check();
        assert_eq!(pool.usage().admission_limit_bytes, 96);
        assert!(first.resize(65).is_err());
        first.resize(32)?;
        second.resize(64)?;
        assert_eq!(pool.usage().reserved_bytes, 96);
        // Restoring headroom cannot raise the immutable startup ceiling.
        headroom.store(u64::MAX, Ordering::Relaxed);
        pool.force_pressure_check();
        assert_eq!(pool.usage().admission_limit_bytes, 128);
        first.resize(64)?;
        drop(first);
        drop(second);
        assert_eq!(local.used(), 0);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn simultaneous_pressure_rechecks_and_grants_never_overcommit() -> Result<()> {
        let headroom = Arc::new(AtomicU64::new(80));
        let pool = MemoryPool::pressure_test(40, headroom.clone());
        let gate = Arc::new(std::sync::Barrier::new(9));
        let mut workers = Vec::new();
        for _ in 0..8 {
            let pool = pool.clone();
            let gate = gate.clone();
            workers.push(std::thread::spawn(move || -> Result<()> {
                let local = Arc::new(Workspace::shared(32, pool.clone()));
                for _ in 0..100 {
                    let mut reservation = Reservation::for_workspace(local.clone());
                    gate.wait();
                    let acquired = reservation.resize(9).is_ok();
                    gate.wait();
                    let usage = pool.usage();
                    assert!(usage.reserved_bytes <= usage.admission_limit_bytes);
                    assert_eq!(local.used(), if acquired { 9 } else { 0 });
                    gate.wait();
                    drop(reservation);
                    gate.wait();
                }
                Ok(())
            }));
        }
        for round in 0..100 {
            headroom.store(if round % 2 == 0 { 0 } else { 80 }, Ordering::Relaxed);
            gate.wait();
            pool.force_pressure_check();
            gate.wait();
            let usage = pool.usage();
            assert!(usage.reserved_bytes <= usage.admission_limit_bytes);
            assert!(usage.admission_limit_bytes <= 40);
            gate.wait();
            gate.wait();
        }
        for worker in workers {
            worker.join().unwrap()?;
        }
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert_eq!(pool.usage().pressure_rechecks, 100);
        Ok(())
    }
    #[test]
    fn local_and_aggregate_edges_rollback_and_independent_lifetimes() -> Result<()> {
        for limit in [63, 64, 65] {
            let pool = Arc::new(MemoryPool::new(limit));
            let a = Arc::new(Workspace::shared(64, pool.clone()));
            let b = Arc::new(Workspace::shared(64, pool.clone()));
            let mut first = Reservation::for_workspace(a.clone());
            first.resize(32)?;
            let mut second = Reservation::for_workspace(b.clone());
            assert_eq!(second.resize(32).is_ok(), limit >= 64);
            assert_eq!(a.used(), 32);
            assert_eq!(b.used(), if limit >= 64 { 32 } else { 0 });
            assert_eq!(pool.usage().reserved_bytes, a.used() + b.used());
            assert!(first.resize(65).is_err());
            assert_eq!(a.used(), 32);
            assert_eq!(pool.usage().reserved_bytes, a.used() + b.used());
            drop(first);
            drop(a);
            second.resize(32)?;
            drop(b);
            assert_eq!(pool.usage().reserved_bytes, 32);
            drop(second);
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert!(pool.usage().peak_reserved_bytes <= limit);
        }
        Ok(())
    }
    #[test]
    fn simultaneous_acquisitions_never_overgrant_and_retry_after_release() -> Result<()> {
        let pool = Arc::new(MemoryPool::new(40));
        let gate = Arc::new(std::sync::Barrier::new(9));
        let mut workers = Vec::new();
        for _ in 0..8 {
            let pool = pool.clone();
            let gate = gate.clone();
            workers.push(std::thread::spawn(move || -> Result<()> {
                let local = Arc::new(Workspace::shared(32, pool.clone()));
                for _ in 0..100 {
                    let mut reservation = Reservation::for_workspace(local.clone());
                    gate.wait();
                    let acquired = reservation.resize(9).is_ok();
                    gate.wait();
                    assert!(pool.usage().reserved_bytes <= 40);
                    assert_eq!(local.used(), if acquired { 9 } else { 0 });
                    gate.wait();
                    drop(reservation);
                    gate.wait();
                    assert_eq!(local.used(), 0);
                }
                Ok(())
            }));
        }
        for _ in 0..100 {
            gate.wait();
            gate.wait();
            assert!(pool.usage().reserved_bytes <= 40);
            gate.wait();
            gate.wait();
        }
        for worker in workers {
            worker.join().unwrap()?;
        }
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert_eq!(pool.usage().peak_reserved_bytes, 36);
        let mut retry = Reservation::for_workspace(Arc::new(Workspace::shared(40, pool.clone())));
        retry.resize(40)?;
        drop(retry);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use crate::{
        core::{Job, Operation, Shuffle},
        engine::prepare_with_memory_pool,
        profile::ProfileCache,
        storage::{Reservation, Workspace},
    };
    use std::{fmt::Write as _, sync::atomic::AtomicBool};

    #[test]
    fn mid_ingestion_pressure_spills_with_exact_order_and_row_conservation() -> Result<()> {
        let (dir, mut job) = fixture()?;
        let count: usize = 100_000;
        let mut text = String::from("id");
        for c in 0..32 {
            text.push_str(&format!(",c{c}"));
        }
        text.push('\n');
        for id in 0..count {
            write!(text, "{id},\"界,{}", id % 7)?;
            if id.is_multiple_of(1000) {
                text.push_str("\nquoted");
            }
            text.push('"');
            for c in 1..32 {
                if id == 80000 && c == 1 {
                    text.push(',');
                    text.push_str(&"界".repeat(600000));
                } else {
                    text.push(',');
                    text.push((b'0' + ((id + c) % 10) as u8) as char);
                }
            }
            text.push('\n');
        }
        std::fs::write(&job.input, text)?;
        job.resources.memory_mb = 256.into();
        job.resources.max_record_bytes = 2 * 1024 * 1024;
        job.operations.push(Operation::Balanced { files: 4 });
        for workers in [1, 4] {
            job.resources.workers = workers;
            job.output = dir
                .path()
                .join(format!("reference-{workers}"))
                .to_string_lossy()
                .into();
            let baseline = prepare_with_memory_pool(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(MemoryPool::new(128 * 1024 * 1024)),
            )?;
            assert_eq!(baseline.analysis.diagnostics["sort_runs"], 0);
            let expected = baseline.execute()?;
            let reference = std::path::PathBuf::from(&job.output);
            for headroom_mib in [8u64, 16] {
                job.output = dir
                    .path()
                    .join(format!("pressure-{workers}-{headroom_mib}"))
                    .to_string_lossy()
                    .into();
                let headroom = Arc::new(AtomicU64::new(256 * 1024 * 1024));
                let pool = MemoryPool::pressure_test(128 * 1024 * 1024, headroom.clone());
                let p = pool.clone();
                let changed = Arc::new(AtomicBool::new(false));
                let switched = changed.clone();
                let notify: crate::storage::Notify = Arc::new(move |progress| {
                    if progress.phase == "Reading and validating CSV"
                        && progress.rows >= 65536
                        && !switched.swap(true, Ordering::Relaxed)
                    {
                        headroom.store(headroom_mib * 1024 * 1024, Ordering::Relaxed);
                        p.force_pressure_check();
                    }
                });
                let attempt = (|| -> Result<_> {
                    let prepared = prepare_with_memory_pool(
                        job.clone(),
                        Arc::new(AtomicBool::new(false)),
                        notify,
                        pool.clone(),
                    )?;
                    assert!(changed.load(Ordering::Relaxed));
                    assert!(prepared.analysis.diagnostics["sort_runs"].as_u64().unwrap() > 0);
                    assert!(pool.usage().pressure_rechecks > 0);
                    let pressure_usage = pool.usage();
                    let actual = prepared.execute()?;
                    Ok((actual, pressure_usage))
                })();
                let (actual, pressure_usage) = attempt?;
                // Verifier-owned JSON copies do not retain engine owners across final-drop checks.
                let pressure_diagnostics = serde_json::to_value(&actual.diagnostics)?;
                let expected_diagnostics = serde_json::to_value(&expected.diagnostics)?;
                assert_eq!(actual.logical_digest, expected.logical_digest);
                assert_eq!(
                    serde_json::to_value(&actual.stages)?,
                    serde_json::to_value(&expected.stages)?
                );
                let mut seen = vec![false; count];
                for entry in std::fs::read_dir(&job.output)? {
                    let entry = entry?;
                    if entry.path().extension() != Some(std::ffi::OsStr::new("csv")) {
                        continue;
                    }
                    let bytes = std::fs::read(entry.path())?;
                    assert_eq!(bytes, std::fs::read(reference.join(entry.file_name()))?);
                    let mut parser = crate::core::csv::Parser::new(
                        std::io::Cursor::new(bytes),
                        job.output_csv.clone(),
                        job.resources.max_record_bytes,
                    );
                    assert_eq!(parser.next_record()?.unwrap().len(), 33);
                    while let Some(fields) = parser.next_record()? {
                        let id: usize = fields[0].parse()?;
                        assert!(id < count && !seen[id]);
                        seen[id] = true;
                        assert_eq!(
                            fields[1],
                            format!(
                                "界,{}{}",
                                id % 7,
                                if id.is_multiple_of(1000) {
                                    "\nquoted"
                                } else {
                                    ""
                                }
                            )
                        );
                        for c in 1..32 {
                            if id == 80000 && c == 1 {
                                assert_eq!(fields[c + 1], "界".repeat(600000));
                            } else {
                                assert_eq!(fields[c + 1], ((id + c) % 10).to_string());
                            }
                        }
                    }
                }
                assert!(seen.into_iter().all(|v| v));
                let outputs = |path: &std::path::Path| -> Result<Vec<serde_json::Value>> {
                    Ok(std::fs::read_to_string(path.join("manifest.jsonl"))?
                        .lines()
                        .map(serde_json::from_str::<serde_json::Value>)
                        .collect::<std::result::Result<Vec<_>, _>>()?
                        .into_iter()
                        .filter(|v| v["type"] == "output")
                        .collect())
                };
                assert_eq!(
                    outputs(&reference)?,
                    outputs(std::path::Path::new(&job.output))?
                );
                let retained_preview = actual.preview.reserved_bytes();
                let retained_summaries = actual.column_values.reserved_bytes();
                let retained_stages = actual.stages.reserved_bytes();
                let retained_text = actual.text_reserved_bytes();
                let retained_diagnostics = actual.diagnostics.reserved_bytes();
                let retained_notes =
                    actual.warnings.reserved_bytes() + actual.timings.reserved_bytes();
                let retained_header = actual
                    .header
                    .as_ref()
                    .map_or(0, |header| header.reserved_bytes());
                assert_eq!(
                    pool.usage().reserved_bytes,
                    retained_preview
                        + retained_header
                        + retained_summaries
                        + retained_stages
                        + retained_text
                        + retained_notes
                        + retained_diagnostics
                );
                let logical_digest = actual.logical_digest.to_string();
                drop(actual);
                assert_eq!(pool.usage().reserved_bytes, 0);
                println!(
                    "{}",
                    serde_json::json!({
                        "type":"injected_pressure_complete_job", "workers":workers, "rows":count,
                        "fields":33, "late_wide_payload_bytes":1800000, "quoted_newlines":true,
                        "pressure_after_rows":65536, "injected_additional_headroom_bytes":headroom_mib * 1024 * 1024,
                        "scope":"deterministic ledger/admission test; not OS/cgroup pressure or throughput evidence",
                        "before":expected_diagnostics, "after":pressure_diagnostics,
                        "pressure_usage":pressure_usage, "logical_digest":logical_digest,
                        "retained_preview_bytes_before_drop":retained_preview,
                        "retained_header_bytes_before_drop":retained_header,
                        "retained_summary_bytes_before_drop":retained_summaries,
                        "retained_stage_bytes_before_drop":retained_stages,
                        "retained_text_bytes_before_drop":retained_text,
                        "retained_warning_timing_bytes_before_drop":retained_notes,
                        "retained_diagnostic_bytes_before_drop":retained_diagnostics,
                        "exact_output_metadata_parity":true, "independent_id_field_conservation":true,
                        "reserved_bytes_after_drop":pool.usage().reserved_bytes, "verified":true
                    })
                );
            }
        }
        Ok(())
    }

    #[test]
    fn pressure_denies_cached_copy_and_publication_without_revoking_other_owners() -> Result<()> {
        let (dir, job) = fixture()?;
        let headroom = Arc::new(AtomicU64::new(128 * 1024 * 1024));
        let pool = MemoryPool::pressure_test(64 * 1024 * 1024, headroom.clone());
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let returned = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let retained = pool.usage().reserved_bytes;
        headroom.store(0, Ordering::Relaxed);
        pool.force_pressure_check();
        assert!(cache
            .profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
            .is_err());
        assert_eq!(pool.usage().reserved_bytes, retained);
        headroom.store(128 * 1024 * 1024, Ordering::Relaxed);
        pool.force_pressure_check();
        let p = pool.clone();
        let signal = headroom.clone();
        let notify: crate::storage::Notify = Arc::new(move |progress| {
            if progress.phase == "Finalizing output snapshot" {
                signal.store(0, Ordering::Relaxed);
                p.force_pressure_check();
            }
        });
        let prepared = prepare_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            notify,
            pool.clone(),
        )?;
        assert!(prepared.execute().is_err());
        assert!(!std::path::Path::new(&job.output).exists());
        assert_eq!(pool.usage().reserved_bytes, retained);
        assert!(!std::fs::read_dir(dir.path())?.any(|e| {
            let name = e.unwrap().file_name();
            let name = name.to_string_lossy();
            name.starts_with("chopper-") || name.starts_with(".chopper-staging-")
        }));
        headroom.store(128 * 1024 * 1024, Ordering::Relaxed);
        pool.force_pressure_check();
        let retried = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(retried.cache_hit, !cfg!(windows));
        prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?
        .execute()?;
        drop(returned);
        drop(retried);
        drop(cache);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    fn fixture() -> Result<(tempfile::TempDir, Job)> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let mut text = String::from("id,label\n");
        for id in 0..2000 {
            text.push_str(&format!("{id},\"界,{}\"\n", id % 7));
        }
        std::fs::write(&input, text)?;
        let mut job = Job {
            input: input.to_string_lossy().into(),
            output: dir.path().join("out").to_string_lossy().into(),
            random_seed: Some("shared-v1".into()),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }],
            ..Job::default()
        };
        job.resources.memory_mb = 32.into();
        job.resources.max_record_bytes = 1024 * 1024;
        job.resources.workers = 1;
        job.resources.temp_dir = Some(dir.path().to_string_lossy().into());
        Ok((dir, job))
    }
    #[test]
    fn cached_returned_profiles_and_two_prepared_jobs_share_final_owner_accounting() -> Result<()> {
        let (dir, mut job) = fixture()?;
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let returned = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let cached_and_returned = pool.usage().reserved_bytes;
        assert!(cached_and_returned > 0);
        let returned_copy = returned.try_clone()?;
        assert!(pool.usage().reserved_bytes > cached_and_returned);
        let profiles = pool.usage().reserved_bytes;
        let first = prepare_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        job.output = dir.path().join("out2").to_string_lossy().into();
        let second = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let retained = first.ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap()
            + second.ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap();
        assert!(retained > 0);
        assert_eq!(pool.usage().reserved_bytes, profiles + retained);
        drop(returned);
        drop(returned_copy);
        cache.clear();
        assert_eq!(pool.usage().reserved_bytes, retained);
        first.execute()?;
        second.execute()?;
        assert_eq!(
            std::fs::read(dir.path().join("out/part-00000001.csv"))?,
            std::fs::read(dir.path().join("out2/part-00000001.csv"))?
        );
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    #[test]
    fn denied_preparation_and_cancelled_profile_keep_other_owners_and_retry_cleanly() -> Result<()>
    {
        let (dir, job) = fixture()?;
        let limit = 16 * 1024 * 1024;
        let pool = Arc::new(MemoryPool::new(limit));
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let returned = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let retained = pool.usage().reserved_bytes;
        let mut other =
            Reservation::for_workspace(Arc::new(Workspace::shared(limit as usize, pool.clone())));
        other.resize((limit - retained - 1024) as usize)?;
        let failed = prepare_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        );
        assert!(failed.is_err());
        assert!(!dir.path().join("out").exists());
        assert_eq!(pool.usage().reserved_bytes, limit - 1024);
        assert!(!std::fs::read_dir(dir.path())?.any(|e| e
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with("chopper-")));
        assert!(cache
            .profile(&job, Arc::new(AtomicBool::new(true)), Arc::new(|_| {}))
            .is_err());
        assert_eq!(pool.usage().reserved_bytes, limit - 1024);
        drop(other);
        assert_eq!(pool.usage().reserved_bytes, retained);
        let retried = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(retried.cache_hit, !cfg!(windows));
        let prepared = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        prepared.execute()?;
        assert!(dir.path().join("out/manifest.jsonl").is_file());
        drop(returned);
        drop(retried);
        drop(cache);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
}

#[cfg(test)]
mod automatic_memory_tests {
    use super::*;
    use chopper_core::{Job, MemoryBudget, Resources};
    const MIB: u64 = 1024 * 1024;
    #[test]
    fn estimated_run_tier_falls_back_when_free_capacity_is_insufficient() -> Result<()> {
        let resources = Resources::automatic();
        for (free, wanted, resolved) in [
            (512 * MIB, [1024, 256], 1024),
            (512 * MIB - 1, [1024, 256], 256),
            (96 * MIB, [512, 256], 192),
            (768 * MIB, [2048, 1024], 1024),
            (512 * MIB - 1, [2048, 1024], 256),
        ] {
            let pool = MemoryPool::new(free);
            assert_eq!(
                pool.resolve_memory_for_run(&resources, wanted, 0)?,
                resolved
            );
            assert_eq!(pool.reservation_counts().0, 0);
        }
        let explicit = Resources {
            memory_mb: 512.into(),
            ..resources
        };
        assert_eq!(
            MemoryPool::new(1).resolve_memory_for_run(&explicit, [2048, 1024], 0)?,
            512
        );
        Ok(())
    }

    #[test]
    fn automatic_byte_boundaries_and_numeric_preservation() -> Result<()> {
        let mut resources = Resources {
            memory_mb: MemoryBudget::Auto,
            ..Resources::default()
        };
        for (free, expected) in [(128 * MIB, 256), (128 * MIB - 1, 255), (64 * MIB, 128)] {
            assert_eq!(MemoryPool::new(free).resolve_memory(&resources)?, expected);
        }
        let error = MemoryPool::new(64 * MIB - 1)
            .resolve_memory(&resources)
            .unwrap_err()
            .to_string();
        assert!(error.contains("resolved memory budget 127 MiB"));
        assert!(error.contains("requires at least 128 MiB"));
        assert_eq!(
            resources.max_record_bytes,
            Resources::default().max_record_bytes
        );
        assert_eq!(
            MemoryPool::new(1).resolve_memory(&Resources::default())?,
            256
        );
        resources.max_record_bytes = 1;
        assert_eq!(MemoryPool::new(16 * MIB).resolve_memory(&resources)?, 32);
        assert!(MemoryPool::new(16 * MIB - 1)
            .resolve_memory(&resources)
            .is_err());
        resources.memory_mb = 512.into();
        assert_eq!(MemoryPool::new(1).resolve_memory(&resources)?, 512);
        Ok(())
    }
    #[test]
    fn automatic_observation_accounts_for_live_grants_and_pressure() -> Result<()> {
        let resources = Resources {
            memory_mb: MemoryBudget::Auto,
            max_record_bytes: 1,
            ..Resources::default()
        };
        let headroom = Arc::new(AtomicU64::new(256 * MIB));
        let pool = MemoryPool::pressure_test(128 * MIB, headroom.clone());
        pool.acquire(64 * MIB)?;
        assert_eq!(pool.resolve_memory(&resources)?, 128);
        assert_eq!(pool.usage().reserved_bytes, 64 * MIB);
        headroom.store(32 * MIB, Ordering::Relaxed);
        pool.force_pressure_check();
        assert_eq!(pool.resolve_memory(&resources)?, 32);
        pool.acquire(16 * MIB)?;
        assert!(pool.acquire(1).is_err());
        assert!(pool.resolve_memory(&resources).is_err());
        pool.release(80 * MIB);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    #[test]
    fn automatic_prepared_execution_retains_resolution_and_requested_manifest() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let output = dir.path().join("output");
        std::fs::write(&input, b"id\n1\n2\n")?;
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            resources: Resources {
                memory_mb: MemoryBudget::Auto,
                workers: 1,
                max_record_bytes: 1024,
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        };
        let pool = Arc::new(MemoryPool::new(64 * MIB));
        let prepared = crate::engine::prepare_with_memory_pool(
            job,
            Arc::new(std::sync::atomic::AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        assert_eq!(prepared.job.resources.memory_mb, MemoryBudget::Auto);
        assert_eq!(prepared.ctx.memory as u64, 128 * MIB);
        assert_eq!(prepared.analysis.memory_budget_bytes, 128 * MIB);
        // Live prepared owners reduce a fresh automatic observation below 128 MiB.
        assert!(pool.resolve_memory(&prepared.job.resources)? < 128);
        prepared.execute()?;
        let manifest = std::fs::read_to_string(output.join("manifest.jsonl"))?;
        assert!(manifest.contains("\"memory_mb\":\"auto\""));
        assert!(manifest.contains("\"memory_budget_bytes\":134217728"));
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    #[test]
    fn automatic_denials_release_directory_and_configuration_owners() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let pool = Arc::new(MemoryPool::new(16 * MIB));
        let mut job = Job {
            input: "missing.csv".into(),
            resources: Resources {
                memory_mb: MemoryBudget::Auto,
                max_record_bytes: 1,
                temp_dir: Some(dir.path().join("missing").to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        };
        assert!(crate::engine::prepare_with_memory_pool(
            job.clone(),
            Arc::new(std::sync::atomic::AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone()
        )
        .is_err());
        assert_eq!(pool.usage().reserved_bytes, 0);
        job.resources.temp_dir = Some(dir.path().to_string_lossy().into_owned());
        job.input = "x".repeat(17 * MIB as usize);
        assert!(crate::engine::prepare_with_memory_pool(
            job,
            Arc::new(std::sync::atomic::AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone()
        )
        .is_err());
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert_eq!(std::fs::read_dir(dir.path())?.count(), 0);
        Ok(())
    }
}
