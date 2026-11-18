use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
const TEXT: &str = "phase,\"\n\u{754c}";
pub(crate) fn run() -> Result<serde_json::Value> {
    let required = TEXT.len() + Shared::controller_bytes();
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
            let result = ProgressPhase::copy(TEXT, Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = result.err().context("phase edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "phase denial type changed"
                );
            } else {
                let phase = result?;
                ensure!(
                    phase.reserved_bytes() == required as u64 && phase.capacity() == TEXT.len(),
                    "phase capacity not reconciled"
                );
                let copy = phase.clone();
                ensure!(
                    std::ptr::eq(copy.as_ptr(), phase.as_ptr())
                        && workspace.used() == required as u64,
                    "clone allocated"
                );
                drop(phase);
                ensure!(
                    workspace.used() == required as u64 && copy == TEXT,
                    "clone lost grant"
                );
                let decoded: ProgressPhase = serde_json::from_slice(&serde_json::to_vec(&copy)?)?;
                ensure!(
                    decoded == copy && decoded.reserved_bytes() == 0,
                    "caller decoding changed"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "phase edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = ProgressPhase::copy(TEXT, Reservation::for_workspace(workspace.clone()))?;
    ensure!(
        ProgressPhase::copy(TEXT, Reservation::for_workspace(workspace.clone())).is_err()
            && workspace.used() == required as u64,
        "competing owner changed"
    );
    drop(first);
    drop(ProgressPhase::copy(
        TEXT,
        Reservation::for_workspace(workspace.clone()),
    )?);
    for literal in [
        "",
        "Complete",
        "Profiling all input records",
        "Input profile complete",
    ] {
        let phase = ProgressPhase::literal(literal);
        let copy = phase.clone();
        ensure!(
            copy == literal
                && copy.reserved_bytes() == 0
                && copy.capacity() == 0
                && workspace.used() == 0,
            "static phase allocated"
        );
    }
    use std::fmt::Write as _;
    for (operation, total) in [(0, 0), (9, 10), (99, 100), (usize::MAX, usize::MAX)] {
        let mut text = OperationText::default();
        write!(&mut text, "Preparing operation {operation} of {total}")?;
        ensure!(
            text.as_str() == format!("Preparing operation {operation} of {total}"),
            "decimal formatting changed"
        );
    }
    let mut text = OperationText::default();
    text.write_str("?")?;
    ensure!(text.as_str() == "?", "UTF-8 formatter changed");
    ensure!(
        text.write_str(&"x".repeat(OPERATION_CAPACITY)).is_err() && text.as_str() == "?",
        "formatter overflow mutated text"
    );
    #[cfg(not(target_os = "wasi"))]
    {
        let phase = ProgressPhase::copy(TEXT, Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = phase.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(phase);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(workspace.used() == 0, "concurrent final drop leaked");
    }
    context_lifetime()?;
    Ok(
        serde_json::json!({"local_shared_edges":6,"required_bytes":required,"static_clone_zero":true,"competing_retry":true,"context_and_cache_lifetimes":true,"checked_decimal_utf8":true}),
    )
}
fn context_lifetime() -> Result<()> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;

    let pool = Arc::new(MemoryPool::new(128 * 1024 * 1024));
    let cached = Arc::new(Mutex::new(Progress::default()));
    let seen = Arc::new(AtomicU64::new(0));
    let ctx = Context::with_memory_pool(
        &chopper_core::Resources {
            workers: 1,
            temp_dir: Some(dir.path().to_string_lossy().into_owned()),
            ..Default::default()
        },
        Arc::new(AtomicBool::new(false)),
        {
            let cached = cached.clone();
            let seen = seen.clone();
            Arc::new(move |event| {
                seen.fetch_add(1, AtomicOrdering::Relaxed);
                *cached.lock().unwrap() = event;
            })
        },
        pool.clone(),
    )?;
    let workspace = ctx.workspace.clone();
    ctx.operation_event(9, 10)?;
    let retained = cached.lock().unwrap().clone();
    ensure!(
        retained.phase == "Preparing operation 9 of 10"
            && retained.rows == 0
            && retained.temp_bytes == ctx.used(),
        "real operation event changed"
    );
    let charge = retained.phase.reserved_bytes();
    let mut pressure = Reservation::new(&ctx);
    pressure.resize((ctx.memory as u64 / 2 - workspace.used()) as usize)?;
    let error = ctx
        .dynamic_event(TEXT, 3)
        .err()
        .context("event denial accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ) && seen.load(AtomicOrdering::Relaxed) == 1
            && cached.lock().unwrap().phase == retained.phase,
        "denial replaced cache/called callback"
    );
    ctx.event("Complete", 4)?;
    ensure!(
        cached.lock().unwrap().phase == "Complete"
            && cached.lock().unwrap().phase.reserved_bytes() == 0,
        "static event failed under pressure"
    );
    drop(pressure);
    ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
    ensure!(
        ctx.dynamic_event(TEXT, 0).unwrap_err().to_string() == "job cancelled",
        "cancellation changed"
    );
    drop(ctx);
    ensure!(
        workspace.used() == charge && retained.phase == "Preparing operation 9 of 10",
        "Context teardown lost phase grant"
    );
    drop(cached);
    ensure!(
        workspace.used() == charge,
        "cache teardown lost independent clone"
    );
    drop(retained);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "final phase leaked Workspace"
    );
    Ok(())
}
#[test]
fn progress_phase_contracts() -> Result<()> {
    run().map(|_| ())
}
