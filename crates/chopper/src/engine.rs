pub(crate) mod auto;
pub use auto::{AutoObservations, AutoPlan, PreviewObservations};
mod analysis_text;
pub use analysis_text::AnalysisText;
mod timings;
pub use timings::Timings;
mod warnings;
pub use warnings::Warnings;
mod diagnostics;
mod direct;
pub use diagnostics::Diagnostics;
mod assignment;
pub(crate) mod calculation;
pub use calculation::formula_preview_json;
mod child_metadata;
mod column_summaries;
mod exact_writers;
pub use column_summaries::ColumnSummaries;
#[cfg(feature = "experimental-consecutive-partitions")]
mod consecutive_partitions;
#[cfg(feature = "experimental-constant-partition")]
mod constant_partition;
mod domain_cache;
mod group_metadata;
mod header;
pub use header::Header;
mod formula_sample;
mod input_gzip;
mod input_inspection;
pub use formula_sample::{sample_formula_rows, FormulaSample};
mod inspection_result;
mod shared_analysis;
mod stages;
pub use inspection_result::Inspection;
pub use stages::Stages;
mod input_sniff;
mod input_zip;
mod job_owner;
pub(crate) use job_owner::capacity as job_capacity;
pub use job_owner::PreparedJob;
use job_owner::RunJob;
mod keys;
#[cfg(any(target_os = "wasi", feature = "experimental-nested-balanced"))]
mod nested_balanced;
#[cfg(feature = "experimental-partition-balanced")]
mod partition_balanced;
mod preview;
#[cfg(any(target_os = "linux", target_os = "wasi"))]
mod probabilistic_shuffle;
pub use preview::Preview;
mod exact_plan;
#[cfg(any(test, feature = "resource-contract-tests"))]
mod resource_contracts;
#[cfg(any(
    test,
    feature = "experimental-consecutive-partitions",
    feature = "experimental-streaming-chain",
    feature = "experimental-partition-balanced"
))]
mod retained_execution;
mod run_route;
mod shuffle_assignment;
mod shuffle_elision;
mod shuffle_partition;
mod streaming;
#[cfg(feature = "experimental-streaming-chain")]
mod streaming_chain;
use crate::{
    csv_intake::{self as records, Intake},
    output,
    storage::*,
};
use anyhow::{ensure, Context as _, Result};
use assignment::AssignmentScratch;
use chopper_core::{
    csv::{DecodeReader, Parser},
    random::{self, Random},
    *,
};
use domain_cache::DomainCache;
use keys::OperationKey;
use run_route::{ProcessingMode, RunRoute};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    fs::File,
    io::{BufRead, BufReader, Read, Seek, SeekFrom},
    sync::{atomic::AtomicBool, Arc},
};
use streaming::StreamingGroups;

/// Deterministic resource contracts for the separate test-only WASI reactor.
/// This entry point never changes admission in the production engine.
#[cfg(feature = "resource-contract-tests")]
pub fn run_resource_contracts() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    {
        let mut report = resource_contracts::input_adapters()?;
        report["hosted_uniform_retention"] = crate::storage::hosted_uniform_retention_contract()?;
        Ok(report)
    }
    #[cfg(not(target_os = "wasi"))]
    resource_contracts::input_adapters()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageStats {
    pub operation: usize,
    pub input_groups: u64,
    pub output_groups: u64,
    pub smallest_group: u64,
    pub largest_group: u64,
    pub empty_groups: u64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColumnValues {
    pub column: usize,
    pub values: std::collections::BTreeSet<String>,
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub frequencies: std::collections::BTreeMap<String, u64>,
    pub truncated: bool,
}
// Alias prevents serde derive from imposing a borrowed-input lifetime on this
// field: the decoder returns only known static literals.
type AlgorithmVersion = &'static str;
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Analysis {
    #[serde(deserialize_with = "deserialize_algorithm_version")]
    pub algorithm_version: AlgorithmVersion,
    #[serde(default)]
    pub column_values: ColumnSummaries,
    pub seed: AnalysisText,
    pub rows: u64,
    pub columns: usize,
    pub header: Option<Header>,
    pub preview: Preview,
    pub logical_digest: AnalysisText,
    pub groups: u64,
    pub output_files: u64,
    pub output_csv_bytes: u64,
    pub largest_record_bytes: u64,
    pub temp_bytes: u64,
    pub peak_temp_bytes: u64,
    pub memory_budget_bytes: u64,
    pub workers: usize,
    pub analysis_seconds: f64,
    #[serde(default)]
    pub timings: Timings,
    #[serde(default)]
    pub diagnostics: Diagnostics,
    pub stages: Stages,
    pub warnings: Warnings,
    pub accuracy: AnalysisText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution: Option<ExecutionSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auto_plan: Option<AutoPlan>,
}
impl Analysis {
    pub(crate) fn algorithm_version_for(_job: &Job) -> &'static str {
        ALGORITHM_VERSION
    }

    /// Admission retained by the seed, logical digest and accuracy text owners.
    pub fn text_reserved_bytes(&self) -> u64 {
        self.seed.reserved_bytes()
            + self.logical_digest.reserved_bytes()
            + self.accuracy.reserved_bytes()
    }
}
// Decode into the same static literals without retaining or leaking input text.
fn deserialize_algorithm_version<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<&'static str, D::Error> {
    struct Version;
    impl serde::de::Visitor<'_> for Version {
        type Value = &'static str;
        fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str("a supported Chopper algorithm version")
        }
        fn visit_str<E: serde::de::Error>(
            self,
            value: &str,
        ) -> std::result::Result<Self::Value, E> {
            match value {
                ALGORITHM_VERSION => Ok(ALGORITHM_VERSION),
                "chopper-v1-blake3-1" => Ok("chopper-v1-blake3-1"),
                "chopper-flexible-full-shuffle-v1" => Ok("chopper-flexible-full-shuffle-v1"),
                _ => Err(E::custom("unsupported Chopper algorithm version")),
            }
        }
    }
    deserializer.deserialize_str(Version)
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionSummary {
    pub plan_version: u32,
    pub rng_version: ExecutionRng,
    pub replay_guarantee: ReplayGuarantee,
    pub records: u64,
    pub plan_digest_blake3: [u8; 32],
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ExecutionRng {
    #[serde(rename = "chopper-v1-blake3-1")]
    Blake3CounterV1,
}
impl From<FullShuffleRng> for ExecutionRng {
    fn from(value: FullShuffleRng) -> Self {
        match value {
            FullShuffleRng::Blake3CounterV1 => Self::Blake3CounterV1,
        }
    }
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ReplayGuarantee {
    PreparedSnapshotOnly,
}
pub struct Prepared {
    pub job: PreparedJob,
    pub analysis: Analysis,
    pub output_plan: output::OutputPlan,
    pub ctx: Context,
}
pub fn generated_seed() -> Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).map_err(|e| anyhow::anyhow!("OS random source: {e}"))?;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut seed = String::with_capacity(64);
    for byte in bytes {
        seed.push(HEX[(byte >> 4) as usize] as char);
        seed.push(HEX[(byte & 15) as usize] as char);
    }
    Ok(seed)
}
pub fn prepare(job: Job, cancel: Arc<AtomicBool>, notify: Notify) -> Result<Prepared> {
    prepare_with_memory_pool(job, cancel, notify, crate::resources::process_memory()?)
}
/// Run a job immediately. Eligible limits-only jobs stream into private publication;
/// other pipelines execute their exact prepared snapshot.
pub fn run(job: Job, cancel: Arc<AtomicBool>, notify: Notify) -> Result<Analysis> {
    run_with_memory_pool(job, cancel, notify, crate::resources::process_memory()?)
}
/// Run against the caller's aggregate capacity ledger. Eligibility is decided
/// before CSV consumption (counted Run may peek at the container signature);
/// a consumed direct input is never retried.
pub fn run_with_memory_pool(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Analysis> {
    run_with_auto(job, cancel, notify, pool, None)
}

pub fn run_advised(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    hint: Option<AutoObservations>,
) -> Result<Analysis> {
    run_with_auto(
        job,
        cancel,
        notify,
        crate::resources::process_memory()?,
        hint,
    )
}

/// Run with optional observations from a completed Analyze. The source is read
/// and validated normally regardless of whether the advice is applicable.
pub fn run_with_auto(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    hint: Option<AutoObservations>,
) -> Result<Analysis> {
    run_using(job.into(), cancel, notify, pool, (hint, None), None, None)
}

#[cfg(not(target_os = "wasi"))]
pub(crate) fn run_decoded_native(
    job: crate::cli_job::DecodedJob,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    hint: Option<AutoObservations>,
) -> Result<Analysis> {
    let pool = job.pool().clone();
    run_using(
        RunJob::Decoded(job),
        cancel,
        notify,
        pool,
        (hint, None),
        None,
        None,
    )
}

fn run_using(
    job: RunJob,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    (hint, preview): (Option<AutoObservations>, Option<PreviewObservations>),
    snapshot: Option<crate::observation::Sink<'_>>,
    physical: Option<crate::observation::physical::Sink>,
) -> Result<Analysis> {
    let observed = snapshot.is_some() || physical.is_some();
    let started = std::time::Instant::now();
    job.validate_for_execution()?;
    let route = RunRoute::select(&job, &cancel, &notify, &pool, observed)?;
    let mut plan = route.report(&job, &pool, hint, preview);
    let (published, strategy) = match route {
        RunRoute::Direct { mode, context } => (
            direct::run(job, context, (snapshot, physical), mode, started)?,
            mode.strategy(),
        ),
        RunRoute::Retained(route) => {
            let observe_input = physical.is_some();
            let processed = process_using(
                job,
                cancel,
                notify,
                pool,
                physical,
                ProcessingMode::Run(route, &plan),
                |job, ctx, p, b, s| {
                    if observe_input {
                        with_input_observed(job, Reservation::new(ctx), ctx, |source, input_ctx| {
                            ingest_options(source, job, input_ctx, p, b, s)
                        })
                    } else {
                        with_input(job, Reservation::new(ctx), |mut source| {
                            ingest_options(source.as_mut(), job, ctx, p, b, s)
                        })
                    }
                },
            )?;
            if matches!(&processed, Processed::Direct { .. }) {
                plan.record_private_terminal();
            }
            (processed.publish()?, None)
        }
    };
    let measurements = published.measurements;
    let mut analysis = published.into_analysis();
    plan.finish(&mut analysis, measurements, strategy);
    Ok(analysis)
}

/// Optional structured observations for the limits-only direct path.
pub fn run_observed(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    sink: crate::observation::Sink<'_>,
) -> Result<Analysis> {
    run_using(
        job.into(),
        cancel,
        notify,
        crate::resources::process_memory()?,
        (None, None),
        Some(sink),
        None,
    )
}

/// Keep physical facts and optional Analyze advice together in hosted Run.
pub fn run_observed_with_physical(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    snapshot: crate::observation::Sink<'_>,
    physical: crate::observation::physical::Sink,
) -> Result<Analysis> {
    run_hosted(job, cancel, notify, None, Some((snapshot, physical)))
}

pub fn run_hosted(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    hint: Option<AutoObservations>,
    observers: Option<(
        crate::observation::Sink<'_>,
        crate::observation::physical::Sink,
    )>,
) -> Result<Analysis> {
    run_hosted_with_preview(job, cancel, notify, hint, None, observers)
}

pub fn run_hosted_with_preview(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    hint: Option<AutoObservations>,
    preview: Option<PreviewObservations>,
    observers: Option<(
        crate::observation::Sink<'_>,
        crate::observation::physical::Sink,
    )>,
) -> Result<Analysis> {
    run_hosted_job(
        job.into(),
        cancel,
        notify,
        crate::resources::process_memory()?,
        (hint, preview),
        observers,
    )
}

#[cfg(target_os = "wasi")]
pub fn run_decoded_hosted_with_preview(
    job: crate::cli_job::DecodedJob,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    hint: Option<AutoObservations>,
    preview: Option<PreviewObservations>,
    observers: Option<(
        crate::observation::Sink<'_>,
        crate::observation::physical::Sink,
    )>,
) -> Result<Analysis> {
    let pool = job.pool().clone();
    run_hosted_job(
        RunJob::Decoded(job),
        cancel,
        notify,
        pool,
        (hint, preview),
        observers,
    )
}

fn run_hosted_job(
    job: RunJob,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    advice: (Option<AutoObservations>, Option<PreviewObservations>),
    observers: Option<(
        crate::observation::Sink<'_>,
        crate::observation::physical::Sink,
    )>,
) -> Result<Analysis> {
    let (snapshot, physical) = observers.map_or((None, None), |(s, p)| (Some(s), Some(p)));
    run_using(job, cancel, notify, pool, advice, snapshot, physical)
}
/// Prepare against a caller-owned aggregate capacity ledger. Retained profiles,
/// returned copies and prepared jobs can share this pool without sharing a job limit.
pub fn prepare_with_memory_pool(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Prepared> {
    prepare_using(
        job,
        cancel,
        notify,
        pool,
        None,
        |job, ctx, partitions, balanced, streaming| {
            with_input(job, Reservation::new(ctx), |mut source| {
                ingest_options(source.as_mut(), job, ctx, partitions, balanced, streaming)
            })
        },
    )
}
/// Observe internal preparation through actual storage/output boundaries.
pub fn run_with_observations(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    sink: crate::observation::physical::Sink,
) -> Result<Analysis> {
    let pool = crate::resources::process_memory()?;
    let physical = (!job.operations.is_empty()).then_some(sink);
    run_using(
        job.into(),
        cancel,
        notify,
        pool,
        (None, None),
        None,
        physical,
    )
}
fn prepare_using(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    physical: Option<crate::observation::physical::Sink>,
    read_input: impl FnMut(&Job, &Context, bool, bool, bool) -> Result<Ingested>,
) -> Result<Prepared> {
    job.validate_for_execution()?;
    match process_using(
        job.into(),
        cancel,
        notify,
        pool,
        physical,
        ProcessingMode::Prepare,
        read_input,
    )? {
        Processed::Snapshot(prepared) => Ok(prepared),
        Processed::Direct { .. } => anyhow::bail!("explicit preparation requires a snapshot"),
    }
}

pub(crate) fn configured_writer_capacity(job: &Job) -> Option<usize> {
    direct::writer_capacity(job)
}
pub(crate) fn bounded_final_partition_shape(job: &Job) -> bool {
    direct::partition_eligible(job)
}

// Keep synchronous owners inline: boxing would need a separate allocation grant.
#[allow(clippy::large_enum_variant)]
enum Processed {
    Snapshot(Prepared),
    Direct {
        job: PreparedJob,
        analysis: Analysis,
        publication: output::DirectPublication,
        ctx: Context,
    },
}
impl Processed {
    fn publish(self) -> Result<output::PublishedAnalysis> {
        match self {
            Self::Snapshot(prepared) => prepared.execute_published(),
            Self::Direct {
                job,
                analysis,
                publication,
                ctx,
            } => Ok(publication
                .publish(&job, &analysis, &ctx)?
                .with_analysis(analysis, &ctx)),
        }
    }
}

fn process_using(
    job: RunJob,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    physical: Option<crate::observation::physical::Sink>,
    mode: ProcessingMode<'_>,
    mut read_input: impl FnMut(&Job, &Context, bool, bool, bool) -> Result<Ingested>,
) -> Result<Processed> {
    let started = std::time::Instant::now();
    let _unobserved_run = mode.unobserved_run();
    let ctx = mode.context(&job, cancel, notify, pool, physical)?;
    let _calculated_partition_run = if cfg!(target_os = "wasi") {
        ctx.auto_run
    } else {
        _unobserved_run
    };
    let direct_terminal = ctx.direct_terminal_output;

    let job = PreparedJob::admit(job, Reservation::new(&ctx))?;
    ctx.event("Reading and validating CSV", 0)?;
    let source_metadata = std::fs::metadata(&job.input).context("open input")?;
    ensure!(source_metadata.is_file(), "input must be a regular file");
    let ingest_started = std::time::Instant::now();
    #[cfg(feature = "experimental-consecutive-partitions")]
    let mut partition_fusion = true;
    let ingested = match read_input(
        &job,
        &ctx,
        cfg!(feature = "experimental-consecutive-partitions"),
        cfg!(feature = "experimental-partition-balanced"),
        cfg!(feature = "experimental-streaming-chain"),
    ) {
        #[cfg(feature = "experimental-streaming-chain")]
        Err(error)
            if streaming_chain::retry(&error) && streaming_chain::Plan::at(&job, 0).is_some() =>
        {
            ctx.streaming_chain_retry();
            ctx.event("Retrying routing chain without fusion", 0)?;
            read_input(
                &job,
                &ctx,
                cfg!(feature = "experimental-consecutive-partitions"),
                cfg!(feature = "experimental-partition-balanced"),
                false,
            )?
        }
        #[cfg(feature = "experimental-partition-balanced")]
        Err(error)
            if partition_balanced::admission(&error)
                && partition_balanced::Plan::at(&job, 0).is_some() =>
        {
            ctx.partition_balanced_retry();
            ctx.event("Retrying partition/shuffle without balanced fusion", 0)?;
            read_input(
                &job,
                &ctx,
                cfg!(feature = "experimental-consecutive-partitions"),
                false,
                cfg!(feature = "experimental-streaming-chain"),
            )?
        }
        #[cfg(feature = "experimental-consecutive-partitions")]
        Err(error)
            if consecutive_partitions::admission(&error)
                && consecutive_partitions::Plan::at(&job, 0).is_some() =>
        {
            partition_fusion = false;
            ctx.consecutive_partitions_retry();
            ctx.event("Retrying value partitions without fusion", 0)?;
            read_input(
                &job,
                &ctx,
                false,
                cfg!(feature = "experimental-partition-balanced"),
                cfg!(feature = "experimental-streaming-chain"),
            )?
        }
        result => result?,
    };

    let Ingested {
        mut dataset,
        mut analysis,
        mut final_plan,
        mut terminal_publication,
        consumed,
    } = ingested;
    let input_header = analysis.header.clone();
    let input_columns = analysis.columns;
    let mut phase_timings = timings::Builder::new(Reservation::new(&ctx));
    phase_timings.insert(
        "ingest_and_fused_operations",
        ingest_started.elapsed().as_secs_f64(),
    )?;
    let pipeline_started = std::time::Instant::now();
    let after = std::fs::metadata(&job.input)?;
    ensure!(
        source_metadata.len() == after.len() && source_metadata.modified()? == after.modified()?,
        "input changed while reading; retry with a stable source"
    );
    // The retained spool is the immutable analyzed snapshot used by execution.
    ctx.physical_stage_complete(0);
    let mut stage_completion = ctx.physical_stages();
    let mut index = consumed;
    let mut calculation_times = None;
    let mut calculations = if job.calculated_columns.is_empty() {
        None
    } else {
        let started = std::time::Instant::now();
        let plan = calculation::Plan::prepare(
            &job,
            input_header.as_deref(),
            input_columns,
            Reservation::new(&ctx),
        )?;
        calculation_times = Some((started.elapsed().as_secs_f64(), 0.0));
        Some(plan)
    };
    while index < job.operations.len() || calculations.is_some() {
        stage_completion.complete_through(index);
        if calculations
            .as_ref()
            .is_some_and(|plan| plan.boundary == index)
        {
            let plan = calculations.take().unwrap();
            ctx.event("Evaluating calculated columns", 0)?;
            let mut step_ctx = ctx.physical_scope([index + 1, 0]);
            step_ctx.physical_source = dataset.physical_source;
            let started = std::time::Instant::now();
            #[cfg(any(target_os = "linux", target_os = "wasi"))]
            if _calculated_partition_run
                && !cfg!(feature = "experimental-constant-partition")
                && index == 0
                && dataset.groups == 1
                && source_metadata.len() >= 128 * 1024 * 1024
                && job.compression == chopper_core::Compression::None
            {
                if let [Operation::Partition { columns }] = job.operations.as_slice() {
                    match try_calculated_partition(&plan, &dataset, columns, &job, &step_ctx) {
                        Ok((output, stats, traversal_seconds)) => {
                            calculation_times.as_mut().unwrap().1 = traversal_seconds;
                            analysis.columns = plan.header.len();
                            analysis.header = Some(plan.header);
                            analysis.groups = stats.output_groups;
                            analysis.stages.push(stats)?;
                            final_plan = Some(output);
                            index += 1;
                            break;
                        }
                        // Everything created by the speculative pass is private.
                        // Replay the retained source to preserve staged error order.
                        Err(_) => ctx.check()?,
                    }
                }
            }
            if index == job.operations.len() {
                if direct_terminal {
                    let mut writer =
                        output::PlanWriter::direct_grouped(&job, Some(&plan.header), &step_ctx)?;
                    plan.apply(&dataset, &job, &step_ctx, &mut writer)?;
                    terminal_publication = Some(writer.finish_direct()?);
                } else {
                    let mut writer = output::PlanWriter::new(&job, Some(&plan.header), &step_ctx)?;
                    plan.apply(&dataset, &job, &step_ctx, &mut writer)?;
                    final_plan = Some(writer.finish()?);
                }
                analysis.groups = dataset.groups;
            } else {
                let mut writer = DatasetWriter::new(&step_ctx)?;
                plan.apply(&dataset, &job, &step_ctx, &mut writer)?;
                dataset = writer.finish()?;
            }
            calculation_times.as_mut().unwrap().1 = started.elapsed().as_secs_f64();
            analysis.columns = plan.header.len();
            analysis.header = Some(plan.header);
            if index == job.operations.len() {
                break;
            }
        }
        #[cfg(feature = "experimental-consecutive-partitions")]
        if partition_fusion && calculations.is_none() {
            if let Some(plan) = consecutive_partitions::Plan::at(&job, index) {
                ctx.event("Preparing consecutive value partitions", 0)?;
                let attempt = retained_execution::execute(
                    &job,
                    &analysis,
                    &ctx,
                    index,
                    plan.len(),
                    |writer| {
                        plan.apply(
                            &dataset,
                            analysis.header.as_deref(),
                            analysis.columns,
                            &ctx,
                            writer,
                        )
                        .map(Some)
                    },
                );
                match attempt {
                    Ok(Some(completed)) => {
                        completed.commit(
                            &mut dataset,
                            &mut final_plan,
                            &mut analysis,
                            &mut index,
                            |stats, analysis| {
                                analysis.groups = stats.last().output_groups;
                                stats.append(&mut analysis.stages)
                            },
                        )?;
                        continue;
                    }
                    Ok(None) => unreachable!("consecutive partitions never decline"),
                    Err(error) if consecutive_partitions::admission(error.error()) => {
                        partition_fusion = false;
                        ctx.consecutive_partitions_retry();
                        ctx.event("Retrying value partitions without fusion", 0)?;
                        continue;
                    }
                    Err(error) => return Err(error.into_error()),
                }
            }
        }
        #[cfg(feature = "experimental-streaming-chain")]
        if let Some(plan) = calculations
            .is_none()
            .then(|| streaming_chain::Plan::at(&job, index))
            .flatten()
        {
            ctx.event("Preparing streaming routing chain", 0)?;
            let attempt = retained_execution::execute(&job, &analysis, &ctx, index, 3, |writer| {
                plan.apply(&dataset, &job, &analysis, &ctx, writer)
                    .map(Some)
            });
            match attempt {
                Ok(Some(completed)) => {
                    completed.commit(
                        &mut dataset,
                        &mut final_plan,
                        &mut analysis,
                        &mut index,
                        |stats, analysis| {
                            analysis.groups = stats[2].output_groups;
                            analysis.stages.extend(stats)
                        },
                    )?;
                    continue;
                }
                Ok(None) => unreachable!("streaming chains never decline"),
                Err(error) if error.is_setup() && streaming_chain::retry(error.error()) => {
                    // No parent attempt or emission has begun: writer setup alone failed.
                    ctx.streaming_chain_retry();
                    ctx.event("Retrying routing chain without fusion", 0)?;
                }
                Err(error) => return Err(error.into_error()),
            }
        }
        #[cfg(feature = "experimental-partition-balanced")]
        if let Some(plan) = calculations
            .is_none()
            .then(|| partition_balanced::Plan::at(&job, index))
            .flatten()
        {
            ctx.event("Preparing partition/shuffle balanced ranges", 0)?;
            let attempt =
                retained_execution::execute(&job, &analysis, &ctx, index, plan.len(), |writer| {
                    plan.apply(&dataset, &job, &analysis, &ctx, writer)
                });
            let attempt = match attempt {
                Err(error) if partition_balanced::admission(error.error()) => {
                    ctx.partition_balanced_retry();
                    ctx.event("Retrying partition/shuffle without balanced fusion", 0)?;
                    None
                }
                result => result.map_err(retained_execution::Failure::into_error)?,
            };
            if let Some(completed) = attempt {
                completed.commit(
                    &mut dataset,
                    &mut final_plan,
                    &mut analysis,
                    &mut index,
                    |stats, analysis| {
                        analysis.groups = stats.balanced.output_groups;
                        stats.append(plan, &mut analysis.stages)
                    },
                )?;
                continue;
            }
        }
        #[cfg(all(target_os = "wasi", not(feature = "experimental-nested-balanced")))]
        if index == 0
            && dataset.groups == 1
            && nested_balanced::hosted_eligible(&job, &ctx, dataset.data.len(), analysis.rows)
        {
            ctx.event("Preparing nested balanced ranges", 0)?;
            let mut writer = output::PlanWriter::new(&job, analysis.header.as_deref(), &ctx)?;
            nested_balanced::emit_hosted(
                &dataset,
                &job.operations,
                &ctx,
                &mut writer,
                &mut analysis.stages,
            )
            .context("preparing operation 2")?;
            analysis.groups = writer.groups;
            final_plan = Some(writer.finish()?);
            index = job.operations.len();
            continue;
        }
        #[cfg(feature = "experimental-nested-balanced")]
        {
            let count = job.operations[index..]
                .iter()
                .take_while(|op| matches!(op, Operation::Balanced { .. }))
                .count();
            if count > 1 {
                ctx.event("Preparing nested balanced ranges", 0)?;
                if calculations.is_none() && index + count == job.operations.len() {
                    let mut writer =
                        output::PlanWriter::new(&job, analysis.header.as_deref(), &ctx)?;
                    nested_balanced::emit(
                        &dataset,
                        &job.operations[index..index + count],
                        index,
                        &ctx,
                        &mut writer,
                        &mut analysis.stages,
                        None,
                    )?;
                    analysis.groups = writer.groups;
                    final_plan = Some(writer.finish()?);
                } else {
                    let result = nested_balanced::shared(
                        &dataset,
                        &job.operations[index..index + count],
                        index,
                        &ctx,
                        &mut analysis.stages,
                    )?;
                    dataset = result;
                }
                index += count;
                continue;
            }
        }
        let operation = &job.operations[index];
        ctx.operation_event(index + 1, job.operations.len())?;
        let before = dataset.groups;
        let next = job.operations.get(index + 1);
        // A later full shuffle overwrites order within the same groups. Keep
        // original step numbers for its random domain and for reported statistics.
        if next.is_some_and(|next| shuffle_elision::can_elide(operation, next)) {
            if let Some(span) = ctx
                .physical_scope([index + 1, 0])
                .physical_span(crate::observation::physical::Kind::Elided)
            {
                span.finish(0);
            }
            analysis
                .stages
                .push(dataset_stats(&dataset, index + 1, before, &ctx)?)?;
            index += 1;
            continue;
        }
        #[cfg(any(target_os = "linux", target_os = "wasi"))]
        let probabilistic_after =
            probabilistic_shuffle::Plan::selected(&job, index, &analysis, &ctx).is_some();
        #[cfg(not(any(target_os = "linux", target_os = "wasi")))]
        let probabilistic_after = false;
        let following_shuffles = if probabilistic_after
            || matches!(
                operation,
                Operation::Partition { .. } | Operation::Assign { .. }
            ) {
            job.operations
                .iter()
                .skip(index + 1)
                .take_while(|op| uniform(op))
                .count()
        } else {
            0
        };
        for skipped in index + 1..index + following_shuffles {
            if let Some(span) = ctx
                .physical_scope([skipped + 1, 0])
                .physical_span(crate::observation::physical::Kind::Elided)
            {
                span.finish(0);
            }
        }
        let shuffle_after = (following_shuffles > 0).then_some(index + following_shuffles);
        let balanced_after = if matches!(operation, Operation::Shuffle { .. }) {
            if let Some(Operation::Balanced { files }) = next {
                Some((index + 1, *files))
            } else {
                None
            }
        } else {
            None
        };
        let partition_after = calculations.is_none()
            && shuffle_partition::ENABLED
            && shuffle_partition::Plan::at(&job, index).is_some();
        let assignment_after = calculations.is_none()
            && shuffle_assignment::ENABLED
            && shuffle_assignment::Plan::at(&job, index).is_some();
        let consumed = 1
            + following_shuffles
            + usize::from(balanced_after.is_some())
            + usize::from(partition_after)
            + usize::from(assignment_after);
        let mut scoped_ctx = ctx.physical_scope([
            index + 1,
            if partition_after || assignment_after {
                index + 2
            } else {
                shuffle_after.map_or(0, |i| i + 1)
            },
        ]);
        scoped_ctx.physical_source = dataset.physical_source;
        let ctx = scoped_ctx;
        let shuffle_stats = if balanced_after.is_some() || partition_after || assignment_after {
            Some(dataset_stats(&dataset, index + 1, before, &ctx)?)
        } else {
            None
        };
        let mut stats;
        if calculations.is_none() && index + consumed == job.operations.len() {
            let mut writer = if direct_terminal {
                output::PlanWriter::direct_grouped(&job, analysis.header.as_ref(), &ctx)?
            } else {
                output::PlanWriter::new(&job, analysis.header.as_deref(), &ctx)?
            };
            let prepared = if direct_terminal {
                exact_writers::prepare(&dataset, &job, &analysis, &ctx)?
            } else {
                None
            };
            if let Some(prepared) = prepared {
                // Keep the destination witness captured before tentative preparation.
                let (seed, files, bytes) = writer.finish_direct()?;
                ensure!(files == 0 && bytes == 0, "nonempty exact allocation setup");
                let (publication, files, bytes, completed_stats) = prepared.emit(&dataset, seed)?;
                ctx.used_retained_exact_writers();
                analysis.groups = completed_stats.output_groups;
                stats = completed_stats;
                terminal_publication = Some((publication, files, bytes));
            } else {
                apply_into(
                    &dataset,
                    operation,
                    index,
                    &job,
                    &analysis,
                    &ctx,
                    &mut writer,
                    shuffle_after,
                    balanced_after,
                )
                .with_context(|| format!("preparing operation {}", index + 1))?;
                stats = StageStats {
                    operation: index + 1,
                    input_groups: before,
                    output_groups: writer.groups,
                    smallest_group: if writer.groups == 0 {
                        0
                    } else {
                        writer.smallest
                    },
                    largest_group: writer.largest,
                    empty_groups: writer.empty,
                };
                analysis.groups = writer.groups;
                if direct_terminal {
                    terminal_publication = Some(writer.finish_direct()?);
                } else {
                    final_plan = Some(writer.finish()?);
                }
            }
        } else {
            dataset = if consumed == 1 {
                apply(&dataset, operation, index, &job, &analysis, &ctx)?
            } else {
                let mut writer = DatasetWriter::new(&ctx)?;
                apply_into(
                    &dataset,
                    operation,
                    index,
                    &job,
                    &analysis,
                    &ctx,
                    &mut writer,
                    shuffle_after,
                    balanced_after,
                )?;
                writer.finish()?
            };
            stats = dataset_stats(&dataset, index + 1, before, &ctx)?;
        }
        if let Some(shuffle_stats) = shuffle_stats {
            analysis.stages.push(shuffle_stats)?;
            stats.operation += 1;
        }
        analysis.stages.push(stats.clone())?;
        for _ in 0..following_shuffles {
            stats.operation += 1;
            stats.input_groups = stats.output_groups;
            analysis.stages.push(stats.clone())?;
        }
        index += consumed;
    }
    stage_completion.complete_through(index);
    phase_timings.insert(
        "remaining_operations",
        pipeline_started.elapsed().as_secs_f64(),
    )?;
    if let Some((prepare, traverse)) = calculation_times {
        phase_timings.insert("calculation_prepare", prepare)?;
        phase_timings.insert("calculation_traverse", traverse)?;
    }
    let output_started = std::time::Instant::now();
    let output_plan = if terminal_publication.is_some() {
        None
    } else if let Some(plan) = final_plan {
        Some(plan)
    } else {
        analysis.groups = dataset.groups;
        Some(output::plan(
            &dataset,
            &job,
            analysis.header.as_deref(),
            &ctx,
        )?)
    };
    phase_timings.insert(
        "final_serialization",
        output_started.elapsed().as_secs_f64(),
    )?;
    analysis.header = input_header;
    analysis.columns = input_columns;
    drop(dataset);
    let (files, bytes) = match (&terminal_publication, &output_plan) {
        (Some((_, files, bytes)), None) => (*files, *bytes),
        (None, Some(plan)) => (plan.files, plan.bytes),
        _ => anyhow::bail!("ambiguous terminal output target"),
    };
    analysis.output_files = files;
    analysis.output_csv_bytes = bytes;
    analysis.temp_bytes = ctx.used();
    analysis.peak_temp_bytes = ctx.peak();
    analysis.memory_budget_bytes = ctx.memory as u64;
    analysis.workers = ctx.workers();
    analysis.timings = phase_timings.finish()?;
    analysis.analysis_seconds = started.elapsed().as_secs_f64();
    analysis.warnings = warnings::build(&job, &analysis, Reservation::new(&ctx))?;
    analysis.diagnostics = Diagnostics::analysis(&ctx, &job, &analysis)?;
    ctx.physical_stage_complete(job.operations.len() + 1);
    if let Some((publication, _, _)) = terminal_publication {
        ctx.event("Finalizing direct terminal output", analysis.rows)?;
        Ok(Processed::Direct {
            job,
            analysis,
            publication,
            ctx,
        })
    } else {
        ctx.event("Finalizing output snapshot", analysis.rows)?;
        Ok(Processed::Snapshot(Prepared {
            job,
            analysis,
            output_plan: output_plan.context("missing prepared snapshot")?,
            ctx,
        }))
    }
}
fn uniform(operation: &Operation) -> bool {
    matches!(
        operation,
        Operation::Shuffle {
            strategy: Shuffle::Uniform | Shuffle::Auto,
            ..
        }
    )
}
fn dataset_stats(
    data: &Dataset,
    operation: usize,
    input_groups: u64,
    ctx: &Context,
) -> Result<StageStats> {
    let mut stats = StageStats {
        operation,
        input_groups,
        output_groups: data.groups,
        smallest_group: if data.groups == 0 { 0 } else { u64::MAX },
        largest_group: 0,
        empty_groups: 0,
    };
    for group in data.groups()? {
        ctx.check()?;
        let rows = group?.rows;
        stats.smallest_group = stats.smallest_group.min(rows);
        stats.largest_group = stats.largest_group.max(rows);
        stats.empty_groups += u64::from(rows == 0);
    }
    Ok(stats)
}
/// Read just the first CSV record, without preparing a job or writing temporary data.
pub fn input_columns(job: &Job) -> Result<Inspection> {
    inspect_input(job, false)
}
/// Inspect at most eight input data records; this does not validate the full file.
pub fn input_preview(job: &Job) -> Result<Inspection> {
    inspect_input(job, true)
}
fn validate_input_inspection(job: &Job) -> Result<()> {
    Job {
        input: job.input.clone(),
        input_csv: job.input_csv.clone(),
        input_dialect: job.input_dialect.clone(),
        output_csv: job.input_csv.clone(),
        resources: job.resources.clone(),
        ..Job::default()
    }
    .validate()
}
fn inspect_input(job: &Job, preview: bool) -> Result<Inspection> {
    validate_input_inspection(job)?;
    let mut signature = [0u8; 4];
    let read = File::open(&job.input)?.read(&mut signature)?;
    let input_is_zip =
        read == 4 && matches!(&signature, b"PK\x03\x04" | b"PK\x05\x06" | b"PK\x07\x08");
    let inspection = input_inspection_reservation(job)?;
    with_input(job, inspection.sibling(), |source| {
        if preview {
            input_inspection::preview(source, job, inspection, input_is_zip)
        } else {
            input_inspection::columns(source, job, inspection, input_is_zip)
        }
    })
}
/// Suggest a dialect from at most 64 KiB of decompressed input. Header/escape settings remain explicit.
pub fn sniff_csv(job: &Job) -> Result<Inspection> {
    validate_input_inspection(job)?;
    let inspection = input_inspection_reservation(job)?;
    with_input(job, inspection.sibling(), |source| {
        input_sniff::sniff(source, job, inspection)
    })
}
// The grant belongs to the actual buffered reader, including when a consumer
// retains it after EOF. Codec heaps remain separate; ZIP metadata has its own
// parser-controlled owner in input_zip.
struct InputBuffer<R> {
    reader: BufReader<R>,
    _buffer: Reservation,
}
impl<R: Read> InputBuffer<R> {
    fn new(source: R, capacity: usize, mut buffer: Reservation) -> Result<Self> {
        buffer.resize(capacity)?;
        Ok(Self {
            reader: BufReader::with_capacity(capacity, source),
            _buffer: buffer,
        })
    }
}
impl<R: Read> Read for InputBuffer<R> {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        self.reader.read(bytes)
    }
}
impl<R: Read> BufRead for InputBuffer<R> {
    fn fill_buf(&mut self) -> std::io::Result<&[u8]> {
        self.reader.fill_buf()
    }
    fn consume(&mut self, amount: usize) {
        self.reader.consume(amount);
    }
}
impl<R: Read + Seek> Seek for InputBuffer<R> {
    fn seek(&mut self, position: SeekFrom) -> std::io::Result<u64> {
        self.reader.seek(position)
    }
}
fn input_inspection_reservation(job: &Job) -> Result<Reservation> {
    let pool = crate::resources::process_memory()?;
    let memory_mb = pool.resolve_memory(&job.resources)?;
    Ok(Reservation::for_workspace(Arc::new(Workspace::shared(
        (memory_mb * 1024 * 1024 / 2) as usize,
        pool,
    ))))
}
pub(crate) fn with_input<T>(
    job: &Job,
    buffer: Reservation,
    consume: impl FnOnce(Box<dyn Read + '_>) -> Result<T>,
) -> Result<T> {
    with_input_report(job, buffer, None, |source, _| consume(source))
}
fn with_input_observed<T>(
    job: &Job,
    buffer: Reservation,
    ctx: &Context,
    consume: impl FnOnce(&mut dyn Read, &Context) -> Result<T>,
) -> Result<T> {
    with_input_report(job, buffer, Some(ctx), |mut source, observation| {
        if observation.is_none() {
            return consume(source.as_mut(), ctx);
        }
        let mut input_ctx = ctx.clone();
        if let Some(observation) = observation {
            input_ctx.physical_source = Some(observation.id);
        }
        let mut reader = ObservedInput {
            source: source.as_mut(),
            observation: observation.as_mut(),
        };
        consume(&mut reader, &input_ctx)
    })
}
struct InputObservation {
    attempt: Option<crate::observation::physical::Attempt>,
    id: u32,
    bytes: u64,
    read_failed: bool,
}
impl InputObservation {
    fn new(ctx: &Context, kind: crate::observation::physical::Kind) -> Option<Self> {
        let mut input_ctx = ctx.physical_scope([0, 0]);
        input_ctx.physical_source = None;
        let attempt = input_ctx.physical_attempt(kind)?;
        Some(Self {
            id: input_ctx.physical_identity(kind)?,
            attempt: Some(attempt),
            bytes: 0,
            read_failed: false,
        })
    }
}
struct ObservedInput<'a> {
    source: &'a mut dyn Read,
    observation: Option<&'a mut InputObservation>,
}
impl Read for ObservedInput<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        let result = self.source.read(bytes);
        if let Some(observation) = &mut self.observation {
            match &result {
                Ok(n) => {
                    observation.bytes = observation.bytes.saturating_add(*n as u64);
                    if let Some(attempt) = &mut observation.attempt {
                        attempt.bytes_processed(observation.bytes);
                    }
                }
                Err(_) => observation.read_failed = true,
            }
        }
        result
    }
}
/// Classify a local source using the same signature rules as engine intake.
/// This does not parse records or promise a stable snapshot for a later Run.
pub fn input_is_plain_csv(job: &Job) -> Result<bool> {
    let mut magic = [0u8; 4];
    let read = File::open(&job.input)?.read(&mut magic)?;
    Ok(!is_removed_compression(magic, read) && input_kind(magic, read).is_none())
}
// Reject former Zstandard inputs by signature, even if named like plain CSV.
fn is_removed_compression(magic: [u8; 4], read: usize) -> bool {
    read == 4
        && (magic == [0x28, 0xb5, 0x2f, 0xfd]
            || u32::from_le_bytes(magic) & 0xfffffff0 == 0x184d2a50)
}

fn input_kind(magic: [u8; 4], read: usize) -> Option<crate::observation::physical::Kind> {
    if read >= 2 && magic[..2] == [0x1f, 0x8b] {
        Some(crate::observation::physical::Kind::GzipInput)
    } else if read == 4 && matches!(&magic, b"PK\x03\x04" | b"PK\x05\x06" | b"PK\x07\x08") {
        Some(crate::observation::physical::Kind::ZipInput)
    } else {
        None
    }
}
fn with_input_report<T>(
    job: &Job,
    buffer: Reservation,
    ctx: Option<&Context>,
    consume: impl FnOnce(Box<dyn Read + '_>, &mut Option<InputObservation>) -> Result<T>,
) -> Result<T> {
    let mut file = File::open(&job.input)?;
    let mut magic = [0u8; 4];
    let read = file.read(&mut magic)?;
    file.seek(SeekFrom::Start(0))?;
    ensure!(
        !is_removed_compression(magic, read),
        "Zstandard input is no longer supported; decompress it before running Chopper"
    );
    let kind = input_kind(magic, read);
    let mut observation =
        ctx.and_then(|ctx| kind.and_then(|kind| InputObservation::new(ctx, kind)));
    let mut entered = false;
    let result = (|| {
        let invoke = |source: Box<dyn Read + '_>| {
            entered = true;
            consume(source, &mut observation)
        };
        if kind == Some(crate::observation::physical::Kind::GzipInput) {
            let codec = buffer.sibling();
            invoke(input_gzip::reader(
                InputBuffer::new(file, 8192, buffer)?,
                codec,
            )?)
        } else if kind == Some(crate::observation::physical::Kind::ZipInput) {
            input_zip::consume(file, job, buffer, invoke)
        } else {
            invoke(Box::new(file))
        }
    })();
    if let Some(mut observation) = observation {
        let status = match &result {
            Ok(_) => crate::observation::Status::Completed,
            Err(_) if observation.read_failed || !entered => crate::observation::Status::Failed,
            Err(_) => crate::observation::Status::Interrupted,
        };
        if let Some(attempt) = observation.attempt.take() {
            attempt.finish_bytes(status, observation.bytes);
        }
    }
    result
}

struct Ingested {
    dataset: Dataset,
    analysis: Analysis,
    final_plan: Option<output::OutputPlan>,
    terminal_publication: Option<(output::DirectPublication, u64, u64)>,
    consumed: usize,
}
#[cfg(test)]
fn ingest(mut source: Box<dyn Read + '_>, job: &Job, ctx: &Context) -> Result<Ingested> {
    ingest_options(source.as_mut(), job, ctx, false, false, false)
}
fn ingest_options(
    source: &mut dyn Read,
    job: &Job,
    ctx: &Context,
    _fuse_partitions: bool,
    _fuse_balanced: bool,
    _fuse_streaming: bool,
) -> Result<Ingested> {
    let input = Intake::new(
        source,
        &job.input_csv,
        ctx.max_record,
        Reservation::new(ctx),
    )?;
    records::with_dialect!(input, &job.input_dialect, |input| ingest_records(
        input,
        job,
        ctx,
        _fuse_partitions,
        _fuse_balanced,
        _fuse_streaming,
    ))
}
fn observe_input_error(
    observation: &mut Option<crate::observation::physical::Span<'_>>,
    rows: u64,
    error: anyhow::Error,
) -> anyhow::Error {
    if let Some(span) = observation.take() {
        span.finish_error(&error, rows);
    }
    error
}
fn ingest_records(
    mut input: Intake<impl records::Records>,
    job: &Job,
    ctx: &Context,
    _fuse_partitions: bool,
    _fuse_balanced: bool,
    _fuse_streaming: bool,
) -> Result<Ingested> {
    let mut input_observation =
        ctx.physical_span_for(crate::observation::physical::Kind::Read, [0, 0]);
    let seed = AnalysisText::copy(job.random_seed.as_deref().unwrap(), Reservation::new(ctx))?;
    let mut stages = Stages::new(job.operations.len(), Reservation::new(ctx))?;
    let header = header::read(&mut input)
        .map_err(|error| observe_input_error(&mut input_observation, 0, error))?;
    let mut input_dataset_ctx = ctx.clone();
    input_dataset_ctx.physical_source =
        crate::observation::physical::identity(0, crate::observation::physical::Kind::Read);
    let mut writer = DatasetWriter::new(&input_dataset_ctx)?;
    let mut group = writer.begin(vec![], false);
    // Calculation planning needs the validated source width before any selectors run.
    let raw_snapshot = !job.calculated_columns.is_empty();
    let initial_operations = if raw_snapshot {
        &[][..]
    } else {
        job.operations.as_slice()
    };
    let leading_shuffles = initial_operations
        .iter()
        .take_while(|op| uniform(op))
        .count();
    let initial_fisher_step = (!raw_snapshot)
        .then(|| shuffle_elision::initial_fisher_step(job, leading_shuffles))
        .flatten();
    let initial_assignment = if !raw_snapshot && shuffle_assignment::ENABLED {
        shuffle_assignment::Plan::at(
            job,
            initial_fisher_step.unwrap_or(leading_shuffles.saturating_sub(1)),
        )
    } else {
        None
    };
    let reverse_partition = if shuffle_partition::ENABLED && leading_shuffles > 0 {
        shuffle_partition::Plan::at(job, leading_shuffles - 1)
    } else {
        None
    };
    let first_partition =
        reverse_partition
            .map(|plan| plan.columns)
            .or_else(|| match initial_operations.first() {
                Some(Operation::Partition { columns }) => Some(columns.as_slice()),
                _ => None,
            });
    let partition_step = reverse_partition.map_or(0, |plan| plan.partition_step);
    #[cfg(feature = "experimental-consecutive-partitions")]
    let consecutive = if _fuse_partitions && !raw_snapshot {
        consecutive_partitions::Plan::at(job, 0)
    } else {
        None
    };
    let partition_shuffles = if first_partition.is_some() && reverse_partition.is_none() {
        job.operations
            .iter()
            .skip(1)
            .take_while(|op| uniform(op))
            .count()
    } else {
        0
    };
    let partition_randomized = partition_shuffles > 0 || reverse_partition.is_some();
    #[cfg(feature = "experimental-partition-balanced")]
    let balanced_plan = (_fuse_balanced && !raw_snapshot)
        .then(|| partition_balanced::Plan::at(job, 0))
        .flatten();
    #[cfg(feature = "experimental-partition-balanced")]
    let mut partition_counts = balanced_plan.map(|_| partition_balanced::Counts::new(ctx));
    let partition_parent = group.clone();
    let mut partition_column_buffers = Reservation::new(ctx);
    let mut partition_keys = None;
    let domain = (leading_shuffles > 0 && initial_fisher_step.is_none()).then(|| {
        random::domain(
            job.random_seed.as_deref().unwrap(),
            (leading_shuffles - 1) as u64,
            "[]",
        )
    });
    let observed_operations = if let Some(plan) = reverse_partition {
        [leading_shuffles, plan.partition_step + 1]
    } else if first_partition.is_some() {
        [
            1,
            if partition_shuffles > 0 {
                1 + partition_shuffles
            } else {
                0
            },
        ]
    } else if let Some(plan) = initial_assignment {
        [plan.assignment_step, plan.assignment_step + 1]
    } else if let Some(step) = initial_fisher_step {
        [step + 1, 0]
    } else if leading_shuffles > 0 {
        [leading_shuffles, 0]
    } else {
        [1, 0]
    };
    let mut observed_ctx = ctx.physical_scope(observed_operations);
    observed_ctx.physical_source =
        crate::observation::physical::identity(0, crate::observation::physical::Kind::Read);
    let ctx = &observed_ctx;
    let elided_end = initial_fisher_step.map_or(leading_shuffles, |step| step + 1);
    for operation in 1..elided_end {
        if let Some(span) = ctx
            .physical_scope([operation, 0])
            .physical_span(crate::observation::physical::Kind::Elided)
        {
            span.finish(0);
        }
    }
    for operation in 2..=partition_shuffles {
        if let Some(span) = ctx
            .physical_scope([operation, 0])
            .physical_span(crate::observation::physical::Kind::Elided)
        {
            span.finish(0);
        }
    }
    let mut sorter = domain.map(|domain| Sorter::new(ctx, SortOrder::Random(domain)));
    #[cfg(target_os = "wasi")]
    if ctx.auto_run
        && job.resources.memory_mb.as_mib() == Some(1024)
        && ctx.max_record <= 8 * 1024 * 1024
        && job.resources.grouping == chopper_core::Grouping::Auto
        && job.compression == chopper_core::Compression::None
        && job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        && job.output_csv.encoding.eq_ignore_ascii_case("utf-8")
        && matches!(
            initial_operations,
            [Operation::Shuffle {
                strategy: Shuffle::Uniform
            }]
        )
        && input_is_plain_csv(job).unwrap_or(false)
    {
        if let Some(sorter) = &mut sorter {
            sorter.prefer_hosted_resident();
        }
    }
    if first_partition.is_some() {
        sorter = Some(Sorter::new(
            ctx,
            if partition_randomized {
                SortOrder::GroupRandom
            } else {
                SortOrder::Key
            },
        ));
    }
    let first_streaming = initial_operations
        .first()
        .filter(|op| streaming::eligible(op));
    let mut initial_streaming = None;
    #[cfg(feature = "experimental-streaming-chain")]
    let chain_plan = (_fuse_streaming && !raw_snapshot)
        .then(|| streaming_chain::Plan::at(job, 0))
        .flatten();
    #[cfg(feature = "experimental-streaming-chain")]
    let chain_enabled = chain_plan.is_some();
    #[cfg(not(feature = "experimental-streaming-chain"))]
    let chain_enabled = false;
    #[cfg(feature = "experimental-streaming-chain")]
    let mut initial_chain: Option<streaming_chain::State<'_, '_>> = None;
    let mut initial_resident = initial_fisher_step.map(|step| {
        ResidentShuffle::new(
            ctx,
            random::domain(job.random_seed.as_deref().unwrap(), step as u64, "[]"),
        )
    });
    let mut direct = if job.operations.is_empty() && !raw_snapshot {
        Some(output::PlanWriter::new(job, header.as_deref(), ctx)?)
    } else {
        None
    };
    let mut digest = crate::digest::LogicalDigest::reserved(Reservation::new(ctx))?;
    let mut preview = preview::Builder::new(Reservation::new(ctx));
    let mut largest = 0;
    let mut total_record_bytes = 0u64;
    let mut column_values = column_summaries::Builder::new(Reservation::new(ctx));
    // Plain serialization keeps owned strings; retaining operations keep compact records.
    let owned_ingestion = job.operations.is_empty() && !raw_snapshot;
    while {
        let next = if owned_ingestion {
            input.next_owned(|| ctx.check())
        } else {
            input.next_compact(
                || ctx.check(),
                |memory, bytes| {
                    #[cfg(feature = "experimental-streaming-chain")]
                    if let Some(chain) = &mut initial_chain {
                        return chain.reserve_parser(memory, bytes);
                    }
                    if let Some(sorter) = &mut sorter {
                        sorter.reserve_input(memory, bytes)
                    } else {
                        memory.resize(bytes)
                    }
                },
            )
        };
        next.map_err(|error| observe_input_error(&mut input_observation, group.rows, error))?
    } {
        let record_fields = if owned_ingestion {
            FieldViews::owned(input.owned())
        } else {
            FieldViews::parsed(input.compact())
        };
        let expected = input.columns();
        column_values.observe(job, header.as_deref(), record_fields.clone())?;
        let size = if owned_ingestion {
            input.owned().iter().map(String::len).sum()
        } else {
            input.compact().payload_bytes()
        };
        largest = largest.max(size as u64);
        total_record_bytes = total_record_bytes.saturating_add(size as u64);
        preview.consider(record_fields, size)?;
        if owned_ingestion {
            digest.record(input.owned());
        } else {
            digest.compact_record(input.compact());
        }
        let ordinal = group.rows;
        if owned_ingestion {
            input.consume_owned(|owned_fields| {
                let row = Row {
                    id: ordinal,
                    ordinal,
                    key: vec![],
                    fields: std::mem::take(owned_fields),
                };
                direct.as_mut().unwrap().row(&mut group, &row)?;
                *owned_fields = row.fields;
                Ok(())
            })?;
        } else {
            input.consume_compact(|fields| {
                let mut row = PackedRow::from_record(ordinal, std::mem::take(fields));
                if chain_enabled {
                    #[cfg(feature = "experimental-streaming-chain")]
                    {
                        if initial_chain.is_none() {
                            initial_chain = Some(streaming_chain::State::new(
                                chain_plan.unwrap(),
                                &partition_parent,
                                header.as_deref(),
                                expected,
                                ctx,
                            )?);
                        }
                        *fields = initial_chain
                            .as_mut()
                            .unwrap()
                            .push(row)?
                            .map(PackedRow::into_parser_record)
                            .unwrap_or_default();
                        group.rows += 1;
                    }
                } else if let Some(operation) = first_streaming {
                    if initial_streaming.is_none() {
                        initial_streaming = Some(StreamingGroups::new(
                            operation,
                            header.as_deref(),
                            expected,
                            random::domain(job.random_seed.as_deref().unwrap(), 0, "[]"),
                            ctx,
                        )?);
                    }
                    *fields = initial_streaming
                        .as_mut()
                        .unwrap()
                        .push_compact(row)?
                        .map(PackedRow::into_parser_record)
                        .unwrap_or_default();
                    group.rows += 1;
                } else if let Some(resident) = &mut initial_resident {
                    resident.push_compact(row)?;
                    group.rows += 1;
                } else if let Some(sorter) = &mut sorter {
                    if let Some(columns) = first_partition {
                        if partition_keys.is_none() {
                            partition_keys = Some(PartitionKeys {
                                #[cfg(feature = "experimental-constant-partition")]
                                key_columns: None,
                                parent: &partition_parent,
                                columns: if let Some(plan) = reverse_partition {
                                    plan.resolve(
                                        header.as_deref(),
                                        expected,
                                        &mut partition_column_buffers,
                                    )?
                                } else {
                                    #[cfg(feature = "experimental-consecutive-partitions")]
                                    if let Some(plan) = consecutive {
                                        plan.resolve(
                                            header.as_deref(),
                                            expected,
                                            &mut partition_column_buffers,
                                        )?
                                    } else {
                                        resolve_columns(columns, header.as_deref(), expected)?
                                    }
                                    #[cfg(not(feature = "experimental-consecutive-partitions"))]
                                    resolve_columns(columns, header.as_deref(), expected)?
                                },
                                step: partition_step,
                                shuffle: if let Some(plan) = reverse_partition {
                                    Some(plan.random(
                                        job.random_seed.as_deref().unwrap(),
                                        &partition_parent,
                                    )?)
                                } else {
                                    (partition_shuffles > 0).then_some(PartitionRandom::After {
                                        seed: job.random_seed.as_deref().unwrap(),
                                        step: partition_shuffles,
                                    })
                                },
                                domains: DomainCache::new(ctx),
                            });
                        }
                        let key = partition_keys.as_mut().unwrap().key(
                            row.id,
                            row.fields(),
                            ctx,
                            sorter,
                        )?;
                        #[cfg(feature = "experimental-partition-balanced")]
                        if partition_counts.is_some() {
                            partition_balanced::observe(
                                &mut partition_counts,
                                &key.bytes[..key.bytes.len() - 48],
                            );
                        }
                        let capacity = key.install(&mut row, sorter)?;
                        *fields = sorter
                            .push_compact_reusing(row, capacity)?
                            .map(PackedRow::into_parser_record)
                            .unwrap_or_default();
                    } else {
                        let key = random::block(domain.as_ref().unwrap(), row.id, 0);
                        row.key = PackedKey::Random(key[..16].try_into().unwrap());
                        sorter.push_compact(row, 16)?;
                    }
                    group.rows += 1;
                } else if let Some(plan) = &mut direct {
                    plan.packed_row_ref(&mut group, &row)?;
                    *fields = row.into_parser_record();
                } else {
                    writer.packed_row_ref(&mut group, &row)?;
                    *fields = row.into_parser_record();
                }
                Ok(())
            })?;
        }
        if let Some(span) = &mut input_observation {
            span.rows_processed(group.rows);
        }
        if group.rows % 65536 == 0 {
            ctx.event("Reading and validating CSV", group.rows)?;
        }
    }
    // Intake destroys records/parser/source before releasing their grants.
    // Retained headers and consumer-owned rows keep their independent admission.
    let width = input.columns();
    drop(input);
    let rows = group.rows;
    if let Some(span) = input_observation {
        span.finish(rows);
    }

    let mut final_plan = None;
    let mut terminal_publication = None;
    let mut consumed = leading_shuffles;
    let mut group_count = 1;
    let mut partition_stats = None;
    #[allow(unused_mut)]
    let mut partitions_reported = false;
    if chain_enabled {
        #[cfg(feature = "experimental-streaming-chain")]
        {
            let chain = match initial_chain {
                Some(chain) => chain,
                None => streaming_chain::State::new(
                    chain_plan.unwrap(),
                    &partition_parent,
                    header.as_deref(),
                    width,
                    ctx,
                )?,
            };
            consumed = 3;
            let stats = if consumed == job.operations.len() {
                let mut plan = output::PlanWriter::new(job, header.as_deref(), ctx)?;
                let stats = chain.emit(&mut plan)?;
                final_plan = Some(plan.finish()?);
                stats
            } else {
                chain.emit(&mut writer)?
            };
            group_count = stats[2].output_groups;
            stages.extend(stats)?;
            partitions_reported = true;
            ctx.streaming_chain_fused(rows);
        }
    } else if let Some(operation) = first_streaming {
        let routed = match initial_streaming {
            Some(routed) => routed,
            None => StreamingGroups::new(
                operation,
                header.as_deref(),
                width,
                random::domain(job.random_seed.as_deref().unwrap(), 0, "[]"),
                ctx,
            )?,
        };
        consumed = 1;
        if consumed == job.operations.len() {
            let mut plan = if ctx.direct_terminal_output {
                output::PlanWriter::direct_grouped(job, header.as_ref(), ctx)?
            } else {
                output::PlanWriter::new(job, header.as_deref(), ctx)?
            };
            routed.emit(&group, 0, &mut plan, ctx)?;
            partition_stats = Some(StageStats {
                operation: 1,
                input_groups: 1,
                output_groups: plan.groups,
                smallest_group: if plan.groups == 0 { 0 } else { plan.smallest },
                largest_group: plan.largest,
                empty_groups: plan.empty,
            });
            if ctx.direct_terminal_output {
                terminal_publication = Some(plan.finish_direct()?);
            } else {
                final_plan = Some(plan.finish()?);
            }
        } else {
            routed.emit(&group, 0, &mut writer, ctx)?;
        }
    } else if let Some(resident) = initial_resident {
        consumed = initial_fisher_step.unwrap() + 1;
        for operation in 1..=consumed {
            stages.push(StageStats {
                operation,
                input_groups: 1,
                output_groups: 1,
                smallest_group: rows,
                largest_group: rows,
                empty_groups: u64::from(rows == 0),
            })?;
        }
        let shuffled = SortedRows::Memory(resident.finish()?);
        let balanced_step = consumed;
        let balanced = initial_balanced(job, rows, &mut consumed, &mut group_count, &mut stages)?;
        if let Some(assignment) = initial_assignment {
            consumed += 1;
            let stats = if consumed == job.operations.len() {
                let mut plan = output::PlanWriter::new(job, header.as_deref(), ctx)?;
                let stats = assignment.emit_sorted(
                    shuffled,
                    &group,
                    &mut plan,
                    ctx,
                    crate::observation::physical::Kind::FisherYates,
                )?;
                final_plan = Some(plan.finish()?);
                stats
            } else {
                assignment.emit_sorted(
                    shuffled,
                    &group,
                    &mut writer,
                    ctx,
                    crate::observation::physical::Kind::FisherYates,
                )?
            };
            group_count = stats.output_groups;
            stages.push(stats)?;
        } else if consumed == job.operations.len() {
            let mut plan = if ctx.direct_terminal_output {
                output::PlanWriter::direct_grouped(job, header.as_ref(), ctx)?
            } else {
                output::PlanWriter::new(job, header.as_deref(), ctx)?
            };
            emit_initial_shuffle(
                shuffled,
                &group,
                balanced,
                balanced_step,
                &mut plan,
                ctx,
                crate::observation::physical::Kind::FisherYates,
            )?;
            if ctx.direct_terminal_output {
                terminal_publication = Some(plan.finish_direct()?);
            } else {
                final_plan = Some(plan.finish()?);
            }
        } else {
            emit_initial_shuffle(
                shuffled,
                &group,
                balanced,
                balanced_step,
                &mut writer,
                ctx,
                crate::observation::physical::Kind::FisherYates,
            )?;
        }
    } else if let Some(columns) = first_partition {
        let columns = if let Some(plan) = reverse_partition {
            if let Some(keys) = partition_keys.take() {
                // Reuse the charged selection; the before-shuffle mode never
                // populates the optional per-child domain cache.
                keys.columns
            } else {
                plan.resolve(header.as_deref(), width, &mut partition_column_buffers)?
            }
        } else {
            #[cfg(feature = "experimental-consecutive-partitions")]
            if let Some(plan) = consecutive {
                if let Some(keys) = partition_keys.take() {
                    keys.columns
                } else {
                    plan.resolve(header.as_deref(), width, &mut partition_column_buffers)?
                }
            } else {
                resolve_columns(columns, header.as_deref(), width)?
            }
            #[cfg(not(feature = "experimental-consecutive-partitions"))]
            resolve_columns(columns, header.as_deref(), width)?
        };
        // Release the key cache before merging and encoding.
        drop(partition_keys);
        consumed = reverse_partition.map_or(1 + partition_shuffles, |plan| plan.partition_step + 1);
        if reverse_partition.is_some() {
            for operation in 1..=leading_shuffles {
                stages.push(StageStats {
                    operation,
                    input_groups: 1,
                    output_groups: 1,
                    smallest_group: rows,
                    largest_group: rows,
                    empty_groups: u64::from(rows == 0),
                })?;
            }
        }
        let sorted = sorter.unwrap().finish()?;
        #[allow(unused_mut)]
        let mut sorted = Some(sorted);
        #[cfg(feature = "experimental-partition-balanced")]
        if let (Some(plan), Some(counts)) = (balanced_plan, partition_counts) {
            let mut stats = plan.stats();
            consumed = plan.len();
            if consumed == job.operations.len() {
                let mut output = output::PlanWriter::new(job, header.as_deref(), ctx)?;
                plan.emit(
                    sorted.take().unwrap(),
                    &group,
                    &columns,
                    &counts,
                    &mut stats,
                    &mut output,
                    ctx,
                )?;
                final_plan = Some(output.finish()?);
            } else {
                plan.emit(
                    sorted.take().unwrap(),
                    &group,
                    &columns,
                    &counts,
                    &mut stats,
                    &mut writer,
                    ctx,
                )?;
            }
            group_count = stats.balanced.output_groups;
            ctx.partition_balanced_fused(rows);
            stats.append(plan, &mut stages)?;
            partitions_reported = true;
        }
        #[cfg(feature = "experimental-consecutive-partitions")]
        if let Some(plan) = consecutive {
            consumed = plan.len();
            let mut stats = plan.stats();
            if consumed == job.operations.len() {
                let mut output = output::PlanWriter::new(job, header.as_deref(), ctx)?;
                plan.emit(
                    sorted.take().unwrap(),
                    &group,
                    &columns,
                    &mut stats,
                    &mut output,
                    ctx,
                )?;
                final_plan = Some(output.finish()?);
            } else {
                plan.emit(
                    sorted.take().unwrap(),
                    &group,
                    &columns,
                    &mut stats,
                    &mut writer,
                    ctx,
                )?;
            }
            stats.finish();
            group_count = stats.last().output_groups;
            stats.append(&mut stages)?;
            partitions_reported = true;
        }
        if let Some(sorted) = sorted {
            if consumed == job.operations.len() {
                // One UTF-8 delimiter or terminator byte per field is a lower
                // bound. Quoting, headers, and CRLF can only add output bytes.
                let hosted_buffer = if cfg!(target_os = "wasi") {
                    run_route::hosted_terminal_shuffle_buffer(
                        job,
                        ctx,
                        total_record_bytes.saturating_add(rows.saturating_mul(width as u64)),
                    )
                } else {
                    None
                };
                let mut plan = if let Some(buffer) = hosted_buffer {
                    output::PlanWriter::direct_grouped_buffered(job, header.as_ref(), ctx, buffer)?
                } else if ctx.direct_terminal_output {
                    output::PlanWriter::direct_grouped(job, header.as_ref(), ctx)?
                } else {
                    output::PlanWriter::new(job, header.as_deref(), ctx)?
                };
                emit_partition(
                    sorted,
                    &group,
                    &columns,
                    partition_step,
                    partition_randomized,
                    &mut plan,
                    ctx,
                )?;
                partition_stats = Some(StageStats {
                    operation: partition_step + 1,
                    input_groups: 1,
                    output_groups: plan.groups,
                    smallest_group: if plan.groups == 0 { 0 } else { plan.smallest },
                    largest_group: plan.largest,
                    empty_groups: plan.empty,
                });
                if hosted_buffer.is_some() || ctx.direct_terminal_output {
                    terminal_publication = Some(plan.finish_direct()?);
                } else {
                    final_plan = Some(plan.finish()?);
                }
            } else {
                emit_partition(
                    sorted,
                    &group,
                    &columns,
                    partition_step,
                    partition_randomized,
                    &mut writer,
                    ctx,
                )?;
            }
        }
        if reverse_partition.is_some() {
            ctx.shuffle_partition_fused(rows);
        }
    } else if let Some(sorter) = sorter {
        for operation in 1..=leading_shuffles {
            stages.push(StageStats {
                operation,
                input_groups: 1,
                output_groups: 1,
                smallest_group: rows,
                largest_group: rows,
                empty_groups: u64::from(rows == 0),
            })?;
        }
        let balanced = initial_balanced(job, rows, &mut consumed, &mut group_count, &mut stages)?;
        let sorted = sorter.finish()?;
        if let Some(assignment) = initial_assignment {
            consumed += 1;
            let stats = if consumed == job.operations.len() {
                let mut plan = output::PlanWriter::new(job, header.as_deref(), ctx)?;
                let stats = assignment.emit_sorted(
                    sorted,
                    &group,
                    &mut plan,
                    ctx,
                    crate::observation::physical::Kind::ResidentSort,
                )?;
                final_plan = Some(plan.finish()?);
                stats
            } else {
                assignment.emit_sorted(
                    sorted,
                    &group,
                    &mut writer,
                    ctx,
                    crate::observation::physical::Kind::ResidentSort,
                )?
            };
            group_count = stats.output_groups;
            stages.push(stats)?;
        } else if consumed == job.operations.len() {
            let hosted_buffer = if cfg!(target_os = "wasi") {
                run_route::hosted_terminal_shuffle_buffer(
                    job,
                    ctx,
                    total_record_bytes.saturating_add(rows.saturating_mul(width as u64)),
                )
            } else {
                None
            };
            let mut plan = if let Some(buffer) = hosted_buffer {
                output::PlanWriter::direct_grouped_buffered(job, header.as_ref(), ctx, buffer)?
            } else if ctx.direct_terminal_output {
                output::PlanWriter::direct_grouped(job, header.as_ref(), ctx)?
            } else {
                output::PlanWriter::new(job, header.as_deref(), ctx)?
            };
            emit_initial_shuffle(
                sorted,
                &group,
                balanced,
                leading_shuffles,
                &mut plan,
                ctx,
                crate::observation::physical::Kind::ResidentSort,
            )?;
            if hosted_buffer.is_some() || ctx.direct_terminal_output {
                terminal_publication = Some(plan.finish_direct()?);
            } else {
                final_plan = Some(plan.finish()?);
            }
        } else {
            emit_initial_shuffle(
                sorted,
                &group,
                balanced,
                leading_shuffles,
                &mut writer,
                ctx,
                crate::observation::physical::Kind::ResidentSort,
            )?;
        }
    } else if let Some(mut plan) = direct {
        plan.end(group)?;
        final_plan = Some(plan.finish()?);
    } else {
        writer.end(group)?;
    }
    let dataset = writer.finish()?;
    if !partitions_reported && (first_partition.is_some() || first_streaming.is_some()) {
        let mut stats = match partition_stats {
            Some(stats) => stats,
            None => dataset_stats(&dataset, partition_step + 1, 1, ctx)?,
        };
        group_count = stats.output_groups;
        stages.push(stats.clone())?;
        for operation in partition_step + 2..=consumed {
            stats.operation = operation;
            stats.input_groups = stats.output_groups;
            stages.push(stats.clone())?;
        }
    }
    ctx.input_record_bytes(total_record_bytes);
    Ok(Ingested { dataset, final_plan, terminal_publication, consumed, analysis: Analysis { algorithm_version: Analysis::algorithm_version_for(job), column_values: column_values.finish()?, seed, rows, columns: width, header, preview: preview.finish()?,
        logical_digest: AnalysisText::copy(digest.finalize().to_hex().as_str(), Reservation::new(ctx))?, groups: group_count, output_files: 0, output_csv_bytes: 0,
        largest_record_bytes: largest, temp_bytes: 0, peak_temp_bytes: 0, memory_budget_bytes: ctx.memory as u64, workers: ctx.workers(), analysis_seconds: 0.0, timings: Default::default(), diagnostics: Default::default(), stages, warnings: Warnings::default(),
        accuracy: AnalysisText::copy("Exact row, group, file and uncompressed byte counts; complete strict validation. Compressed sizes and runtime are not guaranteed.", Reservation::new(ctx))?, execution: None, auto_plan: None } })
}
fn initial_balanced(
    job: &Job,
    rows: u64,
    consumed: &mut usize,
    groups: &mut u64,
    stages: &mut Stages,
) -> Result<Option<u64>> {
    let Some(Operation::Balanced { files }) = job.operations.get(*consumed) else {
        return Ok(None);
    };
    ensure!(
        rows >= *files,
        "cannot split {rows} rows into {files} nonempty balanced groups"
    );
    stages.push(StageStats {
        operation: *consumed + 1,
        input_groups: 1,
        output_groups: *files,
        smallest_group: rows / files,
        largest_group: rows.div_ceil(*files),
        empty_groups: 0,
    })?;
    *groups = *files;
    *consumed += 1;
    Ok(Some(*files))
}
fn sorted_physical_kind(
    rows: &SortedRows,
    memory: crate::observation::physical::Kind,
) -> crate::observation::physical::Kind {
    match rows {
        SortedRows::Memory(_) => memory,
        SortedRows::Merge(_) => crate::observation::physical::Kind::MergeTraversal,
        SortedRows::Routed(_) => crate::observation::physical::Kind::Routing,
    }
}
fn emit_initial_shuffle(
    rows: SortedRows,
    parent: &Group,
    balanced: Option<u64>,
    step: usize,
    output: &mut impl RowSink,
    ctx: &Context,
    memory_kind: crate::observation::physical::Kind,
) -> Result<()> {
    output.physical_input(ctx.physical_identity(sorted_physical_kind(&rows, memory_kind)));
    if let Some(files) = balanced {
        return emit_balanced(rows, parent, files, step, memory_kind, output, ctx);
    }
    let mut group = output.begin(vec![], false);
    rows.try_for_each_packed(|row| {
        ctx.check()?;
        row.ordinal = group.rows;
        row.key = PackedKey::Bytes(Box::default());
        output.packed_row_ref(&mut group, row)
    })?;
    output.end(group)
}

#[cfg(test)]
fn child(
    parent: &Group,
    value: serde_json::Value,
    ctx: &Context,
) -> Result<Vec<serde_json::Value>> {
    let mut lineage = parent.lineage.clone();
    lineage.push(value);
    validate_lineage(&lineage, ctx)?;
    Ok(lineage)
}
fn validate_lineage<T: Serialize + ?Sized>(lineage: &T, ctx: &Context) -> Result<()> {
    struct BoundedSize(usize);
    impl std::io::Write for BoundedSize {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if bytes.len() > self.0 {
                return Err(std::io::Error::other(
                    "group lineage exceeds metadata record budget",
                ));
            }
            self.0 -= bytes.len();
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    serde_json::to_writer(BoundedSize(ctx.max_record), lineage)?;
    Ok(())
}
fn apply(
    data: &Dataset,
    operation: &Operation,
    step: usize,
    job: &Job,
    analysis: &Analysis,
    ctx: &Context,
) -> Result<Dataset> {
    #[cfg(feature = "experimental-constant-partition")]
    if let Operation::Partition { columns } = operation {
        let columns = resolve_columns(columns, analysis.header.as_deref(), analysis.columns)?;
        if let Some(plan) = constant_partition::Plan::new(&columns, step, job, analysis, ctx)? {
            if plan.varying.is_empty() {
                if let Some(result) = plan.shared(data, &columns, step, job, analysis, ctx)? {
                    return Ok(result);
                }
            }
        }
    }
    let mut output = DatasetWriter::new(ctx)?;
    if let Operation::Balanced { files } = operation {
        // A terminal Partition decodes every row before emitting each group.
        // Leave invalid selectors and alternate rewrite paths on the full scan.
        let defer_last = job.calculated_columns.is_empty()
            && !cfg!(feature = "experimental-constant-partition")
            && matches!(
                &job.operations[step + 1..],
                [Operation::Partition { columns }] if columns.iter().all(|column| {
                    resolve_column(column, analysis.header.as_deref(), analysis.columns).is_ok()
                })
            );
        for parent in data.groups()? {
            let parent = parent?;
            shared_balanced_parent(data, &parent, *files, step, defer_last, &mut output, ctx)?;
        }
        let mut result = output.finish()?;
        result.data = data.data.clone();
        return Ok(result);
    }
    apply_into(
        data,
        operation,
        step,
        job,
        analysis,
        ctx,
        &mut output,
        None,
        None,
    )?;
    output.finish()
}
fn shared_balanced_parent(
    data: &Dataset,
    parent: &Group,
    files: u64,
    step: usize,
    defer_last: bool,
    output: &mut impl RowSink,
    ctx: &Context,
) -> Result<()> {
    let mut observation = ctx.physical_attempt(crate::observation::physical::Kind::SharedRanges);
    output.physical_input(ctx.physical_identity(crate::observation::physical::Kind::SharedRanges));
    let mut observed = crate::observation::physical::AllocationCounts::default();
    let result = (|| -> Result<()> {
        ensure!(
            parent.rows >= files,
            "cannot split {} rows into {files} nonempty balanced groups",
            parent.rows
        );
        let mut rows = if defer_last && files == 1 {
            None
        } else {
            Some(data.frame_lengths(parent, ctx.max_record)?)
        };
        let mut offset = parent.offset;
        observed.len = usize::try_from(files).unwrap_or(usize::MAX);
        for part in 0..files {
            let n = parent.rows / files + u64::from(part < parent.rows % files);
            let group = group_metadata::ClonedGroup::child(
                parent,
                &child_metadata::Entry::part(step, part + 1),
                ctx,
                |lineage| Group {
                    offset,
                    rows: n,
                    lineage,
                    exact: true,
                },
            )?;
            if defer_last && part + 1 == files {
                ctx.check()?;
            } else {
                let rows = rows.as_mut().expect("boundary scan reader");
                for _ in 0..n {
                    ctx.check()?;
                    offset = offset
                        .checked_add(rows.next().context("missing balanced row")??)
                        .context("spool size overflow")?;
                    observed.rows += 1;
                    if let Some(attempt) = &mut observation {
                        attempt.rows_processed(observed.rows);
                    }
                }
            }
            group.finish(output)?;
            observed.groups += 1;
            if part < crate::observation::physical::MAX_MEMBERSHIPS as u64 {
                observed.memberships[part as usize] = n;
            }
        }
        Ok(())
    })();
    if let Some(attempt) = observation {
        attempt.allocation(
            result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ),
            observed,
        );
    }
    result
}
#[allow(clippy::too_many_arguments)]
fn apply_into(
    data: &Dataset,
    operation: &Operation,
    step: usize,
    job: &Job,
    analysis: &Analysis,
    ctx: &Context,
    output: &mut impl RowSink,
    shuffle_after: Option<usize>,
    balanced_after: Option<(usize, u64)>,
) -> Result<()> {
    if shuffle_partition::ENABLED {
        if let Some(plan) = shuffle_partition::Plan::at(job, step) {
            return plan.apply(data, job, analysis, ctx, output);
        }
    }
    if shuffle_assignment::ENABLED {
        if let Some(plan) = shuffle_assignment::Plan::at(job, step) {
            return plan.apply(data, job, analysis, ctx, output);
        }
    }
    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    if let Some(plan) = probabilistic_shuffle::Plan::selected(job, step, analysis, ctx) {
        return plan.apply(data, job, analysis, ctx, output);
    }
    for parent in data.groups()? {
        ctx.check()?;
        let parent = parent?;
        apply_parent(
            data,
            &parent,
            operation,
            step,
            job,
            analysis,
            ctx,
            output,
            shuffle_after,
            balanced_after,
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn apply_parent(
    data: &Dataset,
    parent: &Group,
    operation: &Operation,
    step: usize,
    job: &Job,
    analysis: &Analysis,
    ctx: &Context,
    output: &mut impl RowSink,
    shuffle_after: Option<usize>,
    balanced_after: Option<(usize, u64)>,
) -> Result<()> {
    ctx.check()?;
    let domain = random::json_domain(
        job.random_seed.as_ref().unwrap(),
        step as u64,
        &parent.lineage,
    )?;
    match operation {
        Operation::Interleaved { .. } | Operation::AssignProbabilistic { .. } => {
            let mut routed = StreamingGroups::new(
                operation,
                analysis.header.as_deref(),
                analysis.columns,
                domain,
                ctx,
            )?;
            let mut rows = data.rows(parent, ctx.max_record)?;
            let mut previous = None;
            while let Some(row) = rows.next_packed(previous.take())? {
                previous = routed.push_compact(row)?;
            }
            routed.emit(parent, step, output, ctx)?;
        }
        Operation::Balanced { files } => {
            let mut observation =
                ctx.physical_attempt(crate::observation::physical::Kind::BalancedTraversal);
            output.physical_input(
                ctx.physical_identity(crate::observation::physical::Kind::BalancedTraversal),
            );
            let mut observed = crate::observation::physical::AllocationCounts {
                len: usize::try_from(*files).unwrap_or(usize::MAX),
                ..Default::default()
            };
            let result = (|| -> Result<()> {
                ensure!(
                    parent.rows >= *files,
                    "cannot split {} rows into {files} nonempty balanced groups",
                    parent.rows
                );
                let mut rows = data.rows(parent, ctx.max_record)?;
                let mut previous = None;
                for part in 0..*files {
                    let n = parent.rows / files + u64::from(part < parent.rows % files);
                    let mut owned = group_metadata::ClonedGroup::begin_child(
                        parent,
                        &child_metadata::Entry::part(step, part + 1),
                        true,
                        output,
                        ctx,
                    )?;
                    let group = &mut owned.group;
                    for _ in 0..n {
                        ctx.check()?;
                        let row = rows
                            .next_packed(previous.take())?
                            .context("missing balanced row")?;
                        output.packed_row_ref(group, &row)?;
                        previous = Some(row);
                        observed.rows += 1;
                        if let Some(attempt) = &mut observation {
                            attempt.rows_processed(observed.rows);
                        }
                    }
                    ctx.check()?;
                    owned.finish(output)?;
                    observed.groups += 1;
                    if part < crate::observation::physical::MAX_MEMBERSHIPS as u64 {
                        observed.memberships[part as usize] = n;
                    }
                }
                Ok(())
            })();
            if let Some(attempt) = observation {
                attempt.allocation(
                    result.as_ref().err().map_or(
                        crate::observation::Status::Completed,
                        crate::observation::physical::error_status,
                    ),
                    observed,
                );
            }
            result?;
        }
        Operation::Partition { columns } => {
            let columns = resolve_columns(columns, analysis.header.as_deref(), analysis.columns)?;
            #[cfg(feature = "experimental-constant-partition")]
            let plan = constant_partition::Plan::new(&columns, step, job, analysis, ctx)?;
            #[cfg(feature = "experimental-constant-partition")]
            if let Some(plan) = &plan {
                if plan.varying.is_empty() {
                    if parent.rows == 0 {
                        return Ok(());
                    }
                    if let Some(child) = plan.child(parent, &columns, step, job, analysis, ctx)? {
                        if let Some(shuffle_step) = shuffle_after {
                            return apply_parent(
                                data,
                                &child.group,
                                &Operation::Shuffle {
                                    strategy: Shuffle::Uniform,
                                },
                                shuffle_step,
                                job,
                                analysis,
                                ctx,
                                output,
                                None,
                                None,
                            );
                        }
                        return constant_partition::copy(data, child, ctx, output);
                    }
                }
            }
            partition(
                data,
                parent,
                &columns,
                step,
                output,
                ctx,
                shuffle_after.map(|i| (job.random_seed.as_deref().unwrap(), i)),
                #[cfg(feature = "experimental-constant-partition")]
                plan.as_ref()
                    .filter(|p| !p.varying.is_empty())
                    .map(|p| p.varying.as_slice()),
            )?;
        }
        Operation::Shuffle { strategy } => {
            let mut owned =
                group_metadata::ClonedGroup::begin(parent, output, Reservation::new(ctx))?;
            let group = &mut owned.group;
            if *strategy == Shuffle::FisherYates {
                let mut resident = ResidentShuffle::new(ctx, domain);
                for row in data.packed_rows(parent, ctx.max_record)? {
                    resident.push_compact(row?)?;
                }
                output.physical_input(
                    ctx.physical_identity(crate::observation::physical::Kind::FisherYates),
                );
                let shuffled = resident.finish()?;
                if let Some((balanced_step, files)) = balanced_after {
                    return emit_balanced(
                        SortedRows::Memory(shuffled),
                        parent,
                        files,
                        balanced_step,
                        crate::observation::physical::Kind::FisherYates,
                        output,
                        ctx,
                    );
                }
                for row in shuffled.compact() {
                    ctx.check()?;
                    let mut row = row?;
                    row.ordinal = group.rows;
                    row.key = PackedKey::Bytes(Box::default());
                    output.packed_row(group, row)?;
                }
            } else {
                let mut sorter = Sorter::new(ctx, SortOrder::Random(domain));
                for row in data.packed_rows(parent, ctx.max_record)? {
                    let mut row = row?;
                    let key = random::block(&domain, row.id, 0);
                    row.key = PackedKey::Random(key[..16].try_into().unwrap());
                    sorter.push_compact(row, 16)?;
                }
                let sorted = sorter.finish()?;
                output.physical_input(ctx.physical_identity(sorted_physical_kind(
                    &sorted,
                    crate::observation::physical::Kind::ResidentSort,
                )));
                if let Some((balanced_step, files)) = balanced_after {
                    emit_balanced(
                        sorted,
                        parent,
                        files,
                        balanced_step,
                        crate::observation::physical::Kind::ResidentSort,
                        output,
                        ctx,
                    )?;
                    return Ok(());
                }
                sorted.try_for_each_packed(|row| {
                    ctx.check()?;
                    row.ordinal = group.rows;
                    row.key = PackedKey::Bytes(Box::default());
                    output.packed_row_ref(group, row)
                })?;
            }
            ctx.check()?;
            owned.finish(output)?;
        }
        Operation::Assign { groups, strata } => {
            let columns = resolve_columns(strata, analysis.header.as_deref(), analysis.columns)?;
            assign(
                data,
                parent,
                &columns,
                groups,
                step,
                &domain,
                shuffle_after.map(|i| (job.random_seed.as_deref().unwrap(), i)),
                output,
                ctx,
            )?;
        }
    }
    Ok(())
}

fn emit_balanced(
    rows: SortedRows,
    parent: &Group,
    files: u64,
    step: usize,
    memory_kind: crate::observation::physical::Kind,
    output: &mut impl RowSink,
    ctx: &Context,
) -> Result<()> {
    let mut split_ctx = ctx.physical_scope([step + 1, 0]);
    split_ctx.physical_source = ctx.physical_identity(sorted_physical_kind(&rows, memory_kind));
    let ctx = &split_ctx;
    let mut observation = ctx.physical_attempt(crate::observation::physical::Kind::FusedBalanced);
    output.physical_input(ctx.physical_identity(crate::observation::physical::Kind::FusedBalanced));
    let mut observed = crate::observation::physical::AllocationCounts {
        len: usize::try_from(files).unwrap_or(usize::MAX),
        ..Default::default()
    };
    let result = (|| -> Result<()> {
        ensure!(
            parent.rows >= files,
            "cannot split {} rows into {files} nonempty balanced groups",
            parent.rows
        );
        let mut rows = rows.reusing();
        let mut ordinal = 0;
        for part in 0..files {
            let n = parent.rows / files + u64::from(part < parent.rows % files);
            let mut owned = group_metadata::ClonedGroup::begin_child(
                parent,
                &child_metadata::Entry::part(step, part + 1),
                true,
                output,
                ctx,
            )?;
            let group = &mut owned.group;
            for _ in 0..n {
                ctx.check()?;
                let row = rows.next()?.context("missing balanced row")?;
                row.ordinal = ordinal;
                row.key = PackedKey::Bytes(Box::default());
                output.packed_row_ref(group, row)?;
                ordinal += 1;
                observed.rows += 1;
                if let Some(attempt) = &mut observation {
                    attempt.rows_processed(observed.rows);
                }
            }
            ctx.check()?;
            owned.finish(output)?;
            observed.groups += 1;
            if part < crate::observation::physical::MAX_MEMBERSHIPS as u64 {
                observed.memberships[part as usize] = n;
            }
        }
        Ok(())
    })();
    if let Some(attempt) = observation {
        attempt.allocation(
            result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ),
            observed,
        );
    }
    result
}

#[derive(Clone, Copy)]
enum PartitionRandom<'a> {
    After { seed: &'a str, step: usize },
    Before([u8; 32]),
}
struct PartitionKeys<'a> {
    parent: &'a Group,
    columns: Vec<usize>,
    #[cfg(feature = "experimental-constant-partition")]
    key_columns: Option<&'a [usize]>,
    step: usize,
    shuffle: Option<PartitionRandom<'a>>,
    domains: DomainCache,
}
impl PartitionKeys<'_> {
    fn key(
        &mut self,
        id: u64,
        fields: FieldViews<'_>,
        ctx: &Context,
        sorter: &mut Sorter,
    ) -> Result<OperationKey> {
        ctx.check()?;
        #[cfg(feature = "experimental-constant-partition")]
        let columns = self.key_columns.unwrap_or(&self.columns);
        #[cfg(not(feature = "experimental-constant-partition"))]
        let columns = &self.columns;
        let mut key = OperationKey::tuple(
            fields.clone(),
            columns,
            if self.shuffle.is_some() { 48 } else { 0 },
            Reservation::new(ctx),
            sorter,
        )?;
        if let Some(random) = self.shuffle {
            let domain = match random {
                PartitionRandom::Before(domain) => domain,
                PartitionRandom::After { seed, step: index } => {
                    if let Some(domain) = self.domains.get(&key.bytes) {
                        domain
                    } else {
                        let domain = child_metadata::domain(
                            self.parent,
                            &child_metadata::Entry::values(
                                self.step,
                                fields.clone(),
                                &self.columns,
                            ),
                            seed,
                            index,
                            ctx,
                        )?;
                        self.domains.insert(&key.bytes, domain);
                        domain
                    }
                }
            };
            key.bytes
                .extend_from_slice(&random::block(&domain, id, 0)[..16]);
            key.bytes.extend_from_slice(&domain);
        }
        Ok(key)
    }
}
#[allow(clippy::too_many_arguments)]
fn partition(
    data: &Dataset,
    parent: &Group,
    columns: &[usize],
    step: usize,
    output: &mut impl RowSink,
    ctx: &Context,
    shuffle: Option<(&str, usize)>,
    #[cfg(feature = "experimental-constant-partition")] key_columns: Option<&[usize]>,
) -> Result<()> {
    let mut sorter = Sorter::new(
        ctx,
        if shuffle.is_some() {
            SortOrder::GroupRandom
        } else {
            SortOrder::Key
        },
    );
    let mut keys = PartitionKeys {
        parent,
        columns: columns.to_vec(),
        #[cfg(feature = "experimental-constant-partition")]
        key_columns,
        step,
        shuffle: shuffle.map(|(seed, step)| PartitionRandom::After { seed, step }),
        domains: DomainCache::new(ctx),
    };
    for row in data.packed_rows(parent, ctx.max_record)? {
        let mut row = row?;
        let key = keys.key(row.id, row.fields(), ctx, &mut sorter)?;
        let capacity = key.install(&mut row, &mut sorter)?;
        sorter.push_compact(row, capacity)?;
    }
    emit_partition(
        sorter.finish()?,
        parent,
        columns,
        step,
        shuffle.is_some(),
        output,
        ctx,
    )
}
#[cfg(any(target_os = "linux", target_os = "wasi"))]
#[cold]
#[inline(never)]
fn try_calculated_partition(
    plan: &calculation::Plan,
    dataset: &Dataset,
    columns: &[chopper_core::Column],
    job: &Job,
    ctx: &Context,
) -> Result<(output::OutputPlan, StageStats, f64)> {
    let columns = resolve_columns(columns, Some(&plan.header), plan.header.len())?;
    let parent = dataset
        .groups()?
        .next()
        .context("missing retained root group")??;
    // Hosted calculation/Partition retains the ordinary encoded-output
    // snapshot and admits its writer before constructing the grouping state.
    #[cfg(target_os = "wasi")]
    let mut writer = output::PlanWriter::new(job, Some(&plan.header), ctx)?;
    let started = std::time::Instant::now();
    let sorted = plan.sorted_partition(dataset, &parent, &columns, job, ctx)?;
    let traversal_seconds = started.elapsed().as_secs_f64();
    ctx.operation_event(1, 1)?;
    #[cfg(target_os = "linux")]
    let mut writer = output::PlanWriter::new(job, Some(&plan.header), ctx)?;
    emit_partition(sorted, &parent, &columns, 0, false, &mut writer, ctx)?;
    let stats = StageStats {
        operation: 1,
        input_groups: 1,
        output_groups: writer.groups,
        smallest_group: if writer.groups == 0 {
            0
        } else {
            writer.smallest
        },
        largest_group: writer.largest,
        empty_groups: writer.empty,
    };
    Ok((writer.finish()?, stats, traversal_seconds))
}

fn emit_partition(
    rows: SortedRows,
    parent: &Group,
    columns: &[usize],
    step: usize,
    shuffled: bool,
    output: &mut impl RowSink,
    ctx: &Context,
) -> Result<()> {
    let kind = if matches!(&rows, SortedRows::Routed(_)) {
        crate::observation::physical::Kind::RoutedGrouping
    } else {
        crate::observation::physical::Kind::Grouping
    };
    let mut grouped_ctx = ctx.clone();
    if matches!(&rows, SortedRows::Memory(_)) {
        grouped_ctx.physical_source =
            ctx.physical_identity(crate::observation::physical::Kind::ResidentSort);
    }
    if matches!(&rows, SortedRows::Merge(_)) {
        grouped_ctx.physical_source =
            ctx.physical_identity(crate::observation::physical::Kind::MergeTraversal);
    }
    if matches!(&rows, SortedRows::Routed(_)) {
        grouped_ctx.physical_source =
            ctx.physical_identity(crate::observation::physical::Kind::Routing);
    }
    let mut observation =
        grouped_ctx.physical_pending_span_for(kind, grouped_ctx.physical_operations);
    output.physical_input(grouped_ctx.physical_identity(kind));
    let result = (|| -> Result<()> {
        let mut output = crate::observation::rows::ObservedRows::new(output, &mut observation);
        let output = &mut output;
        let mut previous = keys::BoundaryKey::new(Reservation::new(ctx));
        let mut group: Option<group_metadata::ClonedGroup> = None;
        let mut rows = rows.reusing();
        while let Some(row) = rows.next()? {
            ctx.check()?;
            let key = row.key.as_ref();
            let key = if shuffled {
                &key[..key.len() - 48]
            } else {
                key
            };
            if !previous.matches(key) {
                if let Some(group) = group.take() {
                    group.finish(output)?;
                }
                previous.replace(key)?;
                group = Some(group_metadata::ClonedGroup::begin_child(
                    parent,
                    &child_metadata::Entry::values(step, row.fields(), columns),
                    false,
                    output,
                    ctx,
                )?);
            }
            row.key = PackedKey::Bytes(Box::default());
            let group = &mut group.as_mut().unwrap().group;
            if shuffled {
                row.ordinal = group.rows;
            }
            output.packed_row_ref(group, row)?;
        }
        if let Some(group) = group {
            ctx.check()?;
            group.finish(output)?;
        }
        Ok(())
    })();
    if let Some(span) = observation {
        span.finish_result(&result);
    }
    result
}
#[allow(clippy::too_many_arguments)]
fn assign(
    data: &Dataset,
    parent: &Group,
    columns: &[usize],
    groups: &[Allocation],
    step: usize,
    domain: &[u8; 32],
    shuffle: Option<(&str, usize)>,
    output: &mut impl RowSink,
    ctx: &Context,
) -> Result<()> {
    let mut observation = ctx.physical_attempt_from(
        crate::observation::physical::Kind::ExactMembership,
        [step + 1, 0],
        [ctx.physical_source, None, None, None],
    );
    let mut observed = crate::observation::physical::AllocationCounts {
        len: groups.len(),
        ..Default::default()
    };
    let result = (|| -> Result<()> {
        let mut scratch = AssignmentScratch::new(groups, shuffle.is_some(), Reservation::new(ctx))?;
        let mut order_ctx = ctx.clone();
        order_ctx.physical_source =
            ctx.physical_identity(crate::observation::physical::Kind::ExactMembership);
        let mut sorter = Sorter::new(
            &order_ctx,
            if shuffle.is_some() {
                SortOrder::GroupRandom
            } else {
                SortOrder::Key
            },
        );
        if let Some((seed, index)) = shuffle {
            for group in groups {
                scratch.domains.push(child_metadata::domain(
                    parent,
                    &child_metadata::Entry::allocation(step, &group.name),
                    seed,
                    index,
                    ctx,
                )?);
            }
        }
        let mut allocate = |source: &Dataset,
                            scope: &Group,
                            seed: [u8; 32],
                            observation: &mut Option<crate::observation::physical::Attempt>|
         -> Result<()> {
            scratch.reset_quota(scope.rows);
            #[cfg(target_os = "linux")]
            let mut quota = {
                let index = assignment::indexed::enabled()
                    && (cfg!(feature = "experimental-exact-quota-index")
                        || (ctx.auto_quota_index
                            && auto::use_quota_index(&scratch.quota, scope.rows)));
                assignment::indexed::QuotaCursor::new(&mut scratch.quota, index)
            };
            #[cfg(target_os = "linux")]
            if quota.is_indexed() {
                ctx.indexed_exact_quota_scope();
            }
            let mut remaining = scope.rows;
            let mut rng = Random::new(seed);
            for row in source.packed_rows(scope, ctx.max_record)? {
                let mut row = row?;
                #[cfg(target_os = "linux")]
                let index = quota.take(rng.below(remaining));
                #[cfg(not(target_os = "linux"))]
                let index = assignment::take_linear(&mut scratch.quota, rng.below(remaining));
                remaining -= 1;
                scratch.counts[index] += 1;
                observed.rows += 1;
                let capacity = if shuffle.is_some() {
                    let key = OperationKey::allocation(
                        index as u64,
                        &scratch.domains[index],
                        row.id,
                        Reservation::new(ctx),
                        &mut sorter,
                    )?;
                    key.install(&mut row, &mut sorter)?
                } else {
                    row.set_index_key(index as u64)?;
                    8
                };
                sorter.push_compact(row, capacity)?;
                if let Some(attempt) = observation {
                    attempt.rows_processed(observed.rows);
                }
            }
            Ok(())
        };
        if columns.is_empty() {
            allocate(data, parent, *domain, &mut observation)?;
        } else {
            let mut strata_ctx = ctx.physical_scope([step + 1, 0]);
            strata_ctx.physical_role = 1;
            let mut stratum_observation =
                strata_ctx.physical_span(crate::observation::physical::Kind::Stratification);
            let mut strata = DatasetWriter::new(&strata_ctx)?;
            let result = partition(
                data,
                parent,
                columns,
                step,
                &mut crate::observation::rows::ObservedRows::new(
                    &mut strata,
                    &mut stratum_observation,
                ),
                &strata_ctx,
                None,
                #[cfg(feature = "experimental-constant-partition")]
                None,
            )
            .and_then(|_| strata.finish());
            if let Some(span) = stratum_observation {
                span.finish_result(&result);
            }
            let strata = result?;
            if let Some(attempt) = &mut observation {
                attempt.source(strata.physical_source);
            }
            for stratum in strata.groups()? {
                let stratum = stratum?;
                let seed = random::json_domain(
                    &domain
                        .iter()
                        .map(|b| format!("{b:02x}"))
                        .collect::<String>(),
                    step as u64,
                    &stratum.lineage,
                )?;
                allocate(&strata, &stratum, seed, &mut observation)?;
            }
        }
        let sorted = sorter.finish()?;
        output.physical_input(ctx.physical_identity(sorted_physical_kind(
            &sorted,
            crate::observation::physical::Kind::ResidentSort,
        )));
        let mut reader = sorted.reusing();
        for (index, allocation) in groups.iter().enumerate() {
            let mut owned = group_metadata::ClonedGroup::begin_child(
                parent,
                &child_metadata::Entry::allocation(step, &allocation.name),
                false,
                output,
                ctx,
            )?;
            let group = &mut owned.group;
            for _ in 0..scratch.counts[index] {
                ctx.check()?;
                let row = reader.next()?.context("truncated assignment")?;
                row.key = PackedKey::Bytes(Box::default());
                if shuffle.is_some() {
                    row.ordinal = group.rows;
                }
                output.packed_row_ref(group, row)?;
            }
            ctx.check()?;
            owned.finish(output)?;
            observed.groups += 1;
            observed.empty_groups += u64::from(scratch.counts[index] == 0);
            if index < crate::observation::physical::MAX_MEMBERSHIPS {
                observed.memberships[index] = scratch.counts[index];
            }
        }
        Ok(())
    })();
    if let Some(attempt) = observation {
        attempt.allocation(
            result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ),
            observed,
        );
    }
    result
}

impl Prepared {
    pub fn execute(self) -> Result<Analysis> {
        self.execute_published()
            .map(output::PublishedAnalysis::into_analysis)
    }
    pub(crate) fn execute_published(self) -> Result<output::PublishedAnalysis> {
        self.job.validate_output()?;
        let mut observation = self.ctx.physical_scope([0, 0]);
        observation.physical_source = crate::observation::physical::identity(
            self.job.operations.len() + 1,
            crate::observation::physical::Kind::Serialize,
        );
        let span = observation.physical_span(crate::observation::physical::Kind::Materialize);
        let result = output::execute(&self);
        if let Some(span) = span {
            match &result {
                Ok(_) => span.finish(0),
                Err(error) => span.finish_error(error, 0),
            }
        }
        Ok(result?.with_analysis(self.analysis, &self.ctx))
    }
}

#[cfg(test)]
mod performance_tests {
    use super::*;

    #[cfg(target_os = "linux")]
    #[test]
    fn calculated_partition_observes_the_evaluator_as_the_sort_source() -> Result<()> {
        use crate::observation::{
            physical::{Fact, Kind},
            Status,
        };
        use std::sync::Mutex;

        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        let mut ctx = Context::new(
            &Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?
        .physical_scope([1, 0]);
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let columns = vec![Column::Name("upper_key".into())];
        let job = Job {
            calculated_columns: vec![CalculatedColumn {
                name: "upper_key".into(),
                expression: "UPPER(key)".into(),
            }],
            operations: vec![Operation::Partition {
                columns: columns.clone(),
            }],
            ..Default::default()
        };
        let mut writer = DatasetWriter::new(&ctx)?;
        let mut root = writer.begin(vec![], false);
        for (id, key) in ["a", "b"].into_iter().enumerate() {
            writer.row(
                &mut root,
                &Row {
                    id: id as u64,
                    ordinal: id as u64,
                    key: vec![],
                    fields: vec![key.into()],
                },
            )?;
        }
        writer.end(root)?;
        let data = writer.finish()?;
        ctx.physical_source = data.physical_source;
        let plan =
            calculation::Plan::prepare(&job, Some(&["key".into()]), 1, Reservation::new(&ctx))?;
        let (_, stats, _) = try_calculated_partition(&plan, &data, &columns, &job, &ctx)?;
        assert_eq!(stats.output_groups, 2);
        let facts = facts.lock().unwrap();
        let calculated = facts
            .iter()
            .find(|f| f.kind == Kind::Calculation && f.status == Status::Completed)
            .unwrap();
        assert_eq!(calculated.rows, 2);
        assert!(facts.iter().any(|f| f.kind == Kind::ResidentSort
            && f.status == Status::Completed
            && f.sources.contains(&Some(calculated.id))));
        Ok(())
    }

    #[test]
    fn partition_rejects_invalid_frames_deferred_by_balanced_boundaries() -> Result<()> {
        use std::{io::Write, sync::atomic::Ordering};

        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::new(&Resources::default(), cancel.clone(), Arc::new(|_| {}))?;
        let row = Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["valid".into()],
        };
        let mut bytes = Vec::new();
        write_row(&mut bytes, &row)?;
        let mut invalid_utf8 = bytes.clone();
        *invalid_utf8.last_mut().unwrap() = 0xff;
        let mut oversized = bytes.clone();
        oversized[32..40].copy_from_slice(&u64::MAX.to_le_bytes());
        for (tail, message) in [
            (&bytes[..bytes.len() - 1], "reading field"),
            (invalid_utf8.as_slice(), "invalid utf-8"),
            (oversized.as_slice(), "exceeds limit"),
        ] {
            let mut writer = DatasetWriter::new(&ctx)?;
            let mut parent = writer.begin(vec![], false);
            writer.row(&mut parent, &row)?;
            parent.rows = 2;
            writer.end(parent.clone())?;
            let mut data = writer.finish()?;
            Arc::get_mut(&mut data.data).unwrap().write_all(tail)?;
            let mut ranges = DatasetWriter::new(&ctx)?;
            shared_balanced_parent(&data, &parent, 2, 0, true, &mut ranges, &ctx)?;
            let ranges = ranges.finish()?;
            let final_range = ranges.groups()?.nth(1).unwrap()?;
            assert_eq!((final_range.offset, final_range.rows), (row.disk_len(), 1));

            let mut partitioned = DatasetWriter::new(&ctx)?;
            let error = partition(
                &data,
                &final_range,
                &[0],
                1,
                &mut partitioned,
                &ctx,
                None,
                #[cfg(feature = "experimental-constant-partition")]
                None,
            )
            .unwrap_err();
            assert!(format!("{error:#}").contains(message), "{error:#}");
            assert_eq!(partitioned.finish()?.groups, 0);
            let missing = Group {
                offset: data.data.len(),
                rows: 1,
                lineage: vec![],
                exact: true,
            };
            let error = data.rows(&missing, ctx.max_record)?.next_packed(None);
            assert!(matches!(error, Err(error) if error.to_string() == "truncated spool"));
            let mut eager = DatasetWriter::new(&ctx)?;
            assert!(shared_balanced_parent(&data, &parent, 2, 0, false, &mut eager, &ctx).is_err());

            cancel.store(true, Ordering::Relaxed);
            assert!(shared_balanced_parent(&data, &parent, 1, 0, true, &mut eager, &ctx).is_err());
            cancel.store(false, Ordering::Relaxed);
        }
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn grouping_observation_waits_for_input_rows() -> Result<()> {
        use crate::observation::{
            physical::{Fact, Kind},
            Status,
        };
        use std::sync::Mutex;
        struct Sink {
            facts: Arc<Mutex<Vec<Fact>>>,
            rows: u64,
        }
        impl RowSink for Sink {
            fn physical_input(&mut self, _: Option<u32>) {
                assert!(
                    !self
                        .facts
                        .lock()
                        .unwrap()
                        .iter()
                        .any(|f| f.kind == Kind::Grouping),
                    "wiring the downstream source must not start grouping"
                );
            }
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                Group {
                    offset: 0,
                    rows: 0,
                    lineage,
                    exact,
                }
            }
            fn row(&mut self, group: &mut Group, _: &Row) -> Result<()> {
                assert!(self
                    .facts
                    .lock()
                    .unwrap()
                    .iter()
                    .any(|f| f.kind == Kind::Grouping && f.status == Status::Active));
                group.rows += 1;
                self.rows += 1;
                Ok(())
            }
            fn end(&mut self, _: Group) -> Result<()> {
                Ok(())
            }
        }
        let facts = Arc::new(Mutex::new(Vec::new()));
        let mut ctx = Context::new(
            &Resources {
                grouping: chopper_core::Grouping::Sort,
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        sorter.push(Row {
            id: 0,
            ordinal: 0,
            key: b"a".to_vec(),
            fields: vec!["a".into()],
        })?;
        let parent = Group {
            offset: 0,
            rows: 1,
            lineage: vec![],
            exact: true,
        };
        let mut sink = Sink { facts, rows: 0 };
        emit_partition(sorter.finish()?, &parent, &[0], 0, false, &mut sink, &ctx)?;
        assert_eq!(sink.rows, 1);
        Ok(())
    }

    #[test]
    fn input_buffer_capacity_edges_and_exhausted_concurrent_owners() -> Result<()> {
        let capacity = 8192;
        {
            for limit in [capacity - 1, capacity, capacity + 1] {
                let workspace = Arc::new(Workspace::new(limit));
                let result = InputBuffer::new(
                    std::io::Cursor::new(b"abc"),
                    capacity,
                    Reservation::for_workspace(workspace.clone()),
                );
                assert_eq!(result.is_ok(), limit >= capacity);
                if let Ok(mut reader) = result {
                    assert_eq!(reader.reader.capacity(), capacity);
                    let mut bytes = Vec::new();
                    reader.read_to_end(&mut bytes)?;
                    assert_eq!(bytes, b"abc");
                    assert_eq!(workspace.used(), capacity as u64);
                    let denied = InputBuffer::new(
                        std::io::empty(),
                        capacity,
                        Reservation::for_workspace(workspace.clone()),
                    );
                    assert!(denied.is_err());
                    assert_eq!(workspace.used(), capacity as u64);
                    drop(reader);
                }
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn input_adapters_shared_admission_multiframe_and_error_release() -> Result<()> {
        let report = resource_contracts::input_adapters()?;
        assert_eq!(report["contract"], "input-adapter-resource-contracts-v1");
        assert_eq!(report["cases"].as_array().unwrap().len(), 3);
        assert_eq!(report["fixture_directory_removed"], true);
        Ok(())
    }

    #[test]
    fn buffered_source_coalesces_small_reads_and_keeps_its_grant_through_eof() -> Result<()> {
        use std::{cell::Cell, rc::Rc};
        struct Source {
            remaining: usize,
            calls: Rc<Cell<usize>>,
        }
        impl Read for Source {
            fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
                self.calls.set(self.calls.get() + 1);
                let size = out.len().min(self.remaining);
                out[..size].fill(42);
                self.remaining -= size;
                Ok(size)
            }
        }
        fn collect(mut source: impl Read) -> Result<Vec<u8>> {
            let mut result = Vec::new();
            let mut chunk = [0u8; 8192];
            loop {
                let size = source.read(&mut chunk)?;
                if size == 0 {
                    break;
                }
                result.extend_from_slice(&chunk[..size]);
            }
            Ok(result)
        }
        let calls = Rc::new(Cell::new(0));
        let source = || Source {
            remaining: 256 * 1024,
            calls: calls.clone(),
        };
        let expected = collect(source())?;
        assert_eq!(calls.get(), 33);
        calls.set(0);
        let capacity = 128 * 1024;
        let workspace = Arc::new(Workspace::new(capacity));
        let mut reader = InputBuffer::new(
            source(),
            capacity,
            Reservation::for_workspace(workspace.clone()),
        )?;
        assert_eq!(collect(&mut reader)?, expected);
        assert_eq!(calls.get(), 3);
        assert_eq!(workspace.used(), capacity as u64);
        drop(reader);
        assert_eq!(workspace.used(), 0);
        calls.set(0);
        let denied = Arc::new(Workspace::new(capacity - 1));
        assert!(InputBuffer::new(
            source(),
            capacity,
            Reservation::for_workspace(denied.clone())
        )
        .is_err());
        assert_eq!(calls.get(), 0);
        assert_eq!(denied.used(), 0);
        Ok(())
    }

    #[test]
    fn lineage_size_check_preserves_exact_serialized_budget_edges() -> Result<()> {
        let mut ctx = Context::new(
            &Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let parent = Group {
            offset: 0,
            rows: 0,
            exact: false,
            lineage: vec![json!({"operation":0,"values":["界", "\0\n\"\\"]})],
        };
        let step = json!({"operation":1,"allocation":"界".repeat(10000)});
        let mut expected = parent.lineage.clone();
        expected.push(step.clone());
        let size = serde_json::to_vec(&expected)?.len();
        for maximum in [size - 1, size, size + 1] {
            ctx.max_record = maximum;
            let result = child(&parent, step.clone(), &ctx);
            assert_eq!(result.is_ok(), maximum >= size);
            if let Ok(actual) = result {
                assert_eq!(actual, expected);
            }
            assert_eq!(parent.lineage.len(), 1);
        }
        Ok(())
    }

    #[test]
    fn partition_domain_cache_pressure_preserves_v1_keys() -> Result<()> {
        let ctx = Context::new(
            &Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let parent = Group {
            offset: 0,
            rows: 0,
            lineage: vec![json!({"operation":0,"part":2})],
            exact: false,
        };
        for limit in [0, 512, 65536] {
            let mut keys = PartitionKeys {
                #[cfg(feature = "experimental-constant-partition")]
                key_columns: None,
                parent: &parent,
                columns: vec![1, 0],
                step: 1,
                shuffle: Some(PartitionRandom::After {
                    seed: "cache-v1",
                    step: 2,
                }),
                domains: DomainCache::new(&ctx),
            };
            // A zero-capacity workspace forces every optional insertion to fail.
            keys.domains = DomainCache::for_test(&ctx, limit);
            let mut sorter = Sorter::new(&ctx, SortOrder::Key);
            for id in 0..100 {
                let fields = vec![format!("value-{}-界\0", id % 17), "\"\n".into()];
                let mut expected = random::tuple_key(&fields, &[1, 0]);
                let lineage = child(
                    &parent,
                    json!({"operation":1,"values":[fields[1],fields[0]]}),
                    &ctx,
                )?;
                let domain = random::domain("cache-v1", 2, &serde_json::to_string(&lineage)?);
                expected.extend_from_slice(&random::block(&domain, id, 0)[..16]);
                expected.extend_from_slice(&domain);
                assert_eq!(
                    keys.key(id, FieldViews::owned(&fields), &ctx, &mut sorter)?
                        .bytes,
                    expected
                );
            }
        }
        Ok(())
    }

    #[test]
    fn ingestion_parser_reservations_release_on_success_error_and_cancellation() -> Result<()> {
        for plain in [false, true] {
            for cancelled in [false, true] {
                for malformed in [false, true] {
                    let job = Job {
                        random_seed: Some("parser-budget".into()),
                        operations: if plain {
                            vec![]
                        } else {
                            vec![serde_json::from_value(json!({
                                "type": "shuffle", "strategy": "uniform"
                            }))?]
                        },
                        ..Job::default()
                    };
                    let cancellation = Arc::new(AtomicBool::new(false));
                    let ctx = Context::new(&job.resources, cancellation.clone(), Arc::new(|_| {}))?;
                    cancellation.store(cancelled, std::sync::atomic::Ordering::Relaxed);
                    let input = format!(
                        "id,text\n0,{}\n{}",
                        "界".repeat(100_000),
                        if malformed {
                            "1,\"unterminated"
                        } else {
                            "1,small\n"
                        }
                    );
                    let result = ingest(Box::new(input.as_bytes()), &job, &ctx);
                    assert_eq!(result.is_err(), malformed || cancelled);
                    if let Ok(ingested) = &result {
                        let diagnostics = ctx.diagnostics();
                        assert_eq!(
                            diagnostics["workspace_reserved_bytes"],
                            ingested.analysis.preview.reserved_bytes()
                                + ingested.analysis.warnings.reserved_bytes()
                                + ingested.analysis.timings.reserved_bytes()
                                + ingested.analysis.diagnostics.reserved_bytes()
                                + ingested.analysis.text_reserved_bytes()
                                + ingested.analysis.stages.reserved_bytes()
                                + ingested.analysis.column_values.reserved_bytes()
                                + diagnostics["temporary_path_reserved_bytes"]
                                    .as_u64()
                                    .unwrap()
                                + ctx.directory_reserved_bytes()
                                + ingested
                                    .analysis
                                    .header
                                    .as_ref()
                                    .map_or(0, |fields| fields.reserved_bytes())
                        );
                    }
                    drop(result);
                    assert_eq!(
                        ctx.diagnostics()["workspace_reserved_bytes"],
                        ctx.directory_reserved_bytes()
                    );
                    assert_eq!(ctx.used(), 0);
                }
            }
        }
        Ok(())
    }

    #[test]
    fn compact_partition_matches_owned_for_selected_columns_and_shuffle() -> Result<()> {
        let ctx = Context::new(
            &Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let parent = Group {
            offset: 0,
            rows: 4,
            lineage: vec![],
            exact: false,
        };
        for shuffled in [false, true] {
            for wide in [false, true] {
                let rows: Vec<_> = (0..4)
                    .map(|id| {
                        let fields = vec![
                            if id < 2 {
                                "a\0".into()
                            } else {
                                "界\n\"".into()
                            },
                            if wide {
                                "x".repeat(10000)
                            } else {
                                String::new()
                            },
                            "selected first".into(),
                        ];
                        let mut key = random::tuple_key(&fields, &[2, 0]);
                        if shuffled {
                            key.extend_from_slice(&[0; 48]);
                        }
                        Row {
                            id,
                            ordinal: 10 + id,
                            fields,
                            key,
                        }
                    })
                    .collect();
                let mut reference = None;
                for packed in [false, true] {
                    let mut writer = DatasetWriter::new(&ctx)?;
                    if packed {
                        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
                        for row in &rows {
                            sorter.push(row.clone())?;
                        }
                        emit_partition(
                            sorter.finish()?,
                            &parent,
                            &[2, 0],
                            3,
                            shuffled,
                            &mut writer,
                            &ctx,
                        )?;
                    } else {
                        for pair in rows.chunks(2) {
                            let values = [&pair[0].fields[2], &pair[0].fields[0]];
                            let mut group = writer.begin(
                                child(&parent, json!({"operation":3,"values":values}), &ctx)?,
                                false,
                            );
                            for (index, row) in pair.iter().enumerate() {
                                let mut row = row.clone();
                                row.key.clear();
                                if shuffled {
                                    row.ordinal = index as u64;
                                }
                                writer.row(&mut group, &row)?;
                            }
                            writer.end(group)?;
                        }
                    }
                    let data = writer.finish()?;
                    let mut actual = Vec::new();
                    for group in data.groups()? {
                        let group = group?;
                        actual.extend_from_slice(serde_json::to_string(&group)?.as_bytes());
                        for (index, row) in data.rows(&group, ctx.max_record)?.enumerate() {
                            let row = row?;
                            assert!(row.key.is_empty());
                            assert_eq!(
                                row.ordinal,
                                if shuffled { index as u64 } else { 10 + row.id }
                            );
                            write_row(&mut actual, &row)?;
                        }
                    }
                    if let Some(reference) = &reference {
                        assert_eq!(&actual, reference);
                    } else {
                        reference = Some(actual);
                    }
                }
            }
        }
        Ok(())
    }

    #[test]
    fn intermediate_balanced_groups_share_the_original_snapshot() -> Result<()> {
        let job = Job {
            random_seed: Some("test".into()),
            operations: vec![Operation::Balanced { files: 2 }],
            ..Job::default()
        };
        let ctx = Context::new(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let input = format!(
            "id,text\n{}",
            (0..1000)
                .map(|i| format!("{i},{}\n", "x".repeat(100)))
                .collect::<String>()
        );
        let original = ingest(Box::new(input.as_bytes()), &job, &ctx)?;
        let before = ctx.used();
        let divided = apply(
            &original.dataset,
            &job.operations[0],
            0,
            &job,
            &original.analysis,
            &ctx,
        )?;
        assert!(Arc::ptr_eq(&original.dataset.data, &divided.data));
        assert!(
            ctx.used() - before < 4096,
            "only the group catalog should be written"
        );
        let mut ids = Vec::new();
        for group in divided.groups()? {
            let group = group?;
            assert_eq!(group.rows, 500);
            ids.extend(
                divided
                    .rows(&group, ctx.max_record)?
                    .map(|row| row.unwrap().id),
            );
        }
        assert_eq!(ids, (0..1000).collect::<Vec<_>>());
        Ok(())
    }
}

#[cfg(all(test, not(target_os = "wasi")))]
mod terminal_controls;
