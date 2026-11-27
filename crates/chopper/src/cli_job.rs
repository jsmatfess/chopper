//! Decode-origin payload owner. See docs/cli-job-decoding.md.
use crate::{
    engine,
    resources::{process_memory, MemoryAdmission, MemoryPool},
};
use anyhow::{ensure, Result};
use chopper_core::Job;
use std::{
    io::{self, Read},
    sync::Arc,
};
#[cfg(not(target_os = "wasi"))]
use {
    crate::storage::Notify,
    anyhow::Context,
    chopper_core::MemoryBudget,
    std::{path::Path, sync::atomic::AtomicBool},
};
#[cfg(not(target_os = "wasi"))]
mod diagnostics;
#[cfg(not(target_os = "wasi"))]
pub use diagnostics::JobJsonPath;
#[cfg(any(
    all(test, not(target_os = "wasi")),
    all(target_os = "wasi", feature = "resource-contract-tests")
))]
mod census;
mod prefix;
#[cfg(all(test, not(target_os = "wasi")))]
mod tests;
#[cfg(all(test, target_os = "linux"))]
pub(crate) use census::observed_allocation_requests;
#[cfg(all(test, not(target_os = "wasi")))]
pub(crate) use census::{
    begin as start_allocation_observation, end as finish_allocation_observation,
};
#[cfg(all(target_os = "wasi", feature = "resource-contract-tests"))]
mod wasi_contracts;
#[cfg(target_os = "wasi")]
const BUFFER_BYTES: usize = 8 * 1024;
#[cfg(not(target_os = "wasi"))]
const BUFFER_BYTES: usize = 0;
#[cfg(not(target_os = "wasi"))]
pub(crate) const MAX_JOB_BYTES: u64 = 1024 * 1024;
const DECODE_ORIGIN: &str = if cfg!(target_os = "wasi") {
    "Job"
} else {
    "CLI Job"
};

struct Grant {
    pool: Arc<MemoryPool>,
    bytes: usize,
}
impl Grant {
    fn new(pool: Arc<MemoryPool>) -> Self {
        Self { pool, bytes: 0 }
    }
    fn grow(&mut self, bytes: usize) -> std::result::Result<(), MemoryAdmission> {
        if bytes > self.bytes {
            self.pool.try_acquire((bytes - self.bytes) as u64)?;
            self.bytes = bytes;
        }
        #[cfg(any(
            all(test, not(target_os = "wasi")),
            all(target_os = "wasi", feature = "resource-contract-tests")
        ))]
        census::observe_grant(self.bytes);
        Ok(())
    }
    fn shrink(&mut self, bytes: usize) {
        assert!(bytes <= self.bytes);
        #[cfg(any(
            all(test, not(target_os = "wasi")),
            all(target_os = "wasi", feature = "resource-contract-tests")
        ))]
        census::observe_grant(bytes);
        self.pool.release((self.bytes - bytes) as u64);
        self.bytes = bytes;
    }
}
impl Drop for Grant {
    fn drop(&mut self) {
        self.shrink(0);
    }
}

enum Denial {
    Shared(MemoryAdmission),
    Overflow,
}
struct AdmittedReader<'a, R> {
    source: R,
    prefix: prefix::Prefix,
    grant: &'a mut Grant,
    denial: Option<Denial>,
    #[cfg(not(target_os = "wasi"))]
    track_paths: bool,
}
impl<R: Read> Read for AdmittedReader<'_, R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        if self.denial.is_some() {
            return Err(io::ErrorKind::Other.into());
        }
        let mut byte = [0];
        if self.source.read(&mut byte)? == 0 {
            return Ok(0);
        }
        let allowance = self.prefix.advance(byte[0]);
        #[cfg(not(target_os = "wasi"))]
        let allowance = allowance.and_then(|required| {
            if self.track_paths {
                // A tracked seed can retain an active key and clone it into the deserializer.
                let text_bound = if self.prefix.fallback {
                    self.prefix.bytes
                } else {
                    self.prefix.text
                };
                required.checked_add(text_bound.checked_mul(2)?)
            } else {
                Some(required)
            }
        });
        match allowance.and_then(|bytes| bytes.checked_add(BUFFER_BYTES)) {
            None => self.denial = Some(Denial::Overflow),
            Some(required) => {
                if let Err(error) = self.grant.grow(required) {
                    self.denial = Some(Denial::Shared(error));
                }
            }
        }
        if self.denial.is_some() {
            #[cfg(all(target_os = "wasi", feature = "resource-contract-tests"))]
            census::census(|c| c.enabled = false);
            return Err(io::ErrorKind::Other.into());
        }
        output[0] = byte[0];
        Ok(1)
    }
}

/// Immutable decoded payload followed by its source grant in destruction order.
/// There is no bare extraction, mutable borrow or Clone. Ordinary core/engine
/// APIs continue to accept caller-owned Jobs independently of this facade.
///
/// ```compile_fail
/// fn grow(owner: &mut chopper::cli_job::DecodedJob) {
///     owner.job().input.push_str("unadmitted");
/// }
/// ```
pub struct DecodedJob {
    job: Job,
    _grant: Grant,
}
#[cfg(not(target_os = "wasi"))]
impl DecodedJob {
    /// Preserve metadata-only 1 MiB rejection and metadata/open error ordering.
    pub fn read(path: impl AsRef<Path>) -> Result<Self> {
        Self::read_path(path.as_ref(), process_memory, false)
    }

    /// Decode the same Job with field-path context for JSON data errors.
    pub fn read_with_diagnostics(path: impl AsRef<Path>) -> Result<Self> {
        Self::read_path(path.as_ref(), process_memory, true)
    }

    fn read_path(
        path: &Path,
        pool: impl FnOnce() -> Result<Arc<MemoryPool>>,
        track_paths: bool,
    ) -> Result<Self> {
        let metadata = std::fs::metadata(path)?;
        Self::open_after_metadata(
            metadata.len(),
            || std::fs::File::open(path),
            pool,
            track_paths,
        )
    }
    fn open_after_metadata<R: Read>(
        length: u64,
        open: impl FnOnce() -> io::Result<R>,
        pool: impl FnOnce() -> Result<Arc<MemoryPool>>,
        track_paths: bool,
    ) -> Result<Self> {
        ensure!(length <= MAX_JOB_BYTES, "configuration exceeds 1 MiB");
        let file = open()?;
        Self::decode(file, pool()?, track_paths)
    }
    fn decode(source: impl Read, pool: Arc<MemoryPool>, track_paths: bool) -> Result<Self> {
        Self::decode_admitted(|| source, pool, track_paths)
    }
    pub(crate) fn from_json(json: &str) -> Result<Self> {
        Self::open_after_metadata(
            json.len() as u64,
            || Ok(json.as_bytes()),
            process_memory,
            true,
        )
    }
    pub(crate) fn copy_for_run(settings: &Job) -> Result<Self> {
        let mut grant = Grant::new(process_memory()?);
        // Clone allocates by length for the schema's Vec and String fields.
        grant.grow(engine::job_capacity(settings)?)?;
        let job = settings.clone();
        let retained = engine::job_capacity(&job)?;
        ensure!(
            retained <= grant.bytes,
            "Job copy exceeds admitted capacity"
        );
        grant.shrink(retained);
        Ok(Self { job, _grant: grant })
    }
    pub fn resource_overrides(
        mut self,
        memory: Option<MemoryBudget>,
        workers: Option<usize>,
    ) -> Self {
        if let Some(memory) = memory {
            self.job.resources.memory_mb = memory;
        }
        if let Some(workers) = workers {
            self.job.resources.workers = workers;
        }
        self
    }
    /// Transfer the decoded configuration and its shared grant at Run preparation.
    pub fn run(self, cancel: Arc<AtomicBool>, notify: Notify) -> Result<engine::Analysis> {
        self.run_advised(cancel, notify, None)
    }
    pub fn run_advised(
        self,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        hint: Option<engine::AutoObservations>,
    ) -> Result<engine::Analysis> {
        engine::run_decoded_native(self, cancel, notify, hint)
    }
    /// Inspect input while retaining the decoded configuration's shared grant.
    pub fn analyze(
        self,
        cancel: Arc<AtomicBool>,
        notify: Notify,
    ) -> Result<crate::profile::InputProfile> {
        let Self { job, _grant: grant } = self;
        let result = crate::profile::ProfileCache::with_memory_pool(grant.pool.clone())
            .profile(&job, cancel, notify);
        drop(job);
        drop(grant);
        result
    }
}

#[cfg(target_os = "wasi")]
impl DecodedJob {
    /// Read the browser Job with the existing WASI source buffer.
    pub fn read_hosted() -> Result<Self> {
        let file = std::fs::File::open("/job.json")?;
        Self::decode_buffered(file, process_memory()?)
    }

    /// Read the browser inspection Job with the existing WASI source buffer.
    pub fn read_inspection() -> Result<Self> {
        Self::read_hosted()
    }

    fn decode_buffered(source: impl Read, pool: Arc<MemoryPool>) -> Result<Self> {
        Self::decode_admitted(|| io::BufReader::with_capacity(BUFFER_BYTES, source), pool)
    }

    #[cfg(feature = "resource-contract-tests")]
    pub fn resource_contracts() -> Result<serde_json::Value> {
        wasi_contracts::run()
    }

    #[cfg(feature = "resource-contract-tests")]
    pub fn inspection_reserved_bytes() -> Result<usize> {
        Ok(process_memory()?.reservation_counts().0 as usize)
    }
}

#[cfg(any(target_os = "wasi", test))]
impl DecodedJob {
    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(crate) fn decode_for_run_test(source: impl Read, pool: Arc<MemoryPool>) -> Result<Self> {
        #[cfg(target_os = "wasi")]
        {
            Self::decode_buffered(source, pool)
        }
        #[cfg(not(target_os = "wasi"))]
        {
            Self::decode(source, pool, false)
        }
    }

    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(crate) fn with_test_seed(mut self) -> Result<Self> {
        let seed = "seed";
        self._grant.grow(self._grant.bytes + seed.len())?;
        self.job.random_seed = Some(seed.into());
        Ok(self)
    }
}

impl DecodedJob {
    pub(crate) fn pool(&self) -> &Arc<MemoryPool> {
        &self._grant.pool
    }

    #[cfg(target_os = "wasi")]
    pub(crate) fn memory_credit(&self, pool: &MemoryPool) -> u64 {
        if std::ptr::eq(Arc::as_ptr(&self._grant.pool), pool) {
            self._grant.bytes as u64
        } else {
            0
        }
    }

    pub(crate) fn into_workspace(
        mut self,
        memory: &mut crate::storage::Reservation,
        bytes: usize,
    ) -> Result<Job> {
        memory.accept_shared(bytes, &self._grant.pool, self._grant.bytes)?;
        // The workspace now owns the original charge and any seed delta.
        self._grant.bytes = 0;
        Ok(self.job)
    }
    fn decode_admitted<R: Read>(
        open_reader: impl FnOnce() -> R,
        pool: Arc<MemoryPool>,
        #[cfg(not(target_os = "wasi"))] track_paths: bool,
    ) -> Result<Self> {
        let mut grant = Grant::new(pool);
        let initial = grant.grow(prefix::DEFAULTS + BUFFER_BYTES);
        #[cfg(all(target_os = "wasi", feature = "resource-contract-tests"))]
        if initial.is_err() {
            census::census(|c| c.enabled = false);
        }
        #[cfg(not(target_os = "wasi"))]
        initial.context("read job JSON")?;
        #[cfg(target_os = "wasi")]
        initial?;
        let mut reader = AdmittedReader {
            source: open_reader(),
            prefix: prefix::Prefix::default(),
            grant: &mut grant,
            denial: None,
            #[cfg(not(target_os = "wasi"))]
            track_paths,
        };
        #[cfg(not(target_os = "wasi"))]
        let (result, path) = if track_paths {
            diagnostics::decode(&mut reader)
        } else {
            (serde_json::from_reader::<_, Job>(&mut reader), None)
        };
        #[cfg(target_os = "wasi")]
        let result = serde_json::from_reader::<_, Job>(&mut reader);
        let denial = reader.denial.take();
        drop(reader);
        if let Some(denial) = denial {
            // from_reader has destroyed scratch/partial values. Error carriers
            // are excluded, and are constructed only after the sticky transport.
            drop(result);
            let error = match denial {
                Denial::Shared(error) => anyhow::Error::new(error),
                Denial::Overflow => anyhow::anyhow!("{DECODE_ORIGIN} decoding capacity overflow"),
            };
            #[cfg(not(target_os = "wasi"))]
            let error = error.context("read job JSON");
            return Err(error);
        }
        #[cfg(not(target_os = "wasi"))]
        let job = match path {
            Some(path) => result.context(JobJsonPath::from_serde(path)),
            None => result.context("read job JSON"),
        }?;
        #[cfg(target_os = "wasi")]
        let job = result?;
        let retained = engine::job_capacity(&job)?;
        ensure!(
            retained <= grant.bytes,
            "{DECODE_ORIGIN} decoder exceeded audited construction allowance"
        );
        grant.shrink(retained);
        Ok(Self { job, _grant: grant })
    }
    pub fn job(&self) -> &Job {
        &self.job
    }
}
