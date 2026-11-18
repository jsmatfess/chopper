//! Clone admission and active output-catalog lineage ownership on native/WASI.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

fn fixture() -> Group {
    let mut text = String::with_capacity(4096);
    text.push_str("\u{754c}\n\"quoted\\value");
    let mut lineage = Vec::with_capacity(8);
    lineage.push(json!({"operation":2,"values":["", "\u{e9}", {"nested":[true, null, 17]}]}));
    lineage.push(json!({"allocation":text}));
    Group {
        offset: 91,
        rows: 7,
        lineage,
        exact: false,
    }
}

fn cloned(source: &Group, memory: Reservation) -> Result<PlannedMetadata<Group>> {
    PlannedMetadata::clone_lineage(source, memory, |group| group)
}

fn owner_controls() -> Result<serde_json::Value> {
    let source = fixture();
    let expected = serde_json::to_vec(&source)?;
    let allowance = source.json_capacity()?;
    let probe = Arc::new(Workspace::new(1024 * 1024));
    let owner = cloned(&source, Reservation::for_workspace(probe.clone()))?;
    let retained = owner.value.json_capacity()?;
    ensure!(
        retained > 0 && retained <= allowance && probe.used() == retained as u64,
        "clone grant/capacity changed"
    );
    ensure!(
        serde_json::to_vec(&owner.value)? == expected,
        "clone changed metadata"
    );
    drop(owner);
    ensure!(probe.used() == 0, "clone probe leaked");
    let mut edges = 0;
    for shared in [false, true] {
        for limit in [allowance - 1, allowance, allowance + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * allowance, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let built = AtomicBool::new(false);
            let attempt = PlannedMetadata::clone_lineage(
                &source,
                Reservation::for_workspace(workspace.clone()),
                |group| {
                    built.store(true, Ordering::Relaxed);
                    group
                },
            );
            if limit < allowance {
                let error = attempt.err().context("clone edge accepted")?;
                ensure!(
                    !built.load(Ordering::Relaxed),
                    "clone builder ran before admission"
                );
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "clone denial lost type"
                );
            } else {
                let owner = attempt?;
                ensure!(
                    built.load(Ordering::Relaxed) && serde_json::to_vec(&owner.value)? == expected,
                    "admitted clone changed"
                );
                drop(owner);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "clone edge leaked"
            );
            edges += 1;
        }
    }
    let pool = Arc::new(MemoryPool::new(allowance as u64));
    let workspace = Arc::new(Workspace::shared(2 * allowance, pool.clone()));
    let mut competitor = Reservation::for_workspace(workspace.clone());
    competitor.resize(1)?;
    let error = cloned(&source, Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing clone accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "competing clone leaked"
    );
    drop(competitor);
    let owner = cloned(&source, Reservation::for_workspace(workspace.clone()))?;
    drop(owner);
    ensure!(pool.usage().reserved_bytes == 0, "clone retry leaked");

    let pool = Arc::new(MemoryPool::new(2 * allowance as u64));
    let workspace = Arc::new(Workspace::shared(2 * allowance, pool.clone()));
    let first = cloned(&source, Reservation::for_workspace(workspace.clone()))?;
    let second = cloned(&source, Reservation::for_workspace(workspace.clone()))?;
    drop(source);
    ensure!(
        workspace.used() == 2 * retained as u64,
        "source drop lost clone charges"
    );
    struct Writer {
        workspace: Arc<Workspace>,
        held: u64,
        fail: bool,
    }
    impl Write for Writer {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            assert_eq!(self.workspace.used(), self.held);
            if self.fail {
                Err(std::io::Error::other(
                    "injected cloned catalog serialization failure",
                ))
            } else {
                Ok(bytes.len())
            }
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    for fail in [false, true] {
        let mut writer = Writer {
            workspace: workspace.clone(),
            held: 2 * retained as u64,
            fail,
        };
        ensure!(
            serde_json::to_writer(&mut writer, &first.value).is_err() == fail,
            "clone serialization outcome changed"
        );
    }
    drop(first);
    ensure!(
        workspace.used() == retained as u64,
        "other clone owner released early"
    );
    drop(second);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "concurrent clone owners leaked"
    );
    Ok(
        json!({"source_allowance_bytes":allowance,"clone_retained_bytes":retained,"local_shared_edge_checks":edges,"denied_builder_not_called":true,"competitor_retry":true,"independent_clones":2,"serialization_failure_retains_owner":true,"metadata_blake3":blake3::hash(&expected).to_hex().as_str(),"final_reserved_bytes":0}),
    )
}

fn writer_controls() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let directory = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let directory = tempfile::tempdir()?;
    let root = directory.path().to_owned();
    let pool = Arc::new(MemoryPool::new(16 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let resources = chopper_core::Resources {
        workers: 1,
        temp_bytes: Some(4096),
        temp_dir: Some(root.to_string_lossy().into_owned()),
        ..Default::default()
    };
    let ctx =
        Context::with_memory_pool(&resources, cancel.clone(), Arc::new(|_| {}), pool.clone())?;
    let mut job = Job::default();
    job.limits.rows = Some(1);
    let row = Row {
        id: 1,
        ordinal: 0,
        key: Vec::new(),
        fields: vec!["\u{754c},quoted\nvalue".to_owned()],
    };
    let mut outcomes = Vec::new();
    for mode in [
        "completed",
        "cancelled",
        "catalog_error",
        "denied_retry",
        "empty_allocation",
    ] {
        let mut writer = PlanWriter::new(&job, None, &ctx)?;
        let mut group = writer.begin(fixture().lineage, false);
        let baseline = pool.usage().reserved_bytes;
        if mode == "denied_retry" {
            // Reserve all remaining process capacity, then release it and retry
            // the same writer before prefix/data emission. Indices stay intact.
            let remaining = pool.usage().limit_bytes - pool.usage().reserved_bytes;
            let mut competitor = Reservation::for_workspace(Arc::new(Workspace::shared(
                remaining as usize,
                pool.clone(),
            )));
            competitor.resize(remaining as usize)?;
            let error = writer
                .open(&group)
                .err()
                .context("chunk clone admission accepted")?;
            let EncodedTarget::Snapshot { data, .. } = &writer.target else {
                unreachable!()
            };
            ensure!(
                matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Shared { .. })
                ) && writer.chunk.is_none()
                    && writer.files == 0
                    && data.buffer().is_empty()
                    && data.get_ref().is_empty(),
                "denied open changed index or emitted prefix"
            );
            drop(competitor);
        }
        if mode == "empty_allocation" {
            writer.end(group)?;
        } else {
            writer.row(&mut group, &row)?;
            let retained = writer
                .chunk
                .as_ref()
                .context("missing active chunk")?
                ._memory
                .bytes();
            ensure!(
                retained > 0 && pool.usage().reserved_bytes >= baseline + retained,
                "active chunk clone lost grant"
            );
            if mode == "cancelled" {
                cancel.store(true, Ordering::Relaxed);
                ensure!(writer.end(group).is_err(), "cancelled group accepted");
                ensure!(
                    writer.chunk.is_some() && pool.usage().reserved_bytes >= baseline + retained,
                    "cancellation released still-owned chunk"
                );
                cancel.store(false, Ordering::Relaxed);
            } else if mode == "catalog_error" {
                // Exhaust the real temporary-space budget and bypass catalog
                // buffering so serialization fails while the clone is owned.
                let EncodedTarget::Snapshot { data, mut catalog } = writer.target else {
                    unreachable!()
                };
                catalog.flush()?;
                let catalog = catalog.into_inner().map_err(|e| e.into_error())?;
                writer.target = EncodedTarget::Snapshot {
                    data,
                    catalog: BufWriter::with_capacity(0, catalog),
                };
                let mut blocker = ctx.file()?;
                let zeros = [0u8; 4096];
                blocker.write_all(&zeros[..ctx.remaining_temp() as usize])?;
                let result = writer.end(group);
                ensure!(result.is_err(), "exhausted catalog accepted writes");
                ensure!(writer.chunk.is_none(), "failed close kept extracted chunk");
            } else {
                // A strict one-row cap closes the first clone before opening
                // the next, without changing lineage or source counters.
                writer.row(&mut group, &row)?;
                writer.end(group)?;
            }
        }
        drop(writer);
        ensure!(
            ctx.used() == 0 && pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "writer failure left clone/file/buffer owners"
        );
        outcomes.push(json!({"mode":mode,"idle_directory_baseline_restored":true}));
    }
    let mut dataset_writer = DatasetWriter::new(&ctx)?;
    let mut group = dataset_writer.begin(fixture().lineage, false);
    dataset_writer.row(&mut group, &row)?;
    dataset_writer.row(&mut group, &row)?;
    dataset_writer.end(group)?;
    let empty = dataset_writer.begin(vec![json!({"allocation":"empty"})], false);
    dataset_writer.end(empty)?;
    let dataset = dataset_writer.finish()?;
    let before_plan = pool.usage().reserved_bytes;
    let output = plan(&dataset, &job, None, &ctx)?;
    ensure!(
        output.files == 3,
        "materialized planning lost split/empty allocation"
    );
    let mut csv = Vec::new();
    output.data.reader()?.read_to_end(&mut csv)?;
    ensure!(
        csv == "\"\u{754c},quoted\nvalue\"\n".repeat(2).as_bytes(),
        "materialized plan changed CSV bytes"
    );
    let chunks = output.chunks()?.collect::<Result<Vec<_>>>()?;
    ensure!(
        chunks
            .iter()
            .map(|chunk| chunk.group.rows)
            .collect::<Vec<_>>()
            == [0, 1, 0],
        "materialized clone counters changed"
    );
    ensure!(
        chunks.iter().all(|chunk| chunk.group.offset == 0)
            && chunks.iter().map(|chunk| chunk.rows).collect::<Vec<_>>() == [1, 1, 0],
        "materialized clone offsets/output rows changed"
    );
    ensure!(
        chunks[0].group.lineage == fixture().lineage
            && chunks[2].group.lineage == [json!({"allocation":"empty"})],
        "materialized lineage changed"
    );
    drop(chunks);
    drop(output);
    ensure!(
        pool.usage().reserved_bytes == before_plan,
        "materialized plan clone outlived output"
    );
    drop(dataset);
    ensure!(
        pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
        "materialized dataset owners leaked"
    );
    drop(ctx);
    ensure!(pool.usage().reserved_bytes == 0, "writer context leaked");
    directory.close()?;
    ensure!(!root.try_exists()?, "planned metadata fixture leaked");
    Ok(
        json!({"outcomes":outcomes,"materialized_dataset_csv_and_catalog_parity":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

pub(crate) fn run() -> Result<serde_json::Value> {
    Ok(
        json!({"contract":"planned-lineage-metadata-resource-contract-v1","owners":owner_controls()?,"writer":writer_controls()?}),
    )
}

#[cfg(test)]
#[test]
fn planned_lineage_clone_admission_and_lifetimes() -> Result<()> {
    println!("CHOPPER_PLANNED_LINEAGE_CONTRACT {}", run()?);
    Ok(())
}
