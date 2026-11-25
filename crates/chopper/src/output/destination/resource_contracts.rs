use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

fn owner_controls() -> Result<()> {
    let relative = Path::new("./results/界");
    let resolved = std::path::absolute(relative)?;
    let mut paths = vec![resolved.as_path(), relative];
    if cfg!(windows) {
        paths.extend([
            Path::new(r"C:\root\界"),
            Path::new(r"\\?\C:\root\界"),
            Path::new(r"\\server\share\界"),
        ]);
    }
    for input in paths {
        let expected = std::path::absolute(input)?;
        let mut path = std::path::absolute(input)?;
        path.reserve_exact(97);
        let address = path.as_os_str().as_encoded_bytes().as_ptr();
        let capacity = path.capacity();
        let workspace = Arc::new(Workspace::new(capacity));
        let owner = DestinationPath::admit(path, Reservation::for_workspace(workspace.clone()))?;
        ensure!(
            owner.as_path() == expected
                && owner.as_path().as_os_str().as_encoded_bytes().as_ptr() == address
                && workspace.used() == capacity as u64,
            "destination resolution, allocation, or capacity changed"
        );
        drop(owner);
        ensure!(workspace.used() == 0, "resolved destination leaked");
    }

    let path = || {
        let mut path = resolved.clone();
        path.reserve_exact(97);
        path
    };
    let required = path().capacity();
    for limit in [required - 1, required, required + 1] {
        for shared in [false, true] {
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * required, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let attempt =
                DestinationPath::admit(path(), Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = attempt.err().context("destination edge admitted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "destination edge lost denial type: {error:#}"
                );
            } else {
                let owner = attempt?;
                ensure!(
                    workspace.used() == required as u64,
                    "destination undercharged"
                );
                drop(owner);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "destination edge leaked memory"
            );
        }
    }

    let pool = Arc::new(MemoryPool::new(2 * required as u64));
    let first = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let second = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let admit = |workspace: &Arc<Workspace>| {
        DestinationPath::admit(path(), Reservation::for_workspace(workspace.clone()))
    };
    let a = admit(&first)?;
    let b = admit(&second)?;
    ensure!(pool.usage().reserved_bytes == 2 * required as u64);
    drop(a);
    let mut peer = Reservation::for_workspace(first.clone());
    peer.resize(1)?;
    let error = admit(&first)
        .err()
        .context("competing destination admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && first.used() == 1
            && second.used() == required as u64
    );
    drop(peer);
    drop(admit(&first)?);
    ensure!(pool.usage().reserved_bytes == required as u64);
    drop(b);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "overlapping destinations leaked"
    );
    Ok(())
}

fn publication_controls() -> Result<()> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let root = std::path::absolute(dir.path())?;
    let output = root.join("results-界");
    let input = root.join("input.csv");
    fs::write(&input, "id\n1\n")?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        output: output.to_string_lossy().into_owned(),
        resources: chopper_core::Resources {
            memory_mb: 32.into(),
            max_record_bytes: 1024 * 1024,
            workers: 1,
            temp_dir: Some(root.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let limit = 64 * 1024 * 1024;
    let pool = Arc::new(MemoryPool::new(limit));
    let cancel = Arc::new(AtomicBool::new(false));
    let prepared = crate::engine::prepare_with_memory_pool(
        job,
        cancel.clone(),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let ctx = &prepared.ctx;
    let retained = pool.usage().reserved_bytes;
    let capacity = std::path::absolute(&output)?.capacity() as u64;
    let mut peer =
        Reservation::for_workspace(Arc::new(Workspace::shared(limit as usize, pool.clone())));
    let try_publication = |direct: bool| {
        if direct {
            DirectPublication::new(&prepared.job, ctx).map(drop)
        } else {
            execute(&prepared).map(drop)
        }
    };
    let no_stage = || -> Result<()> {
        for entry in fs::read_dir(&root)? {
            ensure!(
                !entry?
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".chopper-staging-"),
                "destination failure left staging"
            );
        }
        Ok(())
    };
    fs::write(&output, b"incumbent")?;
    for direct in [false, true] {
        peer.resize((limit - retained - capacity + 1) as usize)?;
        let held = pool.usage().reserved_bytes;
        let error = try_publication(direct)
            .err()
            .context("expected destination capacity denial")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && format!("{error:#}").contains("reserve absolute publication destination")
                && pool.usage().reserved_bytes == held
        );
        peer.resize(0)?;
        let error = try_publication(direct)
            .err()
            .context("accepted destination file")?;
        ensure!(
            format!("{error:#}").contains("output destination must be a new or empty directory")
        );
        ensure!(fs::read(&output)? == b"incumbent" && pool.usage().reserved_bytes == retained);
        no_stage()?;
    }
    fs::remove_file(&output)?;
    for direct in [false, true] {
        peer.resize((limit - retained - capacity) as usize)?;
        let held = pool.usage().reserved_bytes;
        let error = try_publication(direct)
            .err()
            .context("expected staging denial")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && !format!("{error:#}").contains("reserve absolute publication destination")
                && pool.usage().reserved_bytes == held,
            "staging denial leaked a destination charge: {error:#}"
        );
        peer.resize((limit - retained) as usize)?;
        let held = pool.usage().reserved_bytes;
        cancel.store(true, Ordering::Relaxed);
        let error = try_publication(direct)
            .err()
            .context("expected cancellation")?;
        ensure!(
            format!("{error:#}").contains("job cancelled") && pool.usage().reserved_bytes == held,
            "destination admission took priority over cancellation: {error:#}"
        );
        cancel.store(false, Ordering::Relaxed);
        peer.resize(0)?;
        ensure!(!output.try_exists()?);
        no_stage()?;
    }
    let before_stage = ctx.directory_reserved_bytes();
    let direct = DirectPublication::grouped_single(&prepared.job, None, ctx)?;
    ensure!(
        pool.usage().reserved_bytes
            == retained + capacity + (ctx.directory_reserved_bytes() - before_stage),
        "direct publication lost its live destination charge"
    );
    drop(direct);
    ensure!(pool.usage().reserved_bytes == retained && !output.try_exists()?);
    no_stage()?;
    execute(&prepared)?;
    ensure!(output.join("manifest.jsonl").is_file() && pool.usage().reserved_bytes == retained);
    drop(prepared);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "destination publication leaked"
    );
    no_stage()?;
    dir.close()?;
    Ok(())
}

pub(crate) fn run() -> Result<serde_json::Value> {
    owner_controls()?;
    publication_controls()?;
    Ok(json!({
        "contract": "absolute-publication-destination-v1",
        "capacity_edges": 6,
        "windows_prefixes": cfg!(windows),
        "independent_owners_and_peer_retry": true,
        "snapshot_and_direct_denial_cleanup": true,
        "cancellation_under_pressure": true,
        "direct_abandonment": true,
        "final_reserved_bytes": 0,
    }))
}

#[cfg(test)]
#[test]
fn absolute_destination_capacity_and_lifetimes() -> Result<()> {
    println!("CHOPPER_PUBLICATION_DESTINATION_CONTRACT {}", run()?);
    Ok(())
}
