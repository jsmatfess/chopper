//! Admission for the pinned single-threaded, dictionary-free output stream.
use crate::storage::Reservation;
use anyhow::{ensure, Context as _, Result};
use std::io::{self, Write};

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;

const LEVEL: i32 = 3;
const WINDOW_LOG: u32 = 21;
const OUTPUT_BUFFER: usize = 32 * 1024;

pub(super) fn capacity() -> Result<usize> {
    // No pointers or contexts are passed: these APIs compute a size from value
    // parameters. Exact crate pins and this version check retain the audited C
    // implementation. The estimator covers both row-matchfinder choices.
    let version = unsafe { zstd_sys::ZSTD_versionNumber() };
    ensure!(
        version == 10507,
        "Zstandard allocation audit requires version 1.5.7"
    );
    let code = unsafe {
        let mut parameters = zstd_sys::ZSTD_getCParams(LEVEL, 0, 0);
        parameters.windowLog = WINDOW_LOG;
        zstd_sys::ZSTD_estimateCStreamSize_usingCParams(parameters)
    };
    // Safety: this pure status predicate accepts any size_t result.
    ensure!(
        unsafe { zstd_sys::ZSTD_isError(code) } == 0,
        "Zstandard stream estimate failed: {}",
        zstd_safe::get_error_name(code)
    );
    // The C estimate includes the context and all buffered streaming workspace.
    // Source-audited resize frees old workspace before allocating its replacement.
    // zstd-rs separately owns this non-growing output Vec.
    code.checked_add(OUTPUT_BUFFER)
        .context("Zstandard allocation allowance overflow")
}

pub(super) struct Encoder<W: Write> {
    codec: zstd::stream::write::Encoder<'static, W>,
    _memory: Reservation,
}
impl<W: Write> Encoder<W> {
    pub(super) fn new(writer: W, mut memory: Reservation) -> Result<Self> {
        memory.resize(capacity()?)?;
        let mut codec = zstd::stream::write::Encoder::new(writer, LEVEL)?;
        codec.window_log(WINDOW_LOG)?;
        codec.include_checksum(true)?;
        Ok(Self {
            codec,
            _memory: memory,
        })
    }
    pub(super) fn finish(self) -> io::Result<W> {
        let Self { codec, _memory } = self;
        let result = codec.finish();
        drop(_memory);
        result
    }
}
impl<W: Write> Write for Encoder<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.codec.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.codec.flush()
    }
}
