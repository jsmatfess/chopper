pub(super) fn execute<T: Send>(
    work: impl FnOnce() -> anyhow::Result<T> + Send,
) -> anyhow::Result<T> {
    #[cfg(windows)]
    {
        // Embedded callers inherit the host's stack reserve. Match the CLI's 4 MiB.
        std::thread::scope(|scope| {
            let worker = std::thread::Builder::new()
                .stack_size(4 * 1024 * 1024)
                .spawn_scoped(scope, work)?;
            worker
                .join()
                .unwrap_or_else(|payload| std::panic::resume_unwind(payload))
        })
    }
    #[cfg(not(windows))]
    work()
}
