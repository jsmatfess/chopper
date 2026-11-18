//! Preserve logical parent scopes while routing three count-independent stages once.
use super::*;
use streaming::Membership;

#[derive(Debug)]
struct CounterLimit;
impl std::fmt::Display for CounterLimit {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("routing chain counter capacity limit")
    }
}
impl std::error::Error for CounterLimit {}
pub(super) fn retry(error: &anyhow::Error) -> bool {
    error.downcast_ref::<CounterLimit>().is_some()
        || error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_some()
}
fn bounded(condition: bool) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(CounterLimit.into())
    }
}

#[derive(Clone, Copy)]
pub(super) struct Plan<'a> {
    first: &'a Operation,
    columns: &'a [Column],
    last: &'a Operation,
    seed: &'a str,
    step: usize,
}
impl<'a> Plan<'a> {
    pub fn at(job: &'a Job, step: usize) -> Option<Self> {
        let first = job.operations.get(step)?;
        let Operation::Partition { columns } = job.operations.get(step + 1)? else {
            return None;
        };
        let last = job.operations.get(step + 2)?;
        (streaming::eligible(first) && streaming::eligible(last)).then_some(Self {
            first,
            columns,
            last,
            seed: job.random_seed.as_deref()?,
            step,
        })
    }
    pub fn stats(self) -> [StageStats; 3] {
        std::array::from_fn(|index| StageStats {
            operation: self.step + index + 1,
            input_groups: 0,
            output_groups: 0,
            smallest_group: u64::MAX,
            largest_group: 0,
            empty_groups: 0,
        })
    }
    pub fn apply(
        self,
        data: &Dataset,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<[StageStats; 3]> {
        let mut total = self.stats();
        let mut count = 0;
        for parent in data.groups()? {
            let parent = parent?;
            let attempt = exact_plan::Proposal::new(self, &parent).prepare(
                ctx,
                |plan, parent| {
                    let mut state = State::new(
                        plan,
                        parent,
                        analysis.header.as_deref(),
                        analysis.columns,
                        ctx,
                    )?;
                    let mut rows = data.rows(parent, ctx.max_record)?;
                    let mut previous = None;
                    while let Some(row) = rows.next_packed(previous.take())? {
                        previous = state.push(row)?;
                    }
                    Ok(state)
                },
                retry,
            )?;
            let stats = match attempt {
                exact_plan::Attempt::Prepared(state) => {
                    let stats = state.emit(output)?;
                    count += parent.rows;
                    stats
                }
                exact_plan::Attempt::Retry(_) => {
                    ctx.event(
                        "Retrying retained routing parent without fusion",
                        parent.rows,
                    )?;
                    ctx.streaming_chain_retry();
                    self.original(data, &parent, job, analysis, ctx, output)?
                }
            };
            for (total, current) in total.iter_mut().zip(stats) {
                total.input_groups += current.input_groups;
                total.output_groups += current.output_groups;
                if current.output_groups > 0 {
                    total.smallest_group = total.smallest_group.min(current.smallest_group);
                }
                total.largest_group = total.largest_group.max(current.largest_group);
                total.empty_groups += current.empty_groups;
                ensure!(
                    total.output_groups <= ctx.max_files,
                    "logical group count exceeds max_files"
                );
            }
        }
        finish(&mut total);
        ctx.streaming_chain_fused(count);
        Ok(total)
    }
    /// Replay only this retained parent. Materialize the original stages before
    /// copying to the caller's sink; errors during that copy are terminal too.
    #[allow(clippy::too_many_arguments)]
    fn original(
        self,
        data: &Dataset,
        parent: &Group,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<[StageStats; 3]> {
        let mut writer = DatasetWriter::new(ctx)?;
        apply_parent(
            data,
            parent,
            self.first,
            self.step,
            job,
            analysis,
            ctx,
            &mut writer,
            None,
            None,
        )?;
        let mut data = writer.finish()?;
        let mut stats = self.stats();
        stats[0] = dataset_stats(&data, self.step + 1, 1, ctx)?;
        for (offset, operation) in [(1, &job.operations[self.step + 1]), (2, self.last)] {
            let before = data.groups;
            data = apply(&data, operation, self.step + offset, job, analysis, ctx)?;
            stats[offset] = dataset_stats(&data, self.step + offset + 1, before, ctx)?;
        }
        for parent in data.groups()? {
            let parent = parent?;
            let mut group =
                group_metadata::ClonedGroup::begin(&parent, output, Reservation::new(ctx))?;
            for row in data.packed_rows(&parent, ctx.max_record)? {
                ctx.check()?;
                output.packed_row_ref(&mut group.group, &row?)?;
            }
            group.finish(output)?;
        }
        Ok(stats)
    }
}
fn include(stats: &mut StageStats, rows: u64) {
    stats.output_groups += 1;
    stats.smallest_group = stats.smallest_group.min(rows);
    stats.largest_group = stats.largest_group.max(rows);
    stats.empty_groups += u64::from(rows == 0);
}
fn finish(stats: &mut [StageStats; 3]) {
    for stats in stats {
        if stats.output_groups == 0 {
            stats.smallest_group = 0;
        }
    }
}

struct Entry {
    key: Vec<u8>,
    values: Vec<String>,
    counts: Vec<u64>,
    seen: u64,
    first: usize,
    domain: [u8; 32],
}
pub(super) struct State<'a, 'b> {
    plan: Plan<'a>,
    parent: &'b Group,
    ctx: &'b Context,
    first: Membership<'a>,
    last: Membership<'a>,
    columns: Vec<usize>,
    entries: Vec<Entry>,
    reservation: Reservation,
    limit: usize,
    sorter: Sorter,
}
impl<'a, 'b> State<'a, 'b> {
    pub fn new(
        plan: Plan<'a>,
        parent: &'b Group,
        header: Option<&[String]>,
        width: usize,
        ctx: &'b Context,
    ) -> Result<Self> {
        let domain = random::json_domain(plan.seed, plan.step as u64, &parent.lineage)?;
        let first = Membership::new(plan.first, header, width, domain, ctx)?;
        let last = Membership::new(plan.last, header, width, [0; 32], ctx)?;
        let mut reservation = Reservation::new(ctx);
        let mut columns = Vec::new();
        reservation.reserve_vec(&mut columns, plan.columns.len())?;
        for column in plan.columns {
            columns.push(resolve_column(column, header, width)?);
        }
        let limit = ctx.memory / 32;
        bounded(reservation.bytes() as usize <= limit)?;
        Ok(Self {
            plan,
            parent,
            ctx,
            first,
            last,
            columns,
            entries: Vec::new(),
            reservation,
            limit,
            // Value fanout is unknown: admit a resident first buffer before
            // selecting bounded routing or external merging.
            sorter: Sorter::new(ctx, SortOrder::Key),
        })
    }
    pub fn reserve_parser(&mut self, reservation: &mut Reservation, bytes: usize) -> Result<()> {
        self.sorter.reserve_input(reservation, bytes)
    }
    fn reserve<T>(
        reservation: &mut Reservation,
        values: &mut Vec<T>,
        capacity: usize,
        limit: usize,
    ) -> Result<()> {
        if capacity > values.capacity() {
            let growth = capacity
                .checked_mul(std::mem::size_of::<T>())
                .context("routing counter capacity overflow")?;
            bounded(
                (reservation.bytes() as usize)
                    .checked_add(growth)
                    .is_some_and(|bytes| bytes <= limit),
            )?;
            reservation.reserve_vec(values, capacity)?;
            bounded(reservation.bytes() as usize <= limit)?;
        }
        Ok(())
    }
    fn entry(&mut self, key: &[u8], first: usize, fields: FieldViews<'_>) -> Result<usize> {
        match self
            .entries
            .binary_search_by(|entry| entry.key.as_slice().cmp(key))
        {
            Ok(index) => Ok(index),
            Err(index) => {
                bounded(self.entries.len() < 256)?;
                if self.entries.len() == self.entries.capacity() {
                    let capacity = (self.entries.capacity().max(4) * 2).min(256);
                    Self::reserve(
                        &mut self.reservation,
                        &mut self.entries,
                        capacity,
                        self.limit,
                    )?;
                }
                let mut copy = Vec::new();
                Self::reserve(&mut self.reservation, &mut copy, key.len(), self.limit)?;
                copy.extend_from_slice(key);
                let mut values = Vec::new();
                Self::reserve(
                    &mut self.reservation,
                    &mut values,
                    self.columns.len(),
                    self.limit,
                )?;
                for &column in &self.columns {
                    let field = fields.clone().nth(column).expect("resolved column");
                    bounded(
                        (self.reservation.bytes() as usize)
                            .checked_add(field.len())
                            .is_some_and(|bytes| bytes <= self.limit),
                    )?;
                    values.push(self.reservation.copy_string(field)?);
                    bounded(self.reservation.bytes() as usize <= self.limit)?;
                }
                let mut counts = Vec::new();
                Self::reserve(
                    &mut self.reservation,
                    &mut counts,
                    self.last.counts().len(),
                    self.limit,
                )?;
                counts.resize(self.last.counts().len(), 0);
                let domain = if self.last.exact() {
                    [0; 32]
                } else {
                    let group = group_metadata::ClonedGroup::child(
                        self.parent,
                        &self.first.entry(self.plan.step, first),
                        self.ctx,
                        |lineage| Group {
                            offset: 0,
                            rows: 0,
                            lineage,
                            exact: self.first.exact(),
                        },
                    )?;
                    Membership::scoped_domain(&child_metadata::domain(
                        &group.group,
                        &child_metadata::Entry::all_values(
                            self.plan.step + 1,
                            FieldViews::owned(&values),
                        ),
                        self.plan.seed,
                        self.plan.step + 2,
                        self.ctx,
                    )?)
                };
                self.entries.insert(
                    index,
                    Entry {
                        key: copy,
                        values,
                        counts,
                        seen: 0,
                        first,
                        domain,
                    },
                );
                Ok(index)
            }
        }
    }
    pub fn push(&mut self, mut row: PackedRow) -> Result<Option<PackedRow>> {
        self.ctx.check()?;
        let first = self.first.index(row.id, row.fields());
        let mut key = OperationKey::tuple(
            row.fields(),
            &self.columns,
            16,
            Reservation::new(self.ctx),
            &mut self.sorter,
        )?;
        key.bytes.extend_from_slice(&(first as u64).to_be_bytes());
        key.bytes.rotate_right(8);
        // The composite routing key is larger than either original stage key.
        // A denied owned-row allowance must replay the original pipeline.
        bounded(row.decoded_size(key.bytes.capacity()) <= self.ctx.memory / 4)?;
        let index = self.entry(&key.bytes, first, row.fields())?;
        let entry = &mut self.entries[index];
        let last = self
            .last
            .index_in(&entry.domain, entry.seen, row.id, row.fields());
        entry.seen += 1;
        entry.counts[last] += 1;
        key.bytes.extend_from_slice(&(last as u64).to_be_bytes());
        let capacity = key.install(&mut row, &mut self.sorter)?;
        self.sorter.push_compact_reusing(row, capacity)
    }
    pub fn emit(self, output: &mut impl RowSink) -> Result<[StageStats; 3]> {
        self.first.validate_seen(self.first.seen())?;
        let mut stats = self.plan.stats();
        stats[0].input_groups = 1;
        for &count in self.first.counts() {
            self.ctx.check()?;
            include(&mut stats[0], count);
        }
        ensure!(
            stats[0].output_groups <= self.ctx.max_files,
            "logical group count exceeds max_files"
        );
        stats[1].input_groups = stats[0].output_groups;
        let mut rows = self.sorter.finish()?.reusing();
        for entry in &self.entries {
            self.ctx.check()?;
            self.last.validate_seen(entry.seen)?;
            let first = group_metadata::ClonedGroup::child(
                self.parent,
                &self.first.entry(self.plan.step, entry.first),
                self.ctx,
                |lineage| Group {
                    offset: 0,
                    rows: self.first.counts()[entry.first],
                    lineage,
                    exact: self.first.exact(),
                },
            )?;
            let partition = group_metadata::ClonedGroup::child(
                &first.group,
                &child_metadata::Entry::all_values(
                    self.plan.step + 1,
                    FieldViews::owned(&entry.values),
                ),
                self.ctx,
                |lineage| Group {
                    offset: 0,
                    rows: entry.seen,
                    lineage,
                    exact: false,
                },
            )?;
            include(&mut stats[1], entry.seen);
            ensure!(
                stats[1].output_groups <= self.ctx.max_files,
                "logical group count exceeds max_files"
            );
            stats[2].input_groups += 1;
            for (last, count) in entry.counts.iter().enumerate() {
                self.ctx.check()?;
                let mut owned = group_metadata::ClonedGroup::begin_child(
                    &partition.group,
                    &self.last.entry(self.plan.step + 2, last),
                    self.last.exact(),
                    output,
                    self.ctx,
                )?;
                for _ in 0..*count {
                    self.ctx.check()?;
                    let row = rows.next()?.context("truncated routing chain")?;
                    let key = row.key.as_ref();
                    ensure!(
                        key.len() == entry.key.len() + 8
                            && key.starts_with(&entry.key)
                            && key[key.len() - 8..] == (last as u64).to_be_bytes(),
                        "routing chain counter/key mismatch"
                    );
                    row.key = PackedKey::Bytes(Box::default());
                    output.packed_row_ref(&mut owned.group, row)?;
                }
                self.ctx.check()?;
                owned.finish(output)?;
                include(&mut stats[2], *count);
                ensure!(
                    stats[2].output_groups <= self.ctx.max_files,
                    "logical group count exceeds max_files"
                );
            }
        }
        ensure!(rows.next()?.is_none(), "unexpected routing chain row");
        finish(&mut stats);
        Ok(stats)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{atomic::Ordering, Mutex};
    fn probability() -> Operation {
        Operation::AssignProbabilistic {
            groups: vec![
                Allocation {
                    name: "keep / 界".into(),
                    percent: "60".into(),
                },
                Allocation {
                    name: "other".into(),
                    percent: "40".into(),
                },
                Allocation {
                    name: "empty".into(),
                    percent: "0".into(),
                },
            ],
            strata: vec![Column::Index(2), Column::Index(0)],
        }
    }
    fn job(first: bool, last: bool) -> Job {
        Job {
            random_seed: Some("streaming-chain-v1".into()),
            operations: vec![
                if first {
                    probability()
                } else {
                    Operation::Interleaved { files: 2 }
                },
                Operation::Partition {
                    columns: vec![Column::Name("key".into()), Column::Index(1)],
                },
                if last {
                    probability()
                } else {
                    Operation::Interleaved { files: 3 }
                },
            ],
            resources: Resources {
                memory_mb: 32.into(),
                max_record_bytes: 2 * 1024 * 1024,
                workers: 1,
                grouping: Grouping::Sort,
                ..Default::default()
            },
            ..Default::default()
        }
    }
    fn context(job: &Job) -> Result<Context> {
        Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )
    }
    fn text(count: usize) -> Result<Vec<u8>> {
        let mut bytes = b"id,key,text\n".to_vec();
        let mut serializer = chopper_core::csv::Serializer::new(&CsvSettings::default())?;
        for id in 0..count {
            bytes.extend_from_slice(serializer.serialize_fields([
                id.to_string().as_str(),
                ["", "a\0界", "a\"q"][id % 3],
                "quoted,\"q\"\ntext",
            ])?);
        }
        Ok(bytes)
    }
    fn raw(input: &[u8], job: &Job, ctx: &Context) -> Result<Ingested> {
        let mut plain = job.clone();
        plain.operations = vec![Operation::Balanced { files: 1 }];
        ingest(Box::new(input), &plain, ctx)
    }
    fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
        let mut result = Vec::new();
        for group in data.groups()? {
            let group = group?;
            let rows = data
                .rows(&group, ctx.max_record)?
                .map(|r| r.map(|r| json!([r.id, r.ordinal, r.key, r.fields])))
                .collect::<Result<Vec<_>>>()?;
            result.push(json!([group.lineage, group.exact, rows]));
        }
        Ok(json!(result))
    }
    fn serial(source: &Ingested, job: &Job, ctx: &Context) -> Result<(Dataset, Vec<StageStats>)> {
        let mut data = apply(
            &source.dataset,
            &job.operations[0],
            0,
            job,
            &source.analysis,
            ctx,
        )?;
        let mut stats = vec![dataset_stats(&data, 1, source.dataset.groups, ctx)?];
        for index in 1..3 {
            let before = data.groups;
            data = apply(
                &data,
                &job.operations[index],
                index,
                job,
                &source.analysis,
                ctx,
            )?;
            stats.push(dataset_stats(&data, index + 1, before, ctx)?);
        }
        Ok((data, stats))
    }
    #[test]
    fn selector_keeps_scopes_and_excludes_count_dependent_or_nonadjacent_chains() {
        for first in [false, true] {
            for last in [false, true] {
                let job = job(first, last);
                assert!(Plan::at(&job, 0).is_some());
                assert!(Plan::at(&job, 1).is_none());
                for barrier in [
                    Operation::Balanced { files: 2 },
                    Operation::Assign {
                        groups: vec![],
                        strata: vec![],
                    },
                    Operation::Shuffle {
                        strategy: Shuffle::Uniform,
                    },
                ] {
                    let mut bad = job.clone();
                    bad.operations[0] = barrier.clone();
                    assert!(Plan::at(&bad, 0).is_none());
                    let mut bad = job.clone();
                    bad.operations[2] = barrier;
                    assert!(Plan::at(&bad, 0).is_none());
                }
            }
        }
    }
    #[test]
    fn all_membership_pairs_preserve_parent_counters_domains_stats_and_external_order() -> Result<()>
    {
        for first in [false, true] {
            for last in [false, true] {
                for budget in [4096, 32 * 1024 * 1024] {
                    let job = job(first, last);
                    let mut ctx = context(&job)?;
                    let input = text(333)?;
                    let source = raw(&input, &job, &ctx)?;
                    ctx.memory = budget;
                    let (expected, expected_stats) = serial(&source, &job, &ctx)?;
                    let parent = source.dataset.groups()?.next().unwrap()?;
                    let mut state = State::new(
                        Plan::at(&job, 0).unwrap(),
                        &parent,
                        source.analysis.header.as_deref(),
                        source.analysis.columns,
                        &ctx,
                    )?;
                    // Force tiny sort runs while keeping the production catalog allowance.
                    state.limit = 1024 * 1024;
                    let mut previous = None;
                    let mut rows = source.dataset.rows(&parent, ctx.max_record)?;
                    while let Some(row) = rows.next_packed(previous.take())? {
                        previous = state.push(row)?;
                    }
                    drop(rows);
                    drop(previous);
                    let mut writer = DatasetWriter::new(&ctx)?;
                    let stats = state.emit(&mut writer)?;
                    let actual = writer.finish()?;
                    assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
                    assert_eq!(
                        serde_json::to_value(stats)?,
                        serde_json::to_value(expected_stats)?
                    );
                    let shuffle = Operation::Shuffle {
                        strategy: Shuffle::Uniform,
                    };
                    let a = apply(&actual, &shuffle, 3, &job, &source.analysis, &ctx)?;
                    let b = apply(&expected, &shuffle, 3, &job, &source.analysis, &ctx)?;
                    assert_eq!(snapshot(&a, &ctx)?, snapshot(&b, &ctx)?);
                    if budget == 4096 {
                        assert!(ctx.diagnostics()["merge_operations"].as_u64().unwrap() > 2);
                    }
                }
            }
        }
        Ok(())
    }
    #[test]
    fn catalog_exact_capacity_growth_overlap_and_shared_denial_release() -> Result<()> {
        let job = job(true, true);
        let ctx = context(&job)?;
        let parent = Group {
            offset: 0,
            rows: 0,
            lineage: vec![],
            exact: false,
        };
        let header = vec!["id".into(), "key".into(), "text".into()];
        for count in [1, 9] {
            let build = |limit: usize| -> Result<(Result<()>, State<'_, '_>, Arc<Workspace>)> {
                let mut state =
                    State::new(Plan::at(&job, 0).unwrap(), &parent, Some(&header), 3, &ctx)?;
                let workspace = Arc::new(Workspace::new(limit));
                let mut reservation = Reservation::for_workspace(workspace.clone());
                reservation.resize(state.reservation.bytes() as usize)?;
                state.reservation = reservation;
                let result = (|| -> Result<()> {
                    for i in 0..count {
                        let fields = vec![i.to_string(), format!("key-{i}"), "text".into()];
                        let mut key = 0u64.to_be_bytes().to_vec();
                        key.extend(random::tuple_key(&fields, &[1, 1]));
                        state.entry(&key, 0, FieldViews::owned(&fields))?;
                    }
                    Ok(())
                })();
                Ok((result, state, workspace))
            };
            let (result, state, workspace) = build(1024 * 1024)?;
            result?;
            let peak = workspace.peak() as usize;
            if count == 9 {
                assert!(
                    workspace.used() < peak as u64,
                    "growth must retain both arrays"
                );
            }
            drop(state);
            assert_eq!(workspace.used(), 0);
            for limit in [peak - 1, peak, peak + 1] {
                let (result, state, workspace) = build(limit)?;
                assert_eq!(result.is_ok(), limit >= peak);
                if let Err(error) = result {
                    assert!(retry(&error));
                }
                drop(state);
                assert_eq!(workspace.used(), 0);
            }
        }
        let pool = Arc::new(crate::resources::MemoryPool::new(1024 * 1024));
        let shared = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let mut state = State::new(
            Plan::at(&job, 0).unwrap(),
            &parent,
            Some(&header),
            3,
            &shared,
        )?;
        let held = pool.usage().limit_bytes - pool.usage().reserved_bytes;
        pool.acquire(held)?;
        let fields = vec!["id".into(), "key".into(), "text".into()];
        assert!(retry(
            &state
                .entry(b"key", 0, FieldViews::owned(&fields))
                .err()
                .unwrap()
        ));
        pool.release(held);
        drop(state);
        assert_eq!(
            pool.usage().reserved_bytes,
            shared.directory_reserved_bytes()
        );
        drop(shared);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
    #[test]
    fn composite_key_allowance_denial_replays_rows_that_fit_the_original_keys() -> Result<()> {
        let mut job = job(false, false);
        job.operations[0] = Operation::Interleaved { files: 1 };
        job.operations[2] = Operation::Interleaved { files: 1 };
        let mut ctx = context(&job)?;
        let mut header = vec!["id".to_string(), "key".into(), "text".into()];
        header.extend((3..166).map(|i| format!("field{i}")));
        let mut fields = vec![String::new(); 166];
        fields[165] = "12345678".into();
        let mut serializer = chopper_core::csv::Serializer::new(&CsvSettings::default())?;
        let mut input = serializer.serialize(&header)?.to_vec();
        input.extend_from_slice(serializer.serialize(&fields)?);
        let source = raw(&input, &job, &ctx)?;
        // Keep the decoded allowance exact while admitting current inline sorter metadata.
        ctx.memory = 16 * 1024;
        let parent = source.dataset.groups()?.next().unwrap()?;
        let row = source
            .dataset
            .packed_rows(&parent, ctx.max_record)?
            .next()
            .unwrap()?;
        assert_eq!(row.decoded_size(8), ctx.memory / 4);
        let mut state = State::new(
            Plan::at(&job, 0).unwrap(),
            &parent,
            source.analysis.header.as_deref(),
            166,
            &ctx,
        )?;
        state.limit = 1024 * 1024;
        let error = state.push(row).err().unwrap();
        assert!(error.downcast_ref::<CounterLimit>().is_some());
        drop(state);
        let (original, _) = serial(&source, &job, &ctx)?;
        assert_eq!(original.groups, 1);
        assert_eq!(original.groups()?.next().unwrap()?.rows, 1);
        Ok(())
    }

    #[test]
    fn bounded_fanout_retries_only_unemitted_parent() -> Result<()> {
        struct SeenSink {
            writer: DatasetWriter,
            groups: u64,
        }
        impl RowSink for SeenSink {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                self.writer.begin(lineage, exact)
            }
            fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
                self.writer.row(group, row)
            }
            fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
                self.writer.packed_row_ref(group, row)
            }
            fn end(&mut self, group: Group) -> Result<()> {
                self.writer.end(group)?;
                self.groups += 1;
                Ok(())
            }
        }
        let mut job = job(false, true);
        job.operations[0] = Operation::Interleaved { files: 1 };
        let input = format!(
            "id,key,text\n{}",
            (0..600)
                .map(|i| format!(
                    "{i},{},text\n",
                    if i < 300 {
                        "common".into()
                    } else {
                        i.to_string()
                    }
                ))
                .collect::<String>()
        );
        let ctx = context(&job)?;
        let source = raw(input.as_bytes(), &job, &ctx)?;
        let parents = apply(
            &source.dataset,
            &Operation::Balanced { files: 2 },
            0,
            &job,
            &source.analysis,
            &ctx,
        )?;
        let before = ctx.used();
        {
            let mut writer = SeenSink {
                writer: DatasetWriter::new(&ctx)?,
                groups: 0,
            };
            let stats = Plan::at(&job, 0).unwrap().apply(
                &parents,
                &job,
                &source.analysis,
                &ctx,
                &mut writer,
            )?;
            assert!(writer.groups > 0);
            let actual = writer.writer.finish()?;
            let mut expected = apply(
                &parents,
                &job.operations[0],
                0,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let mut expected_stats = vec![dataset_stats(&expected, 1, parents.groups, &ctx)?];
            for index in 1..3 {
                let before = expected.groups;
                expected = apply(
                    &expected,
                    &job.operations[index],
                    index,
                    &job,
                    &source.analysis,
                    &ctx,
                )?;
                expected_stats.push(dataset_stats(&expected, index + 1, before, &ctx)?);
            }
            assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
            assert_eq!(
                serde_json::to_value(stats)?,
                serde_json::to_value(expected_stats)?
            );
            assert_eq!(ctx.diagnostics()["streaming_chain_retries"], 1);
        }
        assert_eq!(ctx.used(), before);
        let parent = source.dataset.groups()?.next().unwrap()?;
        let mut state = State::new(
            Plan::at(&job, 0).unwrap(),
            &parent,
            source.analysis.header.as_deref(),
            3,
            &ctx,
        )?;
        state.limit = 1;
        let row = source
            .dataset
            .packed_rows(&parent, ctx.max_record)?
            .next()
            .unwrap()?;
        assert!(state
            .push(row)
            .err()
            .unwrap()
            .downcast_ref::<CounterLimit>()
            .is_some());
        Ok(())
    }
    #[test]
    fn injected_csv_and_dataset_admission_retry_preserves_prepared_snapshot() -> Result<()> {
        for initial in [true, false] {
            let dir = tempfile::tempdir()?;
            let input = dir.path().join("input.csv");
            std::fs::write(&input, text(333)?)?;
            let mut job = job(true, true);
            job.input = input.to_string_lossy().into();
            if !initial {
                job.operations.insert(0, Operation::Balanced { files: 2 });
            }
            let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
            let injected = Arc::new(AtomicBool::new(false));
            let blocker = Arc::new(Mutex::new(0u64));
            let notify = {
                let pool = pool.clone();
                let injected = injected.clone();
                let blocker = blocker.clone();
                Arc::new(move |progress: Progress| {
                    let trigger = if initial {
                        "Reading and validating CSV"
                    } else {
                        "Preparing streaming routing chain"
                    };
                    if progress.phase == trigger && !injected.swap(true, Ordering::Relaxed) {
                        let bytes = pool.usage().limit_bytes - pool.usage().reserved_bytes;
                        pool.acquire(bytes).unwrap();
                        *blocker.lock().unwrap() = bytes;
                    } else if matches!(
                        progress.phase.as_str(),
                        "Retrying routing chain without fusion"
                            | "Retrying retained routing parent without fusion"
                    ) {
                        pool.release(std::mem::take(&mut *blocker.lock().unwrap()));
                    }
                })
            };
            let actual = prepare_with_memory_pool(
                job.clone(),
                Arc::new(AtomicBool::new(false)),
                notify,
                pool.clone(),
            )?;
            let expected = prepare_with_memory_pool(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
            )?;
            assert!(injected.load(Ordering::Relaxed));
            assert_eq!(actual.analysis.diagnostics["streaming_chain_retries"], 1);
            assert_eq!(
                serde_json::to_value(&actual.analysis.stages)?,
                serde_json::to_value(&expected.analysis.stages)?
            );
            let mut a = Vec::new();
            let mut b = Vec::new();
            actual.output_plan.data.reader()?.read_to_end(&mut a)?;
            expected.output_plan.data.reader()?.read_to_end(&mut b)?;
            assert_eq!(a, b);
            assert_eq!(actual.analysis.output_files, expected.analysis.output_files);
            drop(actual);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }
    #[test]
    fn empty_allocations_ingestion_and_nonempty_failures_match_serial_stages() -> Result<()> {
        for count in [0, 333] {
            let job = job(true, true);
            let ctx = context(&job)?;
            let input = text(count)?;
            let source = raw(&input, &job, &ctx)?;
            let (expected, stats) = serial(&source, &job, &ctx)?;
            let expected = output::plan(&expected, &job, source.analysis.header.as_deref(), &ctx)?;
            let actual = ingest_options(&mut input.as_slice(), &job, &ctx, false, false, true)?;
            assert_eq!(actual.consumed, 3);
            assert_eq!(
                serde_json::to_value(actual.analysis.stages)?,
                serde_json::to_value(stats)?
            );
            let actual = actual.final_plan.unwrap();
            let mut a = Vec::new();
            let mut b = Vec::new();
            actual.data.reader()?.read_to_end(&mut a)?;
            expected.data.reader()?.read_to_end(&mut b)?;
            assert_eq!(a, b);
            assert_eq!(actual.files, expected.files);
        }
        let job = job(false, false);
        let ctx = context(&job)?;
        let input = text(0)?;
        let error = ingest_options(&mut input.as_slice(), &job, &ctx, false, false, true)
            .err()
            .unwrap();
        assert!(!retry(&error));
        assert!(error.to_string().contains("nonempty"));
        Ok(())
    }
    #[test]
    fn cancellation_after_actual_child_output_releases_every_tentative_grant() -> Result<()> {
        struct StopSink {
            writer: DatasetWriter,
            cancel: Arc<AtomicBool>,
            rows: u64,
        }
        impl RowSink for StopSink {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                self.writer.begin(lineage, exact)
            }
            fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
                self.writer.row(group, row)
            }
            fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
                self.rows += 1;
                self.writer.packed_row_ref(group, row)
            }
            fn end(&mut self, group: Group) -> Result<()> {
                self.writer.end(group)?;
                self.cancel.store(true, Ordering::Relaxed);
                Ok(())
            }
        }
        let job = job(false, false);
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::with_memory_pool(
            &job.resources,
            cancel.clone(),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let input = text(333)?;
        let source = raw(&input, &job, &ctx)?;
        let before = ctx.used();
        let reserved = pool.usage().reserved_bytes;
        let mut sink = StopSink {
            writer: DatasetWriter::new(&ctx)?,
            cancel,
            rows: 0,
        };
        let error = Plan::at(&job, 0)
            .unwrap()
            .apply(&source.dataset, &job, &source.analysis, &ctx, &mut sink)
            .err()
            .unwrap();
        assert!(error.to_string().contains("cancelled"));
        assert!(!retry(&error));
        assert!(sink.rows > 0);
        drop(sink);
        assert_eq!(ctx.used(), before);
        assert_eq!(pool.usage().reserved_bytes, reserved);
        Ok(())
    }
}
