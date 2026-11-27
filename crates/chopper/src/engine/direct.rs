//! Direct serialization, with an opt-in validated count pass for Balanced.
use super::*;
use crate::observation::{Observer, Status};
mod counted_partition;
mod fanout;
pub(super) use fanout::Writers;
pub(super) fn writer_capacity(job: &Job) -> Option<usize> {
    fanout::writer_capacity(job)
}
pub(super) fn partition_eligible(job: &Job) -> bool {
    fanout::partition_eligible(job)
}
pub(super) fn chain_eligible(job: &Job) -> bool {
    fanout::chains::eligible(job)
}
pub(super) fn fanout_eligible(job: &Job) -> bool {
    fanout::eligible(job)
}

fn counted_output_eligible(job: &Job) -> bool {
    job.compression == chopper_core::Compression::None
        || cfg!(feature = "experimental-counted-codec-balanced")
}

fn counted_partition_eligible(job: &Job) -> bool {
    cfg!(feature = "experimental-counted-partition-balanced")
        && matches!(
            job.operations.as_slice(),
            [Operation::Partition { .. }, Operation::Balanced { .. }]
        )
        && writer_capacity(job).is_some_and(|limit| job.resources.max_files <= limit as u64)
}

pub(super) fn counted_eligible(job: &Job) -> bool {
    let partition = counted_partition_eligible(job);
    if !cfg!(all(
        feature = "experimental-counted-balanced",
        not(target_os = "wasi")
    )) || !counted_output_eligible(job)
        || !job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        || !(partition || matches!(job.operations.as_slice(), [Operation::Balanced { .. }]))
    {
        return false;
    }
    input_signature(job).is_some_and(|kind| kind.is_none())
}

fn input_signature(job: &Job) -> Option<Option<crate::observation::physical::Kind>> {
    if !std::fs::metadata(&job.input).ok()?.is_file() {
        return None;
    }
    let mut file = File::open(&job.input).ok()?;
    let mut magic = [0; 4];
    let read = file.read(&mut magic).ok()?;
    if is_removed_compression(magic, read) {
        return None;
    }
    Some(input_kind(magic, read))
}

pub(super) fn native_input_hint(job: &Job) -> Option<u64> {
    input_signature(job)?.is_none().then_some(())?;
    Some(std::fs::metadata(&job.input).ok()?.len())
}

#[derive(Clone, Copy)]
pub(super) enum Plan {
    Streaming,
    BatchedFanout,
    Counted { partition: bool, automatic: bool },
    Fanout { chain: bool, automatic: bool },
}

impl Plan {
    pub(super) fn route(self) -> auto::Route {
        match self {
            Self::Streaming => auto::Route::Streaming,
            Self::Counted { .. } => auto::Route::Counted,
            Self::Fanout { .. } | Self::BatchedFanout => auto::Route::BoundedWriters,
        }
    }
    pub(super) fn memory_targets(self) -> [u64; 2] {
        if matches!(self, Self::BatchedFanout) {
            [1024, 256]
        } else {
            [256, 256]
        }
    }

    pub(super) fn ready(self, ctx: &Context) -> bool {
        const MIB: usize = 1024 * 1024;
        let (memory, headroom) = match self {
            Self::BatchedFanout => (1024 * MIB, 511 * MIB as u64),
            Self::Fanout {
                automatic: true, ..
            }
            | Self::Counted {
                automatic: true, ..
            } => (
                auto::NATIVE_DIRECT_MIN_MEMORY_MB as usize * MIB,
                auto::NATIVE_DIRECT_HEADROOM_BYTES,
            ),
            _ => return true,
        };
        ctx.memory >= memory && ctx.working_headroom() >= headroom
    }

    pub(super) fn strategy(self) -> Option<auto::Strategy> {
        match self {
            Self::Streaming => None,
            Self::Counted {
                partition: true, ..
            } => Some(auto::Strategy::CountedPartitionBalanced),
            Self::Counted {
                partition: false, ..
            } => Some(auto::Strategy::CountedBalanced),
            Self::Fanout { chain: true, .. } => Some(auto::Strategy::BoundedWriterChain),
            Self::Fanout { chain: false, .. } => Some(auto::Strategy::BoundedFinalWriters),
            Self::BatchedFanout => Some(auto::Strategy::BatchedFinalSync),
        }
    }
}

pub(super) fn select(job: &Job, pool: &crate::resources::MemoryPool) -> Option<Plan> {
    if job.operations.is_empty() {
        return Some(Plan::Streaming);
    }
    if counted_eligible(job) {
        return Some(Plan::Counted {
            partition: counted_partition_eligible(job),
            automatic: false,
        });
    }
    if fanout_eligible(job) || chain_eligible(job) {
        return Some(Plan::Fanout {
            chain: chain_eligible(job),
            automatic: false,
        });
    }

    auto::native_direct_candidate(job, pool)
}

struct Counted {
    rows: u64,
    header: Option<Header>,
    digest: Option<blake3::Hash>,
    partitions: Option<counted_partition::Counts>,
}

fn count(source: &mut dyn Read, job: &Job, ctx: &Context, partition: bool) -> Result<Counted> {
    let input = Intake::new(
        source,
        &job.input_csv,
        ctx.max_record,
        Reservation::new(ctx),
    )?;
    records::with_dialect!(input, &job.input_dialect, |input| count_records(
        input, job, ctx, partition,
    ))
}

fn count_records(
    mut input: Intake<impl records::Records>,
    job: &Job,
    ctx: &Context,
    partition: bool,
) -> Result<Counted> {
    let header = header::read(&mut input)?;
    // Singleton Balanced needs only the count. Partition also needs the
    // first-pass digest to verify the rows used to compute per-key quotas.
    let mut digest = partition
        .then(|| crate::digest::LogicalDigest::reserved(Reservation::new(ctx)))
        .transpose()?;
    let mut rows = 0u64;
    let mut partitions = None;
    while input.next_compact(|| ctx.check(), |memory, bytes| memory.resize(bytes))? {
        if let Some(digest) = &mut digest {
            digest.compact_record(input.compact());
        }
        if partition {
            if partitions.is_none() {
                partitions = Some(counted_partition::Counts::new(
                    job,
                    header.as_ref(),
                    input.columns(),
                    ctx,
                )?);
            }
            partitions
                .as_mut()
                .unwrap()
                .count(input.compact().fields())?;
        }
        rows = rows.checked_add(1).context("row count overflow")?;
        if rows.is_multiple_of(65536) {
            ctx.event("Counting and validating CSV", rows)?;
        }
    }
    ctx.check()?;
    if partition {
        if partitions.is_none() {
            partitions = Some(counted_partition::Counts::new(
                job,
                header.as_ref(),
                input.columns(),
                ctx,
            )?);
        }
        partitions.as_ref().unwrap().validate()?;
    }
    Ok(Counted {
        rows,
        header,
        digest: digest.map(crate::digest::LogicalDigest::finalize),
        partitions,
    })
}

pub(super) fn run(
    job: RunJob,
    mut ctx: Context,
    (sink, physical): (
        Option<crate::observation::Sink<'_>>,
        Option<crate::observation::physical::Sink>,
    ),
    plan: Plan,
    started: std::time::Instant,
) -> Result<output::PublishedAnalysis> {
    let fanout_job = matches!(
        plan,
        Plan::Fanout { chain: false, .. } | Plan::BatchedFanout
    );
    let chain_job = matches!(plan, Plan::Fanout { chain: true, .. });
    let counted_job = matches!(plan, Plan::Counted { .. });
    let counted_partition = matches!(
        plan,
        Plan::Counted {
            partition: true,
            ..
        }
    );
    ensure!(
        !counted_job
            || (counted_output_eligible(&job)
                && (counted_partition
                    || matches!(job.operations.as_slice(), [Operation::Balanced { .. }]))),
        "direct count requires one eligible Balanced operation"
    );
    ctx.physical = physical;
    ctx.auto_final_writers = matches!(
        plan,
        Plan::Fanout {
            automatic: true,
            ..
        } | Plan::Counted {
            partition: true,
            automatic: true,
            ..
        }
    );
    ctx.auto_final_sync = matches!(plan, Plan::BatchedFanout);
    ctx.auto_final_writers |= ctx.auto_final_sync;
    let mut observer = sink.and_then(|sink| Observer::new(&ctx, sink));
    let job = PreparedJob::admit(job, Reservation::new(&ctx))?;
    ctx.event(
        if counted_job {
            "Reading and validating CSV"
        } else {
            "Reading and writing CSV"
        },
        0,
    )?;
    observe(&mut observer, false, Status::Active, 0, true);
    let before = std::fs::metadata(&job.input).context("open input")?;
    ensure!(before.is_file(), "input must be a regular file");
    let ingest_started = std::time::Instant::now();
    let mut counted = if counted_job {
        ctx.event("Counting and validating CSV", 0)?;
        let result = with_input(&job, Reservation::new(&ctx), |mut source| {
            count(source.as_mut(), &job, &ctx, counted_partition)
        })?;
        if let [Operation::Balanced { files }] = job.operations.as_slice() {
            ensure!(
                result.rows >= *files,
                "cannot split {} rows into {files} nonempty balanced groups",
                result.rows
            );
        }
        let after_count = std::fs::metadata(&job.input)?;
        ensure!(
            before.len() == after_count.len() && before.modified()? == after_count.modified()?,
            "input changed while counting; retry with a stable source"
        );
        Some(result)
    } else {
        None
    };
    if counted.is_some() {
        ctx.event("Writing counted Balanced CSV", 0)?;
    }
    let (mut analysis, publication) =
        with_input_observed(&job, Reservation::new(&ctx), &ctx, |source, input_ctx| {
            consume(
                source,
                &job,
                input_ctx,
                &mut observer,
                counted.as_mut(),
                fanout_job,
                chain_job,
            )
        })?;
    // Release first-pass metadata and any Partition proof after comparison.
    drop(counted);
    let after = std::fs::metadata(&job.input)?;
    ensure!(
        before.len() == after.len() && before.modified()? == after.modified()?,
        "input changed while reading; retry with a stable source"
    );
    observe(&mut observer, false, Status::Completed, analysis.rows, true);
    let mut timings = timings::Builder::new(Reservation::new(&ctx));
    timings.insert(
        "ingest_and_fused_operations",
        ingest_started.elapsed().as_secs_f64(),
    )?;
    timings.insert("remaining_operations", 0.0)?;
    timings.insert("final_serialization", 0.0)?;
    analysis.temp_bytes = ctx.used();
    analysis.peak_temp_bytes = ctx.peak();
    analysis.timings = timings.finish()?;
    analysis.analysis_seconds = started.elapsed().as_secs_f64();
    analysis.warnings = warnings::build(&job, &analysis, Reservation::new(&ctx))?;
    analysis.diagnostics = Diagnostics::analysis(&ctx, &job, &analysis)?;
    if counted_job || fanout_job || chain_job {
        ctx.event("Finalizing direct terminal output", analysis.rows)?;
    }
    let receipt = publication
        .publish(&job, &analysis, &ctx)
        .map_err(|error| observe_error(&mut observer, true, analysis.rows, error))?;
    observe(&mut observer, true, Status::Completed, analysis.rows, true);
    Ok(receipt.with_analysis(analysis, &ctx))
}

fn consume(
    source: &mut dyn Read,
    job: &Job,
    ctx: &Context,
    observer: &mut Option<Observer<'_>>,
    counted: Option<&mut Counted>,
    fanout_job: bool,
    chain_job: bool,
) -> Result<(Analysis, output::DirectPublication)> {
    let input = Intake::new(
        source,
        &job.input_csv,
        ctx.max_record,
        Reservation::new(ctx),
    )
    .map_err(|error| {
        // Input-buffer denial precedes decoder observation, as before.
        if error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_some()
        {
            error
        } else {
            observe_error(observer, false, 0, error)
        }
    })?;
    records::with_dialect!(input, &job.input_dialect, |input| consume_records(
        input, job, ctx, observer, counted, fanout_job, chain_job,
    ))
}

fn consume_records(
    mut input: Intake<impl records::Records>,
    job: &Job,
    ctx: &Context,
    observer: &mut Option<Observer<'_>>,
    mut counted: Option<&mut Counted>,
    fanout_job: bool,
    chain_job: bool,
) -> Result<(Analysis, output::DirectPublication)> {
    let seed = AnalysisText::copy(job.random_seed.as_deref().unwrap(), Reservation::new(ctx))?;
    let mut stages = Stages::new(job.operations.len(), Reservation::new(ctx))?;
    let header =
        header::read(&mut input).map_err(|error| observe_error(observer, false, 0, error))?;
    if let Some(proof) = counted.as_deref() {
        ensure!(
            header.as_deref() == proof.header.as_deref(),
            "input header changed after counting"
        );
    }
    let mut counted_partition = counted
        .as_mut()
        .and_then(|proof| proof.partitions.take())
        .map(|counts| counted_partition::Emit::new(counts, job, header.as_ref(), ctx))
        .transpose()?;
    let counted = counted.as_deref();
    let balanced_rows = counted
        .filter(|_| counted_partition.is_none())
        .map(|proof| proof.rows);
    let files = if let Some(count) = balanced_rows {
        let Operation::Balanced { files } = job.operations[0] else {
            unreachable!()
        };
        stages.push(StageStats {
            operation: 1,
            input_groups: 1,
            output_groups: files,
            smallest_group: count / files,
            largest_group: count.div_ceil(files),
            empty_groups: 0,
        })?;
        files
    } else {
        1
    };
    observe(observer, true, Status::Active, 0, true);
    let mut fanout = None;
    let mut chain = None;
    let mut writer = if fanout_job || chain_job || counted_partition.is_some() {
        None
    } else {
        Some(
            (if balanced_rows.is_some() {
                output::PlanWriter::direct_grouped(job, header.as_ref(), ctx)
            } else {
                output::PlanWriter::direct(job, header.as_deref(), ctx)
            })
            .map_err(|error| observe_error(observer, true, 0, error))?,
        )
    };
    let lineage = |part| {
        if balanced_rows.is_some() {
            vec![serde_json::json!({"operation":0,"part":part})]
        } else {
            vec![]
        }
    };
    let mut part = 1;
    let mut rows = 0u64;
    let quota = |part| {
        balanced_rows.map_or(u64::MAX, |count| {
            count / files + u64::from(part <= count % files)
        })
    };
    let mut group = Group {
        offset: 0,
        rows: 0,
        lineage: lineage(part),
        exact: balanced_rows.is_some(),
    };
    let mut digest = crate::digest::LogicalDigest::reserved(Reservation::new(ctx))?;
    let mut preview = preview::Builder::new(Reservation::new(ctx));
    let mut column_values = column_summaries::Builder::new(Reservation::new(ctx));
    let mut largest = 0;
    loop {
        let mut check_failed = false;
        let present = input
            .next_owned(|| ctx.check().inspect_err(|_| check_failed = true))
            .map_err(|error| {
                // Execution cancellation at this checkpoint previously propagated
                // without fabricating an additional input observation.
                if check_failed {
                    error
                } else {
                    observe_error(observer, false, group.rows, error)
                }
            })?;
        if !present {
            break;
        }
        if let Some(counted) = counted {
            ensure!(
                rows < counted.rows,
                "input row count changed after counting"
            );
            if balanced_rows.is_some() && group.rows == quota(part) {
                writer.as_mut().unwrap().end(group)?;
                part += 1;
                group = writer.as_ref().unwrap().begin(lineage(part), true);
            }
        }
        #[cfg(feature = "resource-contract-tests")]
        crate::guide_test_control::checkpoint("direct-row");
        let views = FieldViews::owned(input.owned());
        column_values.observe(job, header.as_deref(), views.clone())?;
        let size = views.clone().map(str::len).sum();
        largest = largest.max(size as u64);
        preview.consider(views.clone(), size)?;
        digest.record(input.owned());
        if let Some(partition) = &mut counted_partition {
            partition.row(rows, views)?;
            group.rows += 1;
        } else if chain_job {
            if chain.is_none() {
                chain = Some(fanout::chains::Chains::new(
                    job,
                    header.as_ref(),
                    input.columns(),
                    ctx,
                )?);
            }
            chain.as_mut().unwrap().row(rows, views)?;
            group.rows += 1;
        } else if fanout_job {
            if fanout.is_none() {
                fanout = Some(fanout::Fanout::new(
                    job,
                    header.as_ref(),
                    input.columns(),
                    ctx,
                )?);
            }
            fanout.as_mut().unwrap().row(rows, views)?;
            group.rows += 1;
        } else {
            input.consume_owned(|fields| {
                let row = Row {
                    id: rows,
                    ordinal: group.rows,
                    key: vec![],
                    fields: std::mem::take(fields),
                };
                writer
                    .as_mut()
                    .unwrap()
                    .row(&mut group, &row)
                    .map_err(|error| observe_error(observer, true, group.rows, error))?;
                *fields = row.fields;
                Ok(())
            })?;
        }
        rows += 1;
        if rows.is_multiple_of(4096) {
            observe(observer, false, Status::Active, rows, false);
            observe(observer, true, Status::Active, rows, false);
        }
    }
    let digest = digest.finalize();
    if let Some(counted) = counted {
        if let Some(expected) = counted.digest {
            ensure!(
                rows == counted.rows && digest == expected,
                "input content changed after counting"
            );
        } else {
            ensure!(
                rows == counted.rows,
                "input row count changed after counting"
            );
        }
    }
    observe(observer, false, Status::Active, rows, true);
    observe(observer, true, Status::Active, rows, true);
    let (publication, files, bytes, groups) = if let Some(partition) = counted_partition {
        partition.finish(&mut stages)?
    } else if chain_job {
        let chain = match chain {
            Some(chain) => chain,
            None => fanout::chains::Chains::new(job, header.as_ref(), input.columns(), ctx)?,
        };
        chain.finish(&mut stages)?
    } else if fanout_job {
        let fanout = match fanout {
            Some(fanout) => fanout,
            None => fanout::Fanout::new(job, header.as_ref(), input.columns(), ctx)?,
        };
        let (publication, files, bytes, stats) = fanout.finish()?;
        let groups = stats.output_groups;
        stages.push(stats)?;
        (publication, files, bytes, groups)
    } else {
        let mut writer = writer.unwrap();
        writer
            .end(group)
            .map_err(|error| observe_error(observer, true, rows, error))?;
        let (publication, output_files, bytes) = writer
            .finish_direct()
            .map_err(|error| observe_error(observer, true, rows, error))?;
        (publication, output_files, bytes, files)
    };
    let analysis = Analysis { algorithm_version: Analysis::algorithm_version_for(job),
        column_values: column_values.finish()?, seed, rows, columns: input.columns(),
        header, preview: preview.finish()?,
        logical_digest: AnalysisText::copy(digest.to_hex().as_str(), Reservation::new(ctx))?,
        groups, output_files: files, output_csv_bytes: bytes, largest_record_bytes: largest,
        temp_bytes: 0, peak_temp_bytes: 0, memory_budget_bytes: ctx.memory as u64,
        workers: ctx.workers(), analysis_seconds: 0.0, timings: Default::default(),
        diagnostics: Default::default(), stages, warnings: Warnings::default(),
        accuracy: AnalysisText::copy("Exact row, group, file and uncompressed byte counts; complete strict validation. Compressed sizes and runtime are not guaranteed.", Reservation::new(ctx))?,
        execution: None, auto_plan: None,
    };
    Ok((analysis, publication))
}

fn observe_error(
    observer: &mut Option<Observer<'_>>,
    write: bool,
    rows: u64,
    error: anyhow::Error,
) -> anyhow::Error {
    observe(
        observer,
        write,
        crate::observation::physical::error_status(&error),
        rows,
        true,
    );
    error
}

fn observe(
    observer: &mut Option<Observer<'_>>,
    write: bool,
    status: Status,
    rows: u64,
    force: bool,
) {
    if let Some(observer) = observer {
        observer.update(write, status, rows, force);
    }
}
