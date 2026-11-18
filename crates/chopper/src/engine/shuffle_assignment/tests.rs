use super::*;
use std::collections::BTreeMap;

fn groups() -> Vec<Allocation> {
    [("first", "50"), ("zero", "0"), ("last", "50")]
        .into_iter()
        .map(|(name, percent)| Allocation {
            name: name.into(),
            percent: percent.into(),
        })
        .collect()
}
fn job(strategy: Shuffle) -> Job {
    Job {
        random_seed: Some("range-wiring".into()),
        operations: vec![
            Operation::Shuffle { strategy },
            Operation::Assign {
                groups: groups(),
                strata: vec![],
            },
        ],
        ..Default::default()
    }
}
fn context() -> Result<Context> {
    Context::with_memory_pool(
        &Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: 1048576,
            ..Default::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
    )
}
#[derive(Default)]
struct Capture {
    groups: Vec<(Group, Vec<Row>)>,
    current: Vec<Row>,
    fail: bool,
    source: Option<u32>,
}
impl RowSink for Capture {
    fn physical_input(&mut self, source: Option<u32>) {
        self.source = source;
    }
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        Group {
            offset: 0,
            rows: 0,
            lineage,
            exact,
        }
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        ensure!(!self.fail, "injected sink failure");
        self.current.push(Row {
            id: row.id,
            ordinal: row.ordinal,
            key: row.key.clone(),
            fields: row.fields.clone(),
        });
        group.rows += 1;
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.groups.push((group, std::mem::take(&mut self.current)));
        Ok(())
    }
}
fn ordered(ids: &[u64], ctx: &Context) -> Result<SortedRows> {
    let mut sorter = Sorter::new(ctx, SortOrder::Key);
    for (ordinal, id) in ids.iter().enumerate() {
        sorter.push(Row {
            id: *id,
            ordinal: ordinal as u64,
            key: vec![],
            fields: vec![id.to_string(), "界,\"\n".into()],
        })?;
    }
    sorter.finish()
}
fn parent(rows: u64) -> Group {
    Group {
        offset: 0,
        rows,
        lineage: vec![json!({"operation":0,"part":1})],
        exact: true,
    }
}
#[test]
fn eligibility_preserves_indices_and_overlap_barriers() {
    for strategy in [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates] {
        let mut job = job(strategy);
        assert!(Plan::at(&job, 0).is_some());
        assert!(Plan::at(&job, usize::MAX).is_none());
        for suffix in [Shuffle::Auto, Shuffle::Uniform] {
            job.operations.push(Operation::Shuffle { strategy: suffix });
            assert!(Plan::at(&job, 0).is_none());
            job.operations.pop();
        }
        job.operations.insert(0, Operation::Balanced { files: 1 });
        let plan = Plan::at(&job, 1).unwrap();
        assert_eq!((plan.shuffle_step, plan.assignment_step), (1, 2));
        if let Operation::Assign { strata, .. } = &mut job.operations[2] {
            strata.push(Column::Index(0));
        }
        assert!(Plan::at(&job, 1).is_none());
    }
    let mut job = job(Shuffle::Auto);
    job.operations.insert(1, Operation::Balanced { files: 1 });
    assert!(Plan::at(&job, 0).is_none());
}
#[test]
fn ties_zeros_empty_fields_identity_ordinals_and_stats() -> Result<()> {
    let ctx = context()?;
    let job = job(Shuffle::Uniform);
    for n in [0, 1, 3, 4] {
        let ids = (0..n).collect::<Vec<_>>();
        let mut output = Capture::default();
        let stats = Plan::at(&job, 0).unwrap().emit_sorted(
            ordered(&ids, &ctx)?,
            &parent(n),
            &mut output,
            &ctx,
            Kind::ResidentSort,
        )?;
        let counts = [n.div_ceil(2), 0, n / 2];
        assert_eq!(
            (stats.operation, stats.input_groups, stats.output_groups),
            (2, 1, 3)
        );
        assert_eq!(
            (
                stats.smallest_group,
                stats.largest_group,
                stats.empty_groups
            ),
            (
                0,
                counts[0],
                counts.iter().filter(|n| **n == 0).count() as u64
            )
        );
        assert_eq!(output.groups.len(), 3);
        let mut actual = Vec::new();
        for (i, (group, rows)) in output.groups.iter().enumerate() {
            assert_eq!(group.rows, counts[i]);
            assert!(!group.exact);
            assert_eq!(
                group.lineage,
                vec![
                    json!({"operation":0,"part":1}),
                    json!({"operation":1,"allocation":groups()[i].name})
                ]
            );
            for (ordinal, row) in rows.iter().enumerate() {
                assert_eq!(row.ordinal, ordinal as u64);
                assert!(row.key.is_empty());
                assert_eq!(row.fields, [row.id.to_string(), "界,\"\n".into()]);
                actual.push(row.id);
            }
        }
        assert_eq!(actual, ids);
    }
    Ok(())
}
#[test]
fn missing_trailing_cancel_and_sink_errors_are_terminal() -> Result<()> {
    let ctx = context()?;
    let job = job(Shuffle::Uniform);
    let plan = Plan::at(&job, 0).unwrap();
    for (ids, count, message) in [(vec![0], 2, "truncated"), (vec![0, 1], 1, "trailing")] {
        let mut output = Capture::default();
        let error = plan
            .emit_sorted(
                ordered(&ids, &ctx)?,
                &parent(count),
                &mut output,
                &ctx,
                Kind::ResidentSort,
            )
            .unwrap_err();
        assert!(error.to_string().contains(message));
    }
    let mut output = Capture {
        fail: true,
        ..Default::default()
    };
    assert!(plan
        .emit_sorted(
            ordered(&[0, 1], &ctx)?,
            &parent(2),
            &mut output,
            &ctx,
            Kind::ResidentSort
        )
        .unwrap_err()
        .to_string()
        .contains("injected"));
    let cancel = Arc::new(AtomicBool::new(false));
    let ctx = Context::new(&Resources::default(), cancel.clone(), Arc::new(|_| {}))?;
    let rows = ordered(&[0], &ctx)?;
    cancel.store(true, std::sync::atomic::Ordering::Relaxed);
    assert!(plan
        .emit_sorted(
            rows,
            &parent(1),
            &mut Capture::default(),
            &ctx,
            Kind::ResidentSort
        )
        .is_err());
    Ok(())
}
#[test]
fn quota_admission_denial_releases_owner() -> Result<()> {
    let groups = groups();
    let bytes = groups.len() * (3 * std::mem::size_of::<u64>() + std::mem::size_of::<usize>());
    let workspace = Arc::new(Workspace::new(bytes - 1));
    assert!(AssignmentScratch::new(
        &groups,
        false,
        Reservation::for_workspace(workspace.clone())
    )
    .is_err());
    assert_eq!(workspace.used(), 0);
    Ok(())
}
#[test]
fn retained_apply_preserves_parent_isolation_for_every_strategy() -> Result<()> {
    for strategy in [Shuffle::Auto, Shuffle::Uniform, Shuffle::FisherYates] {
        let ctx = context()?;
        let mut job = job(strategy);
        job.operations.insert(0, Operation::Balanced { files: 2 });
        let source = ingest_options(
            &mut b"id,text\n0,a\n1,b\n2,c\n3,d\n4,e\n5,f\n".as_slice(),
            &job,
            &ctx,
            false,
            false,
            false,
        )?;
        let mut parents = DatasetWriter::new(&ctx)?;
        for group in source.dataset.groups()? {
            let group = group?;
            apply_parent(
                &source.dataset,
                &group,
                &job.operations[0],
                0,
                &job,
                &source.analysis,
                &ctx,
                &mut parents,
                None,
                None,
            )?;
        }
        let parents = parents.finish()?;
        let mut output = Capture::default();
        let plan = Plan::at(&job, 1).unwrap();
        plan.apply(&parents, &job, &source.analysis, &ctx, &mut output)?;
        assert_eq!(output.groups.len(), 6);
        let mut ids = Vec::new();
        for (index, (group, rows)) in output.groups.iter().enumerate() {
            assert_eq!(
                group.lineage[0],
                json!({"operation":0,"part":index / 3 + 1})
            );
            assert_eq!(group.lineage[1]["operation"], 2);
            assert_eq!(rows.len(), [2, 0, 1][index % 3]);
            for row in rows {
                assert_eq!(row.id / 3, (index / 3) as u64);
                assert_eq!(row.fields[0], row.id.to_string());
                assert_eq!(row.fields[1], ((b'a' + row.id as u8) as char).to_string());
                ids.push(row.id);
            }
        }
        ids.sort_unstable();
        assert_eq!(ids, (0..6).collect::<Vec<_>>());
        if strategy == Shuffle::FisherYates {
            let mut tiny = ctx.clone();
            tiny.memory = 64;
            let mut denied = Capture::default();
            assert!(plan
                .apply(&parents, &job, &source.analysis, &tiny, &mut denied)
                .is_err());
            assert!(denied.groups.is_empty() && denied.current.is_empty());
        }
    }
    Ok(())
}
fn permutations(ids: &mut [u64], at: usize, out: &mut Vec<Vec<u64>>) {
    if at == ids.len() {
        out.push(ids.to_vec());
        return;
    }
    for i in at..ids.len() {
        ids.swap(at, i);
        permutations(ids, at + 1, out);
        ids.swap(at, i);
    }
}
#[test]
fn exhaustive_joint_ordered_outcomes_supplement_the_distribution_argument() -> Result<()> {
    let ctx = context()?;
    let job = job(Shuffle::Uniform);
    let plan = Plan::at(&job, 0).unwrap();
    let mut permutations_out = Vec::new();
    permutations(&mut [0, 1, 2, 3], 0, &mut permutations_out);
    let mut cut = BTreeMap::new();
    let mut original = BTreeMap::new();
    for ids in permutations_out {
        let mut output = Capture::default();
        plan.emit_sorted(
            ordered(&ids, &ctx)?,
            &parent(4),
            &mut output,
            &ctx,
            Kind::ResidentSort,
        )?;
        let signature = output
            .groups
            .iter()
            .map(|(_, rows)| rows.iter().map(|r| r.id).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        *cut.entry(signature).or_insert(0usize) += 1;
        // Enumerate every exact 2/0/2 membership of this original permutation.
        for a in 0..4 {
            for b in a + 1..4 {
                let first = ids
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| *i == a || *i == b)
                    .map(|(_, id)| *id)
                    .collect::<Vec<_>>();
                let last = ids
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| *i != a && *i != b)
                    .map(|(_, id)| *id)
                    .collect::<Vec<_>>();
                *original.entry(vec![first, vec![], last]).or_insert(0usize) += 1;
            }
        }
    }
    assert_eq!(cut.len(), 24);
    assert!(cut.values().all(|n| *n == 1));
    assert_eq!(
        cut.keys().collect::<Vec<_>>(),
        original.keys().collect::<Vec<_>>()
    );
    assert!(original.values().all(|n| *n == 6));
    Ok(())
}

// Hold a competitor at an exact owner phase, without changing production limits.
#[test]
fn combined_permutation_quota_and_late_serialization_denials_are_terminal() -> Result<()> {
    use crate::resources::{MemoryAdmission, MemoryPool};
    use std::cell::RefCell;
    use std::rc::Rc;

    struct Pressure<'a> {
        writer: output::PlanWriter<'a>,
        workspace: Arc<Workspace>,
        pool: Arc<MemoryPool>,
        shared: bool,
        charge: Reservation,
        deny_late: bool,
        ended: usize,
        rows: usize,
    }
    impl Pressure<'_> {
        fn exhaust(&mut self) -> Result<()> {
            let remaining = if self.shared {
                let usage = self.pool.usage();
                usage.limit_bytes - usage.reserved_bytes
            } else {
                16 * 1024 * 1024 - self.workspace.used()
            };
            self.charge.resize(remaining as usize)
        }
    }
    impl RowSink for Pressure<'_> {
        fn physical_input(&mut self, source: Option<u32>) {
            self.writer.physical_input(source);
        }
        fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
            self.writer.begin(lineage, exact)
        }
        fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
            self.writer.row(group, row)
        }
        fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
            if self.deny_late && row.id == 1 {
                assert_eq!((self.ended, self.rows), (2, 1));
                assert!(row.fields().nth(1).unwrap().len() >= 128 * 1024);
                self.exhaust()?;
            }
            self.writer.packed_row_ref(group, row)?;
            self.rows += 1;
            Ok(())
        }
        fn end(&mut self, group: Group) -> Result<()> {
            self.writer.end(group)?;
            self.ended += 1;
            Ok(())
        }
    }

    for shared in [false, true] {
        for phase in [
            "quota",
            "late_serializer",
            "success_first_wide",
            "success_late_wide",
        ] {
            let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
            let captured = Rc::new(RefCell::new(None));
            let capture = captured.clone();
            let _hook = crate::storage::context_test_hook::install(move |workspace, _| {
                *capture.borrow_mut() = Some(workspace);
            });
            let ctx = Context::with_memory_pool(
                &Resources {
                    memory_mb: 32.into(),
                    workers: 1,
                    max_record_bytes: 1024 * 1024,
                    ..Default::default()
                },
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let workspace = captured.borrow_mut().take().unwrap();
            let mut job = job(Shuffle::FisherYates);
            job.operations.insert(
                0,
                Operation::Shuffle {
                    strategy: Shuffle::Auto,
                },
            );
            assert_eq!(
                super::super::shuffle_elision::initial_fisher_step(&job, 1),
                Some(1)
            );
            let plan = Plan::at(&job, 1).unwrap();
            let mut resident = ResidentShuffle::new(&ctx, [17; 32]);
            for id in 0..2 {
                let wide = if phase == "success_first_wide" {
                    id == 0
                } else {
                    id == 1
                };
                resident.push(Row {
                    id,
                    ordinal: id,
                    key: vec![],
                    fields: vec![
                        id.to_string(),
                        if wide {
                            "界,\"\n".repeat(32768)
                        } else {
                            "small".into()
                        },
                    ],
                })?;
            }
            // The production FY loop and owners, with deterministic identity draws
            // so a wide row reaches the later child after a real emitted prefix.
            let rows = SortedRows::Memory(resident.finish_with_draws(|bound| bound - 1)?);
            {
                let charge = Reservation::for_workspace(if shared {
                    Arc::new(Workspace::shared(64 * 1024 * 1024, pool.clone()))
                } else {
                    workspace.clone()
                });
                let mut sink = Pressure {
                    writer: output::PlanWriter::new(&job, None, &ctx)?,
                    workspace: workspace.clone(),
                    pool: pool.clone(),
                    shared,
                    charge,
                    deny_late: phase == "late_serializer",
                    ended: 0,
                    rows: 0,
                };
                if phase == "quota" {
                    sink.exhaust()?;
                }
                let result = plan.emit_sorted(rows, &parent(2), &mut sink, &ctx, Kind::FisherYates);
                if phase.starts_with("success") {
                    assert_eq!(result?.output_groups, 3);
                    assert_eq!((sink.ended, sink.rows), (3, 2));
                    let snapshot = sink.writer.finish()?;
                    assert_eq!(snapshot.files, 3);
                    assert!(snapshot.bytes > 128 * 1024);
                    drop(snapshot);
                    drop(sink.charge);
                } else {
                    let error = result.unwrap_err();
                    let admission = error
                        .downcast_ref::<MemoryAdmission>()
                        .expect("typed admission error");
                    assert_eq!(matches!(admission, MemoryAdmission::Shared { .. }), shared);
                    assert_eq!(
                        (sink.ended, sink.rows),
                        if phase == "quota" { (0, 0) } else { (2, 1) }
                    );
                    // Never finish or publish a successful prefix after terminal denial.
                    drop(sink);
                }
            }
            let diagnostics = ctx.diagnostics();
            assert_eq!(diagnostics["fisher_yates_calls"], 1);
            assert_eq!(diagnostics["sort_runs"], 0);
            assert_eq!(diagnostics["temporary_cleanup_failures"], 0);
            assert_eq!(ctx.used(), 0);
            assert_eq!(workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(std::fs::read_dir(ctx.dir.path())?.count(), 0);
            let directory = ctx.dir.path().to_path_buf();
            drop(ctx);
            assert!(!directory.exists());
            assert_eq!(workspace.used(), 0);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
    }
    Ok(())
}
