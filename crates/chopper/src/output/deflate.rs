//! Owned admission for the pinned miniz output compressor and flate2 buffers.
use crate::storage::Reservation;
use anyhow::Result;
use std::io::{self, Write};

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;

// Audited miniz_oxide 0.9.1: boxed CompressorOxide, boxed HuffmanOxide
// (three tables of 288 counts/codes/sizes), boxed LocalBuf, and three boxed
// HashBuffers arrays (dictionary padded by MAX_MATCH_LEN and two hash chains).
// wasm32 additionally boxes LZOxide's 64 KiB code buffer; native keeps it inline
// in CompressorOxide. flate2 1.1.10 adds a non-growing 32 KiB zio Vec and, for
// our metadata-free gzip builder, one ten-byte header (allow sixteen).
const CODE_BUFFER: usize = 64 * 1024;
const DICTIONARY: usize = 32 * 1024;
pub(super) const CAPACITY: usize =
    std::mem::size_of::<miniz_oxide::deflate::core::CompressorOxide>()
        + 3 * 288 * (2 + 2 + 1)
        + CODE_BUFFER * 13 / 10
        + DICTIONARY
        + 258
        + 2 * DICTIONARY * 2
        + if cfg!(target_arch = "wasm32") {
            CODE_BUFFER
        } else {
            0
        }
        + 32 * 1024
        + 16;

pub(super) struct Encoder<T> {
    codec: T,
    // Preserve the allowance through codec Drop's implicit finalization too.
    _memory: Reservation,
}

impl<T> Encoder<T> {
    fn new(mut memory: Reservation, create: impl FnOnce() -> T) -> Result<Self> {
        memory.resize(CAPACITY)?;
        Ok(Self {
            codec: create(),
            _memory: memory,
        })
    }

    pub(super) fn finish<W>(self, finish: impl FnOnce(T) -> io::Result<W>) -> io::Result<W> {
        let Self { codec, _memory } = self;
        let result = finish(codec);
        drop(_memory);
        result
    }
}

pub(super) fn gzip<W: Write>(
    writer: W,
    memory: Reservation,
) -> Result<Encoder<flate2::write::GzEncoder<W>>> {
    Encoder::new(memory, || {
        flate2::GzBuilder::new()
            .mtime(0)
            .write(writer, Default::default())
    })
}

pub(super) fn raw<W: Write>(
    writer: W,
    memory: Reservation,
) -> Result<Encoder<flate2::write::DeflateEncoder<W>>> {
    Encoder::new(memory, || {
        flate2::write::DeflateEncoder::new(writer, Default::default())
    })
}

impl<T: Write> Write for Encoder<T> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.codec.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.codec.flush()
    }
}
