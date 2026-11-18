//! Private publication adapter for the shared encoded chunk writer.
use super::*;

struct OpenChunk {
    sink: ObservedSink,
    name: PublicationName,
    path: Option<PublicationPath>,
    crc: crc32fast::Hasher,
}

pub(crate) struct DirectPublication {
    current: Option<OpenChunk>,
    archive: Option<ZipStream>,
    records: BufWriter<DiskFile>,
    _records_buffer: Reservation,
    destination: std::path::PathBuf,
    existing_empty: bool,
    // Destroy all open handles before removing an abandoned staging directory.
    stage: JobDirectory,
}
impl DirectPublication {
    pub(super) fn new(job: &Job, ctx: &Context) -> Result<Self> {
        let destination = std::path::absolute(&job.output)?;
        let existing_empty = empty_destination(&destination)?;
        let parent = destination.parent().context("invalid output directory")?;
        ensure!(parent.is_dir(), "output parent directory does not exist");
        let stage = ctx.staging_directory(parent)?;
        let mut buffer = Reservation::new(ctx);
        buffer.resize(PLAN_CATALOG_BUFFER)?;
        let records = BufWriter::with_capacity(PLAN_CATALOG_BUFFER, ctx.file()?);
        let archive = if job.compression == Compression::Zip {
            Some(ZipStream::observed(
                PublicationPath::join(stage.path(), "outputs.zip", Reservation::new(ctx))?,
                job,
                ctx,
            )?)
        } else {
            None
        };
        Ok(Self {
            current: None,
            archive,
            records,
            _records_buffer: buffer,
            destination,
            existing_empty,
            stage,
        })
    }
    pub(super) fn open(&mut self, chunk: &Chunk, job: &Job, ctx: &Context) -> Result<()> {
        ensure!(self.current.is_none(), "direct chunk already open");
        // This adapter is deliberately limited to the initial, limits-only group.
        ensure!(
            chunk.group.lineage.is_empty(),
            "direct output requires an empty pipeline"
        );
        let name = output_name(chunk.index, &chunk.group, job, None, Reservation::new(ctx))?;
        let (sink, path) = open_sink(&name, job, self.stage.path(), ctx)?;
        self.current = Some(OpenChunk {
            sink,
            name,
            path,
            crc: crc32fast::Hasher::new(),
        });
        Ok(())
    }
    pub(super) fn write_all(&mut self, bytes: &[u8]) -> Result<()> {
        let current = self.current.as_mut().context("direct chunk is not open")?;
        if self.archive.is_some() {
            current.crc.update(bytes);
        }
        current.sink.write_all(bytes)?;
        Ok(())
    }
    pub(super) fn close(&mut self, chunk: &Chunk, job: &Job, ctx: &Context) -> Result<()> {
        ctx.check()?;
        let OpenChunk {
            sink,
            name,
            path,
            crc,
        } = self.current.take().context("direct chunk is not open")?;
        let compressed = sink.finish()?;
        let stored = if let Some(file) = &compressed {
            file.len()
        } else {
            std::fs::metadata(path.as_ref().context("missing direct output path")?)?.len()
        };
        if let Some(compressed) = compressed {
            self.archive
                .as_mut()
                .context("missing direct ZIP archive")?
                .add(
                    name.as_str(),
                    publication_reader(&compressed, ctx)?,
                    stored,
                    chunk.bytes,
                    crc.finalize(),
                    ctx,
                )?;
        }
        serde_json::to_writer(
            &mut self.records,
            &OutputRecord {
                compressed_target_exceeded: job
                    .limits
                    .compressed_bytes
                    .is_some_and(|limit| stored > limit),
                csv_bytes: chunk.bytes,
                lineage: &chunk.group.lineage,
                path: name.as_str(),
                rows: chunk.rows,
                stored_bytes: stored,
                kind: "output",
            },
        )?;
        self.records.write_all(b"\n")?;
        Ok(())
    }
    pub(super) fn seal(&mut self) -> Result<()> {
        ensure!(self.current.is_none(), "unfinished direct chunk");
        self.records.flush()?;
        Ok(())
    }
    pub(crate) fn publish(
        mut self,
        job: &Job,
        analysis: &crate::engine::Analysis,
        ctx: &Context,
    ) -> Result<EnginePublication> {
        ctx.pressure_boundary();
        ensure!(self.current.is_none(), "unfinished direct chunk");
        let manifest_path =
            PublicationPath::join(self.stage.path(), "manifest.jsonl", Reservation::new(ctx))?;
        let mut manifest = PublicationWriter::new(&manifest_path, MANIFEST_BUFFER, ctx)?;
        serde_json::to_writer(
            &mut manifest,
            &job_manifest::ManifestTree::build(job, analysis, Reservation::new(ctx))?,
        )?;
        manifest.write_all(b"\n")?;
        let mut input = publication_reader(self.records.get_ref(), ctx)?;
        let mut bytes = [0u8; 8192];
        loop {
            ctx.check()?;
            let count = input.read(&mut bytes)?;
            if count == 0 {
                break;
            }
            manifest.write_all(&bytes[..count])?;
        }
        drop(input);
        manifest.sync_all()?;
        drop(manifest);
        finish_archive(self.archive.take(), manifest_path.as_ref(), ctx)?;
        commit_directory(&mut self.stage, &self.destination, self.existing_empty, ctx)?;
        // Publication is the commit point, as for prepared execution.
        (ctx.notify)(Progress {
            phase: crate::storage::ProgressPhase::literal("Complete"),
            rows: analysis.rows,
            temp_bytes: ctx.used(),
        });
        Ok(EnginePublication(()))
    }
}
