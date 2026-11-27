use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

fn text(value: &str, capacity: usize, total: &mut usize) -> String {
    let mut result = String::with_capacity(capacity.max(value.len()));
    result.push_str(value);
    *total += result.capacity();
    result
}
fn fixture() -> (Job, usize) {
    let mut expected = 0;
    let mut job = Job {
        input: text("input.csv", 128, &mut expected),
        output: text("output", 96, &mut expected),
        zip_member: Some(text("data.csv", 80, &mut expected)),
        random_seed: Some(text("seed", 64, &mut expected)),
        ..Job::default()
    };
    job.resources.temp_dir = Some(text("temporary", 128, &mut expected));
    job.input_csv.encoding = text("utf-8", 32, &mut expected);
    job.input_csv.line_ending = text("lf", 16, &mut expected);
    job.input_dialect.comment_prefix = Some(text("# ", 40, &mut expected));
    job.output_csv.encoding = text("utf-8", 48, &mut expected);
    job.output_csv.line_ending = text("crlf", 24, &mut expected);
    let mut partition = Vec::with_capacity(7);
    partition.push(Column::Name(text("key", 96, &mut expected)));
    partition.push(Column::Index(1));
    expected += partition.capacity() * std::mem::size_of::<Column>();
    let mut strata = Vec::with_capacity(6);
    strata.push(Column::Name(text("stratum", 72, &mut expected)));
    expected += strata.capacity() * std::mem::size_of::<Column>();
    let mut groups = Vec::with_capacity(5);
    groups.push(Allocation {
        name: text("one", 80, &mut expected),
        percent: text("100", 32, &mut expected),
    });
    expected += groups.capacity() * std::mem::size_of::<Allocation>();
    let mut probability = Vec::with_capacity(3);
    probability.push(Allocation {
        name: text("p", 48, &mut expected),
        percent: text("100", 24, &mut expected),
    });
    expected += probability.capacity() * std::mem::size_of::<Allocation>();
    let mut operations = Vec::with_capacity(12);
    operations.extend([
        Operation::Partition { columns: partition },
        Operation::Assign { groups, strata },
        Operation::AssignProbabilistic {
            groups: probability,
            strata: Vec::new(),
        },
        Operation::Balanced { files: 1 },
        Operation::Interleaved { files: 1 },
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        },
    ]);
    expected += operations.capacity() * std::mem::size_of::<Operation>();
    job.operations = operations;
    (job, expected)
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let (job, expected) = fixture();
    let canonical = serde_json::to_vec(&job)?;
    ensure!(
        capacity(&job)? == expected,
        "configuration capacity differs from constructed allocations"
    );
    drop(job);
    for shared in [false, true] {
        for limit in [expected - 1, expected, expected + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(expected + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result =
                PreparedJob::admit(fixture().0, Reservation::for_workspace(workspace.clone()));
            if limit < expected {
                let error = result.err().context("configuration edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "configuration denial lost type"
                );
            } else {
                let owner = result?;
                ensure!(
                    workspace.used() == expected as u64 && serde_json::to_vec(&owner)? == canonical,
                    "configuration bytes/lifetime changed"
                );
                let mut copied = owner.clone();
                copied.input.push_str("-caller-copy");
                ensure!(
                    owner.input == "input.csv" && workspace.used() == expected as u64,
                    "caller clone changed owner"
                );
                drop(owner);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "configuration edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * expected - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * expected, pool.clone()));
    let first = PreparedJob::admit(fixture().0, Reservation::for_workspace(workspace.clone()))?;
    let error = PreparedJob::admit(fixture().0, Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing configuration admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == expected as u64,
        "competing configuration changed first owner"
    );
    drop(first);
    let retry = PreparedJob::admit(fixture().0, Reservation::for_workspace(workspace.clone()))?;
    drop(retry);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "configuration retry leaked"
    );
    let job = Job::default();
    let before = capacity(&job)?;
    let denied = Arc::new(Workspace::new(before + 63));
    let error = PreparedJob::admit(Job::default(), Reservation::for_workspace(denied.clone()))
        .err()
        .context("generated seed edge accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Local)
        ) && denied.used() == 0,
        "generated seed denial lost ownership/type"
    );
    let workspace = Arc::new(Workspace::new(before + 64));
    let owner = PreparedJob::admit(job, Reservation::for_workspace(workspace.clone()))?;
    let seed = owner.random_seed.as_ref().unwrap();
    ensure!(
        seed.len() == 64
            && seed
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            && workspace.used() == (before + 64) as u64,
        "generated seed allowance/format changed"
    );
    drop(owner);
    ensure!(workspace.used() == 0, "generated seed owner leaked");
    Ok(
        json!({"contract":"prepared-job-capacity-admission-v1","retained_bytes":expected,"local_shared_edges":6,"spare_nested_capacities_included":true,"canonical_serialization_equal":true,"caller_clone_independent":true,"competing_owner_release_retry":true,"generated_seed_bytes":64,"public_preparation":preparation()?,"final_reserved_bytes":0}),
    )
}

fn preparation() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id\n1\n")?;
    let build = || {
        let mut output = dir.path().join("output").to_string_lossy().into_owned();
        output.reserve_exact(1024 * 1024);
        Job {
            input: input.to_string_lossy().into_owned(),
            output,
            random_seed: Some("prepared-owner".into()),
            resources: Resources {
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        }
    };
    let pool = Arc::new(MemoryPool::new(256 * 1024));
    let reading = Arc::new(AtomicBool::new(false));
    let signal = reading.clone();
    let error = prepare_with_memory_pool(
        build(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(move |progress| {
            if progress.phase == "Reading and validating CSV" {
                signal.store(true, std::sync::atomic::Ordering::Relaxed);
            }
        }),
        pool.clone(),
    )
    .err()
    .context("large retained capacity admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && !reading.load(std::sync::atomic::Ordering::Relaxed)
            && pool.usage().reserved_bytes == 0,
        "configuration denial crossed input boundary or leaked"
    );
    let job = build();
    let expected = capacity(&job)?;
    let canonical = serde_json::to_vec(&job)?;
    let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
    let prepared = prepare_with_memory_pool(
        job,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    ensure!(
        prepared.job._memory.bytes() == expected as u64
            && pool.usage().reserved_bytes >= expected as u64
            && serde_json::to_vec(&prepared.job)? == canonical,
        "prepared configuration owner or schema changed"
    );
    struct Reject;
    impl std::io::Write for Reject {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("serialization sentinel"))
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let retained = pool.usage().reserved_bytes;
    ensure!(
        serde_json::to_writer(Reject, &prepared.job).is_err()
            && pool.usage().reserved_bytes == retained,
        "serialization failure released owner"
    );
    let analysis = prepared.execute()?;
    ensure!(analysis.rows == 1, "prepared execution changed rows");
    drop(analysis);
    ensure!(
        pool.usage().reserved_bytes == 0
            && std::fs::read(dir.path().join("output/part-00000001.csv"))? == b"id\n1\n",
        "prepared execution changed bytes or leaked"
    );
    dir.close()?;
    Ok(
        json!({"retained_capacity_bytes":expected,"denial_before_input":true,"prepared_serialization_equal":true,"serialization_failure_retains_owner":true,"execution_csv_parity":true,"final_reserved_bytes":0}),
    )
}

#[test]
fn prepared_job_capacity_admission() {
    println!("{}", run().unwrap());
}
