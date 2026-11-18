use super::*;
use crate::{
    resources::{MemoryAdmission, MemoryPool},
    storage::Workspace,
};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
    sync::Arc,
};

struct Destination {
    workspace: Arc<Workspace>,
    capacity: usize,
    bytes: Rc<RefCell<Vec<u8>>>,
    fail: Rc<Cell<bool>>,
    require_drop_grant: bool,
}
impl Write for Destination {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        assert_eq!(
            self.workspace.used(),
            self.capacity as u64,
            "Zstandard write lost grant"
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
                self.capacity as u64,
                "Zstandard destination drop lost grant"
            );
        }
    }
}

fn checked(result: zstd_safe::SafeResult) -> Result<usize> {
    result.map_err(|code| anyhow::anyhow!("Zstandard probe: {}", zstd_safe::get_error_name(code)))
}
fn context_probe(payload: &[u8], allowance: usize) -> Result<usize> {
    use zstd_sys::ZSTD_EndDirective::{ZSTD_e_continue, ZSTD_e_end};
    let mut context = zstd_safe::CCtx::create();
    checked(context.set_parameter(zstd_safe::CParameter::CompressionLevel(LEVEL)))?;
    checked(context.load_dictionary(&[]))?;
    checked(context.set_parameter(zstd_safe::CParameter::WindowLog(WINDOW_LOG)))?;
    checked(context.set_parameter(zstd_safe::CParameter::ChecksumFlag(true)))?;
    let mut peak = context.sizeof();
    let mut buffer = [0u8; 32 * 1024];
    for chunk in payload.chunks(65536) {
        let mut input = zstd_safe::InBuffer::around(chunk);
        while input.pos < input.src.len() {
            let mut output = zstd_safe::OutBuffer::around(&mut buffer[..]);
            checked(context.compress_stream2(&mut output, &mut input, ZSTD_e_continue))?;
            peak = peak.max(context.sizeof());
        }
    }
    loop {
        let mut input = zstd_safe::InBuffer::around(&[]);
        let mut output = zstd_safe::OutBuffer::around(&mut buffer[..]);
        let remaining = checked(context.compress_stream2(&mut output, &mut input, ZSTD_e_end))?;
        peak = peak.max(context.sizeof());
        if remaining == 0 {
            break;
        }
    }
    ensure!(
        peak <= allowance - OUTPUT_BUFFER,
        "Zstandard context exceeded estimator"
    );
    Ok(peak)
}

#[cfg(target_os = "wasi")]
fn wasm_shim_contract() -> Result<()> {
    use std::{ffi::c_void, hint::black_box, mem::size_of, ptr::null_mut};

    // Resolve the same zstd-sys symbols used by the vendored C codec.
    extern "C" {
        fn rust_zstd_wasm_shim_malloc(size: usize) -> *mut c_void;
        fn rust_zstd_wasm_shim_calloc(nmemb: usize, size: usize) -> *mut c_void;
        fn rust_zstd_wasm_shim_free(ptr: *mut c_void);
    }

    // SAFETY: These calls pass only sizes and a null pointer accepted by free.
    unsafe {
        ensure!(
            rust_zstd_wasm_shim_calloc(black_box(usize::MAX / 2 + 1), 2).is_null(),
            "WASI Zstandard shim accepted calloc overflow"
        );
        ensure!(
            rust_zstd_wasm_shim_malloc(black_box(usize::MAX)).is_null(),
            "WASI Zstandard shim accepted header overflow"
        );
        ensure!(
            rust_zstd_wasm_shim_malloc(black_box(isize::MAX as usize - size_of::<usize>()))
                .is_null(),
            "WASI Zstandard shim accepted an invalid aligned layout"
        );
        rust_zstd_wasm_shim_free(black_box(null_mut()));
    }
    Ok(())
}

pub(crate) fn run() -> Result<serde_json::Value> {
    #[cfg(target_os = "wasi")]
    wasm_shim_contract()?;

    let allowance = capacity()?;
    for shared in [false, true] {
        for limit in [allowance - 1, allowance, allowance + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(allowance + 1, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let result = Encoder::new(io::sink(), Reservation::for_workspace(workspace.clone()));
            if limit < allowance {
                let error = result.err().context("Zstandard edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "Zstandard denial lost type"
                );
            } else {
                let mut codec = result?;
                codec.write_all(b"payload")?;
                codec.finish()?;
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "Zstandard edge leaked"
            );
        }
    }
    let pool = Arc::new(MemoryPool::new((2 * allowance) as u64));
    let workspace = Arc::new(Workspace::shared(3 * allowance, pool.clone()));
    let first = Encoder::new(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    let second = Encoder::new(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    let denied = Encoder::new(io::sink(), Reservation::for_workspace(workspace.clone()))
        .err()
        .context("third Zstandard encoder accepted")?;
    ensure!(
        matches!(
            denied.downcast_ref::<MemoryAdmission>(),
            Some(MemoryAdmission::Shared { .. })
        ) && workspace.used() == (2 * allowance) as u64,
        "Zstandard competitor ownership changed"
    );
    drop(first);
    let retry = Encoder::new(io::sink(), Reservation::for_workspace(workspace.clone()))?;
    drop(second);
    drop(retry);
    ensure!(
        workspace.used() == 0 && pool.usage().reserved_bytes == 0,
        "Zstandard competing owner leaked"
    );

    let mut noise = Vec::new();
    let mut state = 0x123456789abcdefu64;
    for _ in 0..(3 * 1024 * 1024 + 1) {
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
    let mut observed = Vec::new();
    for (index, payload) in payloads.iter().enumerate() {
        observed.push(context_probe(payload, allowance)?);
        for mode in ["finish", "drop", "write-error", "finish-error"] {
            let workspace = Arc::new(Workspace::new(allowance));
            let bytes = Rc::new(RefCell::new(Vec::new()));
            let fail = Rc::new(Cell::new(mode == "write-error"));
            let destination = Destination {
                workspace: workspace.clone(),
                capacity: allowance,
                bytes: bytes.clone(),
                fail: fail.clone(),
                require_drop_grant: true,
            };
            let mut codec =
                Encoder::new(destination, Reservation::for_workspace(workspace.clone()))?;
            let wrote = codec.write_all(payload);
            let success = mode == "finish" || mode == "drop";
            if mode == "drop" {
                wrote?;
                drop(codec);
            } else {
                if mode == "finish-error" {
                    fail.set(true);
                }
                let result = codec.finish();
                if mode == "finish" {
                    wrote?;
                    let mut writer = result?;
                    writer.require_drop_grant = false;
                    drop(writer);
                } else {
                    ensure!(
                        wrote.is_err() || result.is_err(),
                        "Zstandard destination error lost"
                    );
                }
            }
            ensure!(workspace.used() == 0, "Zstandard {mode} leaked");
            if success {
                let expected = Rc::new(RefCell::new(Vec::new()));
                struct Collect(Rc<RefCell<Vec<u8>>>);
                impl Write for Collect {
                    fn write(&mut self, b: &[u8]) -> io::Result<usize> {
                        self.0.borrow_mut().extend_from_slice(b);
                        Ok(b.len())
                    }
                    fn flush(&mut self) -> io::Result<()> {
                        Ok(())
                    }
                }
                let mut legacy =
                    zstd::stream::write::Encoder::new(Collect(expected.clone()), LEVEL)?;
                legacy.window_log(WINDOW_LOG)?;
                legacy.include_checksum(true)?;
                legacy.write_all(payload)?;
                if mode == "finish" {
                    legacy.finish()?;
                } else {
                    drop(legacy);
                }
                ensure!(
                    *bytes.borrow() == *expected.borrow(),
                    "Zstandard exact compressed parity changed"
                );
            }
            cases.push(serde_json::json!({"payload":index,"mode":mode,"exact_bytes_checked":success,"final_reserved_bytes":0}));
        }
    }
    Ok(
        serde_json::json!({"contract":"output-zstandard-codec-admission-v1","capacity_bytes":allowance,"context_estimate_bytes":allowance-OUTPUT_BUFFER,"observed_context_bytes":observed,"local_shared_edges":6,"concurrent_owner_release_retry":true,"cases":cases,"final_reserved_bytes":0}),
    )
}

#[test]
fn output_zstandard_codec_admission() {
    println!("{}", run().unwrap());
}
