//! Explicit job budgets larger than the shared pool retain spill headroom.
use super::*;
use std::collections::BTreeMap;

#[test]
fn manual_memory_shared_spill_contract() -> Result<()> {
    run().map(|_| ())
}

pub(super) fn run() -> Result<serde_json::Value> {
    const MIB: u64 = 1024 * 1024;
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    let mut writer = std::io::BufWriter::new(File::create(&input)?);
    writeln!(writer, "id,country,segment")?;
    let payload = "x".repeat(96);
    for id in 0..60_000 {
        writeln!(writer, "{id},{},{payload}", id % 8)?;
    }
    writer.flush()?;
    drop(writer);
    let mut baseline = None;
    let mut peak = 0;
    for memory in [32, 512] {
        let pool = Arc::new(MemoryPool::new(16 * MIB));
        let output = dir.path().join(format!("output-{memory}"));
        let mut job: Job = serde_json::from_value(json!({
            "version": 1, "input": input, "output": output,
            "operations": [
                {"type":"partition", "columns":["country", "segment"]},
                {"type":"assign", "groups":[{"name":"treatment","percent":"80"},{"name":"control","percent":"20"}]},
                {"type":"shuffle", "strategy":"auto"}
            ],
            "resources": {"memory_mb":memory,"max_record_bytes": 1048576,"workers":1,
                "temp_dir":dir.path()}
        }))?;
        // Internal deterministic oracle; no seed is accepted through Job JSON.
        job.random_seed = Some("manual-memory-regression".into());
        let prepared = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        ensure!(
            prepared.ctx.memory as u64 == memory * MIB,
            "numeric job budget changed"
        );
        ensure!(
            prepared.analysis.memory_budget_bytes == memory * MIB,
            "reported job budget changed"
        );
        let analysis = prepared.execute()?;
        ensure!(analysis.rows == 60_000, "manual memory lost rows");
        drop(analysis);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "manual memory owner leaked"
        );
        peak = peak.max(pool.usage().peak_reserved_bytes);
        ensure!(peak <= 16 * MIB, "shared memory ceiling exceeded");
        let mut files = BTreeMap::new();
        let mut seen = vec![false; 60_000];
        for entry in std::fs::read_dir(&output)? {
            let path = entry?.path();
            if path.extension().is_some_and(|extension| extension == "csv") {
                let bytes = std::fs::read(&path)?;
                let text = std::str::from_utf8(&bytes)?;
                for line in text.lines().skip(1) {
                    let fields = line.split(',').collect::<Vec<_>>();
                    ensure!(
                        fields.len() == 3 && fields[2] == payload,
                        "manual memory changed fields"
                    );
                    let id = fields[0].parse::<usize>()?;
                    ensure!(id < seen.len() && !seen[id], "manual memory repeated a row");
                    ensure!(
                        fields[1] == (id % 8).to_string(),
                        "manual memory changed partition membership"
                    );
                    seen[id] = true;
                }
                let name = path.file_name().unwrap().to_string_lossy();
                let expected = if name.contains("allocation-treatment") {
                    6000
                } else {
                    1500
                };
                ensure!(
                    text.lines().count() - 1 == expected,
                    "manual memory changed exact allocation quotas"
                );
                files.insert(path.file_name().unwrap().to_owned(), bytes);
            }
        }
        ensure!(seen.iter().all(|seen| *seen), "manual memory omitted a row");
        ensure!(
            files.len() == 16,
            "manual memory changed partition/allocation fanout"
        );
        if let Some(baseline) = &baseline {
            ensure!(
                &files == baseline,
                "manual memory changed seeded CSV bytes or group membership"
            );
        } else {
            baseline = Some(files);
        }
    }
    dir.close()?;
    Ok(json!({"explicit_memory_mb":512,"shared_limit_bytes":16*MIB,
        "peak_reserved_bytes":peak,"rows":60000,"seeded_csv_parity":true,
        "exact_field_and_id_conservation":true,"final_reserved_bytes":0}))
}
