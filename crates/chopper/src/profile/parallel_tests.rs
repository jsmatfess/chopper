use super::*;
fn job() -> Job {
    let mut job = Job::default();
    job.resources.workers = 4;
    job.operations = vec![Operation::Partition {
        columns: vec![
            chopper_core::Column::Index(0),
            chopper_core::Column::Index(1),
        ],
    }];
    job
}
fn scan_bytes(
    text: &[u8],
    job: &Job,
    workspace: Arc<Workspace>,
    parallel: bool,
) -> Result<Observations> {
    let notify: Notify = Arc::new(|_| {});
    scan_configured(
        Box::new(text),
        job,
        &AtomicBool::new(false),
        &notify,
        workspace,
        parallel,
    )
}
#[test]
fn batches_preserve_full_profile_across_quoted_boundaries_and_wide_rows() -> Result<()> {
    let mut text = "id,value,other\n".to_owned();
    for i in 0..5100 {
        let value = if i == 4517 {
            "界".repeat(100_000)
        } else {
            format!("{i},\"quote\"\nnext")
        };
        text.push_str(&format!(
            "{i},\"{}\",{}\n",
            value.replace('"', "\"\""),
            i % 7
        ));
    }
    for headers in [true, false] {
        let mut job = job();
        job.input_csv.headers = headers;
        let serial = scan_bytes(
            text.as_bytes(),
            &job,
            Arc::new(Workspace::new(16 * 1024 * 1024)),
            false,
        )?;
        let workspace = Arc::new(Workspace::new(16 * 1024 * 1024));
        let parallel = scan_bytes(text.as_bytes(), &job, workspace.clone(), true)?;
        assert_eq!(
            serde_json::to_value(&parallel.profile)?,
            serde_json::to_value(&serial.profile)?
        );
        assert_eq!(parallel.combinations, serial.combinations);
        assert_eq!(
            parallel.profile.execution.hashed_rows,
            parallel.profile.rows
        );
        assert!(parallel.profile.execution.hash_batches > 1);
        assert_eq!(parallel.profile.execution.hash_workers, 4);
        drop(parallel);
        assert_eq!(workspace.used(), 0);
    }
    for text in ["", "id,value\n", "id,value\n1,x\n"] {
        let mut job = job();
        job.operations.clear();
        let serial = scan_bytes(
            text.as_bytes(),
            &job,
            Arc::new(Workspace::new(1024 * 1024)),
            false,
        )?;
        let parallel = scan_bytes(
            text.as_bytes(),
            &job,
            Arc::new(Workspace::new(1024 * 1024)),
            true,
        )?;
        assert_eq!(
            serde_json::to_value(parallel.profile)?,
            serde_json::to_value(serial.profile)?
        );
    }
    Ok(())
}
#[test]
fn single_worker_and_denied_optional_metadata_use_serial_storage() -> Result<()> {
    let text = "id,value\n".to_owned() + &"1,ok\n".repeat(1000);
    let mut job = job();
    let roomy = Arc::new(Workspace::new(1024 * 1024));
    let serial = scan_bytes(text.as_bytes(), &job, roomy.clone(), false)?;
    let expected = serde_json::to_value(&serial.profile)?;
    drop(serial);
    let peak = roomy.peak() as usize;
    let workspace = Arc::new(Workspace::new(peak));
    let fallback = scan_bytes(text.as_bytes(), &job, workspace.clone(), true)?;
    assert_eq!(fallback.profile.execution.hash_workers, 0);
    assert_eq!(serde_json::to_value(&fallback.profile)?, expected);
    drop(fallback);
    assert_eq!(workspace.used(), 0);
    job.resources.workers = 1;
    let serial = scan_bytes(text.as_bytes(), &job, workspace.clone(), true)?;
    assert_eq!(serial.profile.execution.hashed_rows, 0);
    assert_eq!(serde_json::to_value(&serial.profile)?, expected);
    drop(serial);
    assert_eq!(workspace.used(), 0);
    Ok(())
}
#[test]
fn denied_late_batch_restarts_serially_after_releasing_partial_scan() -> Result<()> {
    let mut text = "id,value\n".to_owned();
    for i in 0..600 {
        text.push_str(&format!(
            "{i},{}\n",
            if i == 490 {
                "x".repeat(400_000)
            } else {
                "small".into()
            }
        ));
    }
    let job = job();
    let serial_workspace = Arc::new(Workspace::new(16 * 1024 * 1024));
    let serial = scan_bytes(text.as_bytes(), &job, serial_workspace.clone(), false)?;
    let serial_peak = serial_workspace.peak();
    let expected = serde_json::to_value(&serial.profile)?;
    let expected_widths = (serial.decoded_field_bytes, serial.largest_decoded_row_bytes);
    drop(serial);
    let parallel_workspace = Arc::new(Workspace::new(16 * 1024 * 1024));
    drop(scan_bytes(
        text.as_bytes(),
        &job,
        parallel_workspace.clone(),
        true,
    )?);
    let parallel_peak = parallel_workspace.peak();
    assert!(parallel_peak > serial_peak + 16_384);
    let limit = (serial_peak + parallel_peak) / 2;
    let local = Arc::new(Workspace::new(limit as usize));
    let error = scan_bytes(text.as_bytes(), &job, local.clone(), true)
        .err()
        .unwrap();
    assert!(error
        .downcast_ref::<crate::resources::MemoryAdmission>()
        .is_some());
    assert_eq!(local.used(), 0);
    drop(scan_bytes(text.as_bytes(), &job, local.clone(), false)?);
    assert_eq!(local.used(), 0);

    let directory = tempfile::tempdir()?;
    let path = directory.path().join("input.csv");
    std::fs::write(&path, text)?;
    let mut job = job;
    job.input = path.to_string_lossy().into_owned();
    let pool = Arc::new(crate::resources::MemoryPool::new(limit));
    let mut cache = ProfileCache::with_memory_pool(pool.clone());
    let result = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
    assert!(result.execution.serial_retry);
    assert_eq!(result.execution.hash_workers, 0);
    let mut actual = serde_json::to_value(&result)?;
    actual["seconds"] = serde_json::json!(0.0);
    // Cache responses add job-specific planning after the equivalent raw scan.
    if let Some(advice) = result.writer_estimate {
        assert_eq!(
            advice.estimated_groups,
            result.stages[0].input_distinct_keys
        );
    }
    actual["stages"] = serde_json::json!([]);
    if let Some(advice) = result.auto_observations {
        assert_eq!(advice.rows, result.rows);
        assert_eq!(
            (advice.decoded_field_bytes, advice.largest_decoded_row_bytes),
            expected_widths
        );
    }
    actual.as_object_mut().unwrap().remove("auto_observations");
    actual.as_object_mut().unwrap().remove("writer_estimate");
    assert_eq!(actual, expected);
    let cached = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
    assert_eq!(cached.cache_hit, !cfg!(windows));
    drop((cached, result, cache));
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(())
}
#[test]
fn batch_corruption_and_cancellation_release_all_reservations() -> Result<()> {
    for suffix in ["bad\n", "1,\"unterminated", "1,\"bad\"x\n"] {
        let text = "id,value\n".to_owned() + &"1,ok\n".repeat(300) + suffix;
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let error = scan_bytes(text.as_bytes(), &job(), workspace.clone(), true)
            .err()
            .unwrap();
        assert!(error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_none());
        assert!(format!("{error:#}").contains("302"));
        assert_eq!(workspace.used(), 0);
    }
    let text = "id,value\n".to_owned() + &"1,ok\n".repeat(20_000);
    let workspace = Arc::new(Workspace::new(8 * 1024 * 1024));
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    let notify: Notify = Arc::new(move |_| signal.store(true, Ordering::Relaxed));
    let error = scan_configured(
        Box::new(text.as_bytes()),
        &job(),
        &cancel,
        &notify,
        workspace.clone(),
        true,
    )
    .err()
    .unwrap();
    assert!(format!("{error:#}").contains("cancelled"));
    assert_eq!(workspace.used(), 0);
    Ok(())
}
