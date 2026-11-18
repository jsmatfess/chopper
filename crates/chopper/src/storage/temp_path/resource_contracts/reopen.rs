use super::*;

pub(super) fn run(parent: &Path) -> Result<serde_json::Value> {
    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let (mut source, memory) =
        super::super::file(parent, Reservation::for_workspace(workspace.clone()))?;
    source.write_all(b"abcdef")?;
    let retained = workspace.used();
    let mut first = super::super::reopen(&source)?;
    let mut second = super::super::reopen(&source)?;
    let mut a = [0; 2];
    let mut b = [0; 3];
    first.read_exact(&mut a)?;
    second.read_exact(&mut b)?;
    ensure!(
        &a == b"ab"
            && &b == b"abc"
            && source.as_file_mut().stream_position()? == 6
            && workspace.used() == retained,
        "reopen changed independent offsets or acquired a working grant"
    );
    drop(first);
    drop(second);

    #[cfg(not(target_os = "wasi"))]
    let replacement_check = {
        let moved = source.path().with_extension("original");
        std::fs::rename(source.path(), &moved)?;
        std::fs::write(source.path(), b"replacement")?;
        #[cfg(windows)]
        {
            let mut reopened = super::super::reopen(&source)?;
            let mut bytes = Vec::new();
            reopened.read_to_end(&mut bytes)?;
            ensure!(
                bytes == b"abcdef",
                "Windows reopen selected replacement path instead of original handle"
            );
        }
        #[cfg(unix)]
        {
            let error = super::super::reopen(&source)
                .err()
                .context("reopen accepted replacement inode")?;
            ensure!(
                error.kind() == io::ErrorKind::NotFound && error.get_ref().is_none(),
                "inode mismatch allocated a path-bearing error or lost kind"
            );
        }
        std::fs::remove_file(source.path())?;
        std::fs::remove_file(&moved)?;
        true
    };
    #[cfg(target_os = "wasi")]
    let replacement_check = false;

    #[cfg(any(unix, target_os = "wasi"))]
    {
        // Native replacement testing removed the name already; WASI removes its
        // own isolated source here. Open-by-name failure must carry no cloned path.
        if source.path().try_exists()? {
            std::fs::remove_file(source.path())?;
        }
        let error = super::super::reopen(&source)
            .err()
            .context("reopen accepted absent name")?;
        ensure!(
            error.kind() == io::ErrorKind::NotFound
                && error.get_ref().is_none()
                && workspace.used() == retained,
            "raw reopen error retained a cloned path/grant"
        );
    }
    drop(source);
    drop(memory);
    ensure!(workspace.used() == 0, "reopen ownership leaked");
    Ok(
        serde_json::json!({"independent_offsets":true,"no_error_path_copy_or_grant":true,
        "native_replacement_identity_checked":replacement_check,"final_reserved_bytes":0}),
    )
}
