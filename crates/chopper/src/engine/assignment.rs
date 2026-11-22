//! Exact-assignment scratch retained across strata and charged before allocation.
use super::*;

#[cfg(target_os = "linux")]
pub(super) mod indexed;

pub(super) struct AssignmentScratch {
    pub weights: Vec<u64>,
    pub counts: Vec<u64>,
    pub quota: Vec<u64>,
    pub order: Vec<usize>,
    pub domains: Vec<[u8; 32]>,
    // Dropped after the allocations it owns.
    _reservation: Reservation,
}

impl AssignmentScratch {
    pub(super) fn new(
        groups: &[Allocation],
        shuffled: bool,
        mut reservation: Reservation,
    ) -> Result<Self> {
        let mut weights = Vec::new();
        let mut counts = Vec::new();
        let mut quota = Vec::new();
        let mut order = Vec::new();
        let mut domains = Vec::new();
        reservation.reserve_vec(&mut weights, groups.len())?;
        weights.resize(groups.len(), 0);
        weights_into(groups, &mut weights)?;
        reservation.reserve_vec(&mut counts, groups.len())?;
        counts.resize(groups.len(), 0);
        reservation.reserve_vec(&mut quota, groups.len())?;
        quota.resize(groups.len(), 0);
        reservation.reserve_vec(&mut order, groups.len())?;
        order.resize(groups.len(), 0);
        if shuffled {
            reservation.reserve_vec(&mut domains, groups.len())?;
        }
        Ok(Self {
            weights,
            counts,
            quota,
            order,
            domains,
            _reservation: reservation,
        })
    }

    pub(super) fn reset_quota(&mut self, rows: u64) {
        quotas_into(rows, &self.weights, &mut self.quota, &mut self.order);
    }
}

#[inline]
pub(super) fn take_linear(quota: &mut [u64], mut draw: u64) -> usize {
    let mut index = 0;
    while draw >= quota[index] {
        draw -= quota[index];
        index += 1;
    }
    quota[index] -= 1;
    index
}

#[cfg(test)]
mod tests {
    use super::*;

    fn groups() -> Vec<Allocation> {
        ["33.333333", "33.333333", "33.333334"]
            .into_iter()
            .enumerate()
            .map(|(i, percent)| Allocation {
                name: i.to_string(),
                percent: percent.into(),
            })
            .collect()
    }

    #[test]
    fn exact_and_shared_assignment_capacity() -> Result<()> {
        let groups = groups();
        for shuffled in [false, true] {
            let bytes = groups.len()
                * (3 * std::mem::size_of::<u64>()
                    + std::mem::size_of::<usize>()
                    + if shuffled { 32 } else { 0 });
            for limit in [bytes - 1, bytes, bytes + 1] {
                let workspace = Arc::new(Workspace::new(limit));
                let result = AssignmentScratch::new(
                    &groups,
                    shuffled,
                    Reservation::for_workspace(workspace.clone()),
                );
                assert_eq!(result.is_ok(), limit >= bytes);
                if let Ok(scratch) = result {
                    assert_eq!(workspace.used(), bytes as u64);
                    assert_eq!(scratch.domains.capacity(), if shuffled { 3 } else { 0 });
                    let mut competitor = Reservation::for_workspace(workspace.clone());
                    assert!(competitor.resize(limit - bytes + 1).is_err());
                    drop(scratch);
                    assert_eq!(workspace.used(), 0);
                    competitor.resize(limit)?;
                }
                assert_eq!(workspace.used(), 0);
                if limit == bytes {
                    let mut competitor = Reservation::for_workspace(workspace.clone());
                    competitor.resize(1)?;
                    assert!(AssignmentScratch::new(
                        &groups,
                        shuffled,
                        Reservation::for_workspace(workspace.clone()),
                    )
                    .is_err());
                    assert_eq!(workspace.used(), 1);
                    drop(competitor);
                    let retry = AssignmentScratch::new(
                        &groups,
                        shuffled,
                        Reservation::for_workspace(workspace.clone()),
                    )?;
                    drop(retry);
                    assert_eq!(workspace.used(), 0);
                }
            }
        }
        Ok(())
    }

    #[test]
    fn quota_reuse_preserves_v1_and_capacity() -> Result<()> {
        let groups = groups();
        let workspace = Arc::new(Workspace::new(1024));
        let mut scratch =
            AssignmentScratch::new(&groups, true, Reservation::for_workspace(workspace.clone()))?;
        let retained = workspace.used();
        for n in (0..1000).chain([u64::MAX]) {
            scratch.reset_quota(n);
            assert_eq!(scratch.quota, quotas(n, &scratch.weights));
            assert_eq!(scratch.quota.iter().sum::<u64>(), n);
            assert_eq!(workspace.used(), retained);
            scratch.quota.fill(0); // Simulate consumption by a previous stratum.
        }
        scratch.reset_quota(2);
        assert_eq!(scratch.quota, [1, 0, 1]);
        drop(scratch);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn quota_order_matches_original_stable_sort() {
        // Independent pre-change implementation, including a large tie set.
        for weights in [
            vec![50_000_000, 50_000_000, 0],
            vec![1_000_000; 100],
            vec![1, 99_999_998, 1],
        ] {
            let mut quota = vec![0; weights.len()];
            let mut order = vec![0; weights.len()];
            for rows in (0..301).chain([1_000_000_001, u64::MAX]) {
                let mut expected: Vec<_> = weights
                    .iter()
                    .map(|w| ((rows as u128 * *w as u128) / 100_000_000) as u64)
                    .collect();
                let mut original_order: Vec<_> = (0..weights.len()).collect();
                original_order.sort_by_key(|i| {
                    (
                        std::cmp::Reverse(rows as u128 * weights[*i] as u128 % 100_000_000),
                        *i,
                    )
                });
                for i in original_order
                    .into_iter()
                    .take((rows - expected.iter().sum::<u64>()) as usize)
                {
                    expected[i] += 1;
                }
                quotas_into(rows, &weights, &mut quota, &mut order);
                assert_eq!(quota, expected);
            }
        }
    }

    #[test]
    fn invalid_weights_release_partial_assignment_storage() -> Result<()> {
        let workspace = Arc::new(Workspace::new(1024));
        for invalid in ["1.2.3", "-1", "100.000001", "0"] {
            let groups = vec![Allocation {
                name: "invalid".into(),
                percent: invalid.into(),
            }];
            assert!(AssignmentScratch::new(
                &groups,
                true,
                Reservation::for_workspace(workspace.clone())
            )
            .is_err());
            assert_eq!(workspace.used(), 0);
        }
        let scratch = AssignmentScratch::new(
            &groups(),
            true,
            Reservation::for_workspace(workspace.clone()),
        )?;
        drop(scratch);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }
}
