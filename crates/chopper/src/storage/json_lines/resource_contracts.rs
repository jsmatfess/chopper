//! The same decoded-group assertions run natively and inside the OPFS reactor.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

const POOL_BYTES: u64 = 4 * 1024 * 1024;

fn context(parent: &std::path::Path, pool: Arc<MemoryPool>) -> Result<Context> {
    Context::with_memory_pool(
        &chopper_core::Resources {
            memory_mb: 64.into(),
            workers: 1,
            max_record_bytes: 64 * 1024,
            temp_bytes: Some(8 * 1024 * 1024),
            temp_dir: Some(parent.to_string_lossy().into_owned()),
            ..Default::default()
        },
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool,
    )
}

pub(crate) fn group_catalog() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let directory = dir.path().to_owned();
    let pool = Arc::new(MemoryPool::new(POOL_BYTES));
    let ctx = context(dir.path(), pool.clone())?;
    let job_directory = ctx.dir.path().to_owned();
    let mut writer = DatasetWriter::new(&ctx)?;
    let group = writer.begin(
        vec![serde_json::json!({"values": ["quoted\"line\n界", ["wide", null]], "object": {"key": "value"}})],
        true,
    );
    let text = serde_json::to_vec(&group)?;
    writer.end(group.clone())?;
    writer.end(group)?;
    let dataset = writer.finish()?;

    // Calibrate decoder demand on this target, including pointer-size-dependent
    // Value/map allowances. This is a contract, never a production selector.
    let probe = Arc::new(Workspace::new(POOL_BYTES as usize));
    let decoded = decode_reserved::<Group>(&text, Reservation::for_workspace(probe.clone()))?;
    let retained = probe.used();
    let transient = probe.peak();
    ensure!(
        retained > 0 && transient >= retained,
        "invalid decode probe"
    );
    drop(decoded);
    ensure!(probe.used() == 0, "probe leaked decoded charge");

    let mut reader = dataset.groups()?;
    let held = reader.next().context("missing first group")??;
    ensure!(serde_json::to_vec(&held)? == text, "group bytes changed");
    let mut pressure = Reservation::for_workspace(Arc::new(Workspace::shared(
        POOL_BYTES as usize,
        pool.clone(),
    )));
    // The identical second record reuses the already allocated line buffer.
    // Its decode has one byte less than the observed transient grant, while
    // local workspace admission is ample. The first Group stays really owned.
    pressure.resize((POOL_BYTES - pool.usage().reserved_bytes - transient + 1) as usize)?;
    let pressure_bytes = pressure.bytes();
    let error = reader
        .next()
        .context("missing denied second group")?
        .err()
        .context("shared pressure should deny decoded group")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ),
        "expected typed shared decode denial: {error:#}"
    );
    ensure!(
        reader.next().is_none(),
        "normal reader retried failed record"
    );
    ensure!(
        serde_json::to_vec(&held)? == text,
        "denial damaged held owner"
    );
    drop(held);
    drop(reader);

    // Retry is an explicit fresh normal reader over the unchanged catalog.
    // The native-only rewind iterator is deliberately not used here.
    let mut retry = dataset.groups()?;
    let owner = retry.next().context("missing retried group")??;
    ensure!(
        serde_json::to_vec(&owner)? == text,
        "retry changed immutable record"
    );
    drop(retry);
    drop(pressure);
    drop(dataset);
    drop(ctx);
    ensure!(
        !job_directory.try_exists()?,
        "group dataset directory leaked"
    );
    ensure!(
        pool.usage().reserved_bytes == retained,
        "owner lost charge with dataset/context"
    );
    ensure!(
        serde_json::to_vec(&owner)? == text,
        "owner invalid after dataset drop"
    );
    drop(owner);
    ensure!(
        pool.usage().reserved_bytes == 0,
        "final group owner leaked charge"
    );

    for cancel in [false, true] {
        let ctx = context(dir.path(), pool.clone())?;
        let path = ctx.dir.path().to_owned();
        let mut file = ctx.file()?;
        if cancel {
            file.write_all(&text)?;
        } else {
            // Valid JSON with a bad typed field exercises owned decode failure.
            file.write_all(br#"{"offset":0,"rows":0,"lineage":[],"exact":"invalid"}"#)?;
        }
        file.write_all(b"\n")?;
        file.write_all(&text)?;
        file.write_all(b"\n")?;
        file.flush()?;
        let mut lines = JsonLines::<Group>::new(&file, 64 * 1024)?.reserved();
        if cancel {
            drop(lines.next().context("missing before-cancel group")??);
            ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
        }
        let error = lines
            .next()
            .context("missing terminal error")?
            .err()
            .context("malformed/cancelled catalog accepted")?;
        ensure!(
            error.downcast_ref::<MemoryAdmission>().is_none(),
            "terminal error became admission denial"
        );
        ensure!(
            error.to_string().contains("cancelled") == cancel,
            "wrong terminal error: {error:#}"
        );
        ensure!(
            lines.next().is_none(),
            "reader continued after terminal error"
        );
        drop(lines);
        drop(file);
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "terminal path leaked charge"
        );
        ensure!(!path.try_exists()?, "terminal path leaked directory");
    }
    ensure!(
        std::fs::read_dir(dir.path())?.next().is_none(),
        "fixture contains leaked files"
    );
    dir.close()?;
    ensure!(!directory.try_exists()?, "fixture directory leaked");
    Ok(serde_json::json!({
        "contract": "decoded-group-catalog-resource-contracts-v1",
        "pointer_bytes": std::mem::size_of::<usize>(),
        "record_bytes": text.len(), "retained_bytes": retained,
        "decode_transient_bytes": transient, "competing_owner_bytes": pressure_bytes,
        "typed_shared_denials": 1, "normal_denial_terminal": true,
        "fresh_reader_release_retries": 1, "immutable_record_parity": true,
        "owner_survives_reader_dataset_context": true,
        "malformed_terminal": true, "buffered_cancellation_terminal": true,
        "fixture_directory_removed": true, "final_reserved_bytes": 0,
    }))
}

#[cfg(test)]
mod tests {
    #[test]
    fn group_catalog_shared_ownership_contract() -> anyhow::Result<()> {
        super::group_catalog()?;
        Ok(())
    }
}
