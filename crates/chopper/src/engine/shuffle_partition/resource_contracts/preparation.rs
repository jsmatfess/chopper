//! Enter through public preparation with immutable file input and a caller-owned
//! shared pool. Progress callbacks hold/release only synthetic competing capacity;
//! production admission and execution have no test-only branch.
use super::*;
use std::sync::Mutex;

fn prepared_snapshot(prepared: &Prepared) -> Result<(serde_json::Value, Vec<u8>)> {
    ensure!(
        !std::path::Path::new(&prepared.job.output).try_exists()?,
        "preparation published before confirmation"
    );
    output::execute(prepared)?;
    let (chunks, bytes) =
        publication::published(std::path::Path::new(&prepared.job.output), 1_000_000)?;
    let mut seen = [false; 16];
    let wide = "late-key".repeat(40_000);
    for chunk in &chunks {
        let raw = std::fs::read(
            std::path::Path::new(&prepared.job.output)
                .join(chunk["path"].as_str().context("missing CSV path")?),
        )?;
        let decoder = DecodeReader::new(raw.as_slice(), "utf-16le")?;
        let mut parser = Parser::new(
            BufReader::new(decoder),
            prepared.job.output_csv.clone(),
            prepared.job.resources.max_record_bytes,
        );
        ensure!(
            parser.next_record()? == Some(vec!["id".into(), "key".into(), "text".into()]),
            "public CSV header changed"
        );
        let mut rows = 0u64;
        while let Some(row) = parser.next_record()? {
            ensure!(row.len() == 3, "public output field count changed");
            let id = row[0].parse::<usize>()?;
            ensure!(
                id < seen.len() && !seen[id],
                "public output duplicated/changed ID"
            );
            seen[id] = true;
            let key = if id < 8 { "a" } else { &wide };
            ensure!(
                row[1] == key && row[2] == "quote,\"界\"\nline",
                "public output changed fields"
            );
            ensure!(
                chunk["lineage"][0]["part"] == if id < 8 { 1 } else { 2 }
                    && chunk["lineage"][1]["values"][0] == key
                    && chunk["lineage"][2]["values"][0] == row[2],
                "public output changed group membership"
            );
            rows += 1;
        }
        ensure!(chunk["rows"] == rows, "public output row metadata changed");
    }
    ensure!(
        seen.into_iter().all(|present| present),
        "public output omitted IDs"
    );
    Ok((
        json!({
            "encoded_blake3":blake3::hash(&bytes).to_hex().to_string(),
            "encoded_bytes":bytes.len(), "chunks":chunks,
            "rows":prepared.analysis.rows, "columns":prepared.analysis.columns,
            "header":prepared.analysis.header, "groups":prepared.analysis.groups,
            "stages":prepared.analysis.stages, "logical_digest":prepared.analysis.logical_digest,
            "output_files":prepared.analysis.output_files,
            "output_csv_bytes":prepared.analysis.output_csv_bytes,
        }),
        bytes,
    ))
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let fixture = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let fixture = tempfile::tempdir()?;
    let fixture_path = fixture.path().to_owned();
    let input = fixture.path().join("input.csv");
    let temp = fixture.path().join("temporary");
    std::fs::create_dir(&temp)?;
    let wide = "late-key".repeat(40_000);
    let mut text = "id,key,text\n".to_owned();
    for id in 0..16 {
        let key = if id < 8 { "a" } else { &wide };
        text.push_str(&format!("{id},{key},\"quote,\"\"界\"\"\nline\"\n"));
    }
    std::fs::write(&input, text.as_bytes())?;
    let fixture_blake3 = blake3::hash(text.as_bytes()).to_hex().to_string();
    let mut job = Job {
        input: input.to_string_lossy().into_owned(),
        output: fixture.path().join("output").to_string_lossy().into_owned(),
        random_seed: Some("public-prepare-retry-v1".into()),
        operations: vec![
            Operation::Balanced { files: 2 },
            shuffle(),
            Operation::Partition {
                columns: vec![Column::Index(1)],
            },
            // Keep the candidate intermediate so pressure reaches its actual
            // retained-parent attempt before terminal output buffers exist.
            Operation::Partition {
                columns: vec![Column::Index(2)],
            },
        ],
        resources: Resources {
            workers: 1,
            memory_mb: 32.into(),
            max_record_bytes: 2 * 1024 * 1024,
            temp_bytes: Some(TEMPORARY_BYTES),
            temp_dir: Some(temp.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    job.output_csv.encoding = "utf-16le".into();
    job.output_csv.bom = true;
    job.output_csv.line_ending = "crlf".into();
    job.limits.bytes = Some(1_000_000);
    let pool = Arc::new(MemoryPool::new(SHARED_BYTES));
    let baseline = prepare_with_memory_pool(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let expected = prepared_snapshot(&baseline)?;
    ensure!(
        baseline.analysis.diagnostics["shuffle_partition_retries"] == 0,
        "unpressured public preparation retried"
    );
    ensure!(
        baseline.analysis.diagnostics["shuffle_partition_fusions"] == 2,
        "unpressured retained parents did not fuse"
    );
    ensure!(
        baseline.analysis.output_files > 2,
        "strict-cap fixture did not split encoded output"
    );
    drop(baseline);
    std::fs::remove_dir_all(&job.output)?;
    ensure!(
        pool.usage().reserved_bytes == 0 && std::fs::read_dir(&temp)?.next().is_none(),
        "control preparation owners leaked"
    );
    let mut cases = Vec::new();
    for mode in ["released", "cancelled", "retained"] {
        let pressure = Arc::new(Pressure {
            pool: pool.clone(),
            held: AtomicU64::new(0),
        });
        let retries = Arc::new(AtomicU64::new(0));
        let injection_error = Arc::new(Mutex::new(None::<String>));
        let cancel = Arc::new(AtomicBool::new(false));
        let held = pressure.clone();
        let observed = retries.clone();
        let failure = injection_error.clone();
        let cancellation = cancel.clone();
        let result = prepare_with_memory_pool(
            job.clone(),
            cancel,
            Arc::new(move |progress| {
                if progress.phase == "Preparing operation 2 of 4" {
                    let result = (|| -> Result<()> {
                        let bytes = SHARED_BYTES
                            .checked_sub(held.pool.usage().reserved_bytes + 256 * 1024)
                            .context("public fixture exhausted headroom")?;
                        held.pool.acquire(bytes)?;
                        held.held.store(bytes, Ordering::Relaxed);
                        Ok(())
                    })();
                    if let Err(error) = result {
                        *failure.lock().unwrap() = Some(format!("{error:#}"));
                    }
                }
                if progress.phase == "retrying shuffle/partition with original stages" {
                    observed.fetch_add(1, Ordering::Relaxed);
                    if mode != "retained" {
                        held.release();
                    }
                    if mode == "cancelled" {
                        cancellation.store(true, Ordering::Relaxed);
                    }
                }
            }),
            pool.clone(),
        );
        ensure!(
            injection_error.lock().unwrap().is_none(),
            "public preparation injection failed: {:?}",
            injection_error.lock().unwrap()
        );
        ensure!(
            retries.load(Ordering::Relaxed) == 1,
            "{mode}: public dispatch did not reach exactly one parent retry ({}): {:?}",
            retries.load(Ordering::Relaxed),
            result.as_ref().err()
        );
        let mut audit = serde_json::Value::Null;
        if mode == "released" {
            let prepared = result?;
            ensure!(
                prepared_snapshot(&prepared)? == expected,
                "public retry changed bytes, membership, caps or metadata"
            );
            ensure!(
                prepared.analysis.diagnostics["shuffle_partition_retries"] == 1,
                "public retry diagnostics changed"
            );
            audit = prepared.analysis.diagnostics["shuffle_partition_decisions"].clone();
            let records = audit["records"]
                .as_array()
                .context("missing public decision audit")?;
            ensure!(
                records.len() == 2
                    && records[0]["outcome"] == "fused_committed"
                    && records[1]["outcome"] == "original_committed"
                    && records[1]["admission_denial"] == "shared",
                "public retry audit changed: {audit}"
            );
            ensure!(
                pool.usage().reserved_bytes
                    == prepared.ctx.diagnostics()["workspace_reserved_bytes"]
                        .as_u64()
                        .context("missing workspace charge")?,
                "public prepared owner equation changed"
            );
            drop(prepared);
            std::fs::remove_dir_all(&job.output)?;
        } else {
            let error = result
                .err()
                .context("public preparation error case unexpectedly succeeded")?;
            if mode == "cancelled" {
                ensure!(
                    error.to_string().contains("cancel") || format!("{error:#}").contains("cancel"),
                    "public cancellation changed: {error:#}"
                );
            } else {
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "public retained pressure lost typed denial: {error:#}"
                );
            }
        }
        let competing_reserved_bytes = pressure.held.load(Ordering::Relaxed);
        ensure!(
            pool.usage().reserved_bytes == competing_reserved_bytes,
            "{mode}: public result retained capacity beyond the competing owner"
        );
        pressure.release();
        ensure!(
            pool.usage().reserved_bytes == 0 && std::fs::read_dir(&temp)?.next().is_none(),
            "{mode}: failed/prepared public owners leaked"
        );
        ensure!(
            !std::path::Path::new(&job.output).try_exists()?,
            "public preparation/verification output survived cleanup"
        );
        ensure!(
            blake3::hash(&std::fs::read(&input)?).to_hex().as_str() == fixture_blake3,
            "public preparation changed source"
        );
        cases.push(json!({"mode":mode,"retry_entries":1,"source_unchanged":true,"temporary_workspace_removed":true,"output_absent_after_cleanup":true,"destination_published":mode == "released","outcome":match mode {"released"=>"prepared-and-published-exact-retry", "cancelled"=>"cancelled-before-replay", _=>"typed-shared-denial"},"competing_reserved_bytes_after_prepare":competing_reserved_bytes,"final_reserved_bytes":0,"decision_audit":audit}));
    }
    fixture.close()?;
    ensure!(!fixture_path.try_exists()?, "public fixture leaked");
    // Exact bytes and complete metadata were compared above. Keep the report
    // bounded instead of repeating a 320 KiB lineage key in every output chunk.
    let (mut expected, _) = expected;
    let chunks = expected["chunks"].take();
    expected["chunks_blake3"] = json!(blake3::hash(&serde_json::to_vec(&chunks)?)
        .to_hex()
        .to_string());
    expected["chunks"] = json!(chunks.as_array().context("missing verified chunks")?.iter().map(|chunk| {
        Ok(json!({"path":chunk["path"],"rows":chunk["rows"],"csv_bytes":chunk["csv_bytes"],
            "lineage_blake3":blake3::hash(&serde_json::to_vec(&chunk["lineage"])?).to_hex().to_string()}))
    }).collect::<Result<Vec<_>>>()?);
    Ok(
        json!({"contract":"public-preparation-retained-parent-resource-contract-v1", "entry":"prepare_with_memory_pool", "fixture_blake3":fixture_blake3, "headroom_bytes_at_public_stage_boundary":256 * 1024, "control_fused_parents":2, "control_retries":0, "direct_encoded_bytes_and_metadata_equality":true, "expected":expected, "cases":cases, "fixture_directory_removed":true}),
    )
}
