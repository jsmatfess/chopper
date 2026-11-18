//! Shared native/WASI checks for publication metadata admission and lifetimes.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

fn group(lineage: Vec<serde_json::Value>) -> Group {
    Group {
        offset: 0,
        rows: 0,
        lineage,
        exact: false,
    }
}

fn name_controls() -> Result<serde_json::Value> {
    let mut job = Job {
        operations: vec![Operation::Partition {
            columns: vec![Column::Index(0)],
        }],
        ..Default::default()
    };
    let header = vec![" name ".to_owned()];
    let fixture = group(vec![
        json!({"operation":0,"values":["../\u{754c}: a"]}),
        json!({"allocation":"..."}),
        json!({"part":u64::MAX}),
    ]);
    let mut cases = Vec::new();
    for (compression, suffix) in [
        (Compression::None, ""),
        (Compression::Zip, ""),
        (Compression::Gzip, ".gz"),
        (Compression::Zstd, ".zst"),
    ] {
        job.compression = compression;
        let workspace = Arc::new(Workspace::new(4096));
        let name = output_name(
            u64::MAX,
            &fixture,
            &job,
            Some(&header),
            Reservation::for_workspace(workspace.clone()),
        )?;
        let expected = format!("name-_\u{754c}__a-allocation-empty-split-18446744073709551615-part-18446744073709551615.csv{suffix}");
        ensure!(
            name.as_str() == expected,
            "publication name schema changed: {}",
            name.as_str()
        );
        ensure!(
            workspace.used() == name.value.capacity() as u64,
            "name lost retained grant"
        );
        cases.push(json!({"suffix":suffix,"name":name.as_str(),"retained_bytes":workspace.used()}));
        drop(name);
        ensure!(workspace.used() == 0, "name control leaked");
    }
    job.compression = Compression::Zstd;
    let wide = group(vec![json!({"allocation":"\u{754c}".repeat(200)})]);
    let workspace = Arc::new(Workspace::new(4096));
    let name = output_name(
        u64::MAX,
        &wide,
        &job,
        None,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        name.as_str().len() <= NAME_CAPACITY
            && name
                .as_str()
                .ends_with("-part-18446744073709551615.csv.zst"),
        "wide UTF-8 suffix/truncation changed"
    );
    let wide_name = name.as_str().to_owned();
    drop(name);
    let numeric = group(vec![json!({"operation":0,"values":[""]})]);
    let name = output_name(
        1,
        &numeric,
        &job,
        None,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        name.as_str() == "column-1-empty-part-00000001.csv.zst",
        "numeric header fallback changed"
    );
    drop(name);
    let empty = group(Vec::new());
    let name = output_name(
        1,
        &empty,
        &job,
        None,
        Reservation::for_workspace(workspace.clone()),
    )?;
    ensure!(
        name.as_str() == "part-00000001.csv.zst",
        "empty lineage name changed"
    );
    drop(name);
    // Preallocation must include both the final string and numeric-label scratch.
    let required = NAME_CAPACITY + LABEL_CAPACITY;
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(4096, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let attempt = output_name(
                1,
                &fixture,
                &job,
                None,
                Reservation::for_workspace(workspace.clone()),
            );
            if limit < required {
                let error = attempt.err().context("name edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "name denial lost type"
                );
            } else {
                drop(attempt?);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "name edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(required as u64));
    let workspace = Arc::new(Workspace::shared(4096, pool.clone()));
    let mut competitor = Reservation::for_workspace(workspace.clone());
    competitor.resize(1)?;
    let error = output_name(
        1,
        &fixture,
        &job,
        None,
        Reservation::for_workspace(workspace.clone()),
    )
    .err()
    .context("competing name accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "competing name denial leaked"
    );
    drop(competitor);
    let name = output_name(
        1,
        &fixture,
        &job,
        None,
        Reservation::for_workspace(workspace.clone()),
    )?;
    drop(name);
    ensure!(pool.usage().reserved_bytes == 0, "name retry leaked");
    Ok(
        json!({"cases":cases,"wide_name":wide_name,"construction_bytes":required,"local_shared_edge_checks":6,"competitor_retry":true,"final_reserved_bytes":0}),
    )
}

fn batch_controls() -> Result<serde_json::Value> {
    let required = 2 * std::mem::size_of::<PublicationTask>();
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(required + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let attempt = PublicationBatch::new(2, Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = attempt.err().context("batch edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "batch denial lost type"
                );
            } else {
                let batch = attempt?;
                ensure!(
                    workspace.used()
                        == (batch.tasks.capacity() * std::mem::size_of::<PublicationTask>()) as u64,
                    "batch descriptors lost grant"
                );
                drop(batch);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "batch edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(required as u64));
    let workspace = Arc::new(Workspace::shared(2 * required + 1, pool.clone()));
    let first = PublicationBatch::new(1, Reservation::for_workspace(workspace.clone()))?;
    let second = PublicationBatch::new(1, Reservation::for_workspace(workspace.clone()))?;
    ensure!(
        pool.usage().reserved_bytes == required as u64,
        "concurrent batch grant changed"
    );
    let error = PublicationBatch::new(1, Reservation::for_workspace(workspace.clone()))
        .err()
        .context("third batch accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ),
        "batch denial lost shared type"
    );
    drop(first);
    let retry = PublicationBatch::new(1, Reservation::for_workspace(workspace.clone()))?;
    drop(second);
    drop(retry);
    ensure!(pool.usage().reserved_bytes == 0, "batch retry leaked");
    Ok(
        json!({"task_slot_bytes":required / 2,"two_slot_bytes":required,"local_shared_edge_checks":6,"concurrent_batches":2,"competitor_retry":true,"final_reserved_bytes":0}),
    )
}

fn task_controls() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let directory = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let directory = tempfile::tempdir()?;
    let root = directory.path().to_owned();
    let pool = Arc::new(MemoryPool::new(16 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let resources = chopper_core::Resources {
        workers: if cfg!(target_os = "wasi") { 1 } else { 2 },
        temp_dir: Some(root.to_string_lossy().into_owned()),
        ..Default::default()
    };
    let ctx =
        Context::with_memory_pool(&resources, cancel.clone(), Arc::new(|_| {}), pool.clone())?;
    let job = Job::default();
    let mut writer = PlanWriter::new(&job, None, &ctx)?;
    for index in 0..2 {
        let mut group = writer.begin(vec![json!({"part":index + 1})], false);
        writer.row(
            &mut group,
            &Row {
                id: index,
                ordinal: index,
                key: Vec::new(),
                fields: vec![index.to_string()],
            },
        )?;
        writer.end(group)?;
    }
    let plan = writer.finish()?;
    let baseline = pool.usage().reserved_bytes;
    let mut outcomes = Vec::new();
    for mode in ["success", "consumer_error", "worker_error", "cancelled"] {
        let stage = root.join(mode);
        std::fs::create_dir(&stage)?;
        let mut batch = PublicationBatch::new(2, Reservation::new(&ctx))?;
        for chunk in plan.chunks()? {
            batch.push(chunk?)?;
        }
        let descriptor_bytes = batch._memory.bytes();
        let before = pool.usage().reserved_bytes;
        cancel.store(mode == "cancelled", Ordering::Relaxed);
        ctx.for_each_batch(&mut batch.tasks, |task| {
            let path = if mode == "worker_error" && task.chunk.index == 2 {
                stage.join("missing")
            } else {
                stage.clone()
            };
            task.completed = Some(write_chunk(&task.chunk, &plan, &job, None, &path, &ctx));
        });
        cancel.store(false, Ordering::Relaxed);
        let successes = batch
            .tasks
            .iter()
            .filter(|task| task.completed.as_ref().unwrap().is_ok())
            .count();
        ensure!(
            successes
                == match mode {
                    "cancelled" => 0,
                    "worker_error" => 1,
                    _ => 2,
                },
            "worker outcome changed"
        );
        ensure!(
            pool.usage().reserved_bytes == before + successes as u64 * NAME_CAPACITY as u64,
            "completed result names lost grant"
        );
        let outcome: Result<()> = (|| {
            for (index, task) in batch.tasks.drain(..).enumerate() {
                let completed = task.completed.context("missing publication completion")??;
                ensure!(
                    task.chunk.index == index as u64 + 1,
                    "batch collection reordered tasks"
                );
                ensure!(
                    completed.name.as_str()
                        == format!("split-{}-part-{:08}.csv", index + 1, index + 1),
                    "task name changed"
                );
                ensure!(
                    batch._memory.bytes() == descriptor_bytes,
                    "drain released batch capacity early"
                );
                if mode == "consumer_error" {
                    anyhow::bail!("injected manifest collection failure");
                }
            }
            Ok(())
        })();
        ensure!(
            outcome.is_ok() == (mode == "success"),
            "collection outcome changed"
        );
        // A drained vector still owns capacity; errors also drop uncollected tasks.
        ensure!(
            batch._memory.bytes() == descriptor_bytes,
            "collection released descriptor capacity early"
        );
        drop(batch);
        ensure!(
            pool.usage().reserved_bytes == baseline,
            "batch/result/decoded owners survived error or completion"
        );
        std::fs::remove_dir_all(&stage)?;
        outcomes.push(json!({"mode":mode,"successful_tasks":successes,"baseline_restored":true}));
    }
    drop(plan);
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "publication task context leaked"
    );
    directory.close()?;
    ensure!(!root.try_exists()?, "publication task fixture leaked");
    Ok(json!({"outcomes":outcomes,"fixture_directory_removed":true,"final_reserved_bytes":0}))
}

pub(crate) fn run() -> Result<serde_json::Value> {
    Ok(
        json!({"contract":"publication-metadata-resource-contract-v1","names":name_controls()?,"batches":batch_controls()?,"tasks":task_controls()?}),
    )
}

#[cfg(test)]
#[test]
fn publication_metadata_admission_and_owner_lifetimes() -> Result<()> {
    println!("CHOPPER_PUBLICATION_METADATA_CONTRACT {}", run()?);
    Ok(())
}
