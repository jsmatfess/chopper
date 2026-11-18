use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
fn fixture(memory: Reservation) -> Result<Timings> {
    let mut builder = Builder::new(memory);
    builder.insert("z", 1.5)?;
    builder.insert("aa", 0.0)?;
    builder.insert("\u{754c}", -3.25)?;
    builder.finish()
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let required = NODE_ALLOWANCE + 6 + Shared::<BTreeMap<String, f64>>::controller_bytes();
    let canonical = serde_json::to_vec(&BTreeMap::from([
        ("z", 1.5),
        ("aa", 0.0),
        ("\u{754c}", -3.25),
    ]))?;

    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(required + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = fixture(Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = result.err().context("notes edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "notes denial lost type"
                );
            } else {
                let owner = result?;
                ensure!(
                    owner.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&owner)? == canonical,
                    "notes bytes/schema changed"
                );
                let copy = owner.clone();
                ensure!(
                    std::ptr::eq(
                        copy.get_key_value("z").unwrap().0.as_ptr(),
                        owner.get_key_value("z").unwrap().0.as_ptr()
                    ) && workspace.used() == required as u64,
                    "timing clone copied keys/grant"
                );
                drop(owner);
                ensure!(
                    workspace.used() == required as u64 && serde_json::to_vec(&copy)? == canonical,
                    "notes clone lost grant"
                );
                let decoded: Timings = serde_json::from_slice(&canonical)?;
                ensure!(
                    decoded == copy && decoded.reserved_bytes() == 0,
                    "caller notes schema changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "notes edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = fixture(Reservation::for_workspace(workspace.clone()))?;
    let error = fixture(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing notes accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "notes competition changed live owner"
    );
    drop(first);
    drop(fixture(Reservation::for_workspace(workspace.clone()))?);
    ensure!(workspace.used() == 0, "notes retry leaked");
    #[cfg(not(target_os = "wasi"))]
    {
        let owner = fixture(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = owner.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(owner);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(
            workspace.used() == 0 && pool.usage().reserved_bytes == 0,
            "concurrent notes last drop leaked"
        );
    }

    let workspace = Arc::new(Workspace::new(required));
    let empty = Builder::new(Reservation::for_workspace(workspace.clone())).finish()?;
    ensure!(
        empty.is_empty() && workspace.used() == 0,
        "empty timings allocated"
    );
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    builder.insert("a", 1.0)?;
    builder.insert("b", 2.0)?;
    builder.insert("c", 3.0)?;
    builder.insert("a", 4.0)?;
    ensure!(
        builder.insert("fourth", 5.0).is_err() && workspace.used() == 0,
        "timing stack bound allocated or changed"
    );
    let result = builder.finish()?;
    ensure!(
        result.len() == 3 && result["a"] == 4.0,
        "timing overwrite/bound changed values"
    );
    drop(result);
    ensure!(workspace.used() == 0, "timing overwrite leaked");
    let workspace = Arc::new(Workspace::new(NODE_ALLOWANCE + 2));
    let error = fixture(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("partial timing map admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ) && workspace.used() == 0,
        "partial timing key copy leaked"
    );
    Ok(
        json!({"required_bytes":required,"node_allowance_bytes":NODE_ALLOWANCE,"local_shared_edges":6,"shared_clone_and_last_drop":true,"competing_owner_retry":true,"caller_json_equal":true,"empty_no_allocation":true,"stack_observations_and_overwrite":true,"fourth_entry_rejected":true,"partial_key_copy_cleanup":true}),
    )
}
#[cfg(test)]
#[test]
fn analysis_timing_admission_and_lifetime() -> Result<()> {
    println!("CHOPPER_TIMING_CONTRACT {}", run()?);
    Ok(())
}
