//! Bounded experiment: independent sort workspaces, ordered spool replay.
//! The extra materialization is deliberate and included in whole-job timings.
use super::*;

struct Task {
    parent: Group,
    result: Option<Result<Dataset>>,
    _metadata: Reservation,
}

#[cfg(test)]
fn retain_parent(parent: &Group, ctx: &Context) -> Result<Reservation> {
    let mut reservation = Reservation::new(ctx);
    reservation.resize(parent.json_capacity()?)?;
    Ok(reservation)
}

fn replay(data: &Dataset, output: &mut impl RowSink, ctx: &Context) -> Result<()> {
    for group in data.groups()? {
        let group = group?;
        let mut rows = data.rows(&group, ctx.max_record)?;
        let (group, _metadata) = group.into_parts();
        let mut target = output.begin(group.lineage, group.exact);
        let mut previous = None;
        while let Some(row) = rows.next_packed(previous.take())? {
            ctx.check()?;
            output.packed_row_ref(&mut target, &row)?;
            previous = Some(row);
        }
        output.end(target)?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn evaluate(
    data: &Dataset,
    parent: &Group,
    step: usize,
    job: &Job,
    ctx: &Context,
    concurrency: usize,
    balanced_after: Option<(usize, u64)>,
) -> Result<Dataset> {
    let mut local = ctx.clone();
    // Divide only sorter/merge sizing. The clone keeps the original shared
    // workspace, process pool, disk/file budget, cancellation and worker pool.
    local.memory /= concurrency;
    let domain = random::json_domain(job.seed.as_ref().unwrap(), step as u64, &parent.lineage)?;
    let mut output = DatasetWriter::new(&local)?;
    let mut sorter = Sorter::new(&local, SortOrder::Random(domain));
    for row in data.packed_rows(parent, ctx.max_record)? {
        let mut row = row?;
        let key = random::block(&domain, row.id, 0);
        row.key = PackedKey::Random(key[..16].try_into().unwrap());
        // An oversized row in the smaller optional workspace retries with the
        // original serial budget, rather than becoming a new job failure.
        if row.memory() > local.memory / 4 {
            return Err(crate::resources::MemoryAdmission::Local.into());
        }
        sorter.push_compact(row, 16)?;
    }
    let sorted = sorter.finish()?;
    if let Some((balanced_step, files)) = balanced_after {
        emit_balanced(
            sorted,
            parent,
            files,
            balanced_step,
            true,
            &mut output,
            &local,
        )?;
    } else {
        let mut owned = group_metadata::ClonedGroup::begin(parent, &output, Reservation::new(ctx))?;
        let group = &mut owned.group;
        sorted.try_for_each_packed(|row| {
            ctx.check()?;
            row.ordinal = group.rows;
            row.key = PackedKey::Bytes(Box::default());
            output.packed_row_ref(group, row)
        })?;
        ctx.check()?;
        owned.finish(&mut output)?;
    }
    output.finish()
}

// Wait for every task before inspecting errors. A non-admission error always
// wins over retry, so corrupt input/cancellation is never masked by pressure.
fn batch_failed(tasks: &mut [Task], ctx: &Context) -> Result<bool> {
    let mut denied = false;
    for task in tasks.iter_mut() {
        if task.result.as_ref().unwrap().is_err() {
            let error = task.result.take().unwrap().err().unwrap();
            if error
                .downcast_ref::<crate::resources::MemoryAdmission>()
                .is_none()
            {
                return Err(error);
            }
            denied = true;
        }
    }
    if denied {
        // Drop successful siblings and their files/reservations before retry.
        for task in tasks {
            task.result = None;
        }
        ctx.group_retry();
    }
    Ok(denied)
}

fn consume_batch<S: RowSink>(
    tasks: &mut [Task],
    ctx: &Context,
    output: &mut S,
    mut serial: impl FnMut(&Group, &mut S) -> Result<()>,
) -> Result<bool> {
    let denied = batch_failed(tasks, ctx)?;
    if denied {
        for task in tasks {
            serial(&task.parent, output)?;
        }
    } else {
        for task in tasks {
            let result = task.result.take().unwrap()?;
            replay(&result, output, ctx)?;
        }
    }
    Ok(denied)
}

/// Optional prefetch owns a vector and possibly earlier parents. Release those
/// owners before retrying the rewound record, then finish this stage serially.
fn finish_serial_after_prefetch_denial<S: RowSink>(
    mut tasks: Vec<Task>,
    reservation: Reservation,
    mut parents: impl Iterator<Item = Result<ChargedJson<Group>>>,
    ctx: &Context,
    output: &mut S,
    mut serial: impl FnMut(&Group, &mut S) -> Result<()>,
) -> Result<()> {
    ctx.check()?;
    for task in tasks.drain(..) {
        ctx.check()?;
        serial(&task.parent, output)?;
    }
    drop(tasks);
    drop(reservation);
    ctx.group_retry();
    loop {
        ctx.check()?;
        let Some(parent) = parents.next() else {
            return Ok(());
        };
        serial(&*parent?, output)?;
    }
}

#[allow(clippy::too_many_arguments)]
pub(super) fn apply(
    data: &Dataset,
    operation: &Operation,
    step: usize,
    job: &Job,
    analysis: &Analysis,
    ctx: &Context,
    output: &mut impl RowSink,
    shuffle_after: Option<usize>,
    balanced_after: Option<(usize, u64)>,
) -> Result<bool> {
    if ctx.workers() < 2
        || data.groups < 2
        || !matches!(
            operation,
            Operation::Shuffle {
                strategy: Shuffle::Auto | Shuffle::Uniform,
                ..
            }
        )
    {
        return Ok(false);
    }
    let mut reservation = Reservation::new(ctx);
    let mut tasks: Vec<Task> = Vec::new();
    let batch_size = ctx.workers().min(4);
    if let Err(error) = reservation.reserve_vec(&mut tasks, batch_size) {
        if error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_some()
        {
            return Ok(false);
        }
        return Err(error);
    }
    let mut parents = match data.retryable_groups() {
        Ok(parents) => parents,
        Err(error)
            if error
                .downcast_ref::<crate::resources::MemoryAdmission>()
                .is_some() =>
        {
            // No parent was read or emitted; the ordinary stage can retry after
            // this optional batch's vector and grant have been dropped.
            ctx.check()?;
            return Ok(false);
        }
        Err(error) => return Err(error),
    };
    loop {
        ctx.check()?;
        ctx.pressure_boundary();
        tasks.clear();
        for _ in 0..batch_size {
            ctx.check()?;
            let Some(parent) = parents.next() else { break };
            let parent = match parent {
                Ok(parent) => parent,
                Err(error)
                    if error
                        .downcast_ref::<crate::resources::MemoryAdmission>()
                        .is_some() =>
                {
                    finish_serial_after_prefetch_denial(
                        tasks,
                        reservation,
                        parents,
                        ctx,
                        output,
                        |parent, output| {
                            apply_parent(
                                data,
                                parent,
                                operation,
                                step,
                                job,
                                analysis,
                                ctx,
                                output,
                                shuffle_after,
                                balanced_after,
                            )
                        },
                    )?;
                    return Ok(true);
                }
                Err(error) => return Err(error),
            };
            let (parent, metadata) = parent.into_parts();
            tasks.push(Task {
                parent,
                result: None,
                _metadata: metadata,
            });
        }
        if tasks.is_empty() {
            return Ok(true);
        }
        if tasks.len() == 1 {
            apply_parent(
                data,
                &tasks[0].parent,
                operation,
                step,
                job,
                analysis,
                ctx,
                output,
                shuffle_after,
                balanced_after,
            )?;
            continue;
        }
        let concurrency = tasks.len();
        ctx.for_each_group(&mut tasks, |task| {
            #[cfg(test)]
            if let Some(hook) = &ctx.group_test_hook {
                if let Err(error) = hook(task.parent.offset, "before") {
                    task.result = Some(Err(error));
                    return;
                }
            }
            let result = evaluate(
                data,
                &task.parent,
                step,
                job,
                ctx,
                concurrency,
                balanced_after,
            );
            #[cfg(test)]
            if let Some(hook) = &ctx.group_test_hook {
                let event = match &result {
                    Ok(_) => "materialized",
                    Err(error)
                        if matches!(
                            error.downcast_ref::<crate::resources::MemoryAdmission>(),
                            Some(crate::resources::MemoryAdmission::Shared { .. })
                        ) =>
                    {
                        "shared_denied"
                    }
                    Err(_) => "failed",
                };
                if let Err(error) = hook(task.parent.offset, event) {
                    task.result = Some(Err(error));
                    return;
                }
            }
            task.result = Some(result);
        });
        if consume_batch(&mut tasks, ctx, output, |parent, output| {
            #[cfg(test)]
            if let Some(hook) = &ctx.group_test_hook {
                hook(parent.offset, "serial")?;
            }
            apply_parent(
                data,
                parent,
                operation,
                step,
                job,
                analysis,
                ctx,
                output,
                shuffle_after,
                balanced_after,
            )
        })? {
            // One batch retry, then stay serial for the remaining stage.
            // Release retained task metadata before reading the next parent.
            drop(tasks);
            drop(reservation);
            loop {
                ctx.check()?;
                let Some(parent) = parents.next() else { break };
                #[cfg(test)]
                if let Some(hook) = &ctx.group_test_hook {
                    hook(
                        parent
                            .as_ref()
                            .map_err(|e| anyhow::anyhow!("{e:#}"))?
                            .offset,
                        "serial",
                    )?;
                }
                apply_parent(
                    data,
                    &*parent?,
                    operation,
                    step,
                    job,
                    analysis,
                    ctx,
                    output,
                    shuffle_after,
                    balanced_after,
                )?;
            }
            return Ok(true);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replay_endpoint_cancellation_rejects_native_plan_and_releases_siblings() -> Result<()> {
        // Cancel after a successful row write, including the final row of the
        // final sibling. Exercise the native final-output sink: replay returning
        // from an intermediate DatasetWriter is not the publication boundary.
        struct CancelAfter<'a> {
            inner: output::PlanWriter<'a>,
            cancel: Arc<AtomicBool>,
            after: usize,
            emitted: usize,
            ends: usize,
        }
        impl RowSink for CancelAfter<'_> {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                self.inner.begin(lineage, exact)
            }
            fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
                self.inner.row(group, row)?;
                self.emitted += 1;
                if self.emitted == self.after {
                    self.cancel
                        .store(true, std::sync::atomic::Ordering::Relaxed);
                }
                Ok(())
            }
            fn end(&mut self, group: Group) -> Result<()> {
                self.ends += 1;
                self.inner.end(group)
            }
        }
        for after in [1, 9] {
            let pool = Arc::new(crate::resources::MemoryPool::new(8 * 1024 * 1024));
            let cancel = Arc::new(AtomicBool::new(false));
            let ctx = Context::with_memory_pool(
                &Resources {
                    workers: 4,
                    ..Default::default()
                },
                cancel.clone(),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let directory = ctx.dir.path().to_path_buf();
            let destination = directory.join("unpublished");
            let job = Job {
                output: destination.to_string_lossy().into_owned(),
                ..Default::default()
            };
            let mut tasks = Vec::new();
            for part in 0..3 {
                let mut writer = DatasetWriter::new(&ctx)?;
                let mut parent = writer.begin(vec![json!({"part": part})], true);
                for id in part * 3..part * 3 + 3 {
                    writer.row(
                        &mut parent,
                        &Row {
                            id,
                            ordinal: id % 3,
                            key: Vec::new(),
                            fields: vec![id.to_string()],
                        },
                    )?;
                }
                let metadata = retain_parent(&parent, &ctx)?;
                writer.end(parent.clone())?;
                tasks.push(Task {
                    parent,
                    result: Some(Ok(writer.finish()?)),
                    _metadata: metadata,
                });
            }
            let sibling_paths = std::fs::read_dir(&directory)?
                .map(|entry| entry.map(|entry| entry.path()))
                .collect::<std::io::Result<Vec<_>>>()?;
            assert_eq!(sibling_paths.len(), 6, "three materialized siblings");
            let mut sink = CancelAfter {
                inner: output::PlanWriter::new(&job, None, &ctx)?,
                cancel,
                after,
                emitted: 0,
                ends: 0,
            };
            let error = consume_batch(&mut tasks, &ctx, &mut sink, |_, _| {
                anyhow::bail!("cancellation must not retry serially")
            })
            .unwrap_err();
            assert!(format!("{error:#}").contains("cancelled"));
            assert_eq!(sink.emitted, after);
            assert_eq!(sink.ends, if after == 1 { 0 } else { 3 });
            assert_eq!(sink.inner.groups, if after == 1 { 0 } else { 2 });
            assert_eq!(ctx.diagnostics()["parallel_group_retries"], 0);
            assert!(!destination.exists(), "cancelled native plan published");
            // This is the same error propagation as apply_into -> preparation:
            // do not finish the failed plan or proceed to Prepared::execute.
            drop(sink);
            drop(tasks);
            assert!(sibling_paths.iter().all(|path| !path.exists()));
            assert_eq!(std::fs::read_dir(&directory)?.count(), 0);
            assert_eq!(pool.usage().reserved_bytes, ctx.directory_reserved_bytes());
            eprintln!(
                "replay cancel after row {after}: terminal; siblings removed; directory-only grant"
            );
            drop(ctx);
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert!(!directory.exists());
        }
        Ok(())
    }

    #[test]
    fn replay_endpoint_terminal_errors_precede_denial_without_emission() -> Result<()> {
        for terminal in ["job cancelled", "invalid spool frame"] {
            let ctx = context(4)?;
            let mut sibling = DatasetWriter::new(&ctx)?;
            sibling.end(sibling.begin(vec![json!({"part": 0})], true))?;
            let parent = Group {
                offset: 0,
                rows: 0,
                lineage: Vec::new(),
                exact: true,
            };
            let mut tasks = Vec::new();
            for result in [
                Ok(sibling.finish()?),
                Err(crate::resources::MemoryAdmission::Shared {
                    limit: 1,
                    startup: 2,
                }
                .into()),
                Err(anyhow::anyhow!(terminal)),
            ] {
                tasks.push(Task {
                    parent: parent.clone(),
                    result: Some(result),
                    _metadata: retain_parent(&parent, &ctx)?,
                });
            }
            let paths = std::fs::read_dir(ctx.dir.path())?
                .map(|entry| entry.map(|entry| entry.path()))
                .collect::<std::io::Result<Vec<_>>>()?;
            let mut output = DatasetWriter::new(&ctx)?;
            let error = consume_batch(&mut tasks, &ctx, &mut output, |_, _| {
                anyhow::bail!("terminal error must not retry")
            })
            .unwrap_err();
            assert_eq!(error.to_string(), terminal);
            assert_eq!(ctx.diagnostics()["parallel_group_retries"], 0);
            drop(output);
            drop(tasks);
            assert!(paths.iter().all(|path| !path.exists()));
            assert_eq!(std::fs::read_dir(ctx.dir.path())?.count(), 0);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
        }
        Ok(())
    }

    #[test]
    fn real_shared_competitor_denial_discards_sibling_before_exact_serial_retry() -> Result<()> {
        use std::sync::{mpsc, Mutex};
        use std::time::Duration;

        let pool = Arc::new(crate::resources::MemoryPool::new(16 * 1024 * 1024));
        let resources = Resources {
            memory_mb: 32,
            workers: 2,
            ..Default::default()
        };
        let make_context = || {
            Context::with_memory_pool(
                &resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )
        };
        let mut ctx = make_context()?;
        let competitor_ctx = make_context()?;
        let owned_dirs = [
            ctx.dir.path().to_path_buf(),
            competitor_ctx.dir.path().to_path_buf(),
        ];
        let competitor = Arc::new(Mutex::new(Reservation::new(&competitor_ctx)));
        let job = Job {
            seed: Some("actual-shared-owner".into()),
            ..Default::default()
        };
        let Ingested {
            dataset,
            analysis,
            final_plan,
            consumed: _,
        } = ingest(Box::new(&b"id,text\n"[..]), &job, &ctx)?;
        drop(dataset);
        assert!(final_plan.is_some(), "empty pipeline retains a direct plan");
        let before_plan_drop = pool.usage().reserved_bytes;
        let plan_path_charge = ctx.diagnostics()["temporary_path_reserved_bytes"]
            .as_u64()
            .unwrap();
        assert!(plan_path_charge > 0);
        drop(final_plan);
        let after_plan_drop = pool.usage().reserved_bytes;
        assert_eq!(before_plan_drop - after_plan_drop, plan_path_charge);
        assert_eq!(ctx.diagnostics()["temporary_path_reserved_bytes"], 0);
        eprintln!(
            "ingestion final_plan release: pool {before_plan_drop} -> {after_plan_drop}; actual path charge {plan_path_charge}"
        );
        let mut source = DatasetWriter::new(&ctx)?;
        for part in 0..5 {
            let mut group = source.begin(vec![json!({"step": 0, "part": part + 1})], true);
            for id in part * 3..part * 3 + 3 {
                source.row(
                    &mut group,
                    &Row {
                        id,
                        ordinal: id % 3,
                        key: vec![],
                        fields: vec![id.to_string(), "quoted, \"界\"\ntext".into()],
                    },
                )?;
            }
            source.end(group)?;
        }
        let source = source.finish()?;
        let operation = Operation::Shuffle {
            strategy: Shuffle::Uniform,
        };
        // Measure actual serial admission with the same source, output writer,
        // analysis and both directory owners alive; do not invent a cutoff.
        let mut reference = DatasetWriter::new(&ctx)?;
        let idle = pool.usage().reserved_bytes;
        pool.reset_peak_for_test();
        for parent in source.groups()? {
            apply_parent(
                &source,
                &*parent?,
                &operation,
                1,
                &job,
                &analysis,
                &ctx,
                &mut reference,
                None,
                None,
            )?;
        }
        let serial_extra = pool.usage().peak_reserved_bytes.checked_sub(idle).unwrap();
        let reference = reference.finish()?;
        let expected = snapshot(&reference, &ctx)?;
        drop(reference);
        assert!(serial_extra > 0);

        let mut output = DatasetWriter::new(&ctx)?;
        let original_paths = std::fs::read_dir(ctx.dir.path())?
            .map(|p| p.map(|p| p.path()))
            .collect::<std::io::Result<std::collections::BTreeSet<_>>>()?;
        let first = source.groups()?.next().unwrap()?.offset;
        let (ready_tx, ready_rx) = mpsc::sync_channel(1);
        let ready_rx = Mutex::new(ready_rx);
        let retained_spool = Arc::new(Mutex::new(Vec::new()));
        let serial_calls = Arc::new(Mutex::new(Vec::new()));
        let denied = Arc::new(AtomicBool::new(false));
        let context_view = ctx.clone(); // No hook: avoids a reference cycle.
        let hook_pool = pool.clone();
        let hook_competitor = competitor.clone();
        let hook_paths = retained_spool.clone();
        let hook_serial = serial_calls.clone();
        let hook_denied = denied.clone();
        ctx.group_test_hook = Some(Arc::new(move |offset, event| {
            match (offset == first, event) {
                (false, "before") => {
                    ready_rx
                        .lock()
                        .unwrap()
                        .recv_timeout(Duration::from_secs(5))?;
                    let usage = hook_pool.usage();
                    let bytes = usage
                        .limit_bytes
                        .checked_sub(usage.reserved_bytes + serial_extra)
                        .context("serial boundary exceeds shared ceiling")?;
                    hook_competitor.lock().unwrap().resize(bytes as usize)?;
                    assert!(bytes > 0);
                }
                (true, "materialized") => {
                    let paths = std::fs::read_dir(context_view.dir.path())?
                        .map(|p| p.map(|p| p.path()))
                        .collect::<std::io::Result<Vec<_>>>()?;
                    *hook_paths.lock().unwrap() = paths
                        .into_iter()
                        .filter(|p| !original_paths.contains(p))
                        .collect();
                    assert!(
                        !hook_paths.lock().unwrap().is_empty(),
                        "successful sibling must own real spool files"
                    );
                    ready_tx.send(())?;
                }
                (false, "shared_denied") => {
                    hook_denied.store(true, std::sync::atomic::Ordering::Relaxed);
                }
                (_, "serial") => {
                    assert!(hook_denied.load(std::sync::atomic::Ordering::Relaxed));
                    assert!(hook_competitor.lock().unwrap().bytes() > 0);
                    assert!(
                        hook_paths.lock().unwrap().iter().all(|p| !p.exists()),
                        "sibling spools must be removed before serial retry"
                    );
                    hook_serial.lock().unwrap().push(offset);
                }
                (_, "failed") => anyhow::bail!("unexpected worker failure"),
                (false, "materialized") => {
                    anyhow::bail!("measured boundary did not force actual Shared denial")
                }
                _ => (),
            }
            Ok(())
        }));
        assert!(apply(
            &source,
            &operation,
            1,
            &job,
            &analysis,
            &ctx,
            &mut output,
            None,
            None
        )?);
        ctx.group_test_hook = None;
        let output = output.finish()?;
        assert_eq!(snapshot(&output, &ctx)?, expected);
        let offsets = source
            .groups()?
            .map(|p| Ok(p?.offset))
            .collect::<Result<Vec<_>>>()?;
        assert_eq!(
            *serial_calls.lock().unwrap(),
            offsets,
            "all remaining parents stay serial, once each"
        );
        assert_eq!(ctx.diagnostics()["parallel_group_batches"], 1);
        assert_eq!(ctx.diagnostics()["parallel_groups"], 2);
        assert_eq!(ctx.diagnostics()["parallel_group_retries"], 1);
        assert!(competitor.lock().unwrap().bytes() > 0);
        drop(output);
        drop(source);
        drop(analysis);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        drop(ctx);
        assert_eq!(
            pool.usage().reserved_bytes,
            competitor_ctx.directory_reserved_bytes() + competitor.lock().unwrap().bytes()
        );
        drop(competitor);
        drop(competitor_ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        assert!(owned_dirs.iter().all(|p| !p.exists()));
        Ok(())
    }

    fn context(workers: usize) -> Result<Context> {
        Context::with_memory_pool(
            &Resources {
                memory_mb: 32,
                workers,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )
    }

    fn snapshot(data: &Dataset, ctx: &Context) -> Result<Vec<u8>> {
        let mut bytes = Vec::new();
        for group in data.groups()? {
            let group = group?;
            serde_json::to_writer(&mut bytes, &group)?;
            for row in data.rows(&group, ctx.max_record)? {
                let row = row?;
                write_row(&mut bytes, &row)?;
            }
        }
        Ok(bytes)
    }

    #[test]
    fn prefetch_denial_releases_first_parent_vector_or_retained_batch_before_serial_retry(
    ) -> Result<()> {
        for retain_first in [false, true] {
            let ctx = context(4)?;
            let mut source = DatasetWriter::new(&ctx)?;
            for id in 0..2 {
                let mut group = source.begin(
                    vec![json!({"wide": "x".repeat(100_000), "part": id})],
                    false,
                );
                source.row(
                    &mut group,
                    &Row {
                        id,
                        ordinal: 0,
                        key: vec![],
                        fields: vec![format!("row-{id}")],
                    },
                )?;
                source.end(group)?;
            }
            let source = source.finish()?;
            let expected = snapshot(&source, &ctx)?;
            let mut output = DatasetWriter::new(&ctx)?;
            // Observe the actual decode boundary with the real output writer
            // alive. Wide lineage makes predecode overlap the peak allocation.
            let mut probe = source.groups()?;
            drop(probe.next().unwrap()?);
            drop(probe);
            let serial_peak = ctx.diagnostics()["peak_workspace_reserved_bytes"]
                .as_u64()
                .unwrap() as usize;
            let mut tasks = Vec::new();
            let mut grant = Reservation::new(&ctx);
            grant.reserve_vec(&mut tasks, 4)?;
            let mut parents = source.retryable_groups()?;
            if retain_first {
                let (parent, metadata) = parents.next().unwrap()?.into_parts();
                tasks.push(Task {
                    parent,
                    result: None,
                    _metadata: metadata,
                });
            }
            let mut pressure = Reservation::new(&ctx);
            pressure.resize(ctx.memory / 2 - serial_peak)?;
            let error = parents
                .next()
                .unwrap()
                .err()
                .context("optional owners must deny prefetch")?;
            assert!(error
                .downcast_ref::<crate::resources::MemoryAdmission>()
                .is_some());
            finish_serial_after_prefetch_denial(
                tasks,
                grant,
                parents,
                &ctx,
                &mut output,
                |parent, output| {
                    let mut target = output.begin(parent.lineage.clone(), parent.exact);
                    for row in source.rows(parent, ctx.max_record)? {
                        output.row(&mut target, &*row?)?;
                    }
                    output.end(target)
                },
            )?;
            drop(pressure);
            let output = output.finish()?;
            assert_eq!(snapshot(&output, &ctx)?, expected);
            assert_eq!(ctx.diagnostics()["parallel_group_retries"], 1);
            drop(output);
            drop(source);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"]
                    .as_u64()
                    .unwrap(),
                ctx.directory_reserved_bytes()
            );
        }
        Ok(())
    }

    #[test]
    fn moved_replay_lineage_keeps_charge_through_sink_end_failure() -> Result<()> {
        struct Reject<'a>(&'a Context);
        impl RowSink for Reject<'_> {
            fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
                Group {
                    offset: 0,
                    rows: 0,
                    lineage,
                    exact,
                }
            }
            fn row(&mut self, _: &mut Group, _: &Row) -> Result<()> {
                Ok(())
            }
            fn end(&mut self, group: Group) -> Result<()> {
                let retained = group.json_capacity()? as u64;
                assert!(retained > 100_000);
                assert!(
                    self.0.diagnostics()["workspace_reserved_bytes"]
                        .as_u64()
                        .unwrap()
                        >= retained + 2 * 64 * 1024
                );
                anyhow::bail!("injected sink end failure")
            }
        }
        let ctx = context(4)?;
        let mut writer = DatasetWriter::new(&ctx)?;
        writer.end(writer.begin(vec![json!({"wide": "x".repeat(100_000)})], false))?;
        let source = writer.finish()?;
        let paths = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        assert_eq!(
            replay(&source, &mut Reject(&ctx), &ctx)
                .unwrap_err()
                .to_string(),
            "injected sink end failure"
        );
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap(),
            paths
        );
        drop(source);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap(),
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }

    #[test]
    fn prefetch_serial_retry_checks_cancel_and_returns_second_denial_or_corruption() -> Result<()> {
        use std::cell::Cell;
        for mode in ["cancel", "denial", "corrupt"] {
            let cancel = Arc::new(AtomicBool::new(false));
            let ctx = Context::with_memory_pool(
                &Resources {
                    memory_mb: 32,
                    workers: 4,
                    ..Default::default()
                },
                cancel.clone(),
                Arc::new(|_| {}),
                Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
            )?;
            let calls = Cell::new(0);
            let parents = std::iter::from_fn(|| {
                calls.set(calls.get() + 1);
                Some(if mode == "denial" {
                    Err(crate::resources::MemoryAdmission::Local.into())
                } else {
                    Err(anyhow::anyhow!("corrupt pending catalog"))
                })
            });
            let mut tasks = Vec::new();
            let mut grant = Reservation::new(&ctx);
            grant.reserve_vec(&mut tasks, 4)?;
            let mut output = DatasetWriter::new(&ctx)?;
            cancel.store(mode == "cancel", std::sync::atomic::Ordering::Relaxed);
            let error = finish_serial_after_prefetch_denial(
                tasks,
                grant,
                parents,
                &ctx,
                &mut output,
                |_, _| -> Result<()> { panic!("terminal error must not emit") },
            )
            .unwrap_err();
            assert_eq!(calls.get(), usize::from(mode != "cancel"));
            assert_eq!(
                error
                    .downcast_ref::<crate::resources::MemoryAdmission>()
                    .is_some(),
                mode == "denial"
            );
            assert_eq!(error.to_string().contains("cancelled"), mode == "cancel");
            drop(output);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
        }
        Ok(())
    }

    #[test]
    #[cfg(any(target_os = "linux", windows))]
    fn prefetch_serial_retry_checks_failed_cleanup_before_pending_decode() -> Result<()> {
        let ctx = context(4)?;
        let mut tasks = Vec::new();
        let mut grant = Reservation::new(&ctx);
        grant.reserve_vec(&mut tasks, 4)?;
        let mut output = DatasetWriter::new(&ctx)?;
        ctx.force_cleanup_error_for_test()?;
        let parents = std::iter::from_fn(|| -> Option<Result<ChargedJson<Group>>> {
            panic!("failed cleanup must prevent pending decode")
        });
        let error = finish_serial_after_prefetch_denial(
            tasks,
            grant,
            parents,
            &ctx,
            &mut output,
            |_, _| -> Result<()> { panic!("failed cleanup must prevent output") },
        )
        .unwrap_err();
        assert!(error.to_string().contains("temporary cleanup failed"));
        drop(output);
        // The failed orphan/path remains charged until its context is released.
        assert!(
            ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap()
                > 0
        );
        Ok(())
    }

    #[test]
    fn ordered_batches_match_serial_with_remainders_wide_rows_and_balanced_fusion() -> Result<()> {
        let ctx = context(4)?;
        let job = Job {
            seed: Some("parallel-groups".into()),
            operations: vec![Operation::Balanced { files: 5 }],
            ..Default::default()
        };
        let mut text = "id,text\n".to_owned();
        for id in 0..503 {
            text.push_str(&format!(
                "{id},\"{},\"\"quoted\"\"\nnext\"\n",
                if id == 250 {
                    "界".repeat(100_000)
                } else {
                    "duplicate".into()
                }
            ));
        }
        let input = ingest(Box::new(text.as_bytes()), &job, &ctx)?;
        let grouped = super::super::apply(
            &input.dataset,
            &job.operations[0],
            0,
            &job,
            &input.analysis,
            &ctx,
        )?;
        let operation = Operation::Shuffle {
            strategy: Shuffle::Uniform,
        };
        let baseline = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        for balanced in [None, Some((2, 2))] {
            let mut serial = DatasetWriter::new(&ctx)?;
            for parent in grouped.groups()? {
                apply_parent(
                    &grouped,
                    &*parent?,
                    &operation,
                    1,
                    &job,
                    &input.analysis,
                    &ctx,
                    &mut serial,
                    None,
                    balanced,
                )?;
            }
            let serial = serial.finish()?;
            let expected = snapshot(&serial, &ctx)?;
            drop(serial);
            let mut parallel = DatasetWriter::new(&ctx)?;
            assert!(apply(
                &grouped,
                &operation,
                1,
                &job,
                &input.analysis,
                &ctx,
                &mut parallel,
                None,
                balanced
            )?);
            let parallel = parallel.finish()?;
            assert_eq!(snapshot(&parallel, &ctx)?, expected);
            drop(parallel);
            assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        }
        assert_eq!(ctx.diagnostics()["parallel_groups"], 8);
        assert_eq!(ctx.diagnostics()["parallel_group_batches"], 2);
        assert_eq!(ctx.diagnostics()["parallel_group_retries"], 0);
        drop(grouped);
        drop(input);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn admission_failure_drops_successful_siblings_before_retry_and_terminal_errors_win(
    ) -> Result<()> {
        let ctx = context(4)?;
        let parent = Group {
            offset: 0,
            rows: 0,
            lineage: vec![json!({"part": 1})],
            exact: true,
        };
        let make = |result| -> Result<Task> {
            Ok(Task {
                parent: parent.clone(),
                result: Some(result),
                _metadata: retain_parent(&parent, &ctx)?,
            })
        };
        let spool = || -> Result<Dataset> {
            let mut writer = DatasetWriter::new(&ctx)?;
            writer.end(writer.begin(parent.lineage.clone(), true))?;
            writer.finish()
        };
        let mut tasks = vec![
            make(Ok(spool()?))?,
            make(Err(crate::resources::MemoryAdmission::Local.into()))?,
            make(Ok(spool()?))?,
        ];
        assert!(ctx.used() > 0);
        assert!(batch_failed(&mut tasks, &ctx)?);
        assert!(tasks.iter().all(|t| t.result.is_none()));
        assert_eq!(ctx.used(), 0, "all sibling spools discarded");
        drop(tasks);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        for message in ["job cancelled", "invalid spool frame"] {
            let mut tasks = vec![
                make(Err(crate::resources::MemoryAdmission::Local.into()))?,
                make(Err(anyhow::anyhow!(message)))?,
            ];
            assert_eq!(
                batch_failed(&mut tasks, &ctx).unwrap_err().to_string(),
                message
            );
        }
        assert_eq!(ctx.diagnostics()["parallel_group_retries"], 1);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }

    #[test]
    fn batch_metadata_shared_capacity_edges_and_denial_rollback() -> Result<()> {
        let parent = Group {
            offset: 0,
            rows: 0,
            lineage: vec![json!({"long": "界".repeat(100), "nested": [1, {}, "x"]})],
            exact: false,
        };
        let ctx = context(1)?;
        let bytes = retain_parent(&parent, &ctx)?.bytes();
        let directory = ctx.directory_reserved_bytes();
        for delta in [-1isize, 0, 1] {
            let pool = Arc::new(crate::resources::MemoryPool::new(
                (bytes + directory)
                    .checked_add_signed(delta as i64)
                    .unwrap(),
            ));
            let ctx = Context::with_memory_pool(
                &Resources::default(),
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            assert_eq!(ctx.directory_reserved_bytes(), directory);
            let result = retain_parent(&parent, &ctx);
            assert_eq!(result.is_ok(), delta >= 0);
            assert_eq!(
                pool.usage().reserved_bytes,
                directory + if delta >= 0 { bytes } else { 0 }
            );
            drop(result);
            assert_eq!(pool.usage().reserved_bytes, directory);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
            drop(ctx);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn failed_batch_serial_replay_preserves_exact_rows_order_and_lineage() -> Result<()> {
        let ctx = context(4)?;
        let job = Job {
            seed: Some("retry-groups".into()),
            operations: vec![Operation::Balanced { files: 3 }],
            ..Default::default()
        };
        let input = ingest(Box::new(&b"id,text\n0,duplicate\n1,duplicate\n2,duplicate\n3,duplicate\n4,duplicate\n5,duplicate\n"[..]), &job, &ctx)?;
        let grouped = super::super::apply(
            &input.dataset,
            &job.operations[0],
            0,
            &job,
            &input.analysis,
            &ctx,
        )?;
        let operation = Operation::Shuffle {
            strategy: Shuffle::Uniform,
        };
        let process = |parent: &Group, writer: &mut DatasetWriter| {
            apply_parent(
                &grouped,
                parent,
                &operation,
                1,
                &job,
                &input.analysis,
                &ctx,
                writer,
                None,
                None,
            )
        };
        let mut tasks = Vec::new();
        let mut reference = DatasetWriter::new(&ctx)?;
        for (index, parent) in grouped.groups()?.enumerate() {
            let parent = parent?;
            process(&parent, &mut reference)?;
            let result = if index == 1 {
                Err(crate::resources::MemoryAdmission::Shared {
                    limit: 1,
                    startup: 2,
                }
                .into())
            } else {
                let mut writer = DatasetWriter::new(&ctx)?;
                process(&parent, &mut writer)?;
                Ok(writer.finish()?)
            };
            let (parent, metadata) = parent.into_parts();
            tasks.push(Task {
                _metadata: metadata,
                parent,
                result: Some(result),
            });
        }
        let reference = reference.finish()?;
        let mut retry = DatasetWriter::new(&ctx)?;
        assert!(consume_batch(&mut tasks, &ctx, &mut retry, process)?);
        let retry = retry.finish()?;
        assert_eq!(snapshot(&retry, &ctx)?, snapshot(&reference, &ctx)?);
        let ids = retry
            .groups()?
            .map(|g| {
                retry
                    .rows(&*g?, ctx.max_record)?
                    .map(|r| Ok(r?.id))
                    .collect::<Result<Vec<_>>>()
            })
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .flatten()
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(ids, (0..6).collect());
        drop(tasks);
        drop(retry);
        drop(reference);
        drop(grouped);
        drop(input);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn worker_corruption_cancellation_and_oversized_optional_rows_release_spools() -> Result<()> {
        let cancel = Arc::new(AtomicBool::new(false));
        let ctx = Context::with_memory_pool(
            &Resources {
                memory_mb: 32,
                workers: 4,
                ..Default::default()
            },
            cancel.clone(),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )?;
        let job = Job {
            seed: Some("worker-failure".into()),
            ..Default::default()
        };
        let parent = Group {
            offset: 0,
            rows: 1,
            lineage: vec![],
            exact: false,
        };
        let mut writer = DatasetWriter::new(&ctx)?;
        writer.end(parent.clone())?; // Catalog promises one absent frame.
        let corrupt = writer.finish()?;
        let baseline = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        let error = evaluate(&corrupt, &parent, 0, &job, &ctx, 4, None)
            .err()
            .unwrap();
        assert!(error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_none());
        assert!(format!("{error:#}").contains("truncated"));
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        cancel.store(true, std::sync::atomic::Ordering::Relaxed);
        let error = evaluate(&corrupt, &parent, 0, &job, &ctx, 4, None)
            .err()
            .unwrap();
        assert!(format!("{error:#}").contains("cancelled"));
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        cancel.store(false, std::sync::atomic::Ordering::Relaxed);
        drop(corrupt);

        let mut writer = DatasetWriter::new(&ctx)?;
        let mut group = writer.begin(vec![], false);
        writer.row(
            &mut group,
            &Row {
                id: 0,
                ordinal: 0,
                key: vec![],
                fields: vec!["x".repeat(3 * 1024 * 1024)],
            },
        )?;
        writer.end(group)?;
        let data = writer.finish()?;
        let parent = data.groups()?.next().unwrap()?;
        let baseline = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        let error = evaluate(&data, &parent, 0, &job, &ctx, 4, None)
            .err()
            .unwrap();
        assert!(error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_some());
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        let operation = Operation::Shuffle {
            strategy: Shuffle::Uniform,
        };
        // Same row succeeds under the original serial sort grant.
        let analysis = ingest(Box::new(&b"id,text\n"[..]), &job, &ctx)?.analysis;
        let mut output = DatasetWriter::new(&ctx)?;
        apply_parent(
            &data,
            &parent,
            &operation,
            0,
            &job,
            &analysis,
            &ctx,
            &mut output,
            None,
            None,
        )?;
        let output = output.finish()?;
        assert_eq!(
            output
                .rows(&*output.groups()?.next().unwrap()?, ctx.max_record)?
                .next()
                .unwrap()?
                .fields[0]
                .len(),
            3 * 1024 * 1024
        );
        drop(output);
        drop(data);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
                + analysis
                    .header
                    .as_ref()
                    .map_or(0, |header| header.reserved_bytes())
                + analysis.preview.reserved_bytes()
                + analysis.warnings.reserved_bytes()
                + analysis.timings.reserved_bytes()
                + analysis.diagnostics.reserved_bytes()
                + analysis.text_reserved_bytes()
                + analysis.stages.reserved_bytes()
                + analysis.column_values.reserved_bytes()
        );
        drop(analysis);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        assert_eq!(ctx.used(), 0);
        Ok(())
    }
}
