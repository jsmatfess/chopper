use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::cell::Cell;
use std::sync::atomic::Ordering;

fn fixture() -> Group {
    let mut lineage = Vec::with_capacity(8);
    lineage.push(json!({"operation":0,"values":["\u{754c}\n\"quoted", {"nested":[true,null,17]}]}));
    Group {
        offset: 0,
        rows: 0,
        lineage,
        exact: true,
    }
}

struct Sink {
    begins: Cell<usize>,
    pool: Arc<MemoryPool>,
    baseline: u64,
    minimum: u64,
    cancel: Arc<AtomicBool>,
    mode: &'static str,
    ids: Vec<u64>,
    ended: bool,
}
impl RowSink for Sink {
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        assert!(self.pool.usage().reserved_bytes >= self.baseline + self.minimum);
        self.begins.set(self.begins.get() + 1);
        Group {
            offset: 0,
            rows: 0,
            lineage,
            exact,
        }
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        ensure!(
            self.pool.usage().reserved_bytes >= self.baseline + self.minimum,
            "shuffle row lost lineage admission"
        );
        ensure!(
            group.lineage == fixture().lineage && group.exact,
            "shuffle changed lineage/exactness"
        );
        ensure!(
            row.ordinal == group.rows
                && row.fields == [row.id.to_string(), "\u{754c},\"quoted\"\nline".into()],
            "shuffle changed ordinal/fields"
        );
        if self.mode == "row_error" {
            anyhow::bail!("injected shuffle row error");
        }
        if self.mode == "cancelled" || (self.mode == "last_row_cancelled" && group.rows == 7) {
            self.cancel.store(true, Ordering::Relaxed);
        }
        self.ids.push(row.id);
        group.rows += 1;
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        ensure!(
            self.pool.usage().reserved_bytes >= self.baseline + self.minimum,
            "shuffle end released lineage before consumption"
        );
        ensure!(
            group.lineage == fixture().lineage && group.exact,
            "shuffle end changed metadata"
        );
        if self.mode == "end_error" {
            anyhow::bail!("injected shuffle catalog error");
        }
        self.ended = true;
        Ok(())
    }
}
fn sink(
    pool: &Arc<MemoryPool>,
    baseline: u64,
    minimum: u64,
    cancel: &Arc<AtomicBool>,
    mode: &'static str,
) -> Sink {
    Sink {
        begins: Cell::new(0),
        pool: pool.clone(),
        baseline,
        minimum,
        cancel: cancel.clone(),
        mode,
        ids: Vec::new(),
        ended: false,
    }
}

fn edges() -> Result<serde_json::Value> {
    let parent = fixture();
    let allowance = parent.json_capacity()?;
    let cancel = Arc::new(AtomicBool::new(false));
    for shared in [false, true] {
        for limit in [allowance - 1, allowance, allowance + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * allowance, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let output = sink(
                &pool,
                0,
                if shared { allowance as u64 } else { 0 },
                &cancel,
                "success",
            );
            let result = ClonedGroup::begin(
                &parent,
                &output,
                Reservation::for_workspace(workspace.clone()),
            );
            if limit < allowance {
                let error = result.err().context("shuffle lineage edge accepted")?;
                ensure!(
                    output.begins.get() == 0
                        && matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                    "shuffle denial invoked sink or lost type"
                );
            } else {
                let owner = result?;
                ensure!(
                    owner.group.lineage == parent.lineage
                        && workspace.used() == owner.group.json_capacity()? as u64,
                    "shuffle clone retained capacity/parity changed"
                );
                drop(owner);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "shuffle edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(2 * allowance as u64));
    let workspace = Arc::new(Workspace::shared(2 * allowance, pool.clone()));
    let mut output = sink(&pool, 0, allowance as u64, &cancel, "success");
    let first = ClonedGroup::begin(
        &parent,
        &output,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let second = ClonedGroup::begin(
        &parent,
        &output,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let retained = first.group.json_capacity()? as u64;
    drop(parent);
    ensure!(
        pool.usage().reserved_bytes == 2 * retained,
        "source drop lost independent clones"
    );
    output.minimum = retained;
    first.finish(&mut output)?;
    ensure!(
        pool.usage().reserved_bytes == retained,
        "finishing first lost sibling grant"
    );
    second.finish(&mut output)?;
    ensure!(
        pool.usage().reserved_bytes == 0,
        "shuffle final owner leaked"
    );
    Ok(
        json!({"local_shared_edge_checks":6,"denial_precedes_sink_begin":true,
        "source_allowance_bytes":allowance,"retained_bytes":retained,
        "independent_clones":2,"source_drop_retains_clones":true,"final_reserved_bytes":0}),
    )
}

fn execution() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let path = dir.path().to_owned();
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,text\n0,value\n")?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        random_seed: Some("shuffle-lineage-contract".into()),
        resources: Resources {
            workers: 1,
            temp_dir: Some(path.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let prepared = prepare(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?;
    let analysis = prepared.analysis.clone();
    drop(prepared);
    let pool = Arc::new(MemoryPool::new(32 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let ctx = Context::with_memory_pool(
        &job.resources,
        cancel.clone(),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let mut writer = DatasetWriter::new(&ctx)?;
    let mut parent = writer.begin(fixture().lineage, true);
    for id in 0..8 {
        writer.row(
            &mut parent,
            &Row {
                id,
                ordinal: id,
                key: Vec::new(),
                fields: vec![id.to_string(), "\u{754c},\"quoted\"\nline".into()],
            },
        )?;
    }
    writer.end(parent.clone())?;
    let data = writer.finish()?;
    let baseline = pool.usage().reserved_bytes;
    // Actual clone capacity may shrink spare Vec slots. Probe without row/sort
    // allocations to isolate the output lineage's retained minimum.
    let probe_sink = sink(
        &pool,
        baseline,
        parent.json_capacity()? as u64,
        &cancel,
        "success",
    );
    let probe = ClonedGroup::begin(&parent, &probe_sink, Reservation::new(&ctx))?;
    let retained = probe.group.json_capacity()? as u64;
    drop(probe);
    let run = |strategy, output: &mut Sink| {
        apply_parent(
            &data,
            &parent,
            &Operation::Shuffle { strategy },
            1,
            &job,
            &analysis,
            &ctx,
            output,
            None,
            None,
        )
    };
    let mut cases = Vec::new();
    let strategies = [Shuffle::Uniform, Shuffle::FisherYates];
    let strategies = strategies.into_iter();
    for strategy in strategies {
        let mut expected = None;
        for mode in [
            "success",
            "row_error",
            "end_error",
            "cancelled",
            "last_row_cancelled",
            "retry",
        ] {
            let mut output = sink(&pool, baseline, retained, &cancel, mode);
            let result = run(strategy, &mut output);
            ensure!(
                result.is_ok() == matches!(mode, "success" | "retry"),
                "shuffle {strategy:?}/{mode}: {result:?}"
            );
            if result.is_ok() {
                ensure!(output.ended, "shuffle omitted catalog end");
                let mut ids = output.ids.clone();
                ids.sort_unstable();
                ensure!(
                    ids == (0..8).collect::<Vec<_>>(),
                    "shuffle lost/duplicated IDs"
                );
                if let Some(expected) = &expected {
                    ensure!(
                        &output.ids == expected,
                        "shuffle retry changed seeded order"
                    );
                } else {
                    expected = Some(output.ids.clone());
                }
            }
            if matches!(mode, "cancelled" | "last_row_cancelled") {
                ensure!(
                    output.ids.len() == if mode == "cancelled" { 1 } else { 8 }
                        && !output.ended
                        && result.unwrap_err().to_string() == "job cancelled",
                    "shuffle did not observe cancellation between emitted rows"
                );
            }
            cancel.store(false, Ordering::Relaxed);
            ensure!(
                pool.usage().reserved_bytes == baseline && ctx.used() > 0,
                "shuffle {mode} leaked temporary/lineage owners"
            );
        }
        // Fill the shared pool before the real executor enters the clone seam.
        let remaining = pool.usage().limit_bytes - baseline;
        let mut pressure = Reservation::for_workspace(Arc::new(Workspace::shared(
            remaining as usize,
            pool.clone(),
        )));
        pressure.resize(remaining as usize)?;
        let mut output = sink(&pool, baseline, retained, &cancel, "success");
        let error = run(strategy, &mut output)
            .err()
            .context("shared shuffle denial accepted")?;
        ensure!(
            output.begins.get() == 0
                && matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Shared { .. })
                ),
            "executor denial lost type or emitted group"
        );
        drop(pressure);
        run(strategy, &mut output)?;
        ensure!(
            Some(&output.ids) == expected.as_ref() && pool.usage().reserved_bytes == baseline,
            "shared-denial retry changed order or leaked"
        );
        cases.push(json!({"strategy":strategy,"row_and_end_failure_cleanup":true,"cancellation_cleanup":true,
            "typed_shared_denial_before_begin":true,"release_retry_exact_order":true,"field_and_id_conservation":true,
            "lineage_and_exactness_preserved":true,"baseline_restored":true}));
    }
    drop(data);
    ensure!(
        ctx.used() == 0 && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "shuffle dataset leaked"
    );
    drop(ctx);
    ensure!(pool.usage().reserved_bytes == 0, "shuffle context leaked");
    dir.close()?;
    ensure!(!path.try_exists()?, "shuffle fixture leaked");
    Ok(json!({"cases":cases,"fixture_directory_removed":true,"final_reserved_bytes":0}))
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let report = json!({"contract":"shuffle-lineage-admission-contract-v1","owners":edges()?,"execution":execution()?});
    Ok(report)
}

#[cfg(test)]
#[test]
fn shuffle_lineage_admission_lifetime_and_executor_cleanup() -> Result<()> {
    println!("CHOPPER_SHUFFLE_LINEAGE_CONTRACT {}", run()?);
    Ok(())
}
