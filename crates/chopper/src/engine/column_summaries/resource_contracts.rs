use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use std::collections::BTreeSet;

fn job() -> Job {
    Job {
        operations: vec![Operation::Partition {
            columns: vec![Column::Index(2), Column::Index(0), Column::Index(1)],
        }],
        ..Job::default()
    }
}
fn rows() -> Vec<Vec<String>> {
    vec![
        vec!["x".into(), "".into(), "\u{754c}".into()],
        vec!["x".into(), "b".into(), "\u{754c}".into()],
    ]
}
// Reference the original selection/truncation algorithm, not the admitted builder.
fn legacy(job: &Job, header: Option<&[String]>, rows: &[Vec<String>]) -> Result<serde_json::Value> {
    let mut selected = BTreeSet::new();
    if let Some(first) = rows.first() {
        for operation in &job.operations {
            let columns = match operation {
                Operation::Partition { columns } => columns,
                Operation::Assign { strata, .. }
                | Operation::AssignProbabilistic { strata, .. } => strata,
                _ => continue,
            };
            selected.extend(resolve_columns(columns, header, first.len())?);
        }
    }
    let mut summaries = selected
        .into_iter()
        .take(64)
        .map(|column| ColumnValues {
            column,
            values: BTreeSet::new(),
            frequencies: Default::default(),
            truncated: false,
        })
        .collect::<Vec<_>>();
    let mut bytes = 0;
    for row in rows {
        for summary in &mut summaries {
            if summary.truncated {
                continue;
            }
            let value = &row[summary.column];
            if let Some(count) = summary.frequencies.get_mut(value) {
                *count += 1;
            } else {
                if summary.values.len() < 100 && bytes + value.len() + 64 <= 256 * 1024 {
                    bytes += value.len() + 64;
                    summary.values.insert(value.clone());
                    summary.frequencies.insert(value.clone(), 1);
                } else {
                    summary.truncated = true;
                    summary.frequencies.clear();
                }
            }
        }
    }
    Ok(serde_json::to_value(summaries)?)
}
fn build(memory: Reservation) -> Result<ColumnSummaries> {
    let mut builder = Builder::new(memory);
    for row in rows() {
        builder.observe(&job(), None, FieldViews::owned(&row))?;
    }
    builder.finish()
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let required = 3 * std::mem::size_of::<ColumnValues>()
        + 4 * NODE_ALLOWANCE
        + 10
        + Shared::<Vec<ColumnValues>>::controller_bytes();
    let canonical = legacy(&job(), None, &rows())?;
    for shared in [false, true] {
        for limit in [required - 1, required, required + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(required + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = build(Reservation::for_workspace(workspace.clone()));
            if limit < required {
                let error = result.err().context("summary edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "summary edge lost denial type"
                );
            } else {
                let values = result?;
                ensure!(
                    values.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_value(&values)? == canonical,
                    "summary bytes or values changed"
                );
                let copy = values.clone();
                ensure!(
                    std::ptr::eq(copy.as_ptr(), values.as_ptr())
                        && workspace.used() == required as u64,
                    "summary clone copied data/grant"
                );
                drop(values);
                ensure!(
                    serde_json::to_value(&copy)? == canonical
                        && workspace.used() == required as u64,
                    "summary clone lost owner"
                );
                let decoded: ColumnSummaries = serde_json::from_value(canonical.clone())?;
                ensure!(
                    decoded.reserved_bytes() == 0 && serde_json::to_value(&decoded)? == canonical,
                    "caller summary deserialization changed"
                );
                drop(decoded);
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "summary edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = build(Reservation::for_workspace(workspace.clone()))?;
    let error = build(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing summary accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "competing summary changed first owner"
    );
    drop(first);
    drop(build(Reservation::for_workspace(workspace.clone()))?);
    ensure!(pool.usage().reserved_bytes == 0, "summary retry leaked");
    #[cfg(not(target_os = "wasi"))]
    {
        let values = build(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = values.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(values);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(workspace.used() == 0, "concurrent summary release leaked");
    }
    entry_denial()?;
    let parity = parity()?;
    Ok(
        json!({"contract":"column-summary-admission-v1","retained_fixture_bytes":required,"node_allowance_per_key":NODE_ALLOWANCE,"local_shared_edges":6,"canonical_legacy_equal":true,"clone_shares_trees_and_grant":true,"caller_deserialization_equal":true,"competing_owner_release_retry":true,"entry_denial_preserves_tree_and_display_budget":true,"native_concurrent_last_drop":cfg!(not(target_os="wasi")),"parity":parity,"public_lifetimes":lifetimes()?,"final_reserved_bytes":0}),
    )
}
fn entry_denial() -> Result<()> {
    let pool = Arc::new(MemoryPool::new(64 * 1024));
    let workspace = Arc::new(Workspace::shared(64 * 1024, pool.clone()));
    let job = Job {
        operations: vec![Operation::Partition {
            columns: vec![Column::Index(0)],
        }],
        ..Job::default()
    };
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let first = vec!["first".into()];
    builder.observe(&job, None, FieldViews::owned(&first))?;
    let retained = workspace.used();
    let display = builder.display_bytes;
    let mut pressure =
        Reservation::for_workspace(Arc::new(Workspace::shared(64 * 1024, pool.clone())));
    pressure.resize(64 * 1024 - retained as usize - NODE_ALLOWANCE - "second".len() + 1)?;
    let second = vec!["second".into()];
    let before = pool.usage().reserved_bytes;
    let error = builder
        .observe(&job, None, FieldViews::owned(&second))
        .err()
        .context("summary copy edge accepted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && builder.values[0].values == BTreeSet::from(["first".into()])
            && !builder.values[0].truncated
            && builder.display_bytes == display
            && workspace.used() == retained
            && pool.usage().reserved_bytes == before,
        "entry denial changed tree/display or leaked"
    );
    drop(pressure);
    builder.observe(&job, None, FieldViews::owned(&second))?;
    let result = builder.finish()?;
    ensure!(
        result[0].values == BTreeSet::from(["first".into(), "second".into()]),
        "summary entry retry changed values"
    );
    drop(result);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "summary entry retry leaked"
    );
    Ok(())
}
fn parity() -> Result<serde_json::Value> {
    let workspace = Arc::new(Workspace::new(8 * 1024 * 1024));
    let header = (0..140).map(|i| format!("column{i}")).collect::<Vec<_>>();
    let wide = Job {
        operations: vec![Operation::Partition {
            columns: (0..140)
                .rev()
                .map(Column::Index)
                .chain([Column::Name("column2".into()), Column::Index(139)])
                .collect(),
        }],
        ..Job::default()
    };
    let wide_rows = vec![(0..140).map(|i| i.to_string()).collect::<Vec<_>>()];
    let limited = (0..110)
        .map(|i| {
            vec![
                format!("value{}", i % 101),
                "fixed".into(),
                format!("\u{754c}\n{}", i % 7),
            ]
        })
        .collect::<Vec<_>>();
    let boundary = vec![
        vec!["x".repeat(DISPLAY_BYTES - 64), "".into(), "".into()],
        vec![
            "x".repeat(DISPLAY_BYTES - 64),
            "different".into(),
            "".into(),
        ],
    ];
    for (job, header, rows) in [
        (&wide, Some(header.as_slice()), &wide_rows),
        (&job(), None, &limited),
        (&job(), None, &boundary),
    ] {
        let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
        for row in rows {
            builder.observe(job, header, FieldViews::owned(row))?;
        }
        let result = builder.finish()?;
        ensure!(
            serde_json::to_value(&result)? == legacy(job, header, rows)?,
            "legacy summary selection/truncation changed"
        );
        if result.len() == 64 {
            ensure!(
                result.iter().map(|v| v.column).eq(0..64),
                "bounded selection lost lowest indices"
            );
        }
        drop(result);
        ensure!(workspace.used() == 0, "summary parity leaked");
    }
    for invalid in [Column::Index(140), Column::Name("missing".into())] {
        let mut bad = wide.clone();
        if let Operation::Partition { columns } = &mut bad.operations[0] {
            columns.push(invalid);
        }
        let expected = legacy(&bad, Some(&header), &wide_rows)
            .unwrap_err()
            .to_string();
        let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
        let error = builder
            .observe(&bad, Some(&header), FieldViews::owned(&wide_rows[0]))
            .err()
            .context("late invalid summary column accepted")?;
        ensure!(
            error.to_string() == expected && workspace.used() == 0,
            "late error changed or selection allocated"
        );
    }
    let mut ambiguous_header = header.clone();
    ambiguous_header[138] = "duplicate".into();
    ambiguous_header[139] = "duplicate".into();
    let mut bad = wide.clone();
    if let Operation::Partition { columns } = &mut bad.operations[0] {
        columns.push(Column::Name("duplicate".into()));
    }
    let expected = legacy(&bad, Some(&ambiguous_header), &wide_rows)
        .unwrap_err()
        .to_string();
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    let error = builder
        .observe(
            &bad,
            Some(&ambiguous_header),
            FieldViews::owned(&wide_rows[0]),
        )
        .err()
        .context("late ambiguous column accepted")?;
    ensure!(
        error.to_string() == expected && workspace.used() == 0,
        "late ambiguous error changed or allocated"
    );
    let empty = Builder::new(Reservation::for_workspace(workspace.clone())).finish()?;
    ensure!(
        empty.is_empty() && empty.reserved_bytes() == 0 && workspace.used() == 0,
        "empty-input summaries allocated"
    );
    let mut builder = Builder::new(Reservation::for_workspace(workspace.clone()));
    builder.observe(&Job::default(), None, FieldViews::owned(&wide_rows[0]))?;
    let empty = builder.finish()?;
    ensure!(
        empty.is_empty() && empty.reserved_bytes() == 0 && workspace.used() == 0,
        "unselected summaries allocated"
    );
    Ok(
        json!({"legacy_cases":3,"lowest_64_order_and_duplicates":true,"hundred_value_and_display_byte_limits":true,"sticky_truncation":true,"late_invalid_columns_equal":true,"empty_and_unselected_no_allocation":true}),
    )
}

fn lifetimes() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,key\n1,a\n2,b\n3,a\n")?;
    for execute in [false, true] {
        let output = dir
            .path()
            .join(if execute { "published" } else { "discarded" });
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: output.to_string_lossy().into_owned(),
            random_seed: Some("summary-owner".into()),
            operations: vec![Operation::Partition {
                columns: vec![Column::Index(1)],
            }],
            resources: Resources {
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        };
        let prepared = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let ctx = prepared.ctx.clone();
        let copied = prepared.analysis.clone();
        ensure!(
            std::ptr::eq(
                copied.column_values.as_ptr(),
                prepared.analysis.column_values.as_ptr()
            ) && serde_json::to_value(&copied.column_values)?
                == json!([{"column":1,"values":["a","b"],"frequencies":{"a":2,"b":1},"truncated":false}]),
            "public summary clone/schema changed"
        );
        let retained = copied.warnings.reserved_bytes()
            + copied.timings.reserved_bytes()
            + copied.diagnostics.reserved_bytes()
            + copied.text_reserved_bytes()
            + copied.stages.reserved_bytes()
            + copied.column_values.reserved_bytes()
            + copied.preview.reserved_bytes()
            + copied.header.as_ref().map_or(0, Header::reserved_bytes);
        struct Reject;
        impl std::io::Write for Reject {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("summary serialization sentinel"))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let before = pool.usage().reserved_bytes;
        ensure!(
            serde_json::to_writer(Reject, &copied.column_values).is_err()
                && pool.usage().reserved_bytes == before,
            "summary serialization failure lost owner"
        );
        if execute {
            drop(prepared.execute()?);
            let mut rows = Vec::new();
            for entry in std::fs::read_dir(&output)? {
                let entry = entry?;
                if entry.path().extension() != Some(std::ffi::OsStr::new("csv")) {
                    continue;
                }
                let mut parser = Parser::new(
                    std::io::Cursor::new(std::fs::read(entry.path())?),
                    CsvSettings::default(),
                    1024 * 1024,
                );
                ensure!(
                    parser.next_record()? == Some(vec!["id".into(), "key".into()]),
                    "summary publication header changed"
                );
                while let Some(row) = parser.next_record()? {
                    rows.push(row);
                }
            }
            rows.sort();
            ensure!(
                rows == vec![
                    vec!["1".to_string(), "a".into()],
                    vec!["2".into(), "b".into()],
                    vec!["3".into(), "a".into()]
                ],
                "summary publication fields/IDs changed"
            );
        } else {
            drop(prepared);
            ensure!(
                !output.try_exists()?,
                "discarded summary preparation published"
            );
        }
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained,
            "returned/cloned summary lost live grant"
        );
        drop(copied);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "last summary clone retained grant"
        );
        drop(ctx);
        ensure!(pool.usage().reserved_bytes == 0, "summary context leaked");
    }
    let temporary = dir.path().join("failure-temporary");
    std::fs::create_dir(&temporary)?;
    for cancellation in [false, true] {
        let text = if cancellation {
            format!("id,key\n{}", "1,a\n".repeat(65_537))
        } else {
            "id,key\n1,a\n2,b\n3,\"unterminated".into()
        };
        std::fs::write(&input, text)?;
        let output = dir.path().join("failed-output");
        let pool = Arc::new(MemoryPool::new(64 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let observed = Arc::new(AtomicBool::new(false));
        let progress_seen = observed.clone();
        let result = prepare_with_memory_pool(
            Job {
                input: input.to_string_lossy().into_owned(),
                output: output.to_string_lossy().into_owned(),
                random_seed: Some("summary-cleanup".into()),
                operations: vec![Operation::Partition {
                    columns: vec![Column::Index(1)],
                }],
                resources: Resources {
                    temp_dir: Some(temporary.to_string_lossy().into_owned()),
                    memory_mb: 32.into(),
                    max_record_bytes: 1024 * 1024,
                    ..Resources::default()
                },
                ..Job::default()
            },
            cancel,
            Arc::new(move |progress| {
                if cancellation
                    && progress.phase == "Reading and validating CSV"
                    && progress.rows >= 65_536
                {
                    progress_seen.store(true, std::sync::atomic::Ordering::Relaxed);
                    signal.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }),
            pool.clone(),
        );
        let error = result.err().context("summary failure case prepared")?;
        ensure!(
            !output.try_exists()?
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&temporary)?.next().is_none(),
            "summary failed/cancelled scan leaked"
        );
        ensure!(
            if cancellation {
                observed.load(std::sync::atomic::Ordering::Relaxed)
                    && format!("{error:#}").contains("cancel")
            } else {
                format!("{error:#}").contains("unterminated quoted field")
            },
            "summary failure did not reach intended populated scan"
        );
    }
    dir.close()?;
    Ok(
        json!({"analysis_clone_shares_summaries":true,"serialization_failure_retains_owner":true,"prepared_drop_and_execute_lifetimes":true,"publication_rows_and_fields":true,"last_clone_release":true,"malformed_and_populated_scan_cancellation_cleanup":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

#[test]
fn column_summary_admission_selection_and_lifetime() {
    println!("{}", run().unwrap());
}
