//! Automatic resolution against the same native/WASI shared ledger.
use super::*;

#[test]
fn automatic_memory_shared_reactor_contract() -> Result<()> {
    run().map(|_| ())
}

pub(super) fn run() -> Result<serde_json::Value> {
    const MIB: u64 = 1024 * 1024;
    let mut resources = Resources {
        memory_mb: MemoryBudget::Auto,
        max_record_bytes: 1024,
        workers: 1,
        ..Resources::default()
    };
    let pool = Arc::new(MemoryPool::new(128 * MIB));
    ensure!(
        pool.resolve_memory(&resources)? == 256,
        "automatic ceiling changed"
    );
    let mut retained = Reservation::for_workspace(Arc::new(Workspace::shared(
        128 * MIB as usize,
        pool.clone(),
    )));
    retained.resize(64 * MIB as usize)?;
    ensure!(
        pool.resolve_memory(&resources)? == 128,
        "automatic ignored live owner"
    );
    retained.resize(128 * MIB as usize)?;
    ensure!(
        pool.resolve_memory(&resources).is_err(),
        "automatic accepted no headroom"
    );
    ensure!(
        resources.memory_mb == MemoryBudget::Auto && resources.max_record_bytes == 1024,
        "automatic mutated requested limits"
    );
    resources.memory_mb = 256.into();
    ensure!(
        pool.resolve_memory(&resources)? == 256,
        "numeric budget changed"
    );
    drop(retained);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "automatic contract leaked"
    );
    Ok(json!({"live_grants": true, "numeric_preserved": true, "final_reserved_bytes": 0}))
}
