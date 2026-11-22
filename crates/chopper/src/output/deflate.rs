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

pub const BLOCK_BYTES: usize = 256 * 1024;
pub const COMPRESSED_BLOCK_BYTES: usize = BLOCK_BYTES + BLOCK_BYTES / 8 + 256;
pub(super) const BLOCK_WORKING_BYTES: usize = CAPACITY + BLOCK_BYTES + COMPRESSED_BLOCK_BYTES;

/// Each block begins with an empty dictionary. Sync flush ends it on a byte
/// boundary with BFINAL clear, so blocks can be written in input order.
pub struct BlockEncoder(flate2::Compress);

impl Default for BlockEncoder {
    fn default() -> Self {
        Self(flate2::Compress::new(flate2::Compression::default(), false))
    }
}

impl BlockEncoder {
    pub fn encode(&mut self, input: &[u8], output: &mut [u8]) -> io::Result<usize> {
        if input.is_empty() || input.len() > BLOCK_BYTES || output.len() < COMPRESSED_BLOCK_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid deflate block size",
            ));
        }
        self.0.reset();
        self.0
            .compress(input, output, flate2::FlushCompress::Sync)
            .map_err(io::Error::other)?;
        let written = self.0.total_out() as usize;
        if self.0.total_in() != input.len() as u64
            || written == output.len()
            || !output[..written].ends_with(&[0, 0, 255, 255])
        {
            return Err(io::Error::other(
                "deflate block did not finish its sync flush",
            ));
        }
        Ok(written)
    }
}

pub(super) const FINAL_EMPTY_BLOCK: &[u8] = &[3, 0];

impl<T: Write> Write for Encoder<T> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.codec.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.codec.flush()
    }
}

#[cfg(test)]
mod block_tests {
    use super::*;
    use std::io::Read;

    #[test]
    fn independent_blocks_decode_as_one_stream() -> Result<()> {
        let mut noise = vec![0; BLOCK_BYTES];
        let mut state = 1u32;
        for byte in &mut noise {
            state ^= state << 13;
            state ^= state >> 17;
            state ^= state << 5;
            *byte = state as u8;
        }
        let repeated = vec![b'z'; BLOCK_BYTES];
        let input = [&noise[..], &repeated[..], b"one byte short of nothing"];
        let mut encoder = BlockEncoder::default();
        let mut scratch = vec![0; COMPRESSED_BLOCK_BYTES];
        let mut stream = Vec::new();
        for block in input {
            let bytes = encoder.encode(block, &mut scratch)?;
            stream.extend_from_slice(&scratch[..bytes]);
        }
        stream.extend_from_slice(FINAL_EMPTY_BLOCK);
        let mut decoded = Vec::new();
        flate2::read::DeflateDecoder::new(stream.as_slice()).read_to_end(&mut decoded)?;
        assert_eq!(decoded, input.concat());
        Ok(())
    }
}
