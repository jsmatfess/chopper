//! Traversal growth and independent leaf clones, shared by native and WASI.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::atomic::Ordering;

#[cfg(all(target_os = "wasi", not(feature = "experimental-nested-balanced")))]
fn hosted_guard(root: &std::path::Path) -> Result<()> {
    const MIB: u64 = 1024 * 1024;
    let mut job = Job {
        operations: vec![
            Operation::Balanced { files: 3 },
            Operation::Balanced { files: 7 },
        ],
        resources: Resources {
            memory_mb: 32.into(),
            max_record_bytes: MIB as usize,
            temp_dir: Some(root.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let pool = Arc::new(MemoryPool::new(32 * MIB));
    let mut ctx = Context::with_memory_pool(
        &job.resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    ensure!(
        !hosted_eligible(&job, &ctx, 256 * MIB, 21),
        "Prepare selected fusion"
    );
    ctx.auto_run = true;
    ensure!(
        hosted_eligible(&job, &ctx, 256 * MIB, 21),
        "Run declined fusion"
    );
    ensure!(
        !hosted_eligible(&job, &ctx, 256 * MIB - 1, 21),
        "small spool selected fusion"
    );
    ensure!(
        !hosted_eligible(&job, &ctx, 256 * MIB, 20),
        "invalid leaf count selected fusion"
    );
    job.operations.push(Operation::Balanced { files: 2 });
    ensure!(
        !hosted_eligible(&job, &ctx, 256 * MIB, 42),
        "three steps selected fusion"
    );
    job.operations.pop();
    let required = 12 * MIB;
    let held = 32 * MIB - pool.usage().reserved_bytes - required;
    let mut peer = Reservation::for_workspace(Arc::new(Workspace::shared(32 * MIB as usize, pool)));
    peer.resize(held as usize)?;
    ensure!(
        ctx.working_headroom() == required && hosted_eligible(&job, &ctx, 256 * MIB, 21),
        "exact headroom declined fusion"
    );
    peer.resize(held as usize + 1)?;
    ensure!(
        ctx.working_headroom() == required - 1 && !hosted_eligible(&job, &ctx, 256 * MIB, 21),
        "insufficient headroom selected fusion"
    );
    Ok(())
}

fn parent(data: &Dataset) -> Result<ChargedJson<Group>> {
    data.groups()?.next().context("missing nested parent")?
}

fn edges(data: &Dataset) -> Result<serde_json::Value> {
    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let owner = Parent::new(
        parent(data)?,
        8,
        Reservation::for_workspace(workspace.clone()),
    )?;
    let peak = workspace.peak() as usize;
    let retained = workspace.used();
    ensure!(
        peak > retained as usize && owner.value.lineage.capacity() >= owner.value.lineage.len() + 8,
        "nested growth lacks replacement overlap or depth capacity"
    );
    drop(owner);
    ensure!(workspace.used() == 0, "nested growth probe leaked");
    for shared in [false, true] {
        for limit in [peak - 1, peak, peak + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * peak, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = Parent::new(
                parent(data)?,
                8,
                Reservation::for_workspace(workspace.clone()),
            );
            if limit < peak {
                let error = result.err().context("nested growth edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "nested growth denial lost type"
                );
            } else {
                drop(result?);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "nested edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(peak as u64));
    let workspace = Arc::new(Workspace::shared(2 * peak, pool.clone()));
    let mut sibling = Reservation::for_workspace(workspace.clone());
    sibling.resize(1)?;
    let error = Parent::new(
        parent(data)?,
        8,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("nested competitor accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "nested failed growth lost sibling"
    );
    drop(sibling);
    let owner = Parent::new(
        parent(data)?,
        8,
        Reservation::for_workspace(workspace.clone()),
    )?;
    drop(owner);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "nested release retry leaked"
    );
    for depth in [0, 65, usize::MAX] {
        ensure!(
            Parent::new(
                parent(data)?,
                depth,
                Reservation::for_workspace(workspace.clone())
            )
            .is_err()
                && workspace.used() == 0,
            "invalid depth allocated traversal storage"
        );
    }
    Ok(
        json!({"local_shared_edges":6,"construction_peak_bytes":peak,"retained_growth_bytes":retained,
        "replacement_overlap_admitted":true,"typed_competitor_denial_and_retry":true,"invalid_depths":3,"final_reserved_bytes":0}),
    )
}

fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
    let mut result = Vec::new();
    for group in data.groups()? {
        let group = group?;
        let rows = data
            .rows(&group, ctx.max_record)?
            .map(|row| {
                let row = row?;
                Ok(json!([row.id, row.ordinal, row.fields]))
            })
            .collect::<Result<Vec<_>>>()?;
        result.push(json!([group.lineage, group.exact, group.rows, rows]));
    }
    Ok(json!(result))
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let fixture = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let fixture = tempfile::tempdir()?;
    let root = fixture.path().to_owned();
    let input = root.join("input.csv");
    std::fs::write(&input, b"id,text\n0,value\n")?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        random_seed: Some("nested-lineage-contract".into()),
        resources: Resources {
            workers: 1,
            temp_dir: Some(root.to_string_lossy().into_owned()),
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
    let mut group = writer.begin(
        vec![json!({"operation":0,"values":["\u{754c},\"quoted\"\n"]})],
        false,
    );
    for id in 0..16 {
        writer.row(
            &mut group,
            &Row {
                id,
                ordinal: id,
                key: Vec::new(),
                fields: vec![id.to_string(), "\u{754c},\"quoted\"\n".into()],
            },
        )?;
    }
    writer.end(group)?;
    let source = writer.finish()?;
    let owner_controls = edges(&source)?;
    let baseline = pool.usage().reserved_bytes;
    let job = Job {
        operations: vec![
            Operation::Partition {
                columns: vec![chopper_core::Column::Index(1)],
            },
            Operation::Balanced { files: 2 },
            Operation::Balanced { files: 2 },
            Operation::Balanced { files: 2 },
        ],
        ..job
    };
    let operations = &job.operations[1..];
    let one = apply(&source, &operations[0], 1, &job, &analysis, &ctx)?;
    let two = apply(&one, &operations[1], 2, &job, &analysis, &ctx)?;
    let serial = apply(&two, &operations[2], 3, &job, &analysis, &ctx)?;
    let expected = snapshot(&serial, &ctx)?;
    let expected_stats = vec![
        dataset_stats(&one, 2, source.groups, &ctx)?,
        dataset_stats(&two, 3, one.groups, &ctx)?,
        dataset_stats(&serial, 4, two.groups, &ctx)?,
    ];
    let mut stats = Stages::new(operations.len(), Reservation::new(&ctx))?;
    let fused = shared(&source, operations, 1, &ctx, &mut stats)?;
    ensure!(
        Arc::ptr_eq(&fused.data, &source.data)
            && snapshot(&fused, &ctx)? == expected
            && serde_json::to_vec(&stats)? == serde_json::to_vec(&expected_stats)?,
        "nested shared path changed rows/metadata/stats"
    );
    drop(stats);
    drop(fused);
    drop(serial);
    drop(two);
    drop(one);
    ensure!(
        pool.usage().reserved_bytes == baseline,
        "shared nested owners leaked"
    );
    let mut outcomes = Vec::new();
    for mode in [
        "success",
        "row_error",
        "end_error",
        "cancelled",
        "last_row_cancelled",
    ] {
        struct Sink<'a> {
            writer: DatasetWriter,
            pool: Arc<MemoryPool>,
            baseline: u64,
            cancel: &'a AtomicBool,
            mode: &'static str,
            rows: usize,
            ends: usize,
        }
        impl RowSink for Sink<'_> {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                assert!(self.pool.usage().reserved_bytes > self.baseline);
                self.writer.begin(lineage, exact)
            }
            fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
                ensure!(
                    self.pool.usage().reserved_bytes > self.baseline,
                    "nested row lost admission"
                );
                if self.mode == "row_error" {
                    anyhow::bail!("injected nested row error");
                }
                self.writer.row(group, row)?;
                self.rows += 1;
                if (self.mode == "cancelled" && self.rows == 1)
                    || (self.mode == "last_row_cancelled" && self.rows == 16)
                {
                    self.cancel.store(true, Ordering::Relaxed);
                }
                Ok(())
            }
            fn end(&mut self, group: Group) -> Result<()> {
                ensure!(
                    self.pool.usage().reserved_bytes > self.baseline,
                    "nested end released traversal/clone"
                );
                if self.mode == "end_error" {
                    anyhow::bail!("injected nested catalog error");
                }
                self.ends += 1;
                self.writer.end(group)
            }
        }
        let writer = DatasetWriter::new(&ctx)?;
        let before = pool.usage().reserved_bytes;
        let mut sink = Sink {
            writer,
            pool: pool.clone(),
            baseline: before,
            cancel: &cancel,
            mode,
            rows: 0,
            ends: 0,
        };
        let mut stats = Stages::new(operations.len(), Reservation::new(&ctx))?;
        let result = emit(&source, operations, 1, &ctx, &mut sink, &mut stats, None);
        ensure!(
            result.is_ok() == (mode == "success"),
            "nested {mode}: {result:?}"
        );
        if mode == "success" {
            let output = sink.writer.finish()?;
            ensure!(
                snapshot(&output, &ctx)? == expected
                    && serde_json::to_vec(&stats)? == serde_json::to_vec(&expected_stats)?,
                "nested emit parity changed"
            );
            drop(output);
        } else {
            if mode.ends_with("cancelled") {
                ensure!(
                    result.unwrap_err().to_string() == "job cancelled"
                        && sink.rows == if mode == "cancelled" { 1 } else { 16 }
                        && sink.ends == if mode == "cancelled" { 0 } else { 7 },
                    "nested missed first/last-row cancellation"
                );
            }
            drop(sink);
        }
        drop(stats);
        cancel.store(false, Ordering::Relaxed);
        ensure!(
            pool.usage().reserved_bytes == baseline,
            "nested {mode} leaked"
        );
        outcomes.push(json!({"mode":mode,"baseline_restored":true}));
    }
    #[cfg(all(target_os = "wasi", not(feature = "experimental-nested-balanced")))]
    hosted_guard(&root)?;
    drop(source);
    ensure!(
        ctx.used() == 0 && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "nested source leaked"
    );
    drop(ctx);
    ensure!(pool.usage().reserved_bytes == 0, "nested context leaked");
    fixture.close()?;
    ensure!(!root.try_exists()?, "nested fixture leaked");
    Ok(
        json!({"contract":"nested-balanced-lineage-admission-v1","owners":owner_controls,"outcomes":outcomes,
        "shared_ranges_and_emitted_rows_match_serial":true,"stage_statistics_equal":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

#[cfg(test)]
#[test]
fn nested_balanced_lineage_admission_and_cleanup() -> Result<()> {
    println!("CHOPPER_NESTED_LINEAGE_CONTRACT {}", run()?);
    Ok(())
}
