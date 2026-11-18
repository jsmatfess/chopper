//! Deterministic actual-binary controls, compiled only in resource-contract builds.
//! The parent holds the host validation lock and owns the barrier pipe.
pub fn checkpoint(phase: &str) {
    use std::io::Read;
    if std::env::var("CHOPPER_GUIDE_TEST_PHASE").as_deref() != Ok(phase) {
        return;
    }
    let Some(path) = std::env::var_os("CHOPPER_GUIDE_TEST_RELEASE") else {
        return;
    };
    static USED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    if USED.swap(true, std::sync::atomic::Ordering::Relaxed) {
        return;
    }
    eprintln!("guide test barrier: {phase}");
    let mut byte = [0];
    std::fs::File::open(path)
        .and_then(|mut f| f.read_exact(&mut byte))
        .expect("test parent must release barrier");
}
