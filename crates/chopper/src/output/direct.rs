//! Private publication adapter for the shared encoded chunk writer.
use super::*;

#[derive(Clone, Copy)]
struct RecordNumbers {
    rows: u64,
    csv_bytes: u64,
    stored_bytes: u64,
    compressed_target_exceeded: bool,
}
impl RecordNumbers {
    fn output<'a>(self, path: &'a str, lineage: &'a [serde_json::Value]) -> OutputRecord<'a> {
        OutputRecord {
            rows: self.rows,
            csv_bytes: self.csv_bytes,
            stored_bytes: self.stored_bytes,
            compressed_target_exceeded: self.compressed_target_exceeded,
            path,
            lineage,
            kind: "output",
        }
    }
}
struct SingleRecord {
    // Move the existing admitted relative name; no second string/tree copy.
    name: PublicationName,
    numbers: RecordNumbers,
    #[cfg(feature = "experimental-batched-final-sync")]
    pending_sync: Option<File>,
}
enum Records {
    Disk(BufWriter<DiskFile>),
    Single(Option<SingleRecord>),
}
impl Records {
    fn file(&self) -> Result<&DiskFile> {
        match self {
            Self::Disk(records) => Ok(records.get_ref()),
            Self::Single(_) => {
                anyhow::bail!("single catalog must be materialized before publication")
            }
        }
    }
    #[cfg(test)]
    fn capacity(&self) -> usize {
        match self {
            Self::Disk(records) => records.capacity(),
            Self::Single(_) => 0,
        }
    }
}
impl Write for Records {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        match self {
            Self::Disk(records) => records.write(bytes),
            Self::Single(_) => Err(std::io::Error::other(
                "typed catalog cannot accept encoded bytes",
            )),
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Self::Disk(records) => records.flush(),
            Self::Single(_) => Ok(()),
        }
    }
}
struct RecordLimit {
    bytes: usize,
    maximum: usize,
}
impl Write for RecordLimit {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.bytes = self
            .bytes
            .checked_add(bytes.len())
            .filter(|n| *n <= self.maximum)
            .ok_or_else(|| {
                std::io::Error::other("catalog record exceeds metadata record budget")
            })?;
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
fn check_record_length(record: &OutputRecord<'_>, maximum: usize) -> Result<()> {
    // JsonLines bounds JSON bytes excluding its terminating newline.
    serde_json::to_writer(RecordLimit { bytes: 0, maximum }, record)?;
    Ok(())
}

struct OpenChunk {
    sink: ObservedSink,
    name: PublicationName,
    path: Option<PublicationPath>,
    crc: crc32fast::Hasher,
}

pub(crate) struct DirectPublication {
    current: Option<OpenChunk>,
    header: Option<crate::engine::Header>,
    grouped: bool,
    pub(super) buffer_capacity: usize,
    archive: Option<ZipStream>,
    records: Records,
    #[cfg(feature = "experimental-batched-final-sync")]
    sync: deferred_sync::Queue,
    _records_buffer: Reservation,
    destination: std::path::PathBuf,
    existing_empty: bool,
    // Destroy all open handles before removing an abandoned staging directory.
    stage: JobDirectory,
}
impl DirectPublication {
    pub(crate) fn append_group(
        &mut self,
        other: Self,
        group: &Group,
        files: &mut u64,
        job: &Job,
        ctx: &Context,
    ) -> Result<()> {
        ensure!(
            job.compression == Compression::None,
            "fanout requires plain output"
        );
        ensure!(other.current.is_none(), "unfinished fanout output");
        #[cfg(feature = "experimental-batched-final-sync")]
        let mut other = other;
        // Each source has its own private directory. Its admitted Group retains
        // lineage until this merge, so a typed one-chunk record needs no clone.
        match &other.records {
            Records::Single(record) => {
                let record = record.as_ref().context("missing single catalog record")?;
                // Match the old source JsonLines boundary. The canonical root
                // catalog is copied without decoding, so do not add this limit
                // to close or materialization.
                check_record_length(
                    &record.numbers.output(record.name.as_str(), &group.lineage),
                    ctx.max_record.saturating_add(1024),
                )?;
                self.append_record(
                    other.stage.path(),
                    record.name.as_str(),
                    record.numbers,
                    group,
                    files,
                    (job, ctx),
                )?;
            }
            Records::Disk(records) => {
                for record in JsonLines::<serde_json::Value>::new(
                    records.get_ref(),
                    ctx.max_record.saturating_add(1024),
                )?
                .reserved()
                {
                    ctx.check()?;
                    let record = record?;
                    let numbers = RecordNumbers {
                        rows: record["rows"]
                            .as_u64()
                            .context("invalid fanout row count")?,
                        csv_bytes: record["csv_bytes"]
                            .as_u64()
                            .context("invalid fanout byte count")?,
                        stored_bytes: record["stored_bytes"]
                            .as_u64()
                            .context("invalid fanout stored count")?,
                        compressed_target_exceeded: record["compressed_target_exceeded"]
                            .as_bool()
                            .context("invalid fanout target")?,
                    };
                    self.append_record(
                        other.stage.path(),
                        record["path"].as_str().context("invalid fanout path")?,
                        numbers,
                        group,
                        files,
                        (job, ctx),
                    )?;
                }
            }
        }
        #[cfg(feature = "experimental-batched-final-sync")]
        {
            if let Records::Single(Some(record)) = &mut other.records {
                self.sync.take(&mut record.pending_sync)?;
            }
            self.sync.absorb(&mut other.sync)?;
        }
        Ok(())
    }
    fn append_record(
        &mut self,
        source: &Path,
        old_name: &str,
        numbers: RecordNumbers,
        group: &Group,
        files: &mut u64,
        execution: (&Job, &Context),
    ) -> Result<()> {
        let (job, ctx) = execution;
        ctx.check()?;
        let index = files.checked_add(1).context("output count overflow")?;
        ensure!(index <= ctx.max_files, "output count exceeds max_files");
        let name = output_name(
            index,
            group,
            job,
            self.header.as_deref(),
            Reservation::new(ctx),
        )?;
        let old = PublicationPath::join(source, old_name, Reservation::new(ctx))?;
        let new = PublicationPath::join(self.stage.path(), name.as_str(), Reservation::new(ctx))?;
        std::fs::rename(&old, &new)?;
        serde_json::to_writer(
            &mut self.records,
            &numbers.output(name.as_str(), &group.lineage),
        )?;
        self.records.write_all(b"\n")?;
        *files = index;
        Ok(())
    }
    pub(crate) fn materialize_group_records(&mut self, group: &Group, ctx: &Context) -> Result<()> {
        let Records::Single(record) = &mut self.records else {
            return Ok(());
        };
        let record = record.as_mut().context("missing single catalog record")?;
        // Keep this exact stage and original destination witness. The CSV sink
        // has closed before its one canonical root catalog is admitted.
        self._records_buffer.resize(PLAN_CATALOG_BUFFER)?;
        let mut disk = BufWriter::with_capacity(PLAN_CATALOG_BUFFER, ctx.file()?);
        serde_json::to_writer(
            &mut disk,
            &record.numbers.output(record.name.as_str(), &group.lineage),
        )?;
        disk.write_all(b"\n")?;
        #[cfg(feature = "experimental-batched-final-sync")]
        self.sync.take(&mut record.pending_sync)?;
        self.records = Records::Disk(disk);
        Ok(())
    }

    pub(super) fn new(job: &Job, ctx: &Context) -> Result<Self> {
        Self::with_catalog_buffer(job, ctx, PLAN_CATALOG_BUFFER)
    }
    fn with_catalog_buffer(job: &Job, ctx: &Context, capacity: usize) -> Result<Self> {
        Self::with_records(job, ctx, Some(capacity))
    }
    fn with_records(job: &Job, ctx: &Context, capacity: Option<usize>) -> Result<Self> {
        let destination = std::path::absolute(&job.output)?;
        let existing_empty = empty_destination(&destination)?;
        let parent = destination.parent().context("invalid output directory")?;
        ensure!(parent.is_dir(), "output parent directory does not exist");
        let stage = ctx.staging_directory(parent)?;
        let mut buffer = Reservation::new(ctx);
        let records = if let Some(capacity) = capacity {
            buffer.resize(capacity)?;
            Records::Disk(BufWriter::with_capacity(capacity, ctx.file()?))
        } else {
            Records::Single(None)
        };
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
            header: None,
            grouped: false,
            buffer_capacity: PUBLICATION_BUFFER,
            archive,
            records,
            #[cfg(feature = "experimental-batched-final-sync")]
            sync: deferred_sync::Queue::new(ctx),
            _records_buffer: buffer,
            destination,
            existing_empty,
            stage,
        })
    }
    pub(crate) fn grouped(
        job: &Job,
        header: Option<&crate::engine::Header>,
        ctx: &Context,
    ) -> Result<Self> {
        Self::grouped_with_catalog(job, header, ctx, PLAN_CATALOG_BUFFER)
    }
    pub(super) fn grouped_with_catalog(
        job: &Job,
        header: Option<&crate::engine::Header>,
        ctx: &Context,
        capacity: usize,
    ) -> Result<Self> {
        let mut result = Self::with_catalog_buffer(job, ctx, capacity)?;
        result.header = header.cloned();
        result.grouped = true;
        Ok(result)
    }
    pub(super) fn grouped_single(
        job: &Job,
        header: Option<&crate::engine::Header>,
        ctx: &Context,
    ) -> Result<Self> {
        ensure!(
            job.compression == Compression::None,
            "single catalog requires plain output"
        );
        let mut result = Self::with_records(job, ctx, None)?;
        result.header = header.cloned();
        result.grouped = true;
        Ok(result)
    }
    pub(super) fn open(&mut self, chunk: &Chunk, job: &Job, ctx: &Context) -> Result<()> {
        ensure!(self.current.is_none(), "direct chunk already open");
        // Limits-only callers retain their original empty-lineage contract.
        ensure!(
            self.grouped || chunk.group.lineage.is_empty(),
            "direct output requires an empty pipeline"
        );
        let name = output_name(
            chunk.index,
            &chunk.group,
            job,
            self.header.as_deref(),
            Reservation::new(ctx),
        )?;
        let (sink, path) =
            open_sink_buffered(&name, job, self.stage.path(), ctx, self.buffer_capacity)?;
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
        #[cfg(feature = "experimental-batched-final-sync")]
        let (compressed, pending_sync) =
            if cfg!(target_os = "linux") && matches!(self.records, Records::Single(_)) {
                (None, Some(sink.finish_deferred()?))
            } else {
                (sink.finish()?, None)
            };
        #[cfg(not(feature = "experimental-batched-final-sync"))]
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
        let numbers = RecordNumbers {
            compressed_target_exceeded: job
                .limits
                .compressed_bytes
                .is_some_and(|limit| stored > limit),
            csv_bytes: chunk.bytes,
            rows: chunk.rows,
            stored_bytes: stored,
        };
        let record = numbers.output(name.as_str(), &chunk.group.lineage);
        match &mut self.records {
            Records::Disk(records) => {
                serde_json::to_writer(&mut *records, &record)?;
                records.write_all(b"\n")?;
            }
            Records::Single(slot) => {
                ensure!(
                    slot.is_none(),
                    "single catalog cannot contain a second chunk"
                );
                *slot = Some(SingleRecord {
                    name,
                    numbers,
                    #[cfg(feature = "experimental-batched-final-sync")]
                    pending_sync,
                });
            }
        }
        Ok(())
    }
    pub(crate) fn seal(&mut self) -> Result<()> {
        ensure!(self.current.is_none(), "unfinished direct chunk");
        self.records.flush()?;
        Ok(())
    }
    pub(crate) fn sync_pending(&mut self, ctx: &Context) -> Result<()> {
        #[cfg(feature = "experimental-batched-final-sync")]
        self.sync.sync(ctx)?;
        #[cfg(not(feature = "experimental-batched-final-sync"))]
        let _ = ctx;
        Ok(())
    }
    pub(crate) fn publish(
        mut self,
        job: &Job,
        analysis: &crate::engine::Analysis,
        ctx: &Context,
    ) -> Result<EnginePublication> {
        ctx.check()?;
        ctx.pressure_boundary();
        ensure!(self.current.is_none(), "unfinished direct chunk");
        self.sync_pending(ctx)?;
        let manifest_path =
            PublicationPath::join(self.stage.path(), "manifest.jsonl", Reservation::new(ctx))?;
        let mut manifest = PublicationWriter::new(&manifest_path, MANIFEST_BUFFER, ctx)?;
        serde_json::to_writer(
            &mut manifest,
            &job_manifest::ManifestTree::build(job, analysis, Reservation::new(ctx))?,
        )?;
        manifest.write_all(b"\n")?;
        let mut input = publication_reader(self.records.file()?, ctx)?;
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

#[cfg(test)]
mod catalog_tests {
    use super::*;
    use std::sync::{atomic::AtomicBool, Arc};

    #[test]
    fn selected_catalog_capacity_is_admitted_and_released_on_success_and_denial() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let job = Job {
            output: dir.path().join("output").to_string_lossy().into(),
            resources: chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            ..Default::default()
        };
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024)),
        )?;
        for capacity in [512, PLAN_CATALOG_BUFFER] {
            let writer = DirectPublication::grouped_with_catalog(&job, None, &ctx, capacity)?;
            assert_eq!(writer.records.capacity(), capacity);
            assert_eq!(writer._records_buffer.bytes(), capacity as u64);
            drop(writer);
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
            assert_eq!(std::fs::read_dir(dir.path())?.count(), 0);
        }
        assert!(DirectPublication::grouped_with_catalog(&job, None, &ctx, usize::MAX).is_err());
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        assert_eq!(std::fs::read_dir(dir.path())?.count(), 0);
        Ok(())
    }
}

#[cfg(test)]
mod single_catalog_tests {
    use super::*;
    use std::sync::{atomic::AtomicBool, Arc};

    fn setup() -> Result<(tempfile::TempDir, Job, Context)> {
        let dir = tempfile::tempdir()?;
        std::fs::create_dir(dir.path().join("temp"))?;
        let job = Job {
            output: dir.path().join("output").to_string_lossy().into(),
            resources: chopper_core::Resources {
                temp_dir: Some(dir.path().join("temp").to_string_lossy().into()),
                workers: 1,
                ..Default::default()
            },
            ..Default::default()
        };
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(256 * 1024 * 1024)),
        )?;
        Ok((dir, job, ctx))
    }
    fn chunk() -> Chunk {
        Chunk {
            index: 1,
            offset: 0,
            rows: 1,
            bytes: 5,
            group: Group {
                offset: 0,
                rows: 1,
                lineage: vec![],
                exact: true,
            },
        }
    }

    #[test]
    fn serialized_length_guard_matches_disk_line_budget_including_escapes() -> Result<()> {
        let (_dir, _job, ctx) = setup()?;
        let lineage = vec![serde_json::json!({"operation":0,"allocation":"quote\"\0\n界"})];
        let numbers = RecordNumbers {
            rows: u64::MAX,
            csv_bytes: 15,
            stored_bytes: 15,
            compressed_target_exceeded: false,
        };
        let record = numbers.output("escaped.csv", &lineage);
        let bytes = serde_json::to_vec(&record)?;
        let mut file = ctx.file()?;
        file.write_all(&bytes)?;
        file.write_all(b"\n")?;
        for maximum in [bytes.len() - 1, bytes.len(), bytes.len() + 1] {
            let counted = check_record_length(&record, maximum).is_ok();
            let decoded = JsonLines::<serde_json::Value>::new(&file, maximum)?
                .reserved()
                .next()
                .unwrap()
                .is_ok();
            assert_eq!(counted, decoded);
            assert_eq!(counted, maximum >= bytes.len());
        }
        Ok(())
    }

    #[test]
    fn single_record_materialization_denial_and_second_chunk_keep_private_cleanup() -> Result<()> {
        for mode in ["normal", "denied", "second"] {
            let (dir, job, ctx) = setup()?;
            let before = ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap();
            let mut publication = DirectPublication::grouped_single(&job, None, &ctx)?;
            assert_eq!(publication._records_buffer.bytes(), 0);
            let chunk = chunk();
            publication.open(&chunk, &job, &ctx)?;
            publication.write_all(b"id\n0\n")?;
            publication.close(&chunk, &job, &ctx)?;
            publication.seal()?;
            assert!(publication.records.file().is_err());
            let mut held = Reservation::new(&ctx);
            if mode == "denied" {
                held.resize(
                    ctx.memory / 2
                        - ctx.diagnostics()["workspace_reserved_bytes"]
                            .as_u64()
                            .unwrap() as usize,
                )?;
                assert!(publication
                    .materialize_group_records(&chunk.group, &ctx)
                    .is_err());
            } else if mode == "second" {
                let mut next = chunk;
                next.index = 2;
                publication.open(&next, &job, &ctx)?;
                publication.write_all(b"id\n0\n")?;
                assert!(publication.close(&next, &job, &ctx).is_err());
            } else {
                publication.materialize_group_records(&chunk.group, &ctx)?;
                publication.seal()?;
                assert_eq!(
                    publication._records_buffer.bytes(),
                    PLAN_CATALOG_BUFFER as u64
                );
                let records: Vec<_> = JsonLines::<serde_json::Value>::new(
                    publication.records.file()?,
                    ctx.max_record,
                )?
                .reserved()
                .collect::<Result<_>>()?;
                assert_eq!(records.len(), 1);
                assert_eq!(records[0]["rows"], 1);
                assert_eq!(records[0]["csv_bytes"], 5);
                assert_eq!(records[0]["lineage"], serde_json::json!([]));
            }
            drop(publication);
            drop(held);
            assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], before);
            assert!(!std::path::Path::new(&job.output).exists());
            assert!(!std::fs::read_dir(dir.path())?.any(|p| p
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".chopper-staging-")));
        }
        Ok(())
    }

    #[test]
    fn root_keeps_streamed_metadata_while_source_merge_keeps_old_line_limit() -> Result<()> {
        for single in [false, true] {
            let (_dir, mut job, _original) = setup()?;
            job.resources.max_record_bytes = 64 * 1024;
            let ctx = Context::with_memory_pool(
                &job.resources,
                Arc::new(AtomicBool::new(false)),
                Arc::new(|_| {}),
                Arc::new(crate::resources::MemoryPool::new(256 * 1024 * 1024)),
            )?;
            let mut chunk = chunk();
            chunk.group.lineage = vec![serde_json::json!({
                "operation": 0, "allocation": "x".repeat(ctx.max_record + 2048)
            })];
            for root in [true, false] {
                let mut publication = if single {
                    DirectPublication::grouped_single(&job, None, &ctx)?
                } else {
                    DirectPublication::grouped(&job, None, &ctx)?
                };
                publication.open(&chunk, &job, &ctx)?;
                publication.write_all(b"id\n0\n")?;
                publication.close(&chunk, &job, &ctx)?;
                publication.seal()?;
                if root {
                    publication.materialize_group_records(&chunk.group, &ctx)?;
                    publication.seal()?;
                    let file = publication.records.file()?;
                    assert!(file.len() > (ctx.max_record + 1024) as u64);
                    // Root publication streams these bytes; decoding the same
                    // line as a merged source must still fail at its old limit.
                    assert!(
                        JsonLines::<serde_json::Value>::new(file, ctx.max_record + 1024)?
                            .reserved()
                            .next()
                            .unwrap()
                            .is_err()
                    );
                } else {
                    let mut destination = DirectPublication::new(&job, &ctx)?;
                    let mut files = 0;
                    assert!(destination
                        .append_group(publication, &chunk.group, &mut files, &job, &ctx)
                        .is_err());
                    assert_eq!(files, 0);
                }
            }
            ctx.check()?;
        }
        Ok(())
    }

    #[cfg(all(feature = "experimental-batched-final-sync", target_os = "linux"))]
    #[test]
    fn batched_sync_transfers_first_and_external_root_handles_and_cleans_sync_error() -> Result<()>
    {
        for mode in ["first", "external", "error"] {
            let (dir, job, ctx) = setup()?;
            let before = ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap();
            let mut root = if mode == "first" {
                None
            } else {
                Some(DirectPublication::new(&job, &ctx)?)
            };
            let mut files = 0;
            for part in 0..3 {
                let mut chunk = chunk();
                chunk.group.lineage = vec![serde_json::json!({"operation": 0, "part": part + 1})];
                let mut publication = DirectPublication::grouped_single(&job, None, &ctx)?;
                publication.open(&chunk, &job, &ctx)?;
                publication.write_all(b"id\n0\n")?;
                publication.close(&chunk, &job, &ctx)?;
                publication.seal()?;
                let Records::Single(Some(record)) = &publication.records else {
                    panic!("typed record")
                };
                assert!(record.pending_sync.is_some());
                if let Some(root) = &mut root {
                    root.append_group(publication, &chunk.group, &mut files, &job, &ctx)?;
                } else {
                    publication.materialize_group_records(&chunk.group, &ctx)?;
                    files = 1;
                    root = Some(publication);
                }
                assert_eq!(root.as_ref().unwrap().sync.len(), part + 1);
            }
            let mut root = root.unwrap();
            assert_eq!(files, 3);
            root.seal()?;
            if mode == "error" {
                root.sync.take(&mut Some(File::open("/dev/null")?))?;
            }
            assert_eq!(root.sync_pending(&ctx).is_ok(), mode != "error");
            assert_eq!(root.sync.len(), 0);
            root.sync_pending(&ctx)?;
            drop(root);
            assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], before);
            assert!(!std::path::Path::new(&job.output).exists());
            assert!(!std::fs::read_dir(dir.path())?.any(|entry| entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".chopper-staging-")));
            ctx.check()?;
        }
        Ok(())
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn single_catalog_removes_metadata_descriptors_while_csv_sinks_stay_open() -> Result<()> {
        let (dir, job, ctx) = setup()?;
        let temporary = std::fs::canonicalize(dir.path().join("temp"))?;
        let outputs = std::fs::canonicalize(dir.path())?;
        for single in [false, true] {
            let mut memory = Reservation::new(&ctx);
            let mut writers = Vec::new();
            memory.reserve_vec(&mut writers, 64)?;
            for _ in 0..64 {
                let mut writer = if single {
                    DirectPublication::grouped_single(&job, None, &ctx)?
                } else {
                    DirectPublication::grouped(&job, None, &ctx)?
                };
                writer.open(&chunk(), &job, &ctx)?;
                writer.write_all(b"id\n0\n")?;
                writers.push(writer);
            }
            let links: Vec<_> = std::fs::read_dir("/proc/self/fd")?
                .filter_map(|entry| std::fs::read_link(entry.ok()?.path()).ok())
                .collect();
            let metadata = links
                .iter()
                .filter(|path| path.starts_with(&temporary))
                .count();
            let csv = links
                .iter()
                .filter(|path| {
                    path.starts_with(&outputs)
                        && !path.starts_with(&temporary)
                        && path.extension().is_some_and(|extension| extension == "csv")
                })
                .count();
            assert_eq!(metadata, if single { 0 } else { 64 });
            assert_eq!(csv, 64);
            println!("single_catalog={single} controlled_metadata_fds={metadata} csv_fds={csv}");
            drop(writers);
            drop(memory);
            ctx.check()?;
            assert_eq!(
                ctx.diagnostics()["workspace_reserved_bytes"],
                ctx.directory_reserved_bytes()
            );
        }
        Ok(())
    }
}
