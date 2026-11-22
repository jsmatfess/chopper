//! Shared native/WASI contract assertions. Keep production internals private;
//! only the explicitly enabled test reactor can invoke the engine wrapper.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::io::Write;
mod automatic_memory;
mod cleanup;
mod column;
mod direct;
mod manual_memory;
mod progress;

pub(super) fn input_adapters() -> Result<serde_json::Value> {
    let zstandard = input_zstandard::resource_contracts::run()?;
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let fixture_directory = dir.path().to_owned();
    let mut gzip = Vec::new();
    let mut zstd = Vec::new();
    for part in [b"id\n".as_slice(), b"1\n".as_slice()] {
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), Default::default());
        encoder.write_all(part)?;
        gzip.extend(encoder.finish()?);
        zstd.extend(zstd::stream::encode_all(part, 0)?);
    }
    let mut zip = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    zip.start_file("data.csv", zip::write::SimpleFileOptions::default())?;
    zip.write_all(b"id\n1\n")?;
    let zip = zip.finish()?.into_inner();
    let mut cases = Vec::new();
    for (name, encoded, capacity) in [
        ("plain", b"id\n1\n".to_vec(), 0),
        ("gzip", gzip, 8192 + input_gzip::capacity::<File>()),
        ("zstd", zstd, zstd::zstd_safe::DCtx::in_size()),
        ("zip", zip, 8192),
    ] {
        if name == "zstd" {
            cases.push(zstandard["standard_case"].clone());
            continue;
        }
        let path = dir.path().join(name);
        std::fs::write(&path, &encoded)?;
        let job = Job {
            input: path.to_string_lossy().into_owned(),
            ..Job::default()
        };
        let capacity = if name == "zip" {
            let workspace = Arc::new(Workspace::new(4 * 1024 * 1024));
            let mut retained = 0;
            with_input(&job, Reservation::for_workspace(workspace.clone()), |_| {
                retained = workspace.used() as usize;
                Ok(())
            })?;
            ensure!(retained > 8192, "ZIP metadata owner was not charged");
            ensure!(workspace.used() == 0, "ZIP probe leaked");
            retained
        } else {
            capacity
        };
        let required = capacity.max(if name == "zip" { encoded.len() } else { 0 });
        for limit in [required.saturating_sub(1), required, required + 1] {
            let pool = Arc::new(MemoryPool::new(limit as u64 + 7));
            let workspace = Arc::new(Workspace::shared(required + 1, pool.clone()));
            let mut pressure =
                Reservation::for_workspace(Arc::new(Workspace::shared(7, pool.clone())));
            pressure.resize(7)?;
            let mut called = false;
            let result = with_input(
                &job,
                Reservation::for_workspace(workspace.clone()),
                |mut source| {
                    called = true;
                    ensure!(
                        workspace.used() == capacity as u64,
                        "{name}: missing input charge"
                    );
                    let mut bytes = Vec::new();
                    source.read_to_end(&mut bytes)?;
                    ensure!(bytes == b"id\n1\n", "{name}: decoded bytes changed");
                    ensure!(
                        workspace.used() == capacity as u64,
                        "{name}: EOF released live reader charge"
                    );
                    Ok(())
                },
            );
            ensure!(
                result.is_ok() == (limit >= required),
                "{name}: edge {limit}: {result:?}"
            );
            ensure!(
                called == (limit >= required),
                "{name}: denied adapter invoked consumer"
            );
            ensure!(workspace.used() == 0, "{name}: edge reader leaked charge");
            ensure!(
                pool.usage().reserved_bytes == 7,
                "{name}: edge changed retained owner"
            );
            if limit < required {
                let error = result.unwrap_err();
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "{name}: denial lost shared-memory type: {error:#}"
                );
            }
            drop(pressure);
            ensure!(
                pool.usage().reserved_bytes == 0,
                "{name}: edge owner leaked charge"
            );
        }

        // Retain another real owner until the adapter is denied, then release
        // and retry the identical source. Local admission remains sufficient.
        if capacity != 0 {
            let pool = Arc::new(MemoryPool::new(required as u64 + 7));
            let workspace = Arc::new(Workspace::shared(required + 1, pool.clone()));
            let mut owner =
                Reservation::for_workspace(Arc::new(Workspace::shared(8, pool.clone())));
            owner.resize(8)?;
            let mut called = false;
            let error = with_input(&job, Reservation::for_workspace(workspace.clone()), |_| {
                called = true;
                Ok(())
            })
            .err()
            .context("retained shared owner must deny the adapter")?;
            ensure!(!called, "{name}: denied adapter invoked consumer");
            ensure!(
                matches!(
                    error.downcast_ref::<MemoryAdmission>(),
                    Some(MemoryAdmission::Shared { .. })
                ),
                "{name}: expected typed shared denial: {error:#}"
            );
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 8,
                "{name}: denial changed live owners"
            );
            drop(owner);
            ensure!(
                pool.usage().reserved_bytes == 0,
                "{name}: released owner remained charged"
            );
            with_input(
                &job,
                Reservation::for_workspace(workspace.clone()),
                |mut source| {
                    ensure!(
                        workspace.used() == capacity as u64,
                        "{name}: retry missing input charge"
                    );
                    let mut bytes = Vec::new();
                    source.read_to_end(&mut bytes)?;
                    ensure!(bytes == b"id\n1\n", "{name}: retry changed decoded bytes");
                    ensure!(
                        workspace.used() == capacity as u64,
                        "{name}: retry EOF released reader charge"
                    );
                    Ok(())
                },
            )?;
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "{name}: retry leaked charge"
            );
        }

        let workspace = Arc::new(Workspace::new(required));
        let error = with_input(
            &job,
            Reservation::for_workspace(workspace.clone()),
            |_| -> Result<()> { anyhow::bail!("cancelled") },
        )
        .err()
        .context("consumer error must propagate")?;
        ensure!(
            error.to_string() == "cancelled",
            "{name}: consumer error changed"
        );
        ensure!(
            workspace.used() == 0,
            "{name}: consumer error leaked charge"
        );
        let truncated = name == "gzip" || name == "zstd";
        if truncated {
            let mut broken = encoded.clone();
            broken.pop();
            std::fs::write(&path, broken)?;
            let result = with_input(
                &job,
                Reservation::for_workspace(workspace.clone()),
                |mut source| {
                    std::io::copy(&mut source, &mut std::io::sink())?;
                    Ok(())
                },
            );
            ensure!(result.is_err(), "{name}: truncated stream accepted");
            ensure!(
                workspace.used() == 0,
                "{name}: truncated stream leaked charge"
            );
        }
        cases.push(json!({
            "codec": name, "capacity_bytes": capacity, "required_bytes": required,
            "edge_checks": 3, "typed_shared_denials": 2 * usize::from(capacity != 0),
            "release_retries": usize::from(capacity != 0), "consumer_error_cleanup": true,
            "truncated_error_cleanup": if truncated { Some(true) } else { None },
            "final_reserved_bytes": 0,
        }));
    }
    dir.close()?;
    ensure!(
        !fixture_directory.try_exists()?,
        "contract fixture directory leaked"
    );
    let report = json!({
        "schema_version": 1, "contract": "input-adapter-resource-contracts-v1",
        "cases": cases, "fixture_directory_removed": true,
        "group_catalog": crate::storage::group_catalog_resource_contracts()?,
        "inspection_columns": input_inspection::resource_contracts()?,
        "inspection_result": inspection_result::resource_contracts::run()?,
        "inspection_sniff": input_sniff::resource_contracts::run()?,
        "zip_metadata": input_zip::resource_contracts::run()?,
        "zip_codec": input_zip::codec_contracts::run()?,
        "gzip_codec": input_gzip::resource_contracts::run()?,
        "zstandard_input": zstandard,
        "output_deflate_codec": crate::output::deflate_contracts::run()?,
        "output_zstandard_codec": crate::output::zstandard_contracts::run()?,
        "directory_paths": crate::storage::directory_resource_contracts()?,
        "publication_metadata": crate::output::publication_metadata_contracts::run()?,
        "publication_paths": crate::output::publication_path_contracts::run()?,
        "planned_metadata": crate::output::planned_metadata_contracts::run()?,
        "shuffle_metadata": group_metadata::resource_contracts::run()?,
        "child_metadata": child_metadata::resource_contracts::run()?,
        "partition_boundary": keys::resource_contracts::run()?,
        "temporary_construction": temporary_construction_resource_contracts()?,
        "job_manifest": crate::output::job_manifest_contracts::run()?,
        "prepared_job": job_owner::resource_contracts::run()?,
        "analysis_preview": preview::resource_contracts::run()?,
        "analysis_header": header::resource_contracts::run()?,
        "column_summaries": column_summaries::resource_contracts::run()?,
        "stage_stats": stages::resource_contracts::run()?,
        "analysis_text": analysis_text::resource_contracts::run()?,
        "progress_phase": crate::storage::progress_resource_contracts::run()?,
        "progress_publication": progress::run()?,
        "analysis_warnings": warnings::resource_contracts::run()?,
        "analysis_timings": timings::resource_contracts::run()?,
        "analysis_diagnostics": diagnostics::resource_contracts::run()?,
        "column_deserialization": column::run()?,
        "direct_run": direct::run()?,
        "execution_observation": crate::observation::resource_contracts()?,
        "prepared_observation":crate::observation::physical::resource_contracts()?,
        "automatic_memory": automatic_memory::run()?,
        "manual_memory": manual_memory::run()?,
        "cleanup_failure": cleanup::run()?,
    });
    #[cfg(target_os = "wasi")]
    let report = {
        let mut report = report;
        report["auto_fusion"] = auto_fusion()?;
        report
    };
    #[cfg(feature = "experimental-spill-blocks")]
    let report = {
        let mut report = report;
        report["spill_blocks"] = crate::storage::spill_block_resource_contracts()?;
        report
    };
    #[cfg(feature = "experimental-nested-balanced")]
    let report = {
        let mut report = report;
        report["nested_balanced"] = nested_balanced::resource_contracts::run()?;
        report
    };
    #[cfg(feature = "experimental-shuffle-partition")]
    let report = {
        let mut report = report;
        report["shuffle_partition"] = json!({
            "retained_parent": shuffle_partition::resource_contracts::retained_parent_retry()?,
            "terminal_emission": shuffle_partition::resource_contracts::terminal_emission()?,
            "publication": shuffle_partition::resource_contracts::publication::run()?,
            "public_preparation": shuffle_partition::resource_contracts::preparation::run()?,
        });
        report
    };
    #[cfg(any(
        feature = "experimental-consecutive-partitions",
        feature = "experimental-streaming-chain",
        feature = "experimental-partition-balanced"
    ))]
    let report = {
        let mut report = report;
        report["retained_execution"] = retained_execution::resource_contracts::run()?;
        report
    };
    Ok(report)
}

#[cfg(target_os = "wasi")]
fn auto_fusion() -> Result<serde_json::Value> {
    use std::sync::{atomic::Ordering::Relaxed, Mutex};
    let root = tempfile::tempdir_in("/tmp")?;
    let input = root.path().join("input.csv");
    let mut fixture = std::io::BufWriter::new(File::create(&input)?);
    writeln!(fixture, "id,key,payload")?;
    let payload = "x".repeat(112);
    for id in 0..45_000 {
        writeln!(fixture, "{id},{},{payload}", id % 3)?;
    }
    fixture.flush()?;
    drop(fixture);
    for cancel_at_boundary in [false, true] {
        let scratch = root.path().join("work");
        std::fs::create_dir(&scratch)?;
        let output = root.path().join(if cancel_at_boundary {
            "cancelled"
        } else {
            "retry"
        });
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            operations: vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                Operation::AssignProbabilistic {
                    groups: vec![Allocation {
                        name: "all".into(),
                        percent: "100".into(),
                    }],
                    strata: vec![],
                },
                Operation::Shuffle {
                    strategy: Shuffle::Auto,
                },
            ],
            resources: Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                temp_dir: Some(scratch.to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        };
        let capacity = 32 * 1024 * 1024;
        let pool = Arc::new(MemoryPool::new(capacity));
        let injected = Arc::new(AtomicBool::new(false));
        let cancel = Arc::new(AtomicBool::new(false));
        let peer = Arc::new(Mutex::new(Reservation::for_workspace(Arc::new(
            Workspace::shared(capacity as usize, pool.clone()),
        ))));
        let notify = {
            let (pool, injected, cancel, peer) =
                (pool.clone(), injected.clone(), cancel.clone(), peer.clone());
            Arc::new(move |progress: crate::storage::Progress| {
                if progress.phase == "Before prepared probabilistic spill"
                    && !injected.swap(true, Relaxed)
                {
                    let available = capacity - pool.reservation_counts().0;
                    peer.lock()
                        .unwrap()
                        .resize((available - 32 * 1024) as usize)
                        .unwrap();
                    cancel.store(cancel_at_boundary, Relaxed);
                }
                if progress.phase == "Retrying probabilistic assignment and shuffle" {
                    peer.lock().unwrap().resize(0).unwrap();
                }
            })
        };
        let result = run_with_memory_pool(job, cancel, notify, pool.clone());
        ensure!(
            injected.load(Relaxed),
            "Auto never reached fusion preparation"
        );
        drop(peer);
        if cancel_at_boundary {
            ensure!(
                result.is_err() && !output.exists(),
                "cancelled fusion published output"
            );
        } else {
            let analysis = result?;
            ensure!(
                analysis.rows == 45_000 && analysis.output_files == 3,
                "retry changed output"
            );
            ensure!(
                analysis.diagnostics["probabilistic_shuffle_retries"] == 1,
                "typed denial did not retry"
            );
        }
        ensure!(
            pool.reservation_counts().0 == 0,
            "fusion leaked working grants"
        );
        ensure!(
            std::fs::read_dir(&scratch)?.next().is_none(),
            "fusion leaked temporary files"
        );
        std::fs::remove_dir(scratch)?;
    }
    Ok(json!({"pre_emission_retry":true,"cancellation_cleanup":true}))
}
