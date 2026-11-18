//! Count a bounded tuple catalog while sorting, then emit balanced children directly.
use super::*;

pub(super) fn admission(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<crate::resources::MemoryAdmission>()
        .is_some()
}

pub(super) struct Counts {
    entries: Vec<(Vec<u8>, u64)>,
    reservation: Reservation,
    limit: usize,
}
impl Counts {
    pub fn new(ctx: &Context) -> Self {
        Self {
            entries: Vec::new(),
            reservation: Reservation::new(ctx),
            limit: ctx.memory / 64,
        }
    }
    fn add(&mut self, key: &[u8]) -> Result<()> {
        match self
            .entries
            .binary_search_by(|(stored, _)| stored.as_slice().cmp(key))
        {
            Ok(index) => self.entries[index].1 += 1,
            Err(index) => {
                // High fanout uses the original pipeline. Never retain an unbounded catalog.
                ensure!(self.entries.len() < 256, "partition count fanout limit");
                let growth = (self.entries.capacity().max(4) * 2).min(256);
                ensure!(
                    self.reservation.bytes() as usize
                        + key.len()
                        + growth * std::mem::size_of::<(Vec<u8>, u64)>()
                        <= self.limit,
                    "partition count capacity limit"
                );
                if self.entries.len() == self.entries.capacity() {
                    self.reservation.reserve_vec(&mut self.entries, growth)?;
                }
                let mut copy = Vec::new();
                self.reservation.reserve_vec(&mut copy, key.len())?;
                copy.extend_from_slice(key);
                self.entries.insert(index, (copy, 1));
            }
        }
        Ok(())
    }
}
pub(super) fn observe(counts: &mut Option<Counts>, key: &[u8]) {
    if counts
        .as_mut()
        .is_some_and(|counts| counts.add(key).is_err())
    {
        // Optional admission failure releases all tentative capacity immediately.
        *counts = None;
    }
}

#[derive(Clone, Copy)]
pub(super) struct Plan<'a> {
    columns: &'a [Column],
    step: usize,
    shuffle_step: usize,
    files: u64,
}
impl<'a> Plan<'a> {
    pub fn at(job: &'a Job, step: usize) -> Option<Self> {
        let Operation::Partition { columns } = job.operations.get(step)? else {
            return None;
        };
        let shuffles = job.operations[step + 1..]
            .iter()
            .take_while(|op| uniform(op))
            .count();
        if shuffles == 0 {
            return None;
        }
        let Operation::Balanced { files } = job.operations.get(step + shuffles + 1)? else {
            return None;
        };
        Some(Self {
            columns,
            step,
            shuffle_step: step + shuffles,
            files: *files,
        })
    }
    pub fn len(self) -> usize {
        self.shuffle_step - self.step + 2
    }
    pub fn stats(self) -> Stats {
        let new = |operation| StageStats {
            operation,
            input_groups: 0,
            output_groups: 0,
            smallest_group: u64::MAX,
            largest_group: 0,
            empty_groups: 0,
        };
        Stats {
            partition: new(self.step + 1),
            balanced: new(self.shuffle_step + 2),
        }
    }
    pub fn apply(
        self,
        data: &Dataset,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<Option<Stats>> {
        let mut selected = Reservation::new(ctx);
        let mut columns = Vec::new();
        selected.reserve_vec(&mut columns, self.columns.len())?;
        for column in self.columns {
            columns.push(resolve_column(
                column,
                analysis.header.as_deref(),
                analysis.columns,
            )?);
        }
        let mut stats = self.stats();
        let mut total_rows = 0;
        for parent in data.groups()? {
            let parent = parent?;
            total_rows += parent.rows;
            let mut sorter = Sorter::new(ctx, SortOrder::GroupRandom);
            let mut counts = Some(Counts::new(ctx));
            let mut keys = PartitionKeys {
                parent: &parent,
                columns: std::mem::take(&mut columns),
                step: self.step,
                #[cfg(feature = "experimental-constant-partition")]
                key_columns: None,
                shuffle: Some(PartitionRandom::After {
                    seed: job.random_seed.as_deref().unwrap(),
                    step: self.shuffle_step,
                }),
                domains: DomainCache::new(ctx),
            };
            for row in data.packed_rows(&parent, ctx.max_record)? {
                ctx.check()?;
                let mut row = row?;
                let key = keys.key(row.id, row.fields(), ctx, &mut sorter)?;
                observe(&mut counts, &key.bytes[..key.bytes.len() - 48]);
                if counts.is_none() {
                    return Ok(None);
                }
                let capacity = key.install(&mut row, &mut sorter)?;
                sorter.push_compact(row, capacity)?;
            }
            columns = std::mem::take(&mut keys.columns);
            drop(keys);
            self.emit(
                sorter.finish()?,
                &parent,
                &columns,
                &counts.unwrap(),
                &mut stats,
                output,
                ctx,
            )?;
        }
        ctx.partition_balanced_fused(total_rows);
        Ok(Some(stats))
    }
    #[allow(clippy::too_many_arguments)]
    pub fn emit(
        self,
        rows: SortedRows,
        parent: &Group,
        columns: &[usize],
        counts: &Counts,
        stats: &mut Stats,
        output: &mut impl RowSink,
        ctx: &Context,
    ) -> Result<()> {
        stats.partition.input_groups += 1;
        let mut rows = rows.reusing();
        for (key, count) in &counts.entries {
            ctx.check()?;
            ensure!(
                *count >= self.files,
                "cannot split {count} rows into {} nonempty balanced groups",
                self.files
            );
            let mut partition = None;
            let mut ordinal = 0;
            for part in 0..self.files {
                let n = count / self.files + u64::from(part < count % self.files);
                let mut group = None;
                for _ in 0..n {
                    ctx.check()?;
                    let row = rows.next()?.context("missing partition/balanced row")?;
                    let stored = row.key.as_ref();
                    ensure!(
                        stored.len() >= 48 && &stored[..stored.len() - 48] == key,
                        "partition count/key mismatch"
                    );
                    if partition.is_none() {
                        partition = Some(group_metadata::ClonedGroup::child(
                            parent,
                            &child_metadata::Entry::values(self.step, row.fields(), columns),
                            ctx,
                            |lineage| Group {
                                offset: 0,
                                rows: *count,
                                lineage,
                                exact: false,
                            },
                        )?);
                    }
                    if group.is_none() {
                        group = Some(group_metadata::ClonedGroup::begin_child(
                            &partition.as_ref().unwrap().group,
                            &child_metadata::Entry::part(self.shuffle_step + 1, part + 1),
                            true,
                            output,
                            ctx,
                        )?);
                    }
                    row.ordinal = ordinal;
                    row.key = PackedKey::Bytes(Box::default());
                    output.packed_row_ref(&mut group.as_mut().unwrap().group, row)?;
                    ordinal += 1;
                }
                ctx.check()?;
                group.unwrap().finish(output)?;
                stats.balanced.output_groups += 1;
                stats.balanced.smallest_group = stats.balanced.smallest_group.min(n);
                stats.balanced.largest_group = stats.balanced.largest_group.max(n);
            }
            stats.partition.output_groups += 1;
            stats.partition.smallest_group = stats.partition.smallest_group.min(*count);
            stats.partition.largest_group = stats.partition.largest_group.max(*count);
            stats.balanced.input_groups += 1;
            ensure!(
                stats.partition.output_groups <= ctx.max_files,
                "logical group count exceeds max_files"
            );
        }
        ensure!(rows.next()?.is_none(), "unexpected partition/balanced row");
        Ok(())
    }
}
pub(super) struct Stats {
    partition: StageStats,
    pub balanced: StageStats,
}
impl Stats {
    pub fn append(mut self, plan: Plan<'_>, stages: &mut Stages) -> Result<()> {
        if self.partition.output_groups == 0 {
            self.partition.smallest_group = 0;
        }
        if self.balanced.output_groups == 0 {
            self.balanced.smallest_group = 0;
        }
        stages.push(self.partition.clone())?;
        for operation in plan.step + 2..=plan.shuffle_step + 1 {
            let mut stats = self.partition.clone();
            stats.operation = operation;
            stats.input_groups = stats.output_groups;
            stages.push(stats)?;
        }
        stages.push(self.balanced)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn shuffle() -> Operation {
        Operation::Shuffle {
            strategy: Shuffle::Uniform,
        }
    }
    fn job() -> Job {
        Job {
            random_seed: Some("partition-balanced-v1".into()),
            operations: vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                shuffle(),
                shuffle(),
                Operation::Balanced { files: 3 },
            ],
            ..Default::default()
        }
    }
    fn context(job: &Job) -> Result<Context> {
        Context::new(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )
    }
    fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
        let mut result = Vec::new();
        for group in data.groups()? {
            let group = group?;
            let rows = data
                .rows(&group, ctx.max_record)?
                .map(|r| r.map(|r| json!([r.id, r.ordinal, r.fields])))
                .collect::<Result<Vec<_>>>()?;
            result.push(json!([group.lineage, group.exact, rows]));
        }
        Ok(json!(result))
    }
    #[test]
    fn selector_preserves_indices_and_rejects_algorithm_and_operation_barriers() {
        let mut job = job();
        let plan = Plan::at(&job, 0).unwrap();
        assert_eq!((plan.len(), plan.shuffle_step), (4, 2));
        for operation in [
            Operation::Interleaved { files: 2 },
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
            },
        ] {
            job.operations[1] = operation;
            assert!(Plan::at(&job, 0).is_none());
        }
    }
    #[test]
    fn bounded_counts_release_on_fanout_capacity_and_shared_denial() -> Result<()> {
        let job = job();
        let ctx = context(&job)?;
        let mut counts = Some(Counts::new(&ctx));
        for i in 0u64..256 {
            observe(&mut counts, &i.to_be_bytes());
        }
        assert_eq!(counts.as_ref().unwrap().entries.len(), 256);
        observe(&mut counts, &0u64.to_be_bytes());
        assert_eq!(counts.as_ref().unwrap().entries[0].1, 2);
        observe(&mut counts, &256u64.to_be_bytes());
        assert!(counts.is_none());
        let mut tiny = Counts::new(&ctx);
        tiny.limit = 1;
        let mut counts = Some(tiny);
        observe(&mut counts, b"key");
        assert!(counts.is_none());
        let pool = Arc::new(crate::resources::MemoryPool::new(
            ctx.directory_reserved_bytes() + 1,
        ));
        let shared = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool,
        )?;
        let mut counts = Some(Counts::new(&shared));
        observe(&mut counts, b"key");
        assert!(counts.is_none());
        Ok(())
    }
    #[test]
    fn fusion_preserves_rounding_stats_parent_domains_and_ingestion() -> Result<()> {
        let job = job();
        let ctx = context(&job)?;
        let input = format!(
            "id,key,text\n{}",
            (0..121)
                .map(|i| format!("{i},{},\"界,\"\"q\"\"\ntext\"\n", i % 3))
                .collect::<String>()
        );
        let mut plain = job.clone();
        plain.operations = vec![Operation::Balanced { files: 1 }];
        let source = ingest(Box::new(input.as_bytes()), &plain, &ctx)?;
        let mut serial = apply(
            &source.dataset,
            &job.operations[0],
            0,
            &job,
            &source.analysis,
            &ctx,
        )?;
        let mut expected = vec![dataset_stats(&serial, 1, 1, &ctx)?];
        // Consecutive uniform elimination uses the last original index.
        expected.push(dataset_stats(&serial, 2, serial.groups, &ctx)?);
        serial = apply(&serial, &job.operations[2], 2, &job, &source.analysis, &ctx)?;
        expected.push(dataset_stats(&serial, 3, serial.groups, &ctx)?);
        let before = serial.groups;
        serial = apply(&serial, &job.operations[3], 3, &job, &source.analysis, &ctx)?;
        expected.push(dataset_stats(&serial, 4, before, &ctx)?);
        let plan = Plan::at(&job, 0).unwrap();
        let mut writer = DatasetWriter::new(&ctx)?;
        let stats = plan
            .apply(&source.dataset, &job, &source.analysis, &ctx, &mut writer)?
            .unwrap();
        let fused = writer.finish()?;
        assert_eq!(snapshot(&fused, &ctx)?, snapshot(&serial, &ctx)?);
        let mut stages = Stages::new(job.operations.len(), Reservation::new(&ctx))?;
        stats.append(plan, &mut stages)?;
        assert_eq!(
            serde_json::to_value(&stages)?,
            serde_json::to_value(expected)?
        );
        let ingested = ingest_options(&mut input.as_bytes(), &job, &ctx, false, true, false)?;
        assert_eq!(ingested.consumed, 4);
        assert_eq!(
            serde_json::to_value(ingested.analysis.stages)?,
            serde_json::to_value(stages)?
        );
        for op in [shuffle(), Operation::Interleaved { files: 2 }] {
            let a = apply(&serial, &op, 4, &job, &source.analysis, &ctx)?;
            let b = apply(&fused, &op, 4, &job, &source.analysis, &ctx)?;
            assert_eq!(snapshot(&a, &ctx)?, snapshot(&b, &ctx)?);
        }
        Ok(())
    }
    #[test]
    fn typed_pressure_retries_csv_and_later_dataset_with_all_grants_released() -> Result<()> {
        use std::sync::{atomic::Ordering, Mutex};
        for initial in [true, false] {
            let dir = tempfile::tempdir()?;
            let input = dir.path().join("input.csv");
            std::fs::write(
                &input,
                format!(
                    "id,key\n{}",
                    (0..121)
                        .map(|i| format!("{i},{}\n", i % 3))
                        .collect::<String>()
                ),
            )?;
            let mut job = job();
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
                        "Preparing partition/shuffle balanced ranges"
                    };
                    if progress.phase == trigger && !injected.swap(true, Ordering::Relaxed) {
                        let bytes = pool.usage().limit_bytes - pool.usage().reserved_bytes;
                        pool.acquire(bytes).unwrap();
                        *blocker.lock().unwrap() = bytes;
                    } else if progress.phase == "Retrying partition/shuffle without balanced fusion"
                    {
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
            assert!(injected.load(Ordering::Relaxed));
            assert_eq!(actual.analysis.diagnostics["partition_balanced_retries"], 1);
            let expected = prepare_with_memory_pool(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
            )?;
            assert_eq!(
                serde_json::to_value(&actual.analysis.stages)?,
                serde_json::to_value(&expected.analysis.stages)?
            );
            let mut a = Vec::new();
            let mut b = Vec::new();
            actual.output_plan.data.reader()?.read_to_end(&mut a)?;
            expected.output_plan.data.reader()?.read_to_end(&mut b)?;
            assert_eq!(a, b);
            drop(actual);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn cancellation_after_emitting_a_child_releases_partial_output_and_counts() -> Result<()> {
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
                self.cancel
                    .store(true, std::sync::atomic::Ordering::Relaxed);
                Ok(())
            }
        }
        let job = job();
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::with_memory_pool(
            &job.resources,
            cancel.clone(),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let text = format!(
            "id,key\n{}",
            (0..121)
                .map(|i| format!("{i},{}\n", i % 3))
                .collect::<String>()
        );
        let mut plain = job.clone();
        plain.operations = vec![Operation::Balanced { files: 1 }];
        let source = ingest(Box::new(text.as_bytes()), &plain, &ctx)?;
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
        assert!(sink.rows > 0);
        drop(sink);
        assert_eq!(ctx.used(), before);
        assert_eq!(pool.usage().reserved_bytes, reserved);
        Ok(())
    }

    #[test]
    fn equal_random_keys_preserve_collision_refinement_through_hierarchical_merges() -> Result<()> {
        for budget in [4096, 32 * 1024 * 1024] {
            let job = job();
            let mut ctx = context(&job)?;
            ctx.memory = budget;
            let plan = Plan::at(&job, 0).unwrap();
            let parent = Group {
                offset: 0,
                rows: 333,
                lineage: vec![json!({"operation":0,"part":2})],
                exact: false,
            };
            let mut fused = Sorter::new(&ctx, SortOrder::GroupRandom);
            let mut reference = Sorter::new(&ctx, SortOrder::GroupRandom);
            let mut counts = Counts::new(&ctx);
            counts.limit = 1024 * 1024;
            let mut keys = PartitionKeys {
                parent: &parent,
                columns: vec![1],
                step: 0,
                #[cfg(feature = "experimental-constant-partition")]
                key_columns: None,
                shuffle: Some(PartitionRandom::After {
                    seed: job.random_seed.as_deref().unwrap(),
                    step: 2,
                }),
                domains: DomainCache::new(&ctx),
            };
            for id in (0..333).rev() {
                let fields = vec![
                    id.to_string(),
                    format!("key-{}\0界", id % 7),
                    "duplicate".into(),
                ];
                let mut row = PackedRow::new(Row {
                    id,
                    ordinal: 1000 - id,
                    key: vec![],
                    fields: fields.clone(),
                })?;
                let mut key = keys.key(id, row.fields(), &ctx, &mut fused)?;
                let end = key.bytes.len() - 32;
                key.bytes[end - 16..end].fill(0);
                counts.add(&key.bytes[..key.bytes.len() - 48])?;
                reference.push(Row {
                    id,
                    ordinal: 1000 - id,
                    key: key.bytes.clone(),
                    fields,
                })?;
                let capacity = key.install(&mut row, &mut fused)?;
                fused.push_compact(row, capacity)?;
            }
            drop(keys);
            let mut writer = DatasetWriter::new(&ctx)?;
            emit_partition(
                reference.finish()?,
                &parent,
                &[1],
                0,
                true,
                &mut writer,
                &ctx,
            )?;
            let partitioned = writer.finish()?;
            let mut plain = job.clone();
            plain.operations = vec![Operation::Balanced { files: 1 }];
            let source = ingest(Box::new("id,key,text\n".as_bytes()), &plain, &ctx)?;
            let serial = apply(
                &partitioned,
                &Operation::Balanced { files: 3 },
                3,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let mut writer = DatasetWriter::new(&ctx)?;
            plan.emit(
                fused.finish()?,
                &parent,
                &[1],
                &counts,
                &mut plan.stats(),
                &mut writer,
                &ctx,
            )?;
            assert_eq!(snapshot(&writer.finish()?, &ctx)?, snapshot(&serial, &ctx)?);
            if budget == 4096 {
                assert!(ctx.diagnostics()["merge_operations"].as_u64().unwrap() > 2);
            }
        }
        Ok(())
    }

    #[test]
    fn denial_after_a_successful_parent_and_insufficient_rows_drop_tentative_output() -> Result<()>
    {
        let mut job = job();
        job.operations[0] = Operation::Partition {
            columns: vec![Column::Index(0)],
        };
        let ctx = context(&job)?;
        let input = format!(
            "id,key\n{}",
            (0..600)
                .map(|i| format!("{},x\n", if i < 300 { 0 } else { i }))
                .collect::<String>()
        );
        let mut plain = job.clone();
        plain.operations = vec![Operation::Balanced { files: 1 }];
        let source = ingest(Box::new(input.as_bytes()), &plain, &ctx)?;
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
            let mut writer = DatasetWriter::new(&ctx)?;
            assert!(Plan::at(&job, 0)
                .unwrap()
                .apply(&parents, &job, &source.analysis, &ctx, &mut writer)?
                .is_none());
        }
        assert_eq!(ctx.used(), before);
        let mut writer = DatasetWriter::new(&ctx)?;
        assert!(Plan::at(&job, 0)
            .unwrap()
            .apply(&source.dataset, &job, &source.analysis, &ctx, &mut writer)?
            .is_none());
        job.operations[0] = Operation::Partition {
            columns: vec![Column::Index(1)],
        };
        job.operations[3] = Operation::Balanced { files: 601 };
        assert!(Plan::at(&job, 0)
            .unwrap()
            .apply(&source.dataset, &job, &source.analysis, &ctx, &mut writer)
            .is_err());
        Ok(())
    }
}
