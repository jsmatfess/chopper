//! Ordered block compression for single gzip streams and ZIP members.
use super::deflate::{self, BlockEncoder, BLOCK_BYTES, COMPRESSED_BLOCK_BYTES};
use crate::storage::{Context, Reservation};
use chopper_core::{Compression, Job};
use std::io::{self, Write};

#[cfg(target_os = "wasi")]
pub(super) mod hosted_files;

const MIN_PARALLEL_BYTES: u64 = (8 * BLOCK_BYTES) as u64;
const MIN_CAPPED_SOURCE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_BLOCK_WORKERS: usize = 4;
const GZIP_HEADER: &[u8] = &[0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 255];

pub(super) fn workers(job: &Job, ctx: &Context, bytes: u64) -> usize {
    if job.compression == Compression::None || bytes < MIN_PARALLEL_BYTES {
        return 1;
    }
    #[cfg(not(target_os = "wasi"))]
    let available = ctx.workers();
    #[cfg(target_os = "wasi")]
    let available = if job.resources.workers == 1 {
        1
    } else {
        hosted::available(ctx)
    };
    let affordable = ctx.working_headroom() / slot_cost() as u64;
    available
        .min(MAX_BLOCK_WORKERS)
        .min(affordable as usize)
        .max(1)
}

pub(super) fn direct_workers(job: &Job, ctx: &Context) -> usize {
    if direct_candidate(job) {
        let blocks = job.limits.bytes.map_or(MAX_BLOCK_WORKERS as u64, |limit| {
            limit.div_ceil(BLOCK_BYTES as u64)
        });
        workers(job, ctx, MIN_PARALLEL_BYTES).min(blocks.min(MAX_BLOCK_WORKERS as u64) as usize)
    } else {
        1
    }
}

pub(crate) fn direct_candidate(job: &Job) -> bool {
    if job.compression == Compression::None || job.limits.rows.is_some() {
        return false;
    }
    let cap = job.limits.bytes.unwrap_or(u64::MAX);
    let source = std::fs::metadata(&job.input).map_or(0, |source| source.len());
    source.min(cap) >= MIN_PARALLEL_BYTES
        || (source >= MIN_CAPPED_SOURCE_BYTES && cap >= 2 * BLOCK_BYTES as u64)
}

const fn slot_cost() -> usize {
    deflate::BLOCK_WORKING_BYTES + std::mem::size_of::<Block>()
}

pub(super) fn reserve(ctx: &Context, workers: usize) -> Option<Reservation> {
    if workers < 2 {
        return None;
    }
    let mut memory = Reservation::new(ctx);
    memory.resize(workers * slot_cost()).ok()?;
    Some(memory)
}

struct Block {
    input: Vec<u8>,
    output: Vec<u8>,
    codec: Option<BlockEncoder>,
    result: io::Result<usize>,
}

impl Block {
    fn new() -> Self {
        Self {
            input: Vec::with_capacity(BLOCK_BYTES),
            output: vec![0; COMPRESSED_BLOCK_BYTES],
            codec: None,
            result: Ok(0),
        }
    }

    fn local(&mut self) {
        self.result = self
            .codec
            .get_or_insert_with(BlockEncoder::default)
            .encode(&self.input, &mut self.output);
    }

    fn write_to(&mut self, writer: &mut impl Write) -> io::Result<()> {
        let bytes = std::mem::replace(&mut self.result, Ok(0))?;
        writer.write_all(&self.output[..bytes])?;
        self.input.clear();
        Ok(())
    }
}

struct Gzip {
    checksum: crc32fast::Hasher,
    bytes: u32,
}

impl Gzip {
    fn start(mut writer: impl Write) -> io::Result<Self> {
        writer.write_all(GZIP_HEADER)?;
        Ok(Self {
            checksum: crc32fast::Hasher::new(),
            bytes: 0,
        })
    }

    fn update(&mut self, bytes: &[u8]) {
        self.checksum.update(bytes);
        self.bytes = self.bytes.wrapping_add(bytes.len() as u32);
    }

    fn finish(self, mut writer: impl Write) -> io::Result<()> {
        writer.write_all(&self.checksum.finalize().to_le_bytes())?;
        writer.write_all(&self.bytes.to_le_bytes())
    }
}

pub(super) struct Encoder<W> {
    writer: W,
    blocks: Vec<Block>,
    next: usize,
    gzip: Option<Gzip>,
    ctx: Context,
    _memory: Reservation,
}

impl<W: Write> Encoder<W> {
    pub(super) fn new(
        mut writer: W,
        gzip: bool,
        ctx: &Context,
        workers: usize,
        memory: Reservation,
    ) -> io::Result<Self> {
        let gzip = if gzip {
            Some(Gzip::start(&mut writer)?)
        } else {
            None
        };
        let mut blocks = Vec::with_capacity(workers);
        blocks.resize_with(workers, Block::new);
        Ok(Self {
            writer,
            blocks,
            next: 0,
            gzip,
            ctx: ctx.clone(),
            _memory: memory,
        })
    }

    fn encode_pending(&mut self) -> io::Result<()> {
        let count = self.next
            + usize::from(
                self.next < self.blocks.len() && !self.blocks[self.next].input.is_empty(),
            );
        let blocks = &mut self.blocks[..count];
        self.ctx.check().map_err(io::Error::other)?;
        encode_blocks(&self.ctx, blocks);
        self.ctx.check().map_err(io::Error::other)?;
        for block in blocks {
            block.write_to(&mut self.writer)?;
        }
        self.next = 0;
        Ok(())
    }

    pub(super) fn finish(mut self) -> io::Result<W> {
        self.encode_pending()?;
        self.writer.write_all(deflate::FINAL_EMPTY_BLOCK)?;
        if let Some(gzip) = self.gzip.take() {
            gzip.finish(&mut self.writer)?;
        }
        Ok(self.writer)
    }
}

impl<W: Write> Write for Encoder<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if let Some(gzip) = &mut self.gzip {
            gzip.update(bytes);
        }
        let mut rest = bytes;
        while !rest.is_empty() {
            let block = &mut self.blocks[self.next];
            let take = (BLOCK_BYTES - block.input.len()).min(rest.len());
            block.input.extend_from_slice(&rest[..take]);
            rest = &rest[take..];
            if block.input.len() == BLOCK_BYTES {
                self.next += 1;
                if self.next == self.blocks.len() {
                    self.encode_pending()?;
                }
            }
        }
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.encode_pending()?;
        self.writer.flush()
    }
}

fn encode_blocks(ctx: &Context, blocks: &mut [Block]) {
    if blocks.is_empty() {
        return;
    }
    #[cfg(not(target_os = "wasi"))]
    if blocks.len() > 1 {
        ctx.for_each_batch(blocks, Block::local);
        ctx.deflate_workers(blocks.len());
        return;
    }
    #[cfg(target_os = "wasi")]
    {
        let workers = hosted::encode(blocks);
        if workers > 1 {
            ctx.deflate_workers(workers);
        }
    }
    #[cfg(not(target_os = "wasi"))]
    blocks[0].local();
}

#[cfg(target_os = "wasi")]
pub(crate) mod hosted {
    use super::{
        deflate, slot_cost, Block, Context, Reservation, BLOCK_BYTES, COMPRESSED_BLOCK_BYTES,
    };

    // Once a codec worker receives a block it retains its input/output vectors
    // and compressor through Run. The bridge's shared buffers have the same
    // payload capacities. Keep that grant until both external owners retire.
    const WORKER_BYTES: usize =
        deflate::BLOCK_WORKING_BYTES + BLOCK_BYTES + COMPRESSED_BLOCK_BYTES + 64;

    pub(crate) struct Lease {
        workers: usize,
        _memory: Reservation,
    }

    impl Drop for Lease {
        fn drop(&mut self) {
            unsafe { shutdown() };
        }
    }

    #[link(wasm_import_module = "chopper_compression")]
    extern "C" {
        fn worker_count() -> u32;
        fn submit(slot: u32, input: *const u8, bytes: u32) -> u32;
        fn collect(slot: u32, output: *mut u8, capacity: u32) -> u32;
        fn shutdown();
    }

    pub(super) fn available(ctx: &Context) -> usize {
        let ready = unsafe { worker_count() as usize }.min(super::MAX_BLOCK_WORKERS);
        let lease = ctx.hosted_deflate();
        if let Some(lease) = lease.get() {
            return ready.min(lease.workers);
        }
        let affordable = ctx.working_headroom() as usize / (WORKER_BYTES + slot_cost());
        let workers = ready.min(affordable);
        if workers < 2 {
            return 1;
        }
        let mut memory = Reservation::new(ctx);
        if memory.resize(workers * WORKER_BYTES).is_err() {
            return 1;
        }
        // This WASI host invokes the reactor on one engine thread.
        lease
            .get_or_init(|| Lease {
                workers,
                _memory: memory,
            })
            .workers
    }

    pub(super) fn encode(blocks: &mut [Block]) -> usize {
        let mut workers = 0;
        for (slot, block) in blocks.iter_mut().enumerate() {
            if block.input.is_empty() {
                continue;
            }
            let submitted =
                unsafe { submit(slot as u32, block.input.as_ptr(), block.input.len() as u32) };
            // Zero denotes a local fallback. Keep the input until collection.
            block.result = Ok(submitted as usize);
        }
        for (slot, block) in blocks.iter_mut().enumerate() {
            if block.input.is_empty() {
                continue;
            }
            if block.result.as_ref().is_ok_and(|submitted| *submitted != 0) {
                let bytes = unsafe {
                    collect(
                        slot as u32,
                        block.output.as_mut_ptr(),
                        block.output.len() as u32,
                    )
                } as usize;
                if bytes != 0 && bytes <= block.output.len() {
                    block.result = Ok(bytes);
                    workers += 1;
                    continue;
                }
            }
            block.local();
        }
        workers
    }
}
