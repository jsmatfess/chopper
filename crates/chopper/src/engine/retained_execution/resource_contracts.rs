//! Same writer/commit contracts for native tests and the optional WASI reactor.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

fn context(temporary_bytes: u64, pool: Arc<MemoryPool>) -> Result<Context> {
    Context::with_memory_pool(
        &Resources {
            workers: 1,
            memory_mb: 32.into(),
            max_record_bytes: 2 * 1024 * 1024,
            temp_bytes: Some(temporary_bytes),
            #[cfg(target_os = "wasi")]
            temp_dir: Some("/tmp".into()),
            ..Default::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool,
    )
}
fn copy(data: &Dataset, ctx: &Context, sink: &mut impl RowSink) -> Result<()> {
    sink.physical_input(data.physical_source);
    for parent in data.groups()? {
        let parent = parent?;
        let mut group = sink.begin(parent.lineage.clone(), parent.exact);
        for row in data.packed_rows(&parent, ctx.max_record)? {
            sink.packed_row(&mut group, row?)?;
        }
        sink.end(group)?;
    }
    Ok(())
}
fn stats(index: usize) -> [StageStats; 2] {
    std::array::from_fn(|offset| StageStats {
        operation: index + offset + 1,
        input_groups: 1,
        output_groups: 1,
        smallest_group: 2,
        largest_group: 2,
        empty_groups: 0,
    })
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
    let ctx = context(16 * 1024 * 1024, pool.clone())?;
    let job = Job {
        random_seed: Some("retained-result-contract".into()),
        operations: vec![Operation::Balanced { files: 1 }; 3],
        ..Default::default()
    };
    for terminal in [false, true] {
        let source = ingest_options(
            &mut b"id\n1\n2\n".as_slice(),
            &job,
            &ctx,
            false,
            false,
            false,
        )?;
        ensure!(
            source.consumed == 0,
            "fixture unexpectedly consumed operations"
        );
        let mut dataset = source.dataset;
        let mut analysis = source.analysis;
        let mut output = None;
        let mut index = usize::from(terminal);
        let completed = execute(&job, &analysis, &ctx, index, 2, |writer| {
            copy(&dataset, &ctx, writer)?;
            Ok(Some(stats(index)))
        })
        .map_err(Failure::into_error)?
        .context("copy declined")?;
        // A completed attempt still leaves caller state alone until commitment.
        ensure!(
            analysis.stages.is_empty() && output.is_none(),
            "premature commitment"
        );
        completed.commit(
            &mut dataset,
            &mut output,
            &mut analysis,
            &mut index,
            |stats, analysis| {
                analysis.groups = stats[1].output_groups;
                analysis.stages.extend(stats)
            },
        )?;
        ensure!(
            index == usize::from(terminal) + 2 && analysis.stages.len() == 2,
            "commit count mismatch"
        );
        ensure!(
            analysis.stages[0].operation == usize::from(terminal) + 1,
            "original stage index lost"
        );
        if terminal {
            let output = output.context("terminal result missing snapshot")?;
            let mut bytes = Vec::new();
            output.data.reader()?.read_to_end(&mut bytes)?;
            ensure!(
                bytes == b"id\n1\n2\n" && output.files == 1,
                "terminal CSV changed"
            );
        } else {
            ensure!(
                output.is_none() && dataset.groups == 1,
                "intermediate result serialized early"
            );
            let parent = dataset.groups()?.next().context("missing result group")??;
            let fields = dataset
                .rows(&parent, ctx.max_record)?
                .map(|row| Ok(row?.fields.clone()))
                .collect::<Result<Vec<_>>>()?;
            ensure!(
                fields == vec![vec!["1".to_owned()], vec!["2".to_owned()]],
                "retained rows changed"
            );
        }
    }
    let source = ingest_options(
        &mut b"id\n1\n2\n".as_slice(),
        &job,
        &ctx,
        false,
        false,
        false,
    )?;
    let mut dataset = source.dataset;
    let mut analysis = source.analysis;
    let before = ctx.used();
    for terminal in [false, true] {
        let index = usize::from(terminal);
        let declined = execute::<()>(&job, &analysis, &ctx, index, 2, |writer| {
            copy(&dataset, &ctx, writer)?;
            Ok(None)
        })
        .map_err(Failure::into_error)?;
        ensure!(
            declined.is_none() && ctx.used() == before,
            "declined writer leaked tentative output"
        );
        let error = execute::<()>(&job, &analysis, &ctx, index, 2, |writer| {
            copy(&dataset, &ctx, writer)?;
            anyhow::bail!("failed after writing")
        })
        .err()
        .context("execution failure accepted")?;
        ensure!(
            !error.is_setup()
                && error.error().to_string() == "failed after writing"
                && ctx.used() == before,
            "execution failure classification/cleanup changed"
        );
        let tiny = context(1, pool.clone())?;
        let mut applied = false;
        let error = execute(&job, &analysis, &tiny, index, 2, |writer| {
            copy(&dataset, &tiny, writer)?;
            applied = true;
            Ok(Some(()))
        })
        .err()
        .context("finalization denial accepted")?;
        ensure!(
            applied && !error.is_setup() && tiny.used() == 0,
            "finalization failure retried as setup or leaked"
        );
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(64 * 1024 * 1024, pool.clone())));
        pressure.resize((64 * 1024 * 1024 - pool.usage().reserved_bytes) as usize)?;
        let mut applied = false;
        let error = execute::<()>(&job, &analysis, &ctx, index, 2, |_| {
            applied = true;
            Ok(Some(()))
        })
        .err()
        .context("setup denial accepted")?;
        ensure!(
            error.is_setup()
                && error.error().downcast_ref::<MemoryAdmission>().is_some()
                && !applied
                && ctx.used() == before,
            "setup denial crossed execution seam"
        );
        drop(pressure);
    }
    let old_data = dataset.data.clone();
    let mut index = 0;
    let mut output = None;
    let completed = execute(&job, &analysis, &ctx, index, 2, |writer| {
        copy(&dataset, &ctx, writer)?;
        Ok(Some(stats(index)))
    })
    .map_err(Failure::into_error)?
    .context("copy declined")?;
    let shared_stages = analysis.stages.clone();
    let result = completed.commit(
        &mut dataset,
        &mut output,
        &mut analysis,
        &mut index,
        |stats, analysis| analysis.stages.extend(stats),
    );
    ensure!(
        result.is_err()
            && index == 0
            && output.is_none()
            && Arc::ptr_eq(&dataset.data, &old_data)
            && ctx.used() == before,
        "failed statistics append committed output or leaked"
    );
    drop(shared_stages);
    drop(old_data);
    drop(dataset);
    drop(analysis);
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "retained execution ownership leaked"
    );
    Ok(
        json!({"terminal_and_intermediate":true,"decline_cleanup":true,"execution_and_finish_terminal":true,"setup_denial_before_apply":true,"append_failure_preserves_cursor_and_input":true}),
    )
}
#[cfg(test)]
#[test]
fn writer_lifetime_commit_and_error_phases() -> Result<()> {
    run().map(|_| ())
}
