//! Retry through the real encoded-output sink and Rust destination finalization.
//! WASI finalization here does not exercise the JavaScript destination exporter
//! or its completion marker. Fixture/verification allocations are not RSS claims.
use super::*;
use std::io::Read;

struct Pressured<'a, S> {
    sink: &'a mut S,
    pressure: Arc<Pressure>,
    groups: u64,
}
impl<S: RowSink> RowSink for Pressured<'_, S> {
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        self.sink.begin(lineage, exact)
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        self.sink.row(group, row)
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        self.sink.packed_row_ref(group, row)
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.sink.end(group)?;
        self.groups += 1;
        if self.groups == 1 {
            let held = SHARED_BYTES
                .checked_sub(self.pressure.pool.usage().reserved_bytes + 128 * 1024)
                .context("publication fixture exhausted shared headroom")?;
            self.pressure.pool.acquire(held)?;
            self.pressure.held.store(held, Ordering::Relaxed);
        }
        Ok(())
    }
}

pub(super) fn published(
    directory: &std::path::Path,
    cap: u64,
) -> Result<(Vec<serde_json::Value>, Vec<u8>)> {
    let manifest = std::fs::read_to_string(directory.join("manifest.jsonl"))?;
    let mut records = Vec::new();
    let mut encoded = Vec::new();
    for line in manifest.lines() {
        let record: serde_json::Value = serde_json::from_str(line)?;
        if record["type"] != "output" {
            continue;
        }
        let path = record["path"]
            .as_str()
            .context("published record has no path")?;
        let bytes = std::fs::read(directory.join(path))?;
        ensure!(
            bytes.len() as u64 <= cap && record["csv_bytes"] == bytes.len() as u64,
            "published CSV violated its serialized-byte cap"
        );
        ensure!(
            bytes.starts_with(&[0xff, 0xfe]) && bytes.len().is_multiple_of(2),
            "published CSV lost UTF-16LE BOM/framing"
        );
        let text = String::from_utf16(
            &bytes[2..]
                .as_chunks::<2>()
                .0
                .iter()
                .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
                .collect::<Vec<_>>(),
        )?;
        ensure!(
            text.starts_with("id,key,text\r\n") && text.contains("\"quote,\"\"界\"\"\nline\""),
            "published CSV lost header, CRLF, quoting or Unicode"
        );
        encoded.extend_from_slice(&bytes);
        records.push(record);
    }
    ensure!(!records.is_empty(), "publication produced no CSV records");
    Ok((records, encoded))
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let fixture = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let fixture = tempfile::tempdir()?;
    let fixture_path = fixture.path().to_owned();
    let mut cases = Vec::new();
    for mode in ["published", "cap_rejected", "cancelled_writing"] {
        let pool = Arc::new(MemoryPool::new(SHARED_BYTES));
        let pressure = Arc::new(Pressure {
            pool: pool.clone(),
            held: AtomicU64::new(0),
        });
        let cancelled = Arc::new(AtomicBool::new(false));
        let mut ctx = context(pool.clone(), cancelled.clone())?;
        let workspace = ctx.dir.path().to_owned();
        let retry_entries = Arc::new(AtomicU64::new(0));
        let writing_events = Arc::new(AtomicU64::new(0));
        let cancel_on_write = Arc::new(AtomicBool::new(false));
        let retries = retry_entries.clone();
        let writing = writing_events.clone();
        let armed = cancel_on_write.clone();
        let cancel = cancelled.clone();
        let release = pressure.clone();
        ctx.notify = Arc::new(move |progress| {
            if progress.phase == "retrying shuffle/partition with original stages" {
                retries.fetch_add(1, Ordering::Relaxed);
                release.release();
            }
            if armed.load(Ordering::Relaxed) && progress.phase == "Writing output" {
                writing.fetch_add(1, Ordering::Relaxed);
                cancel.store(true, Ordering::Relaxed);
            }
        });
        let output = fixture.path().join(format!("{mode}-candidate"));
        let baseline_output = fixture.path().join(format!("{mode}-baseline"));
        let mut job = Job {
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("retry-encoded-publication-v1".into()),
            resources: Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 2 * 1024 * 1024,
                temp_bytes: Some(TEMPORARY_BYTES),
                #[cfg(target_os = "wasi")]
                temp_dir: Some("/tmp".into()),
                ..Default::default()
            },
            operations: vec![
                Operation::Balanced { files: 2 },
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
            ],
            ..Default::default()
        };
        job.output_csv.encoding = "utf-16le".into();
        job.output_csv.line_ending = "crlf".into();
        job.output_csv.bom = true;
        let wide = "late-key".repeat(40_000);
        let payload = "quote,\"界\"\nline";
        let mut serializer = chopper_core::csv::Serializer::new(&job.output_csv)?;
        let prefix = chopper_core::csv::bom(&job.output_csv)?.len() as u64
            + serializer.serialize_fields(["id", "key", "text"])?.len() as u64;
        let maximum_row = serializer
            .serialize_fields(["15", wide.as_str(), payload])?
            .len() as u64;
        let cap = if mode == "cap_rejected" {
            prefix + maximum_row - 1
        } else {
            prefix + 2 * maximum_row
        };
        job.limits.bytes = Some(cap);
        let mut text = "id,key,text\n".to_owned();
        for id in 0..16 {
            text.push_str(&format!(
                "{id},{},\"quote,\"\"界\"\"\nline\"\n",
                if id < 8 { "a" } else { &wide }
            ));
        }
        let fixture_blake3 = blake3::hash(text.as_bytes()).to_hex().to_string();
        let ingested = ingest_options(&mut text.as_bytes(), &job, &ctx, false, false, false)?;
        let parents = serial(
            &ingested.dataset,
            &job.operations[0],
            0,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let shuffled = serial(
            &parents,
            &job.operations[1],
            1,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let expected = serial(
            &shuffled,
            &job.operations[2],
            2,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let baseline_plan =
            output::plan(&expected, &job, ingested.analysis.header.as_deref(), &ctx);
        let mut writer = output::PlanWriter::new(&job, ingested.analysis.header.as_deref(), &ctx)?;
        let mut sink = Pressured {
            sink: &mut writer,
            pressure: pressure.clone(),
            groups: 0,
        };
        let result = Plan::at(&job, 1)
            .context("publication candidate unavailable")?
            .apply(&parents, &job, &ingested.analysis, &ctx, &mut sink);
        drop(sink);
        pressure.release();
        ensure!(
            retry_entries.load(Ordering::Relaxed) == 1
                && ctx.diagnostics()["shuffle_partition_retries"] == 1
                && ctx.diagnostics()["shuffle_partition_fusions"] == 1,
            "{mode}: fixture did not retry exactly one late parent"
        );
        let mut csv_digest = None;
        let mut metadata_digest = None;
        let mut csv_files = None;
        let mut csv_bytes = None;
        if mode == "cap_rejected" {
            let error = result
                .err()
                .context("one-byte-too-small cap unexpectedly succeeded")?;
            ensure!(
                format!("{error:#}").contains("one row plus header exceeds output byte limit"),
                "{mode}: unexpected terminal error: {error:#}"
            );
            let baseline_error = baseline_plan
                .err()
                .context("serial baseline accepted invalid cap")?;
            ensure!(
                format!("{baseline_error:#}")
                    .contains("one row plus header exceeds output byte limit"),
                "serial baseline failed for an unrelated reason: {baseline_error:#}"
            );
            drop(writer);
            drop(ingested);
        } else {
            result?;
            let candidate_plan = writer.finish()?;
            let baseline_plan = baseline_plan?;
            ensure!(
                candidate_plan.files == 5 && baseline_plan.files == 5,
                "byte cap did not split eight wide rows into four CSVs"
            );
            ensure!(
                candidate_plan.bytes == baseline_plan.bytes,
                "encoded plan length changed"
            );
            let mut expected_bytes = Vec::new();
            baseline_plan
                .data
                .reader()?
                .read_to_end(&mut expected_bytes)?;
            let mut candidate_bytes = Vec::new();
            candidate_plan
                .data
                .reader()?
                .read_to_end(&mut candidate_bytes)?;
            ensure!(
                candidate_bytes == expected_bytes,
                "retry changed exact encoded CSV snapshot"
            );
            csv_files = Some(candidate_plan.files);
            csv_bytes = Some(candidate_plan.bytes);
            let Ingested {
                mut analysis,
                dataset,
                ..
            } = ingested;
            drop(dataset);
            analysis.output_files = baseline_plan.files;
            analysis.output_csv_bytes = baseline_plan.bytes;
            analysis.groups = 2;
            analysis.diagnostics = Diagnostics::context(&ctx)?;
            let mut baseline_job = job.clone();
            baseline_job.output = baseline_output.to_string_lossy().into_owned();
            let baseline = Prepared {
                job: PreparedJob::admit(baseline_job, Reservation::new(&ctx))?,
                analysis,
                output_plan: baseline_plan,
                ctx: ctx.clone(),
            };
            // Publish the serial plan first while keeping the same shared header
            // owner, then move Analysis into the candidate.
            output::execute(&baseline)?;
            let (expected_records, published_baseline) = published(&baseline_output, cap)?;
            ensure!(
                published_baseline == expected_bytes,
                "baseline publication changed snapshot"
            );
            let Prepared {
                mut analysis,
                output_plan,
                ..
            } = baseline;
            drop(output_plan);
            analysis.output_files = candidate_plan.files;
            analysis.output_csv_bytes = candidate_plan.bytes;
            analysis.diagnostics = Diagnostics::context(&ctx)?;
            let prepared = Prepared {
                job: PreparedJob::admit(job, Reservation::new(&ctx))?,
                analysis,
                output_plan: candidate_plan,
                ctx: ctx.clone(),
            };
            if mode == "cancelled_writing" {
                cancel_on_write.store(true, Ordering::Relaxed);
            }
            let execution = prepared.execute();
            if mode == "published" {
                execution?;
                let (records, bytes) = published(&output, cap)?;
                ensure!(
                    records == expected_records && bytes == expected_bytes,
                    "published filenames, lineage, metadata or exact CSV bytes changed"
                );
                ensure!(
                    records
                        .iter()
                        .map(|record| record["rows"].as_u64().unwrap())
                        .sum::<u64>()
                        == 16,
                    "published rows missing or duplicated"
                );
                ensure!(
                    records.iter().skip(1).all(|record| record["rows"] == 2),
                    "wide CSV split changed"
                );
                csv_digest = Some(blake3::hash(&bytes).to_hex().to_string());
                metadata_digest = Some(
                    blake3::hash(&serde_json::to_vec(&records)?)
                        .to_hex()
                        .to_string(),
                );
            } else {
                let error = execution
                    .err()
                    .context("writing cancellation unexpectedly succeeded")?;
                ensure!(
                    format!("{error:#}").contains("cancel")
                        && writing_events.load(Ordering::Relaxed) == 1,
                    "cancellation did not stop after first private destination write"
                );
            }
            std::fs::remove_dir_all(&baseline_output)?;
        }
        ensure!(
            output.try_exists()? == (mode == "published"),
            "{mode}: publication visibility changed"
        );
        if mode == "published" {
            #[cfg(target_os = "wasi")]
            {
                ensure!(
                    !std::path::Path::new("/results").try_exists()?,
                    "browser export results already exist"
                );
                // Transfer only the verified published result to the test worker.
                // The worker unlinks these files after export; Context still
                // releases all temporary/audit owners before returning.
                std::fs::rename(&output, "/results")?;
            }
            #[cfg(not(target_os = "wasi"))]
            std::fs::remove_dir_all(&output)?;
        }
        ensure!(
            std::fs::read_dir(fixture.path())?.next().is_none(),
            "{mode}: publication/staging leaked"
        );
        drop(expected);
        drop(shuffled);
        drop(parents);
        let audit = ctx.diagnostics()["shuffle_partition_decisions"].clone();
        let audit_bytes = audit["reserved_bytes"]
            .as_u64()
            .context("publication audit charge absent")?;
        ensure!(
            audit_bytes > 0
                && audit["records"].as_array().unwrap().len() == 2
                && audit["records"][1]["admission_denial"] == "shared"
                && audit["records"][1]["outcome"]
                    == if mode == "cap_rejected" {
                        "terminal"
                    } else {
                        "original_committed"
                    },
            "{mode}: retry audit changed"
        );
        ensure!(
            ctx.used() == 0
                && ctx.diagnostics()["workspace_reserved_bytes"]
                    == audit_bytes + ctx.directory_reserved_bytes()
                && pool.usage().reserved_bytes == audit_bytes + ctx.directory_reserved_bytes()
                && std::fs::read_dir(&workspace)?.next().is_none(),
            "{mode}: temporary owners leaked"
        );
        let directory_bytes = ctx.directory_reserved_bytes();
        ensure!(directory_bytes > 0, "{mode}: directory owner missing");
        let peak = ctx.peak();
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0 && !workspace.try_exists()?,
            "{mode}: final context leaked"
        );
        cases.push(json!({"mode":mode,"fixture_blake3":fixture_blake3,
            "byte_cap":cap,"prefix_bytes":prefix,"maximum_row_bytes":maximum_row,
            "output_files":csv_files,"output_csv_bytes":csv_bytes,
            "csv_blake3":csv_digest,"output_records_blake3":metadata_digest,
            "retry_entries":1,"fused_parents":1,"csv_encoding":"utf-16le","bom":true,"line_ending":"crlf",
            "private_writing_events_before_cancellation":writing_events.load(Ordering::Relaxed),
            "destination_published":mode=="published","staging_removed":true,
            "workspace_removed":true,"final_reserved_bytes":0,"directory_reserved_bytes_before_context_drop":directory_bytes,"decision_audit":audit,"peak_temporary_bytes":peak}));
    }
    fixture.close()?;
    ensure!(!fixture_path.try_exists()?, "publication fixture leaked");
    Ok(
        json!({"contract":"retained-parent-encoded-publication-resource-contract-v1",
        "scope":"retained-parent planner/encoded sink and Rust destination finalization; excludes JavaScript export/completion marker",
        "runtime_finalization":if cfg!(target_os = "wasi") { "wasi_internal_directory" } else { "native_atomic_directory" },
        "javascript_export_tested":false,"completion_marker_tested":false,
        "retained_for_browser_export":cfg!(target_os = "wasi"),
        "shared_bytes":SHARED_BYTES,"temporary_budget_bytes":TEMPORARY_BYTES,
        "fixture_directory_removed":true,"cases":cases}),
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn retained_parent_retry_preserves_encoded_caps_and_publication_cleanup() -> anyhow::Result<()>
    {
        println!(
            "CHOPPER_RETRY_PUBLICATION_RESOURCE_CONTRACT {}",
            super::run()?
        );
        Ok(())
    }
}
