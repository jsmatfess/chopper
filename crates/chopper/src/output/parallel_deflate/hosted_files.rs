//! Run independently framed prepared outputs in a bounded WASI codec batch.
use super::super::{
    output_name, publication_reader, CompletedChunk, OutputObservation, OutputPlan,
    PublicationBatch, PublicationName, PublicationPath, PublicationWriter, ZipTarget,
    PUBLICATION_BUFFER,
};
use super::{
    deflate, encode_blocks, reserve, workers, Block, Gzip, BLOCK_BYTES, MIN_PARALLEL_BYTES,
};
use crate::{
    observation::{physical, Status},
    storage::{Context, Reservation},
};
use anyhow::{Context as _, Result};
use chopper_core::{Compression, Job};
use std::{
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
};

const MIN_AVERAGE_FILE_BYTES: u64 = BLOCK_BYTES as u64;

pub(in crate::output) fn small(bytes: u64) -> bool {
    bytes < MIN_PARALLEL_BYTES
}

pub(in crate::output) fn batch_limit(job: &Job, ctx: &Context, plan: &OutputPlan) -> usize {
    if plan.files < 2
        || plan.bytes / plan.files < MIN_AVERAGE_FILE_BYTES
        || ctx.working_headroom() < 8 * 1024 * 1024
    {
        return 1;
    }
    workers(job, ctx, plan.bytes)
}

struct Member {
    body: Body,
    name: PublicationName,
    path: Option<PublicationPath>,
    offset: u64,
    remaining: u64,
}

enum Body {
    Gzip(PublicationWriter, Gzip),
    Zip(ZipTarget, crc32fast::Hasher),
}

impl Member {
    fn start(
        name: PublicationName,
        job: &Job,
        ctx: &Context,
        stage: &Path,
        offset: u64,
        remaining: u64,
    ) -> Result<Self> {
        let (body, path) = if job.compression == Compression::Zip {
            (
                Body::Zip(ZipTarget::spool(ctx, remaining)?, crc32fast::Hasher::new()),
                None,
            )
        } else {
            let path = PublicationPath::join(stage, name.as_str(), Reservation::new(ctx))?;
            let mut writer = PublicationWriter::new(&path, PUBLICATION_BUFFER, ctx)?;
            let gzip = Gzip::start(&mut writer)?;
            (Body::Gzip(writer, gzip), Some(path))
        };
        Ok(Self {
            body,
            name,
            path,
            offset,
            remaining,
        })
    }

    fn read(&mut self, input: &mut (impl Read + Seek), block: &mut Block) -> Result<()> {
        let len = self.remaining.min(BLOCK_BYTES as u64) as usize;
        if len != 0 {
            block.input.resize(len, 0);
            input.seek(SeekFrom::Start(self.offset))?;
            input.read_exact(&mut block.input)?;
            self.offset += len as u64;
            self.remaining -= len as u64;
            match &mut self.body {
                Body::Gzip(_, frame) => frame.update(&block.input),
                Body::Zip(_, crc) => crc.update(&block.input),
            }
        }
        Ok(())
    }

    fn write(&mut self, block: &mut Block) -> Result<usize> {
        let len = block.input.len();
        if len != 0 {
            match &mut self.body {
                Body::Gzip(writer, _) => block.write_to(writer)?,
                Body::Zip(writer, _) => block.write_to(writer)?,
            }
        }
        Ok(len)
    }

    fn finish(self) -> Result<CompletedChunk> {
        let Self {
            body, name, path, ..
        } = self;
        let (compressed, stored, crc) = match body {
            Body::Gzip(mut writer, frame) => {
                writer.write_all(deflate::FINAL_EMPTY_BLOCK)?;
                frame.finish(&mut writer)?;
                writer.sync_all()?;
                (
                    None,
                    std::fs::metadata(path.context("missing gzip path")?)?.len(),
                    0,
                )
            }
            Body::Zip(mut writer, crc) => {
                writer.write_all(deflate::FINAL_EMPTY_BLOCK)?;
                let stored = writer.len();
                (Some(writer), stored, crc.finalize())
            }
        };
        Ok(CompletedChunk {
            name,
            compressed,
            stored,
            crc,
        })
    }
}

pub(in crate::output) fn write_batch(
    batch: &mut PublicationBatch,
    plan: &OutputPlan,
    job: &Job,
    header: Option<&[String]>,
    stage: &Path,
    ctx: &Context,
) -> Result<bool> {
    let count = batch.tasks.len();
    if count < 2 {
        return Ok(false);
    }
    debug_assert!(batch.tasks.iter().all(|task| small(task.chunk.bytes)));
    let Some(_blocks) = reserve(ctx, count) else {
        return Ok(false);
    };
    let mut workspace = Reservation::new(ctx);
    if workspace
        .resize(count * std::mem::size_of::<Member>())
        .is_err()
    {
        return Ok(false);
    }
    let kind = if job.compression == Compression::Zip {
        physical::Kind::ZipDeflate
    } else {
        physical::Kind::GzipOutput
    };
    // One attempt represents the complete batch. Individual members share a
    // physical kind ID and overlapping attempts would mask earlier completions.
    let mut observation = OutputObservation::new(job, ctx, kind);
    let result = (|| {
        let mut members = Vec::with_capacity(count);
        let mut blocks = Vec::with_capacity(count);
        for task in &batch.tasks {
            let chunk = &task.chunk;
            let name = output_name(
                chunk.index,
                &chunk.group,
                job,
                header,
                Reservation::new(ctx),
            )?;
            members.push(Member::start(
                name,
                job,
                ctx,
                stage,
                chunk.offset,
                chunk.bytes,
            )?);
            blocks.push(Block::new());
        }
        let mut input = publication_reader(&plan.data, ctx)?;
        while members.iter().any(|member| member.remaining > 0) {
            ctx.check()?;
            for (member, block) in members.iter_mut().zip(&mut blocks) {
                member.read(&mut input, block)?;
            }
            encode_blocks(ctx, &mut blocks);
            for (member, block) in members.iter_mut().zip(&mut blocks) {
                let bytes = member.write(block)?;
                if let Some(observation) = &mut observation {
                    observation.add(bytes);
                }
            }
        }
        for (task, member) in batch.tasks.iter_mut().zip(members) {
            task.completed = Some(Ok(member.finish()?));
        }
        Ok(true)
    })();
    if let Some(observation) = &mut observation {
        observation.finish(
            result
                .as_ref()
                .err()
                .map_or(Status::Completed, physical::error_status),
        );
    }
    result
}
