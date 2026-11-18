use super::*;

struct Sink<'a> {
    pool: &'a MemoryPool,
    baseline: u64,
    cancel: &'a AtomicBool,
    mode: &'static str,
    ids: Vec<u64>,
    ended: bool,
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
            "child row lost metadata admission"
        );
        ensure!(
            row.fields == [row.id.to_string(), "界\n\"same".into()],
            "child changed fields"
        );
        if self.mode == "row_error" {
            anyhow::bail!("injected child row error");
        }
        self.ids.push(row.id);
        group.rows += 1;
        if self.mode == "cancel_first" || (self.mode == "cancel_last" && group.rows == 8) {
            self.cancel.store(true, Ordering::Relaxed);
        }
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        ensure!(
            self.pool.usage().reserved_bytes >= self.baseline + group.json_capacity()? as u64,
            "child completion lost metadata admission"
        );
        ensure!(
            group.rows == 8 && group.lineage.len() == 1,
            "child changed membership/metadata"
        );
        if self.mode == "end_error" {
            anyhow::bail!("injected child catalog error");
        }
        self.ended = true;
        Ok(())
    }
}

pub(super) fn run(dir: &std::path::Path) -> Result<serde_json::Value> {
    let input = dir.join("input.csv");
    std::fs::write(&input, b"id,value\n0,same\n")?;
    let job = Job {
        input: input.to_string_lossy().into_owned(),
        random_seed: Some("child-contract".into()),
        resources: Resources {
            workers: 1,
            temp_dir: Some(dir.to_string_lossy().into_owned()),
            ..Default::default()
        },
        ..Default::default()
    };
    let prepared = prepare(
        job.clone(),
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
    )?;
    let analysis = prepared.analysis.clone();
    drop(prepared);
    let pool = Arc::new(MemoryPool::new(32 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let ctx = Context::with_memory_pool(
        &job.resources,
        cancel.clone(),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let mut writer = DatasetWriter::new(&ctx)?;
    let mut parent = writer.begin(Vec::new(), true);
    for id in 0..8 {
        writer.row(
            &mut parent,
            &Row {
                id,
                ordinal: id,
                key: Vec::new(),
                fields: vec![id.to_string(), "界\n\"same".into()],
            },
        )?;
    }
    writer.end(parent.clone())?;
    let data = writer.finish()?;
    let baseline = pool.usage().reserved_bytes;
    let allocation = vec![Allocation {
        name: "界\"allocation".into(),
        percent: "100".into(),
    }];
    let operations = [
        Operation::Balanced { files: 1 },
        Operation::Interleaved { files: 1 },
        Operation::Partition {
            columns: vec![Column::Index(1)],
        },
        Operation::Assign {
            groups: allocation.clone(),
            strata: Vec::new(),
        },
        Operation::AssignProbabilistic {
            groups: allocation,
            strata: Vec::new(),
        },
    ];
    let mut cases = Vec::new();
    for operation in operations {
        let mut expected = None;
        for mode in [
            "success",
            "row_error",
            "end_error",
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
                ended: false,
            };
            let result = apply_parent(
                &data, &parent, &operation, 0, &job, &analysis, &ctx, &mut sink, None, None,
            );
            ensure!(
                result.is_ok() == matches!(mode, "success" | "retry"),
                "child operation {operation:?}/{mode}: {result:?}"
            );
            if result.is_ok() {
                ensure!(sink.ended, "child did not complete");
                let mut sorted = sink.ids.clone();
                sorted.sort_unstable();
                ensure!(sorted == (0..8).collect::<Vec<_>>(), "child lost rows");
                if let Some(expected) = &expected {
                    ensure!(&sink.ids == expected, "child retry changed order");
                } else {
                    expected = Some(sink.ids.clone());
                }
            } else {
                ensure!(!sink.ended, "failed child completed");
            }
            cancel.store(false, Ordering::Relaxed);
            ensure!(
                pool.usage().reserved_bytes == baseline,
                "child executor leaked after {mode}"
            );
        }
        cases.push(
            json!({"operation":operation,"row_and_end_failure_cleanup":true,
            "first_and_last_row_cancellation_cleanup":true,"retry_exact_order":true}),
        );
    }
    drop(data);
    drop(ctx);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "child executor retained context"
    );
    Ok(json!({"cases":cases,"final_reserved_bytes":0}))
}
