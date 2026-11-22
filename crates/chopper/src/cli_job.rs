//! Native scripted CLI decode-origin payload owner. See docs/cli-job-decoding.md.
use crate::{
    engine,
    resources::{process_memory, MemoryAdmission, MemoryPool},
    storage::Notify,
};
use anyhow::{ensure, Context, Result};
use chopper_core::{Job, MemoryBudget};
use std::{
    io::{self, Read},
    path::Path,
    sync::{atomic::AtomicBool, Arc},
};
mod prefix;
#[cfg(test)]
mod tests;

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
        #[cfg(test)]
        tests::observe_grant(self.bytes);
        Ok(())
    }
    fn shrink(&mut self, bytes: usize) {
        assert!(bytes <= self.bytes);
        #[cfg(test)]
        tests::observe_grant(bytes);
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
        match self.prefix.advance(byte[0]) {
            None => self.denial = Some(Denial::Overflow),
            Some(required) => {
                if let Err(error) = self.grant.grow(required) {
                    self.denial = Some(Denial::Shared(error));
                }
            }
        }
        if self.denial.is_some() {
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
    grant: Grant,
}
impl DecodedJob {
    /// Preserve metadata-only 1 MiB rejection and metadata/open error ordering.
    pub fn read(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let metadata = std::fs::metadata(path)?;
        Self::open_after_metadata(metadata.len(), || std::fs::File::open(path), process_memory)
    }
    fn open_after_metadata<R: Read>(
        length: u64,
        open: impl FnOnce() -> io::Result<R>,
        pool: impl FnOnce() -> Result<Arc<MemoryPool>>,
    ) -> Result<Self> {
        ensure!(length <= 1024 * 1024, "configuration exceeds 1 MiB");
        let file = open()?;
        Self::decode(file, pool()?)
    }
    fn decode(source: impl Read, pool: Arc<MemoryPool>) -> Result<Self> {
        let mut grant = Grant::new(pool);
        grant.grow(prefix::DEFAULTS).context("read job JSON")?;
        let mut reader = AdmittedReader {
            source,
            prefix: prefix::Prefix::default(),
            grant: &mut grant,
            denial: None,
        };
        let result = serde_json::from_reader::<_, Job>(&mut reader);
        let denial = reader.denial.take();
        drop(reader);
        if let Some(denial) = denial {
            // from_reader has destroyed scratch/partial values. Error carriers
            // are excluded, and are constructed only after the sticky transport.
            drop(result);
            return match denial {
                Denial::Shared(error) => Err(anyhow::Error::new(error)),
                Denial::Overflow => Err(anyhow::anyhow!("CLI Job decoding capacity overflow")),
            }
            .context("read job JSON");
        }
        let job = result.context("read job JSON")?;
        let retained = engine::job_capacity(&job)?;
        ensure!(
            retained <= grant.bytes,
            "CLI Job decoder exceeded audited construction allowance"
        );
        grant.shrink(retained);
        Ok(Self { job, grant })
    }
    pub fn job(&self) -> &Job {
        &self.job
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
    /// Retain the source grant until all consuming engine work returns.
    pub fn run(self, cancel: Arc<AtomicBool>, notify: Notify) -> Result<engine::Analysis> {
        self.run_advised(cancel, notify, None)
    }
    pub fn run_advised(
        self,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        hint: Option<engine::AutoObservations>,
    ) -> Result<engine::Analysis> {
        let Self { job, grant } = self;
        let result = engine::run_with_auto(job, cancel, notify, grant.pool.clone(), hint);
        drop(grant);
        result
    }
    /// Inspect input while retaining the decoded configuration's shared grant.
    pub fn analyze(
        self,
        cancel: Arc<AtomicBool>,
        notify: Notify,
    ) -> Result<crate::profile::InputProfile> {
        let Self { job, grant } = self;
        let result = crate::profile::ProfileCache::with_memory_pool(grant.pool.clone())
            .profile(&job, cancel, notify);
        drop(job);
        drop(grant);
        result
    }
}
