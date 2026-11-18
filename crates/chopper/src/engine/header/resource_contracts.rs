use super::*;
use crate::resources::{MemoryAdmission, MemoryPool};

fn fixture() -> (Vec<String>, usize) {
    let mut fields = Vec::with_capacity(9);
    let mut bytes = fields.capacity() * std::mem::size_of::<String>();
    for (text, capacity) in [("duplicate", 128), ("", 96), ("duplicate\n\u{754c}", 64)] {
        let mut field = String::with_capacity(capacity);
        field.push_str(text);
        bytes += field.capacity();
        fields.push(field);
    }
    (fields, bytes)
}
fn build(mut memory: Reservation) -> Result<Header> {
    let (fields, bytes) = fixture();
    memory.resize(bytes)?;
    Header::admit(fields, memory)
}
pub(in crate::engine) fn run() -> Result<serde_json::Value> {
    let (fields, bytes) = fixture();
    let canonical = serde_json::to_vec(&fields)?;
    let required = bytes + Shared::<Vec<String>>::controller_bytes();
    drop(fields);
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
                let error = result.err().context("header controller edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (false, Some(MemoryAdmission::Local))
                            | (true, Some(MemoryAdmission::Shared { .. }))
                    ),
                    "header edge lost denial type"
                );
            } else {
                let header = result?;
                ensure!(
                    header.reserved_bytes() == required as u64
                        && workspace.used() == required as u64
                        && serde_json::to_vec(&header)? == canonical
                        && header.capacity() == 9,
                    "header capacity or schema changed"
                );
                let copy = header.clone();
                ensure!(
                    std::ptr::eq(copy.as_ptr(), header.as_ptr())
                        && workspace.used() == required as u64,
                    "header clone copied fields or grant"
                );
                drop(header);
                ensure!(
                    copy.len() == 3 && workspace.used() == required as u64,
                    "header clone lost grant"
                );
                drop(copy);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "header edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * required - 1) as u64));
    let workspace = Arc::new(Workspace::shared(2 * required, pool.clone()));
    let first = build(Reservation::for_workspace(workspace.clone()))?;
    let error = build(Reservation::for_workspace(workspace.clone()))
        .err()
        .context("competing header admitted")?;
    ensure!(
        matches!(
            error.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == required as u64,
        "header competition changed live owner"
    );
    drop(first);
    let retry = build(Reservation::for_workspace(workspace.clone()))?;
    let decoded: Header = serde_json::from_slice(&serde_json::to_vec(&retry)?)?;
    ensure!(
        decoded == retry && decoded.reserved_bytes() == 0,
        "caller header deserialization changed"
    );
    drop(decoded);
    drop(retry);
    ensure!(pool.usage().reserved_bytes == 0, "header retry leaked");
    #[cfg(not(target_os = "wasi"))]
    {
        let header = build(Reservation::for_workspace(workspace.clone()))?;
        let barrier = Arc::new(std::sync::Barrier::new(5));
        std::thread::scope(|scope| {
            for _ in 0..4 {
                let copy = header.clone();
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(copy);
                });
            }
            drop(header);
            assert_eq!(workspace.used(), required as u64);
            barrier.wait();
        });
        ensure!(workspace.used() == 0, "concurrent header drop leaked");
    }
    Ok(
        json!({"contract":"analysis-header-shared-owner-v1","retained_fixture_bytes":required,"spare_vector_and_string_capacity":true,"local_shared_edges":6,"clone_shares_fields_and_grant":true,"canonical_serialization_equal":true,"caller_deserialization_equal":true,"competing_owner_release_retry":true,"native_concurrent_last_drop":cfg!(not(target_os="wasi")),"public_lifetimes":lifetimes()?,"final_reserved_bytes":0}),
    )
}

fn lifetimes() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    let dir = tempfile::tempdir_in("/tmp")?;
    #[cfg(not(target_os = "wasi"))]
    let dir = tempfile::tempdir()?;
    let input = dir.path().join("input.csv");
    std::fs::write(&input, b"id,text\n1,first\n2,last\n")?;
    struct Reject;
    impl std::io::Write for Reject {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("header serialization sentinel"))
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    for execute in [false, true] {
        let output = dir
            .path()
            .join(if execute { "published" } else { "discarded" });
        let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
        let prepared = prepare_with_memory_pool(
            Job {
                input: input.to_string_lossy().into_owned(),
                output: output.to_string_lossy().into_owned(),
                random_seed: Some("header-owner".into()),
                resources: Resources {
                    temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                    ..Resources::default()
                },
                ..Job::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let ctx = prepared.ctx.clone();
        let analysis = prepared.analysis.clone();
        let header = analysis.header.as_ref().unwrap();
        let payload = header.capacity() * std::mem::size_of::<String>()
            + header.iter().map(String::capacity).sum::<usize>();
        ensure!(
            header.reserved_bytes() == (payload + Shared::<Vec<String>>::controller_bytes()) as u64
                && std::ptr::eq(
                    header.as_ptr(),
                    prepared.analysis.header.as_ref().unwrap().as_ptr()
                ),
            "Analysis clone header owner changed"
        );
        let retained = analysis.warnings.reserved_bytes()
            + analysis.timings.reserved_bytes()
            + analysis.diagnostics.reserved_bytes()
            + analysis.text_reserved_bytes()
            + header.reserved_bytes()
            + analysis.preview.reserved_bytes();
        let before = pool.usage().reserved_bytes;
        ensure!(
            serde_json::to_writer(Reject, header).is_err() && pool.usage().reserved_bytes == before,
            "header serialization failure released grant"
        );
        if execute {
            let result = prepared.execute()?;
            ensure!(
                pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained
                    && std::fs::read(output.join("part-00000001.csv"))?
                        == b"id,text\n1,first\n2,last\n",
                "execute detached header or changed CSV"
            );
            drop(result);
        } else {
            drop(prepared);
            ensure!(!output.try_exists()?, "discarded preparation published");
        }
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes() + retained
                && serde_json::to_value(&analysis.header)? == json!(["id", "text"]),
            "retained Analysis lost header charge/data"
        );
        drop(analysis);
        ensure!(
            pool.usage().reserved_bytes == ctx.directory_reserved_bytes(),
            "final Analysis drop retained header"
        );
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "header context cleanup leaked"
        );
    }
    for (headers, data, expected) in [
        (true, "", false),
        (false, "id,text\n1,first\n", false),
        (true, "id,text\n", true),
    ] {
        std::fs::write(&input, data)?;
        let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
        let mut job = Job {
            input: input.to_string_lossy().into_owned(),
            random_seed: Some("header-presence".into()),
            resources: Resources {
                temp_dir: Some(dir.path().to_string_lossy().into_owned()),
                ..Resources::default()
            },
            ..Job::default()
        };
        job.input_csv.headers = headers;
        job.output_csv.headers = false;
        let prepared = prepare_with_memory_pool(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        ensure!(
            prepared.analysis.header.is_some() == expected,
            "empty/headerless/header-only presence changed"
        );
        drop(prepared);
        ensure!(
            pool.usage().reserved_bytes == 0,
            "header presence case leaked"
        );
    }
    let temporary = dir.path().join("header-temporary");
    std::fs::create_dir(&temporary)?;
    for valid in [false, true] {
        let data = if valid {
            "id,name,name,\"\",\"line\n\u{754c}\"\n1,a,b,\"\",tail\n"
        } else {
            "\"unterminated header"
        };
        std::fs::write(&input, data)?;
        let output = dir.path().join(if valid {
            "shape-valid"
        } else {
            "shape-invalid"
        });
        let pool = Arc::new(MemoryPool::new(8 * 1024 * 1024));
        let result = prepare_with_memory_pool(
            Job {
                input: input.to_string_lossy().into_owned(),
                output: output.to_string_lossy().into_owned(),
                random_seed: Some("header-shape".into()),
                resources: Resources {
                    temp_dir: Some(temporary.to_string_lossy().into_owned()),
                    ..Resources::default()
                },
                ..Job::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        );
        if valid {
            let prepared = result?;
            ensure!(
                serde_json::to_value(&prepared.analysis.header)?
                    == json!(["id", "name", "name", "", "line\n\u{754c}"]),
                "header names/order/empty fields changed"
            );
            drop(prepared.execute()?);
            let actual = std::fs::read(output.join("part-00000001.csv"))?;
            ensure!(
                actual == data.as_bytes(),
                "header shape publication bytes changed: {actual:?}"
            );
        } else {
            let error = result.err().context("malformed header accepted")?;
            ensure!(
                format!("{error:#}").contains("unterminated quoted field")
                    && !output.try_exists()?,
                "header failure changed or published"
            );
        }
        ensure!(
            pool.usage().reserved_bytes == 0 && std::fs::read_dir(&temporary)?.next().is_none(),
            "header shape/error cleanup leaked"
        );
    }
    dir.close()?;
    Ok(
        json!({"analysis_clone_shares_header":true,"serialization_failure_retains_owner":true,"prepared_drop_retains_header":true,"execution_retains_header":true,"exact_csv_parity":true,"last_clone_release":true,"empty_headerless_header_only_presence":true,"duplicate_empty_multiline_unicode_header_parity":true,"malformed_header_cleanup":true,"fixture_directory_removed":true,"final_reserved_bytes":0}),
    )
}

#[test]
fn analysis_header_shared_admission_and_lifetime() {
    println!("{}", run().unwrap());
}
