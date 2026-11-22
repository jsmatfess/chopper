//! Numeric advice from existing observations; never an execution certificate.
use super::*;

#[derive(Clone, Copy, Serialize)]
pub struct WriterEstimate {
    pub estimated_groups: Option<u64>,
    pub exact_if_feasible: bool,
    pub simultaneous_writer_capacity: Option<usize>,
    pub configured_output_file_limit: u64,
    pub estimated_groups_fit_writer_capacity: Option<bool>,
    pub estimated_groups_fit_file_limit: Option<bool>,
    pub bounded_partition_shape: bool,
}

pub(super) fn estimate(job: &Job, profile: &InputProfile) -> Option<WriterEstimate> {
    if !cfg!(all(
        feature = "experimental-final-writers",
        not(target_os = "wasi")
    )) {
        return None;
    }
    let mut groups = Some(1u64);
    let mut exact = true;
    let mut partitioned = false;
    let mut unchanged_parent = true;
    for (index, operation) in job.operations.iter().enumerate() {
        let multiplier = match operation {
            Operation::Shuffle { .. } => 1,
            Operation::Partition { .. } => {
                // Input sketches cannot supply conditional per-parent counts.
                // Do not multiply marginal estimates across correlated keys.
                if partitioned || !unchanged_parent {
                    groups = None;
                    exact = false;
                } else {
                    groups = profile.stages[index].input_distinct_keys;
                    exact = profile.stages[index].distinct_exact && groups.is_some();
                }
                partitioned = true;
                continue;
            }
            Operation::Balanced { files } | Operation::Interleaved { files } => *files,
            Operation::Assign { groups, .. } | Operation::AssignProbabilistic { groups, .. } => {
                groups.len() as u64
            }
        };
        groups = groups.and_then(|count| count.checked_mul(multiplier));
        exact &= groups.is_some();
        unchanged_parent &= multiplier == 1;
    }
    let capacity = engine::configured_writer_capacity(job);
    Some(WriterEstimate {
        estimated_groups: groups,
        exact_if_feasible: exact,
        simultaneous_writer_capacity: capacity,
        configured_output_file_limit: job.resources.max_files,
        estimated_groups_fit_writer_capacity: groups
            .zip(capacity)
            .map(|(groups, cap)| groups <= cap as u64),
        estimated_groups_fit_file_limit: groups.map(|groups| groups <= job.resources.max_files),
        bounded_partition_shape: engine::bounded_final_partition_shape(job),
    })
}

#[cfg(all(
    test,
    feature = "experimental-bounded-final-partition",
    not(target_os = "wasi")
))]
mod tests {
    use super::*;
    use chopper_core::{Allocation, Column, Resources};

    #[test]
    fn advice_reuses_key_sketches_recomputes_limits_and_does_not_count_strata_as_outputs(
    ) -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        std::fs::write(
            &input,
            format!(
                "id,key\n{}",
                (0..4096)
                    .map(|i| format!("{i},{}\n", i % 200))
                    .collect::<String>()
            ),
        )?;
        let mut job = Job {
            input: input.to_string_lossy().into(),
            resources: Resources {
                memory_mb: 64.into(),
                max_record_bytes: 1024 * 1024,
                max_files: 256,
                workers: 1,
                ..Default::default()
            },
            operations: vec![Operation::Partition {
                columns: vec![Column::Index(1)],
            }],
            ..Default::default()
        };
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let first = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let advice = first.writer_estimate.unwrap();
        assert_eq!(advice.estimated_groups, first.stages[0].input_distinct_keys);
        assert!((160..=240).contains(&advice.estimated_groups.unwrap()));
        assert!(!advice.exact_if_feasible && advice.bounded_partition_shape);
        job.resources.max_files = 10000;
        let second = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(
            second.writer_estimate.unwrap().estimated_groups,
            advice.estimated_groups
        );
        assert!(!second.writer_estimate.unwrap().bounded_partition_shape);
        assert_eq!(
            second.writer_estimate.unwrap().configured_output_file_limit,
            10000
        );
        job.operations = vec![Operation::AssignProbabilistic {
            groups: vec![
                Allocation {
                    name: "a".into(),
                    percent: "50".into(),
                },
                Allocation {
                    name: "b".into(),
                    percent: "50".into(),
                },
            ],
            strata: vec![Column::Index(1)],
        }];
        let third = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(third.writer_estimate.unwrap().estimated_groups, Some(2));
        assert!(third.writer_estimate.unwrap().exact_if_feasible);
        job.operations = vec![
            Operation::Interleaved { files: 2 },
            Operation::Partition {
                columns: vec![Column::Index(1)],
            },
        ];
        let fourth = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(fourth.writer_estimate.unwrap().estimated_groups, None);
        drop((first, second, third, fourth, cache));
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
}
