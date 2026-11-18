use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let first = b"a\0\xff\0\0escaped";
    let next = "界\0longer\n\"boundary".repeat(3).into_bytes();
    let peak = first.len() + next.len();
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
            let mut key = BoundaryKey::new(Reservation::for_workspace(workspace.clone()));
            ensure!(!key.matches(&[]), "uninitialized empty key matched");
            key.replace(&[])?;
            ensure!(
                key.matches(&[]) && workspace.used() == 0,
                "empty tuple key allocated or did not initialize"
            );
            key.replace(first)?;
            ensure!(
                key.matches(first) && workspace.used() == first.len() as u64,
                "first key charge/parity changed"
            );
            let result = key.replace(&next);
            if limit < peak {
                let error = result.err().context("boundary growth edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "boundary denial lost type"
                );
                ensure!(
                    key.matches(first) && workspace.used() == first.len() as u64,
                    "boundary denial changed old key/grant"
                );
            } else {
                result?;
                ensure!(
                    key.matches(&next)
                        && workspace.used() == next.len() as u64
                        && workspace.peak() == peak as u64,
                    "boundary replacement overlap/parity changed"
                );
                key.replace(&[])?;
                ensure!(
                    key.matches(&[]) && workspace.used() == next.len() as u64,
                    "shorter key released retained capacity"
                );
            }
            drop(key);
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "boundary key leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(peak as u64));
    let workspace = Arc::new(Workspace::shared(2 * peak, pool.clone()));
    let mut key = BoundaryKey::new(Reservation::for_workspace(workspace.clone()));
    key.replace(first)?;
    let mut sibling = BoundaryKey::new(Reservation::for_workspace(workspace.clone()));
    sibling.replace(b"x")?;
    let error = key
        .replace(&next)
        .err()
        .context("boundary competitor accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && key.matches(first)
            && sibling.matches(b"x")
            && workspace.used() == (first.len() + 1) as u64,
        "boundary failed growth changed sibling or old key"
    );
    drop(sibling);
    key.replace(&next)?;
    drop(key);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "boundary retry leaked"
    );
    Ok(
        json!({"contract":"partition-boundary-key-admission-v1","local_shared_edge_checks":6,
        "empty_tuple_initialized_without_allocation":true,"replacement_overlap_bytes":peak,
        "denial_retains_old_key_and_sibling":true,"retained_capacity_after_shrink":true,
        "competitor_release_retry":true,"final_reserved_bytes":0}),
    )
}

#[cfg(test)]
#[test]
fn partition_boundary_key_capacity_and_replacement_overlap() -> Result<()> {
    println!("CHOPPER_PARTITION_BOUNDARY_CONTRACT {}", run()?);
    Ok(())
}
