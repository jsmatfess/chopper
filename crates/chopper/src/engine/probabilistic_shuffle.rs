//! Original probabilistic membership and per-child Uniform in one retained-parent sort.
use super::*;
use crate::{
    observation::{
        physical::{self, Kind},
        Status,
    },
    resources::MemoryAdmission,
};

#[derive(Clone, Copy)]
pub(super) struct Plan {
    assignment: usize,
    shuffle: usize,
}

struct Prepared<'a> {
    membership: streaming::Membership<'a>,
    rows: SortedRows,
}

#[cfg(test)]
std::thread_local! {
    static SERIAL_CONTROL: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

#[cfg(all(
    test,
    target_os = "linux",
    feature = "experimental-probabilistic-shuffle-fusion"
))]
mod tests;

impl Plan {
    pub(super) fn at(job: &Job, step: usize) -> Option<Self> {
        #[cfg(test)]
        if SERIAL_CONTROL.with(std::cell::Cell::get) {
            return None;
        }
        let [Operation::Partition { .. }, Operation::AssignProbabilistic { .. }, shuffle] =
            job.operations.as_slice()
        else {
            return None;
        };
        if step == 1 && uniform(shuffle) && job.compression == chopper_core::Compression::None {
            Some(Self {
                assignment: 1,
                shuffle: 2,
            })
        } else {
            None
        }
    }

    pub(super) fn selected(
        job: &Job,
        step: usize,
        analysis: &Analysis,
        ctx: &Context,
    ) -> Option<Self> {
        let plan = Self::at(job, step)?;
        if cfg!(all(
            target_os = "linux",
            feature = "experimental-probabilistic-shuffle-fusion"
        )) {
            return Some(plan);
        }
        if !ctx.auto_run || job.resources.grouping != chopper_core::Grouping::Auto {
            return None;
        }
        let partition = analysis
            .stages
            .first()
            .filter(|stage| stage.operation == 1)?;
        auto::fuse_probabilistic(
            ctx.memory as u64,
            ctx.workers(),
            analysis.rows,
            ctx.validated_payload_bytes(),
            partition,
        )
        .then_some(plan)
    }

    fn prepare<'a>(
        self,
        data: &Dataset,
        parent: &Group,
        job: &'a Job,
        analysis: &Analysis,
        ctx: &Context,
    ) -> Result<Prepared<'a>> {
        let seed = job
            .random_seed
            .as_deref()
            .context("missing effective seed")?;
        let domain = random::json_domain(seed, self.assignment as u64, &parent.lineage)?;
        let mut membership = streaming::Membership::new(
            &job.operations[self.assignment],
            analysis.header.as_deref(),
            analysis.columns,
            domain,
            ctx,
        )?;
        let mut domain_grant = Reservation::new(ctx);
        let mut domains = Vec::new();
        domain_grant.reserve_vec(&mut domains, membership.counts().len())?;
        for index in 0..membership.counts().len() {
            domains.push(child_metadata::domain(
                parent,
                &membership.entry(self.assignment, index),
                seed,
                self.shuffle,
                ctx,
            )?);
        }
        let member_ctx = ctx.physical_scope([self.assignment + 1, 0]);
        let mut order_ctx = ctx.clone();
        order_ctx.physical_source = member_ctx.physical_identity(Kind::ProbabilisticMembership);
        let mut observation = member_ctx.physical_attempt(Kind::ProbabilisticMembership);
        let mut observed = physical::AllocationCounts {
            len: domains.len(),
            ..Default::default()
        };
        let result = (|| -> Result<SortedRows> {
            #[cfg(any(test, feature = "resource-contract-tests"))]
            ctx.event("Before prepared probabilistic spill", parent.rows)?;
            let mut sorter = Sorter::probabilistic_shuffle(&order_ctx)?;
            for row in data.packed_rows(parent, ctx.max_record)? {
                ctx.check()?;
                let mut row = row?;
                let index = membership.index(row.id, row.fields());
                let key = OperationKey::allocation(
                    index as u64,
                    &domains[index],
                    row.id,
                    Reservation::new(ctx),
                    &mut sorter,
                )?;
                let capacity = key.install(&mut row, &mut sorter)?;
                sorter.push_compact(row, capacity)?;
                if let Some(attempt) = &mut observation {
                    attempt.rows_processed(membership.seen());
                }
            }
            ensure!(
                membership.seen() == parent.rows,
                "probabilistic parent row count mismatch"
            );
            sorter.finish()
        })();
        if let Some(attempt) = observation {
            observed.rows = membership.seen();
            if result.is_ok() {
                observed.groups = observed.len as u64;
                observed.empty_groups =
                    membership.counts().iter().filter(|&&n| n == 0).count() as u64;
            }
            for (slot, &count) in observed.memberships.iter_mut().zip(membership.counts()) {
                *slot = count;
            }
            attempt.allocation(
                result
                    .as_ref()
                    .err()
                    .map_or(Status::Completed, physical::error_status),
                observed,
            );
        }
        Ok(Prepared {
            membership,
            rows: result?,
        })
    }

    fn emit(
        self,
        prepared: Prepared<'_>,
        parent: &Group,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        let Prepared { membership, rows } = prepared;
        output
            .physical_input(ctx.physical_identity(sorted_physical_kind(&rows, Kind::ResidentSort)));
        let mut rows = rows.reusing();
        for (index, &count) in membership.counts().iter().enumerate() {
            ctx.check()?;
            let mut owned = group_metadata::ClonedGroup::begin_child(
                parent,
                &membership.entry(self.assignment, index),
                false,
                output,
                ctx,
            )?;
            for ordinal in 0..count {
                ctx.check()?;
                let row = rows
                    .next()?
                    .context("truncated fused probabilistic allocation")?;
                row.ordinal = ordinal;
                row.key = PackedKey::Bytes(Box::default());
                output.packed_row_ref(&mut owned.group, row)?;
            }
            ctx.check()?;
            owned.finish(output)?;
        }
        ensure!(
            rows.next()?.is_none(),
            "extra fused probabilistic allocation rows"
        );
        Ok(())
    }

    pub(super) fn apply(
        self,
        data: &Dataset,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        for parent in data.groups()? {
            let parent = parent?;
            ctx.probabilistic_shuffle_attempt();
            let prepared = exact_plan::Proposal::new(self, &parent).prepare(
                ctx,
                |plan, parent| plan.prepare(data, parent, job, analysis, ctx),
                |error| error.downcast_ref::<MemoryAdmission>().is_some(),
            )?;
            match prepared {
                exact_plan::Attempt::Prepared(prepared) => {
                    self.emit(prepared, &parent, ctx, output)?
                }
                exact_plan::Attempt::Retry(_) => {
                    ctx.probabilistic_shuffle_retry();
                    ctx.event("Retrying probabilistic assignment and shuffle", parent.rows)?;
                    let span = ctx.physical_span(Kind::Fallback);
                    if let Some(span) = span {
                        span.finish(0);
                    }
                    self.original(data, &parent, job, analysis, ctx, output)?;
                }
            }
        }
        Ok(())
    }

    fn original(
        self,
        data: &Dataset,
        parent: &Group,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        let mut assignment = ctx.physical_scope([self.assignment + 1, 0]);
        assignment.physical_source = ctx
            .physical_identity(Kind::Fallback)
            .or(ctx.physical_source);
        let mut allocated = DatasetWriter::new(&assignment)?;
        apply_parent(
            data,
            parent,
            &job.operations[self.assignment],
            self.assignment,
            job,
            analysis,
            &assignment,
            &mut allocated,
            None,
            None,
        )?;
        let allocated = allocated.finish()?;
        let mut shuffle = ctx.physical_scope([self.shuffle + 1, 0]);
        shuffle.physical_source = allocated.physical_source;
        for child in allocated.groups()? {
            apply_parent(
                &allocated,
                &*child?,
                &job.operations[self.shuffle],
                self.shuffle,
                job,
                analysis,
                &shuffle,
                output,
                None,
                None,
            )?;
        }
        Ok(())
    }
}
