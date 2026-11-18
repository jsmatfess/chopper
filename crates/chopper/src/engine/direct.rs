//! One input traversal for limits-only jobs, with no retained CSV snapshot.
use super::*;
use crate::observation::{Observer, Status};

pub(super) fn run(
    job: Job,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
    sink: Option<crate::observation::Sink<'_>>,
    physical: Option<crate::observation::physical::Sink>,
) -> Result<output::PublishedAnalysis> {
    let started = std::time::Instant::now();
    job.validate()?;
    ensure!(!job.output.is_empty(), "output path is required");
    let mut ctx = Context::with_memory_pool(&job.resources, cancel, notify, pool)?;
    ctx.physical = physical;
    let mut observer = sink.and_then(|sink| Observer::new(&ctx, sink));
    let job = PreparedJob::admit(job, Reservation::new(&ctx))?;
    ctx.event("Reading and writing CSV", 0)?;
    observe(&mut observer, false, Status::Active, 0, true);
    let before = std::fs::metadata(&job.input).context("open input")?;
    ensure!(before.is_file(), "input must be a regular file");
    let ingest_started = std::time::Instant::now();
    let (mut analysis, publication) =
        with_input_observed(&job, Reservation::new(&ctx), &ctx, |source, input_ctx| {
            consume(source, &job, input_ctx, &mut observer)
        })?;
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
    let receipt = publication
        .publish(&job, &analysis, &ctx)
        .map_err(|error| observe_error(&mut observer, true, analysis.rows, error))?;
    observe(&mut observer, true, Status::Completed, analysis.rows, true);
    Ok(receipt.with_analysis(analysis))
}

fn consume(
    source: &mut dyn Read,
    job: &Job,
    ctx: &Context,
    observer: &mut Option<Observer<'_>>,
) -> Result<(Analysis, output::DirectPublication)> {
    let mut input = Intake::new(
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
    let seed = AnalysisText::copy(job.random_seed.as_deref().unwrap(), Reservation::new(ctx))?;
    let stages = Stages::new(0, Reservation::new(ctx))?;
    let header =
        header::read(&mut input).map_err(|error| observe_error(observer, false, 0, error))?;
    observe(observer, true, Status::Active, 0, true);
    let mut writer = output::PlanWriter::direct(job, header.as_deref(), ctx)
        .map_err(|error| observe_error(observer, true, 0, error))?;
    let mut group = writer.begin(vec![], false);
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
        #[cfg(feature = "resource-contract-tests")]
        crate::guide_test_control::checkpoint("direct-row");
        let views = FieldViews::owned(input.owned());
        column_values.observe(job, header.as_deref(), views.clone())?;
        let size = input.owned().iter().map(String::len).sum();
        largest = largest.max(size as u64);
        preview.consider(views, size)?;
        digest.record(input.owned());
        input.consume_owned(|fields| {
            let row = Row {
                id: group.rows,
                ordinal: group.rows,
                key: vec![],
                fields: std::mem::take(fields),
            };
            writer
                .row(&mut group, &row)
                .map_err(|error| observe_error(observer, true, group.rows, error))?;
            *fields = row.fields;
            Ok(())
        })?;
        if group.rows % 4096 == 0 {
            observe(observer, false, Status::Active, group.rows, false);
            observe(observer, true, Status::Active, group.rows, false);
        }
    }
    let rows = group.rows;
    observe(observer, false, Status::Active, rows, true);
    observe(observer, true, Status::Active, rows, true);
    writer
        .end(group)
        .map_err(|error| observe_error(observer, true, rows, error))?;
    let (publication, files, bytes) = writer
        .finish_direct()
        .map_err(|error| observe_error(observer, true, rows, error))?;
    let analysis = Analysis { algorithm_version: Analysis::algorithm_version_for(job),
        column_values: column_values.finish()?, seed, rows, columns: input.columns(),
        header, preview: preview.finish()?,
        logical_digest: AnalysisText::copy(digest.finalize().to_hex().as_str(), Reservation::new(ctx))?,
        groups: 1, output_files: files, output_csv_bytes: bytes, largest_record_bytes: largest,
        temp_bytes: 0, peak_temp_bytes: 0, memory_budget_bytes: ctx.memory as u64,
        workers: ctx.workers(), analysis_seconds: 0.0, timings: Default::default(),
        diagnostics: Default::default(), stages, warnings: Warnings::default(),
        accuracy: AnalysisText::copy("Exact row, group, file and uncompressed byte counts; complete strict validation. Compressed sizes and runtime are not guaranteed.", Reservation::new(ctx))?,
        execution: None,
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
