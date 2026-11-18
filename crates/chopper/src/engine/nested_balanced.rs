//! Traverse the original nested ranges, retaining each logical rounding boundary.
use super::*;

/// The decoded tree and its extra traversal capacity drop before either grant.
struct Parent {
    value: ChargedJson<Group>,
    _growth: Reservation,
}
impl Parent {
    fn new(mut value: ChargedJson<Group>, depth: usize, mut growth: Reservation) -> Result<Self> {
        ensure!((1..=64).contains(&depth), "invalid balanced chain depth");
        // Every live traversal entry has precisely two scalar fields. Reserve
        // all depth levels before constructing their BTreeMaps/keys. No entry
        // strings or array payloads are copied from row values here.
        let trees = (2 * json_map_entry_allowance() + "operation".len() + "part".len())
            .checked_mul(depth)
            .context("balanced lineage capacity overflow")?;
        let descriptors = value
            .lineage
            .capacity()
            .checked_mul(std::mem::size_of::<serde_json::Value>())
            .context("balanced lineage capacity overflow")?;
        let length = value
            .lineage
            .len()
            .checked_add(depth)
            .context("balanced lineage length overflow")?;
        // The original decoded owner conservatively keeps its initial vector
        // charge. This additional grant owns the traversal vector, including
        // replacement overlap, rather than transferring a live decode charge.
        growth.resize(
            trees
                .checked_add(descriptors)
                .context("balanced lineage capacity overflow")?,
        )?;
        growth.reserve_vec(&mut value.value_mut().lineage, length)?;
        Ok(Self {
            value,
            _growth: growth,
        })
    }
}

fn walk(
    parent: &mut Group,
    operations: &[Operation],
    step: usize,
    stats: &mut [StageStats],
    ctx: &Context,
    leaf: &mut impl FnMut(&Group) -> Result<()>,
) -> Result<()> {
    ctx.check()?;
    let Operation::Balanced { files } = operations[0] else {
        unreachable!("balanced chain selector")
    };
    ensure!(
        parent.rows >= files,
        "cannot split {} rows into {files} nonempty balanced groups",
        parent.rows
    );
    stats[0].input_groups += 1;
    let parent_rows = parent.rows;
    for part in 0..files {
        ctx.check()?;
        let rows = parent_rows / files + u64::from(part < parent_rows % files);
        parent.rows = rows;
        parent.lineage.push(json!({"operation":step,"part":part+1}));
        validate_lineage(&parent.lineage, ctx)?;
        let current = &mut stats[0];
        current.output_groups += 1;
        ensure!(
            current.output_groups <= ctx.max_files,
            "logical group count exceeds max_files; increase the ceiling explicitly"
        );
        current.smallest_group = current.smallest_group.min(rows);
        current.largest_group = current.largest_group.max(rows);
        if operations.len() == 1 {
            leaf(parent)?;
        } else {
            walk(
                parent,
                &operations[1..],
                step + 1,
                &mut stats[1..],
                ctx,
                leaf,
            )?;
        }
        parent.lineage.pop();
    }
    parent.rows = parent_rows;
    Ok(())
}

// Job validation limits chains to 64 operations. Counters stay bounded on stack;
// no parent/group catalog is collected in memory.
fn statistics(step: usize) -> [StageStats; 64] {
    std::array::from_fn(|i| StageStats {
        operation: step + i + 1,
        input_groups: 0,
        output_groups: 0,
        smallest_group: u64::MAX,
        largest_group: 0,
        empty_groups: 0,
    })
}

fn finish(stats: &mut [StageStats], stages: &mut Stages) -> Result<()> {
    for stats in stats {
        if stats.output_groups == 0 {
            stats.smallest_group = 0;
        }
        stages.push(stats.clone())?;
    }
    Ok(())
}

pub(super) fn shared(
    data: &Dataset,
    operations: &[Operation],
    step: usize,
    ctx: &Context,
    stages: &mut Stages,
) -> Result<Dataset> {
    let mut writer = DatasetWriter::new(ctx)?;
    let mut stats = statistics(step);
    for parent in data.groups()? {
        let mut parent = Parent::new(parent?, operations.len(), Reservation::new(ctx))?;
        let parent = parent.value.value_mut();
        let mut frames = data.frame_lengths(parent, ctx.max_record)?;
        let mut offset = parent.offset;
        walk(parent, operations, step, &mut stats, ctx, &mut |group| {
            let result =
                group_metadata::ClonedGroup::build(group, Reservation::new(ctx), |mut group| {
                    group.offset = offset;
                    group.exact = true;
                    group
                })?;
            for _ in 0..group.rows {
                ctx.check()?;
                offset = offset
                    .checked_add(frames.next().context("missing balanced row")??)
                    .context("spool size overflow")?;
            }
            result.finish(&mut writer)
        })?;
    }
    let mut result = writer.finish()?;
    result.data = data.data.clone();
    finish(&mut stats[..operations.len()], stages)?;
    Ok(result)
}

pub(super) fn emit(
    data: &Dataset,
    operations: &[Operation],
    step: usize,
    ctx: &Context,
    output: &mut impl RowSink,
    stages: &mut Stages,
) -> Result<()> {
    let mut stats = statistics(step);
    for parent in data.groups()? {
        let mut parent = Parent::new(parent?, operations.len(), Reservation::new(ctx))?;
        let parent = parent.value.value_mut();
        let mut rows = data.rows(parent, ctx.max_record)?;
        let mut previous = None;
        walk(parent, operations, step, &mut stats, ctx, &mut |group| {
            let mut owned =
                group_metadata::ClonedGroup::begin(group, output, Reservation::new(ctx))?;
            let result = &mut owned.group;
            result.exact = true;
            for _ in 0..group.rows {
                ctx.check()?;
                let row = rows
                    .next_packed(previous.take())?
                    .context("missing balanced row")?;
                output.packed_row_ref(result, &row)?;
                previous = Some(row);
            }
            ctx.check()?;
            owned.finish(output)
        })?;
    }
    finish(&mut stats[..operations.len()], stages)?;
    Ok(())
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

#[cfg(test)]
mod tests {
    use super::*;

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
    fn nested_ranges_preserve_rounding_parents_stats_and_downstream_domains() -> Result<()> {
        for count in [24, 25, 47, 101] {
            let job = Job {
                random_seed: Some("nested".into()),
                operations: vec![Operation::Balanced { files: 2 }],
                ..Default::default()
            };
            let ctx = Context::new(
                &job.resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
            )?;
            let text = format!(
                "id,text\n{}",
                (0..count)
                    .map(|i| format!("{i},\"界,\"\"q\"\"\ntext\"\n"))
                    .collect::<String>()
            );
            let source = ingest(Box::new(text.as_bytes()), &job, &ctx)?;
            assert_eq!(source.dataset.groups, 1);
            let parent = apply(
                &source.dataset,
                &Operation::Balanced { files: 2 },
                0,
                &job,
                &source.analysis,
                &ctx,
            )?;
            let operations = [
                Operation::Balanced { files: 3 },
                Operation::Balanced { files: 2 },
            ];
            let first = apply(&parent, &operations[0], 1, &job, &source.analysis, &ctx)?;
            let serial = apply(&first, &operations[1], 2, &job, &source.analysis, &ctx)?;
            let expected = vec![
                dataset_stats(&first, 2, parent.groups, &ctx)?,
                dataset_stats(&serial, 3, first.groups, &ctx)?,
            ];
            let mut stats = Stages::new(operations.len(), Reservation::new(&ctx))?;
            let fused = shared(&parent, &operations, 1, &ctx, &mut stats)?;
            assert!(Arc::ptr_eq(&fused.data, &parent.data));
            assert_eq!(snapshot(&fused, &ctx)?, snapshot(&serial, &ctx)?);
            assert_eq!(
                serde_json::to_value(&stats)?,
                serde_json::to_value(&expected)?
            );
            let mut writer = DatasetWriter::new(&ctx)?;
            stats = Stages::new(operations.len(), Reservation::new(&ctx))?;
            emit(&parent, &operations, 1, &ctx, &mut writer, &mut stats)?;
            let emitted = writer.finish()?;
            assert_eq!(snapshot(&emitted, &ctx)?, snapshot(&serial, &ctx)?);
            assert_eq!(
                serde_json::to_value(stats)?,
                serde_json::to_value(expected)?
            );
            let shuffle = Operation::Shuffle {
                strategy: Shuffle::Uniform,
            };
            let a = apply(&serial, &shuffle, 3, &job, &source.analysis, &ctx)?;
            let b = apply(&fused, &shuffle, 3, &job, &source.analysis, &ctx)?;
            assert_eq!(snapshot(&a, &ctx)?, snapshot(&b, &ctx)?);
        }
        Ok(())
    }

    #[test]
    fn invalid_nested_counts_and_cancellation_release_partial_catalogs() -> Result<()> {
        let job = Job {
            random_seed: Some("nested".into()),
            operations: vec![Operation::Balanced { files: 2 }],
            ..Default::default()
        };
        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::new(&job.resources, cancel.clone(), Arc::new(|_| {}))?;
        let source = ingest(Box::new("id\n0\n1\n2\n3\n4\n".as_bytes()), &job, &ctx)?;
        let operations = [
            Operation::Balanced { files: 2 },
            Operation::Balanced { files: 3 },
        ];
        let mut stats = Stages::new(operations.len(), Reservation::new(&ctx))?;
        let before = ctx.used();
        assert!(shared(&source.dataset, &operations, 0, &ctx, &mut stats).is_err());
        assert!(stats.is_empty());
        assert_eq!(ctx.used(), before);
        cancel.store(true, std::sync::atomic::Ordering::Relaxed);
        assert!(shared(&source.dataset, &operations, 0, &ctx, &mut stats).is_err());
        assert_eq!(ctx.used(), before);
        Ok(())
    }
}
