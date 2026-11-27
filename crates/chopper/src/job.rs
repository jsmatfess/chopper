//! Synchronous file-to-file Jobs for native Rust callers.
use crate::{
    cli_job::DecodedJob,
    profile::{InputProfile, ProfileCache},
    storage::{Cancelled, Notify, ProgressPhase},
};
use anyhow::ensure;
use serde::Serialize;
use std::{
    fmt,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};

pub use crate::{
    profile::{ColumnProfile, StageProfile, WriterEstimate},
    storage::Progress,
};
pub use chopper_core::{
    Allocation, CalculatedColumn, Column, Compression, CsvSettings, CsvTrim, FullShuffleAlgorithm,
    FullShuffleRng, Grouping, InputDialect, Job as JobSettings, Limits, MemoryBudget, Operation,
    Resources, Shuffle,
};

mod error;
mod save;
mod worker;
pub use error::Error;
#[doc(hidden)]
pub use save::{display_guide_text, save_guide_configuration};

/// An ordered, reusable sequence of existing Job operations.
#[derive(Clone, Debug, Default)]
pub struct Pipeline(Vec<Operation>);

impl Pipeline {
    pub fn new() -> Self {
        Self::default()
    }

    /// Return a new pipeline by appending an operation or another pipeline.
    pub fn then(&self, next: impl Into<Self>) -> Self {
        let mut combined = self.clone();
        combined.0.extend(next.into().0);
        combined
    }

    pub fn operations(&self) -> &[Operation] {
        &self.0
    }

    pub fn into_operations(self) -> Vec<Operation> {
        self.0
    }
}

impl From<Operation> for Pipeline {
    fn from(operation: Operation) -> Self {
        Self(vec![operation])
    }
}

impl From<&Pipeline> for Pipeline {
    fn from(pipeline: &Pipeline) -> Self {
        pipeline.clone()
    }
}

/// Immutable, reusable Job settings. Relative paths resolve from the process's
/// current directory during each operation, including after loading a saved Job.
pub struct Job(Source);

enum Source {
    Typed(JobSettings),
    Decoded(DecodedJob),
}

impl fmt::Debug for Job {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_tuple("Job").field(self.settings()).finish()
    }
}

impl Job {
    pub fn new(mut settings: JobSettings) -> Self {
        settings.random_seed = None;
        Self(Source::Typed(settings))
    }

    /// Decode the supported Job JSON format and retain its configuration grant.
    /// Use [`Self::validate`] to check the decoded settings before execution.
    pub fn from_json(json: &str) -> Result<Self, Error> {
        DecodedJob::from_json(json)
            .map(|job| Self(Source::Decoded(job)))
            .map_err(Error::decode)
    }

    pub fn load(path: impl AsRef<Path>) -> Result<Self, Error> {
        DecodedJob::read_with_diagnostics(path)
            .map(|job| Self(Source::Decoded(job)))
            .map_err(Error::decode)
    }

    pub fn settings(&self) -> &JobSettings {
        match &self.0 {
            Source::Typed(settings) => settings,
            Source::Decoded(job) => job.job(),
        }
    }

    /// Write a Job JSON file atomically. The target file must be new.
    /// An error can report a committed save with incomplete temporary cleanup.
    pub fn save(&self, path: impl AsRef<Path>) -> Result<(), Error> {
        std::path::absolute(path)
            .map_err(anyhow::Error::from)
            .and_then(|destination| {
                save::write(self.settings(), &destination, save::Mode::CompactNew)
            })
            .map_err(|error| Error::new("config_write", error))
    }

    /// Check only configuration, including formulas and the required output path.
    pub fn validate(&self) -> Result<(), Error> {
        self.settings()
            .validate()
            .and_then(|()| self.settings().validate_output())
            .map_err(|error| Error::new("invalid_config", error))
    }

    /// Scan the current input and return bounded, advisory observations.
    pub fn analyze(&self, control: Option<&ExecutionControl>) -> Result<AnalyzeReport, Error> {
        execute(control, |cancel, notify| {
            ProfileCache::default()
                .profile(self.settings(), cancel, notify)
                .map(AnalyzeReport)
        })
    }

    /// Validate the current source, execute the Job, and publish the result.
    pub fn run(&self, control: Option<&ExecutionControl>) -> Result<RunReport, Error> {
        execute(control, |cancel, notify| {
            let settings = self.settings();
            let manifest_path = Path::new(&settings.output).join("manifest.jsonl");
            let analysis = DecodedJob::copy_for_run(settings)?.run(cancel, notify)?;
            Ok(RunReport {
                rows: analysis.rows,
                columns: analysis.columns,
                groups: analysis.groups,
                output_files: analysis.output_files,
                output_csv_bytes: analysis.output_csv_bytes,
                manifest_path,
            })
        })
    }
}

/// Aggregate publication outcome. Per-file metadata is in `manifest_path`.
#[derive(Clone, Debug, Serialize)]
#[non_exhaustive]
pub struct RunReport {
    pub rows: u64,
    pub columns: usize,
    pub groups: u64,
    pub output_files: u64,
    pub output_csv_bytes: u64,
    pub manifest_path: PathBuf,
}

/// Bounded observations from Analyze. Borrowed access keeps the report's
/// allocations with their admission grants.
#[derive(Serialize)]
#[serde(transparent)]
pub struct AnalyzeReport(InputProfile);

impl fmt::Debug for AnalyzeReport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("AnalyzeReport")
            .field("rows", &self.0.rows)
            .field("columns", &self.0.columns)
            .finish_non_exhaustive()
    }
}

impl AnalyzeReport {
    pub fn rows(&self) -> u64 {
        self.0.rows
    }

    pub fn columns(&self) -> usize {
        self.0.columns
    }

    pub fn header(&self) -> Option<&[String]> {
        self.0.header.as_deref()
    }

    pub fn preview(&self) -> &[Vec<String>] {
        &self.0.preview
    }

    pub fn column_values(&self) -> &[ColumnProfile] {
        &self.0.column_values
    }

    pub fn stages(&self) -> &[StageProfile] {
        &self.0.stages
    }

    pub fn writer_estimate(&self) -> Option<&WriterEstimate> {
        self.0.writer_estimate.as_ref()
    }

    pub fn suggested_run_memory_mb(&self) -> Option<u64> {
        self.0.suggested_run_memory_mb
    }
}

/// A one-use control for an Analyze or Run. Clones observe and cancel the same
/// execution. A cancellation request can be set before execution starts.
#[derive(Clone, Default)]
pub struct ExecutionControl(Arc<ControlState>);

struct ControlState {
    claimed: AtomicBool,
    cancelled: Arc<AtomicBool>,
    progress: Mutex<Progress>,
}

impl Default for ControlState {
    fn default() -> Self {
        Self {
            claimed: AtomicBool::new(false),
            cancelled: Arc::default(),
            progress: Mutex::new(Progress {
                phase: ProgressPhase::literal("Pending"),
                ..Progress::default()
            }),
        }
    }
}

impl ExecutionControl {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        self.0.cancelled.store(true, Ordering::Relaxed);
    }

    /// Return the most recent progress event. Rows are relative to the phase.
    pub fn progress(&self) -> Progress {
        self.0.progress.lock().unwrap().clone()
    }
}

fn execute<T: Send>(
    control: Option<&ExecutionControl>,
    work: impl FnOnce(Arc<AtomicBool>, Notify) -> anyhow::Result<T> + Send,
) -> Result<T, Error> {
    let (cancel, notify): (_, Notify) = if let Some(control) = control {
        if control.0.claimed.swap(true, Ordering::Relaxed) {
            return Err(Error::new(
                "control_in_use",
                anyhow::anyhow!("execution control already used; create a new control"),
            ));
        }
        control.0.progress.lock().unwrap().phase = ProgressPhase::literal("Starting");
        let state = control.0.clone();
        (
            state.cancelled.clone(),
            Arc::new(move |progress| *state.progress.lock().unwrap() = progress),
        )
    } else {
        (Arc::new(AtomicBool::new(false)), Arc::new(|_| ()))
    };
    let result = worker::execute(|| {
        ensure!(!cancel.load(Ordering::Relaxed), Cancelled);
        work(cancel, notify)
    })
    .map_err(Error::execution);
    if let Some(control) = control {
        let mut progress = control.0.progress.lock().unwrap();
        progress.phase = ProgressPhase::literal(match &result {
            Ok(_) => "Complete",
            Err(error) if error.code() == "cancelled" => "Cancelled",
            Err(_) => "Failed",
        });
        progress.temp_bytes = 0;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::{execute, DecodedJob, ExecutionControl, JobSettings, Resources};
    use crate::storage::Context;
    use std::{io::Write, sync::atomic::Ordering};

    #[test]
    fn run_setup_cancellation_reports_cancelled() -> anyhow::Result<()> {
        let root = tempfile::tempdir()?;
        let output = root.path().join("output");
        let settings = JobSettings::for_files("unused.csv", output.to_str().unwrap());
        let control = ExecutionControl::new();
        let result = execute(Some(&control), |cancel, notify| {
            let job = DecodedJob::copy_for_run(&settings)?;
            // Reproduce cancellation after the worker's first check.
            cancel.store(true, Ordering::Relaxed);
            job.run(cancel, notify).map(|_| ())
        });

        assert_eq!(result.unwrap_err().code(), "cancelled");
        assert_eq!(control.progress().phase.as_str(), "Cancelled");
        assert_eq!(root.path().read_dir()?.count(), 0);
        Ok(())
    }

    #[test]
    fn spill_write_cancellation_reports_cancelled() -> anyhow::Result<()> {
        let root = tempfile::tempdir()?;
        let resources = Resources {
            temp_dir: Some(root.path().to_str().unwrap().into()),
            ..Resources::default()
        };
        let control = ExecutionControl::new();
        let result = execute(Some(&control), |cancel, notify| {
            let context = Context::new(&resources, cancel.clone(), notify)?;
            let mut spill = context.file()?;
            cancel.store(true, Ordering::Relaxed);
            spill.write_all(b"record")?;
            Ok(())
        });

        assert_eq!(result.unwrap_err().code(), "cancelled");
        assert_eq!(control.progress().phase.as_str(), "Cancelled");
        assert_eq!(control.progress().temp_bytes, 0);
        assert_eq!(root.path().read_dir()?.count(), 0);
        Ok(())
    }
}
