//! Exact quota cursor with an in-place Fenwick representation for many groups.
use super::take_linear;

const INDEXED_MINIMUM: usize = 32;

#[cfg(test)]
std::thread_local! {
    static DISABLE_INDEX: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub(in crate::engine) fn enabled() -> bool {
    #[cfg(test)]
    {
        !DISABLE_INDEX.with(std::cell::Cell::get)
    }
    #[cfg(not(test))]
    {
        true
    }
}

pub(in crate::engine) struct QuotaCursor<'a> {
    quota: &'a mut [u64],
    first_step: usize,
}

impl<'a> QuotaCursor<'a> {
    pub(in crate::engine) fn new(quota: &'a mut [u64], allow_index: bool) -> Self {
        let mut first_step = 0;
        if allow_index && quota.len() >= INDEXED_MINIMUM {
            first_step = 1 << quota.len().ilog2();
            for node in 1..=quota.len() {
                let parent = node + node.isolate_lowest_one();
                if parent <= quota.len() {
                    quota[parent - 1] += quota[node - 1];
                }
            }
        }
        Self { quota, first_step }
    }

    pub(in crate::engine) fn is_indexed(&self) -> bool {
        self.first_step != 0
    }

    #[inline]
    pub(in crate::engine) fn take(&mut self, mut draw: u64) -> usize {
        if self.first_step == 0 {
            return take_linear(self.quota, draw);
        }

        // Find the largest prefix whose weight does not exceed the draw.
        // Its length is the zero-based index of the next, selected group.
        let mut prefix = 0;
        let mut step = self.first_step;
        while step != 0 {
            let next = prefix + step;
            if next <= self.quota.len() {
                let weight = self.quota[next - 1];
                if weight <= draw {
                    draw -= weight;
                    prefix = next;
                }
            }
            step /= 2;
        }
        debug_assert!(prefix < self.quota.len());
        let mut node = prefix + 1;
        while node <= self.quota.len() {
            self.quota[node - 1] -= 1;
            node += node.isolate_lowest_one();
        }
        prefix
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chopper_core::random::Random;

    #[test]
    #[ignore = "requires an explicit pinned whole-job fixture"]
    fn measure_quota_lookup() -> anyhow::Result<()> {
        use crate::engine::*;
        use crate::resources::MemoryPool;

        let config =
            std::env::var_os("CHOPPER_EXACT_QUOTA_CONFIG").context("missing pinned job")?;
        let arm = std::env::var("CHOPPER_EXACT_QUOTA_ARM")?;
        ensure!(matches!(arm.as_str(), "linear" | "indexed"), "unknown arm");
        DISABLE_INDEX.with(|flag| flag.set(arm == "linear"));
        let mut job: Job = serde_json::from_slice(&std::fs::read(config)?)?;
        job.random_seed = Some("standalone-exact-quota-lookup-v1".into());
        let [Operation::Assign { groups, .. }] = job.operations.as_slice() else {
            anyhow::bail!("quota benchmark expects one exact operation");
        };
        let uses_index = enabled() && groups.len() >= INDEXED_MINIMUM;
        let pool = Arc::new(MemoryPool::new(
            std::env::var("CHOPPER_EXACT_QUOTA_SHARED_BYTES")?.parse()?,
        ));
        let start = std::time::Instant::now();
        job.validate()?;
        let mut visits = 0;
        let result = process_using(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
            None,
            false,
            None,
            false,
            |job, ctx, partitions, balanced, streaming| {
                visits += 1;
                with_input(job, Reservation::new(ctx), |mut source| {
                    ingest_options(source.as_mut(), job, ctx, partitions, balanced, streaming)
                })
            },
        )?;
        assert_eq!(visits, 1);
        let Processed::Snapshot(ref prepared) = result else {
            anyhow::bail!("expected standard snapshot output");
        };
        let counters = prepared.ctx.clone();
        let analysis = result.publish()?.into_analysis();
        let elapsed_seconds = start.elapsed().as_secs_f64();
        println!(
            "MEASUREMENT {}",
            serde_json::json!({
                "arm": arm,
                "uses_index": uses_index,
                "elapsed_seconds": elapsed_seconds,
                "rows": analysis.rows,
                "files": analysis.output_files,
                "output_csv_bytes": analysis.output_csv_bytes,
                "diagnostics": counters.diagnostics(),
                "peak_reserved_bytes": pool.usage().peak_reserved_bytes,
            })
        );
        drop(analysis);
        drop(counters);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn indexed_cursor_chooses_the_same_existing_quota() {
        let mut rng = Random::new([7; 32]);
        for groups in [1, 3, 31, 32, 33, 63, 64, 65, 127, 256, 1000, 1024] {
            for occupancy in [1, 2, 10, 100, 1000] {
                let mut control: Vec<u64> = (0..groups)
                    .map(|index| {
                        if index % occupancy == 0 {
                            rng.below(32) + 1
                        } else {
                            0
                        }
                    })
                    .collect();
                let mut quota = control.clone();
                let remaining = quota.iter().sum();
                let mut candidate = QuotaCursor::new(&mut quota, true);
                for bound in (1..=remaining).rev() {
                    let draw = rng.below(bound);
                    assert_eq!(candidate.take(draw), take_linear(&mut control, draw));
                }
                assert!(quota.iter().all(|weight| *weight == 0));
            }
        }
    }

    #[test]
    fn every_small_draw_handles_zero_runs_tails_and_prefix_boundaries() {
        for active in 0..6 {
            for next in active..6 {
                for last in next..6 {
                    let mut quota = [0; 33];
                    quota[active * 6] += 1;
                    quota[next * 6] += 1;
                    quota[last * 6 + 2] += 1;
                    for a in 0..3 {
                        for b in 0..2 {
                            let mut control = quota;
                            let mut candidate = quota;
                            let mut cursor = QuotaCursor::new(&mut candidate, true);
                            for draw in [a, b, 0] {
                                assert_eq!(cursor.take(draw), take_linear(&mut control, draw));
                            }
                            assert!(candidate.iter().all(|weight| *weight == 0));
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn full_width_row_count_prefixes_do_not_overflow() {
        let mut quota = [0; 1024];
        quota[3] = u64::MAX - 123;
        quota[1023] = 123;
        let mut control = quota;
        let mut cursor = QuotaCursor::new(&mut quota, true);
        for draw in [u64::MAX - 1, u64::MAX - 300, 1, 0] {
            assert_eq!(cursor.take(draw), take_linear(&mut control, draw));
        }
    }
}
