use super::*;

pub(super) fn run(job: &Job, path: &std::path::Path) -> Result<serde_json::Value> {
    let mut bytes = Vec::new();
    for part in [b"id\n".as_slice(), b"1\n".as_slice()] {
        bytes.extend(zstd::stream::encode_all(part, 0)?);
    }
    let (actual, requests, _) = decode(&bytes, None)?;
    ensure!(actual == b"id\n1\n", "modern concatenation changed");
    for at in 1..=requests {
        let error = decode(&bytes, Some(at))
            .err()
            .context("modern allocation fault accepted")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ),
            "modern fault lost type"
        );
    }
    std::fs::write(path, &bytes)?;
    let workspace = Arc::new(Workspace::new(LIMIT));
    let mut retained = 0;
    with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut actual = Vec::new();
            reader.read_to_end(&mut actual)?;
            ensure!(actual == b"id\n1\n", "modern bytes changed");
            retained = workspace.used();
            Ok(())
        },
    )?;
    let required = workspace.peak() as usize;
    ensure!(workspace.used() == 0, "modern reader leaked");
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(LIMIT, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = with_input(
                job,
                Reservation::for_workspace(workspace.clone()),
                |mut reader| {
                    let mut actual = Vec::new();
                    reader.read_to_end(&mut actual)?;
                    ensure!(actual == b"id\n1\n", "modern edge bytes changed");
                    Ok(())
                },
            );
            if limit < required {
                let error = result.err().context("modern edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "modern edge lost type: {error:#}"
                );
            } else {
                result?;
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "modern edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new(required as u64));
    let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
    let mut competitor = Reservation::for_workspace(Arc::new(Workspace::shared(1, pool.clone())));
    competitor.resize(1)?;
    let result = with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut actual = Vec::new();
            reader.read_to_end(&mut actual)?;
            Ok(())
        },
    );
    ensure!(
        matches!(
            result
                .err()
                .context("modern competitor admitted")?
                .downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && pool.usage().reserved_bytes == 1,
        "modern competitor changed"
    );
    drop(competitor);
    with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut actual = Vec::new();
            reader.read_to_end(&mut actual)?;
            ensure!(actual == b"id\n1\n", "modern retry changed bytes");
            Ok(())
        },
    )?;
    let error = with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| -> Result<()> {
            reader.read_exact(&mut [0; 1])?;
            anyhow::bail!("cancelled")
        },
    )
    .err()
    .context("modern consumer failure lost")?;
    ensure!(
        error.to_string() == "cancelled"
            && workspace.used() == 0
            && pool.usage().reserved_bytes == 0,
        "modern consumer leaked"
    );
    let mut truncated = bytes.clone();
    truncated.pop();
    std::fs::write(path, truncated)?;
    let result = with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            std::io::copy(&mut reader, &mut std::io::sink())?;
            Ok(())
        },
    );
    ensure!(
        result.is_err() && workspace.used() == 0,
        "modern truncation accepted or leaked"
    );
    let mut skippable = 0x184d2a50u32.to_le_bytes().to_vec();
    skippable.extend_from_slice(&7u32.to_le_bytes());
    skippable.extend_from_slice(b"ignored");
    skippable.extend_from_slice(&bytes);
    std::fs::write(path, &skippable)?;
    with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut actual = Vec::new();
            reader.read_to_end(&mut actual)?;
            ensure!(actual == b"id\n1\n", "skippable frame changed bytes");
            Ok(())
        },
    )?;
    // Raw modern block with an 8 MiB declared window and unknown content size.
    let payload = b"id\n1\n";
    let mut large_window = vec![0x28, 0xb5, 0x2f, 0xfd, 0, ((23 - 10) << 3)];
    let block = ((payload.len() as u32) << 3) | 1;
    large_window.extend_from_slice(&block.to_le_bytes()[..3]);
    large_window.extend_from_slice(payload);
    ensure!(
        zstd::stream::decode_all(large_window.as_slice())? == payload,
        "window-limit fixture invalid"
    );
    std::fs::write(path, &large_window)?;
    let mut small = job.clone();
    small.resources.memory_mb = 16.into();
    let error = with_input(
        &small,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            std::io::copy(&mut reader, &mut std::io::sink())?;
            Ok(())
        },
    )
    .err()
    .context("modern window limit ignored")?;
    ensure!(
        error.downcast_ref::<MemoryAdmission>().is_none()
            && error.to_string().contains("memory")
            && workspace.used() == 0,
        "window limit behavior changed"
    );
    std::fs::write(path, LEGACY)?;
    with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |mut reader| {
            let mut actual = Vec::new();
            reader.read_to_end(&mut actual)?;
            ensure!(actual == LEGACY, "legacy-at-start detection changed");
            Ok(())
        },
    )?;

    let mut csv = b"id\n".to_vec();
    for _ in 0..65537 {
        csv.extend_from_slice(b"1\n");
    }
    std::fs::write(path, zstd::stream::encode_all(csv.as_slice(), 0)?)?;
    let pool = Arc::new(MemoryPool::new(LIMIT as u64));
    let mut cache = crate::profile::ProfileCache::with_memory_pool(pool.clone());
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    let error = cache
        .profile(
            job,
            cancel.clone(),
            Arc::new(move |progress| {
                if progress.rows >= 65536 {
                    signal.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }),
        )
        .err()
        .context("modern profile did not cancel")?;
    ensure!(
        cancel.load(std::sync::atomic::Ordering::Relaxed)
            && format!("{error:#}").contains("cancel"),
        "profile cancellation did not reach decoded rows"
    );
    drop(cache);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "modern profile cancellation leaked"
    );
    Ok(
        json!({"codec":"zstd","capacity_bytes":retained,"required_bytes":required,"dynamic_codec_allocations":true,"edge_checks":3,"local_edge_checks":3,"typed_shared_denials":2,"release_retries":1,"local_shared_edges":6,"allocation_fault_denials":requests,"competitor_release_retry":true,"consumer_error_cleanup":true,"truncated_error_cleanup":true,"skippable_parity":true,"window_limit_preserved":true,"legacy_at_start_detection_preserved":true,"public_profile_cancellation_cleanup":true,"final_reserved_bytes":0}),
    )
}
