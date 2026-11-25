use super::*;
use crate::{
    cli_job::DecodedJob,
    resources::{MemoryAdmission, MemoryPool},
};

fn decode(wire: &[u8], pool: &Arc<MemoryPool>) -> Result<DecodedJob> {
    DecodedJob::decode_for_run_test(wire, pool.clone())
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let mut edges = 0;
    for delta in [64, 0] {
        // The wire schema excludes the internal seed.
        let build = |pool: &Arc<MemoryPool>| {
            let owner = decode(br#"{"output":"result"}"#, pool)?;
            if delta == 0 {
                return owner.with_test_seed();
            }
            Ok(owner)
        };
        let probe = Arc::new(MemoryPool::new(u64::MAX));
        let first = build(&probe)?;
        let retained = capacity(first.job())?;
        let total = retained + delta;
        let limit = probe.reservation_counts().1 + (total as u64) + 1;
        drop(first);
        let shared_edges: &[usize] = if delta == 0 { &[0, 1] } else { &[63, 64, 65] };
        for local in [total - 1, total, total + 1] {
            for &shared in shared_edges {
                let pool = Arc::new(MemoryPool::new(limit));
                let owner = build(&pool)?;
                let other = limit - retained as u64 - shared as u64;
                pool.acquire(other)?;
                let peak_before = pool.reservation_counts().1;
                let workspace = Arc::new(Workspace::shared(local, pool.clone()));
                let result = PreparedJob::admit(
                    RunJob::Decoded(owner),
                    Reservation::for_workspace(workspace.clone()),
                );
                if local < total || shared < delta {
                    let error = result.err().context("transfer admitted beyond a limit")?;
                    ensure!(
                        matches!(
                            (local < total, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Local))
                                | (false, Some(MemoryAdmission::Shared { .. }))
                        ),
                        "transfer denial changed type: {error:#}"
                    );
                    ensure!(workspace.peak() == 0 && pool.reservation_counts().1 == peak_before);
                } else {
                    let prepared = result?;
                    ensure!(prepared.output == "result" && prepared.random_seed.is_some());
                    ensure!(
                        prepared.reserved_bytes() == total as u64
                            && workspace.used() == total as u64
                    );
                    ensure!(
                        pool.reservation_counts()
                            == (other + total as u64, peak_before.max(other + total as u64))
                    );
                    drop(prepared);
                }
                ensure!(workspace.used() == 0 && pool.reservation_counts().0 == other);
                pool.release(other);
                ensure!(pool.reservation_counts().0 == 0);
                edges += 1;
            }
        }
    }
    let pool = Arc::new(MemoryPool::new(64 * 1024));
    let foreign = Arc::new(MemoryPool::new(64 * 1024));
    let owner = RunJob::Decoded(decode(b"{}", &pool)?);
    ensure!(owner.memory_credit(&foreign) == 0 && owner.memory_credit(&pool) > 0);
    let workspace = Arc::new(Workspace::shared(1024, foreign.clone()));
    let error = PreparedJob::admit(owner, Reservation::for_workspace(workspace.clone()))
        .err()
        .context("mismatched pool accepted")?;
    ensure!(error.to_string().contains("different memory pools"));
    ensure!(workspace.used() == 0 && foreign.reservation_counts() == (0, 0));
    ensure!(pool.reservation_counts().0 == 0);
    Ok(json!({"local_shared_edges":edges,"mismatched_pool_denied":true}))
}

#[cfg(target_os = "wasi")]
pub(in crate::engine) fn wasi_auto() -> Result<serde_json::Value> {
    const MIB: u64 = 1024 * 1024;
    let dir = tempfile::tempdir_in("/tmp")?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id\n1\n2\n")?;
    let mut budgets = Vec::new();
    for (competing, explicit, expected) in [(0, None, 2048), (1, None, 256), (1, Some(1024), 1024)]
    {
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: dir
                .path()
                .join(format!("result-{expected}"))
                .to_string_lossy()
                .into_owned(),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }],
            resources: Resources {
                memory_mb: explicit.map_or(MemoryBudget::Auto, MemoryBudget::from),
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::automatic()
            },
            ..Job::default()
        };
        let pool = Arc::new(MemoryPool::new(1024 * MIB));
        let owner = decode(&serde_json::to_vec(&job)?, &pool)?;
        let hint = AutoObservations {
            binding: crate::profile::auto_binding(owner.job()).context("test source binding")?,
            rows: 2,
            columns: 1,
            decoded_field_bytes: 300 * MIB,
            largest_decoded_row_bytes: 1,
            partition: None,
        };
        pool.acquire(competing)?;
        let analysis = run_using(
            RunJob::Decoded(owner),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
            (Some(hint), None),
            None,
            None,
        )?;
        ensure!(analysis.rows == 2 && analysis.memory_budget_bytes == expected * MIB);
        let plan = serde_json::to_value(analysis.auto_plan.as_ref())?;
        ensure!(plan["analysis_status"] == "matched" && plan["physical_plan"] == "snapshot");
        ensure!(plan["effective_memory_bytes"] == expected * MIB);
        if explicit.is_none() {
            ensure!(plan["memory_plan"]["target_mb"] == 2048);
        }
        let csv =
            std::fs::read_to_string(std::path::Path::new(&job.output).join("part-00000001.csv"))?;
        ensure!(matches!(csv.as_str(), "id\n1\n2\n" | "id\n2\n1\n"));
        drop(analysis);
        ensure!(pool.reservation_counts().0 == competing);
        pool.release(competing);
        budgets.push(expected);
    }
    dir.close()?;
    Ok(json!(budgets))
}

#[test]
fn decoded_run_transfers_prepared_job_admission() {
    run().unwrap();
}
