use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
mod reopen;

pub(crate) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let fixture = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let fixture = tempfile::tempdir()?;
    let unicode = fixture.path().join("construct-\u{754c}-\u{e9}");
    std::fs::create_dir(&unicode)?;
    let path_bytes = unicode.as_os_str().len() + 1 + "test-".len() + RANDOM_BYTES;
    let mut parents = vec![
        unicode.clone(),
        unicode.join("."),
        unicode.join("missing").join(".."),
    ];
    let mut trailing = unicode.as_os_str().to_owned();
    trailing.push(std::path::MAIN_SEPARATOR_STR);
    parents.push(trailing.into());
    #[cfg(windows)]
    parents.extend(
        [
            r"C:\",
            r"\\server\share\directory",
            r"\\?\C:\directory\missing\..",
        ]
        .into_iter()
        .map(PathBuf::from),
    );
    let join_parity_cases = parents.len();
    for parent in parents {
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let expected = parent.join("test-abc123");
        let result = create_with(
            &parent,
            "test-",
            Reservation::for_workspace(workspace.clone()),
            || Ok(*b"abc123"),
            |path| {
                assert_eq!(path, expected);
                Ok(())
            },
        )?;
        drop(result);
        ensure!(workspace.used() == 0, "join parity case leaked");
    }
    for shared in [false, true] {
        for limit in [path_bytes - 1, path_bytes, path_bytes + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * path_bytes, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let mut called = 0;
            let result = create_with(
                &unicode,
                "test-",
                Reservation::for_workspace(workspace.clone()),
                || Ok(*b"abc123"),
                |path| {
                    called += 1;
                    assert_eq!(workspace.used(), path_bytes as u64);
                    assert!(path.file_name().unwrap() == "test-abc123");
                    Ok(())
                },
            );
            if limit < path_bytes {
                let error = result
                    .err()
                    .context("temporary construction edge accepted")?;
                ensure!(
                    called == 0
                        && matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                    "construction denial called filesystem or lost type"
                );
            } else {
                let ((), path, memory) = result?;
                ensure!(
                    called == 1 && workspace.used() == path.as_os_str().len() as u64,
                    "constructed path lost retained charge"
                );
                drop(path);
                drop(memory);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "construction edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(path_bytes as u64));
    let workspace = Arc::new(Workspace::shared(2 * path_bytes, pool.clone()));
    let mut sibling = Reservation::for_workspace(workspace.clone());
    sibling.resize(1)?;
    let error = create_with(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || Ok(*b"abc123"),
        |_| Ok(()),
    )
    .err()
    .context("construction competitor accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == 1,
        "construction denial changed sibling"
    );
    drop(sibling);
    let ((), path, memory) = create_with(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || Ok(*b"abc123"),
        |_| Ok(()),
    )?;
    drop(path);
    drop(memory);
    ensure!(workspace.used() == 0, "construction retry leaked");

    // Atomic collision retry must never attach a cleanup guard to someone else's path.
    let existing = unicode.join("test-aaaaaa");
    std::fs::write(&existing, b"sentinel")?;
    let workspace = Arc::new(Workspace::new(4 * path_bytes + 512));
    let mut names = [*b"aaaaaa", *b"bbbbbb"].into_iter();
    let mut opens = 0;
    let (mut file, path, memory) = create_with(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || Ok(names.next().unwrap()),
        |path| {
            opens += 1;
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(path)
        },
    )?;
    file.write_all(b"created")?;
    ensure!(
        opens == 2
            && std::fs::read(&existing)? == b"sentinel"
            && workspace.used() == path_bytes as u64,
        "collision replaced existing file or lost grant"
    );
    drop(file);
    std::fs::remove_file(&path)?;
    drop(path);
    drop(memory);
    std::fs::remove_file(&existing)?;

    let mut collisions = 0;
    let error = create_with::<()>(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || Ok(*b"aaaaaa"),
        |_| {
            collisions += 1;
            Err(io::ErrorKind::AlreadyExists.into())
        },
    )
    .err()
    .context("collision limit accepted")?;
    ensure!(
        collisions == ATTEMPTS && error.to_string().contains("collision") && workspace.used() == 0,
        "collision exhaustion leaked or was unbounded"
    );
    let error = create_with::<()>(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || Ok(*b"aaaaaa"),
        |_| Err(io::Error::from_raw_os_error(5)),
    )
    .err()
    .context("OS failure accepted")?;
    ensure!(
        error.downcast_ref::<io::Error>().is_some() && workspace.used() == 0,
        "OS error retained constructed path/grant"
    );
    drop(error);
    let error = create_with::<()>(
        &unicode,
        "test-",
        Reservation::for_workspace(workspace.clone()),
        || anyhow::bail!("injected random failure"),
        |_| panic!("random failure called filesystem"),
    )
    .err()
    .context("random failure accepted")?;
    ensure!(
        error.to_string().contains("random") && workspace.used() == 0,
        "random failure leaked"
    );
    for (parent, prefix) in [
        (Path::new("relative"), "test-"),
        (unicode.as_path(), "../escape-"),
    ] {
        ensure!(
            create_with(
                parent,
                prefix,
                Reservation::for_workspace(workspace.clone()),
                || Ok(*b"aaaaaa"),
                |_| Ok(())
            )
            .is_err()
                && workspace.used() == 0,
            "invalid construction input escaped validation"
        );
    }

    // Real production adapter retains tempfile's identity-preserving reopen.
    let (mut file, memory) = super::file(&unicode, Reservation::for_workspace(workspace.clone()))?;
    file.write_all(b"reopen-content")?;
    let retained = memory.bytes();
    let mut reopened = super::reopen(&file)?;
    let mut bytes = Vec::new();
    reopened.read_to_end(&mut bytes)?;
    ensure!(
        bytes == b"reopen-content" && workspace.used() == retained,
        "production reopen changed file/grant"
    );
    drop(reopened);
    let reopen = reopen::run(&unicode)?;
    drop(file);
    drop(memory);
    ensure!(
        workspace.used() == 0 && std::fs::read_dir(&unicode)?.next().is_none(),
        "production file cleanup leaked"
    );
    let fixture_path = fixture.path().to_owned();
    fixture.close()?;
    ensure!(!fixture_path.try_exists()?, "construction fixture leaked");
    Ok(
        serde_json::json!({"contract":"temporary-path-construction-admission-v1","local_shared_edge_checks":6,
        "admission_before_filesystem":true,"competitor_release_retry":true,"collision_preserves_existing_file":true,
        "collision_attempt_limit":ATTEMPTS,"random_and_os_failure_cleanup":true,"invalid_inputs_rejected":true,
        "production_reopen_and_cleanup":true,"join_parity_cases":join_parity_cases,"reopen":reopen,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

#[cfg(test)]
#[test]
fn temporary_construction_admission_collision_and_error_lifetimes() -> Result<()> {
    println!("CHOPPER_TEMPORARY_CONSTRUCTION_CONTRACT {}", run()?);
    Ok(())
}
