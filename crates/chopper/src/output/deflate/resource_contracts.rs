use super::*;
use crate::{
    resources::{MemoryAdmission, MemoryPool},
    storage::Workspace,
};
use anyhow::{ensure, Context as _};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    sync::Arc,
};

struct Destination {
    workspace: Arc<Workspace>,
    bytes: Rc<RefCell<Vec<u8>>>,
    fail: Rc<Cell<bool>>,
    require_drop_grant: bool,
}
impl Write for Destination {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        assert_eq!(
            self.workspace.used(),
            CAPACITY as u64,
            "codec write lost grant"
        );
        if self.fail.get() {
            return Err(io::Error::other("destination sentinel"));
        }
        self.bytes.borrow_mut().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Drop for Destination {
    fn drop(&mut self) {
        if self.require_drop_grant {
            assert_eq!(
                self.workspace.used(),
                CAPACITY as u64,
                "codec drop lost grant"
            );
        }
    }
}

pub(crate) fn run() -> Result<serde_json::Value> {
    let mut edges = 0;
    for gzip in [false, true] {
        for shared in [false, true] {
            for limit in [CAPACITY - 1, CAPACITY, CAPACITY + 1] {
                let pool = Arc::new(MemoryPool::new(if shared {
                    limit as u64
                } else {
                    u64::MAX
                }));
                let workspace = Arc::new(if shared {
                    Workspace::shared(CAPACITY + 1, pool.clone())
                } else {
                    Workspace::new(limit)
                });
                let memory = Reservation::for_workspace(workspace.clone());
                let result = if gzip {
                    super::gzip(io::sink(), memory).and_then(|mut codec| {
                        codec.write_all(b"payload")?;
                        codec.finish(flate2::write::GzEncoder::finish)?;
                        Ok(())
                    })
                } else {
                    raw(io::sink(), memory).and_then(|mut codec| {
                        codec.write_all(b"payload")?;
                        codec.finish(flate2::write::DeflateEncoder::finish)?;
                        Ok(())
                    })
                };
                if limit < CAPACITY {
                    let error = result.err().context("codec edge accepted")?;
                    ensure!(
                        matches!(
                            (shared, error.downcast_ref::<MemoryAdmission>()),
                            (true, Some(MemoryAdmission::Shared { .. }))
                                | (false, Some(MemoryAdmission::Local))
                        ),
                        "codec denial lost type"
                    );
                } else {
                    result?;
                }
                ensure!(
                    workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                    "codec edge leaked"
                );
                edges += 1;
            }
        }
    }
    // Admission must precede the codec factory (all internal allocations).
    let workspace = Arc::new(Workspace::new(CAPACITY - 1));
    let mut constructed = false;
    let result = Encoder::new(Reservation::for_workspace(workspace.clone()), || {
        constructed = true;
    });
    ensure!(
        result.is_err() && !constructed && workspace.used() == 0,
        "denied codec constructed"
    );

    let pool = Arc::new(MemoryPool::new((2 * CAPACITY) as u64));
    let workspace = Arc::new(Workspace::shared(3 * CAPACITY, pool.clone()));
    let first = gzip(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    let second = raw(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    let denied = gzip(io::sink(), Reservation::for_workspace(workspace.clone()))
        .err()
        .context("third codec admitted")?;
    ensure!(
        matches!(
            denied.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == (2 * CAPACITY) as u64,
        "denial changed concurrent owners"
    );
    drop(first);
    let retry = gzip(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    drop(second);
    drop(retry);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "concurrent codecs leaked"
    );

    let mut noise = Vec::new();
    let mut state = 0x123456789abcdefu64;
    for _ in 0..131073 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        noise.push(state as u8);
    }
    let payloads = [
        b"".as_slice(),
        "id,label\n1,\"café,世界\"\n".as_bytes(),
        noise.as_slice(),
    ];
    let mut cases = Vec::new();
    for is_gzip in [false, true] {
        for (index, payload) in payloads.iter().enumerate() {
            for mode in ["finish", "drop", "write-error", "finish-error"] {
                let workspace = Arc::new(Workspace::new(CAPACITY));
                let bytes = Rc::new(RefCell::new(Vec::new()));
                let fail = Rc::new(Cell::new(mode == "write-error"));
                let destination = Destination {
                    workspace: workspace.clone(),
                    bytes: bytes.clone(),
                    fail: fail.clone(),
                    require_drop_grant: true,
                };
                let mut success = false;
                macro_rules! exercise {
                    ($codec:expr,$finish:path) => {{
                        let mut codec = $codec?;
                        let wrote = codec.write_all(payload);
                        if mode == "drop" {
                            wrote?;
                            drop(codec);
                            success = true;
                        } else {
                            if mode == "finish-error" {
                                fail.set(true);
                            }
                            let result = codec.finish(|codec| {
                                let mut writer = $finish(codec)?;
                                ensure_grant(&workspace);
                                writer.require_drop_grant = false;
                                Ok(writer)
                            });
                            if mode == "finish" {
                                wrote?;
                                drop(result?);
                                success = true;
                            } else {
                                ensure!(
                                    wrote.is_err() || result.is_err(),
                                    "destination error lost"
                                );
                            }
                        }
                    }};
                }
                let memory = Reservation::for_workspace(workspace.clone());
                if is_gzip {
                    exercise!(gzip(destination, memory), flate2::write::GzEncoder::finish);
                } else {
                    exercise!(
                        raw(destination, memory),
                        flate2::write::DeflateEncoder::finish
                    );
                }
                ensure!(workspace.used() == 0, "codec {mode} leaked");
                if success {
                    let expected = if is_gzip {
                        let mut codec = flate2::GzBuilder::new()
                            .mtime(0)
                            .write(Vec::new(), Default::default());
                        codec.write_all(payload)?;
                        codec.finish()?
                    } else {
                        let mut codec =
                            flate2::write::DeflateEncoder::new(Vec::new(), Default::default());
                        codec.write_all(payload)?;
                        codec.finish()?
                    };
                    ensure!(*bytes.borrow() == expected, "codec byte parity changed");
                }
                cases.push(serde_json::json!({"gzip":is_gzip,"payload":index,"mode":mode,"exact_bytes_checked":success,"final_reserved_bytes":0}));
            }
        }
    }
    Ok(
        serde_json::json!({"contract":"output-deflate-codec-admission-v1","capacity_bytes":CAPACITY,"local_shared_edges":edges,"admission_before_construction":true,"concurrent_owner_release_retry":true,"cases":cases,"final_reserved_bytes":0}),
    )
}
fn ensure_grant(workspace: &Workspace) {
    assert_eq!(
        workspace.used(),
        CAPACITY as u64,
        "finish callback lost codec grant"
    );
}

#[test]
fn output_deflate_codec_admission() {
    println!("{}", run().unwrap());
}
