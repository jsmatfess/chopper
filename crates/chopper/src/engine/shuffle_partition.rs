//! Exact v1 rewrite: partition tuples precede the original parent shuffle keys.
//! Physical ordinals are normalized within each resulting parent. Every current
//! consumer uses only their relative order; random streams use stable source IDs.
use super::*;
#[cfg(feature = "experimental-shuffle-partition")]
use crate::storage::decision_audit::{DecisionRecord, Denial, Outcome, Phase};

pub(super) const ENABLED: bool = true;

#[derive(Clone, Copy)]
pub(super) struct Plan<'a> {
    pub columns: &'a [Column],
    pub partition_step: usize,
    shuffle_step: usize,
}

/// Declaration order keeps the column allocation alive only while its charge
/// is live. Sorter growth continues to use the existing quarter-job ceiling.
struct Admitted<'a> {
    plan: Plan<'a>,
    parent: &'a Group,
    columns: Vec<usize>,
    _columns_reservation: Reservation,
}

impl<'a> Admitted<'a> {
    fn new(plan: Plan<'a>, parent: &'a Group, analysis: &Analysis, ctx: &Context) -> Result<Self> {
        let mut reservation = Reservation::new(ctx);
        let columns = plan.resolve(
            analysis.header.as_deref(),
            analysis.columns,
            &mut reservation,
        )?;
        Ok(Admitted {
            plan,
            parent,
            columns,
            _columns_reservation: reservation,
        })
    }
}

impl Admitted<'_> {
    /// No sink is touched while preparing. Typed admission denial can therefore
    /// discard this attempt and replay the retained source with original domains.
    fn prepare(
        self,
        data: &Dataset,
        job: &Job,
        ctx: &Context,
        #[cfg(feature = "experimental-shuffle-partition")] record: &mut DecisionRecord,
    ) -> Result<PreparedParent> {
        let Self {
            plan,
            parent,
            columns,
            _columns_reservation,
        } = self;
        let mut keys = PartitionKeys {
            #[cfg(feature = "experimental-constant-partition")]
            key_columns: None,
            parent,
            columns,
            step: plan.partition_step,
            shuffle: Some(plan.random(job.random_seed.as_deref().unwrap(), parent)?),
            domains: DomainCache::new(ctx),
        };
        let mut sorter = Sorter::new(ctx, SortOrder::GroupRandom);
        for row in data.packed_rows(parent, ctx.max_record)? {
            ctx.check()?;
            let mut row = row?;
            #[cfg(feature = "experimental-shuffle-partition")]
            record.shape.decoded(&row);
            let key = keys.key(row.id, row.fields(), ctx, &mut sorter)?;
            let capacity = key.install(&mut row, &mut sorter)?;
            #[cfg(feature = "experimental-shuffle-partition")]
            record.shape.keyed(&row);
            sorter.push_compact(row, capacity)?;
        }
        Ok(PreparedParent {
            rows: sorter.finish()?,
            columns: keys.columns,
            _columns_reservation,
        })
    }
}

struct PreparedParent {
    rows: SortedRows,
    columns: Vec<usize>,
    _columns_reservation: Reservation,
}

#[cfg(all(
    any(test, feature = "resource-contract-tests"),
    feature = "experimental-shuffle-partition"
))]
pub(super) mod resource_contracts;

#[cfg(all(test, feature = "experimental-shuffle-partition"))]
mod tests {
    use super::*;

    use resource_contracts::{serial, shuffle, snapshot};

    fn context() -> Result<Context> {
        Context::with_memory_pool(
            &Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 2 * 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )
    }

    #[test]
    fn eligibility_is_adjacent_uniform_only_and_keeps_original_indices() -> Result<()> {
        let partition = Operation::Partition {
            columns: vec![Column::Index(0)],
        };
        for strategy in [Shuffle::Uniform, Shuffle::Auto, Shuffle::FisherYates] {
            let job = Job {
                operations: vec![Operation::Shuffle { strategy }, partition.clone()],
                ..Default::default()
            };
            assert_eq!(
                Plan::at(&job, 0).is_some(),
                matches!(strategy, Shuffle::Uniform | Shuffle::Auto)
            );
        }
        for between in [
            Operation::Balanced { files: 2 },
            Operation::Interleaved { files: 2 },
            Operation::Assign {
                groups: vec![],
                strata: vec![],
            },
        ] {
            let job = Job {
                operations: vec![shuffle(), between, partition.clone()],
                ..Default::default()
            };
            assert!(Plan::at(&job, 0).is_none());
        }
        let job = Job {
            operations: vec![shuffle(), shuffle(), partition],
            ..Default::default()
        };
        assert!(Plan::at(&job, 0).is_none());
        let plan = Plan::at(&job, 1).unwrap();
        assert_eq!((plan.shuffle_step, plan.partition_step), (1, 2));
        assert!(Plan::at(&job, 2).is_none());
        Ok(())
    }

    #[test]
    fn forced_collisions_match_global_shuffle_then_stable_partition_through_hierarchy() -> Result<()>
    {
        for budget in [4096, 32 * 1024 * 1024] {
            let mut ctx = context()?;
            ctx.memory = budget; // Force many tiny runs without changing the shared ledger.
            let parent = Group {
                offset: 0,
                rows: 333,
                lineage: vec![json!({"operation":0,"part":2})],
                exact: false,
            };
            let domain = random::json_domain("forced-v1", 3, &parent.lineage)?;
            let mut global = Sorter::new(&ctx, SortOrder::Random(domain));
            let mut fused = Sorter::new(&ctx, SortOrder::GroupRandom);
            let mut keys = PartitionKeys {
                #[cfg(feature = "experimental-constant-partition")]
                key_columns: None,
                parent: &parent,
                columns: vec![0, 1],
                step: 4,
                shuffle: Some(PartitionRandom::Before(domain)),
                domains: DomainCache::new(&ctx),
            };
            for id in (0..333).rev() {
                let fields = vec![
                    format!("key-{}\0界", id % 7),
                    format!("{}\n\"", id % 3),
                    "duplicate".into(),
                ];
                let row = Row {
                    id,
                    ordinal: 1000 - id,
                    key: vec![0; 16],
                    fields,
                };
                let mut packed = PackedRow::new(row.clone())?;
                let mut key = keys.key(id, packed.fields(), &ctx, &mut fused)?;
                let end = key.bytes.len() - 32;
                key.bytes[end - 16..end].fill(0);
                let capacity = key.install(&mut packed, &mut fused)?;
                fused.push_compact(packed, capacity)?;
                global.push(row)?;
            }
            let mut shuffled = DatasetWriter::new(&ctx)?;
            let mut group = shuffled.begin(parent.lineage.clone(), false);
            for row in global.finish()? {
                let mut row = (*row?).clone();
                row.ordinal = group.rows;
                row.key.clear();
                shuffled.row(&mut group, &row)?;
            }
            shuffled.end(group)?;
            let shuffled = shuffled.finish()?;
            let shuffled_parent = shuffled.groups()?.next().unwrap()?;
            let mut expected = DatasetWriter::new(&ctx)?;
            partition(
                &shuffled,
                &shuffled_parent,
                &[0, 1],
                4,
                &mut expected,
                &ctx,
                None,
                #[cfg(feature = "experimental-constant-partition")]
                None,
            )?;
            let expected = expected.finish()?;
            let mut actual = DatasetWriter::new(&ctx)?;
            emit_partition(
                fused.finish()?,
                &parent,
                &[0, 1],
                4,
                true,
                &mut actual,
                &ctx,
            )?;
            let actual = actual.finish()?;
            assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
            if budget == 4096 {
                assert!(ctx.diagnostics()["merge_operations"].as_u64().unwrap() > 2);
            }
            drop(actual);
            drop(expected);
            drop(shuffled);
            drop(keys);
            let retained_parent = shuffled_parent.json_capacity()? as u64;
            assert!(retained_parent > 0);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                retained_parent + ctx.directory_reserved_bytes(),
                "decoded parent outlives its dataset and catalog reader"
            );
            drop(shuffled_parent);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn multiple_parents_and_downstream_operations_match_original_encounter_order() -> Result<()> {
        let ctx = context()?;
        let job = Job {
            random_seed: Some("parents-v1".into()),
            operations: vec![
                Operation::Balanced { files: 2 },
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
            ],
            ..Default::default()
        };
        let text = format!(
            "id,key,text\n{}",
            (0..60)
                .map(|id| format!("{id},{},\"quoted,\"\"界\"\"\ntext\"\n", id % 3))
                .collect::<String>()
        );
        let ingested = ingest(Box::new(text.as_bytes()), &job, &ctx)?;
        let parents = serial(
            &ingested.dataset,
            &job.operations[0],
            0,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let shuffled = serial(
            &parents,
            &job.operations[1],
            1,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let expected = serial(
            &shuffled,
            &job.operations[2],
            2,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let mut actual = DatasetWriter::new(&ctx)?;
        Plan::at(&job, 1)
            .unwrap()
            .apply(&parents, &job, &ingested.analysis, &ctx, &mut actual)?;
        let actual = actual.finish()?;
        assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
        let allocation = vec![
            Allocation {
                name: "a".into(),
                percent: "50".into(),
            },
            Allocation {
                name: "b".into(),
                percent: "50".into(),
            },
        ];
        for operation in [
            shuffle(),
            Operation::Balanced { files: 2 },
            Operation::Interleaved { files: 2 },
            Operation::Partition {
                columns: vec![Column::Index(0)],
            },
            Operation::Assign {
                groups: allocation.clone(),
                strata: vec![Column::Index(1)],
            },
            Operation::AssignProbabilistic {
                groups: allocation,
                strata: vec![],
            },
        ] {
            let a = serial(&actual, &operation, 3, &job, &ingested.analysis, &ctx)?;
            let b = serial(&expected, &operation, 3, &job, &ingested.analysis, &ctx)?;
            assert_eq!(snapshot(&a, &ctx)?, snapshot(&b, &ctx)?);
        }
        drop(actual);
        drop(expected);
        drop(shuffled);
        drop(parents);
        drop(ingested);
        let diagnostics = ctx.diagnostics();
        let audit = &diagnostics["shuffle_partition_decisions"];
        assert_eq!(audit["completed_attempts"], 2);
        assert_eq!(audit["records"][0]["parent_ordinal"], 0);
        assert_eq!(audit["records"][1]["parent_ordinal"], 1);
        assert_eq!(audit["records"][1]["observation_complete"], true);
        assert_eq!(audit["records"][1]["outcome"], "fused_committed");
        assert_eq!(
            diagnostics["workspace_reserved_bytes"],
            audit["reserved_bytes"].as_u64().unwrap() + ctx.directory_reserved_bytes()
        );
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn bounded_decisions_observe_late_wide_rows_and_match_original_stages() -> Result<()> {
        let ctx = context()?;
        let job = Job {
            random_seed: Some("bounded-observation-v1".into()),
            operations: vec![
                Operation::Balanced { files: 18 },
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(1)],
                },
            ],
            ..Default::default()
        };
        // The final row of the first parent defeats a narrow-prefix estimate.
        let mut text = "id,key,text\n".to_owned();
        for id in 0..54 {
            text.push_str(&format!(
                "{id},{},{}\n",
                id % 2,
                if id == 2 {
                    "w".repeat(100_000)
                } else {
                    "short".into()
                }
            ));
        }
        let ingested = ingest(Box::new(text.as_bytes()), &job, &ctx)?;
        let parents = serial(
            &ingested.dataset,
            &job.operations[0],
            0,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let shuffled = serial(
            &parents,
            &job.operations[1],
            1,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let expected = serial(
            &shuffled,
            &job.operations[2],
            2,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let mut output = DatasetWriter::new(&ctx)?;
        Plan::at(&job, 1)
            .unwrap()
            .apply(&parents, &job, &ingested.analysis, &ctx, &mut output)?;
        let actual = output.finish()?;
        assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
        let diagnostics = ctx.diagnostics();
        let audit = &diagnostics["shuffle_partition_decisions"];
        assert_eq!(audit["completed_attempts"], 18);
        assert_eq!(audit["omitted_attempts"], 2);
        assert_eq!(audit["records"].as_array().unwrap().len(), 16);
        let first = &audit["records"][0];
        assert_eq!(first["shuffle_step"], 1);
        assert_eq!(first["partition_step"], 2);
        assert_eq!(first["parent_rows"], 3);
        assert_eq!(first["shape"]["rows_decoded"], 3);
        assert_eq!(first["shape"]["rows_keyed"], 3);
        assert_eq!(first["shape"]["maximum_payload_bytes"], 100_002);
        assert!(
            first["shape"]["maximum_row_heap_capacity_bytes"]
                .as_u64()
                .unwrap()
                >= 100_002
        );
        assert_eq!(first["observation_complete"], true);
        assert_eq!(first["key_observation_complete"], true);
        assert_eq!(first["outcome"], "fused_committed");
        assert_eq!(first["context_counter_delta"]["resident_sorts"], 1);
        assert!(audit["selector"].is_null());
        assert!(audit["calibration"].is_null());
        Ok(())
    }

    #[test]
    fn denied_optional_audit_does_not_prevent_exact_execution_after_owner_release() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = Context::with_memory_pool(
            &Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        // Arrange a failed optional audit grant while a separate retained owner
        // holds the shared ledger. Its release precedes the real execution.
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(64 * 1024 * 1024, pool.clone())));
        pressure.resize(64 * 1024 * 1024 - ctx.directory_reserved_bytes() as usize)?;
        let _ = DecisionRecord::new(
            &ctx,
            0,
            1,
            0,
            &Group {
                offset: 0,
                rows: 2,
                lineage: vec![],
                exact: false,
            },
        );
        drop(pressure);
        let job = Job {
            random_seed: Some("audit-denied-v1".into()),
            operations: vec![
                Operation::Balanced { files: 1 },
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(0)],
                },
            ],
            ..Default::default()
        };
        let ingested = ingest(Box::new("id\n2\n1\n".as_bytes()), &job, &ctx)?;
        let parents = serial(
            &ingested.dataset,
            &job.operations[0],
            0,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let shuffled = serial(
            &parents,
            &job.operations[1],
            1,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let expected = serial(
            &shuffled,
            &job.operations[2],
            2,
            &job,
            &ingested.analysis,
            &ctx,
        )?;
        let mut output = DatasetWriter::new(&ctx)?;
        Plan::at(&job, 1)
            .unwrap()
            .apply(&parents, &job, &ingested.analysis, &ctx, &mut output)?;
        let actual = output.finish()?;
        assert_eq!(snapshot(&actual, &ctx)?, snapshot(&expected, &ctx)?);
        let diagnostics = ctx.diagnostics();
        let audit = &diagnostics["shuffle_partition_decisions"];
        assert_eq!(audit["collection_denied"], true);
        assert_eq!(audit["reserved_bytes"], 0);
        assert_eq!(audit["omitted_attempts"], 1);
        assert!(audit["records"].as_array().unwrap().is_empty());
        drop(actual);
        drop(expected);
        drop(shuffled);
        drop(parents);
        drop(ingested);
        assert_eq!(pool.usage().reserved_bytes, ctx.directory_reserved_bytes());
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn leading_elided_shuffles_keep_logical_stats_empty_header_and_prepared_lifetime() -> Result<()>
    {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let temp = dir.path().join("temp");
        std::fs::create_dir(&temp)?;
        for text in ["id,key\n0,a\n1,b\n2,a\n3,b\n", "id,key\n"] {
            std::fs::write(&input, text)?;
            let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
            let job = Job {
                input: input.to_string_lossy().into(),
                random_seed: Some("stats-v1".into()),
                resources: Resources {
                    memory_mb: 32.into(),
                    workers: 1,
                    max_record_bytes: 2097152,
                    temp_dir: Some(temp.to_string_lossy().into()),
                    ..Default::default()
                },
                operations: vec![
                    shuffle(),
                    shuffle(),
                    Operation::Partition {
                        columns: vec![Column::Name("key".into())],
                    },
                ],
                ..Default::default()
            };
            let prepared = prepare_with_memory_pool(
                job,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let stats = &prepared.analysis.stages;
            assert_eq!(stats.len(), 3);
            let rows = prepared.analysis.rows;
            for (index, stage) in stats.iter().take(2).enumerate() {
                assert_eq!(
                    (
                        stage.operation,
                        stage.input_groups,
                        stage.output_groups,
                        stage.smallest_group,
                        stage.largest_group,
                        stage.empty_groups
                    ),
                    (index + 1, 1, 1, rows, rows, u64::from(rows == 0))
                );
            }
            assert_eq!(
                (
                    stats[2].operation,
                    stats[2].input_groups,
                    stats[2].output_groups
                ),
                (3, 1, if rows == 0 { 0 } else { 2 })
            );
            assert_eq!(
                prepared.analysis.diagnostics["shuffle_partition_fusions"],
                1
            );
            assert!(pool.usage().reserved_bytes > 0);
            drop(prepared);
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
        }
        Ok(())
    }

    #[test]
    fn resolved_columns_reserve_before_allocation_and_rollback_for_retry() -> Result<()> {
        let job = Job {
            operations: vec![
                shuffle(),
                Operation::Partition {
                    columns: vec![Column::Index(0), Column::Index(1), Column::Index(2)],
                },
            ],
            ..Default::default()
        };
        let plan = Plan::at(&job, 0).unwrap();
        let bytes = 3 * std::mem::size_of::<usize>();
        let directory = context()?.directory_reserved_bytes();
        for delta in [-1isize, 0, 1] {
            let pool = Arc::new(crate::resources::MemoryPool::new(
                (bytes as u64 + directory)
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
            let mut reservation = Reservation::new(&ctx);
            assert!(plan.resolve(None, 2, &mut reservation).is_err());
            assert_eq!(reservation.bytes(), 0);
            assert_eq!(pool.usage().reserved_bytes, directory);
            let result = plan.resolve(None, 3, &mut reservation);
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(columns) = result {
                assert_eq!(columns, [0, 1, 2]);
            }
            assert_eq!(
                reservation.bytes(),
                if delta >= 0 { bytes as u64 } else { 0 }
            );
            drop(reservation);
            assert_eq!(pool.usage().reserved_bytes, directory);
            drop(ctx);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn retained_owner_denies_late_parent_then_replay_preserves_prior_commit() -> Result<()> {
        let report = resource_contracts::retained_parent_retry()?;
        println!("CHOPPER_RETAINED_PARENT_RESOURCE_CONTRACT {report}");
        Ok(())
    }

    #[test]
    fn public_preparation_replays_denied_retained_parent_and_cleans_errors() -> Result<()> {
        let report = resource_contracts::preparation::run()?;
        println!("CHOPPER_PUBLIC_PREPARATION_RESOURCE_CONTRACT {report}");
        Ok(())
    }

    #[test]
    fn emission_admission_error_is_terminal_and_never_replays_committed_rows() -> Result<()> {
        let report = resource_contracts::terminal_emission()?;
        println!("CHOPPER_TERMINAL_EMISSION_RESOURCE_CONTRACT {report}");
        Ok(())
    }

    #[test]
    fn malformed_input_late_cancellation_and_disk_denial_do_not_publish_or_leak() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let temp = dir.path().join("temp");
        std::fs::create_dir(&temp)?;
        for mode in ["malformed", "cancel", "disk"] {
            let mut text = "key,text\n".to_owned();
            text.push_str(&"a,duplicate\n".repeat(70_000));
            if mode == "malformed" {
                text.push_str("a,\"unterminated");
            }
            std::fs::write(&input, text)?;
            let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
            let cancel = Arc::new(AtomicBool::new(false));
            let signal = cancel.clone();
            let job = Job {
                input: input.to_string_lossy().into(),
                output: dir.path().join("output").to_string_lossy().into(),
                random_seed: Some("failure-v1".into()),
                resources: Resources {
                    memory_mb: 32.into(),
                    workers: 1,
                    max_record_bytes: 2097152,
                    temp_dir: Some(temp.to_string_lossy().into()),
                    temp_bytes: (mode == "disk").then_some(1000),
                    ..Default::default()
                },
                operations: vec![
                    shuffle(),
                    Operation::Partition {
                        columns: vec![Column::Index(0)],
                    },
                ],
                ..Default::default()
            };
            let result = prepare_with_memory_pool(
                job,
                cancel,
                Arc::new(move |progress| {
                    if mode == "cancel" && progress.rows >= 65536 {
                        signal.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                }),
                pool.clone(),
            );
            let error = result.err().context("expected preparation failure")?;
            let message = format!("{error:#}");
            assert!(
                match mode {
                    "cancel" => message.contains("cancel"),
                    "disk" => message.contains("temporary-space"),
                    _ => message.contains("quoted") || message.contains("unterminated"),
                },
                "{mode}: {message}"
            );
            assert_eq!(pool.usage().reserved_bytes, 0);
            assert_eq!(std::fs::read_dir(&temp)?.count(), 0);
            assert!(!dir.path().join("output").exists());
        }
        Ok(())
    }
}

impl<'a> Plan<'a> {
    /// Eligibility is independent of memory/worker count and never changes the
    /// requested strategy. Positional splits and assignment are not commuted.
    pub fn at(job: &'a Job, step: usize) -> Option<Self> {
        if !matches!(
            job.operations.get(step),
            Some(Operation::Shuffle {
                strategy: Shuffle::Uniform | Shuffle::Auto
            })
        ) {
            return None;
        }
        let Operation::Partition { columns } = job.operations.get(step + 1)? else {
            return None;
        };
        Some(Self {
            columns,
            shuffle_step: step,
            partition_step: step + 1,
        })
    }

    pub fn random(self, seed: &str, parent: &Group) -> Result<PartitionRandom<'static>> {
        Ok(PartitionRandom::Before(random::json_domain(
            seed,
            self.shuffle_step as u64,
            &parent.lineage,
        )?))
    }

    pub fn resolve(
        self,
        header: Option<&[String]>,
        width: usize,
        reservation: &mut Reservation,
    ) -> Result<Vec<usize>> {
        let before = reservation.bytes() as usize;
        let result = (|| {
            let mut columns = Vec::new();
            reservation.reserve_vec(&mut columns, self.columns.len())?;
            for column in self.columns {
                columns.push(resolve_column(column, header, width)?);
            }
            Ok(columns)
        })();
        if result.is_err() {
            // The partial vector is gone before releasing its charge.
            reservation.resize(before)?;
        }
        result
    }

    pub fn apply(
        self,
        data: &Dataset,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        #[cfg(feature = "experimental-shuffle-partition")]
        let mut parent_ordinal = 0u64;
        for parent in data.groups()? {
            let parent = parent?;
            #[cfg(feature = "experimental-shuffle-partition")]
            let mut record = DecisionRecord::new(
                ctx,
                self.shuffle_step,
                self.partition_step,
                parent_ordinal,
                &parent,
            );
            let result: Result<()> = (|| {
                let prepared = exact_plan::Proposal::new(self, &parent).prepare(
                    ctx,
                    |plan, parent| {
                        Admitted::new(plan, parent, analysis, ctx).and_then(|attempt| {
                            #[cfg(feature = "experimental-shuffle-partition")]
                            {
                                record.phase = Phase::Preparation;
                            }
                            attempt.prepare(
                                data,
                                job,
                                ctx,
                                #[cfg(feature = "experimental-shuffle-partition")]
                                &mut record,
                            )
                        })
                    },
                    |error| {
                        error
                            .downcast_ref::<crate::resources::MemoryAdmission>()
                            .is_some()
                    },
                )?;
                let prepared = match prepared {
                    exact_plan::Attempt::Prepared(prepared) => prepared,
                    exact_plan::Attempt::Retry(_error) => {
                        #[cfg(feature = "experimental-shuffle-partition")]
                        {
                            record.admission_denial = Denial::from_error(&_error);
                            record.admission_denial_phase = Some(record.phase);
                            record.phase = Phase::OriginalRetry;
                        }
                        // All tentative owners have dropped before the replay. A
                        // cancellation at this boundary wins over admission retry.
                        ctx.event(
                            "retrying shuffle/partition with original stages",
                            parent.rows,
                        )?;
                        ctx.shuffle_partition_retry();
                        self.original(data, &parent, job, analysis, ctx, output)?;
                        #[cfg(feature = "experimental-shuffle-partition")]
                        {
                            record.outcome = Outcome::OriginalCommitted;
                        }
                        return Ok(());
                    }
                };
                // Once emission starts, any error is terminal. Retrying here could
                // duplicate already committed parents or rows in a terminal sink.
                #[cfg(feature = "experimental-shuffle-partition")]
                {
                    record.phase = Phase::Emission;
                }
                emit_partition(
                    prepared.rows,
                    &parent,
                    &prepared.columns,
                    self.partition_step,
                    true,
                    output,
                    ctx,
                )?;
                ctx.shuffle_partition_fused(parent.rows);
                #[cfg(feature = "experimental-shuffle-partition")]
                {
                    record.outcome = Outcome::FusedCommitted;
                }
                Ok(())
            })();
            #[cfg(feature = "experimental-shuffle-partition")]
            record.finish(ctx, result.as_ref().err());
            result?;
            #[cfg(feature = "experimental-shuffle-partition")]
            {
                // Diagnostic identity cannot introduce an execution error.
                parent_ordinal = parent_ordinal.saturating_add(1);
            }
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn original(
        self,
        data: &Dataset,
        parent: &Group,
        job: &Job,
        analysis: &Analysis,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        let mut shuffled = DatasetWriter::new(ctx)?;
        apply_parent(
            data,
            parent,
            &job.operations[self.shuffle_step],
            self.shuffle_step,
            job,
            analysis,
            ctx,
            &mut shuffled,
            None,
            None,
        )?;
        let shuffled = shuffled.finish()?;
        for parent in shuffled.groups()? {
            apply_parent(
                &shuffled,
                &*parent?,
                &job.operations[self.partition_step],
                self.partition_step,
                job,
                analysis,
                ctx,
                output,
                None,
                None,
            )?;
        }
        Ok(())
    }
}
