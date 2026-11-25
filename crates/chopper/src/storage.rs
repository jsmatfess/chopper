use anyhow::{ensure, Context as _, Result};
#[cfg(not(target_os = "wasi"))]
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::{
    cmp::Ordering,
    collections::BinaryHeap,
    fs::File,
    io::{self, BufRead, BufReader, BufWriter, Read, Seek, SeekFrom, Write},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering as AtomicOrdering},
        Arc, Mutex,
    },
};
use tempfile::{NamedTempFile, TempDir};
mod adaptive;
mod frame_key;
use frame_key::FrameKey;
mod progress_phase;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use progress_phase::resource_contracts as progress_resource_contracts;
pub use progress_phase::ProgressPhase;
mod catalog;
#[cfg(feature = "experimental-shuffle-partition")]
pub(crate) mod decision_audit;
pub(crate) mod diagnostics;
pub(crate) mod json_estimate;
mod json_lines;
#[cfg(feature = "experimental-spill-blocks")]
mod spill_blocks;
#[cfg(all(
    feature = "experimental-spill-blocks",
    any(test, feature = "resource-contract-tests")
))]
pub(crate) use spill_blocks::resource_contracts as spill_block_resource_contracts;
#[cfg(feature = "experimental-spill-blocks")]
use spill_blocks::{SpillFile, SpillReader};
#[cfg(not(feature = "experimental-spill-blocks"))]
type SpillFile = DiskFile;
#[cfg(not(feature = "experimental-spill-blocks"))]
type SpillReader = DiskReader;
pub(crate) use adaptive::PackedKey;
pub(crate) use adaptive::Workspace;
use adaptive::{reserve_row_capacity, ResidentRows, RoutedRows, Router};
pub use adaptive::{FieldViews, PackedRow};
pub(crate) use adaptive::{Reservation, ResidentShuffle};
use catalog::Catalog;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use json_lines::resource_contracts::group_catalog as group_catalog_resource_contracts;
pub use json_lines::ChargedJson;
pub(crate) use json_lines::{
    map_entry_allowance as json_map_entry_allowance, JsonCapacity, JsonLines,
};

mod job_directory;
mod temp_path;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use job_directory::resource_contracts::run as directory_resource_contracts;
pub use job_directory::JobDirectory;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use temp_path::resource_contracts::run as temporary_construction_resource_contracts;

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct Progress {
    pub phase: ProgressPhase,
    pub rows: u64,
    pub temp_bytes: u64,
}
pub type Notify = Arc<dyn Fn(Progress) + Send + Sync>;
pub struct Budget {
    #[cfg(target_os = "wasi")]
    hosted_deflate: std::sync::OnceLock<crate::output::HostedDeflateLease>,
    observation_enabled: AtomicBool,
    observation_visits: AtomicU64,
    observation_attempts: AtomicU64,
    #[cfg(feature = "experimental-shuffle-partition")]
    decision_audit: Mutex<decision_audit::DecisionAudit>,
    cleanup_failures: AtomicU64,
    first_cleanup_failure: Mutex<Option<CleanupFailure>>,
    written: AtomicU64,
    read: AtomicU64,
    files_created: AtomicU64,
    live_files: AtomicU64,
    path_bytes: AtomicU64,
    peak_files: AtomicU64,
    sort_runs: AtomicU64,
    merge_operations: AtomicU64,
    merge_inputs: AtomicU64,
    peak_merge_fan_in: AtomicU64,
    retained_exact_writers: AtomicBool,
    retained_exact_fallbacks: AtomicU64,
    used_short_tail: AtomicBool,
    resident_sorts: AtomicU64,
    sort_calls: AtomicU64,
    sort_rows: AtomicU64,
    sort_nanoseconds: AtomicU64,
    fisher_yates_calls: AtomicU64,
    fisher_yates_rows: AtomicU64,
    fisher_yates_nanoseconds: AtomicU64,
    routed_groups: AtomicU64,
    routing_fallbacks: AtomicU64,
    routing_reused_runs: AtomicU64,
    compact_spill_files: AtomicU64,
    compact_spill_blocks: AtomicU64,
    compact_spill_rows: AtomicU64,
    compact_spill_source_bytes: AtomicU64,
    compact_spill_stored_bytes: AtomicU64,
    compact_spill_fallbacks: AtomicU64,
    shuffle_partition_fusions: AtomicU64,
    shuffle_partition_rows: AtomicU64,
    input_record_bytes: AtomicU64,
    peak_bounded_writer_slots: AtomicU64,
    peak_deflate_workers: AtomicU64,
    probabilistic_shuffle_attempts: AtomicU64,
    probabilistic_shuffle_retries: AtomicU64,
    indexed_exact_quota_scopes: AtomicU64,
    shuffle_partition_retries: AtomicU64,
    consecutive_partition_fusions: AtomicU64,
    consecutive_partition_rows: AtomicU64,
    consecutive_partition_retries: AtomicU64,
    partition_balanced_fusions: AtomicU64,
    partition_balanced_rows: AtomicU64,
    partition_balanced_retries: AtomicU64,
    streaming_chain_fusions: AtomicU64,
    streaming_chain_rows: AtomicU64,
    streaming_chain_retries: AtomicU64,
    used: AtomicU64,
    peak: AtomicU64,
    maximum: u64,
    cancel: Arc<AtomicBool>,
    // Keep publication admission in the shared job state so it does not enlarge each sorter.
    run_destination: Mutex<crate::output::RunDestination>,
}
// Move the existing TempPath and its reservation here on the first failed
// unlink. No new path allocation is needed on an already-denied resource path.
struct CleanupFailure {
    path: tempfile::TempPath,
    _path_reservation: Reservation,
}

#[derive(Debug)]
pub(crate) struct Cancelled;
impl std::fmt::Display for Cancelled {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("job cancelled")
    }
}
impl std::error::Error for Cancelled {}
#[derive(Clone)]
pub struct Context {
    pub dir: Arc<JobDirectory>,
    budget: Arc<Budget>,
    pub memory: usize,
    pub max_record: usize,
    pub max_files: u64,
    pub notify: Notify,
    pub(crate) physical: Option<crate::observation::physical::Sink>,
    pub(crate) physical_operations: [usize; 2],
    pub(crate) physical_source: Option<u32>,
    pub(crate) physical_role: u8,
    pub(crate) direct_terminal_output: bool,
    pub(crate) auto_run: bool,
    pub(crate) auto_final_writers: bool,
    pub(crate) auto_final_sync: bool,
    pub(crate) auto_merge_ceiling: Option<usize>,
    pub(crate) auto_retained_exact: bool,
    pub(crate) auto_quota_index: bool,
    workspace: Arc<Workspace>,
    directory_path_bytes: Arc<AtomicU64>,
    grouping: chopper_core::Grouping,
    #[cfg(not(target_os = "wasi"))]
    pool: Arc<rayon::ThreadPool>,
}
// Reach the actual Run-created workspace without changing production admission,
// configuration or worker selection. Thread-local, one-shot and reset on unwind.
#[cfg(all(test, not(target_os = "wasi")))]
pub(crate) mod context_test_hook {
    use super::*;
    type Hook = Box<dyn FnOnce(&Context)>;
    thread_local! {
        static HOOK: std::cell::RefCell<Option<Hook>> = const { std::cell::RefCell::new(None) };
    }
    pub(crate) struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            HOOK.with(|hook| hook.borrow_mut().take());
        }
    }
    pub(crate) fn install(hook: impl FnOnce(Arc<Workspace>, usize) + 'static) -> Reset {
        HOOK.with(|slot| {
            assert!(slot.borrow().is_none());
            *slot.borrow_mut() = Some(Box::new(move |ctx| {
                hook(ctx.workspace.clone(), ctx.workers())
            }));
        });
        Reset
    }
    pub(super) fn created(ctx: &Context) {
        let hook = HOOK.with(|slot| slot.borrow_mut().take());
        if let Some(hook) = hook {
            hook(ctx);
        }
    }
}
impl Context {
    pub(crate) fn directory_reserved_bytes(&self) -> u64 {
        self.directory_path_bytes.load(AtomicOrdering::Relaxed)
    }
    #[cfg(any(
        test,
        all(
            feature = "resource-contract-tests",
            feature = "experimental-spill-blocks"
        )
    ))]
    fn replace_workspace_for_test(&mut self, mut workspace: Workspace) -> Result<()> {
        ensure!(
            self.workspace.used() == self.directory_reserved_bytes(),
            "cannot replace workspace with live algorithm owners"
        );
        // Existing algorithm-boundary tests specify their available algorithm
        // allowance. Keep the directory as an explicit additional owner.
        workspace.add_directory_allowance_for_test(self.directory_reserved_bytes());
        let workspace = Arc::new(workspace);
        Arc::get_mut(&mut self.dir)
            .context("test directory has other owners")?
            .rebind_for_test(workspace.clone())?;
        self.workspace = workspace;
        Ok(())
    }
    pub(crate) fn staging_directory(&self, parent: &std::path::Path) -> Result<JobDirectory> {
        self.check()?;
        JobDirectory::create(
            Some(parent),
            ".chopper-staging-",
            Reservation::new(self),
            self.directory_path_bytes.clone(),
        )
    }

    pub(crate) fn run_destination(
        &self,
    ) -> std::sync::MutexGuard<'_, crate::output::RunDestination> {
        self.budget
            .run_destination
            .lock()
            .expect("Run destination lock")
    }

    pub fn new(
        resources: &chopper_core::Resources,
        cancel: Arc<AtomicBool>,
        notify: Notify,
    ) -> Result<Self> {
        Self::with_memory_pool(
            resources,
            cancel,
            notify,
            crate::resources::process_memory()?,
        )
    }
    pub fn with_memory_pool(
        resources: &chopper_core::Resources,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        memory_pool: Arc<crate::resources::MemoryPool>,
    ) -> Result<Self> {
        Self::with_worker_limit(resources, cancel, notify, memory_pool, usize::MAX)
    }

    pub(crate) fn with_worker_limit(
        resources: &chopper_core::Resources,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        memory_pool: Arc<crate::resources::MemoryPool>,
        automatic_worker_limit: usize,
    ) -> Result<Self> {
        Self::with_run_limits(
            resources,
            cancel,
            notify,
            memory_pool,
            automatic_worker_limit,
            [256, 256],
        )
    }

    pub(crate) fn with_run_limits(
        resources: &chopper_core::Resources,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        memory_pool: Arc<crate::resources::MemoryPool>,
        automatic_worker_limit: usize,
        auto_memory_targets_mb: [u64; 2],
    ) -> Result<Self> {
        #[cfg(target_os = "wasi")]
        let _ = automatic_worker_limit;
        ensure!(!cancel.load(AtomicOrdering::Relaxed), "job cancelled");
        let memory_mb = memory_pool.resolve_memory_for_run(resources, auto_memory_targets_mb)?;
        let workspace = Arc::new(Workspace::shared(
            (memory_mb * 1024 * 1024 / 2) as usize,
            memory_pool,
        ));
        let directory_path_bytes = Arc::new(AtomicU64::new(0));
        let dir = JobDirectory::create(
            resources.temp_dir.as_deref().map(std::path::Path::new),
            "chopper-",
            Reservation::for_workspace(workspace.clone()),
            directory_path_bytes.clone(),
        )?;
        let maximum = if let Some(maximum) = resources.temp_bytes {
            resources.validate_temp_bytes()?;
            ensure!(
                maximum <= available_space(dir.path())?,
                "temporary-space budget exceeds available disk space"
            );
            maximum
        } else {
            u64::MAX
        };
        #[cfg(not(target_os = "wasi"))]
        let workers = crate::engine::auto::workers(resources, memory_mb, automatic_worker_limit);
        #[cfg(not(target_os = "wasi"))]
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(workers)
            .stack_size(1024 * 1024)
            .thread_name(|i| format!("chopper-sort-{i}"))
            .build()?;
        let context = Self {
            dir: Arc::new(dir),
            budget: Arc::new(Budget {
                #[cfg(target_os = "wasi")]
                hosted_deflate: std::sync::OnceLock::new(),
                observation_enabled: AtomicBool::new(true),
                observation_visits: AtomicU64::new(0),
                observation_attempts: AtomicU64::new(0),
                #[cfg(feature = "experimental-shuffle-partition")]
                decision_audit: Mutex::new(decision_audit::DecisionAudit::default()),
                cleanup_failures: AtomicU64::new(0),
                first_cleanup_failure: Mutex::new(None),
                written: AtomicU64::new(0),
                read: AtomicU64::new(0),
                files_created: AtomicU64::new(0),
                live_files: AtomicU64::new(0),
                path_bytes: AtomicU64::new(0),
                peak_files: AtomicU64::new(0),

                sort_runs: AtomicU64::new(0),
                merge_operations: AtomicU64::new(0),
                merge_inputs: AtomicU64::new(0),
                peak_merge_fan_in: AtomicU64::new(0),
                retained_exact_writers: AtomicBool::new(false),
                retained_exact_fallbacks: AtomicU64::new(0),
                used_short_tail: AtomicBool::new(false),
                resident_sorts: AtomicU64::new(0),
                sort_calls: AtomicU64::new(0),
                sort_rows: AtomicU64::new(0),
                sort_nanoseconds: AtomicU64::new(0),
                fisher_yates_calls: AtomicU64::new(0),
                fisher_yates_rows: AtomicU64::new(0),
                fisher_yates_nanoseconds: AtomicU64::new(0),
                routed_groups: AtomicU64::new(0),
                routing_fallbacks: AtomicU64::new(0),
                routing_reused_runs: AtomicU64::new(0),
                compact_spill_files: AtomicU64::new(0),
                compact_spill_blocks: AtomicU64::new(0),
                compact_spill_rows: AtomicU64::new(0),
                compact_spill_source_bytes: AtomicU64::new(0),
                compact_spill_stored_bytes: AtomicU64::new(0),
                compact_spill_fallbacks: AtomicU64::new(0),
                shuffle_partition_fusions: AtomicU64::new(0),
                shuffle_partition_rows: AtomicU64::new(0),
                input_record_bytes: AtomicU64::new(0),
                peak_bounded_writer_slots: AtomicU64::new(0),
                peak_deflate_workers: AtomicU64::new(0),
                probabilistic_shuffle_attempts: AtomicU64::new(0),
                probabilistic_shuffle_retries: AtomicU64::new(0),
                indexed_exact_quota_scopes: AtomicU64::new(0),
                shuffle_partition_retries: AtomicU64::new(0),
                consecutive_partition_fusions: AtomicU64::new(0),
                consecutive_partition_rows: AtomicU64::new(0),
                consecutive_partition_retries: AtomicU64::new(0),
                partition_balanced_fusions: AtomicU64::new(0),
                partition_balanced_rows: AtomicU64::new(0),
                partition_balanced_retries: AtomicU64::new(0),
                streaming_chain_fusions: AtomicU64::new(0),
                streaming_chain_rows: AtomicU64::new(0),
                streaming_chain_retries: AtomicU64::new(0),
                used: AtomicU64::new(0),
                peak: AtomicU64::new(0),
                maximum,
                cancel,
                run_destination: Mutex::new(crate::output::RunDestination::Unchecked),
            }),
            memory: (memory_mb * 1024 * 1024) as usize,
            max_record: resources.max_record_bytes,
            max_files: resources.max_files,
            notify,
            physical: None,
            physical_operations: [0; 2],
            physical_source: None,
            physical_role: 0,
            direct_terminal_output: false,
            auto_run: false,
            auto_final_writers: false,
            auto_final_sync: false,
            auto_merge_ceiling: None,
            auto_retained_exact: false,
            auto_quota_index: false,
            workspace,
            directory_path_bytes,
            grouping: resources.grouping,
            #[cfg(not(target_os = "wasi"))]
            pool: Arc::new(pool),
        };
        #[cfg(all(test, not(target_os = "wasi")))]
        context_test_hook::created(&context);
        Ok(context)
    }
    pub fn check(&self) -> Result<()> {
        if self.budget.cancel.load(AtomicOrdering::Relaxed) {
            return Err(Cancelled.into());
        }
        if self.budget.cleanup_failures.load(AtomicOrdering::Acquire) != 0 {
            let failure = self
                .budget
                .first_cleanup_failure
                .lock()
                .unwrap_or_else(|p| p.into_inner());
            if let Some(failure) = &*failure {
                anyhow::bail!(
                    "temporary cleanup failed for {}; job cannot continue",
                    failure.path.display()
                );
            }
            anyhow::bail!("temporary cleanup failed; job cannot continue");
        }
        Ok(())
    }
    #[cfg(all(
        any(test, feature = "resource-contract-tests"),
        any(target_os = "linux", windows, target_os = "wasi")
    ))]
    pub(crate) fn force_cleanup_error_for_test(&self) -> Result<std::path::PathBuf> {
        let mut file = self.file()?;
        file.write_all(b"abc")?;
        let path = file.file.as_ref().unwrap().path().to_owned();
        // A real unlink error independent of process UID or chmod behavior.
        std::fs::rename(&path, path.with_extension("retained"))?;
        std::fs::create_dir(&path)?;
        drop(file);
        Ok(path)
    }
    pub fn event(&self, phase: &'static str, rows: u64) -> Result<()> {
        self.check()?;
        self.pressure_boundary();
        (self.notify)(Progress {
            phase: ProgressPhase::literal(phase),
            rows,
            temp_bytes: self.used(),
        });
        Ok(())
    }
    /// Admit dynamic engine text before callback/cache replacement. A denial
    /// leaves the previous event intact and propagates through ordinary cleanup.
    pub fn dynamic_event(&self, phase: &str, rows: u64) -> Result<()> {
        self.check()?;
        self.pressure_boundary();
        let phase = ProgressPhase::copy(phase, Reservation::new(self))?;
        (self.notify)(Progress {
            phase,
            rows,
            temp_bytes: self.used(),
        });
        Ok(())
    }
    pub(crate) fn operation_event(&self, operation: usize, total: usize) -> Result<()> {
        use std::fmt::Write as _;
        let mut text = progress_phase::OperationText::default();
        write!(&mut text, "Preparing operation {operation} of {total}")
            .map_err(|_| anyhow::anyhow!("operation progress capacity overflow"))?;
        self.dynamic_event(text.as_str(), 0)
    }
    pub(crate) fn pressure_boundary(&self) {
        self.workspace.recheck_pressure();
    }
    pub(crate) fn input_record_bytes(&self, bytes: u64) {
        self.budget
            .input_record_bytes
            .store(bytes, AtomicOrdering::Relaxed);
    }

    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    pub(crate) fn validated_payload_bytes(&self) -> u64 {
        self.budget.input_record_bytes.load(AtomicOrdering::Relaxed)
    }

    pub(crate) fn working_headroom(&self) -> u64 {
        self.workspace.available_bytes()
    }

    pub(crate) fn publication_writer_limit(&self, nominal: usize, remaining_files: u64) -> usize {
        let per_writer = 16 * 1024 * 1024 + 2 * self.max_record as u64;
        let room = (self.workspace.available_bytes() / per_writer).max(1);
        nominal
            .min(usize::try_from(room.min(remaining_files.max(1))).unwrap_or(usize::MAX))
            .min(crate::engine::auto::descriptor_writer_ceiling(2).max(1))
    }

    pub(crate) fn bounded_writer_slots(&self, count: usize) {
        self.budget
            .peak_bounded_writer_slots
            .fetch_max(count as u64, AtomicOrdering::Relaxed);
    }
    pub(crate) fn deflate_workers(&self, count: usize) {
        self.budget
            .peak_deflate_workers
            .fetch_max(count as u64, AtomicOrdering::Relaxed);
    }
    #[cfg(target_os = "wasi")]
    pub(crate) fn hosted_deflate(&self) -> &std::sync::OnceLock<crate::output::HostedDeflateLease> {
        &self.budget.hosted_deflate
    }

    pub(crate) fn used_retained_exact_writers(&self) {
        self.budget
            .retained_exact_writers
            .store(true, AtomicOrdering::Relaxed);
    }

    pub(crate) fn retained_exact_fallback(&self) {
        self.budget
            .retained_exact_fallbacks
            .fetch_add(1, AtomicOrdering::Relaxed);
    }

    pub(crate) fn completed_measurements(&self) -> crate::engine::auto::RunMeasurements {
        crate::engine::auto::RunMeasurements {
            temporary_bytes_written: self.budget.written.load(AtomicOrdering::Relaxed),
            temporary_bytes_read: self.budget.read.load(AtomicOrdering::Relaxed),
            peak_merge_fan_in: self.budget.peak_merge_fan_in.load(AtomicOrdering::Relaxed),
            retained_exact_writers: self
                .budget
                .retained_exact_writers
                .load(AtomicOrdering::Relaxed),
            peak_workspace_reserved_bytes: self.workspace.peak(),
            retained_exact_fallbacks: self
                .budget
                .retained_exact_fallbacks
                .load(AtomicOrdering::Relaxed),
            used_short_tail: self.budget.used_short_tail.load(AtomicOrdering::Relaxed),
            peak_writer_slots: self
                .budget
                .peak_bounded_writer_slots
                .load(AtomicOrdering::Relaxed)
                .max(1),
            peak_deflate_workers: self
                .budget
                .peak_deflate_workers
                .load(AtomicOrdering::Relaxed),
        }
    }
    pub fn used(&self) -> u64 {
        self.budget.used.load(AtomicOrdering::Relaxed)
    }
    /// Caller-owned diagnostic JSON. Engine-retained results use the admitted
    /// Diagnostics capture path; this convenience accessor makes an explicit copy.
    pub fn diagnostics(&self) -> serde_json::Value {
        self.with_diagnostic_snapshot(|source| {
            serde_json::to_value(source).expect("diagnostic schema serializes")
        })
    }
    #[cfg(feature = "experimental-streaming-chain")]
    pub(crate) fn streaming_chain_fused(&self, rows: u64) {
        self.budget
            .streaming_chain_fusions
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.budget
            .streaming_chain_rows
            .fetch_add(rows, AtomicOrdering::Relaxed);
    }
    #[cfg(feature = "experimental-streaming-chain")]
    pub(crate) fn streaming_chain_retry(&self) {
        self.budget
            .streaming_chain_retries
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    #[cfg(feature = "experimental-partition-balanced")]
    pub(crate) fn partition_balanced_retry(&self) {
        self.budget
            .partition_balanced_retries
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    #[cfg(feature = "experimental-partition-balanced")]
    pub(crate) fn partition_balanced_fused(&self, rows: u64) {
        self.budget
            .partition_balanced_fusions
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.budget
            .partition_balanced_rows
            .fetch_add(rows, AtomicOrdering::Relaxed);
    }
    pub(crate) fn shuffle_partition_fused(&self, rows: u64) {
        self.budget
            .shuffle_partition_fusions
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.budget
            .shuffle_partition_rows
            .fetch_add(rows, AtomicOrdering::Relaxed);
    }
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    pub(crate) fn probabilistic_shuffle_attempt(&self) {
        self.budget
            .probabilistic_shuffle_attempts
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    pub(crate) fn probabilistic_shuffle_retry(&self) {
        self.budget
            .probabilistic_shuffle_retries
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    #[cfg(target_os = "linux")]
    pub(crate) fn indexed_exact_quota_scope(&self) {
        self.budget
            .indexed_exact_quota_scopes
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    pub(crate) fn shuffle_partition_retry(&self) {
        self.budget
            .shuffle_partition_retries
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    pub fn peak(&self) -> u64 {
        self.budget.peak.load(AtomicOrdering::Relaxed)
    }
    #[cfg(feature = "experimental-consecutive-partitions")]
    pub(crate) fn consecutive_partitions_fused(&self, rows: u64) {
        self.budget
            .consecutive_partition_fusions
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.budget
            .consecutive_partition_rows
            .fetch_add(rows, AtomicOrdering::Relaxed);
    }
    #[cfg(feature = "experimental-consecutive-partitions")]
    pub(crate) fn consecutive_partitions_retry(&self) {
        self.budget
            .consecutive_partition_retries
            .fetch_add(1, AtomicOrdering::Relaxed);
    }
    pub fn workers(&self) -> usize {
        #[cfg(not(target_os = "wasi"))]
        {
            self.pool.current_num_threads()
        }
        #[cfg(target_os = "wasi")]
        {
            1
        }
    }
    pub fn remaining_temp(&self) -> u64 {
        self.budget.maximum.saturating_sub(self.used())
    }
    /// Run already-admitted batch slots without allocating a collected result Vec.
    pub(crate) fn for_each_batch<T: Send>(
        &self,
        items: &mut [T],
        f: impl Fn(&mut T) + Sync + Send,
    ) {
        #[cfg(not(target_os = "wasi"))]
        self.pool.install(|| items.par_iter_mut().for_each(f));
        #[cfg(target_os = "wasi")]
        items.iter_mut().for_each(f);
    }
    pub fn file(&self) -> Result<DiskFile> {
        self.check()?;
        // Name scratch is inline; the constructed/boxed path retains its own
        // grant through the file, error-free reopen and failed-unlink owner.
        let path_bytes = self.file_path_bytes()?;
        let (file, path_reservation) = temp_path::file(self.dir.path(), Reservation::new(self))?;
        ensure!(
            file.path().as_os_str().len() == path_bytes,
            "temporary file path exceeds reserved size"
        );
        self.budget
            .files_created
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.budget
            .path_bytes
            .fetch_add(path_bytes as u64, AtomicOrdering::Relaxed);
        let live = self.budget.live_files.fetch_add(1, AtomicOrdering::Relaxed) + 1;
        self.budget
            .peak_files
            .fetch_max(live, AtomicOrdering::Relaxed);
        Ok(DiskFile {
            file: Some(file),
            budget: self.budget.clone(),
            bytes: 0,
            _path_reservation: path_reservation,
        })
    }
    fn spill_file(&self) -> Result<SpillFile> {
        #[cfg(feature = "experimental-spill-blocks")]
        {
            SpillFile::new(self)
        }
        #[cfg(not(feature = "experimental-spill-blocks"))]
        {
            self.file()
        }
    }
    fn spill_writer(&self, capacity: usize) -> Result<BufWriter<SpillFile>> {
        let file = self.spill_file()?;
        #[cfg(feature = "experimental-spill-blocks")]
        {
            file.buffered(capacity)
        }
        #[cfg(not(feature = "experimental-spill-blocks"))]
        {
            Ok(BufWriter::with_capacity(capacity, file))
        }
    }
    fn file_path_bytes(&self) -> Result<usize> {
        self.dir
            .path()
            .as_os_str()
            .len()
            .checked_add(1 + TEMP_FILE_NAME_BYTES)
            .context("temporary file path size overflow")
    }
}
const TEMP_FILE_PREFIX: &str = ".tmp";
const TEMP_FILE_RANDOM_BYTES: usize = 6;
const TEMP_FILE_NAME_BYTES: usize = TEMP_FILE_PREFIX.len() + TEMP_FILE_RANDOM_BYTES;
pub(crate) const DISK_READ_BUFFER: usize = 64 * 1024;
const DATASET_WRITE_BUFFER: usize = 64 * 1024;
const CATALOG_WRITE_BUFFER: usize = 8 * 1024;

/// Counts bytes returned by file reads, including buffered read-ahead; not physical I/O.
pub struct DiskReader {
    file: File,
    budget: Arc<Budget>,
}
impl Read for DiskReader {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let count = self.file.read(buffer)?;
        self.budget
            .read
            .fetch_add(count as u64, AtomicOrdering::Relaxed);
        Ok(count)
    }
}
impl Seek for DiskReader {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        self.file.seek(position)
    }
}
pub struct DiskFile {
    file: Option<NamedTempFile>,
    budget: Arc<Budget>,
    bytes: u64,
    _path_reservation: Reservation,
}
impl DiskFile {
    pub fn reader(&self) -> Result<BufReader<DiskReader>> {
        Ok(BufReader::with_capacity(
            DISK_READ_BUFFER,
            self.unbuffered_reader()?,
        ))
    }
    /// Independent offset and the same controlled temporary file identity.
    pub(crate) fn unbuffered_reader(&self) -> Result<DiskReader> {
        Ok(DiskReader {
            file: temp_path::reopen(self.file.as_ref().expect("temporary file already closed"))?,
            budget: self.budget.clone(),
        })
    }
    pub fn len(&self) -> u64 {
        self.bytes
    }
    pub fn is_empty(&self) -> bool {
        self.bytes == 0
    }
}
impl Write for DiskFile {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.budget.cancel.load(AtomicOrdering::Relaxed) {
            return Err(io::Error::other("job cancelled"));
        }
        let count = buf.len() as u64;
        #[allow(deprecated)] // Keep support for Rust releases predating AtomicU64::try_update.
        self.budget
            .used
            .fetch_update(AtomicOrdering::Relaxed, AtomicOrdering::Relaxed, |used| {
                used.checked_add(count)
                    .filter(|n| *n <= self.budget.maximum)
            })
            .map_err(|_| io::Error::other("temporary-space budget exhausted"))?;
        match self
            .file
            .as_mut()
            .expect("temporary file already closed")
            .write(buf)
        {
            Ok(n) => {
                self.budget
                    .used
                    .fetch_sub(count - n as u64, AtomicOrdering::Relaxed);
                self.budget
                    .written
                    .fetch_add(n as u64, AtomicOrdering::Relaxed);
                self.bytes += n as u64;
                self.budget.peak.fetch_max(
                    self.budget.used.load(AtomicOrdering::Relaxed),
                    AtomicOrdering::Relaxed,
                );
                Ok(n)
            }
            Err(error) => {
                self.budget.used.fetch_sub(count, AtomicOrdering::Relaxed);
                Err(error)
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        self.file
            .as_mut()
            .expect("temporary file already closed")
            .flush()
    }
}
impl Drop for DiskFile {
    fn drop(&mut self) {
        let Some(file) = self.file.take() else {
            return;
        };
        let mut path = file.into_temp_path(); // Close the handle before unlink.
                                              // We own explicit removal below. Avoid a second implicit unlink, which
                                              // could hide failure or remove a subsequently recreated path.
        path.disable_cleanup(true);
        let path_bytes = path.as_os_str().len() as u64;
        let removed = match std::fs::remove_file(&path) {
            Ok(()) => true,
            Err(error) if error.kind() == io::ErrorKind::NotFound => true,
            Err(error) => {
                eprintln!("chopper: cleanup failed for {}: {error}", path.display());
                false
            }
        };
        if removed {
            self.budget
                .path_bytes
                .fetch_sub(path_bytes, AtomicOrdering::Relaxed);
            self.budget.live_files.fetch_sub(1, AtomicOrdering::Relaxed);
            self.budget
                .used
                .fetch_sub(self.bytes, AtomicOrdering::Relaxed);
        } else {
            let mut failure = self
                .budget
                .first_cleanup_failure
                .lock()
                .unwrap_or_else(|p| p.into_inner());
            if failure.is_none() {
                let empty = self._path_reservation.sibling();
                let reservation = std::mem::replace(&mut self._path_reservation, empty);
                *failure = Some(CleanupFailure {
                    path,
                    _path_reservation: reservation,
                });
            } else {
                // Only the first error needs retained path ownership. Every
                // orphan's data/live-file charge remains conservative, and the
                // job-directory guard still cleans the entire workspace.
                self.budget
                    .path_bytes
                    .fetch_sub(path_bytes, AtomicOrdering::Relaxed);
            }
            self.budget
                .cleanup_failures
                .fetch_add(1, AtomicOrdering::Release);
        }
    }
}

#[cfg(all(test, any(target_os = "linux", windows)))]
mod cleanup_tests {
    use super::*;

    #[test]
    fn concurrent_failed_unlinks_keep_one_path_owner_and_all_orphan_bytes() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let directory = ctx.dir.path().to_owned();
        let mut files = [ctx.file()?, ctx.file()?];
        let mut paths = Vec::new();
        for file in &mut files {
            file.write_all(b"abc")?;
            let path = file.file.as_ref().unwrap().path().to_owned();
            std::fs::rename(&path, path.with_extension("retained"))?;
            std::fs::create_dir(&path)?;
            paths.push(path);
        }
        let path_bytes = paths[0].as_os_str().len() as u64;
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + 2 * path_bytes
        );
        std::thread::scope(|scope| {
            for file in files {
                scope.spawn(move || drop(file));
            }
        });
        let error = ctx.check().unwrap_err().to_string();
        assert!(paths
            .iter()
            .any(|path| error.contains(&path.display().to_string())));
        assert_eq!(ctx.diagnostics()["temporary_cleanup_failures"], 2);
        assert_eq!(ctx.used(), 6);
        assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 2);
        assert_eq!(
            ctx.diagnostics()["temporary_path_reserved_bytes"],
            path_bytes
        );
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + path_bytes
        );
        assert_eq!(
            pool.usage().reserved_bytes,
            ctx.directory_reserved_bytes() + path_bytes
        );
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert!(!directory.exists());
        Ok(())
    }

    #[test]
    fn failed_unlink_retains_temp_charge_and_prevents_continued_execution() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let directory = ctx.dir.path().to_owned();
        let path = ctx.force_cleanup_error_for_test()?;
        let error = ctx.check().expect_err("unlink failure must stop the job");
        assert!(error.to_string().contains("cleanup"));
        assert!(error.to_string().contains(&path.display().to_string()));
        assert_eq!(ctx.used(), 3, "failed removal must not reclaim temp bytes");
        assert_eq!(ctx.diagnostics()["temporary_cleanup_failures"], 1);
        assert!(
            pool.usage().reserved_bytes > 0,
            "failed-path ownership stays charged"
        );
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert!(
            !directory.exists(),
            "job-directory cleanup removes retained paths"
        );
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Row {
    pub id: u64,
    pub ordinal: u64,
    pub key: Vec<u8>,
    pub fields: Vec<String>,
}
impl Row {
    pub fn disk_len(&self) -> u64 {
        32 + self.key.len() as u64
            + 8 * self.fields.len() as u64
            + self.fields.iter().map(|s| s.len() as u64).sum::<u64>()
    }
    pub fn memory(&self) -> usize {
        96 + self.key.capacity()
            + self.fields.capacity() * 24
            + self.fields.iter().map(|s| s.capacity()).sum::<usize>()
    }
}
fn put_u64(w: &mut impl Write, n: u64) -> Result<()> {
    w.write_all(&n.to_le_bytes())?;
    Ok(())
}
fn get_u64(r: &mut impl Read) -> Result<u64> {
    let mut b = [0; 8];
    r.read_exact(&mut b)?;
    Ok(u64::from_le_bytes(b))
}
fn put_bytes(w: &mut impl Write, b: &[u8]) -> Result<()> {
    put_u64(w, b.len() as u64)?;
    w.write_all(b)?;
    Ok(())
}
fn get_bytes(r: &mut impl Read, limit: usize) -> Result<Vec<u8>> {
    let n = get_u64(r)?;
    ensure!(
        n <= limit as u64,
        "invalid or oversized spool frame: length {n} bytes exceeds limit {limit} bytes"
    );
    let mut b = vec![0; n as usize];
    r.read_exact(&mut b)?;
    Ok(b)
}
pub fn write_row(w: &mut impl Write, row: &Row) -> Result<()> {
    put_u64(w, row.id)?;
    put_u64(w, row.ordinal)?;
    put_bytes(w, &row.key)?;
    put_u64(w, row.fields.len() as u64)?;
    for field in &row.fields {
        put_bytes(w, field.as_bytes())?;
    }
    Ok(())
}
struct RowHeader {
    id: u64,
    ordinal: u64,
    // Key bytes must deallocate before their independent allocation grant.
    key: FrameKey,
    key_reservation: Option<Reservation>,
}
impl RowHeader {
    fn parts(&self) -> (&[u8], u64, u64) {
        (&self.key, self.id, self.ordinal)
    }
    fn write(&self, w: &mut impl Write) -> Result<()> {
        put_u64(w, self.id)?;
        put_u64(w, self.ordinal)?;
        put_bytes(w, &self.key)
    }
}
fn read_header(r: &mut impl BufRead, maximum: usize) -> Result<Option<RowHeader>> {
    read_header_reserved(r, maximum, None)
}
fn read_header_reserved(
    r: &mut impl BufRead,
    maximum: usize,
    mut key_reservation: Option<Reservation>,
) -> Result<Option<RowHeader>> {
    if r.fill_buf()?.is_empty() {
        return Ok(None);
    }
    let id = get_u64(r)?;
    let ordinal = get_u64(r)?;
    let limit = maximum
        .checked_mul(2)
        .and_then(|n| n.checked_add(64))
        .context("sort key limit overflow")?;
    let length = get_u64(r)?;
    ensure!(
        length <= limit as u64,
        "invalid or oversized spool sort key"
    );
    let length = length as usize;
    let key = if length == 8 || length == 16 {
        if let Some(charge) = &mut key_reservation {
            charge.resize(0)?;
        }
        let mut bytes = [0; 16];
        r.read_exact(&mut bytes[..length])
            .with_context(|| format!("reading sort key for row {id}"))?;
        if length == 16 {
            FrameKey::Random(bytes)
        } else {
            FrameKey::Index(bytes[..8].try_into().unwrap())
        }
    } else {
        if let Some(charge) = &mut key_reservation {
            charge.resize(length)?;
        }
        let mut key = Vec::new();
        key.try_reserve_exact(length)?;
        if let Some(charge) = &mut key_reservation {
            charge.resize(key.capacity())?;
        }
        key.resize(length, 0);
        r.read_exact(&mut key)
            .with_context(|| format!("reading sort key for row {id}"))?;
        FrameKey::Heap(key)
    };
    Ok(Some(RowHeader {
        id,
        ordinal,
        key,
        key_reservation,
    }))
}
pub fn read_row(r: &mut impl BufRead, maximum: usize) -> Result<Option<Row>> {
    let Some(header) = read_header(r, maximum)? else {
        return Ok(None);
    };
    owned_fields(r, maximum, header).map(Some)
}
fn owned_fields(r: &mut impl BufRead, maximum: usize, header: RowHeader) -> Result<Row> {
    Ok(Row {
        fields: read_fields(r, maximum, header.id)?,
        id: header.id,
        ordinal: header.ordinal,
        key: header.key.into_vec(),
    })
}
/// Owned intermediate decode with a charge that follows the returned row rather
/// than its reader. Borrow the row for consumers; materializing a separate clone
/// is a separate allocation, outside this decode reservation.
#[derive(Debug)]
pub struct DecodedRow {
    row: Row,
    _reservation: Reservation,
}
impl std::ops::Deref for DecodedRow {
    type Target = Row;
    fn deref(&self) -> &Row {
        &self.row
    }
}
fn owned_fields_reserved(
    r: &mut impl BufRead,
    maximum: usize,
    mut header: RowHeader,
) -> Result<DecodedRow> {
    let mut reservation = header
        .key_reservation
        .take()
        .context("owned dataset decoder requires a reservation")?;
    // Declare the owned key after its grant, including all decode failures.
    let key = header.key.into_vec_reserved(&mut reservation)?;
    let count = get_u64(r)?;
    ensure!(
        count <= (maximum / 24 + 1) as u64,
        "invalid spool field count"
    );
    let descriptors = (count as usize)
        .checked_mul(std::mem::size_of::<String>())
        .context("spool descriptor capacity overflow")?;
    let mut bytes = key.capacity();
    reservation.resize(
        bytes
            .checked_add(descriptors)
            .context("spool capacity overflow")?,
    )?;
    let mut fields = Vec::new();
    fields.try_reserve_exact(count as usize)?;
    bytes = bytes
        .checked_add(fields.capacity() * std::mem::size_of::<String>())
        .context("spool capacity overflow")?;
    reservation.resize(bytes)?;
    let mut remaining = maximum;
    for index in 0..count {
        let length = get_u64(r)?;
        ensure!(length <= remaining as u64, "invalid or oversized spool frame: length {length} bytes exceeds limit {remaining} bytes");
        let length = length as usize;
        reservation.resize(
            bytes
                .checked_add(length)
                .context("spool capacity overflow")?,
        )?;
        let mut field = Vec::new();
        field.try_reserve_exact(length)?;
        bytes = bytes
            .checked_add(field.capacity())
            .context("spool capacity overflow")?;
        reservation.resize(bytes)?;
        field.resize(length, 0);
        r.read_exact(&mut field)
            .with_context(|| format!("reading field {} for row {}", index + 1, header.id))?;
        remaining -= length;
        fields.push(String::from_utf8(field)?);
    }
    Ok(DecodedRow {
        row: Row {
            id: header.id,
            ordinal: header.ordinal,
            key,
            fields,
        },
        _reservation: reservation,
    })
}
fn read_fields(r: &mut impl BufRead, maximum: usize, id: u64) -> Result<Vec<String>> {
    let count = get_u64(r)?;
    ensure!(
        count <= (maximum / 24 + 1) as u64,
        "invalid spool field count"
    );
    let mut fields = Vec::with_capacity(count as usize);
    let mut remaining = maximum;
    for index in 0..count {
        let field = get_bytes(r, remaining)
            .with_context(|| format!("reading field {} for row {id}", index + 1))?;
        remaining -= field.len();
        fields.push(String::from_utf8(field)?);
    }
    Ok(fields)
}
/// Validate one field in borrowed chunks. Only an incomplete UTF-8 scalar crosses
/// a reader boundary; retain at most three bytes rather than a whole wide field.
/// A chunk may split a scalar; only success for the entire field certifies UTF-8.
/// Consumers may write chunks to a temporary file, which must be discarded
/// if a later chunk fails validation. Never carry a partial scalar between fields.
#[inline]
fn visit_utf8_field(
    r: &mut impl BufRead,
    remaining: usize,
    mut consume: impl FnMut(&[u8]) -> io::Result<()>,
) -> Result<()> {
    if remaining == 0 {
        return Ok(());
    }
    // Keep the common short-field path to one validation and one callback.
    let buffer = r.fill_buf()?;
    if remaining <= buffer.len() {
        let field = &buffer[..remaining];
        std::str::from_utf8(field)?;
        consume(field)?;
        r.consume(remaining);
        return Ok(());
    }
    visit_split_utf8_field(r, remaining, consume)
}

// Keep the boundary state machine out of the inlined short-field path. Most
// spill fields fit in the reader buffer and need just one validation/callback.
fn visit_split_utf8_field(
    r: &mut impl BufRead,
    mut remaining: usize,
    mut consume: impl FnMut(&[u8]) -> io::Result<()>,
) -> Result<()> {
    let mut pending = [0u8; 4];
    let mut pending_len = 0;
    while remaining > 0 {
        let buffer = r.fill_buf()?;
        if buffer.is_empty() {
            return Err(io::Error::from(io::ErrorKind::UnexpectedEof).into());
        }
        let n = remaining.min(buffer.len());
        let chunk = &buffer[..n];
        let mut rest = chunk;
        while pending_len > 0 && !rest.is_empty() {
            pending[pending_len] = rest[0];
            pending_len += 1;
            rest = &rest[1..];
            match std::str::from_utf8(&pending[..pending_len]) {
                Ok(_) => pending_len = 0,
                Err(error) if error.error_len().is_some() => return Err(error.into()),
                Err(_) => (),
            }
        }
        match std::str::from_utf8(rest) {
            Ok(_) => (),
            Err(error) if error.error_len().is_some() => return Err(error.into()),
            Err(error) => {
                let tail = &rest[error.valid_up_to()..];
                pending[..tail.len()].copy_from_slice(tail);
                pending_len = tail.len();
            }
        }
        consume(chunk)?;
        r.consume(n);
        remaining -= n;
    }
    std::str::from_utf8(&pending[..pending_len])?;
    Ok(())
}

/// Validate an encoded row and return its byte length without constructing fields
/// or allocating a crossing-field scratch buffer.
fn scan_row(r: &mut impl BufRead, maximum: usize) -> Result<Option<u64>> {
    if r.fill_buf()?.is_empty() {
        return Ok(None);
    }
    let id = get_u64(r)?;
    let _ordinal = get_u64(r)?;
    let key_len = get_u64(r)?;
    ensure!(
        key_len <= (maximum * 2 + 64) as u64,
        "invalid or oversized spool sort key"
    );
    let copied = io::copy(&mut r.take(key_len), &mut io::sink())?;
    ensure!(copied == key_len, "truncated spool sort key for row {id}");
    let count = get_u64(r)?;
    ensure!(
        count <= (maximum / 24 + 1) as u64,
        "invalid spool field count"
    );
    let mut remaining = maximum;
    let mut bytes = 32 + key_len;
    for index in 0..count {
        let length = get_u64(r)?;
        ensure!(length <= remaining as u64, "invalid or oversized spool frame: length {length} bytes exceeds limit {remaining} bytes");
        let length = length as usize;
        visit_utf8_field(r, length, |_| Ok(()))
            .with_context(|| format!("reading field {} for row {id}", index + 1))?;
        remaining -= length;
        bytes += 8 + length as u64;
    }
    Ok(Some(bytes))
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Group {
    pub offset: u64,
    pub rows: u64,
    pub lineage: Vec<serde_json::Value>,
    pub exact: bool,
}
impl JsonCapacity for Group {
    fn json_capacity(&self) -> Result<usize> {
        self.lineage.json_capacity()
    }
}
pub struct Dataset {
    pub(crate) physical_source: Option<u32>,
    pub data: Arc<DiskFile>,
    pub catalog: DiskFile,
    pub groups: u64,
    workspace: Arc<Workspace>,
    max_metadata: usize,
}
/// Destination for a logical stage. Final stages can encode directly into the output plan.
/// Physical sinks account for successful writes in their row methods. Logical
/// stages forwarding rows use observation::rows::ObservedRows rather than manual
/// progress publication. Source wiring and construction must not start row work.
pub trait RowSink {
    fn physical_input(&mut self, _source: Option<u32>) {}
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group;
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()>;
    /// Owned-row adapter for sinks that do not consume compact fields directly.
    fn packed_row(&mut self, group: &mut Group, row: PackedRow) -> Result<()> {
        self.packed_row_ref(group, &row)
    }
    /// Borrow checked fields when the caller will reuse the decoder storage.
    /// Existing owned-only sinks keep a compatible materializing adapter.
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        if let Some(owned) = row.reserved_owned()? {
            return self.row(group, &owned);
        }
        self.row(
            group,
            &Row {
                id: row.id,
                ordinal: row.ordinal,
                key: row.key.to_vec(),
                fields: row.fields().map(str::to_owned).collect(),
            },
        )
    }
    fn end(&mut self, group: Group) -> Result<()>;
}
impl RowSink for DatasetWriter {
    fn physical_input(&mut self, source: Option<u32>) {
        if let Some(observation) = &mut self.observation {
            observation.source(source);
        }
    }
    fn packed_row(&mut self, group: &mut Group, row: PackedRow) -> Result<()> {
        self.packed_row_ref(group, &row)
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        if let Some(observation) = &mut self.observation {
            observation.begin();
        }
        row.write(&mut self.data)?;
        self.position = self
            .position
            .checked_add(row.disk_len())
            .context("spool size overflow")?;
        group.rows = group.rows.checked_add(1).context("row count overflow")?;
        if let Some(observation) = &mut self.observation {
            observation.rows += 1;
            if let Some(attempt) = &mut observation.attempt {
                attempt.rows_processed(observation.rows);
            }
        }
        Ok(())
    }

    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        self.begin(lineage, exact)
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        self.row(group, row)
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.end(group)
    }
}
struct DatasetObservation {
    ctx: Context,
    attempt: Option<crate::observation::physical::Attempt>,
    rows: u64,
    groups: u64,
    empty: u64,
}
impl DatasetObservation {
    fn begin(&mut self) {
        if self.attempt.is_none() {
            self.attempt = self
                .ctx
                .physical_attempt(crate::observation::physical::Kind::DatasetMaterialize);
        }
    }
    fn source(&mut self, source: Option<u32>) {
        self.ctx.physical_source = source;
        if let Some(attempt) = &mut self.attempt {
            attempt.source(source);
        }
    }
    fn origin(&self) -> Option<u32> {
        self.attempt.as_ref().and_then(|_| {
            self.ctx
                .physical_identity(crate::observation::physical::Kind::DatasetMaterialize)
        })
    }
    fn finish(mut self, status: crate::observation::Status) {
        if let Some(attempt) = self.attempt.take() {
            attempt.finish_groups(status, self.rows, self.groups, self.empty);
        }
    }
}
impl Drop for DatasetObservation {
    fn drop(&mut self) {
        if let Some(attempt) = self.attempt.take() {
            attempt.finish_groups(
                crate::observation::Status::Interrupted,
                self.rows,
                self.groups,
                self.empty,
            );
        }
    }
}
pub struct DatasetWriter {
    observation: Option<DatasetObservation>,
    data: BufWriter<DiskFile>,
    catalog: BufWriter<DiskFile>,
    position: u64,
    groups: u64,
    max_groups: u64,
    max_metadata: usize,
    workspace: Arc<Workspace>,
    _reservation: Reservation,
}
impl DatasetWriter {
    pub fn new(ctx: &Context) -> Result<Self> {
        // Reserve both intermediate writer buffers before either allocation.
        let mut reservation = Reservation::new(ctx);
        reservation.resize(DATASET_WRITE_BUFFER + CATALOG_WRITE_BUFFER)?;
        Ok(Self {
            observation: ctx.physical_enabled().then(|| DatasetObservation {
                ctx: ctx.clone(),
                attempt: None,
                rows: 0,
                groups: 0,
                empty: 0,
            }),
            data: BufWriter::with_capacity(DATASET_WRITE_BUFFER, ctx.file()?),
            catalog: BufWriter::with_capacity(CATALOG_WRITE_BUFFER, ctx.file()?),
            position: 0,
            groups: 0,
            max_groups: ctx.max_files,
            max_metadata: ctx.max_record.saturating_add(512),
            workspace: ctx.workspace.clone(),
            _reservation: reservation,
        })
    }
    pub fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        Group {
            offset: self.position,
            rows: 0,
            lineage,
            exact,
        }
    }
    pub fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        if let Some(observation) = &mut self.observation {
            observation.begin();
        }
        write_row(&mut self.data, row)?;
        let length = row.disk_len();
        self.position = self
            .position
            .checked_add(length)
            .context("spool size overflow")?;
        group.rows = group.rows.checked_add(1).context("row count overflow")?;
        if let Some(observation) = &mut self.observation {
            observation.rows += 1;
            if let Some(attempt) = &mut observation.attempt {
                attempt.rows_processed(observation.rows);
            }
        }
        Ok(())
    }
    pub fn end(&mut self, group: Group) -> Result<()> {
        if let Some(observation) = &mut self.observation {
            observation.begin();
        }
        self.groups += 1;
        ensure!(
            self.groups <= self.max_groups,
            "logical group count exceeds max_files; increase the ceiling explicitly"
        );
        serde_json::to_writer(&mut self.catalog, &group)?;
        self.catalog.write_all(b"\n")?;
        if let Some(observation) = &mut self.observation {
            observation.groups += 1;
            observation.empty += u64::from(group.rows == 0);
            if let Some(attempt) = &mut observation.attempt {
                attempt.groups_processed(observation.groups, observation.empty);
            }
        }
        Ok(())
    }
    pub fn finish(mut self) -> Result<Dataset> {
        let observation = self.observation.take();
        let source = observation.as_ref().and_then(DatasetObservation::origin);
        let result = (|| -> Result<Dataset> {
            self.data.flush()?;
            self.catalog.flush()?;
            Ok(Dataset {
                physical_source: source,
                data: Arc::new(self.data.into_inner().map_err(|e| e.into_error())?),
                catalog: self.catalog.into_inner().map_err(|e| e.into_error())?,
                groups: self.groups,
                workspace: self.workspace,
                max_metadata: self.max_metadata,
            })
        })();
        if let Some(observation) = observation {
            observation.finish(result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ));
        }
        result
    }
}

impl Dataset {
    fn reader_reservation(&self) -> Result<Reservation> {
        let mut reservation = Reservation::for_workspace(self.workspace.clone());
        reservation.resize(DISK_READ_BUFFER)?;
        Ok(reservation)
    }
    /// Stream catalog groups with decoded capacity held by each returned owner.
    /// Group fields are borrowed through `Deref`; retaining an owner also retains
    /// its reservation independently of this dataset and the catalog reader.
    pub fn groups(&self) -> Result<impl Iterator<Item = Result<ChargedJson<Group>>>> {
        Ok(JsonLines::new(&self.catalog, self.max_metadata)?.reserved())
    }
    pub(crate) fn frame_lengths(&self, group: &Group, maximum: usize) -> Result<GroupFrameLengths> {
        let reservation = self.reader_reservation()?;
        let mut reader = self.data.reader()?;
        reader.seek(SeekFrom::Start(group.offset))?;
        Ok(GroupFrameLengths {
            reader,
            remaining: group.rows,
            maximum,
            _reservation: reservation,
        })
    }
    pub(crate) fn packed_rows(
        &self,
        group: &Group,
        maximum: usize,
    ) -> Result<impl Iterator<Item = Result<PackedRow>>> {
        let mut rows = self.rows(group, maximum)?;
        Ok(std::iter::from_fn(move || {
            if rows.remaining == 0 {
                return None;
            }
            rows.remaining -= 1;
            Some((|| {
                let header = read_header_reserved(
                    &mut rows.reader,
                    maximum,
                    Some(rows._reservation.sibling()),
                )?
                .context("truncated spool")?;
                let mut row = PackedRow::read_fields_reserved(
                    &mut rows.reader,
                    maximum,
                    header,
                    None,
                    Some(rows._reservation.sibling()),
                )?;
                row.trim_fields()?;
                Ok(row)
            })())
        }))
    }
    /// Owned rows retain their decode reservations independently of this reader.
    /// The iterator stops after a decode, budget or cancellation failure.
    pub fn rows(&self, group: &Group, maximum: usize) -> Result<GroupRows> {
        let reservation = self.reader_reservation()?;
        let mut reader = self.data.reader()?;
        reader.seek(SeekFrom::Start(group.offset))?;
        Ok(GroupRows {
            reader,
            remaining: group.rows,
            maximum,
            _reservation: reservation,
        })
    }
}
pub(crate) struct GroupFrameLengths {
    reader: BufReader<DiskReader>,
    remaining: u64,
    maximum: usize,
    _reservation: Reservation,
}
impl Iterator for GroupFrameLengths {
    type Item = Result<u64>;
    fn next(&mut self) -> Option<Self::Item> {
        if self.remaining == 0 {
            return None;
        }
        self.remaining -= 1;
        Some(scan_row(&mut self.reader, self.maximum).and_then(|r| r.context("truncated spool")))
    }
}
pub struct GroupRows {
    reader: BufReader<DiskReader>,
    remaining: u64,
    maximum: usize,
    _reservation: Reservation,
}
impl GroupRows {
    pub(crate) fn next_packed(&mut self, previous: Option<PackedRow>) -> Result<Option<PackedRow>> {
        if self.remaining == 0 {
            return Ok(None);
        }
        self.remaining -= 1;
        let header = read_header_reserved(
            &mut self.reader,
            self.maximum,
            Some(self._reservation.sibling()),
        )?
        .context("truncated spool")?;
        PackedRow::read_fields_reserved(
            &mut self.reader,
            self.maximum,
            header,
            previous,
            Some(self._reservation.sibling()),
        )
        .map(Some)
    }
}
impl Iterator for GroupRows {
    type Item = Result<DecodedRow>;
    fn next(&mut self) -> Option<Self::Item> {
        if self.remaining == 0 {
            return None;
        }
        self.remaining -= 1;
        let result = (|| {
            ensure!(
                !self
                    .reader
                    .get_ref()
                    .budget
                    .cancel
                    .load(AtomicOrdering::Relaxed),
                "job cancelled"
            );
            let header = read_header_reserved(
                &mut self.reader,
                self.maximum,
                Some(self._reservation.sibling()),
            )?
            .context("truncated spool")?;
            owned_fields_reserved(&mut self.reader, self.maximum, header)
        })();
        if result.is_err() {
            self.remaining = 0;
        }
        Some(result)
    }
}
#[derive(Clone)]
pub enum SortOrder {
    Key,
    Random([u8; 32]),
    /// Group prefix, random key, then the group-specific collision domain.
    GroupRandom,
}
impl SortOrder {
    pub fn compare(&self, a: &Row, b: &Row) -> Ordering {
        self.compare_parts((&a.key, a.id, a.ordinal), (&b.key, b.id, b.ordinal))
    }
    fn compare_packed(&self, a: &PackedRow, b: &PackedRow) -> Ordering {
        if let (PackedKey::Random(a_key), PackedKey::Random(b_key)) = (&a.key, &b.key) {
            // Big-endian integers have exactly the existing lexicographic byte
            // order. Equal keys still use the versioned collision refinement.
            let order = u128::from_be_bytes(*a_key).cmp(&u128::from_be_bytes(*b_key));
            if order != Ordering::Equal {
                return order;
            }
        }
        self.compare_parts((&a.key, a.id, a.ordinal), (&b.key, b.id, b.ordinal))
    }
    fn compare_parts(&self, a: (&[u8], u64, u64), b: (&[u8], u64, u64)) -> Ordering {
        a.0.cmp(b.0).then_with(|| match self {
            Self::Key => a.2.cmp(&b.2),
            Self::Random(domain) => chopper_core::random::compare_ties(domain, a.1, b.1),
            Self::GroupRandom => chopper_core::random::compare_ties(
                a.0[a.0.len() - 32..]
                    .try_into()
                    .expect("group random domain"),
                a.1,
                b.1,
            ),
        })
    }
}
#[cfg(target_os = "linux")]
fn wide_merge_handles_available() -> bool {
    let mut limit = std::mem::MaybeUninit::<libc::rlimit>::uninit();
    // getrlimit initializes the result on success. A failure keeps the old cap.
    if unsafe { libc::getrlimit(libc::RLIMIT_NOFILE, limit.as_mut_ptr()) } != 0 {
        return false;
    }
    // Each active run may hold both its original file and an independent reader.
    // Leave headroom for retained levels and the rest of the process.
    unsafe { limit.assume_init() }.rlim_cur >= 4096
}

#[cfg(any(target_os = "linux", target_os = "wasi"))]
struct PreparedSpill {
    // Drop the writer, including its admitted path, before the buffer grant.
    writer: BufWriter<SpillFile>,
    buffer: Reservation,
}
#[cfg(any(target_os = "linux", target_os = "wasi"))]
impl PreparedSpill {
    fn new(ctx: &Context) -> Result<Self> {
        let mut buffer = Reservation::new(ctx);
        buffer.resize(64 * 1024)?;
        let writer = ctx.spill_writer(64 * 1024)?;
        Ok(Self { writer, buffer })
    }
}

// A keyed sorter routes to buckets or owns a prepared spill writer.
// Keeping the mutually exclusive owners in one slot preserves row headroom.
#[allow(clippy::large_enum_variant)]
#[derive(Default)]
enum SortSpillMode {
    #[default]
    Ordinary,
    Routing(Router),
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    Prepared(PreparedSpill),
}
impl SortSpillMode {
    fn router_mut(&mut self) -> Option<&mut Router> {
        if let Self::Routing(router) = self {
            Some(router)
        } else {
            None
        }
    }
    fn take_router(&mut self) -> Option<Router> {
        if let Self::Routing(_) = self {
            if let Self::Routing(router) = std::mem::take(self) {
                return Some(router);
            }
        }
        None
    }
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    fn take_prepared(&mut self) -> Option<PreparedSpill> {
        if let Self::Prepared(_) = self {
            if let Self::Prepared(owner) = std::mem::take(self) {
                return Some(owner);
            }
        }
        None
    }
}

#[cfg(test)]
const _: () = assert!(
    std::mem::size_of::<SortSpillMode>() <= std::mem::size_of::<Option<Router>>(),
    "ordinary and routed sorters must retain their existing fixed capacity",
);

pub struct Sorter {
    ctx: Context,
    order: SortOrder,
    buffer: Vec<PackedRow>,
    bytes: usize,
    levels: Catalog<Catalog<SortRun>>,
    largest_row: usize,
    largest_key: usize,
    reservation: Reservation,
    buffer_limit: usize,
    defer_terminal_merges: bool,
    routing_candidate: bool,
    spill_mode: SortSpillMode,
}
// The fixtures leave room for a small packed row and still force spills.
#[cfg(all(
    test,
    any(
        feature = "experimental-consecutive-partitions",
        feature = "experimental-partition-balanced",
        feature = "experimental-shuffle-partition"
    )
))]
pub(crate) const SORT_HIERARCHY_TEST_MEMORY: usize = 4 * (std::mem::size_of::<Sorter>() + 256);

impl Sorter {
    pub fn new(ctx: &Context, order: SortOrder) -> Self {
        // A large explicit job ceiling cannot expand shared admission. Retain
        // at most half that ceiling for rows so spill construction and I/O can
        // still obtain their own grants before retained rows are released.
        // This is a feasibility target, not a grant or a changed job budget.
        let buffer_limit = ctx.workspace.sort_buffer_limit(ctx.memory / 4);
        let routing_candidate =
            matches!(order, SortOrder::Key) && ctx.grouping == chopper_core::Grouping::Auto;
        #[cfg(target_os = "linux")]
        let defer_terminal_merges = !cfg!(feature = "experimental-spill-blocks")
            && (ctx.auto_merge_ceiling == Some(512)
                || cfg!(feature = "experimental-short-terminal-uniform-merge"))
            && ctx.direct_terminal_output
            && !ctx.physical_enabled()
            && matches!(order, SortOrder::Random(_))
            && wide_merge_handles_available();
        #[cfg(not(target_os = "linux"))]
        let defer_terminal_merges = false;
        Self {
            ctx: ctx.clone(),
            order,
            buffer: Vec::new(),
            bytes: 0,
            levels: Catalog::new(ctx),
            largest_row: 0,
            largest_key: 0,
            reservation: Reservation::new(ctx),
            buffer_limit,
            defer_terminal_merges,
            routing_candidate,
            spill_mode: SortSpillMode::Ordinary,
        }
    }
    #[cfg(target_os = "wasi")]
    pub(crate) fn prefer_hosted_resident(&mut self) {
        let target = self
            .ctx
            .workspace
            .sort_buffer_limit(self.ctx.memory / 16 * 5);
        // Leave space for the live input and output owners in the half-job ledger.
        if self.ctx.working_headroom() >= (target + self.ctx.memory / 8) as u64 {
            self.buffer_limit = target;
        }
    }
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    pub(crate) fn probabilistic_shuffle(ctx: &Context) -> Result<Self> {
        let mut sorter = Self::new(ctx, SortOrder::GroupRandom);
        sorter.spill_mode = SortSpillMode::Prepared(PreparedSpill::new(ctx)?);
        sorter.buffer_limit = ctx
            .workspace
            .available_sort_buffer_limit(sorter.buffer_limit);
        Ok(sorter)
    }
    /// Known count-independent membership can try routing from its first row.
    /// The same one-way fallback bounds handles and preserves sorted output.
    pub(crate) fn streaming(ctx: &Context) -> Self {
        let mut sorter = Self::new(ctx, SortOrder::Key);
        if ctx.grouping == chopper_core::Grouping::Auto {
            sorter.routing_candidate = false;
            sorter.spill_mode = SortSpillMode::Routing(Router::new(ctx));
        }
        sorter
    }
    pub fn push(&mut self, row: Row) -> Result<()> {
        self.push_keyed(row, None).map(|_| ())
    }
    #[cfg(test)]
    pub(crate) fn push_reusing_fields(&mut self, row: Row) -> Result<Vec<String>> {
        self.push_keyed(row, None)
    }
    #[cfg(test)]
    pub(crate) fn push_random(&mut self, row: Row, key: [u8; 16]) -> Result<Vec<String>> {
        self.push_keyed(row, Some(key))
    }
    fn push_keyed(&mut self, mut row: Row, random_key: Option<[u8; 16]>) -> Result<Vec<String>> {
        self.ctx.check()?;
        // Preserve the decoded-row limit and merge planning hint, including
        // materialization of a retained random key by an owned consumer.
        let decoded_size = if random_key.is_some() {
            let size = row.memory() - row.key.capacity() + 16;
            row.key = Vec::new();
            size
        } else {
            row.memory()
        };
        if decoded_size > self.ctx.memory / 4 {
            return Err(anyhow::Error::new(crate::resources::MemoryAdmission::Local)
                .context("record too large for sort memory budget"));
        }
        self.largest_row = self.largest_row.max(decoded_size);
        self.largest_key = self.largest_key.max(if random_key.is_some() {
            16
        } else {
            row.key.len()
        });
        if random_key.is_none() {
            if let Some(router) = self.spill_mode.router_mut() {
                if router.push_row(&row)? {
                    return Ok(row.fields);
                }
            }
        }
        let (mut packed, reusable) =
            PackedRow::new_reusing_fields_reserved(row, &self.reservation)?;
        if let Some(key) = random_key {
            packed.key = PackedKey::Random(key);
        }
        self.push_packed(packed)?;
        Ok(reusable)
    }
    /// Ingest checked spool fields without reconstructing owned strings. Keep
    /// the owned decoder's row limit and planning hint for adapter consumers.
    pub(crate) fn push_compact(
        &mut self,
        row: PackedRow,
        decoded_key_capacity: usize,
    ) -> Result<()> {
        self.push_compact_reusing(row, decoded_key_capacity)
            .map(|_| ())
    }
    /// Return decode storage only after direct routing has consumed the row.
    /// Sorting/fallback retains ownership and requires a fresh input buffer.
    pub(crate) fn push_compact_reusing(
        &mut self,
        mut row: PackedRow,
        decoded_key_capacity: usize,
    ) -> Result<Option<PackedRow>> {
        self.ctx.check()?;
        let decoded_size = row.decoded_size(decoded_key_capacity);
        ensure!(
            decoded_size <= self.ctx.memory / 4,
            "record too large for sort memory budget"
        );
        self.largest_row = self.largest_row.max(decoded_size);
        self.largest_key = self.largest_key.max(row.key.len());
        if let Some(router) = self.spill_mode.router_mut() {
            if router.push(&row)? {
                return Ok(Some(row));
            }
        }
        row.trim_fields()?;
        self.push_packed(row)?;
        Ok(None)
    }
    fn push_packed(&mut self, mut row: PackedRow) -> Result<()> {
        if let Some(router) = self.spill_mode.router_mut() {
            if router.push(&row)? {
                return Ok(());
            }
            // A late key or reordered stratum invalidated direct routing. Each
            // retained bucket is already sorted: reuse it without replaying rows.
            self.ctx
                .budget
                .routing_fallbacks
                .fetch_add(1, AtomicOrdering::Relaxed);
            let router = self.spill_mode.take_router().unwrap();
            let observation_ctx = self.ctx.clone();
            let observation = observation_ctx.physical_span_from(
                crate::observation::physical::Kind::Fallback,
                self.ctx.physical_operations,
                [
                    self.ctx
                        .physical_identity(crate::observation::physical::Kind::Routing),
                    None,
                    None,
                    None,
                ],
            );
            let runs = router.into_runs()?;
            if let Some(span) = observation {
                span.finish_counts(0, runs.len() as u64, None);
            }
            if let Some(span) = self.ctx.physical_span_from(
                crate::observation::physical::Kind::Reuse,
                self.ctx.physical_operations,
                [
                    self.ctx
                        .physical_identity(crate::observation::physical::Kind::Routing),
                    None,
                    None,
                    None,
                ],
            ) {
                span.finish_counts(0, runs.len() as u64, None);
            }

            self.ctx
                .budget
                .routing_reused_runs
                .fetch_add(runs.len() as u64, AtomicOrdering::Relaxed);
            // Buckets are disjoint and ordered by key, so concatenation is
            // already one sorted run. Open just one bucket reader at a time.
            self.add_run(
                SortRun(
                    runs,
                    self.ctx
                        .physical_enabled()
                        .then_some(crate::observation::physical::Kind::Reuse),
                ),
                0,
            )?;
        }
        let size = row.memory();
        if size > self.ctx.memory / 4 {
            return Err(anyhow::Error::new(crate::resources::MemoryAdmission::Local)
                .context("packed record exceeds sort memory budget"));
        }
        let bytes = self
            .bytes
            .checked_add(row.heap_bytes())
            .context("sort buffer size overflow")?;
        if !reserve_row_capacity(
            &mut self.buffer,
            bytes,
            &mut self.reservation,
            self.buffer_limit,
            std::mem::size_of::<Self>(),
        )? {
            self.flush()?;
            if let Some(router) = self.spill_mode.router_mut() {
                if router.push(&row)? {
                    return Ok(());
                }
                // Let the same fallback path handle the threshold-crossing row.
                return self.push_packed(row);
            }
            let bytes = row.heap_bytes();
            if !reserve_row_capacity(
                &mut self.buffer,
                bytes,
                &mut self.reservation,
                self.buffer_limit,
                std::mem::size_of::<Self>(),
            )? {
                return Err(anyhow::Error::new(crate::resources::MemoryAdmission::Local)
                    .context("record cannot fit available sort workspace; increase memory_mb"));
            }
            self.bytes = bytes;
        } else {
            self.bytes = bytes;
        }
        row.release_decode_reservation();
        self.buffer.push(row);
        Ok(())
    }
    fn sort_buffer(&mut self) {
        let started = std::time::Instant::now();
        #[cfg(not(target_os = "wasi"))]
        if self.buffer.len() >= 4096 {
            self.ctx.pool.install(|| {
                self.buffer
                    .par_sort_unstable_by(|a, b| self.order.compare_packed(a, b))
            });
        } else {
            self.buffer
                .sort_unstable_by(|a, b| self.order.compare_packed(a, b));
        }
        #[cfg(target_os = "wasi")]
        self.buffer
            .sort_unstable_by(|a, b| self.order.compare_packed(a, b));
        // Wall time includes Rayon dispatch/join, but excludes packing, spill I/O
        // and merges. Summed across buffers; it is not summed worker CPU time.
        self.ctx.budget.sort_nanoseconds.fetch_add(
            started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
            AtomicOrdering::Relaxed,
        );
        self.ctx
            .budget
            .sort_calls
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.ctx
            .budget
            .sort_rows
            .fetch_add(self.buffer.len() as u64, AtomicOrdering::Relaxed);
    }
    /// Make room for growing ingestion buffers without changing random keys.
    pub(crate) fn reserve_input(&mut self, input: &mut Reservation, bytes: usize) -> Result<()> {
        if input.resize(bytes).is_err() {
            self.flush()?;
            input.resize(bytes)?;
        }
        Ok(())
    }
    fn flush(&mut self) -> Result<()> {
        self.flush_run(true)
    }
    fn flush_run(&mut self, _may_spill_again: bool) -> Result<()> {
        self.ctx.pressure_boundary();
        if self.buffer.is_empty() {
            return Ok(());
        }
        if self.routing_candidate {
            self.routing_candidate = false;
            if Router::eligible(&self.buffer, &self.ctx) {
                let mut router = Router::new(&self.ctx);
                for row in &self.buffer {
                    ensure!(router.push(row)?, "routing preflight mismatch");
                }
                self.buffer = Vec::new();
                self.bytes = 0;
                self.reservation.resize(0)?;
                self.spill_mode = SortSpillMode::Routing(router);
                return Ok(());
            }
        }
        // The spill writer overlaps the retained rows. Reserve it separately
        // from the row-storage ceiling and release it before merge allocation.
        let mut io = Reservation::new(&self.ctx);
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        let prepared = self.spill_mode.take_prepared();
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        let renew_prepared = _may_spill_again && prepared.is_some();
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        let writer = prepared.map(|owner| {
            io = owner.buffer;
            owner.writer
        });
        #[cfg(not(any(target_os = "linux", target_os = "wasi")))]
        let writer = None;
        if writer.is_none() {
            io.resize(64 * 1024)?;
        }
        self.ctx
            .budget
            .sort_runs
            .fetch_add(1, AtomicOrdering::Relaxed);
        let observation_ctx = self.ctx.clone();
        let observation = observation_ctx.physical_span(crate::observation::physical::Kind::Spill);
        let observed_rows = self.buffer.len() as u64;
        self.sort_buffer();
        let mut writer = match writer {
            Some(writer) => writer,
            None => self.ctx.spill_writer(64 * 1024)?,
        };
        for row in self.buffer.drain(..) {
            row.write(&mut writer)?;
        }
        writer.flush()?;
        let run = writer.into_inner().map_err(|e| e.into_error())?;
        self.buffer = Vec::new();
        self.bytes = 0;
        self.reservation.resize(0)?;
        drop(io);
        let run = SortRun::single(&self.ctx, run)?.origin(
            self.ctx
                .physical_enabled()
                .then_some(crate::observation::physical::Kind::Spill),
        );
        if let Some(span) = observation {
            span.finish_counts(observed_rows, 1, None);
        }
        self.add_run(run, 0)?;
        #[cfg(target_os = "wasi")]
        if matches!(self.order, SortOrder::Random(_)) {
            // A spill rules out the resident path for this job.
            self.buffer_limit = self.buffer_limit.min(self.ctx.memory / 4);
        }
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        if renew_prepared {
            self.spill_mode = SortSpillMode::Prepared(PreparedSpill::new(&self.ctx)?);
        }
        Ok(())
    }
    fn fan_in(&self) -> usize {
        let ceiling = 64;
        #[cfg(target_os = "linux")]
        let ceiling = if (self.ctx.auto_merge_ceiling.is_some()
            || cfg!(feature = "experimental-wide-uniform-merge"))
            && self.ctx.direct_terminal_output
            && !self.ctx.physical_enabled()
            && matches!(self.order, SortOrder::Random(_))
            && wide_merge_handles_available()
        {
            if self.defer_terminal_merges {
                512
            } else {
                256
            }
        } else {
            ceiling
        };
        // Only headers are live per run. Leave headroom for the winner's
        // separately reserved decode/conversion capacity and growth overlap.
        let mut budget = self.ctx.memory / 4;
        if ceiling > 64 && self.ctx.auto_merge_ceiling.is_some() {
            budget = budget.min(self.ctx.working_headroom() as usize);
        }
        (budget.saturating_sub(self.largest_row) / (self.largest_key + 65536 + 512))
            .clamp(2, ceiling)
    }
    fn add_run(&mut self, run: SortRun, level: usize) -> Result<()> {
        if self.defer_terminal_merges {
            const PENDING_LIMIT: usize = 1024;
            debug_assert_eq!(level, 0);
            if self.fan_in() > 256 && self.ctx.used() <= self.ctx.budget.maximum / 2 {
                if self.levels.is_empty() {
                    // Admit the pending slots before transferring any run.
                    // A denied optional catalog can use ordinary merging.
                    let reservation = Reservation::new(&self.ctx);
                    let _ = Catalog::with_capacity(reservation, PENDING_LIMIT)
                        .and_then(|catalog| self.levels.push(catalog));
                }
                if self
                    .levels
                    .first()
                    .is_some_and(|pending| pending.len() < PENDING_LIMIT - 1)
                {
                    self.levels[0].push(run)?;
                    return Ok(());
                }
            }
            // Once the pending limit or reader budget is reached, feed the
            // owned runs to the original bounded hierarchy exactly once.
            self.defer_terminal_merges = false;
            let levels = std::mem::replace(&mut self.levels, Catalog::new(&self.ctx));
            for existing in levels {
                for pending in existing {
                    self.add_run(pending, 0)?;
                }
            }
        }
        if self.levels.len() == level {
            self.levels.push(Catalog::new(&self.ctx))?;
        }
        self.levels[level].push(run)?;
        let fan_in = self.fan_in();
        while self.levels[level].len() >= fan_in {
            let runs = self.levels[level].take_prefix(fan_in)?;
            let merged = self.merge(runs, Some(level as u32))?;
            self.add_run(merged, level + 1)?;
        }
        Ok(())
    }
    fn merge(&mut self, runs: Catalog<SortRun>, level: Option<u32>) -> Result<SortRun> {
        use crate::observation::physical::{error_status, Kind};
        let kind = if level == Some(0) {
            Kind::Merge
        } else {
            Kind::HierarchicalMerge
        };
        let (sources, omitted) = if self.ctx.physical_enabled() {
            SortRun::sources(
                &runs,
                self.ctx.physical_operations[0],
                kind,
                self.ctx.physical_role,
            )
        } else {
            ([None; 4], true)
        };
        let mut observation =
            self.ctx
                .physical_attempt_details(kind, self.ctx.physical_operations, sources, omitted);
        let observed_runs = runs.len() as u64;
        let mut visited = 0;
        let result = (|| -> Result<SortRun> {
            self.ctx.pressure_boundary();
            let mut io = Reservation::new(&self.ctx);
            io.resize(65536)?;
            let mut output = self.ctx.spill_writer(65536)?;
            let mut rows = MergeRows::with_observation(
                runs,
                self.order.clone(),
                &self.ctx,
                self.largest_row,
                self.largest_key,
                [None; 4],
                true,
                false,
            )?;
            loop {
                let next = rows.copy_next(&mut output);
                visited = rows.merged;
                if let Some(attempt) = &mut observation {
                    attempt.rows_processed(visited);
                }
                if !next? {
                    break;
                }
            }
            output.flush()?;
            Ok(
                SortRun::single(&self.ctx, output.into_inner().map_err(|e| e.into_error())?)?
                    .origin(self.ctx.physical_enabled().then_some(kind)),
            )
        })();
        if let Some(attempt) = observation {
            attempt.finish(
                result
                    .as_ref()
                    .err()
                    .map_or(crate::observation::Status::Completed, error_status),
                visited,
                observed_runs,
                level,
            );
        }
        result
    }
    pub fn finish(mut self) -> Result<SortedRows> {
        self.ctx.pressure_boundary();
        if let Some(router) = self.spill_mode.take_router() {
            self.ctx
                .budget
                .routed_groups
                .fetch_add(1, AtomicOrdering::Relaxed);
            return Ok(SortedRows::Routed(router.finish()?));
        }
        if self.levels.is_empty() {
            let observation_ctx = self.ctx.clone();
            let observation =
                observation_ctx.physical_span(crate::observation::physical::Kind::ResidentSort);
            self.sort_buffer();
            if let Some(span) = observation {
                span.finish(self.buffer.len() as u64);
            }
            self.ctx
                .budget
                .resident_sorts
                .fetch_add(1, AtomicOrdering::Relaxed);
            return Ok(SortedRows::Memory(ResidentRows {
                rows: self.buffer.into_iter(),
                _reservation: self.reservation,
            }));
        }
        self.flush_run(false)?;
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        drop(self.spill_mode.take_prepared());
        let fan_in = self.fan_in();
        let mut levels = std::mem::replace(&mut self.levels, Catalog::new(&self.ctx)).into_iter();
        let mut runs = if self.defer_terminal_merges {
            let mut pending = levels.next().context("missing pending terminal runs")?;
            debug_assert_eq!(levels.len(), 0);
            // Consolidate only the inputs needed to fit the final merge.
            if pending.len() > 64 {
                self.ctx
                    .budget
                    .used_short_tail
                    .store(true, AtomicOrdering::Relaxed);
            }
            while pending.len() > fan_in {
                let count = (pending.len() - fan_in + 1).min(fan_in);
                let merged = self.merge(pending.take_prefix(count)?, None)?;
                pending.push(merged)?;
            }
            pending
        } else {
            let mut runs = Catalog::new(&self.ctx);
            for level in levels {
                for run in level {
                    runs.push(run)?;
                }
            }
            runs
        };
        while runs.len() > fan_in {
            let mut next = Catalog::new(&self.ctx);
            let mut iter = runs.into_iter();
            loop {
                let mut batch = Catalog::new(&self.ctx);
                for run in iter.by_ref().take(fan_in) {
                    batch.push(run)?;
                }
                if batch.is_empty() {
                    break;
                }
                next.push(if batch.len() == 1 {
                    batch.into_iter().next().unwrap()
                } else {
                    self.merge(batch, None)?
                })?;
            }
            runs = next;
        }
        // Stream the last merge to the next stage instead of materializing it.
        let (sources, omitted) = if self.ctx.physical_enabled() {
            SortRun::sources(
                &runs,
                self.ctx.physical_operations[0],
                crate::observation::physical::Kind::MergeTraversal,
                self.ctx.physical_role,
            )
        } else {
            ([None; 4], true)
        };
        Ok(SortedRows::Merge(MergeRows::with_observation(
            runs,
            self.order,
            &self.ctx,
            self.largest_row,
            self.largest_key,
            sources,
            omitted,
            true,
        )?))
    }
}
// Keep the lending cursor and its bounded observation inline. Boxing just the
// merge variant would add an admitted allocation to every external traversal.
#[allow(clippy::large_enum_variant)]
pub enum SortedRows {
    Memory(ResidentRows),
    Merge(MergeRows),
    Routed(RoutedRows),
}
impl SortedRows {
    pub(crate) fn reusing(self) -> ReusingRows {
        ReusingRows {
            rows: self,
            current: None,
        }
    }
    /// Synchronous consumers borrow each row until the next checked decode.
    pub(crate) fn try_for_each_packed(
        self,
        mut consume: impl FnMut(&mut PackedRow) -> Result<()>,
    ) -> Result<()> {
        let mut rows = self.reusing();
        while let Some(row) = rows.next()? {
            consume(row)?;
        }
        Ok(())
    }
}
/// A lending cursor keeps one decoded payload alive across group boundaries.
/// The current row owns its capacity reservation, including a previously decoded
/// wide buffer. Resident rows transfer their heap charge out of the container.
pub(crate) struct ReusingRows {
    rows: SortedRows,
    current: Option<PackedRow>,
}
impl ReusingRows {
    pub(crate) fn next(&mut self) -> Result<Option<&mut PackedRow>> {
        let previous = self.current.take();
        let row = match &mut self.rows {
            SortedRows::Memory(rows) => {
                drop(previous);
                rows.take_packed().map(Ok)
            }
            SortedRows::Merge(rows) => rows.next_decoded(|reader, maximum, header| {
                PackedRow::read_fields_reusing(reader, maximum, header, previous)
            }),
            SortedRows::Routed(rows) => rows.next_decoded(|reader, maximum, header| {
                PackedRow::read_fields_reusing(reader, maximum, header, previous)
            }),
        };
        self.current = row.transpose()?;
        Ok(self.current.as_mut())
    }
}
impl Iterator for SortedRows {
    type Item = Result<DecodedRow>;
    fn next(&mut self) -> Option<Self::Item> {
        match self {
            Self::Memory(rows) => rows.next(),
            Self::Merge(rows) => rows.next(),
            Self::Routed(rows) => rows.next(),
        }
    }
}
struct Head {
    row: RowHeader,
    run: usize,
    order: Arc<SortOrder>,
}
impl PartialEq for Head {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}
impl Eq for Head {}
impl PartialOrd for Head {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for Head {
    fn cmp(&self, other: &Self) -> Ordering {
        self.order
            .compare_parts(other.row.parts(), self.row.parts())
            .then_with(|| other.run.cmp(&self.run))
    }
}
/// A logical sorted run may consist of several disjoint, ordered bucket files.
struct SortRun(
    Catalog<SpillFile>,
    Option<crate::observation::physical::Kind>,
);
impl SortRun {
    fn origin(mut self, kind: Option<crate::observation::physical::Kind>) -> Self {
        self.1 = kind;
        self
    }
    fn sources(
        runs: &[SortRun],
        operation: usize,
        consumer: crate::observation::physical::Kind,
        role: u8,
    ) -> ([Option<u32>; 4], bool) {
        let mut sources = [None; 4];
        let mut used = 0;
        let mut omitted = false;
        for run in runs {
            let Some(origin) = run.1 else {
                omitted = true;
                continue;
            };
            if origin == consumer {
                omitted = true;
                continue;
            }
            let id = crate::observation::physical::identity_for(operation, origin, role);
            if id.is_none() {
                omitted = true;
                continue;
            }
            if sources[..used].contains(&id) {
                continue;
            }
            if used == 4 {
                omitted = true;
                continue;
            }
            sources[used] = id;
            used += 1;
        }
        (sources, omitted)
    }

    fn single(ctx: &Context, file: impl Into<SpillFile>) -> Result<Self> {
        let mut files = Catalog::new(ctx);
        files.push(file.into())?;
        Ok(Self(files, None))
    }
}
struct RunReader {
    reader: Option<BufReader<SpillReader>>,
    // Close the descriptor before releasing its file, including on Windows.
    current: Option<SpillFile>,
    remaining: catalog::CatalogIter<SpillFile>,
}
impl RunReader {
    fn new(run: SortRun) -> Self {
        Self {
            reader: None,
            current: None,
            remaining: run.0.into_iter(),
        }
    }
    fn header(&mut self, maximum: usize, charge: &Reservation) -> Result<Option<RowHeader>> {
        loop {
            if let Some(reader) = &mut self.reader {
                if let Some(row) = read_header_reserved(reader, maximum, Some(charge.sibling()))? {
                    return Ok(Some(row));
                }
            }
            self.reader = None;
            self.current = None;
            let Some(file) = self.remaining.next() else {
                return Ok(None);
            };
            self.reader = Some(file.reader()?);
            self.current = Some(file);
        }
    }
}
pub struct MergeRows {
    readers: Vec<RunReader>,
    heads: BinaryHeap<Head>,
    ctx: Context,
    merged: u64,
    failed: bool,
    failure_status: crate::observation::Status,
    observation: Option<crate::observation::physical::Attempt>,
    _reservation: Reservation,
}
impl MergeRows {
    #[cfg(test)]
    fn new(
        files: Catalog<SortRun>,
        order: SortOrder,
        ctx: &Context,
        _largest_row: usize,
        _largest_key: usize,
    ) -> Result<Self> {
        Self::with_observation(
            files,
            order,
            ctx,
            _largest_row,
            _largest_key,
            [None; 4],
            true,
            true,
        )
    }
    #[allow(clippy::too_many_arguments)]
    fn with_observation(
        files: Catalog<SortRun>,
        order: SortOrder,
        ctx: &Context,
        _largest_row: usize,
        _largest_key: usize,
        sources: [Option<u32>; 4],
        omitted: bool,
        observe: bool,
    ) -> Result<Self> {
        let mut reservation = Reservation::new(ctx);
        // Reader buffers and metadata arrays are separate from row-owned decode
        // charges. No largest-row allowance is multiplied or retained here.
        reservation.resize(
            files.len() * DISK_READ_BUFFER
                + std::mem::size_of::<SortOrder>()
                + 3 * std::mem::size_of::<usize>(),
        )?;
        ctx.budget
            .merge_operations
            .fetch_add(1, AtomicOrdering::Relaxed);
        ctx.budget
            .merge_inputs
            .fetch_add(files.len() as u64, AtomicOrdering::Relaxed);
        ctx.budget
            .peak_merge_fan_in
            .fetch_max(files.len() as u64, AtomicOrdering::Relaxed);
        let mut readers = Vec::new();
        reservation.reserve_vec(&mut readers, files.len())?;
        reservation
            .resize(reservation.bytes() as usize + files.len() * std::mem::size_of::<Head>())?;
        let mut heads = BinaryHeap::new();
        heads.try_reserve_exact(files.len())?;
        reservation.resize(
            reservation.bytes() as usize
                + (heads.capacity() - files.len()) * std::mem::size_of::<Head>(),
        )?;
        let order = Arc::new(order);
        for (run, file) in files.into_iter().enumerate() {
            ctx.check()?;
            let mut reader = RunReader::new(file);
            if let Some(row) = reader.header(ctx.max_record, &reservation)? {
                heads.push(Head {
                    row,
                    run,
                    order: order.clone(),
                });
            }
            readers.push(reader);
        }
        Ok(Self {
            readers,
            heads,
            ctx: ctx.clone(),
            merged: 0,
            failed: false,
            failure_status: crate::observation::Status::Interrupted,
            observation: if observe {
                ctx.physical_attempt_details(
                    crate::observation::physical::Kind::MergeTraversal,
                    ctx.physical_operations,
                    sources,
                    omitted,
                )
            } else {
                None
            },
            _reservation: reservation,
        })
    }
}
impl MergeRows {
    fn advance(&mut self, run: usize, order: Arc<SortOrder>) -> Result<()> {
        if let Some(row) = self.readers[run].header(self.ctx.max_record, &self._reservation)? {
            self.heads.push(Head { row, run, order });
        }
        self.merged += 1;
        if let Some(attempt) = &mut self.observation {
            attempt.rows_processed(self.merged);
        }
        if self.merged.is_multiple_of(65536) {
            self.ctx.event("Merging sorted runs", self.merged)?;
        }
        Ok(())
    }
    /// Intermediate merges keep the existing framing and validate every field,
    /// but never reconstruct a Vec<String> or copy fields into decode scratch.
    fn copy_next(&mut self, output: &mut impl Write) -> Result<bool> {
        let Some(head) = self.heads.pop() else {
            self.finish_observation();
            return Ok(false);
        };
        self.ctx.check()?;
        head.row.write(output)?;
        let reader = self.readers[head.run]
            .reader
            .as_mut()
            .expect("live merge head");
        let count = get_u64(reader)?;
        ensure!(
            count <= (self.ctx.max_record / 24 + 1) as u64,
            "invalid spool field count"
        );
        put_u64(output, count)?;
        let mut remaining = self.ctx.max_record;
        for index in 0..count {
            let length = get_u64(reader)?;
            ensure!(length <= remaining as u64, "invalid or oversized spool frame: length {length} bytes exceeds limit {remaining} bytes");
            put_u64(output, length)?;
            visit_utf8_field(reader, length as usize, |bytes| output.write_all(bytes))
                .with_context(|| format!("reading field {} for row {}", index + 1, head.row.id))?;
            remaining -= length as usize;
        }
        self.advance(head.run, head.order)?;
        Ok(true)
    }
}
impl MergeRows {
    #[cfg(test)]
    fn next_compact(&mut self) -> Option<Result<PackedRow>> {
        self.next_decoded(PackedRow::read_fields)
    }
    fn next_decoded<T>(
        &mut self,
        decode: impl FnOnce(&mut BufReader<SpillReader>, usize, RowHeader) -> Result<T>,
    ) -> Option<Result<T>> {
        if self.failed {
            return None;
        }
        let Some(head) = self.heads.pop() else {
            self.finish_observation();
            return None;
        };
        // The decoder takes the winning key's charge into its returned row.
        // Loading the replacement therefore accounts both live allocations.
        let next = (|| {
            self.ctx.check()?;
            let row = decode(
                self.readers[head.run]
                    .reader
                    .as_mut()
                    .expect("live merge head"),
                self.ctx.max_record,
                head.row,
            )?;
            self.advance(head.run, head.order)?;
            Ok(row)
        })();
        if let Err(error) = &next {
            self.failed = true;
            self.failure_status = crate::observation::physical::error_status(error);
        }
        Some(next)
    }
}
impl MergeRows {
    fn finish_observation(&mut self) {
        if let Some(attempt) = self.observation.take() {
            attempt.finish(crate::observation::Status::Completed, self.merged, 0, None);
        }
    }
}
impl Drop for MergeRows {
    fn drop(&mut self) {
        if let Some(attempt) = self.observation.take() {
            attempt.finish(self.failure_status, self.merged, 0, None);
        }
    }
}
impl Iterator for MergeRows {
    type Item = Result<DecodedRow>;
    fn next(&mut self) -> Option<Self::Item> {
        self.next_decoded(owned_fields_reserved)
    }
}

#[cfg(all(
    test,
    target_os = "linux",
    feature = "experimental-short-terminal-uniform-merge",
    not(feature = "experimental-spill-blocks")
))]
#[test]
fn terminal_uniform_tail_merge_preserves_rows_and_bounds_pending_runs() -> Result<()> {
    let admitted = wide_merge_handles_available();
    for (runs, temp_bytes, keeps_pending) in [
        (514, None, true),
        (1024, None, false),
        (40, Some(4096), false),
    ] {
        let mut ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                temp_bytes,
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(512 * 1024 * 1024)),
        )?;
        ctx.direct_terminal_output = true;
        let mut sorter = Sorter::new(&ctx, SortOrder::Random([0; 32]));
        assert_eq!(sorter.defer_terminal_merges, admitted);
        // A low-limit process validates the selector without opening a large
        // batch of real files.
        if !admitted {
            continue;
        }
        for id in (0..runs).rev() {
            sorter.push(Row {
                id,
                ordinal: id,
                key: u128::from(id).to_be_bytes().to_vec(),
                fields: vec![id.to_string()],
            })?;
            sorter.flush()?;
        }
        assert_eq!(sorter.defer_terminal_merges, keeps_pending);
        if keeps_pending {
            assert_eq!(sorter.levels[0].len(), runs as usize);
            assert_eq!(ctx.budget.merge_operations.load(AtomicOrdering::Relaxed), 0);
        }
        let rows = sorter.finish()?.collect::<Result<Vec<_>>>()?;
        assert_eq!(
            rows.iter().map(|row| row.id).collect::<Vec<_>>(),
            (0..runs).collect::<Vec<_>>()
        );
        if keeps_pending {
            assert_eq!(ctx.budget.merge_operations.load(AtomicOrdering::Relaxed), 2);
            assert_eq!(ctx.budget.merge_inputs.load(AtomicOrdering::Relaxed), 515);
        }
        drop(rows);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        assert_eq!(ctx.used(), 0);
    }
    Ok(())
}

#[cfg(not(target_os = "wasi"))]
pub fn available_space(path: &std::path::Path) -> std::io::Result<u64> {
    fs2::available_space(path)
}
#[cfg(target_os = "wasi")]
pub fn available_space(_path: &std::path::Path) -> std::io::Result<u64> {
    std::env::var("CHOPPER_DISK_AVAILABLE")
        .ok()
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| std::io::Error::other("browser storage estimate is missing"))
}

/// Only the owners needed for bounded observation delivery; cloning this does
/// not retain the job directory, worker pool or an admission grant.
pub(crate) struct PhysicalReporter {
    budget: Arc<Budget>,
    workspace: Arc<Workspace>,
    sink: crate::observation::physical::Sink,
}
impl Context {
    pub(crate) fn physical_attempt_id(&self) -> u64 {
        self.budget
            .observation_attempts
            .fetch_add(1, AtomicOrdering::Relaxed)
            + 1
    }
    pub(crate) fn physical_enabled(&self) -> bool {
        self.physical.is_some()
            && self
                .budget
                .observation_enabled
                .load(AtomicOrdering::Relaxed)
    }
    pub(crate) fn physical_reporter(&self) -> Option<PhysicalReporter> {
        Some(PhysicalReporter {
            budget: self.budget.clone(),
            workspace: self.workspace.clone(),
            sink: self.physical.clone()?,
        })
    }
}
impl PhysicalReporter {
    pub(crate) fn enabled(&self) -> bool {
        self.budget
            .observation_enabled
            .load(AtomicOrdering::Relaxed)
    }
    pub(crate) fn emit(&self, mut fact: crate::observation::physical::Fact) {
        let sink = &self.sink;
        if !self
            .budget
            .observation_enabled
            .load(AtomicOrdering::Relaxed)
        {
            return;
        }
        let mut grant = Reservation::for_workspace(self.workspace.clone());
        if self
            .budget
            .observation_visits
            .fetch_add(1, AtomicOrdering::Relaxed)
            >= crate::observation::physical::MAX_RECORDS
            || fact.role >= crate::observation::physical::ROLE_SLOTS
            || fact
                .operations
                .iter()
                .any(|op| *op > crate::observation::physical::MAX_OPERATION + 1)
            || grant.resize(8192).is_err()
        {
            fact.kind = crate::observation::physical::Kind::Omitted;
            self.budget
                .observation_enabled
                .store(false, AtomicOrdering::Relaxed);
        }
        if !sink(fact) {
            self.budget
                .observation_enabled
                .store(false, AtomicOrdering::Relaxed);
        }
    }
}

#[cfg(test)]
mod merge_tests {
    #[test]
    fn temporary_space_is_unlimited_by_default_and_explicit_limits_still_apply() -> Result<()> {
        let resources = chopper_core::Resources::default();
        let ctx = Context::new(
            &resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        assert_eq!(ctx.remaining_temp(), u64::MAX);
        let limited = chopper_core::Resources {
            temp_bytes: Some(128),
            ..resources
        };
        let ctx = Context::new(&limited, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(ctx.remaining_temp(), 128);
        let mut file = ctx.file()?;
        assert!(file.write_all(&[0; 129]).is_err());
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn observed_dataset_writer_reports_progress_before_completion() -> Result<()> {
        use crate::observation::{physical::Kind, Status};
        let mut ctx = context()?;
        let facts = Arc::new(Mutex::new(Vec::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let mut writer = DatasetWriter::new(&ctx)?;
        let mut group = writer.begin(Vec::new(), true);
        let row = Row {
            id: 0,
            ordinal: 0,
            key: Vec::new(),
            fields: vec!["sample".into()],
        };
        writer.row(&mut group, &row)?;
        std::thread::sleep(std::time::Duration::from_millis(110));
        for _ in 1..4096 {
            writer.row(&mut group, &row)?;
        }
        assert!(facts
            .lock()
            .unwrap()
            .iter()
            .any(|fact| fact.kind == Kind::DatasetMaterialize
                && fact.status == Status::Active
                && fact.rows == 4096
                && fact.seconds > 0.));
        writer.end(group)?;
        writer.finish()?;
        Ok(())
    }

    #[test]
    fn observed_materialized_merge_failure_keeps_partial_row_visits() -> Result<()> {
        use crate::observation::{physical::Kind, Status};
        let mut ctx = context()?;
        let facts = Arc::new(Mutex::new(Vec::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let mut runs = Catalog::new(&ctx);
        for corrupt in [true, false] {
            let mut bytes = Vec::new();
            write_row(
                &mut bytes,
                &Row {
                    id: u64::from(!corrupt),
                    ordinal: u64::from(!corrupt),
                    key: vec![if corrupt { b'a' } else { b'b' }],
                    fields: vec!["valid".into()],
                },
            )?;
            if corrupt {
                let mut invalid = Vec::new();
                write_row(
                    &mut invalid,
                    &Row {
                        id: 2,
                        ordinal: 2,
                        key: vec![b'c'],
                        fields: vec!["truncated".into()],
                    },
                )?;
                invalid.truncate(invalid.len() - 3);
                bytes.extend(invalid);
            }
            // Exercise corrupt production-v1 bytes at merge consumption. Optional
            // compact spill construction validates its own input before merging.
            let mut file = ctx.file()?;
            file.write_all(&bytes)?;
            file.flush()?;
            #[cfg(feature = "experimental-spill-blocks")]
            let file = SpillFile::from(file);
            runs.push(SortRun::single(&ctx, file)?)?;
        }
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        assert!(sorter.merge(runs, Some(0)).is_err());
        let facts = facts.lock().unwrap();
        let terminal = facts
            .iter()
            .find(|f| f.kind == Kind::Merge && f.status == Status::Failed)
            .expect("attributed merge failure");
        assert_eq!(terminal.rows, 2);
        assert_eq!(terminal.runs, 2);
        assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
        Ok(())
    }

    use super::*;

    #[test]
    fn larger_job_budget_preserves_spill_headroom_under_shared_ceiling() -> Result<()> {
        for grouping in [chopper_core::Grouping::Sort, chopper_core::Grouping::Auto] {
            let pool = Arc::new(crate::resources::MemoryPool::new(4 * 1024 * 1024));
            let ctx = Context::with_memory_pool(
                &chopper_core::Resources {
                    memory_mb: 512.into(),
                    workers: 1,
                    grouping,
                    ..Default::default()
                },
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            assert_eq!(ctx.memory, 512 * 1024 * 1024);
            let baseline = pool.reservation_counts().0;
            let mut sorter = Sorter::new(&ctx, SortOrder::Key);
            for id in 0..25_000u64 {
                sorter.push(Row {
                    id,
                    ordinal: id,
                    key: vec![(id % 8) as u8],
                    fields: vec![id.to_string(), "x".repeat(96)],
                })?;
            }
            let mut expected = (0..25_000u64).collect::<Vec<_>>();
            expected.sort_unstable_by_key(|id| (id % 8, *id));
            let mut rows = sorter.finish()?;
            for id in expected {
                let row = rows.next().unwrap()?;
                assert_eq!(row.id, id);
                assert_eq!(row.fields, [id.to_string(), "x".repeat(96)]);
            }
            assert!(rows.next().is_none());
            drop(rows);
            assert_eq!(ctx.used(), 0);
            assert_eq!(pool.reservation_counts().0, baseline);
            assert!(pool.reservation_counts().1 <= 4 * 1024 * 1024);
        }
        Ok(())
    }

    #[test]
    fn sorted_owned_rows_retain_exact_capacity_after_resident_merge_and_route_drop() -> Result<()> {
        for mode in 0..3 {
            let ctx = context()?;
            let mut sorter = if mode == 2 {
                Sorter::streaming(&ctx)
            } else {
                Sorter::new(&ctx, SortOrder::Random([7; 32]))
            };
            for id in 0..3 {
                sorter.push(Row {
                    id,
                    ordinal: id,
                    key: vec![7; 17],
                    fields: vec!["界".repeat(1000), String::new()],
                })?;
                if mode == 1 {
                    sorter.flush()?;
                }
            }
            let mut rows = sorter.finish()?;
            let first = rows.next().unwrap()?;
            let second = rows.next().unwrap()?;
            drop(rows);
            let bytes = |row: &Row| {
                row.key.capacity()
                    + row.fields.capacity() * std::mem::size_of::<String>()
                    + row.fields.iter().map(String::capacity).sum::<usize>()
            };
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (bytes(&first) + bytes(&second)) as u64
            );
            assert_ne!(first.id, second.id);
            assert_eq!(ctx.used(), 0);
            drop(first);
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + bytes(&second) as u64
            );
            drop(second);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }

    #[test]
    fn merge_compact_row_owns_decode_capacity_after_merge_destruction() -> Result<()> {
        let ctx = context()?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Random([7; 32]));
        sorter.push(Row {
            id: 9,
            ordinal: 2,
            key: vec![7; 17],
            fields: vec!["界".repeat(1000)],
        })?;
        sorter.flush()?;
        let SortedRows::Merge(mut rows) = sorter.finish()? else {
            panic!("expected external merge");
        };
        let row = rows.next_compact().unwrap()?;
        drop(rows);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + row.heap_bytes() as u64
        );
        assert_eq!(row.fields().next().unwrap(), "界".repeat(1000));
        assert_eq!(ctx.used(), 0);
        drop(row);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn owned_dataset_decode_checks_shared_capacity_edges() -> Result<()> {
        let row = Row {
            id: 3,
            ordinal: 9,
            key: vec![7; 17],
            fields: vec!["界\0\n".into(), String::new(), "tail".into()],
        };
        let mut encoded = Vec::new();
        write_row(&mut encoded, &row)?;
        let required = 17 + 3 * std::mem::size_of::<String>() + 9;
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(1024));
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(1024 - required.checked_add_signed(delta).unwrap())?;
            let held = workspace.used();
            let mut input = io::Cursor::new(&encoded);
            let header = read_header_reserved(
                &mut input,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            let result = owned_fields_reserved(&mut input, 1024, header);
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(decoded) = &result {
                assert_eq!(decoded.fields, row.fields);
                assert_eq!(decoded.key, row.key);
                assert_eq!(workspace.used(), held + required as u64);
            }
            drop(result);
            assert_eq!(workspace.used(), held);
        }
        Ok(())
    }

    #[test]
    fn owned_dataset_rows_retain_charges_past_reader_and_dataset_drop() -> Result<()> {
        let ctx = context()?;
        let mut writer = DatasetWriter::new(&ctx)?;
        let mut group = writer.begin(vec![], false);
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![7; 17],
            fields: vec!["界".repeat(1000), String::new()],
        };
        writer.row(&mut group, &row)?;
        writer.row(&mut group, &row)?;
        writer.end(group.clone())?;
        let data = writer.finish()?;
        let base = ctx.workspace.used();
        let mut rows = data.rows(&group, ctx.max_record)?;
        let first = rows.next().unwrap()?;
        let second = rows.next().unwrap()?;
        let retained = 17 + 2 * std::mem::size_of::<String>() + 3000;
        assert!(rows.next().is_none());
        assert_eq!(
            ctx.workspace.used(),
            base + DISK_READ_BUFFER as u64 + 2 * retained as u64
        );
        drop(rows);
        drop(data);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + 2 * retained as u64
        );
        assert_eq!(first.fields, second.fields);
        drop(first);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + retained as u64
        );
        drop(second);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn owned_dataset_decode_releases_on_corrupt_and_oversized_fields() -> Result<()> {
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![7; 17],
            fields: vec!["valid".into()],
        };
        let mut encoded = Vec::new();
        write_row(&mut encoded, &row)?;
        for mode in 0..4 {
            let mut encoded = encoded.clone();
            match mode {
                0 => {
                    encoded.pop();
                }
                1 => {
                    *encoded.last_mut().unwrap() = 0xff;
                }
                2 => {
                    encoded[41..49].copy_from_slice(&u64::MAX.to_le_bytes());
                }
                _ => {
                    encoded[49..57].copy_from_slice(&u64::MAX.to_le_bytes());
                }
            }
            let workspace = Arc::new(Workspace::new(4096));
            let mut input = io::Cursor::new(encoded);
            let header = read_header_reserved(
                &mut input,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            assert!(owned_fields_reserved(&mut input, 1024, header).is_err());
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn owned_dataset_iterator_stops_on_pressure_and_buffered_cancellation() -> Result<()> {
        for cancel in [false, true] {
            let ctx = context()?;
            let mut writer = DatasetWriter::new(&ctx)?;
            let mut group = writer.begin(vec![], false);
            let row = Row {
                id: 1,
                ordinal: 2,
                key: vec![7; 17],
                fields: vec!["value".into()],
            };
            writer.row(&mut group, &row)?;
            writer.row(&mut group, &row)?;
            writer.end(group.clone())?;
            let data = writer.finish()?;
            let base = ctx.workspace.used();
            let mut rows = data.rows(&group, ctx.max_record)?;
            let first = rows.next().unwrap()?;
            let mut other = Reservation::new(&ctx);
            if cancel {
                ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
            } else {
                other.resize(ctx.memory / 2 - ctx.workspace.used() as usize)?;
            }
            let held = ctx.workspace.used();
            assert!(rows.next().unwrap().is_err());
            assert!(rows.next().is_none());
            assert_eq!(ctx.workspace.used(), held);
            drop(first);
            drop(rows);
            drop(other);
            assert_eq!(ctx.workspace.used(), base);
            drop(data);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    fn key_test_run(ctx: &Context, keys: &[usize]) -> Result<SortRun> {
        let mut file = ctx.file()?;
        for (id, &length) in keys.iter().enumerate() {
            write_row(
                &mut file,
                &Row {
                    id: id as u64,
                    ordinal: id as u64,
                    key: vec![7; length],
                    fields: vec![String::new()],
                },
            )?;
        }
        SortRun::single(ctx, file)
    }

    #[test]
    fn merge_head_keys_reserve_actual_shared_capacity_before_allocation() -> Result<()> {
        for delta in [-1isize, 0, 1] {
            let mut ctx = context()?;
            ctx.replace_workspace_for_test(Workspace::new(2_000_000))?;
            let mut runs = Catalog::new(&ctx);
            runs.push(key_test_run(&ctx, &[17])?)?;
            runs.push(key_test_run(&ctx, &[31])?)?;
            let base = ctx.workspace.used() as usize;
            let fixed = 2
                * (DISK_READ_BUFFER
                    + std::mem::size_of::<RunReader>()
                    + std::mem::size_of::<Head>())
                + std::mem::size_of::<SortOrder>()
                + 3 * std::mem::size_of::<usize>();
            let mut other = Reservation::new(&ctx);
            other.resize(
                2_000_000 + ctx.directory_reserved_bytes() as usize
                    - base
                    - fixed
                    - 48usize.checked_add_signed(delta).unwrap(),
            )?;
            let held = other.bytes();
            // Deliberately underestimate key length: actual decoded capacity,
            // rather than the planner's hint, must govern the reservation.
            let result = MergeRows::new(runs, SortOrder::Key, &ctx, 128, 0);
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(rows) = &result {
                assert_eq!(rows.heads.len(), 2);
                assert_eq!(
                    rows.heads
                        .iter()
                        .map(|h| h.row.key_reservation.as_ref().unwrap().bytes())
                        .sum::<u64>(),
                    48
                );
            }
            drop(result);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes() + held);
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn merge_replacement_keys_charge_overlap_for_copy_owned_and_compact() -> Result<()> {
        for mode in 0..3 {
            for delta in [-1isize, 0, 1] {
                let mut ctx = context()?;
                ctx.replace_workspace_for_test(Workspace::new(2_000_000))?;
                let mut runs = Catalog::new(&ctx);
                runs.push(key_test_run(&ctx, &[17, 4000])?)?;
                let mut rows = MergeRows::new(runs, SortOrder::Key, &ctx, 8192, 4000)?;
                let mut other = Reservation::new(&ctx);
                let payload = match mode {
                    0 => 0,
                    1 => 24,
                    _ => 32,
                };
                other.resize(
                    2_000_000 + ctx.directory_reserved_bytes() as usize
                        - ctx.workspace.used() as usize
                        - (4000usize + payload).checked_add_signed(delta).unwrap(),
                )?;
                let result = match mode {
                    0 => rows.copy_next(&mut Vec::new()).map(|_| ()),
                    1 => rows.next().unwrap().map(|_| ()),
                    _ => rows.next_compact().unwrap().map(|_| ()),
                };
                assert_eq!(result.is_ok(), delta >= 0);
                if result.is_ok() {
                    assert_eq!(
                        rows.heads
                            .peek()
                            .unwrap()
                            .row
                            .key_reservation
                            .as_ref()
                            .unwrap()
                            .bytes(),
                        4000
                    );
                    // The old 17-byte key is gone after the replacement loads.
                    assert_eq!(
                        ctx.workspace.used(),
                        2_000_000 + ctx.directory_reserved_bytes()
                            - delta as u64
                            - 17
                            - payload as u64
                    );
                }
                drop(rows);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + other.bytes()
                );
                assert_eq!(ctx.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn routed_header_keys_check_shared_edges_and_release_after_decode() -> Result<()> {
        for delta in [-1isize, 0, 1] {
            let mut ctx = context()?;
            ctx.replace_workspace_for_test(Workspace::new(2_000_000))?;
            let mut router = Router::new(&ctx);
            assert!(router.push_row(&Row {
                id: 0,
                ordinal: 0,
                key: vec![7; 17],
                fields: vec![String::new()]
            })?);
            let mut rows = router.finish()?;
            let mut other = Reservation::new(&ctx);
            other.resize(
                2_000_000 + ctx.directory_reserved_bytes() as usize
                    - ctx.workspace.used() as usize
                    - 41usize.checked_add_signed(delta).unwrap(),
            )?;
            let held = ctx.workspace.used();
            let result = rows
                .next_decoded(|reader, maximum, header| {
                    assert!(header.key_reservation.is_some());
                    assert_eq!(ctx.workspace.used(), held + 17);
                    owned_fields_reserved(reader, maximum, header)
                })
                .unwrap();
            assert_eq!(result.is_ok(), delta >= 0);
            assert_eq!(
                ctx.workspace.used(),
                held + if result.is_ok() { 41 } else { 0 }
            );
            drop(result);
            assert_eq!(ctx.workspace.used(), held);
            drop(rows);
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + other.bytes()
            );
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn merge_header_keys_release_on_truncation_and_cancellation() -> Result<()> {
        for cancel in [false, true] {
            let ctx = context()?;
            let run = key_test_run(&ctx, &[17, 4000])?;
            if !cancel {
                // The second header declares a key whose bytes are truncated.
                run.0[0]
                    .file
                    .as_ref()
                    .unwrap()
                    .as_file()
                    .set_len(17 + 48 + 24 + 10)?;
            }
            let mut runs = Catalog::new(&ctx);
            runs.push(run)?;
            let mut rows = MergeRows::new(runs, SortOrder::Key, &ctx, 8192, 4000)?;
            if cancel {
                ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
            }
            assert!(rows.next().unwrap().is_err());
            assert!(rows.next().is_none());
            drop(rows);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn dataset_key_reservation_checks_shared_edges_and_corruption() -> Result<()> {
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![7; 17],
            fields: vec![String::new()],
        };
        let mut frame = Vec::new();
        write_row(&mut frame, &row)?;
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(40));
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(23usize.checked_add_signed(-delta).unwrap())?;
            let held = workspace.used();
            let header = read_header_reserved(
                &mut io::Cursor::new(&frame),
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            );
            assert_eq!(header.is_ok(), delta >= 0);
            if let Ok(header) = &header {
                assert_eq!(
                    workspace.used(),
                    held + header.as_ref().unwrap().key.capacity() as u64
                );
            }
            drop(header);
            assert_eq!(workspace.used(), held);
        }
        for length in [24, 25, 40] {
            let workspace = Arc::new(Workspace::new(100));
            assert!(read_header_reserved(
                &mut io::Cursor::new(&frame[..length]),
                1024,
                Some(Reservation::for_workspace(workspace.clone()))
            )
            .is_err());
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn fixed_header_keys_preserve_frames_without_heap_admission() -> Result<()> {
        for length in [8, 16] {
            let row = Row {
                id: 7,
                ordinal: 13,
                key: vec![0xff; length],
                fields: vec![],
            };
            let mut frame = Vec::new();
            write_row(&mut frame, &row)?;
            let workspace = Arc::new(Workspace::new(0));
            let mut reader = io::Cursor::new(&frame);
            let header = read_header_reserved(
                &mut reader,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            assert_eq!(header.parts(), (row.key.as_slice(), row.id, row.ordinal));
            assert_eq!(header.key.capacity(), 0);
            assert_eq!(workspace.used(), 0);
            let mut encoded = Vec::new();
            header.write(&mut encoded)?;
            assert_eq!(encoded, frame[..24 + length]);
            drop(header);
            let decoded = read_row(&mut io::Cursor::new(&frame), 1024)?.unwrap();
            assert_eq!(decoded.key, row.key);
            assert_eq!(decoded.id, row.id);
            assert_eq!(decoded.ordinal, row.ordinal);
            for end in 24..24 + length {
                assert!(read_header_reserved(
                    &mut io::Cursor::new(&frame[..end]),
                    1024,
                    Some(Reservation::for_workspace(workspace.clone()))
                )
                .is_err());
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn fixed_header_owned_conversion_requires_and_retains_its_vec_grant() -> Result<()> {
        for length in [8usize, 16] {
            for delta in [-1isize, 0, 1] {
                let workspace = Arc::new(Workspace::new(length.checked_add_signed(delta).unwrap()));
                let row = Row {
                    id: 7,
                    ordinal: 13,
                    key: vec![0xff; length],
                    fields: vec![],
                };
                let mut frame = Vec::new();
                write_row(&mut frame, &row)?;
                let mut reader = io::Cursor::new(frame);
                let header = read_header_reserved(
                    &mut reader,
                    1024,
                    Some(Reservation::for_workspace(workspace.clone())),
                )?
                .unwrap();
                assert_eq!(workspace.used(), 0);
                let decoded = owned_fields_reserved(&mut reader, 1024, header);
                assert_eq!(decoded.is_ok(), delta >= 0);
                if let Ok(decoded) = &decoded {
                    assert_eq!(decoded.key, row.key);
                    assert_eq!(workspace.used(), decoded.key.capacity() as u64);
                }
                drop(decoded);
                assert_eq!(workspace.used(), 0);
            }
            for corrupt in [false, true] {
                let workspace = Arc::new(Workspace::new(4096));
                let row = Row {
                    id: 7,
                    ordinal: 13,
                    key: vec![0xff; length],
                    fields: vec!["x".into()],
                };
                let mut frame = Vec::new();
                write_row(&mut frame, &row)?;
                if corrupt {
                    *frame.last_mut().unwrap() = 0xff;
                } else {
                    frame.pop();
                }
                let mut reader = io::Cursor::new(frame);
                let header = read_header_reserved(
                    &mut reader,
                    1024,
                    Some(Reservation::for_workspace(workspace.clone())),
                )?
                .unwrap();
                assert!(owned_fields_reserved(&mut reader, 1024, header).is_err());
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn dataset_keys_follow_payload_lifetime_and_inline_keys_release_heap_charge() -> Result<()> {
        for key_length in [0, 8, 16, 17, 4000] {
            let workspace = Arc::new(Workspace::new(10000));
            let row = Row {
                id: 1,
                ordinal: 2,
                key: vec![7; key_length],
                fields: vec![String::new()],
            };
            let mut frame = Vec::new();
            write_row(&mut frame, &row)?;
            let mut reader = io::Cursor::new(frame);
            let header = read_header_reserved(
                &mut reader,
                4096,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            let header_heap = if key_length == 8 || key_length == 16 {
                0
            } else {
                key_length
            };
            assert_eq!(workspace.used(), header_heap as u64);
            let mut packed =
                PackedRow::read_fields_reserved(&mut reader, 4096, header, None, None)?;
            let key_heap = if key_length == 8 || key_length == 16 {
                0
            } else {
                key_length
            };
            assert_eq!(workspace.used(), (32 + key_heap) as u64);
            packed.trim_fields()?;
            assert_eq!(workspace.used(), (16 + key_heap) as u64);
            assert_eq!(packed.key.as_slice(), row.key);
            drop(reader);
            assert_eq!(workspace.used(), (16 + key_heap) as u64);
            drop(packed);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn dataset_key_boxing_overlap_and_payload_failure_release_charges() -> Result<()> {
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(113usize.checked_add_signed(delta).unwrap()));
            let mut key = Vec::with_capacity(64);
            key.resize(17, 7);
            let mut charge = Reservation::for_workspace(workspace.clone());
            charge.resize(key.capacity())?;
            let header = RowHeader {
                id: 1,
                ordinal: 2,
                key: key.into(),
                key_reservation: Some(charge),
            };
            let mut fields = Vec::new();
            put_u64(&mut fields, 1)?;
            put_bytes(&mut fields, b"")?;
            let result = PackedRow::read_fields_reserved(
                &mut io::Cursor::new(fields),
                1024,
                header,
                None,
                None,
            );
            assert_eq!(result.is_ok(), delta >= 0);
            if result.is_ok() {
                assert_eq!(workspace.used(), 49);
            }
            drop(result);
            assert_eq!(workspace.used(), 0);
        }
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![7; 17],
            fields: vec!["x".into()],
        };
        let mut frame = Vec::new();
        write_row(&mut frame, &row)?;
        for invalid_utf8 in [false, true] {
            let mut frame = frame.clone();
            if invalid_utf8 {
                *frame.last_mut().unwrap() = 0xff;
            } else {
                frame.pop();
            }
            let workspace = Arc::new(Workspace::new(100));
            let mut reader = io::Cursor::new(frame);
            let header = read_header_reserved(
                &mut reader,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            assert!(
                PackedRow::read_fields_reserved(&mut reader, 1024, header, None, None).is_err()
            );
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn dataset_key_reuse_reserves_both_live_keys_before_handoff() -> Result<()> {
        // First row holds a 17-byte key and 32-byte payload capacity. Reading
        // the next header must also reserve its 17-byte key before old-row reuse.
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(66usize.checked_add_signed(delta).unwrap()));
            let row = Row {
                id: 1,
                ordinal: 2,
                key: vec![7; 17],
                fields: vec![String::new()],
            };
            let mut frame = Vec::new();
            write_row(&mut frame, &row)?;
            write_row(&mut frame, &row)?;
            let mut reader = io::Cursor::new(frame);
            let header = read_header_reserved(
                &mut reader,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            )?
            .unwrap();
            let previous = PackedRow::read_fields_reserved(&mut reader, 1024, header, None, None)?;
            assert_eq!(workspace.used(), 49);
            let next = read_header_reserved(
                &mut reader,
                1024,
                Some(Reservation::for_workspace(workspace.clone())),
            );
            assert_eq!(next.is_ok(), delta >= 0);
            if let Ok(Some(header)) = next {
                let packed = PackedRow::read_fields_reserved(
                    &mut reader,
                    1024,
                    header,
                    Some(previous),
                    None,
                )?;
                assert_eq!(workspace.used(), 49);
                drop(packed);
            } else {
                drop(previous);
            }
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn decoded_dataset_rows_keep_charges_after_reader_drop_and_transfer_to_sort() -> Result<()> {
        for reuse in [false, true] {
            let ctx = context()?;
            let mut writer = DatasetWriter::new(&ctx)?;
            let mut group = writer.begin(vec![], false);
            writer.row(
                &mut group,
                &Row {
                    id: 8,
                    ordinal: 3,
                    key: vec![7; 17],
                    fields: vec!["界".repeat(1000)],
                },
            )?;
            writer.end(group.clone())?;
            let data = writer.finish()?;
            let baseline = ctx.workspace.used();
            let row = if reuse {
                let mut rows = data.rows(&group, ctx.max_record)?;
                rows.next_packed(None)?.unwrap()
            } else {
                let mut rows = data.packed_rows(&group, ctx.max_record)?;
                rows.next().unwrap()?
            };
            assert!(ctx.workspace.used() >= baseline + 3016);
            let mut sorter = Sorter::new(&ctx, SortOrder::Key);
            sorter.push_compact(row, 0)?;
            let mut sorted = sorter.finish()?.reusing();
            assert_eq!(sorted.next()?.unwrap().id, 8);
            assert!(sorted.next()?.is_none());
            drop(sorted);
            assert_eq!(ctx.workspace.used(), baseline);
            drop(data);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn temporary_paths_reserve_before_creation_at_shared_capacity_edges() -> Result<()> {
        let parent = tempfile::Builder::new()
            .prefix("chopper-long-界-path-")
            .tempdir()?;
        for delta in [-1isize, 0, 1] {
            let mut ctx = Context::new(
                &chopper_core::Resources {
                    workers: 1,
                    temp_dir: Some(parent.path().to_str().unwrap().to_owned()),
                    ..Default::default()
                },
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            let bytes = ctx.file_path_bytes()?;
            ctx.replace_workspace_for_test(Workspace::new(2 * bytes))?;
            let mut other = Reservation::new(&ctx);
            let held = bytes.checked_add_signed(-delta).unwrap();
            other.resize(held)?;
            let result = ctx.file();
            assert_eq!(result.is_ok(), delta >= 0);
            assert_eq!(
                ctx.budget.files_created.load(AtomicOrdering::Relaxed),
                u64::from(delta >= 0),
                "denied path reservation must not create a temporary file"
            );
            if let Ok(mut file) = result {
                assert_eq!(file.file.as_ref().unwrap().path().as_os_str().len(), bytes);
                file.write_all(b"payload")?;
                let file = Arc::new(file);
                let retained = file.clone();
                drop(file);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (held + bytes) as u64
                );
                assert!(ctx.file().is_err(), "live file shares the same ceiling");
                drop(retained);
            }
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + held as u64
            );
            assert_eq!(ctx.used(), 0);
            assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
            assert_eq!(std::fs::read_dir(ctx.dir.path())?.count(), 0);
            drop(other);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }

    #[test]
    fn temporary_path_charge_releases_on_creation_failure_and_cancellation() -> Result<()> {
        for cancelled in [false, true] {
            let ctx = context()?;
            if cancelled {
                ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
            } else {
                std::fs::remove_dir(ctx.dir.path())?;
            }
            assert!(ctx.file().is_err());
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
            assert_eq!(ctx.budget.files_created.load(AtomicOrdering::Relaxed), 0);
            assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
        }
        Ok(())
    }

    #[test]
    fn merge_catalogs_overlap_reader_allocation_and_live_until_drop() -> Result<()> {
        let file_bytes = std::mem::size_of::<SpillFile>();
        let run_bytes = std::mem::size_of::<SortRun>();
        let reader_bytes = DISK_READ_BUFFER
            + std::mem::size_of::<RunReader>()
            + std::mem::size_of::<Head>()
            + std::mem::size_of::<SortOrder>()
            + 3 * std::mem::size_of::<usize>();
        let path_bytes = context()?.file_path_bytes()?;
        let exact = path_bytes + file_bytes + run_bytes + reader_bytes;
        for delta in [-1isize, 0, 1] {
            for cancel in [false, true] {
                let mut ctx = context()?;
                ctx.replace_workspace_for_test(Workspace::new(
                    exact.checked_add_signed(delta).unwrap(),
                ))?;
                let mut file = ctx.file()?;
                write_row(
                    &mut file,
                    &Row {
                        id: 1,
                        ordinal: 1,
                        key: vec![],
                        fields: vec!["x".into()],
                    },
                )?;
                let mut runs = Catalog::new(&ctx);
                runs.push(SortRun::single(&ctx, file)?)?;
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (path_bytes + file_bytes + run_bytes) as u64
                );
                let merged = MergeRows::new(runs, SortOrder::Key, &ctx, 128, 0);
                assert_eq!(merged.is_ok(), delta >= 0);
                if let Ok(mut merged) = merged {
                    // The input run-list array is gone; file-list capacity is
                    // still owned by RunReader's iterator even after EOF.
                    assert_eq!(
                        ctx.workspace.used(),
                        ctx.directory_reserved_bytes()
                            + (path_bytes + file_bytes + reader_bytes) as u64
                    );
                    if cancel {
                        ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
                        assert!(merged.next().unwrap().is_err());
                    } else {
                        assert_eq!(merged.next().unwrap()?.id, 1);
                        assert!(merged.next().is_none());
                    }
                    assert_eq!(
                        ctx.workspace.used(),
                        ctx.directory_reserved_bytes()
                            + (if cancel { path_bytes } else { 0 } + file_bytes + reader_bytes)
                                as u64
                    );
                    drop(merged);
                }
                assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
                assert_eq!(ctx.used(), 0);
                assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn dataset_buffers_reserve_before_allocation_and_release_at_capacity_edges() -> Result<()> {
        let path_bytes = context()?.file_path_bytes()?;
        let writer_bytes = DATASET_WRITE_BUFFER + CATALOG_WRITE_BUFFER + 2 * path_bytes;
        for limit in [writer_bytes - 1, writer_bytes, writer_bytes + 1] {
            let mut ctx = context()?;
            ctx.replace_workspace_for_test(Workspace::new(limit))?;
            let result = DatasetWriter::new(&ctx);
            assert_eq!(result.is_ok(), limit >= writer_bytes);
            if let Ok(writer) = result {
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + writer_bytes as u64
                );
                assert_eq!(writer.data.capacity(), DATASET_WRITE_BUFFER);
                assert_eq!(writer.catalog.capacity(), CATALOG_WRITE_BUFFER);
                drop(writer);
            }
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
            assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
        }
        for limit in [
            2 * DISK_READ_BUFFER - 1,
            2 * DISK_READ_BUFFER,
            2 * DISK_READ_BUFFER + 1,
        ] {
            let mut ctx = context()?;
            ctx.replace_workspace_for_test(Workspace::new(limit + 2 * path_bytes))?;
            let mut writer = DatasetWriter::new(&ctx)?;
            let mut group = writer.begin(vec![], false);
            writer.row(
                &mut group,
                &Row {
                    id: 7,
                    ordinal: 0,
                    key: vec![],
                    fields: vec!["界\0\n".into()],
                },
            )?;
            writer.end(group.clone())?;
            let data = writer.finish()?;
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (2 * path_bytes) as u64,
                "finished writer releases both buffers, retaining file paths"
            );
            let mut catalog = data.groups()?;
            assert_eq!(catalog.next().unwrap()?.rows, 1);
            assert!(catalog.next().is_none());
            // Even an exhausted iterator still owns its buffered reader.
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (DISK_READ_BUFFER + 2 * path_bytes) as u64
            );
            let rows = data.rows(&group, ctx.max_record);
            assert_eq!(rows.is_ok(), limit >= 2 * DISK_READ_BUFFER);
            if let Ok(mut rows) = rows {
                // Reader buffers fit, but leave no room for owned descriptors.
                assert!(rows.next().unwrap().is_err());
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + (2 * DISK_READ_BUFFER + 2 * path_bytes) as u64
                );
                assert!(data.frame_lengths(&group, ctx.max_record).is_err());
                drop(rows);
            }
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (DISK_READ_BUFFER + 2 * path_bytes) as u64
            );
            drop(catalog);
            let mut lengths = data.frame_lengths(&group, ctx.max_record)?;
            assert!(lengths.next().unwrap()? > 0);
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (DISK_READ_BUFFER + 2 * path_bytes) as u64
            );
            drop(lengths);
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (2 * path_bytes) as u64
            );
            drop(data);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
            assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
        }
        Ok(())
    }

    #[test]
    fn compact_parser_shares_reservations_and_releases_after_failure() -> Result<()> {
        use chopper_core::csv::{CompactRecord, Parser};
        for input in ["a,b\n", "\"unterminated", "abc,def\n"] {
            for pressure in [0, 1, 32] {
                let mut ctx = context()?;
                ctx.replace_workspace_for_test(Workspace::new(32))?;
                let mut other = Reservation::new(&ctx);
                other.resize(pressure)?;
                let mut charge = Reservation::new(&ctx);
                let mut parser = Parser::new(
                    BufReader::with_capacity(1, input.as_bytes()),
                    chopper_core::CsvSettings::default(),
                    4096,
                );
                let mut record = CompactRecord::default();
                let result = parser.next_compact_record_into_reserved(&mut record, &mut |bytes| {
                    charge.resize(bytes)
                });
                if pressure == 32 || input.contains('"') {
                    assert!(result.is_err());
                    assert!(record.is_empty());
                }
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes()
                        + (pressure + parser.scratch_capacity() + record.capacity()) as u64
                );
                drop(record);
                drop(parser);
                drop(charge);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + pressure as u64
                );
                drop(other);
                assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            }
        }
        Ok(())
    }

    #[test]
    fn owned_parser_shares_workspace_and_releases_on_failure() -> Result<()> {
        use chopper_core::csv::Parser;
        for input in ["a,b\n", "\"unterminated", "abc,def\n"] {
            for pressure in [0, 1, 256] {
                let mut ctx = context()?;
                ctx.replace_workspace_for_test(Workspace::new(256))?;
                let mut other = Reservation::new(&ctx);
                other.resize(pressure)?;
                let mut charge = Reservation::new(&ctx);
                let mut parser = Parser::new(
                    BufReader::with_capacity(1, input.as_bytes()),
                    chopper_core::CsvSettings::default(),
                    4096,
                );
                let mut fields = Vec::new();
                let result = parser
                    .next_record_into_reserved(&mut fields, &mut |bytes| charge.resize(bytes));
                if pressure == 256 || input.contains('"') {
                    assert!(result.is_err());
                } else {
                    assert!(result?);
                }
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes()
                        + (pressure
                            + parser.scratch_capacity()
                            + fields.capacity() * std::mem::size_of::<String>()
                            + fields.iter().map(String::capacity).sum::<usize>())
                            as u64
                );
                drop(fields);
                drop(parser);
                drop(charge);
                assert_eq!(
                    ctx.workspace.used(),
                    ctx.directory_reserved_bytes() + pressure as u64
                );
                drop(other);
                assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            }
        }
        Ok(())
    }

    #[test]
    fn parser_growth_spills_retained_rows_before_retrying_shared_reservation() -> Result<()> {
        use chopper_core::csv::{CompactRecord, Parser};
        let mut ctx = context()?;
        ctx.replace_workspace_for_test(Workspace::new(1_000_000))?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        for id in 0..1500 {
            sorter.push(Row {
                id,
                ordinal: id,
                key: vec![],
                fields: vec!["x".repeat(100)],
            })?;
        }
        assert_eq!(ctx.diagnostics()["sort_runs"], 0);
        let input = format!("{},tail\n", "y".repeat(200_000));
        let mut parser = Parser::new(
            BufReader::with_capacity(65536, input.as_bytes()),
            chopper_core::CsvSettings::default(),
            1_000_000,
        );
        let mut record = CompactRecord::default();
        let mut charge = Reservation::new(&ctx);
        assert!(
            parser.next_compact_record_into_reserved(&mut record, &mut |bytes| {
                sorter.reserve_input(&mut charge, bytes)
            })?
        );
        assert!(ctx.used() > 0, "parser pressure must spill retained rows");
        assert_eq!(record.fields().next().unwrap().len(), 200_000);
        drop(record);
        drop(parser);
        drop(charge);
        let ids = sorter
            .finish()?
            .map(|row| row.map(|row| row.id))
            .collect::<Result<Vec<_>>>()?;
        assert_eq!(ids, (0..1500).collect::<Vec<_>>());
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn dataset_reader_reservation_releases_after_corruption_or_cancellation() -> Result<()> {
        for cancelled in [false, true] {
            let ctx = context()?;
            let path_bytes = ctx.file_path_bytes()?;
            let mut writer = DatasetWriter::new(&ctx)?;
            let mut group = writer.begin(vec![], false);
            group.rows = 1;
            writer.data.write_all(b"truncated")?;
            writer.end(group.clone())?;
            let data = writer.finish()?;
            let mut rows = data.rows(&group, ctx.max_record)?;
            if cancelled {
                ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
                assert!(ctx.check().is_err());
            } else {
                assert!(rows.next_packed(None).is_err());
            }
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + (DISK_READ_BUFFER + 2 * path_bytes) as u64
            );
            drop(rows);
            drop(data);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn forced_collisions_conserve_duplicate_payload_ids_on_all_ingestion_paths() -> Result<()> {
        let domains = [[7; 32], [9; 32], [11; 32]];
        let count = 513u64;
        for grouped in [false, true] {
            let order = if grouped {
                SortOrder::GroupRandom
            } else {
                SortOrder::Random(domains[0])
            };
            let mut expected = (0..count).collect::<Vec<_>>();
            expected.sort_unstable_by(|&a, &b| {
                let ga = if grouped { (a % 3) as usize } else { 0 };
                let gb = if grouped { (b % 3) as usize } else { 0 };
                ga.cmp(&gb)
                    .then_with(|| chopper_core::random::compare_ties(&domains[ga], a, b))
            });
            for compact in [false, true] {
                for external in [false, true] {
                    let mut ctx = context()?;
                    ctx.memory = if external {
                        256 * 1024
                    } else {
                        32 * 1024 * 1024
                    };
                    let mut sorter = Sorter::new(&ctx, order.clone());
                    for id in (0..count).rev() {
                        let group = if grouped { (id % 3) as usize } else { 0 };
                        let mut key = Vec::new();
                        if grouped {
                            key.push(group as u8);
                        }
                        key.extend_from_slice(&[0; 16]);
                        if grouped {
                            key.extend_from_slice(&domains[group]);
                        }
                        let row = Row {
                            id,
                            ordinal: count - id,
                            key,
                            // Identity is deliberately separate from payload.
                            fields: vec!["duplicate".repeat(350), String::new(), "界".into()],
                        };
                        if compact {
                            let capacity = row.key.capacity();
                            sorter.push_compact(PackedRow::new(row)?, capacity)?;
                        } else {
                            sorter.push(row)?;
                        }
                    }
                    if external {
                        assert_eq!(sorter.fan_in(), 2);
                    }
                    let sorted = sorter.finish()?;
                    assert_eq!(matches!(sorted, SortedRows::Merge(_)), external);
                    let mut actual = Vec::new();
                    sorted.try_for_each_packed(|row| {
                        actual.push(row.id);
                        assert_eq!(row.ordinal, count - row.id);
                        assert_eq!(
                            row.fields().collect::<Vec<_>>(),
                            ["duplicate".repeat(350), String::new(), "界".into()]
                        );
                        Ok(())
                    })?;
                    assert_eq!(actual, expected);
                    actual.sort_unstable();
                    assert_eq!(actual, (0..count).collect::<Vec<_>>());
                    if external {
                        // At fan-in two, this many merges requires multiple levels.
                        assert!(ctx.diagnostics()["merge_operations"].as_u64().unwrap() > 2);
                    }
                    assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
                    assert_eq!(ctx.used(), 0);
                }
            }
        }
        Ok(())
    }

    #[test]
    fn group_selection_crosses_actual_capacity_budget_without_changing_order() -> Result<()> {
        let domain = chopper_core::random::domain("group-budget", 0, "[]");
        let order = SortOrder::Random(domain);
        let make_row = |id| {
            PackedRow::new(Row {
                id,
                ordinal: id,
                key: vec![0; 16],
                fields: vec!["x".repeat(1024)],
            })
        };
        let exact = std::mem::size_of::<Sorter>()
            + 4 * (make_row(0)?.heap_bytes() + std::mem::size_of::<PackedRow>());
        let mut expected = (0..4).collect::<Vec<_>>();
        expected.sort_unstable_by(|&a, &b| chopper_core::random::compare_ties(&domain, a, b));
        for delta in [-1isize, 0, 1] {
            let mut ctx = context()?;
            ctx.memory = exact.checked_add_signed(delta).unwrap() * 4;
            let mut sorter = Sorter::new(&ctx, order.clone());
            for id in 0..4 {
                sorter.push_compact(make_row(id)?, 16)?;
            }
            let sorted = sorter.finish()?;
            assert_eq!(matches!(sorted, SortedRows::Memory(_)), delta >= 0);
            let ids = sorted
                .map(|row| row.map(|row| row.id))
                .collect::<Result<Vec<_>>>()?;
            assert_eq!(ids, expected);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn shared_workspace_pressure_spills_or_fails_cleanly() -> Result<()> {
        let parent = tempfile::Builder::new()
            .prefix("chopper-shared-workspace-pressure-explicit-long-task-owned-parent-covering-directory-baseline-over-one-hundred-bytes-")
            .tempdir()?;
        for available in [450_000, 100] {
            let resources = chopper_core::Resources {
                temp_dir: Some(parent.path().to_string_lossy().into_owned()),
                ..Default::default()
            };
            let mut ctx = Context::with_memory_pool(
                &resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024)),
            )?;
            ctx.memory = 4 * 1024 * 1024;
            let directory_baseline = ctx.directory_reserved_bytes();
            assert!(directory_baseline > 100);
            let algorithm_limit = 200_000 + available;
            ctx.replace_workspace_for_test(Workspace::new(algorithm_limit))?;
            assert_eq!(ctx.workspace.used(), directory_baseline);
            let mut other = Reservation::new(&ctx);
            other.resize(200_000)?;
            let domain = [7; 32];
            let mut sorter = Sorter::new(&ctx, SortOrder::Random(domain));
            let result = (|| -> Result<Vec<u64>> {
                for id in 0..4 {
                    sorter.push(Row {
                        id,
                        ordinal: id,
                        key: vec![0; 16],
                        fields: vec!["x".repeat(180_000)],
                    })?;
                }
                assert!(ctx.diagnostics()["sort_runs"].as_u64().unwrap() > 0);
                sorter.finish()?.map(|row| row.map(|row| row.id)).collect()
            })();
            if available == 100 {
                assert!(result.is_err());
            } else {
                let mut expected = (0..4).collect::<Vec<_>>();
                expected
                    .sort_unstable_by(|&a, &b| chopper_core::random::compare_ties(&domain, a, b));
                assert_eq!(result?, expected);
            }
            assert_eq!(ctx.workspace.used(), directory_baseline + 200_000);
            assert_eq!(ctx.used(), 0);
            let expected_limit = directory_baseline + algorithm_limit as u64;
            let peak = ctx.workspace.peak();
            eprintln!("available={available} D={directory_baseline} peak={peak} expected_limit={expected_limit}");
            assert!(
                peak <= expected_limit,
                "available={available} D={directory_baseline} peak={peak} expected_limit={expected_limit}"
            );
            drop(other);
            assert_eq!(ctx.workspace.used(), directory_baseline);
        }
        Ok(())
    }

    #[test]
    fn compact_dataset_ingestion_preserves_frames_keys_and_sort_limits() -> Result<()> {
        let ctx = context()?;
        let mut writer = DatasetWriter::new(&ctx)?;
        let mut group = writer.begin(vec![], false);
        for (id, payload) in ["".to_owned(), "界\0\n".to_owned(), "x".repeat(100_000)]
            .into_iter()
            .enumerate()
        {
            writer.row(
                &mut group,
                &Row {
                    id: id as u64,
                    ordinal: id as u64 + 7,
                    key: vec![id as u8; 16],
                    fields: vec![payload, "selected\0".into(), "".into()],
                },
            )?;
        }
        writer.end(group.clone())?;
        let data = writer.finish()?;
        let mut owned_sort = Sorter::new(&ctx, SortOrder::Key);
        let mut compact_sort = Sorter::new(&ctx, SortOrder::Key);
        for (owned, compact) in data
            .rows(&group, ctx.max_record)?
            .zip(data.packed_rows(&group, ctx.max_record)?)
        {
            let owned = owned?;
            let compact = compact?;
            let mut expected = Vec::new();
            let mut actual = Vec::new();
            write_row(&mut expected, &owned)?;
            compact.write(&mut actual)?;
            assert_eq!(actual, expected);
            for columns in [vec![], vec![2, 0, 1], vec![1, 1, 0]] {
                assert_eq!(
                    chopper_core::random::tuple_key_views(compact.fields(), &columns),
                    chopper_core::random::tuple_key(&owned.fields, &columns)
                );
            }
            compact_sort.push_compact(compact, owned.key.capacity())?;
            owned_sort.push(owned.row)?;
            assert_eq!(compact_sort.largest_row, owned_sort.largest_row);
            assert_eq!(compact_sort.largest_key, owned_sort.largest_key);
        }
        let encode = |rows: SortedRows| -> Result<Vec<u8>> {
            let mut bytes = Vec::new();
            for row in rows {
                let row = row?;
                write_row(&mut bytes, &row)?;
            }
            Ok(bytes)
        };
        assert_eq!(
            encode(compact_sort.finish()?)?,
            encode(owned_sort.finish()?)?
        );
        // Intermediate shuffle ingestion must retain v1 keys, collision order,
        // and the owned decoder's merge allowance even for wide fields.
        let domain = [7; 32];
        let mut owned_sort = Sorter::new(&ctx, SortOrder::Random(domain));
        let mut compact_sort = Sorter::new(&ctx, SortOrder::Random(domain));
        let mut owned_shuffle = ResidentShuffle::new(&ctx, domain);
        let mut compact_shuffle = ResidentShuffle::new(&ctx, domain);
        for (owned, compact) in data
            .rows(&group, ctx.max_record)?
            .zip(data.packed_rows(&group, ctx.max_record)?)
        {
            let owned = owned?;
            let mut compact = compact?;
            // Deliberate equal keys exercise seeded collision refinement.
            let key = [3; 16];
            compact.key = PackedKey::Random(key);
            compact_sort.push_compact(compact, 16)?;
            owned_sort.push_random(owned.clone(), key)?;
            assert_eq!(compact_sort.largest_row, owned_sort.largest_row);
            assert_eq!(compact_sort.largest_key, owned_sort.largest_key);
            owned_shuffle.push(owned.row)?;
        }
        for row in data.packed_rows(&group, ctx.max_record)? {
            compact_shuffle.push_compact(row?)?;
        }
        assert_eq!(
            encode(compact_sort.finish()?)?,
            encode(owned_sort.finish()?)?
        );
        assert_eq!(
            encode(SortedRows::Memory(compact_shuffle.finish()?))?,
            encode(SortedRows::Memory(owned_shuffle.finish()?))?
        );
        let mut reusable = None;
        let mut reader = data.rows(&group, ctx.max_record)?;
        for expected in data.rows(&group, ctx.max_record)? {
            let row = reader.next_packed(reusable.take())?.unwrap();
            let mut actual = Vec::new();
            row.write(&mut actual)?;
            let mut encoded = Vec::new();
            let expected = expected?;
            write_row(&mut encoded, &expected)?;
            assert_eq!(actual, encoded);
            reusable = Some(row);
        }
        assert!(reader.next_packed(reusable)?.is_none());
        let mut truncated = group;
        truncated.rows += 1;
        assert!(data
            .packed_rows(&truncated, ctx.max_record)?
            .last()
            .unwrap()
            .is_err());
        Ok(())
    }

    #[test]
    fn borrowed_field_validation_matches_utf8_and_preserves_exact_boundaries() -> Result<()> {
        let check = |bytes: &[u8]| -> Result<()> {
            let valid = std::str::from_utf8(bytes).is_ok();
            for capacity in [1, 2, 3, 4, 7, 64] {
                let mut source = bytes.to_vec();
                source.push(0xff); // Must not be read as part of this field.
                let mut reader = BufReader::with_capacity(capacity, source.as_slice());
                let mut copied = Vec::new();
                let result = visit_utf8_field(&mut reader, bytes.len(), |chunk| {
                    copied.extend_from_slice(chunk);
                    Ok(())
                });
                assert_eq!(result.is_ok(), valid, "{bytes:?} / buffer {capacity}");
                if valid {
                    assert_eq!(copied, bytes);
                    let mut next = [0];
                    reader.read_exact(&mut next)?;
                    assert_eq!(next, [0xff]);
                }
            }
            Ok(())
        };
        let text =
            "\0\u{7f}\u{80}\u{7ff}\u{800}\u{d7ff}\u{e000}\u{ffff}\u{10000}\u{10ffff}\r\n界🙂";
        let text = text.repeat(7);
        for end in 0..=text.len() {
            check(&text.as_bytes()[..end])?;
        }
        for a in 0..=255 {
            check(&[a])?;
            for b in 0..=255 {
                check(&[a, b])?;
            }
        }
        // Surrogates, overlong encodings, values beyond Unicode and invalid
        // continuations after otherwise valid prefixes, split at every byte.
        for bytes in [
            &[0xe0, 0x80, 0x80][..],
            &[0xed, 0xa0, 0x80],
            &[0xf0, 0x80, 0x80, 0x80],
            &[0xf4, 0x90, 0x80, 0x80],
            &[0xf5, 0x80, 0x80, 0x80],
            &[0xe2, b'a', 0xac],
            &[0xf0, 0x90, b'a', 0x80],
        ] {
            let mut source = b"valid prefix".to_vec();
            source.extend_from_slice(bytes);
            check(&source)?;
        }
        Ok(())
    }

    #[test]
    fn borrowed_fields_reject_truncation_and_propagate_output_errors() -> Result<()> {
        for capacity in [1, 2, 7, 64] {
            let source = "界🙂".as_bytes();
            let mut reader = BufReader::with_capacity(capacity, source);
            assert!(visit_utf8_field(&mut reader, source.len() + 1, |_| Ok(())).is_err());
            // An incomplete first field cannot borrow continuation bytes from
            // the following field, even when they share a reader buffer.
            let mut reader = BufReader::with_capacity(capacity, source);
            assert!(visit_utf8_field(&mut reader, 1, |_| Ok(())).is_err());
            let mut reader = BufReader::with_capacity(capacity, source);
            let error = visit_utf8_field(&mut reader, source.len(), |_| {
                Err(io::Error::other("injected output failure"))
            })
            .unwrap_err();
            assert_eq!(error.to_string(), "injected output failure");
        }
        Ok(())
    }

    #[test]
    fn frame_scanner_matches_decoder_with_small_buffers_and_corruption() -> Result<()> {
        let maximum = 4096;
        let row = Row {
            id: 7,
            ordinal: 9,
            key: vec![0xff; 17], // Keys are bytes, not UTF-8.
            fields: vec!["".into(), "aé🙂\n\"".repeat(90), "last".into()],
        };
        let mut encoded = Vec::new();
        write_row(&mut encoded, &row)?;
        let mut cases = vec![encoded.clone()];
        // Every possible truncation, including inside lengths and UTF-8 sequences.
        cases.extend((1..encoded.len()).map(|n| encoded[..n].to_vec()));
        let key_length_offset = 16;
        let count_offset = 24 + row.key.len();
        let first_length_offset = count_offset + 8;
        for (offset, value) in [
            (key_length_offset, u64::MAX),
            (count_offset, u64::MAX),
            (first_length_offset, maximum as u64 + 1),
            (first_length_offset + 8, maximum as u64),
        ] {
            let mut corrupt = encoded.clone();
            corrupt[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
            cases.push(corrupt);
        }
        let mut invalid_utf8 = encoded.clone();
        invalid_utf8[first_length_offset + 16] = 0xff;
        cases.push(invalid_utf8);
        // Each field fits separately, but their cumulative payload exceeds the cap.
        let mut oversized = Vec::new();
        write_row(
            &mut oversized,
            &Row {
                fields: vec!["x".repeat(3000), "y".repeat(2000)],
                ..row.clone()
            },
        )?;
        cases.push(oversized);
        for capacity in [1, 7, 64, 65536] {
            for bytes in &cases {
                let decoded = read_row(&mut io::Cursor::new(bytes), maximum);
                let compact = (|| -> Result<Option<Row>> {
                    let mut reader = BufReader::with_capacity(capacity, bytes.as_slice());
                    read_header(&mut reader, maximum)?
                        .map(|header| {
                            PackedRow::read_fields(&mut reader, maximum, header)?.unpack()
                        })
                        .transpose()
                })();
                match (&decoded, compact) {
                    (Ok(Some(expected)), Ok(Some(actual))) => {
                        assert_eq!(actual.fields, expected.fields);
                        assert_eq!(actual.key, expected.key);
                        assert_eq!((actual.id, actual.ordinal), (expected.id, expected.ordinal));
                    }
                    (Err(_), Err(_)) => (),
                    other => panic!("owned/compact decoder mismatch: {other:?}"),
                }
                let reused = (|| -> Result<Option<Row>> {
                    let mut reader = BufReader::with_capacity(capacity, bytes.as_slice());
                    read_header(&mut reader, maximum)?
                        .map(|header| {
                            PackedRow::read_fields_reusing(
                                &mut reader,
                                maximum,
                                header,
                                Some(PackedRow::new(row.clone())?),
                            )?
                            .unpack()
                        })
                        .transpose()
                })();
                match (&decoded, reused) {
                    (Ok(Some(expected)), Ok(Some(actual))) => {
                        assert_eq!(actual.fields, expected.fields);
                        assert_eq!(actual.key, expected.key);
                    }
                    (Err(_), Err(_)) => (),
                    other => panic!("owned/reused decoder mismatch: {other:?}"),
                }
                let scanned = scan_row(
                    &mut BufReader::with_capacity(capacity, bytes.as_slice()),
                    maximum,
                );
                match (decoded, scanned) {
                    (Ok(Some(row)), Ok(Some(length))) => assert_eq!(length, row.disk_len()),
                    (Err(_), Err(_)) => (),
                    other => panic!(
                        "decoder/scanner mismatch at buffer {capacity}, length {}: {other:?}",
                        bytes.len()
                    ),
                }
            }
            let stream = encoded.repeat(3);
            let mut reader = BufReader::with_capacity(capacity, stream.as_slice());
            for _ in 0..3 {
                assert_eq!(scan_row(&mut reader, maximum)?, Some(row.disk_len()));
            }
            assert_eq!(scan_row(&mut reader, maximum)?, None);
        }
        Ok(())
    }

    #[test]
    fn inline_random_ingestion_preserves_collision_order_across_budgets() -> Result<()> {
        let domain = chopper_core::random::domain("inline-keys", 0, "[]");
        let order = SortOrder::Random(domain);
        // Exercise a large resident comparison sort while
        // retaining comparison-sorted spill buffers under the small budget.
        let rows: Vec<_> = (0..17_000)
            .map(|id| Row {
                id,
                ordinal: 17_000 - id,
                key: vec![(id % 3) as u8; 16],
                fields: vec![format!("{id},界")],
            })
            .collect();
        let mut expected = rows.clone();
        expected.sort_unstable_by(|a, b| order.compare(a, b));
        for memory in [256 * 1024, 32 * 1024 * 1024] {
            let mut ctx = context()?;
            ctx.memory = memory;
            let mut sorter = Sorter::new(&ctx, order.clone());
            for row in &rows {
                let key = row.key.as_slice().try_into().unwrap();
                sorter.push_random(row.clone(), key)?;
            }
            let actual = sorter.finish()?.collect::<Result<Vec<_>>>()?;
            let diagnostics = ctx.diagnostics();
            assert_eq!(diagnostics["sort_rows"], rows.len() as u64);
            assert_eq!(
                diagnostics["sort_calls"].as_u64().unwrap(),
                diagnostics["sort_runs"].as_u64().unwrap()
                    + diagnostics["resident_sorts"].as_u64().unwrap()
            );
            assert!(diagnostics["sort_seconds"].as_f64().unwrap() >= 0.0);
            assert_eq!(actual.len(), expected.len());
            for (actual, expected) in actual.iter().zip(&expected) {
                assert_eq!(actual.id, expected.id);
                assert_eq!(actual.ordinal, expected.ordinal);
                assert_eq!(actual.key, expected.key);
                assert_eq!(actual.fields, expected.fields);
            }
            assert!(
                ctx.workspace.used() > 0,
                "returned rows lost their reservations"
            );
            drop(actual);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }

    fn context() -> Result<Context> {
        // Capacity tests may fill the whole workspace. Keep this fixture's
        // ledger independent of unrelated tests executing in the same process.
        Context::with_memory_pool(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024)),
        )
    }

    #[test]
    fn routed_cursor_reuses_payload_across_groups_and_releases_on_exit() -> Result<()> {
        for cancel in [false, true] {
            let ctx = context()?;
            let mut sorter = Sorter::streaming(&ctx);
            for id in 0..4 {
                sorter.push(Row {
                    id,
                    ordinal: id,
                    key: vec![(id / 2) as u8],
                    fields: vec!["界".into(), "x".repeat(if id == 0 { 65536 } else { 3 })],
                })?;
            }
            let sorted = sorter.finish()?;
            assert!(matches!(sorted, SortedRows::Routed(_)));
            let mut rows = sorted.reusing();
            let mut pointer = None;
            for id in 0..4 {
                let row = rows.next()?.unwrap();
                assert_eq!((row.id, row.ordinal), (id, id));
                assert_eq!(&*row.key, &[(id / 2) as u8]);
                let field = row.fields().nth(1).unwrap();
                assert_eq!(field.len(), if id == 0 { 65536 } else { 3 });
                if let Some(pointer) = pointer {
                    assert_eq!(field.as_ptr(), pointer);
                }
                pointer = Some(field.as_ptr());
                // Consumers clear keys and rewrite ordinals before the next decode.
                row.key = PackedKey::Bytes(Box::default());
                row.ordinal = 99;
                if cancel && id == 2 {
                    ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
                    assert!(rows.next().is_err());
                    assert!(rows.next()?.is_none());
                    break;
                }
            }
            if !cancel {
                assert!(rows.next()?.is_none());
            }
            drop(rows);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn encoded_merge_preserves_frames_across_composite_runs_and_wide_fields() -> Result<()> {
        for mode in 0..5 {
            let ctx = context()?;
            let rows: Vec<_> = (0..18)
                .map(|id| Row {
                    id,
                    ordinal: id,
                    key: vec![id as u8],
                    fields: vec![
                        String::new(),
                        "界\0\r\n\"".into(),
                        "x".repeat(if id == 7 { 65536 } else { 3 }),
                    ],
                })
                .collect();
            let largest = rows.iter().map(Row::memory).max().unwrap();
            let mut runs = Catalog::new(&ctx);
            for start in 0..3 {
                let mut files = Catalog::new(&ctx);
                for row in rows.iter().skip(start).step_by(3) {
                    let mut file = ctx.file()?;
                    write_row(&mut file, row)?;
                    #[cfg(feature = "experimental-spill-blocks")]
                    let file = SpillFile::from(file);
                    files.push(file)?;
                }
                runs.push(SortRun(files, None))?;
            }
            let mut merged = MergeRows::new(runs, SortOrder::Key, &ctx, largest, 1)?;
            let mut actual = Vec::new();
            if mode >= 3 {
                let result = SortedRows::Merge(merged).try_for_each_packed(|row| {
                    if mode == 4 && row.id == 9 {
                        anyhow::bail!("injected sink failure after wide row");
                    }
                    row.write(&mut actual)
                });
                if mode == 4 {
                    assert!(result.is_err());
                } else {
                    result?;
                    let mut expected = Vec::new();
                    for row in &rows {
                        write_row(&mut expected, row)?;
                    }
                    assert_eq!(actual, expected);
                }
                assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
                assert_eq!(ctx.used(), 0);
                continue;
            }
            if mode == 0 {
                while merged.copy_next(&mut actual)? {}
            } else if mode == 1 {
                while let Some(row) = merged.next_compact() {
                    row?.write(&mut actual)?;
                }
            } else {
                for row in &mut merged {
                    let row = row?;
                    write_row(&mut actual, &row)?;
                }
            }
            let mut expected = Vec::new();
            for row in &rows {
                write_row(&mut expected, row)?;
            }
            assert_eq!(actual, expected);
            drop(merged);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn all_merge_consumers_reject_corrupt_payloads_and_release_files() -> Result<()> {
        for mode in 0..4 {
            for corrupt in 0..4 {
                let ctx = context()?;
                let mut data = Vec::new();
                write_row(
                    &mut data,
                    &Row {
                        id: 0,
                        ordinal: 0,
                        key: vec![],
                        fields: vec!["hello".into()],
                    },
                )?;
                match corrupt {
                    0 => {
                        data.pop();
                    } // truncated field
                    1 => {
                        data[40] = 0xff;
                    } // invalid UTF-8
                    2 => {
                        data[32..40].copy_from_slice(&u64::MAX.to_le_bytes());
                    }
                    _ => {
                        data[24..32].copy_from_slice(&u64::MAX.to_le_bytes());
                    }
                }
                let mut file = ctx.file()?;
                file.write_all(&data)?;
                let mut merged = {
                    let mut runs = Catalog::new(&ctx);
                    runs.push(SortRun::single(&ctx, file)?)?;
                    MergeRows::new(runs, SortOrder::Key, &ctx, 128, 0)?
                };
                if mode == 3 {
                    assert!(SortedRows::Merge(merged)
                        .try_for_each_packed(|_| Ok(()))
                        .is_err());
                    assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
                    assert_eq!(ctx.used(), 0);
                    continue;
                }
                if mode == 0 {
                    assert!(merged.copy_next(&mut Vec::new()).is_err());
                } else if mode == 1 {
                    assert!(merged.next_compact().unwrap().is_err());
                    assert!(merged.next_compact().is_none());
                } else {
                    assert!(merged.next().unwrap().is_err());
                    assert!(merged.next().is_none());
                }
                drop(merged);
                assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
                assert_eq!(ctx.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn rare_wide_payload_does_not_reserve_one_decoded_row_per_run() -> Result<()> {
        let ctx = Context::new(
            &chopper_core::Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut runs = Catalog::new(&ctx);
        let mut largest = 0;
        for id in 0..64 {
            let row = Row {
                id,
                ordinal: id,
                key: vec![id as u8],
                fields: vec!["x".repeat(if id == 0 { 1024 * 1024 } else { 1 })],
            };
            largest = largest.max(row.memory());
            let mut file = ctx.file()?;
            write_row(&mut file, &row)?;
            runs.push(SortRun::single(&ctx, file)?)?;
        }
        // Reserving the largest decoded row for all 64 runs would exceed this
        // context's 16 MiB workspace ceiling, despite only one wide payload.
        let merged = MergeRows::new(runs, SortOrder::Key, &ctx, largest, 1)?;
        for (id, row) in merged.enumerate() {
            let row = row?;
            assert_eq!(row.id, id as u64);
            assert_eq!(row.fields[0].len(), if id == 0 { 1024 * 1024 } else { 1 });
        }
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        assert_eq!(ctx.used(), 0);
        Ok(())
    }
}

#[cfg(all(target_os = "wasi", feature = "resource-contract-tests"))]
pub(crate) fn hosted_uniform_retention_contract() -> Result<serde_json::Value> {
    use crate::resources::MemoryPool;

    const MIB: usize = 1024 * 1024;
    const EFFECTIVE: usize = 1024 * MIB;
    const EXTENDED: usize = 320 * MIB;
    const ORDINARY: usize = 256 * MIB;
    const HEADROOM: usize = 448 * MIB;

    let mut cases = Vec::new();
    for available in [HEADROOM - 1, HEADROOM] {
        let pool = Arc::new(MemoryPool::new(EFFECTIVE as u64));
        let ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                memory_mb: 1024.into(),
                workers: 1,
                temp_dir: Some("/tmp".into()),
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let mut peer =
            Reservation::for_workspace(Arc::new(Workspace::shared(EFFECTIVE, pool.clone())));
        peer.resize(EFFECTIVE - available - pool.usage().reserved_bytes as usize)?;
        ensure!(ctx.working_headroom() == available as u64);
        let mut sorter = Sorter::new(&ctx, SortOrder::Random([0; 32]));
        sorter.prefer_hosted_resident();
        let selected = sorter.buffer_limit;
        ensure!(
            selected
                == if available == HEADROOM {
                    EXTENDED
                } else {
                    ORDINARY
                }
        );
        sorter.push(Row {
            id: 0,
            ordinal: 0,
            key: 0u128.to_be_bytes().to_vec(),
            fields: vec!["retained".into()],
        })?;
        sorter.flush()?;
        ensure!(sorter.buffer_limit == ORDINARY);
        let mut rows = 0;
        sorter.finish()?.try_for_each_packed(|row| {
            ensure!(row.id == 0 && row.fields().next() == Some("retained"));
            rows += 1;
            Ok(())
        })?;
        ensure!(rows == 1 && ctx.used() == 0);
        drop(ctx);
        ensure!(pool.usage().reserved_bytes == peer.bytes());
        drop(peer);
        ensure!(pool.usage().reserved_bytes == 0);
        cases.push(serde_json::json!({
            "available_bytes": available,
            "selected_sort_target_bytes": selected,
            "sort_target_bytes_after_spill": ORDINARY,
            "cleaned": true,
        }));
    }
    Ok(serde_json::json!(cases))
}
