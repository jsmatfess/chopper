//! Borrowed domain parity and admitted child-tree ownership on native and WASI.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::atomic::Ordering;
mod execution;
#[cfg(any(
    feature = "experimental-constant-partition",
    feature = "experimental-consecutive-partitions",
    feature = "experimental-partition-balanced",
    feature = "experimental-streaming-chain",
))]
mod experimental;
#[cfg(feature = "experimental-consecutive-partitions")]
mod growth;

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let path = dir.path().to_owned();
    let cancel = Arc::new(AtomicBool::new(false));
    let ctx = Context::new(
        &Resources {
            workers: 1,
            temp_dir: Some(path.to_string_lossy().into_owned()),
            ..Default::default()
        },
        cancel.clone(),
        Arc::new(|_| {}),
    )?;
    let mut lineage = Vec::with_capacity(16);
    lineage.push(json!({"operation":0,"values":["界\n\"quoted",{"nested":[true,null,17]}]}));
    let parent = Group {
        offset: 0,
        rows: 0,
        lineage,
        exact: true,
    };
    let fields = vec!["界\n\"quoted".into(), String::new(), "é".into()];
    let columns = [2, 0, 1, 0];
    let entries = [
        Entry::part(3, u64::MAX),
        Entry::allocation(4, "界\n\"allocation"),
        Entry::values(5, FieldViews::owned(&fields), &columns),
    ];
    let expected_entries = [
        json!({"operation":3,"part":u64::MAX}),
        json!({"operation":4,"allocation":"界\n\"allocation"}),
        json!({"operation":5,"values":["é","界\n\"quoted","","界\n\"quoted"]}),
    ];
    let mut cases = Vec::new();
    for (entry, expected_entry) in entries.iter().zip(expected_entries) {
        let mut expected = parent.lineage.clone();
        expected.push(expected_entry);
        let canonical = serde_json::to_vec(&expected)?;
        ensure!(
            serde_json::to_vec(&Child {
                parent: &parent,
                entry
            })? == canonical,
            "borrowed child changed canonical serialized bytes"
        );
        ensure!(
            domain(&parent, entry, "child-contract", 9, &ctx)?
                == random::json_domain("child-contract", 9, &expected)?,
            "borrowed child changed seeded domain"
        );
        let probe = Arc::new(Workspace::new(1024 * 1024));
        let (values, memory) = build(
            &parent,
            entry,
            &ctx,
            Reservation::for_workspace(probe.clone()),
        )?;
        let peak = probe.peak() as usize;
        ensure!(
            values == expected && probe.used() == values.json_capacity()? as u64,
            "child construction changed tree or retained charge"
        );
        drop(values);
        drop(memory);
        ensure!(probe.used() == 0, "child probe leaked");
        for shared in [false, true] {
            for limit in [peak - 1, peak, peak + 1] {
                let pool = Arc::new(MemoryPool::new(if shared {
                    limit as u64
                } else {
                    u64::MAX
                }));
                let workspace = Arc::new(if shared {
                    Workspace::shared(2 * peak, pool.clone())
                } else {
                    Workspace::new(limit)
                });
                let result = build(
                    &parent,
                    entry,
                    &ctx,
                    Reservation::for_workspace(workspace.clone()),
                );
                if limit < peak {
                    let error = result.err().context("child edge accepted")?;
                    ensure!(
                        matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                        "child denial lost type"
                    );
                } else {
                    let (values, memory) = result?;
                    ensure!(values == expected, "edge changed child");
                    drop(values);
                    drop(memory);
                }
                ensure!(
                    workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                    "child edge leaked"
                );
            }
        }
        let pool = Arc::new(MemoryPool::new(peak as u64));
        let workspace = Arc::new(Workspace::shared(2 * peak, pool.clone()));
        let mut sibling = Reservation::for_workspace(workspace.clone());
        sibling.resize(1)?;
        let error = build(
            &parent,
            entry,
            &ctx,
            Reservation::for_workspace(workspace.clone()),
        )
        .err()
        .context("child competitor accepted")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && workspace.used() == 1,
            "child failure lost sibling"
        );
        drop(sibling);
        let (values, memory) = build(
            &parent,
            entry,
            &ctx,
            Reservation::for_workspace(workspace.clone()),
        )?;
        ensure!(values == expected, "child retry changed metadata");
        drop(values);
        drop(memory);
        ensure!(pool.usage().reserved_bytes == 0, "child retry leaked");
        cases.push(json!({"construction_bytes":peak,"local_shared_edge_checks":6,
            "canonical_bytes_and_seeded_domain_preserved":true,"competitor_retry":true,"final_reserved_bytes":0}));
    }
    #[cfg(feature = "experimental-streaming-chain")]
    {
        let entry = Entry::all_values(5, FieldViews::owned(&fields));
        let mut expected = parent.lineage.clone();
        expected.push(json!({"operation":5,"values":fields}));
        ensure!(
            serde_json::to_vec(&Child {
                parent: &parent,
                entry: &entry
            })? == serde_json::to_vec(&expected)?
                && domain(&parent, &entry, "borrowed-all-values", 9, &ctx)?
                    == random::json_domain("borrowed-all-values", 9, &expected)?,
            "all-values borrowed form changed canonical bytes/domain"
        );
    }
    #[cfg(feature = "experimental-constant-partition")]
    {
        let references = ["é", "界\n\"quoted", "", "é"];
        let entry = Entry::References {
            operation: 5,
            values: &references,
        };
        let mut expected = parent.lineage.clone();
        expected.push(json!({"operation":5,"values":references}));
        ensure!(
            serde_json::to_vec(&Child {
                parent: &parent,
                entry: &entry
            })? == serde_json::to_vec(&expected)?
                && domain(&parent, &entry, "borrowed-references", 9, &ctx)?
                    == random::json_domain("borrowed-references", 9, &expected)?,
            "reference-list borrowed form changed canonical bytes/domain"
        );
    }
    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let bad_columns = [fields.len()];
    ensure!(
        build(
            &parent,
            &Entry::values(0, FieldViews::owned(&fields), &bad_columns),
            &ctx,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err()
            && workspace.peak() == 0,
        "invalid selected column reached allocation"
    );
    #[cfg(feature = "experimental-consecutive-partitions")]
    let growth = growth::run(&parent, &ctx)?;
    #[cfg(not(feature = "experimental-consecutive-partitions"))]
    let growth = serde_json::Value::Null;
    cancel.store(true, Ordering::Relaxed);
    ensure!(
        build(
            &parent,
            &entries[0],
            &ctx,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err()
            && domain(&parent, &entries[0], "seed", 0, &ctx).is_err()
            && workspace.peak() == 0,
        "cancelled child reached allocation/domain"
    );
    drop(ctx);
    let execution = execution::run(&path)?;
    #[cfg(any(
        feature = "experimental-constant-partition",
        feature = "experimental-consecutive-partitions",
        feature = "experimental-partition-balanced",
        feature = "experimental-streaming-chain",
    ))]
    let experimental = experimental::run(&path)?;
    #[cfg(not(any(
        feature = "experimental-constant-partition",
        feature = "experimental-consecutive-partitions",
        feature = "experimental-partition-balanced",
        feature = "experimental-streaming-chain",
    )))]
    let experimental = serde_json::Value::Null;
    dir.close()?;
    ensure!(!path.try_exists()?, "child fixture leaked");
    Ok(
        json!({"contract":"child-lineage-admission-v1","cases":cases,
        "invalid_column_and_cancellation_before_allocation":true,"execution":execution,"experimental":experimental,"growth":growth,"fixture_directory_removed":true}),
    )
}

#[cfg(test)]
#[test]
fn child_lineage_admission_and_seeded_domain_parity() -> Result<()> {
    println!("CHOPPER_CHILD_LINEAGE_CONTRACT {}", run()?);
    Ok(())
}
