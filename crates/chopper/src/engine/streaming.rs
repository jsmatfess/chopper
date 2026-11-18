//! Count-independent membership with bounded routing and a sorting fallback.
use super::*;

pub(super) fn eligible(operation: &Operation) -> bool {
    matches!(
        operation,
        Operation::Interleaved { .. } | Operation::AssignProbabilistic { .. }
    )
}

fn observation_kind(operation: &Operation) -> crate::observation::physical::Kind {
    if matches!(operation, Operation::Interleaved { .. }) {
        crate::observation::physical::Kind::InterleavedMembership
    } else {
        crate::observation::physical::Kind::ProbabilisticMembership
    }
}

// Membership owns the original v1 scope, encounter counter and charged metadata.
// Keeping it independent of materialization lets routing plans share the same draws.
pub(super) struct Membership<'a> {
    operation: &'a Operation,
    counts: Vec<u64>,
    columns: Vec<usize>,
    weights: Vec<u64>,
    domain: [u8; 32],
    seen: u64,
    _reservation: Reservation,
}
impl<'a> Membership<'a> {
    pub fn new(
        operation: &'a Operation,
        header: Option<&[String]>,
        width: usize,
        domain: [u8; 32],
        ctx: &Context,
    ) -> Result<Self> {
        Self::with_reservation(operation, header, width, domain, ctx, Reservation::new(ctx))
    }
    pub(super) fn with_reservation(
        operation: &'a Operation,
        header: Option<&[String]>,
        width: usize,
        domain: [u8; 32],
        ctx: &Context,
        mut reservation: Reservation,
    ) -> Result<Self> {
        let (count, strata, allocations) = match operation {
            Operation::Interleaved { files } => (usize::try_from(*files)?, &[][..], &[][..]),
            Operation::AssignProbabilistic { groups, strata } => {
                (groups.len(), strata.as_slice(), groups.as_slice())
            }
            _ => unreachable!("streaming membership operation"),
        };
        let bytes = count
            .checked_mul(std::mem::size_of::<u64>())
            .and_then(|n| n.checked_add(strata.len().checked_mul(std::mem::size_of::<usize>())?))
            .and_then(|n| n.checked_add(allocations.len().checked_mul(std::mem::size_of::<u64>())?))
            .context("streaming group metadata overflow")?;
        ensure!(
            bytes <= ctx.memory / 16,
            "streaming group metadata exceeds memory budget"
        );
        let mut counts = Vec::new();
        let mut columns = Vec::new();
        let mut weights = Vec::new();
        reservation.reserve_vec(&mut counts, count)?;
        counts.resize(count, 0);
        reservation.reserve_vec(&mut columns, strata.len())?;
        for column in strata {
            columns.push(resolve_column(column, header, width)?);
        }
        reservation.reserve_vec(&mut weights, allocations.len())?;
        weights.resize(allocations.len(), 0);
        if !allocations.is_empty() {
            weights_into(allocations, &mut weights)?;
        }
        ensure!(
            reservation.bytes() <= (ctx.memory / 16) as u64,
            "streaming group metadata exceeds memory budget"
        );
        Ok(Self {
            operation,
            counts,
            columns,
            weights,
            domain: Self::scoped_domain(&domain),
            seen: 0,
            _reservation: reservation,
        })
    }

    pub fn scoped_domain(domain: &[u8; 32]) -> [u8; 32] {
        random::algorithm_domain(domain, "probabilistic-allocation-v1")
    }
    pub fn index(&mut self, id: u64, fields: FieldViews<'_>) -> usize {
        let index = self.index_in(&self.domain, self.seen, id, fields);
        self.seen += 1;
        self.counts[index] += 1;
        index
    }
    pub fn index_in(&self, domain: &[u8; 32], seen: u64, id: u64, fields: FieldViews<'_>) -> usize {
        if self.exact() {
            (seen % self.counts.len() as u64) as usize
        } else {
            random::categorical_views(domain, id, fields, &self.columns, &self.weights)
        }
    }
    pub fn counts(&self) -> &[u64] {
        &self.counts
    }
    pub fn seen(&self) -> u64 {
        self.seen
    }
    pub fn exact(&self) -> bool {
        matches!(self.operation, Operation::Interleaved { .. })
    }
    pub fn validate_seen(&self, seen: u64) -> Result<()> {
        ensure!(
            !self.exact() || seen >= self.counts.len() as u64,
            "cannot split {} rows into {} nonempty balanced groups",
            seen,
            self.counts.len()
        );
        Ok(())
    }
    pub(super) fn entry(&self, step: usize, index: usize) -> child_metadata::Entry<'_> {
        match self.operation {
            Operation::Interleaved { .. } => child_metadata::Entry::part(step, index as u64 + 1),
            Operation::AssignProbabilistic { groups, .. } => {
                child_metadata::Entry::allocation(step, &groups[index].name)
            }
            _ => unreachable!("streaming membership operation"),
        }
    }
}

pub(super) struct StreamingGroups<'a> {
    sorter: Sorter,
    membership: Membership<'a>,
    observation: Option<crate::observation::physical::Attempt>,
    ctx: &'a Context,
    observed: crate::observation::physical::AllocationCounts,
}
impl<'a> StreamingGroups<'a> {
    pub fn new(
        operation: &'a Operation,
        header: Option<&[String]>,
        width: usize,
        domain: [u8; 32],
        ctx: &'a Context,
    ) -> Result<Self> {
        let mut order_ctx = ctx.clone();
        let kind = observation_kind(operation);
        order_ctx.physical_source = ctx.physical_identity(kind);
        Ok(Self {
            sorter: Sorter::streaming(&order_ctx),
            membership: Membership::new(operation, header, width, domain, ctx)?,
            observation: None,
            ctx,
            observed: Default::default(),
        })
    }
    #[cfg(test)]
    fn with_reservation(
        operation: &'a Operation,
        header: Option<&[String]>,
        width: usize,
        domain: [u8; 32],
        ctx: &'a Context,
        reservation: Reservation,
    ) -> Result<Self> {
        let mut order_ctx = ctx.clone();
        let kind = observation_kind(operation);
        order_ctx.physical_source = ctx.physical_identity(kind);
        Ok(Self {
            sorter: Sorter::streaming(&order_ctx),
            membership: Membership::with_reservation(
                operation,
                header,
                width,
                domain,
                ctx,
                reservation,
            )?,
            observation: None,
            ctx,
            observed: Default::default(),
        })
    }
    #[cfg(test)]
    pub fn push(&mut self, mut row: Row) -> Result<Vec<String>> {
        self.start_observation();
        let index = self
            .membership
            .index(row.id, FieldViews::owned(&row.fields));
        row.key = (index as u64).to_be_bytes().to_vec();
        let result = self.sorter.push_reusing_fields(row);
        if let Err(error) = &result {
            self.finish_observation(crate::observation::physical::error_status(error));
        } else if let Some(attempt) = &mut self.observation {
            attempt.rows_processed(self.membership.seen());
        }
        result
    }
    pub fn push_compact(&mut self, mut row: PackedRow) -> Result<Option<PackedRow>> {
        self.start_observation();
        let index = self.membership.index(row.id, row.fields());
        let result = (|| {
            row.set_index_key(index as u64)?;
            self.sorter.push_compact_reusing(row, 8)
        })();
        if let Err(error) = &result {
            self.finish_observation(crate::observation::physical::error_status(error));
        } else {
            if let Some(attempt) = &mut self.observation {
                attempt.rows_processed(self.membership.seen());
            }
        }
        result
    }
    fn start_observation(&mut self) {
        if self.observation.is_none() {
            self.observation = self
                .ctx
                .physical_attempt(observation_kind(self.membership.operation));
        }
    }
    fn finish_observation(&mut self, status: crate::observation::Status) {
        self.observed.rows = self.membership.seen();
        self.observed.len = self.membership.counts().len();
        if let Some(attempt) = self.observation.take() {
            attempt.allocation(status, self.observed);
        }
    }
    pub fn emit(
        mut self,
        parent: &Group,
        step: usize,
        output: &mut impl RowSink,
        ctx: &Context,
    ) -> Result<()> {
        let result = (|| -> Result<()> {
            if self.membership.seen() == 0 {
                self.start_observation();
            }
            self.membership.validate_seen(self.membership.seen())?;
            let sorted = std::mem::replace(&mut self.sorter, Sorter::new(self.ctx, SortOrder::Key))
                .finish()?;
            output.physical_input(ctx.physical_identity(sorted_physical_kind(
                &sorted,
                crate::observation::physical::Kind::ResidentSort,
            )));
            let mut rows = sorted.reusing();
            for (index, count) in self.membership.counts().iter().enumerate() {
                ctx.check()?;
                let mut owned = group_metadata::ClonedGroup::begin_child(
                    parent,
                    &self.membership.entry(step, index),
                    self.membership.exact(),
                    output,
                    ctx,
                )?;
                let group = &mut owned.group;
                for _ in 0..*count {
                    ctx.check()?;
                    let row = rows.next()?.context("truncated streaming allocation")?;
                    row.key = PackedKey::Bytes(Box::default());
                    output.packed_row_ref(group, row)?;
                }
                ctx.check()?;
                owned.finish(output)?;
                self.observed.groups += 1;
                self.observed.empty_groups += u64::from(*count == 0);
                if index < crate::observation::physical::MAX_MEMBERSHIPS {
                    self.observed.memberships[index] = *count;
                }
            }
            Ok(())
        })();
        self.observed.rows = self.membership.seen();
        self.observed.len = self.membership.counts().len();
        if let Some(attempt) = self.observation.take() {
            attempt.allocation(
                result.as_ref().err().map_or(
                    crate::observation::Status::Completed,
                    crate::observation::physical::error_status,
                ),
                self.observed,
            );
        }
        result
    }
}

impl Drop for StreamingGroups<'_> {
    fn drop(&mut self) {
        self.observed.rows = self.membership.seen();
        self.observed.len = self.membership.counts().len();
        if let Some(attempt) = self.observation.take() {
            attempt.allocation(crate::observation::Status::Interrupted, self.observed);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn context() -> Result<Context> {
        Context::new(
            &Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )
    }

    fn probabilistic() -> Operation {
        Operation::AssignProbabilistic {
            groups: vec![
                Allocation {
                    name: "a".into(),
                    percent: "35".into(),
                },
                Allocation {
                    name: "b".into(),
                    percent: "65".into(),
                },
            ],
            strata: vec![Column::Index(2), Column::Index(0)],
        }
    }

    #[test]
    fn routing_starts_on_first_row_after_membership() -> Result<()> {
        use crate::observation::{physical::Kind, Status};
        let mut ctx = context()?;
        let facts = Arc::new(std::sync::Mutex::new(Vec::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let operation = probabilistic();
        let mut state = StreamingGroups::new(&operation, None, 3, [7; 32], &ctx)?;
        assert!(
            facts.lock().unwrap().is_empty(),
            "membership setup must not announce future work"
        );
        assert!(!facts
            .lock()
            .unwrap()
            .iter()
            .any(|f| f.kind == Kind::Routing));
        state.push_compact(PackedRow::new(Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["id".into(), "key".into(), "stratum".into()],
        })?)?;
        let facts = facts.lock().unwrap();
        let membership = facts
            .iter()
            .position(|f| f.kind == Kind::ProbabilisticMembership && f.status == Status::Active)
            .unwrap();
        let routing = facts
            .iter()
            .position(|f| f.kind == Kind::Routing && f.status == Status::Active)
            .unwrap();
        assert!(membership < routing);
        drop(facts);
        Ok(())
    }

    #[test]
    fn probabilistic_push_denial_is_attributed_failure() -> Result<()> {
        use crate::observation::{physical::Kind, Status};
        use crate::resources::MemoryPool;
        let pool = Arc::new(MemoryPool::new(16384));
        let mut ctx = Context::with_memory_pool(
            &Resources {
                memory_mb: 32.into(),
                workers: 1,
                max_record_bytes: 1048576,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let facts = Arc::new(std::sync::Mutex::new(Vec::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let operation = probabilistic();
        let mut state = StreamingGroups::new(&operation, None, 3, [7; 32], &ctx)?;
        let row = PackedRow::new(Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["id".into(), "key".into(), "stratum".into()],
        })?;
        assert!(state.push_compact(row).is_err());
        drop(state);
        let facts = facts.lock().unwrap();
        assert!(facts
            .iter()
            .any(|f| f.kind == Kind::ProbabilisticMembership && f.status == Status::Failed));
        assert!(!facts
            .iter()
            .any(|f| f.kind == Kind::ProbabilisticMembership && f.status == Status::Interrupted));
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    #[test]
    fn streaming_state_exact_capacity_shared_pressure_and_retry() -> Result<()> {
        let ctx = context()?;
        for operation in [Operation::Interleaved { files: 3 }, probabilistic()] {
            let bytes = match &operation {
                Operation::Interleaved { .. } => 3 * std::mem::size_of::<u64>(),
                _ => 4 * std::mem::size_of::<u64>() + 2 * std::mem::size_of::<usize>(),
            };
            for limit in [bytes - 1, bytes, bytes + 1] {
                let workspace = Arc::new(Workspace::new(limit));
                let result = StreamingGroups::with_reservation(
                    &operation,
                    None,
                    3,
                    [7; 32],
                    &ctx,
                    Reservation::for_workspace(workspace.clone()),
                );
                assert_eq!(result.is_ok(), limit >= bytes);
                if let Ok(state) = result {
                    assert_eq!(workspace.used(), bytes as u64);
                    assert_eq!(
                        state.membership.counts.capacity(),
                        state.membership.counts.len()
                    );
                    drop(state);
                }
                assert_eq!(workspace.used(), 0);
                let mut other = Reservation::for_workspace(workspace.clone());
                other.resize(limit)?;
                assert!(StreamingGroups::with_reservation(
                    &operation,
                    None,
                    3,
                    [7; 32],
                    &ctx,
                    Reservation::for_workspace(workspace.clone())
                )
                .is_err());
                assert_eq!(workspace.used(), limit as u64);
                drop(other);
                if limit >= bytes {
                    drop(StreamingGroups::with_reservation(
                        &operation,
                        None,
                        3,
                        [7; 32],
                        &ctx,
                        Reservation::for_workspace(workspace.clone()),
                    )?);
                    assert_eq!(workspace.used(), 0);
                }
            }
        }
        Ok(())
    }

    #[test]
    fn streaming_invalid_columns_weights_and_local_limit_release_storage() -> Result<()> {
        let ctx = context()?;
        let workspace = Arc::new(Workspace::new(ctx.memory));
        let mut bad_column = probabilistic();
        if let Operation::AssignProbabilistic { strata, .. } = &mut bad_column {
            strata.push(Column::Index(3));
        }
        let mut bad_weight = probabilistic();
        if let Operation::AssignProbabilistic { groups, .. } = &mut bad_weight {
            groups[1].percent = "invalid".into();
        }
        for operation in [
            bad_column,
            bad_weight,
            Operation::Interleaved {
                files: (ctx.memory / 16 / 8 + 1) as u64,
            },
        ] {
            assert!(StreamingGroups::with_reservation(
                &operation,
                None,
                3,
                [7; 32],
                &ctx,
                Reservation::for_workspace(workspace.clone())
            )
            .is_err());
            assert_eq!(workspace.used(), 0);
        }
        assert_eq!(
            workspace.peak(),
            4 * 8 + 2 * std::mem::size_of::<usize>() as u64
        );
        Ok(())
    }

    #[test]
    fn routed_input_reuses_decode_storage_until_fallback_takes_ownership() -> Result<()> {
        let ctx = Context::new(
            &Resources {
                memory_mb: 64.into(),
                max_record_bytes: 1024 * 1024,
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut input = DatasetWriter::new(&ctx)?;
        let mut parent = input.begin(vec![], false);
        for id in 0..140 {
            input.row(
                &mut parent,
                &Row {
                    id,
                    ordinal: id,
                    key: vec![],
                    fields: vec![if id == 0 {
                        "x".repeat(10000)
                    } else {
                        id.to_string()
                    }],
                },
            )?;
        }
        input.end(parent.clone())?;
        let input = input.finish()?;
        let operation = Operation::Interleaved { files: 70 };
        let mut routed = StreamingGroups::new(&operation, None, 1, [7; 32], &ctx)?;
        let mut rows = input.rows(&parent, ctx.max_record)?;
        let mut previous = None;
        let mut pointer = None;
        while let Some(row) = rows.next_packed(previous.take())? {
            let id = row.id;
            let address = row.fields().next().unwrap().as_ptr();
            if id < 64 {
                if let Some(pointer) = pointer {
                    assert_eq!(
                        address, pointer,
                        "direct routing must reuse the wide allocation"
                    );
                }
                pointer = Some(address);
            }
            previous = routed.push_compact(row)?;
            assert_eq!(
                previous.is_some(),
                id < 64,
                "fallback retains row ownership"
            );
        }
        let mut output = DatasetWriter::new(&ctx)?;
        routed.emit(&parent, 0, &mut output, &ctx)?;
        let output = output.finish()?;
        for (index, group) in output.groups()?.enumerate() {
            let group = group?;
            let rows = output
                .rows(&group, ctx.max_record)?
                .collect::<Result<Vec<_>>>()?;
            assert_eq!(
                rows.iter().map(|row| row.id).collect::<Vec<_>>(),
                [index as u64, index as u64 + 70]
            );
            for row in rows {
                assert_eq!(
                    row.fields,
                    [if row.id == 0 {
                        "x".repeat(10000)
                    } else {
                        row.id.to_string()
                    }]
                );
            }
        }
        assert_eq!(ctx.diagnostics()["routing_fallbacks"], 1);
        drop(rows);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.diagnostics()["temporary_path_reserved_bytes"]
                .as_u64()
                .unwrap()
                + ctx.directory_reserved_bytes()
        );
        drop(input);
        drop(output);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn compact_streaming_matches_owned_through_routing_and_sort_fallback() -> Result<()> {
        let allocations = vec![
            Allocation {
                name: "empty".into(),
                percent: "0".into(),
            },
            Allocation {
                name: "a".into(),
                percent: "35".into(),
            },
            Allocation {
                name: "b".into(),
                percent: "65".into(),
            },
        ];
        for operation in [
            Operation::Interleaved { files: 70 },
            Operation::AssignProbabilistic {
                groups: allocations,
                strata: vec![Column::Index(2), Column::Index(1)],
            },
        ] {
            let mut reference = None;
            for grouping in [Grouping::Auto, Grouping::Sort] {
                for compact in [false, true] {
                    let ctx = Context::new(
                        &Resources {
                            memory_mb: 32.into(),
                            max_record_bytes: 1024 * 1024,
                            workers: 1,
                            grouping,
                            ..Default::default()
                        },
                        Arc::new(AtomicBool::new(false)),
                        Arc::new(|_| {}),
                    )?;
                    let mut routed = StreamingGroups::new(&operation, None, 3, [7; 32], &ctx)?;
                    for id in 0..1000 {
                        let row = Row {
                            id,
                            ordinal: id,
                            key: vec![9; 16],
                            fields: vec![
                                id.to_string(),
                                if id == 7 {
                                    "界".repeat(10000)
                                } else {
                                    "duplicate\0\n\"".into()
                                },
                                (id % 7).to_string(),
                            ],
                        };
                        if compact {
                            routed.push_compact(PackedRow::new(row)?)?;
                        } else {
                            routed.push(row)?;
                        }
                    }
                    let parent = Group {
                        offset: 0,
                        rows: 1000,
                        lineage: vec![],
                        exact: false,
                    };
                    let mut writer = DatasetWriter::new(&ctx)?;
                    routed.emit(&parent, 2, &mut writer, &ctx)?;
                    let data = writer.finish()?;
                    let mut actual = Vec::new();
                    let mut ids = Vec::new();
                    for group in data.groups()? {
                        let group = group?;
                        actual.extend_from_slice(serde_json::to_string(&group)?.as_bytes());
                        for row in data.rows(&group, ctx.max_record)? {
                            let row = row?;
                            ids.push(row.id);
                            write_row(&mut actual, &row)?;
                        }
                    }
                    ids.sort_unstable();
                    assert_eq!(ids, (0..1000).collect::<Vec<_>>());
                    if let Some(reference) = &reference {
                        assert_eq!(&actual, reference);
                    } else {
                        reference = Some(actual);
                    }
                    assert_eq!(
                        ctx.diagnostics()["workspace_reserved_bytes"],
                        ctx.diagnostics()["temporary_path_reserved_bytes"]
                            .as_u64()
                            .unwrap()
                            + ctx.directory_reserved_bytes()
                    );
                    if grouping == Grouping::Auto
                        && matches!(operation, Operation::Interleaved { .. })
                    {
                        assert_eq!(ctx.diagnostics()["routing_fallbacks"], 1);
                    }
                    drop(data);
                    assert_eq!(
                        ctx.diagnostics()["workspace_reserved_bytes"],
                        ctx.directory_reserved_bytes()
                    );
                    assert_eq!(ctx.used(), 0);
                }
            }
        }
        Ok(())
    }
}
