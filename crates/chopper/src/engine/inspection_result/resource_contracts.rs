//! Construction overlap and retained inspection responses on native/WASI.
use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};
use crate::storage::JsonCapacity;
use std::io::Write;
const LIMIT: usize = 8 * 1024 * 1024;

fn produce(kind: &str, source: &[u8], workspace: Arc<Workspace>) -> Result<Inspection> {
    let charge = Reservation::for_workspace(workspace);
    if kind == "sniff" {
        input_sniff::sniff(source, &Job::default(), charge)
    } else {
        input_inspection::columns(source, &Job::default(), charge, false)
    }
}

pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let mut wide = String::new();
    for index in 0..4096 {
        if index != 0 {
            wide.push(',');
        }
        wide.push_str("\u{754c}\u{e9}");
    }
    wide.push('\n');
    let mut reports = Vec::new();
    for (name, kind, source) in [
        ("columns", "columns", b"country,region,region\n".as_slice()),
        ("wide_unicode_header", "columns", wide.as_bytes()),
        ("sniff", "sniff", b"a;b\r\n1;2\r\n".as_slice()),
    ] {
        let probe = Arc::new(Workspace::new(LIMIT));
        let result = produce(kind, source, probe.clone())?;
        let peak = probe.peak();
        let retained = probe.used();
        ensure!(
            retained > 0 && retained == result._memory.bytes(),
            "result lost its grant"
        );
        ensure!(
            result.value.json_capacity()? <= retained as usize,
            "result exceeds preallocation envelope"
        );
        let expected = serde_json::to_vec(&result)?;
        // The returned result has outlived all source/parser/sample owners.
        // Every serializer write must still see its reservation, including error.
        struct Writer {
            workspace: Arc<Workspace>,
            retained: u64,
            fail: bool,
            writes: usize,
        }
        impl Write for Writer {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                assert_eq!(self.workspace.used(), self.retained);
                self.writes += 1;
                if self.fail {
                    Err(std::io::Error::other(
                        "injected inspection serialization failure",
                    ))
                } else {
                    Ok(bytes.len())
                }
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        for fail in [false, true] {
            let mut writer = Writer {
                workspace: probe.clone(),
                retained,
                fail,
                writes: 0,
            };
            let serialized = serde_json::to_writer(&mut writer, &result);
            ensure!(
                serialized.is_err() == fail && writer.writes > 0,
                "serialization fault changed"
            );
            ensure!(
                probe.used() == retained,
                "serialization released live result"
            );
        }
        drop(result);
        ensure!(probe.used() == 0, "result probe leaked");
        for delta in [-1i64, 0, 1] {
            let pool = Arc::new(MemoryPool::new((peak as i64 + delta) as u64));
            let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
            let attempt = produce(kind, source, workspace.clone());
            if delta < 0 {
                let error = attempt.err().context("result shared edge accepted")?;
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "result denial lost shared type"
                );
            } else {
                let result = attempt?;
                ensure!(
                    serde_json::to_vec(&result)? == expected && workspace.used() == retained,
                    "result edge changed JSON/owner"
                );
                drop(result);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "result edge leaked"
            );
        }
        let local = Arc::new(Workspace::new(peak as usize - 1));
        let error = produce(kind, source, local.clone())
            .err()
            .context("result local edge accepted")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ) && local.used() == 0,
            "result local denial leaked or lost type"
        );
        let pool = Arc::new(MemoryPool::new(peak));
        let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let mut competitor =
            Reservation::for_workspace(Arc::new(Workspace::shared(1, pool.clone())));
        competitor.resize(1)?;
        let error = produce(kind, source, workspace.clone())
            .err()
            .context("result competitor did not deny")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && workspace.used() == 0
                && pool.usage().reserved_bytes == 1,
            "result denial changed competitor"
        );
        drop(competitor);
        let result = produce(kind, source, workspace.clone())?;
        ensure!(
            serde_json::to_vec(&result)? == expected,
            "result fresh retry changed bytes"
        );
        drop(result);
        ensure!(pool.usage().reserved_bytes == 0, "result retry leaked");
        let pool = Arc::new(MemoryPool::new(2 * peak));
        let workspace = Arc::new(Workspace::shared(LIMIT, pool.clone()));
        let first = produce(kind, source, workspace.clone())?;
        let second = produce(kind, source, workspace.clone())?;
        ensure!(
            pool.usage().reserved_bytes == 2 * retained,
            "concurrent result lost owner"
        );
        drop(first);
        ensure!(
            serde_json::to_vec(&second)? == expected && pool.usage().reserved_bytes == retained,
            "dropping sibling changed result"
        );
        drop(second);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "concurrent results leaked"
        );
        reports.push(json!({"name":name,"source_blake3":blake3::hash(source).to_hex().to_string(),"peak_bytes":peak,"retained_result_bytes":retained,"shared_edges":3,"typed_shared_denials":2,"typed_local_denials":1,"fresh_release_retries":1,"serialization_error_retains_owner":true,"concurrent_final_owner":true,"final_reserved_bytes":0}));
    }
    let workspace = Arc::new(Workspace::new(1));
    let called = std::cell::Cell::new(false);
    let error = Inspection::build(Reservation::for_workspace(workspace.clone()), 0, 0, || {
        called.set(true);
        json!({})
    })
    .err()
    .context("builder ran without admission")?;
    ensure!(
        !called.get()
            && matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            )
            && workspace.used() == 0,
        "result allocation preceded admission"
    );
    Ok(
        json!({"contract":"inspection-result-owner-v1","cases":reports,"denial_precedes_builder":true,"scope":"returned fixed-schema JSON trees; caller clones and native wire buffers excluded"}),
    )
}

#[cfg(test)]
#[test]
fn inspection_result_edges_and_serialization_lifetimes() -> Result<()> {
    println!("CHOPPER_INSPECTION_RESULT_CONTRACT {}", run()?);
    Ok(())
}
