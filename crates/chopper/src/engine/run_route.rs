//! Run route selection and ownership of the prerequisites for dispatch.
use super::{
    auto, direct, output, streaming, uniform, AutoObservations, AutoPlan, PreviewObservations,
    RunJob,
};
use crate::{
    observation::physical,
    resources::MemoryPool,
    storage::{Context, Notify},
};
use anyhow::Result;
use chopper_core::{Job, Operation};
use std::sync::{atomic::AtomicBool, Arc};

// Keep the admitted Context inline through dispatch.
#[allow(clippy::large_enum_variant)]
pub(super) enum RunRoute {
    Direct {
        mode: direct::Plan,
        context: Context,
    },
    Retained(RetainedRun),
}

pub(super) struct RetainedRun {
    publication: RetainedPublication,
    destination: output::RunDestination,
    unobserved: bool,
    direct_preflight_fallback: bool,
}

#[derive(Clone, Copy)]
enum RetainedPublication {
    Snapshot,
    PrivateTerminal,
    NativeMerge(usize),
    RetainedExact,
}

impl RetainedPublication {
    fn select(job: &Job, pool: &MemoryPool, calculates: bool, observed: bool) -> Self {
        if calculates {
            return if !observed && large_calculation_direct_eligible(job) {
                Self::PrivateTerminal
            } else {
                Self::Snapshot
            };
        }
        if !observed {
            if let Some(fan_in) = auto::native_terminal_merge(job, pool) {
                return Self::NativeMerge(fan_in);
            }
            if auto::native_retained_exact(job, pool) {
                return Self::RetainedExact;
            }
        }
        if terminal_direct_eligible(job) || (!observed && native_shuffle_direct_eligible(job)) {
            Self::PrivateTerminal
        } else {
            Self::Snapshot
        }
    }

    fn is_terminal(self) -> bool {
        !matches!(self, Self::Snapshot)
    }

    fn merge_fan_in(self) -> Option<usize> {
        match self {
            Self::NativeMerge(fan_in) => Some(fan_in),
            _ => None,
        }
    }

    fn try_retained_exact(self) -> bool {
        matches!(self, Self::RetainedExact)
    }
}

impl RunRoute {
    pub(super) fn select(
        job: &RunJob,
        cancel: &Arc<AtomicBool>,
        notify: &Notify,
        pool: &Arc<MemoryPool>,
        observed: bool,
    ) -> Result<Self> {
        #[cfg(not(target_os = "wasi"))]
        let destination = output::RunDestination::preflight(job)?;
        #[cfg(target_os = "wasi")]
        let destination = output::RunDestination::Unchecked;
        let calculates = !job.calculated_columns.is_empty();
        let candidate = if calculates {
            None
        } else if job.operations.is_empty() {
            Some(direct::Plan::Streaming)
        } else if observed {
            None
        } else {
            direct::select(job, pool)
        };
        if let Some(mode) = candidate {
            #[cfg(target_os = "wasi")]
            job.validate_output()?;
            let context = Context::with_run_limits(
                &job.resources,
                cancel.clone(),
                notify.clone(),
                pool.clone(),
                if output::parallel_direct_compression(job) {
                    usize::MAX
                } else {
                    1
                },
                mode.memory_targets(),
                job.memory_credit(pool),
            )?;
            if mode.ready(&context) {
                *context.run_destination() = destination;
                return Ok(Self::Direct { mode, context });
            }
            // The tentative context drops before retained selection. The
            // destination witness still belongs to this Run and intake has yet to start.
        }
        Ok(Self::Retained(RetainedRun {
            publication: RetainedPublication::select(job, pool, calculates, observed),
            destination,
            unobserved: !observed,
            direct_preflight_fallback: candidate.is_some(),
        }))
    }

    pub(super) fn report(
        &self,
        job: &RunJob,
        pool: &MemoryPool,
        hint: Option<AutoObservations>,
        preview: Option<PreviewObservations>,
    ) -> AutoPlan {
        let job_credit = job.memory_credit(pool);
        match self {
            Self::Direct { mode, .. } => {
                AutoPlan::start(job, pool, hint, mode.route(), preview, job_credit)
            }
            Self::Retained(run) => {
                let route = if run.publication.is_terminal() {
                    auto::Route::PrivateTerminal
                } else {
                    auto::Route::Snapshot
                };
                let mut report = AutoPlan::start(job, pool, hint, route, preview, job_credit);
                report.set_native_merge_fan_in(run.publication.merge_fan_in());
                report.try_retained_exact = run.publication.try_retained_exact();
                report.direct_preflight_fallback = run.direct_preflight_fallback;
                report
            }
        }
    }
}

pub(super) enum ProcessingMode<'a> {
    Prepare,
    Run(RetainedRun, &'a AutoPlan),
}

impl ProcessingMode<'_> {
    pub(super) fn unobserved_run(&self) -> bool {
        matches!(self, Self::Run(run, _) if run.unobserved)
    }

    pub(super) fn context(
        self,
        job: &RunJob,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        pool: Arc<MemoryPool>,
        physical: Option<physical::Sink>,
    ) -> Result<Context> {
        let (worker_limit, memory_targets) = match &self {
            Self::Prepare => (usize::MAX, [256, 256]),
            Self::Run(_, plan) => (plan.automatic_worker_limit(), plan.memory_targets_mb()),
        };
        let job_credit = job.memory_credit(&pool);
        let mut context = Context::with_run_limits(
            &job.resources,
            cancel,
            notify,
            pool,
            worker_limit,
            memory_targets,
            job_credit,
        )?;
        context.physical = physical;
        if let Self::Run(run, _) = self {
            *context.run_destination() = run.destination;
            context.direct_terminal_output = run.publication.is_terminal();
            context.auto_run = true;
            context.auto_quota_index = matches!(job.operations.as_slice(), [Operation::Assign { strata, .. }] if strata.is_empty());
            context.auto_merge_ceiling = run.publication.merge_fan_in();
            context.auto_retained_exact = run.publication.try_retained_exact();
            context.auto_final_writers = context.auto_retained_exact;
        }
        Ok(context)
    }
}

fn large_calculation_direct_eligible(job: &Job) -> bool {
    // The measured benefit came from avoiding a large serialized snapshot.
    // Keep the existing path for smaller, evaluator-heavy exports.
    const MINIMUM_SOURCE_BYTES: u64 = 128 * 1024 * 1024;
    cfg!(target_os = "linux")
        && job.operations.is_empty()
        && job.compression == chopper_core::Compression::None
        && std::fs::metadata(&job.input)
            .is_ok_and(|source| source.is_file() && source.len() >= MINIMUM_SOURCE_BYTES)
}

fn native_shuffle_direct_eligible(job: &Job) -> bool {
    cfg!(all(
        feature = "experimental-terminal-shuffle",
        not(target_os = "wasi")
    )) && job.compression == chopper_core::Compression::None
        && (matches!(job.operations.as_slice(), [Operation::Shuffle { .. }])
            || matches!(job.operations.as_slice(), [shuffle, Operation::Partition { .. }] if uniform(shuffle)))
}

fn terminal_direct_eligible(job: &Job) -> bool {
    job.compression == chopper_core::Compression::None
        && (matches!(job.operations.as_slice(), [Operation::Balanced { .. }])
            || (cfg!(feature = "experimental-terminal-shuffle")
                && matches!(job.operations.as_slice(), [shuffle, Operation::Balanced { .. }] if uniform(shuffle)))
            || (cfg!(all(
                feature = "experimental-terminal-routing",
                not(target_os = "wasi")
            )) && matches!(job.operations.as_slice(), [operation] if streaming::eligible(operation) || matches!(operation, Operation::Partition { .. }) || matches!(operation, Operation::Assign { strata, .. } if !strata.is_empty()))))
}

pub(super) fn hosted_partition_shuffle_buffer(
    job: &Job,
    ctx: &Context,
    minimum_csv_bytes: u64,
) -> Option<usize> {
    const MIB: u64 = 1024 * 1024;
    const MINIMUM_CSV_BYTES: u64 = 96 * MIB;
    const WRITE_BUFFER: u64 = 512 * 1024;
    if !ctx.auto_run
        || minimum_csv_bytes < MINIMUM_CSV_BYTES
        || !job.calculated_columns.is_empty()
        || job.compression != chopper_core::Compression::None
        || job.resources.grouping != chopper_core::Grouping::Auto
        || !job.output_csv.encoding.eq_ignore_ascii_case("utf-8")
        || !matches!(
            job.operations.as_slice(),
            [Operation::Partition { .. }, shuffle] | [shuffle, Operation::Partition { .. }]
                if uniform(shuffle)
        )
    {
        return None;
    }
    let buffer = job.limits.bytes.unwrap_or(WRITE_BUFFER).min(WRITE_BUFFER);
    // Check after the sort has opened its final readers. Leave room for the
    // current row, encoder, and output metadata while the writer is live.
    let headroom = buffer + 2 * ctx.max_record as u64 + MIB;
    (ctx.working_headroom() >= headroom).then_some(buffer as usize)
}

#[cfg(all(
    test,
    target_os = "linux",
    not(feature = "experimental-counted-balanced")
))]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn direct_preflight_decline_retains_destination_and_releases_context() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let output = dir.path().join("result");
        let temp = dir.path().join("temp");
        fs::File::create(&input)?.set_len(2048 * 1024 * 1024)?;
        fs::create_dir(&output)?;
        fs::create_dir(&temp)?;
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            operations: vec![Operation::Balanced { files: 2 }],
            resources: chopper_core::Resources {
                memory_mb: 256.into(),
                workers: 1,
                temp_dir: Some(temp.to_string_lossy().into_owned()),
                ..Default::default()
            },
            ..Job::default()
        };
        // Selecting the candidate can use the full shared headroom. Creating
        // its Context admits the job path, taking it below that same threshold.
        let pool = Arc::new(MemoryPool::new(auto::NATIVE_DIRECT_HEADROOM_BYTES));
        let original = dir.path().join("original-result");
        let _hook = crate::storage::context_test_hook::install({
            let output = output.clone();
            let original = original.clone();
            move |_, _| {
                fs::rename(&output, original).expect("move witnessed destination");
                fs::create_dir(output).expect("create replacement destination");
            }
        });
        let cancel = Arc::new(AtomicBool::new(false));
        let notify: Notify = Arc::new(|_| {});
        let job = RunJob::from(job);
        let route = RunRoute::select(&job, &cancel, &notify, &pool, false)?;
        let plan = route.report(&job, &pool, None, None);
        let report = serde_json::to_value(plan)?;
        let RunRoute::Retained(run) = route else {
            panic!("direct Context should lose eligibility");
        };
        assert!(matches!(
            run.destination,
            output::RunDestination::Existing(_)
        ));
        assert_eq!(report["physical_plan"], "private_terminal");
        assert_eq!(report["direct_preflight_fallback"], true);
        assert_eq!(pool.reservation_counts().0, 0);
        assert_eq!(fs::read_dir(&temp)?.count(), 0);

        let context =
            ProcessingMode::Run(run, &plan).context(&job, cancel, notify, pool.clone(), None)?;
        let error = output::PlanWriter::direct_grouped(&job, None, &context)
            .err()
            .expect("retained staging must reject a replacement destination");
        assert!(format!("{error:#}").contains("output destination changed during Run"));
        drop(context);
        assert_eq!(pool.reservation_counts().0, 0);
        for path in [original, output, temp] {
            assert_eq!(fs::read_dir(path)?.count(), 0);
        }
        Ok(())
    }
}
