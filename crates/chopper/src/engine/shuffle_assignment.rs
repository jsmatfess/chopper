//! Cut a full parent permutation into largest-remainder allocation ranges.
//! This preserves the joint law of membership and order, not a seeded realization.
use super::*;
use crate::observation::physical::{self, Kind};

pub(super) const ENABLED: bool = true;

#[derive(Clone, Copy)]
pub(super) struct Plan<'a> {
    pub assignment_step: usize,
    pub groups: &'a [Allocation],
    shuffle_step: usize,
    strategy: Shuffle,
}

impl<'a> Plan<'a> {
    pub fn at(job: &'a Job, step: usize) -> Option<Self> {
        let Operation::Shuffle { strategy } = job.operations.get(step)? else {
            return None;
        };
        let assignment_step = step.checked_add(1)?;
        let Operation::Assign { groups, strata } = job.operations.get(assignment_step)? else {
            return None;
        };
        if !strata.is_empty()
            || matches!(
                job.operations.get(assignment_step.checked_add(1)?),
                Some(Operation::Shuffle {
                    strategy: Shuffle::Auto | Shuffle::Uniform
                })
            )
        {
            return None;
        }
        Some(Self {
            assignment_step,
            groups,
            shuffle_step: step,
            strategy: *strategy,
        })
    }

    pub fn apply(
        self,
        data: &Dataset,
        job: &Job,
        _analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        let producer = ctx.physical_scope([self.shuffle_step + 1, self.assignment_step + 1]);
        for parent in data.groups()? {
            producer.check()?;
            let parent = parent?;
            // Admission precedes permutation construction; denial is terminal.
            let scratch = AssignmentScratch::new(self.groups, false, Reservation::new(&producer))?;
            let domain = random::json_domain(
                job.random_seed
                    .as_deref()
                    .context("shuffle requires effective seed")?,
                self.shuffle_step as u64,
                &parent.lineage,
            )?;
            let (rows, memory_kind) = if self.strategy == Shuffle::FisherYates {
                let mut resident = ResidentShuffle::new(&producer, domain);
                for row in data.packed_rows(&parent, producer.max_record)? {
                    producer.check()?;
                    resident.push_compact(row?)?;
                }
                (SortedRows::Memory(resident.finish()?), Kind::FisherYates)
            } else {
                let mut sorter = Sorter::new(&producer, SortOrder::Random(domain));
                for row in data.packed_rows(&parent, producer.max_record)? {
                    producer.check()?;
                    let mut row = row?;
                    let key = random::block(&domain, row.id, 0);
                    row.key = PackedKey::Random(key[..16].try_into().unwrap());
                    sorter.push_compact(row, 16)?;
                }
                (sorter.finish()?, Kind::ResidentSort)
            };
            self.emit_prepared(rows, &parent, output, &producer, memory_kind, scratch)?;
        }
        Ok(())
    }

    /// Ingestion already owns the permutation and has no raw-input replay boundary.
    pub fn emit_sorted(
        self,
        rows: SortedRows,
        parent: &Group,
        output: &mut impl RowSink,
        ctx: &Context,
        memory_kind: Kind,
    ) -> Result<StageStats> {
        let scratch = AssignmentScratch::new(self.groups, false, Reservation::new(ctx))?;
        self.emit_prepared(rows, parent, output, ctx, memory_kind, scratch)
    }

    fn emit_prepared(
        self,
        rows: SortedRows,
        parent: &Group,
        output: &mut impl RowSink,
        ctx: &Context,
        memory_kind: Kind,
        mut scratch: AssignmentScratch,
    ) -> Result<StageStats> {
        let producer = ctx.physical_scope([self.shuffle_step + 1, self.assignment_step + 1]);
        let mut membership = ctx.physical_scope([self.assignment_step + 1, 0]);
        membership.physical_source =
            producer.physical_identity(sorted_physical_kind(&rows, memory_kind));
        let ctx = &membership;
        let mut observation = ctx.physical_attempt(Kind::ExactMembership);
        let mut observed = physical::AllocationCounts {
            len: self.groups.len(),
            ..Default::default()
        };
        let result = (|| {
            ctx.check()?;
            let output_groups =
                u64::try_from(self.groups.len()).context("assignment group count overflow")?;
            scratch.reset_quota(parent.rows);
            let mut stats = StageStats {
                operation: self.assignment_step + 1,
                input_groups: 1,
                output_groups,
                smallest_group: scratch.quota.iter().copied().min().unwrap_or(0),
                largest_group: scratch.quota.iter().copied().max().unwrap_or(0),
                empty_groups: 0,
            };
            output.physical_input(ctx.physical_identity(Kind::ExactMembership));
            let mut rows = rows.reusing();
            for (index, allocation) in self.groups.iter().enumerate() {
                ctx.check()?;
                let count = scratch.quota[index];
                let mut owned = group_metadata::ClonedGroup::begin_child(
                    parent,
                    &child_metadata::Entry::allocation(self.assignment_step, &allocation.name),
                    false,
                    output,
                    ctx,
                )?;
                for ordinal in 0..count {
                    ctx.check()?;
                    let row = rows.next()?.context("truncated shuffle assignment")?;
                    row.key = PackedKey::Bytes(Box::default());
                    row.ordinal = ordinal;
                    output.packed_row_ref(&mut owned.group, row)?;
                    observed.rows += 1;
                    if index < physical::MAX_MEMBERSHIPS {
                        observed.memberships[index] += 1;
                    }
                    if let Some(attempt) = &mut observation {
                        attempt.rows_processed(observed.rows);
                    }
                }
                ctx.check()?;
                owned.finish(output)?;
                observed.groups += 1;
                observed.empty_groups += u64::from(count == 0);
                stats.empty_groups += u64::from(count == 0);
            }
            ctx.check()?;
            ensure!(rows.next()?.is_none(), "trailing shuffle assignment rows");
            ensure!(
                observed.rows == parent.rows,
                "shuffle assignment row count mismatch"
            );
            Ok(stats)
        })();
        if let Some(attempt) = observation {
            attempt.allocation(
                result.as_ref().err().map_or(
                    crate::observation::Status::Completed,
                    physical::error_status,
                ),
                observed,
            );
        }
        result
    }
}

#[cfg(test)]
mod tests;
