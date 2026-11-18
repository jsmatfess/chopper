use super::*;

#[derive(Clone, Copy, Debug)]
enum Kind {
    #[cfg(feature = "experimental-constant-partition")]
    Constant,
    #[cfg(feature = "experimental-consecutive-partitions")]
    Consecutive,
    #[cfg(feature = "experimental-partition-balanced")]
    PartitionBalanced,
    #[cfg(feature = "experimental-streaming-chain")]
    Streaming,
}
impl Kind {
    fn operations(self) -> Vec<Operation> {
        let partition = || Operation::Partition {
            columns: vec![Column::Index(1)],
        };
        let allocations = || {
            vec![
                Allocation {
                    name: "界\"keep".into(),
                    percent: "40".into(),
                },
                Allocation {
                    name: "zero".into(),
                    percent: "0".into(),
                },
                Allocation {
                    name: "é\nother".into(),
                    percent: "60".into(),
                },
            ]
        };
        // Some feature subsets do not need either helper.
        let _ = (&partition, &allocations);
        match self {
            #[cfg(feature = "experimental-constant-partition")]
            Self::Constant => vec![partition(), partition()],
            #[cfg(feature = "experimental-consecutive-partitions")]
            Self::Consecutive => vec![partition(), partition()],
            #[cfg(feature = "experimental-partition-balanced")]
            Self::PartitionBalanced => vec![
                partition(),
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
                Operation::Balanced { files: 2 },
            ],
            #[cfg(feature = "experimental-streaming-chain")]
            Self::Streaming => vec![
                Operation::Interleaved { files: 2 },
                partition(),
                Operation::AssignProbabilistic {
                    groups: allocations(),
                    strata: Vec::new(),
                },
            ],
        }
    }
    fn start(self) -> usize {
        match self {
            #[cfg(feature = "experimental-constant-partition")]
            Self::Constant => 1,
            #[allow(unreachable_patterns)]
            _ => 0,
        }
    }
    fn emit(
        self,
        source: &Dataset,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        sink: &mut impl RowSink,
    ) -> Result<()> {
        let _ = analysis;
        match self {
            #[cfg(feature = "experimental-constant-partition")]
            Self::Constant => {
                let columns = [1];
                let plan = constant_partition::Plan::new(&columns, 1, job, analysis, ctx)?
                    .context("missing constant plan")?;
                for parent in source.groups()? {
                    let parent = parent?;
                    let owner = plan
                        .child(&parent, &columns, 1, job, analysis, ctx)?
                        .context("constant child denied")?;
                    constant_partition::copy(source, owner, ctx, sink)?;
                }
                Ok(())
            }
            #[cfg(feature = "experimental-consecutive-partitions")]
            Self::Consecutive => {
                consecutive_partitions::Plan::at(job, 0).unwrap().apply(
                    source,
                    analysis.header.as_deref(),
                    analysis.columns,
                    ctx,
                    sink,
                )?;
                Ok(())
            }
            #[cfg(feature = "experimental-partition-balanced")]
            Self::PartitionBalanced => {
                ensure!(
                    partition_balanced::Plan::at(job, 0)
                        .unwrap()
                        .apply(source, job, analysis, ctx, sink)?
                        .is_some(),
                    "bounded partition plan unexpectedly declined"
                );
                Ok(())
            }
            #[cfg(feature = "experimental-streaming-chain")]
            Self::Streaming => {
                streaming_chain::Plan::at(job, 0)
                    .unwrap()
                    .apply(source, job, analysis, ctx, sink)?;
                Ok(())
            }
        }
    }
}

struct Sink<'a> {
    pool: &'a MemoryPool,
    baseline: u64,
    cancel: &'a AtomicBool,
    mode: &'static str,
    ids: Vec<u64>,
    current: Vec<serde_json::Value>,
    completed: Vec<serde_json::Value>,
}
impl RowSink for Sink<'_> {
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        assert!(
            self.pool.usage().reserved_bytes
                >= self.baseline + lineage.json_capacity().unwrap() as u64
        );
        Group {
            offset: 0,
            rows: 0,
            lineage,
            exact,
        }
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        ensure!(
            self.pool.usage().reserved_bytes >= self.baseline + group.json_capacity()? as u64,
            "experimental row lost metadata admission"
        );
        if self.mode == "row_error" {
            anyhow::bail!("injected experimental row failure");
        }
        self.ids.push(row.id);
        self.current.push(json!([row.id, row.ordinal, row.fields]));
        group.rows += 1;
        if self.mode.ends_with("denial_first")
            || (self.mode.ends_with("denial_last") && self.ids.len() == 8)
        {
            return Err(if self.mode.starts_with("local") {
                crate::resources::MemoryAdmission::Local
            } else {
                crate::resources::MemoryAdmission::Shared {
                    limit: 64 * 1024 * 1024,
                    startup: 64 * 1024 * 1024,
                }
            }
            .into());
        }
        if self.mode == "cancel_first" || (self.mode == "cancel_last" && self.ids.len() == 8) {
            self.cancel.store(true, Ordering::Relaxed);
        }
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        ensure!(
            self.pool.usage().reserved_bytes >= self.baseline + group.json_capacity()? as u64,
            "experimental catalog lost metadata admission"
        );
        if self.mode == "end_error" {
            anyhow::bail!("injected experimental catalog failure");
        }
        self.completed.push(json!([
            group.lineage,
            group.exact,
            std::mem::take(&mut self.current)
        ]));
        Ok(())
    }
}
fn snapshot(data: &Dataset, ctx: &Context) -> Result<Vec<serde_json::Value>> {
    let mut result = Vec::new();
    for group in data.groups()? {
        let group = group?;
        let rows = data
            .rows(&group, ctx.max_record)?
            .map(|row| {
                let row = row?;
                Ok(json!([row.id, row.ordinal, row.fields]))
            })
            .collect::<Result<Vec<_>>>()?;
        result.push(json!([group.lineage, group.exact, rows]));
    }
    Ok(result)
}

pub(super) fn run(path: &std::path::Path) -> Result<serde_json::Value> {
    let scenarios = [
        #[cfg(feature = "experimental-constant-partition")]
        Kind::Constant,
        #[cfg(feature = "experimental-consecutive-partitions")]
        Kind::Consecutive,
        #[cfg(feature = "experimental-partition-balanced")]
        Kind::PartitionBalanced,
        #[cfg(feature = "experimental-streaming-chain")]
        Kind::Streaming,
    ];
    let mut reports = Vec::new();
    for scenario in scenarios {
        let job = Job {
            random_seed: Some("experimental-child-contract".into()),
            operations: scenario.operations(),
            resources: Resources {
                workers: 1,
                temp_dir: Some(path.to_string_lossy().into_owned()),
                ..Default::default()
            },
            ..Default::default()
        };
        let cancel = Arc::new(AtomicBool::new(false));
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let ctx = Context::with_memory_pool(
            &job.resources,
            cancel.clone(),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let input = "id,text\n0,界\n1,é\n2,界\n3,é\n4,界\n5,é\n6,界\n7,é\n";
        // Disabling multi-stage fusion still permits leading operations during
        // ingestion. Materialize an unprocessed root explicitly, as the native
        // rewrite fixtures do, before applying either comparison graph.
        let mut raw_job = job.clone();
        raw_job.operations = vec![Operation::Balanced { files: 1 }];
        let raw = ingest_options(&mut input.as_bytes(), &raw_job, &ctx, false, false, false)?;
        ensure!(
            raw.consumed == 0
                && raw.dataset.groups == 1
                && raw.dataset.groups()?.next().unwrap()?.lineage.is_empty(),
            "experimental fixture did not retain an unprocessed root"
        );
        let initial = if scenario.start() == 1 {
            Some(apply(
                &raw.dataset,
                &job.operations[0],
                0,
                &job,
                &raw.analysis,
                &ctx,
            )?)
        } else {
            None
        };
        let source = initial.as_ref().unwrap_or(&raw.dataset);
        let mut serial = None;

        for step in scenario.start()..job.operations.len() {
            serial = Some(apply(
                serial.as_ref().unwrap_or(source),
                &job.operations[step],
                step,
                &job,
                &raw.analysis,
                &ctx,
            )?);
        }

        let expected = serial
            .as_ref()
            .map(|data| snapshot(data, &ctx))
            .transpose()?;
        drop(serial);
        let baseline = pool.usage().reserved_bytes;
        let mut first: Option<Vec<serde_json::Value>> = None;
        for mode in [
            "success",
            "row_error",
            "end_error",
            "local_denial_first",
            "local_denial_last",
            "shared_denial_first",
            "shared_denial_last",
            "cancel_first",
            "cancel_last",
            "retry",
        ] {
            let mut sink = Sink {
                pool: &pool,
                baseline,
                cancel: &cancel,
                mode,
                ids: Vec::new(),
                current: Vec::new(),
                completed: Vec::new(),
            };
            let result = scenario.emit(source, &job, &raw.analysis, &ctx, &mut sink);
            ensure!(
                result.is_ok() == matches!(mode, "success" | "retry"),
                "{scenario:?}/{mode}: {result:?}"
            );
            if mode.contains("denial") {
                ensure!(
                    result
                        .as_ref()
                        .unwrap_err()
                        .downcast_ref::<crate::resources::MemoryAdmission>()
                        .is_some(),
                    "emission denial lost its type"
                );
                ensure!(
                    sink.ids.len() == if mode.ends_with("first") { 1 } else { 8 },
                    "emission replayed rows after denial"
                );
                ensure!(
                    ctx.diagnostics()["streaming_chain_retries"] == 0,
                    "emission denial retried"
                );
            }
            if matches!(mode, "cancel_first" | "cancel_last") {
                ensure!(
                    cancel.load(Ordering::Relaxed)
                        && format!("{:#}", result.as_ref().unwrap_err()).contains("cancel"),
                    "experimental cancellation fixture did not reach its checkpoint"
                );
                ensure!(
                    sink.completed.len() < first.as_ref().unwrap().len(),
                    "cancelled final child completed"
                );
            }
            if result.is_ok() {
                let mut ids = sink.ids.clone();
                ids.sort_unstable();
                ensure!(
                    ids == (0..8).collect::<Vec<_>>(),
                    "experimental child lost IDs"
                );

                if let Some(expected) = &expected {
                    ensure!(
                        &sink.completed == expected,
                        "{scenario:?} differs from original stages"
                    );
                }
                if let Some(first) = &first {
                    ensure!(
                        &sink.completed == first,
                        "experimental retry changed output"
                    );
                } else {
                    first = Some(sink.completed.clone());
                }
            }
            cancel.store(false, Ordering::Relaxed);
            ensure!(
                pool.usage().reserved_bytes == baseline,
                "{scenario:?}/{mode} leaked"
            );
        }
        let complete_group_rows = first
            .as_ref()
            .unwrap()
            .iter()
            .map(|group| group[2].as_array().unwrap().len())
            .collect::<Vec<_>>();
        reports.push(json!({"scenario":format!("{scenario:?}"),"original_stage_parity":true,"complete_group_rows":complete_group_rows,
            "first_and_last_local_shared_emission_denial":true,"row_and_catalog_failure_cleanup":true,"first_and_last_row_cancellation_cleanup":true,"exact_retry":true}));
        drop(initial);
        drop(raw);
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "experimental context leaked"
        );
    }
    Ok(
        json!({"cases":reports,"weighted_allocations":["40","0","60"],"unprocessed_root_verified":true,"final_reserved_bytes":0}),
    )
}
