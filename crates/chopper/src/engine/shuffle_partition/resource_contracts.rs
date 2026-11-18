//! The same retained-dataset seam is checked by native tests and the test WASI reactor.
//! Fixtures bound their own storage and make no complete RSS claim. The parent
//! helpers cover retained datasets; the publication child additionally checks
//! encoded CSV caps and Rust publication, excluding JavaScript destination export.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::atomic::{AtomicU64, Ordering};
pub(in crate::engine) mod preparation;
pub(in crate::engine) mod publication;

const SHARED_BYTES: u64 = 64 * 1024 * 1024;
const TEMPORARY_BYTES: u64 = 32 * 1024 * 1024;

pub(super) fn shuffle() -> Operation {
    Operation::Shuffle {
        strategy: Shuffle::Uniform,
    }
}

pub(super) fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
    let mut groups = Vec::new();
    for group in data.groups()? {
        let group = group?;
        let rows = data
            .rows(&group, ctx.max_record)?
            .map(|row| {
                let row = row?;
                Ok(json!({"id":row.id,"fields":row.fields}))
            })
            .collect::<Result<Vec<_>>>()?;
        groups.push(json!({"lineage":group.lineage,"exact":group.exact,"rows":rows}));
    }
    Ok(json!(groups))
}

pub(super) fn serial(
    data: &Dataset,
    operation: &Operation,
    step: usize,
    job: &Job,
    analysis: &Analysis,
    ctx: &Context,
) -> Result<Dataset> {
    let mut writer = DatasetWriter::new(ctx)?;
    for parent in data.groups()? {
        apply_parent(
            data,
            &*parent?,
            operation,
            step,
            job,
            analysis,
            ctx,
            &mut writer,
            None,
            None,
        )?;
    }
    writer.finish()
}

fn context(pool: Arc<MemoryPool>, cancel: Arc<AtomicBool>) -> Result<Context> {
    Context::with_memory_pool(
        &Resources {
            workers: 1,
            memory_mb: 32.into(),
            max_record_bytes: 2 * 1024 * 1024,
            temp_bytes: Some(TEMPORARY_BYTES),
            #[cfg(target_os = "wasi")]
            temp_dir: Some("/tmp".into()),
            ..Default::default()
        },
        cancel,
        Arc::new(|_| {}),
        pool,
    )
}

// This synthetic concurrent owner holds admission only, not an allocation. Its
// guard also releases the grant if an assertion returns early with an error.
struct Pressure {
    pool: Arc<MemoryPool>,
    held: AtomicU64,
}
impl Pressure {
    fn release(&self) {
        self.pool.release(self.held.swap(0, Ordering::Relaxed));
    }
}
impl Drop for Pressure {
    fn drop(&mut self) {
        self.release();
    }
}

struct PressureSink<'a> {
    writer: &'a mut DatasetWriter,
    pressure: Arc<Pressure>,
    groups: u64,
    rows: u64,
}
impl RowSink for PressureSink<'_> {
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        self.writer.begin(lineage, exact)
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        self.writer.row(group, row)?;
        self.rows += 1;
        Ok(())
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        self.writer.packed_row_ref(group, row)?;
        self.rows += 1;
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.writer.end(group)?;
        self.groups += 1;
        if self.groups == 1 {
            let amount = SHARED_BYTES
                .checked_sub(self.pressure.pool.usage().reserved_bytes + 128 * 1024)
                .context("first-parent fixture exhausted the shared pool")?;
            self.pressure.pool.acquire(amount)?;
            self.pressure.held.store(amount, Ordering::Relaxed);
        }
        Ok(())
    }
}

pub(in crate::engine) fn retained_parent_retry() -> Result<serde_json::Value> {
    let modes = ["released", "cancelled", "retained"].into_iter().chain(
        if cfg!(any(target_os = "linux", windows, target_os = "wasi")) {
            Some("cleanup")
        } else {
            None
        },
    );
    let mut cases = Vec::new();
    for mode in modes {
        let pool = Arc::new(MemoryPool::new(SHARED_BYTES));
        let pressure = Arc::new(Pressure {
            pool: pool.clone(),
            held: AtomicU64::new(0),
        });
        let cancel = Arc::new(AtomicBool::new(false));
        let mut ctx = context(pool.clone(), cancel.clone())?;
        let workspace = ctx.dir.path().to_owned();
        let job = Job {
            random_seed: Some("retry-parent-v1".into()),
            operations: vec![
                Operation::Balanced { files: 2 },
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
            ],
            ..Default::default()
        };
        let wide = "late-key".repeat(40_000);
        let text = format!(
            "id,key\n{}{}",
            (0..8).map(|id| format!("{id},a\n")).collect::<String>(),
            (8..16)
                .map(|id| format!("{id},{wide}\n"))
                .collect::<String>()
        );
        let fixture_blake3 = blake3::hash(text.as_bytes()).to_hex().to_string();
        let ingested = ingest_options(&mut text.as_bytes(), &job, &ctx, false, false, false)?;
        let parents = serial(
            &ingested.dataset,
            &job.operations[0],
            0,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let shuffled = serial(
            &parents,
            &job.operations[1],
            1,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let expected = serial(
            &shuffled,
            &job.operations[2],
            2,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let release_pressure = pressure.clone();
        let retry_entries = Arc::new(AtomicU64::new(0));
        let observed_retries = retry_entries.clone();
        let cleanup_error = Arc::new(std::sync::Mutex::new(None::<String>));
        #[cfg(any(target_os = "linux", windows, target_os = "wasi"))]
        let retry_ctx = ctx.clone();
        #[cfg(any(target_os = "linux", windows, target_os = "wasi"))]
        let observed_cleanup_error = cleanup_error.clone();
        ctx.notify = Arc::new(move |progress| {
            if progress.phase == "retrying shuffle/partition with original stages" {
                observed_retries.fetch_add(1, Ordering::Relaxed);
                if mode != "retained" {
                    release_pressure.release();
                    if mode == "cancelled" {
                        cancel.store(true, Ordering::Relaxed);
                    }
                    #[cfg(any(target_os = "linux", windows, target_os = "wasi"))]
                    if mode == "cleanup" {
                        if let Err(error) = retry_ctx.force_cleanup_error_for_test() {
                            *observed_cleanup_error.lock().unwrap() = Some(error.to_string());
                        }
                    }
                }
            }
        });
        let mut writer = DatasetWriter::new(&ctx)?;
        let mut sink = PressureSink {
            writer: &mut writer,
            pressure: pressure.clone(),
            groups: 0,
            rows: 0,
        };
        let result = Plan::at(&job, 1)
            .context("candidate plan not enabled")?
            .apply(&parents, &job, &ingested.analysis, &ctx, &mut sink);
        let committed_groups = sink.groups;
        let committed_rows = sink.rows;
        drop(sink);
        pressure.release();
        ensure!(
            cleanup_error.lock().unwrap().is_none(),
            "{mode}: cleanup fault injection failed"
        );
        ensure!(
            retry_entries.load(Ordering::Relaxed) == 1,
            "{mode}: late-parent typed admission did not enter retry once"
        );
        ensure!(
            ctx.diagnostics()["shuffle_partition_fusions"] == 1
                && ctx.diagnostics()["shuffle_partition_rows"] == 8
                && ctx.diagnostics()["shuffle_partition_retries"] == 1,
            "{mode}: earlier parent or retry count changed"
        );
        let mut snapshot_blake3 = None;
        let mut stats_blake3 = None;
        let outcome;
        if mode == "released" {
            result?;
            ensure!(
                committed_groups == 2 && committed_rows == 16,
                "released: committed rows/groups duplicated or missing"
            );
            let actual = writer.finish()?;
            let actual_snapshot = snapshot(&actual, &ctx)?;
            ensure!(
                actual_snapshot == snapshot(&expected, &ctx)?,
                "released: original-stage snapshot bytes/order/lineage changed"
            );
            snapshot_blake3 = Some(
                blake3::hash(&serde_json::to_vec(&actual_snapshot)?)
                    .to_hex()
                    .to_string(),
            );
            let actual_stats = serde_json::to_value(dataset_stats(&actual, 3, 2, &ctx)?)?;
            ensure!(
                actual_stats == serde_json::to_value(dataset_stats(&expected, 3, 2, &ctx)?)?,
                "released: original-stage logical statistics changed"
            );
            stats_blake3 = Some(
                blake3::hash(&serde_json::to_vec(&actual_stats)?)
                    .to_hex()
                    .to_string(),
            );
            drop(actual);
            outcome = "original-stage-replay-success";
        } else {
            ensure!(
                committed_groups == 1 && committed_rows == 8,
                "{mode}: failed parent emitted rows or earlier parent duplicated"
            );
            let error = result
                .err()
                .context("terminal mode unexpectedly succeeded")?;
            outcome = match mode {
                "cancelled" => {
                    ensure!(
                        format!("{error:#}").contains("cancel"),
                        "wrong cancellation error"
                    );
                    "cancelled-before-replay"
                }
                "retained" => {
                    ensure!(
                        error.downcast_ref::<MemoryAdmission>().is_some(),
                        "persistent pressure lost its typed admission error: {error:#}"
                    );
                    "typed-admission-denied"
                }
                "cleanup" => {
                    ensure!(
                        error.to_string().contains("cleanup")
                            && ctx.diagnostics()["temporary_cleanup_failures"] == 1,
                        "actual unlink failure did not prevent replay: {error:#}"
                    );
                    "cleanup-failure-stopped-replay"
                }
                _ => unreachable!(),
            };
            drop(writer);
        }
        drop(expected);
        drop(shuffled);
        drop(parents);
        drop(ingested);
        let decision_audit = ctx.diagnostics()["shuffle_partition_decisions"].clone();
        let audit_bytes = decision_audit["reserved_bytes"]
            .as_u64()
            .context("decision audit has no capacity charge")?;
        let records = decision_audit["records"]
            .as_array()
            .context("decision audit has no records")?;
        ensure!(
            audit_bytes > 0
                && records.len() == 2
                && decision_audit["completed_attempts"] == 2
                && decision_audit["omitted_attempts"] == 0
                && decision_audit["collection_denied"] == false
                && records[0]["outcome"] == "fused_committed"
                && records[0]["observation_complete"] == true
                && records[0]["key_observation_complete"] == true
                && records[1]["admission_denial"] == "shared"
                && records[1]["admission_denial_phase"] == "preparation"
                && (records[1]["observation_complete"] == false
                    || records[1]["key_observation_complete"] == false),
            "{mode}: retained-parent decision observations changed: {decision_audit}"
        );
        ensure!(
            records[1]["outcome"]
                == if mode == "released" {
                    "original_committed"
                } else {
                    "terminal"
                }
                && records[1]["phase"] == "original_retry"
                && records[1]["cancelled"] == (mode == "cancelled")
                && records[1]["cleanup_failed"] == (mode == "cleanup"),
            "{mode}: decision outcome or terminal flags changed"
        );
        let ctx_directory_bytes = ctx.directory_reserved_bytes();
        let retained_path_bytes = pool
            .usage()
            .reserved_bytes
            .checked_sub(audit_bytes)
            .and_then(|bytes| bytes.checked_sub(ctx_directory_bytes))
            .context("decision audit capacity was released early")?;
        ensure!(
            ctx_directory_bytes > 0
                && ctx.diagnostics()["temporary_path_reserved_bytes"] == retained_path_bytes
                && ctx.diagnostics()["workspace_reserved_bytes"]
                    == audit_bytes + ctx_directory_bytes + retained_path_bytes,
            "{mode}: retained owner equation changed"
        );
        if mode == "cleanup" {
            ensure!(
                ctx.used() == 3
                    && retained_path_bytes > 0
                    && std::fs::read_dir(ctx.dir.path())?.count() == 2,
                "cleanup: orphan data/path owners were released early"
            );
        } else {
            ensure!(
                ctx.diagnostics()["workspace_reserved_bytes"]
                    == audit_bytes + ctx.directory_reserved_bytes()
                    && retained_path_bytes == 0
                    && ctx.used() == 0
                    && std::fs::read_dir(ctx.dir.path())?.next().is_none(),
                "{mode}: temporary files or capacity leaked"
            );
        }
        let peak_temporary_bytes = ctx.peak();
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0 && !workspace.try_exists()?,
            "{mode}: final context leaked workspace or capacity"
        );
        cases.push(json!({
            "mode": mode, "outcome": outcome,
            "fixture_blake3": fixture_blake3,
            "fused_parents": 1, "fused_rows": 8, "typed_denial_retries": 1,
            "committed_groups": committed_groups, "committed_rows": committed_rows,
            "snapshot_blake3": snapshot_blake3, "logical_stats_blake3": stats_blake3,
            "peak_temporary_bytes": peak_temporary_bytes,
            "orphan_bytes_before_context_drop": if mode == "cleanup" { 3 } else { 0 },
            "retained_path_bytes_before_context_drop": retained_path_bytes,
            "directory_reserved_bytes_before_context_drop": ctx_directory_bytes,
            "decision_audit": decision_audit,
            "workspace_removed": true, "final_reserved_bytes": 0,
        }));
    }
    Ok(json!({
        "contract": "retained-parent-shuffle-partition-resource-contract-v1",
        "scope": "retained-dataset", "shared_bytes": SHARED_BYTES,
        "temporary_budget_bytes": TEMPORARY_BYTES, "cases": cases,
    }))
}

pub(in crate::engine) fn terminal_emission() -> Result<serde_json::Value> {
    struct DeniedSink {
        rows: u64,
        groups: u64,
    }
    impl RowSink for DeniedSink {
        fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
            Group {
                offset: 0,
                rows: 0,
                lineage,
                exact,
            }
        }
        fn row(&mut self, _: &mut Group, _: &Row) -> Result<()> {
            self.rows += 1;
            Err(MemoryAdmission::Local.into())
        }
        fn end(&mut self, _: Group) -> Result<()> {
            self.groups += 1;
            Ok(())
        }
    }
    let pool = Arc::new(MemoryPool::new(SHARED_BYTES));
    let ctx = context(pool.clone(), Arc::new(AtomicBool::new(false)))?;
    let workspace = ctx.dir.path().to_owned();
    let job = Job {
        random_seed: Some("sink-denial-v1".into()),
        operations: vec![
            Operation::Balanced { files: 1 },
            shuffle(),
            Operation::Partition {
                columns: vec![Column::Index(0)],
            },
        ],
        ..Default::default()
    };
    let source = ingest_options(
        &mut "key\na\na\n".as_bytes(),
        &job,
        &ctx,
        false,
        false,
        false,
    )?;
    let mut sink = DeniedSink { rows: 0, groups: 0 };
    let error = Plan::at(&job, 1)
        .context("candidate plan not enabled")?
        .apply(&source.dataset, &job, &source.analysis, &ctx, &mut sink)
        .err()
        .context("emission denial unexpectedly succeeded")?;
    ensure!(
        error.downcast_ref::<MemoryAdmission>().is_some()
            && sink.rows == 1
            && sink.groups == 0
            && ctx.diagnostics()["shuffle_partition_retries"] == 0,
        "emission admission error retried or changed: {error:#}"
    );
    drop(source);
    let decision_audit = ctx.diagnostics()["shuffle_partition_decisions"].clone();
    let audit_bytes = decision_audit["reserved_bytes"]
        .as_u64()
        .context("emission audit capacity absent")?;
    let records = decision_audit["records"]
        .as_array()
        .context("emission audit records absent")?;
    ensure!(
        audit_bytes > 0
            && records.len() == 1
            && records[0]["outcome"] == "terminal"
            && records[0]["phase"] == "emission"
            && records[0]["terminal_admission_denial"] == "local"
            && records[0]["observation_complete"] == true
            && records[0]["key_observation_complete"] == true,
        "terminal emission decision changed: {decision_audit}"
    );
    ensure!(
        ctx.diagnostics()["workspace_reserved_bytes"]
            == audit_bytes + ctx.directory_reserved_bytes()
            && ctx.used() == 0
            && pool.usage().reserved_bytes == audit_bytes + ctx.directory_reserved_bytes(),
        "emission denial leaked temporary files/capacity"
    );
    let directory_bytes = ctx.directory_reserved_bytes();
    ensure!(directory_bytes > 0, "emission directory owner missing");
    let peak = ctx.peak();
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0 && !workspace.try_exists()?,
        "emission workspace or audit leaked"
    );
    Ok(json!({
        "contract": "shuffle-partition-terminal-emission-resource-contract-v1",
        "scope": "retained-dataset", "typed_admission_denial": true,
        "row_calls": 1, "committed_groups": 0, "retries": 0,
        "peak_temporary_bytes": peak, "workspace_removed": true,
        "final_reserved_bytes": 0,
        "directory_reserved_bytes_before_context_drop": directory_bytes,
        "decision_audit": decision_audit,
    }))
}
