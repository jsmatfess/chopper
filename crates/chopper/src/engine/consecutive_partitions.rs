//! Sort nested partition tuples once; reconstruct every logical stage.
use super::*;

pub(super) fn admission(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<crate::resources::MemoryAdmission>()
        .is_some()
}

#[derive(Clone, Copy)]
pub(super) struct Plan<'a> {
    operations: &'a [Operation],
    step: usize,
}

pub(super) struct Stats {
    levels: [StageStats; 64],
    count: usize,
}
impl Stats {
    pub fn finish(&mut self) {
        for index in 0..self.count {
            if self.levels[index].output_groups == 0 {
                self.levels[index].smallest_group = 0;
            }
            if index > 0 {
                self.levels[index].input_groups = self.levels[index - 1].output_groups;
            }
        }
    }
    pub fn last(&self) -> &StageStats {
        &self.levels[self.count - 1]
    }
    pub fn append(self, stages: &mut Stages) -> Result<()> {
        stages.extend(self.levels.into_iter().take(self.count))
    }
}

impl<'a> Plan<'a> {
    pub fn at(job: &'a Job, step: usize) -> Option<Self> {
        let operations = job.operations.get(step..)?;
        let count = operations
            .iter()
            .take_while(|op| matches!(op, Operation::Partition { columns } if !columns.is_empty()))
            .count();
        (count > 1).then_some(Self {
            operations: &operations[..count],
            step,
        })
    }
    pub fn len(self) -> usize {
        self.operations.len()
    }
    fn columns(self) -> impl Iterator<Item = &'a [Column]> {
        self.operations.iter().map(|op| match op {
            Operation::Partition { columns } => columns.as_slice(),
            _ => unreachable!("consecutive partition selector"),
        })
    }
    pub fn stats(self) -> Stats {
        Stats {
            count: self.len(),
            levels: std::array::from_fn(|level| StageStats {
                operation: self.step + level + 1,
                input_groups: 0,
                output_groups: 0,
                smallest_group: u64::MAX,
                largest_group: 0,
                empty_groups: 0,
            }),
        }
    }
    pub fn resolve(
        self,
        header: Option<&[String]>,
        width: usize,
        reservation: &mut Reservation,
    ) -> Result<Vec<usize>> {
        let count = self.columns().try_fold(0usize, |count, columns| {
            count
                .checked_add(columns.len())
                .context("partition selection size overflow")
        })?;
        let mut selected = Vec::new();
        reservation.reserve_vec(&mut selected, count)?;
        for columns in self.columns() {
            for column in columns {
                selected.push(resolve_column(column, header, width)?);
            }
        }
        Ok(selected)
    }

    pub fn apply(
        self,
        data: &Dataset,
        header: Option<&[String]>,
        width: usize,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<Stats> {
        let mut reservation = Reservation::new(ctx);
        let columns = self.resolve(header, width, &mut reservation)?;
        let mut stats = self.stats();
        for parent in data.groups()? {
            ctx.check()?;
            let parent = parent?;
            let mut sorter = Sorter::new(ctx, SortOrder::Key);
            for row in data.packed_rows(&parent, ctx.max_record)? {
                let mut row = row?;
                let key = OperationKey::tuple(
                    row.fields(),
                    &columns,
                    0,
                    Reservation::new(ctx),
                    &mut sorter,
                )?;
                let capacity = key.install(&mut row, &mut sorter)?;
                sorter.push_compact(row, capacity)?;
            }
            self.emit(sorter.finish()?, &parent, &columns, &mut stats, output, ctx)?;
        }
        stats.finish();
        Ok(stats)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn emit(
        self,
        rows: SortedRows,
        parent: &Group,
        columns: &[usize],
        stats: &mut Stats,
        output: &mut impl RowSink,
        ctx: &Context,
    ) -> Result<()> {
        let mut selections = [0usize; 64];
        let mut total = 0usize;
        for (index, columns) in self.columns().enumerate() {
            total = total
                .checked_add(columns.len())
                .context("partition selection size overflow")?;
            selections[index] = total;
        }
        ensure!(
            total == columns.len(),
            "invalid combined partition selection"
        );
        let mut previous = Vec::new();
        let mut reservation = Reservation::new(ctx);
        let mut previous_ends = [0usize; 64];
        let mut counts = [0u64; 64];
        let mut lineage =
            group_metadata::ClonedGroup::build(parent, Reservation::new(ctx), |group| group)?;
        lineage.group.exact = false;
        let base = lineage.group.lineage.len();
        let mut group: Option<group_metadata::ClonedGroup> = None;
        let mut rows = rows.reusing();
        stats.levels[0].input_groups += 1;
        while let Some(row) = rows.next()? {
            ctx.check()?;
            let key = row.key.as_ref();
            if group.is_none() || previous != key {
                let ends = tuple_ends(key, &selections[..self.len()])?;
                let common = if group.is_some() {
                    (0..self.len())
                        .take_while(|&i| key[..ends[i]] == previous[..previous_ends[i]])
                        .count()
                } else {
                    0
                };
                if let Some(group) = group.take() {
                    group.finish(output)?;
                }
                for (level, count) in counts.iter_mut().enumerate().take(self.len()).skip(common) {
                    if *count > 0 {
                        stats.levels[level].smallest_group =
                            stats.levels[level].smallest_group.min(*count);
                        stats.levels[level].largest_group =
                            stats.levels[level].largest_group.max(*count);
                        *count = 0;
                    }
                }
                reservation.reserve_vec(&mut previous, key.len())?;
                previous.clear();
                previous.extend_from_slice(key);
                previous_ends = ends;
                lineage.truncate(base + common)?;
                for level in common..self.len() {
                    let start = if level == 0 { 0 } else { selections[level - 1] };
                    lineage.append(
                        &child_metadata::Entry::values(
                            self.step + level,
                            row.fields(),
                            &columns[start..selections[level]],
                        ),
                        ctx,
                    )?;
                    stats.levels[level].output_groups += 1;
                    ensure!(
                        stats.levels[level].output_groups <= ctx.max_files,
                        "logical group count exceeds max_files; increase the ceiling explicitly"
                    );
                }
                let next = group_metadata::ClonedGroup::begin(
                    &lineage.group,
                    output,
                    Reservation::new(ctx),
                )?;
                group = Some(next);
            }
            for count in &mut counts[..self.len()] {
                *count += 1;
            }
            row.key = PackedKey::Bytes(Box::default());
            output.packed_row_ref(&mut group.as_mut().unwrap().group, row)?;
        }
        if let Some(group) = group {
            ctx.check()?;
            group.finish(output)?;
        }
        for (level, count) in counts.into_iter().enumerate().take(self.len()) {
            if count > 0 {
                stats.levels[level].smallest_group = stats.levels[level].smallest_group.min(count);
                stats.levels[level].largest_group = stats.levels[level].largest_group.max(count);
            }
        }
        ctx.consecutive_partitions_fused(parent.rows);
        Ok(())
    }
}

// Zero bytes inside values are escaped as 0,255; 0,0 ends one selected field.
fn tuple_ends(key: &[u8], selections: &[usize]) -> Result<[usize; 64]> {
    ensure!(!selections.is_empty(), "empty partition tuple selection");
    let mut ends = [0; 64];
    let (mut byte, mut fields, mut level) = (0, 0, 0);
    while byte < key.len() {
        if key[byte] != 0 {
            byte += 1;
            continue;
        }
        match key.get(byte + 1) {
            Some(255) => byte += 2,
            Some(0) => {
                byte += 2;
                fields += 1;
                if level < selections.len() && fields == selections[level] {
                    ends[level] = byte;
                    level += 1;
                }
            }
            _ => anyhow::bail!("invalid combined partition tuple key"),
        }
    }
    ensure!(
        level == selections.len() && ends[level - 1] == key.len(),
        "invalid combined partition tuple boundary"
    );
    Ok(ends)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{atomic::Ordering, Mutex};

    fn parts() -> Vec<Operation> {
        vec![
            Operation::Partition {
                columns: vec![Column::Name("country".into())],
            },
            Operation::Partition {
                columns: vec![Column::Index(2), Column::Index(1)],
            },
            Operation::Partition {
                columns: vec![Column::Index(1)],
            },
        ]
    }
    fn fixture(count: usize) -> Result<Vec<u8>> {
        let mut text = b"id,country,city,payload\n".to_vec();
        let mut serializer = chopper_core::csv::Serializer::new(&CsvSettings::default())?;
        for i in 0..count {
            let id = i.to_string();
            text.extend_from_slice(serializer.serialize_fields([
                &id,
                ["a", "a\0", "a\0界"][i % 3],
                ["", "c", "c\0界", "c\"q"][(i / 3) % 4],
                "quoted,\"q\"\ntext",
            ])?);
        }
        Ok(text)
    }
    fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
        let mut result = Vec::new();
        for group in data.groups()? {
            let group = group?;
            let rows = data
                .rows(&group, ctx.max_record)?
                .map(|row| {
                    let row = row?;
                    Ok(json!([row.id, row.ordinal, row.key, row.fields]))
                })
                .collect::<Result<Vec<_>>>()?;
            result.push(json!([group.lineage, group.exact, rows]));
        }
        Ok(json!(result))
    }
    fn context(job: &Job) -> Result<Context> {
        Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )
    }

    #[test]
    fn selection_stops_at_each_nonpartition_and_tuple_scanning_handles_escaping() -> Result<()> {
        let mut job = Job {
            operations: parts(),
            ..Default::default()
        };
        assert_eq!(Plan::at(&job, 0).unwrap().len(), 3);
        assert_eq!(Plan::at(&job, 1).unwrap().len(), 2);
        assert!(Plan::at(&job, 2).is_none());
        for barrier in [
            Operation::Balanced { files: 2 },
            Operation::Interleaved { files: 2 },
            Operation::Shuffle {
                strategy: Shuffle::Uniform,
            },
            Operation::Assign {
                groups: vec![],
                strata: vec![],
            },
        ] {
            job.operations = parts();
            job.operations.insert(1, barrier);
            assert!(Plan::at(&job, 0).is_none());
            assert_eq!(Plan::at(&job, 2).unwrap().step, 2);
        }
        let fields = vec!["".into(), "a\0界".into(), "\0\0".into()];
        let key = random::tuple_key(&fields, &[0, 1, 2, 1]);
        let ends = tuple_ends(&key, &[1, 3, 4])?;
        assert_eq!(&key[..ends[0]], random::tuple_key(&fields, &[0]));
        assert_eq!(&key[..ends[1]], random::tuple_key(&fields, &[0, 1, 2]));
        assert_eq!(ends[2], key.len());
        for invalid in [&b"a\0"[..], &b"a\0\x01"[..], &b"a\0\0b\0\0"[..]] {
            assert!(tuple_ends(invalid, &[1]).is_err());
        }
        assert!(tuple_ends(&[], &[]).is_err());
        Ok(())
    }

    #[test]
    fn resident_and_hierarchical_grouping_preserve_all_stages_and_downstream_domains() -> Result<()>
    {
        for budget in [crate::storage::SORT_HIERARCHY_TEST_MEMORY, 32 * 1024 * 1024] {
            let mut operations = vec![Operation::Balanced { files: 2 }];
            operations.extend(parts());
            operations.push(Operation::Shuffle {
                strategy: Shuffle::Uniform,
            });
            let job = Job {
                random_seed: Some("partition-chain".into()),
                operations,
                resources: Resources {
                    memory_mb: 32.into(),
                    max_record_bytes: 1024 * 1024,
                    workers: 1,
                    grouping: Grouping::Sort,
                    ..Default::default()
                },
                ..Default::default()
            };
            let mut ctx = context(&job)?;
            ctx.memory = budget;
            let text = fixture(333)?;
            let source = ingest(Box::new(text.as_slice()), &job, &ctx)?;
            let parents = apply(
                &source.dataset,
                &job.operations[0],
                0,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let mut expected = apply(
                &parents,
                &job.operations[1],
                1,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let mut stats = vec![dataset_stats(&expected, 2, parents.groups, &ctx)?];
            for step in 2..4 {
                let before = expected.groups;
                expected = apply(
                    &expected,
                    &job.operations[step],
                    step,
                    &job,
                    &source.analysis,
                    &ctx,
                )?;
                stats.push(dataset_stats(&expected, step + 1, before, &ctx)?);
            }
            let plan = Plan::at(&job, 1).unwrap();
            let mut writer = DatasetWriter::new(&ctx)?;
            let actual_stats = plan.apply(
                &parents,
                source.analysis.header.as_deref(),
                source.analysis.columns,
                &ctx,
                &mut writer,
            )?;
            let actual = writer.finish()?;
            let mut actual_stages = Stages::new(job.operations.len(), Reservation::new(&ctx))?;
            actual_stats.append(&mut actual_stages)?;
            assert_eq!(
                serde_json::to_value(stats)?,
                serde_json::to_value(actual_stages)?
            );
            assert_eq!(snapshot(&expected, &ctx)?, snapshot(&actual, &ctx)?);
            let expected = apply(
                &expected,
                &job.operations[4],
                4,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let actual = apply(&actual, &job.operations[4], 4, &job, &source.analysis, &ctx)?;
            assert_eq!(snapshot(&expected, &ctx)?, snapshot(&actual, &ctx)?);
            if budget == crate::storage::SORT_HIERARCHY_TEST_MEMORY {
                assert!(ctx.diagnostics()["merge_operations"].as_u64().unwrap() > 2);
            }
        }
        Ok(())
    }

    #[test]
    fn ingestion_terminal_and_empty_chains_match_original_encoded_snapshot() -> Result<()> {
        for count in [0, 121] {
            let job = Job {
                random_seed: Some("ingest-parts".into()),
                operations: parts(),
                ..Default::default()
            };
            let ctx = context(&job)?;
            let text = fixture(count)?;
            let source = ingest(Box::new(text.as_slice()), &job, &ctx)?;
            let mut data = source.dataset;
            let mut expected_stats = source.analysis.stages.to_vec();
            for step in 1..3 {
                let before = data.groups;
                data = apply(
                    &data,
                    &job.operations[step],
                    step,
                    &job,
                    &source.analysis,
                    &ctx,
                )?;
                expected_stats.push(dataset_stats(&data, step + 1, before, &ctx)?);
            }
            let expected = output::plan(&data, &job, source.analysis.header.as_deref(), &ctx)?;
            let actual = ingest_options(&mut text.as_slice(), &job, &ctx, true, false, false)?;
            assert_eq!(actual.consumed, 3);
            assert_eq!(
                serde_json::to_value(expected_stats)?,
                serde_json::to_value(&actual.analysis.stages)?
            );
            assert_eq!(
                actual.analysis.logical_digest,
                source.analysis.logical_digest
            );
            let actual = actual.final_plan.unwrap();
            let mut a = Vec::new();
            let mut b = Vec::new();
            actual.data.reader()?.read_to_end(&mut a)?;
            expected.data.reader()?.read_to_end(&mut b)?;
            assert_eq!(a, b);
            assert_eq!(actual.files, expected.files);
        }
        Ok(())
    }

    #[test]
    fn admission_retry_restarts_csv_or_dataset_without_losing_rows_or_retaining_grants(
    ) -> Result<()> {
        for initial in [true, false] {
            let dir = tempfile::tempdir()?;
            let path = dir.path().join("input.csv");
            std::fs::write(&path, fixture(121)?)?;
            let mut operations = if initial {
                vec![]
            } else {
                vec![Operation::Balanced { files: 2 }]
            };
            operations.extend(parts());
            operations.push(Operation::Shuffle {
                strategy: Shuffle::Uniform,
            });
            let job = Job {
                input: path.to_string_lossy().into(),
                random_seed: Some("retry-parts".into()),
                operations,
                ..Default::default()
            };
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
                        "Preparing consecutive value partitions"
                    };
                    if progress.phase == trigger && !injected.swap(true, Ordering::Relaxed) {
                        let bytes = pool.usage().limit_bytes - pool.usage().reserved_bytes;
                        pool.acquire(bytes).unwrap();
                        *blocker.lock().unwrap() = bytes;
                    } else if progress.phase == "Retrying value partitions without fusion" {
                        let bytes = std::mem::take(&mut *blocker.lock().unwrap());
                        pool.release(bytes);
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
            assert_eq!(
                actual.analysis.diagnostics["consecutive_partition_retries"],
                1
            );
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
            assert_eq!(actual.analysis.output_files, expected.analysis.output_files);
            drop(actual);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }
    #[test]
    fn partial_emission_denial_or_cancellation_discards_rows_catalog_and_reservations() -> Result<()>
    {
        struct StopSink {
            writer: DatasetWriter,
            pool: Arc<crate::resources::MemoryPool>,
            cancel: Arc<AtomicBool>,
            cancel_mode: bool,
            held: u64,
            rows: u64,
        }
        impl RowSink for StopSink {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                self.writer.begin(lineage, exact)
            }
            fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
                self.rows += 1;
                self.writer.row(group, row)
            }
            fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
                self.rows += 1;
                self.writer.packed_row_ref(group, row)
            }
            fn end(&mut self, group: Group) -> Result<()> {
                self.writer.end(group)?;
                if self.cancel_mode {
                    self.cancel.store(true, Ordering::Relaxed);
                } else {
                    let usage = self.pool.usage();
                    self.held = usage.limit_bytes - usage.reserved_bytes;
                    self.pool.acquire(self.held)?;
                }
                Ok(())
            }
        }
        for cancel_mode in [false, true] {
            let mut operations = vec![Operation::Balanced { files: 2 }];
            operations.extend(parts());
            let job = Job {
                random_seed: Some("partial-parts".into()),
                operations,
                ..Default::default()
            };
            let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
            let cancel = Arc::new(AtomicBool::new(false));
            let ctx = Context::with_memory_pool(
                &job.resources,
                cancel.clone(),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let text = fixture(121)?;
            let source = ingest(Box::new(text.as_slice()), &job, &ctx)?;
            let before = ctx.used();
            let reserved = pool.usage().reserved_bytes;
            let mut sink = StopSink {
                writer: DatasetWriter::new(&ctx)?,
                pool: pool.clone(),
                cancel,
                cancel_mode,
                held: 0,
                rows: 0,
            };
            let error = Plan::at(&job, 1)
                .unwrap()
                .apply(
                    &source.dataset,
                    source.analysis.header.as_deref(),
                    source.analysis.columns,
                    &ctx,
                    &mut sink,
                )
                .err()
                .unwrap();
            assert_eq!(admission(&error), !cancel_mode);
            assert!(sink.rows > 0, "failure must follow actual emission");
            pool.release(sink.held);
            drop(sink);
            assert_eq!(ctx.used(), before);
            assert_eq!(pool.usage().reserved_bytes, reserved);
        }
        Ok(())
    }
}
