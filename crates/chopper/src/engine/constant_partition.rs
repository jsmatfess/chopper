//! A prior value partition proves its selected columns constant in every child.
//! Splits, assignment and shuffling only select/reorder rows; none changes fields.
use super::*;

fn proof(
    column: usize,
    step: usize,
    job: &Job,
    analysis: &Analysis,
) -> Result<Option<(usize, usize)>> {
    for (index, operation) in job.operations[..step].iter().enumerate().rev() {
        if let Operation::Partition { columns } = operation {
            for (value, selection) in columns.iter().enumerate() {
                if resolve_column(selection, analysis.header.as_deref(), analysis.columns)?
                    == column
                {
                    return Ok(Some((index, value)));
                }
            }
        }
    }
    Ok(None)
}

fn optional<T>(result: Result<T>) -> Result<Option<T>> {
    match result {
        Ok(value) => Ok(Some(value)),
        Err(error)
            if error
                .downcast_ref::<crate::resources::MemoryAdmission>()
                .is_some() =>
        {
            Ok(None)
        }
        Err(error) => Err(error),
    }
}

pub(super) struct Plan {
    pub varying: Vec<usize>,
    _reservation: Reservation,
}

impl Plan {
    pub fn new(
        columns: &[usize],
        step: usize,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
    ) -> Result<Option<Self>> {
        let mut count = 0;
        for &column in columns {
            count += usize::from(proof(column, step, job, analysis)?.is_none());
        }
        if count == columns.len() {
            return Ok(None);
        }
        optional((|| {
            let mut varying = Vec::new();
            let mut reservation = Reservation::new(ctx);
            reservation.reserve_vec(&mut varying, count)?;
            for &column in columns {
                if proof(column, step, job, analysis)?.is_none() {
                    varying.push(column);
                }
            }
            Ok(Self {
                varying,
                _reservation: reservation,
            })
        })())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn child(
        &self,
        parent: &Group,
        columns: &[usize],
        step: usize,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
    ) -> Result<Option<group_metadata::ClonedGroup>> {
        optional((|| {
            let mut values = Vec::new();
            let mut reservation = Reservation::new(ctx);
            reservation.reserve_vec(&mut values, columns.len())?;
            for &column in columns {
                let (operation, value) =
                    proof(column, step, job, analysis)?.context("missing constant-column proof")?;
                let entry = parent
                    .lineage
                    .iter()
                    .find(|entry| entry["operation"].as_u64() == Some(operation as u64))
                    .context("missing constant-column parent lineage")?;
                values.push(
                    entry["values"]
                        .get(value)
                        .and_then(serde_json::Value::as_str)
                        .context("invalid constant-column lineage value")?,
                );
            }
            group_metadata::ClonedGroup::child(
                parent,
                &child_metadata::Entry::References {
                    operation: step,
                    values: &values,
                },
                ctx,
                |lineage| Group {
                    offset: parent.offset,
                    rows: parent.rows,
                    lineage,
                    exact: false,
                },
            )
        })())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn shared(
        &self,
        data: &Dataset,
        columns: &[usize],
        step: usize,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
    ) -> Result<Option<Dataset>> {
        let mut writer = DatasetWriter::new(ctx)?;
        for parent in data.groups()? {
            ctx.check()?;
            let parent = parent?;
            // Partitioning an empty named allocation produces no child.
            if parent.rows == 0 {
                continue;
            }
            let Some(group) = self.child(&parent, columns, step, job, analysis, ctx)? else {
                return Ok(None); // Drop partial catalog before ordinary execution retries.
            };
            group.finish(&mut writer)?;
        }
        let mut result = writer.finish()?;
        result.data = data.data.clone();
        Ok(Some(result))
    }
}

pub(super) fn copy(
    data: &Dataset,
    mut parent: group_metadata::ClonedGroup,
    ctx: &Context,
    output: &mut impl RowSink,
) -> Result<()> {
    let mut rows = data.rows(&parent.group, ctx.max_record)?;
    parent.restart(output);
    let mut previous = None;
    while let Some(mut row) = rows.next_packed(previous.take())? {
        ctx.check()?;
        row.key = PackedKey::Bytes(Box::default());
        output.packed_row_ref(&mut parent.group, &row)?;
        previous = Some(row);
    }
    ctx.check()?;
    parent.finish(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot(data: &Dataset, ctx: &Context) -> Result<serde_json::Value> {
        let mut groups = Vec::new();
        for group in data.groups()? {
            let group = group?;
            let rows = data
                .rows(&group, ctx.max_record)?
                .map(|row| {
                    let row = row?;
                    Ok(json!([row.id, row.ordinal, row.key, row.fields]))
                })
                .collect::<Result<Vec<_>>>()?;
            groups.push(json!([group.lineage, group.exact, rows]));
        }
        Ok(json!(groups))
    }

    #[test]
    fn constant_and_partial_keys_match_original_partition_and_child_shuffle() -> Result<()> {
        for columns in [
            vec![Column::Index(1)],
            vec![Column::Name("country".into()), Column::Index(1)],
            vec![Column::Index(1), Column::Index(2)],
            vec![Column::Index(2), Column::Index(1), Column::Index(2)],
        ] {
            let job = Job {
                random_seed: Some("constant-keys".into()),
                operations: vec![
                    Operation::Partition {
                        columns: vec![Column::Name("country".into())],
                    },
                    Operation::Partition {
                        columns: columns.clone(),
                    },
                    Operation::Shuffle {
                        strategy: Shuffle::Uniform,
                    },
                ],
                ..Default::default()
            };
            let ctx = Context::new(
                &job.resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            let text = format!(
                "id,country,city,payload\n{}",
                (0..121)
                    .map(|i| format!("{i},g{},c{},\"界,\"\"q\"\"\ntext\"\n", i % 3, (i / 3) % 5))
                    .collect::<String>()
            );
            let source = ingest(Box::new(text.as_bytes()), &job, &ctx)?;
            assert_eq!(source.dataset.groups, 3);
            let resolved = resolve_columns(
                &columns,
                source.analysis.header.as_deref(),
                source.analysis.columns,
            )?;
            let plan = Plan::new(&resolved, 1, &job, &source.analysis, &ctx)?.unwrap();
            assert_eq!(
                plan.varying.len(),
                resolved.iter().filter(|&&c| c == 2).count()
            );
            for shuffled in [false, true] {
                let mut serial = DatasetWriter::new(&ctx)?;
                let mut candidate = DatasetWriter::new(&ctx)?;
                for group in source.dataset.groups()? {
                    let group = group?;
                    partition(
                        &source.dataset,
                        &group,
                        &resolved,
                        1,
                        &mut serial,
                        &ctx,
                        shuffled.then_some(("constant-keys", 2)),
                        None,
                    )?;
                    apply_parent(
                        &source.dataset,
                        &group,
                        &job.operations[1],
                        1,
                        &job,
                        &source.analysis,
                        &ctx,
                        &mut candidate,
                        shuffled.then_some(2),
                        None,
                    )?;
                }
                let serial = serial.finish()?;
                let candidate = candidate.finish()?;
                assert_eq!(snapshot(&serial, &ctx)?, snapshot(&candidate, &ctx)?);
                if plan.varying.is_empty() && !shuffled {
                    let shared = apply(
                        &source.dataset,
                        &job.operations[1],
                        1,
                        &job,
                        &source.analysis,
                        &ctx,
                    )?;
                    assert!(Arc::ptr_eq(&shared.data, &source.dataset.data));
                    assert_eq!(snapshot(&serial, &ctx)?, snapshot(&shared, &ctx)?);
                }
            }
        }
        Ok(())
    }

    #[test]
    fn proof_survives_selection_but_does_not_use_observed_values() -> Result<()> {
        let job = Job {
            operations: vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                Operation::Balanced { files: 2 },
                Operation::AssignProbabilistic {
                    groups: vec![],
                    strata: vec![],
                },
                Operation::Shuffle {
                    strategy: Shuffle::FisherYates,
                },
                Operation::Partition {
                    columns: vec![Column::Index(1), Column::Index(2)],
                },
            ],
            ..Default::default()
        };
        let analysis = Analysis {
            algorithm_version: Analysis::algorithm_version_for(&job),
            execution: None,
            column_values: ColumnSummaries::default(),
            seed: "x".into(),
            rows: 0,
            columns: 3,
            header: None,
            preview: Preview::default(),
            logical_digest: String::new().into(),
            groups: 0,
            output_files: 0,
            output_csv_bytes: 0,
            largest_record_bytes: 0,
            temp_bytes: 0,
            peak_temp_bytes: 0,
            memory_budget_bytes: 0,
            workers: 1,
            analysis_seconds: 0.,
            timings: Default::default(),
            diagnostics: json!({}).into(),
            stages: vec![].into(),
            warnings: vec![].into(),
            accuracy: String::new().into(),
        };
        assert_eq!(proof(1, 4, &job, &analysis)?, Some((0, 0)));
        assert_eq!(proof(2, 4, &job, &analysis)?, None);
        assert_eq!(proof(1, 0, &job, &analysis)?, None);
        let ctx = Context::new(
            &Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let before = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        let mut blocker = Reservation::new(&ctx);
        blocker.resize(ctx.memory / 2 - before as usize - 7)?;
        assert!(Plan::new(&[1, 2], 4, &job, &analysis, &ctx)?.is_none());
        drop(blocker);
        let plan = Plan::new(&[1, 2], 4, &job, &analysis, &ctx)?.unwrap();
        assert_eq!(plan.varying, [2]);
        drop(plan);
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], before);
        Ok(())
    }

    #[test]
    fn shared_partition_drops_named_empty_children_and_cleans_up_on_cancellation() -> Result<()> {
        let job = Job {
            random_seed: Some("empty-constant".into()),
            operations: vec![
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
                Operation::AssignProbabilistic {
                    groups: vec![
                        Allocation {
                            name: "keep".into(),
                            percent: "100".into(),
                        },
                        Allocation {
                            name: "empty".into(),
                            percent: "0".into(),
                        },
                    ],
                    strata: vec![],
                },
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
            ],
            ..Default::default()
        };
        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::new(&job.resources, cancel.clone(), Arc::new(|_| {}))?;
        let source = ingest(Box::new("id,key\n0,a\n1,b\n2,a\n".as_bytes()), &job, &ctx)?;
        let assigned = apply(
            &source.dataset,
            &job.operations[1],
            1,
            &job,
            &source.analysis,
            &ctx,
        )?;
        assert_eq!(assigned.groups, 4);
        let shared = apply(
            &assigned,
            &job.operations[2],
            2,
            &job,
            &source.analysis,
            &ctx,
        )?;
        assert_eq!(shared.groups, 2);
        assert!(Arc::ptr_eq(&shared.data, &assigned.data));
        let mut serial = DatasetWriter::new(&ctx)?;
        for group in assigned.groups()? {
            partition(&assigned, &*group?, &[1], 2, &mut serial, &ctx, None, None)?;
        }
        let serial = serial.finish()?;
        assert_eq!(snapshot(&serial, &ctx)?, snapshot(&shared, &ctx)?);
        let before = ctx.used();
        cancel.store(true, std::sync::atomic::Ordering::Relaxed);
        assert!(apply(
            &assigned,
            &job.operations[2],
            2,
            &job,
            &source.analysis,
            &ctx
        )
        .is_err());
        assert_eq!(ctx.used(), before);
        Ok(())
    }
}
