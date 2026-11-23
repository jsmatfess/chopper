use crate::{engine::Prepared, storage::*};
use anyhow::{ensure, Context as _, Result};
use chopper_core::{csv, Column, Compression, Job, Operation};
#[cfg(any(test, feature = "resource-contract-tests"))]
use serde_json::json;
use std::{
    fs::File,
    io::{BufWriter, Read, Seek, SeekFrom, Write},
    path::Path,
};
#[cfg(target_os = "linux")]
mod deferred_sync;
mod deflate;
mod parallel_deflate;
#[cfg(target_os = "wasi")]
#[doc(hidden)]
pub use deflate::{BlockEncoder, BLOCK_BYTES, COMPRESSED_BLOCK_BYTES};
pub(crate) use parallel_deflate::direct_candidate as parallel_direct_compression;
#[cfg(target_os = "wasi")]
pub(crate) use parallel_deflate::hosted::Lease as HostedDeflateLease;
mod direct;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use deflate::resource_contracts as deflate_contracts;
pub(crate) use direct::DirectPublication;
mod job_manifest;
#[cfg(all(test, not(target_family = "wasm")))]
mod plain_publication_contracts;
mod planned_metadata;
mod publication_metadata;
mod publication_path;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use job_manifest::resource_contracts as job_manifest_contracts;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use planned_metadata::resource_contracts as planned_metadata_contracts;
use planned_metadata::PlannedMetadata;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use publication_metadata::resource_contracts as publication_metadata_contracts;
use publication_metadata::{output_name, PublicationBatch, PublicationName};
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) use publication_path::resource_contracts as publication_path_contracts;
use publication_path::PublicationPath;

/// Proof that the platform's engine publication commit point succeeded.
/// Browser destination export requires its separate verified marker receipt.
/// A caller cannot manufacture publication success:
/// ```compile_fail
/// let _ = chopper::output::EnginePublication(());
/// ```
#[derive(Debug)]
pub struct EnginePublication(());
#[derive(Debug)]
pub(crate) struct PublishedAnalysis {
    analysis: crate::engine::Analysis,
    publication: EnginePublication,
    pub(crate) measurements: crate::engine::auto::RunMeasurements,
}
impl EnginePublication {
    pub(crate) fn with_analysis(
        self,
        analysis: crate::engine::Analysis,
        ctx: &Context,
    ) -> PublishedAnalysis {
        PublishedAnalysis {
            analysis,
            publication: self,
            measurements: ctx.completed_measurements(),
        }
    }
}
impl PublishedAnalysis {
    pub(crate) fn into_analysis(self) -> crate::engine::Analysis {
        let Self {
            analysis,
            publication: _publication,
            ..
        } = self;
        analysis
    }
}
/// Immutable, already-encoded CSV data and a disk-backed chunk catalog.
pub struct OutputPlan {
    pub data: DiskFile,
    catalog: DiskFile,
    pub files: u64,
    pub bytes: u64,
    max_metadata: usize,
}
#[derive(serde::Serialize, serde::Deserialize)]
struct Chunk {
    index: u64,
    offset: u64,
    rows: u64,
    bytes: u64,
    group: Group,
}
impl JsonCapacity for Chunk {
    fn json_capacity(&self) -> Result<usize> {
        self.group.lineage.json_capacity()
    }
}
impl OutputPlan {
    fn chunks(&self) -> Result<impl Iterator<Item = Result<ChargedJson<Chunk>>>> {
        Ok(JsonLines::new(&self.catalog, self.max_metadata)?.reserved())
    }
}
// Borrow the admitted catalog tree during publication instead of cloning it
// into a second serde_json::Value. Keep the existing sorted JSON field order.
#[derive(serde::Serialize)]
struct OutputRecord<'a> {
    compressed_target_exceeded: bool,
    csv_bytes: u64,
    lineage: &'a [serde_json::Value],
    path: &'a str,
    rows: u64,
    stored_bytes: u64,
    #[serde(rename = "type")]
    kind: &'static str,
}
const PLAN_DATA_BUFFER: usize = if cfg!(target_os = "wasi") {
    256 * 1024
} else {
    65536
};
const PLAN_CATALOG_BUFFER: usize = 8192;
const PUBLICATION_BUFFER: usize = 64 * 1024;
const MANIFEST_BUFFER: usize = 8192;

// Own the grant alongside the allocation, including codec finalization and
// BufWriter's drop-time flush. Codec-internal allocations remain separate.
struct PublicationWriter {
    writer: BufWriter<File>,
    _buffer: Reservation,
}
impl PublicationWriter {
    fn new(path: impl AsRef<Path>, capacity: usize, ctx: &Context) -> Result<Self> {
        Self::with_reservation(path, capacity, Reservation::new(ctx))
    }
    fn with_reservation(
        path: impl AsRef<Path>,
        capacity: usize,
        mut buffer: Reservation,
    ) -> Result<Self> {
        buffer.resize(capacity)?;
        Ok(Self {
            writer: BufWriter::with_capacity(capacity, File::create(path)?),
            _buffer: buffer,
        })
    }
    #[cfg(target_os = "linux")]
    fn into_file(mut self) -> Result<File> {
        self.writer.flush()?;
        let Self { writer, _buffer } = self;
        let file = writer.into_inner().map_err(|error| error.into_error())?;
        drop(_buffer);
        Ok(file)
    }
    fn sync_all(&mut self) -> Result<()> {
        self.writer.flush()?;
        self.writer.get_ref().sync_all()?;
        Ok(())
    }
}
impl Write for PublicationWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.writer.write(bytes)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.writer.flush()
    }
}

fn publication_reader(file: &DiskFile, ctx: &Context) -> Result<PublicationReader> {
    PublicationReader::with_reservation(file, Reservation::new(ctx))
}
struct PublicationReader {
    reader: std::io::BufReader<DiskReader>,
    _buffer: Reservation,
}
impl PublicationReader {
    fn with_reservation(file: &DiskFile, mut buffer: Reservation) -> Result<Self> {
        buffer.resize(DISK_READ_BUFFER)?;
        Ok(Self {
            reader: file.reader()?,
            _buffer: buffer,
        })
    }
}
impl Read for PublicationReader {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        self.reader.read(bytes)
    }
}
impl Seek for PublicationReader {
    fn seek(&mut self, position: SeekFrom) -> std::io::Result<u64> {
        self.reader.seek(position)
    }
}

#[cfg(any(test, target_os = "wasi"))]
struct PublicationCopyBuffer {
    bytes: Vec<u8>,
    _buffer: Reservation,
}
#[cfg(any(test, target_os = "wasi"))]
impl PublicationCopyBuffer {
    fn new(ctx: &Context) -> Result<Self> {
        Self::with_reservation(Reservation::new(ctx))
    }
    fn with_reservation(mut buffer: Reservation) -> Result<Self> {
        let mut bytes = Vec::new();
        buffer.reserve_vec(&mut bytes, 256 * 1024)?;
        bytes.resize(256 * 1024, 0);
        Ok(Self {
            bytes,
            _buffer: buffer,
        })
    }
}

// Snapshot and publication adapters share encoded prefixes, rows and cap decisions.
// Keep this per-job dispatch inline rather than adding an unadmitted heap owner.
#[allow(clippy::large_enum_variant)]
enum EncodedTarget {
    Snapshot {
        data: BufWriter<DiskFile>,
        catalog: BufWriter<DiskFile>,
    },
    Direct(DirectPublication),
}
impl EncodedTarget {
    fn open(&mut self, chunk: &Chunk, job: &Job, ctx: &Context) -> Result<()> {
        match self {
            Self::Snapshot { .. } => Ok(()),
            Self::Direct(target) => target.open(chunk, job, ctx),
        }
    }
    fn write_all(&mut self, bytes: &[u8]) -> Result<()> {
        match self {
            Self::Snapshot { data, .. } => Ok(data.write_all(bytes)?),
            Self::Direct(target) => target.write_all(bytes),
        }
    }
    fn close(&mut self, chunk: &Chunk, job: &Job, ctx: &Context) -> Result<()> {
        match self {
            Self::Snapshot { catalog, .. } => {
                serde_json::to_writer(&mut *catalog, chunk)?;
                catalog.write_all(b"\n")?;
                Ok(())
            }
            Self::Direct(target) => target.close(chunk, job, ctx),
        }
    }
}

pub struct PlanWriter<'a> {
    job: &'a Job,
    ctx: &'a Context,
    target: EncodedTarget,
    prefix: Vec<u8>,
    serializer: csv::Serializer,
    chunk: Option<PlannedMetadata<Chunk>>,
    files: u64,
    file_limit: u64,
    bytes: u64,
    processed: u64,
    observation: Option<crate::observation::physical::Span<'a>>,
    pub groups: u64,
    pub smallest: u64,
    pub largest: u64,
    pub empty: u64,
    _buffers: Reservation,
    _serialization: Reservation,
}
impl<'a> PlanWriter<'a> {
    pub fn new(job: &'a Job, header: Option<&[String]>, ctx: &'a Context) -> Result<Self> {
        Self::with_buffers(job, header, ctx, Reservation::new(ctx))
    }
    fn with_buffers(
        job: &'a Job,
        header: Option<&[String]>,
        ctx: &'a Context,
        mut buffers: Reservation,
    ) -> Result<Self> {
        buffers.resize(PLAN_DATA_BUFFER + PLAN_CATALOG_BUFFER)?;
        let target = || {
            Ok(EncodedTarget::Snapshot {
                // Larger WASI batches amortize storage RPCs for the snapshot writer.
                data: BufWriter::with_capacity(PLAN_DATA_BUFFER, ctx.file()?),
                catalog: BufWriter::with_capacity(PLAN_CATALOG_BUFFER, ctx.file()?),
            })
        };
        Self::with_target(job, header, ctx, buffers, target)
    }
    pub(crate) fn direct(
        job: &'a Job,
        header: Option<&[String]>,
        ctx: &'a Context,
    ) -> Result<Self> {
        let target = || Ok(EncodedTarget::Direct(DirectPublication::new(job, ctx)?));
        Self::with_target(job, header, ctx, Reservation::new(ctx), target)
    }
    pub(crate) fn direct_grouped(
        job: &'a Job,
        header: Option<&crate::engine::Header>,
        ctx: &'a Context,
    ) -> Result<Self> {
        Self::with_target(
            job,
            header.map(|h| &h[..]),
            ctx,
            Reservation::new(ctx),
            || {
                Ok(EncodedTarget::Direct(DirectPublication::grouped(
                    job, header, ctx,
                )?))
            },
        )
    }
    pub(crate) fn direct_fanout(
        job: &'a Job,
        header: Option<&crate::engine::Header>,
        ctx: &'a Context,
        single_chunk: bool,
    ) -> Result<Self> {
        let capacity = if cfg!(feature = "experimental-small-final-catalogs") {
            512
        } else {
            PLAN_CATALOG_BUFFER
        };
        let mut result = Self::with_target(
            job,
            header.map(|h| &h[..]),
            ctx,
            Reservation::new(ctx),
            || {
                Ok(EncodedTarget::Direct(
                    if (ctx.auto_final_sync || cfg!(feature = "experimental-single-final-catalog"))
                        && single_chunk
                    {
                        DirectPublication::grouped_single(job, header, ctx)?
                    } else {
                        DirectPublication::grouped_with_catalog(job, header, ctx, capacity)?
                    },
                ))
            },
        )?;
        let EncodedTarget::Direct(target) = &mut result.target else {
            unreachable!("direct constructor");
        };
        target.buffer_capacity =
            if ctx.auto_final_sync || cfg!(feature = "experimental-small-final-buffers") {
                16 * 1024
            } else {
                PUBLICATION_BUFFER
            };
        Ok(result)
    }
    fn with_target(
        job: &'a Job,
        header: Option<&[String]>,
        ctx: &'a Context,
        buffers: Reservation,
        target: impl FnOnce() -> Result<EncodedTarget>,
    ) -> Result<Self> {
        let mut observation = if job.operations.is_empty() {
            None
        } else {
            ctx.physical_pending_span_for(
                crate::observation::physical::Kind::Serialize,
                [job.operations.len() + 1, 0],
            )
        };
        let result = (|| -> Result<Self> {
            let mut serialization = Reservation::new(ctx);
            // A BOM has at most three bytes; reserve before its small Vec exists.
            serialization.resize(3)?;
            let mut prefix = csv::bom(&job.output_csv)?;
            serialization.resize(prefix.capacity())?;
            let mut serializer = csv::Serializer::new(&job.output_csv)?;
            if job.output_csv.headers {
                if let Some(header) = header {
                    let prefix_capacity = prefix.capacity();
                    let bytes = serializer.serialize_fields_reserved(
                        header.iter().map(String::as_str),
                        &mut |bytes| {
                            serialization.resize(
                                prefix_capacity
                                    .checked_add(bytes)
                                    .context("output serialization overflow")?,
                            )
                        },
                    )?;
                    let needed = prefix
                        .len()
                        .checked_add(bytes.len())
                        .context("output prefix overflow")?;
                    serialization.reserve_vec(&mut prefix, needed)?;
                    prefix.extend_from_slice(bytes);
                }
            }
            ensure!(
                prefix.len() as u64 <= job.limits.bytes.unwrap_or(u64::MAX),
                "header/BOM exceeds output byte limit"
            );
            Ok(Self {
                job,
                ctx,
                target: target()?,
                prefix,
                serializer,
                chunk: None,
                files: 0,
                file_limit: ctx.max_files,
                bytes: 0,
                processed: 0,
                observation: observation.take(),
                groups: 0,
                smallest: u64::MAX,
                largest: 0,
                empty: 0,
                _buffers: buffers,
                _serialization: serialization,
            })
        })();
        if let Err(error) = &result {
            if let Some(span) = observation.take() {
                span.finish_error(error, 0);
            }
        }
        result
    }

    // Raw count-independent fanout delegates one monotonic stream cursor.
    // Its selector excludes physical observations, so no per-writer span owns it.
    pub(crate) fn continue_progress_at(&mut self, rows: u64) {
        debug_assert!(self.observation.is_none());
        self.processed = rows;
    }
    pub(crate) fn release_serialization_scratch(&mut self) -> Result<()> {
        // Shared fanout uses its central row encoder. Drop both old buffers
        // before returning their grant; the serialized BOM/header stays owned.
        self.serializer = csv::Serializer::new(&self.job.output_csv)?;
        self._serialization.resize(self.prefix.capacity())
    }
    pub(crate) fn files(&self) -> u64 {
        self.files
    }
    pub(crate) fn allow_additional_files(&mut self, remaining: u64) -> Result<()> {
        self.file_limit = self
            .files
            .checked_add(remaining)
            .context("output count overflow")?;
        Ok(())
    }
    fn open(&mut self, group: &Group) -> Result<()> {
        let index = self.files.checked_add(1).context("output count overflow")?;
        ensure!(index <= self.file_limit, "output count exceeds max_files");
        self.chunk = Some(PlannedMetadata::clone_lineage(
            group,
            Reservation::new(self.ctx),
            |group| Chunk {
                index,
                offset: self.bytes,
                rows: 0,
                bytes: self.prefix.len() as u64,
                group,
            },
        )?);
        self.files = index;
        self.target
            .open(&self.chunk.as_ref().unwrap().value, self.job, self.ctx)?;
        self.target.write_all(&self.prefix)?;
        Ok(())
    }
    fn observe_error(&mut self, error: &anyhow::Error) {
        if let Some(span) = self.observation.take() {
            span.finish_error(error, self.processed);
        }
    }
    fn close(&mut self) -> Result<()> {
        if let Some(chunk) = self.chunk.take() {
            self.bytes = self
                .bytes
                .checked_add(chunk.value.bytes)
                .context("output size overflow")?;
            self.target.close(&chunk.value, self.job, self.ctx)?;
        }
        Ok(())
    }
    pub fn finish(mut self) -> Result<OutputPlan> {
        let observation = self.observation.take();
        let processed = self.processed;
        let result = (|| -> Result<OutputPlan> {
            self.close()?;
            let EncodedTarget::Snapshot {
                mut data,
                mut catalog,
            } = self.target
            else {
                anyhow::bail!("direct output is not a prepared snapshot");
            };
            data.flush()?;
            catalog.flush()?;
            Ok(OutputPlan {
                data: data.into_inner().map_err(|e| e.into_error())?,
                catalog: catalog.into_inner().map_err(|e| e.into_error())?,
                files: self.files,
                bytes: self.bytes,
                max_metadata: self.ctx.max_record.saturating_add(512),
            })
        })();
        if let Some(span) = observation {
            match &result {
                Ok(_) => span.finish(processed),
                Err(error) => span.finish_error(error, processed),
            }
        }
        result
    }

    pub(crate) fn finish_direct(mut self) -> Result<(DirectPublication, u64, u64)> {
        let observation = self.observation.take();
        let processed = self.processed;
        let result = (|| {
            self.close()?;
            let EncodedTarget::Direct(mut target) = self.target else {
                anyhow::bail!("prepared snapshot is not direct output");
            };
            target.seal()?;
            Ok((target, self.files, self.bytes))
        })();
        if let Some(span) = observation {
            match &result {
                Ok(_) => span.finish(processed),
                Err(error) => span.finish_error(error, processed),
            }
        }
        result
    }
}

impl RowSink for PlanWriter<'_> {
    fn physical_input(&mut self, source: Option<u32>) {
        if let Some(span) = &mut self.observation {
            span.source(source);
        }
    }
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        Group {
            offset: 0,
            rows: 0,
            lineage,
            exact,
        }
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        self.write_fields(group, row.fields.iter().map(String::as_str))
    }
    fn packed_row(&mut self, group: &mut Group, row: PackedRow) -> Result<()> {
        self.packed_row_ref(group, &row)
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        self.write_fields(group, row.fields())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.end_group(&group)
    }
}
impl PlanWriter<'_> {
    pub(crate) fn end_group(&mut self, group: &Group) -> Result<()> {
        let result = (|| -> Result<()> {
            self.ctx.check()?;
            if group.rows == 0 && group.lineage.iter().any(|v| v.get("allocation").is_some()) {
                if let Some(span) = &mut self.observation {
                    span.start();
                }
                self.open(group)?;
            }
            self.close()?;
            self.groups += 1;
            ensure!(
                self.groups <= self.ctx.max_files,
                "logical group count exceeds max_files; increase the ceiling explicitly"
            );
            self.smallest = self.smallest.min(group.rows);
            self.largest = self.largest.max(group.rows);
            self.empty += u64::from(group.rows == 0);
            Ok(())
        })();
        if let Err(error) = &result {
            self.observe_error(error);
        }
        result
    }
}
pub fn plan(
    dataset: &Dataset,
    job: &Job,
    header: Option<&[String]>,
    ctx: &Context,
) -> Result<OutputPlan> {
    let mut writer = PlanWriter::new(job, header, ctx)?;
    for group in dataset.groups()? {
        let group = group?;
        let mut output =
            PlannedMetadata::clone_lineage(&group, Reservation::new(ctx), |mut group| {
                group.offset = 0;
                group.rows = 0;
                group
            })?;
        for row in dataset.rows(&group, ctx.max_record)? {
            let row = row?;
            writer.row(&mut output.value, &row)?;
        }
        // The group's grant must outlive end(), including named empty chunks
        // and catalog serialization errors. Only scalar counters were mutated.
        let PlannedMetadata { value, _memory } = output;
        writer.end(value)?;
        drop(_memory);
    }
    writer.finish()
}

enum Sink {
    Plain(PublicationWriter),
    Gzip(deflate::Encoder<flate2::write::GzEncoder<PublicationWriter>>),
    ParallelGzip(parallel_deflate::Encoder<PublicationWriter>),
    Zip(deflate::Encoder<flate2::write::DeflateEncoder<ZipTarget>>),
    ParallelZip(parallel_deflate::Encoder<ZipTarget>),
}
impl Write for Sink {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        match self {
            Self::Plain(w) => w.write(b),
            Self::Gzip(w) => w.write(b),
            Self::ParallelGzip(w) => w.write(b),
            Self::Zip(w) => w.write(b),
            Self::ParallelZip(w) => w.write(b),
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Self::Plain(w) => w.flush(),
            Self::Gzip(w) => w.flush(),
            Self::ParallelGzip(w) => w.flush(),
            Self::Zip(w) => w.flush(),
            Self::ParallelZip(w) => w.flush(),
        }
    }
}
impl Sink {
    fn finish(self) -> Result<Option<ZipTarget>> {
        match self {
            Self::Plain(mut w) => {
                w.sync_all()?;
            }
            Self::Gzip(w) => {
                let mut w = w.finish(flate2::write::GzEncoder::finish)?;
                w.sync_all()?;
            }
            Self::ParallelGzip(w) => w.finish()?.sync_all()?,
            Self::Zip(w) => return Ok(Some(w.finish(flate2::write::DeflateEncoder::finish)?)),
            Self::ParallelZip(w) => return Ok(Some(w.finish()?)),
        }
        Ok(None)
    }
}
struct OutputObservation {
    entries: u64,
    ctx: Context,
    attempt: Option<crate::observation::physical::Attempt>,
    bytes: u64,
}
impl OutputObservation {
    fn new(job: &Job, ctx: &Context, kind: crate::observation::physical::Kind) -> Option<Self> {
        if !ctx.physical_enabled() {
            return None;
        }
        let mut scope = ctx.physical_scope([job.operations.len() + 1, 0]);
        scope.physical_source = if kind == crate::observation::physical::Kind::ZipArchive {
            None
        } else if job.operations.is_empty() {
            Some(1)
        } else {
            scope.physical_identity(crate::observation::physical::Kind::Serialize)
        };
        let attempt = scope.physical_attempt(kind)?;
        Some(Self {
            entries: 0,
            ctx: scope,
            attempt: Some(attempt),
            bytes: 0,
        })
    }
    fn written(&mut self, result: &std::io::Result<usize>) {
        match result {
            Ok(n) => self.add(*n),
            Err(_) => self.finish(crate::observation::Status::Failed),
        }
    }
    fn add(&mut self, bytes: usize) {
        self.bytes = self.bytes.saturating_add(bytes as u64);
        if let Some(attempt) = &mut self.attempt {
            attempt.bytes_processed(self.bytes);
        }
    }
    fn finish(&mut self, status: crate::observation::Status) {
        if let Some(attempt) = self.attempt.take() {
            attempt.finish_bytes_counts(status, self.bytes, self.entries);
        }
    }
}
impl Drop for OutputObservation {
    fn drop(&mut self) {
        self.finish(crate::observation::Status::Interrupted);
    }
}
struct ObservedSink {
    inner: Sink,
    observation: Option<OutputObservation>,
}
impl Write for ObservedSink {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let result = self.inner.write(bytes);
        if let Some(observation) = &mut self.observation {
            observation.written(&result);
        }
        result
    }
    fn flush(&mut self) -> std::io::Result<()> {
        let result = self.inner.flush();
        if result.is_err() {
            if let Some(observation) = &mut self.observation {
                observation.finish(crate::observation::Status::Failed);
            }
        }
        result
    }
}
impl ObservedSink {
    #[cfg(target_os = "linux")]
    fn finish_deferred(self) -> Result<File> {
        let Self { inner, observation } = self;
        ensure!(
            observation.is_none(),
            "deferred sync requires unobserved output"
        );
        match inner {
            Sink::Plain(writer) => writer.into_file(),
            _ => anyhow::bail!("deferred sync requires plain output"),
        }
    }
    fn finish(self) -> Result<Option<ZipTarget>> {
        let Self {
            inner,
            mut observation,
        } = self;
        let result = inner.finish();
        if let Some(observation) = &mut observation {
            observation.finish(result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ));
        }
        result
    }
}
struct CompletedChunk {
    name: PublicationName,
    compressed: Option<ZipTarget>,
    stored: u64,
    crc: u32,
}
fn open_sink_buffered(
    name: &PublicationName,
    job: &Job,
    stage: &Path,
    ctx: &Context,
    buffer_capacity: usize,
    block_workers: usize,
    zip_target: impl FnOnce() -> Result<ZipTarget>,
) -> Result<(ObservedSink, Option<PublicationPath>)> {
    let output_path = if job.compression == Compression::Zip {
        None
    } else {
        Some(PublicationPath::join(
            stage,
            name.as_str(),
            Reservation::new(ctx),
        )?)
    };
    let kind = match job.compression {
        Compression::None => None,
        Compression::Gzip => Some(crate::observation::physical::Kind::GzipOutput),
        Compression::Zip => Some(crate::observation::physical::Kind::ZipDeflate),
    };
    let mut observation = kind.and_then(|kind| OutputObservation::new(job, ctx, kind));
    let result = (|| -> Result<Sink> {
        let sink = if job.compression == Compression::Zip {
            let file = zip_target()?;
            match parallel_deflate::reserve(ctx, block_workers) {
                Some(memory) => Sink::ParallelZip(parallel_deflate::Encoder::new(
                    file,
                    false,
                    ctx,
                    block_workers,
                    memory,
                )?),
                None => Sink::Zip(deflate::raw(file, Reservation::new(ctx))?),
            }
        } else {
            let file = PublicationWriter::new(output_path.as_ref().unwrap(), buffer_capacity, ctx)?;
            match job.compression {
                Compression::None => Sink::Plain(file),
                Compression::Gzip => match parallel_deflate::reserve(ctx, block_workers) {
                    Some(memory) => Sink::ParallelGzip(parallel_deflate::Encoder::new(
                        file,
                        true,
                        ctx,
                        block_workers,
                        memory,
                    )?),
                    None => Sink::Gzip(deflate::gzip(file, Reservation::new(ctx))?),
                },
                Compression::Zip => unreachable!(),
            }
        };
        Ok(sink)
    })();
    let inner = match result {
        Ok(sink) => sink,
        Err(error) => {
            if let Some(observation) = &mut observation {
                observation.finish(crate::observation::physical::error_status(&error));
            }
            return Err(error);
        }
    };
    let sink = ObservedSink { inner, observation };
    Ok((sink, output_path))
}
fn write_chunk(
    chunk: &Chunk,
    plan: &OutputPlan,
    job: &Job,
    header: Option<&[String]>,
    stage: &Path,
    ctx: &Context,
    block_workers: usize,
) -> Result<CompletedChunk> {
    let name = output_name(
        chunk.index,
        &chunk.group,
        job,
        header,
        Reservation::new(ctx),
    )?;
    let (mut sink, output_path) = open_sink_buffered(
        &name,
        job,
        stage,
        ctx,
        PUBLICATION_BUFFER,
        block_workers,
        || ZipTarget::spool(ctx, chunk.bytes),
    )?;
    let mut input = publication_reader(&plan.data, ctx)?;
    input.seek(SeekFrom::Start(chunk.offset))?;
    let mut remaining = chunk.bytes;
    // WASI output is sequential; bound one heap buffer instead of increasing
    // every merge reader or consuming the browser's small WASM stack.
    #[cfg(target_os = "wasi")]
    let mut copy_buffer = PublicationCopyBuffer::new(ctx)?;
    #[cfg(target_os = "wasi")]
    let buffer = &mut copy_buffer.bytes;
    #[cfg(not(target_os = "wasi"))]
    let mut buffer = [0; 65536];
    let mut crc = crc32fast::Hasher::new();
    while remaining > 0 {
        ctx.check()?;
        let count = remaining.min(buffer.len() as u64) as usize;
        input.read_exact(&mut buffer[..count])?;
        if job.compression == Compression::Zip {
            crc.update(&buffer[..count]);
        }
        sink.write_all(&buffer[..count])?;
        remaining -= count as u64;
    }
    let compressed = sink.finish()?;
    let stored = if let Some(file) = &compressed {
        file.len()
    } else {
        std::fs::metadata(output_path.as_ref().unwrap())?.len()
    };
    Ok(CompletedChunk {
        name,
        compressed,
        stored,
        crc: crc.finalize(),
    })
}
fn auto_plain_publication_workers(job: &Job, bytes: u64, files: u64, workers: usize) -> usize {
    // The competing Partition jobs used four workers, 1,152 files and
    // at least 2 GiB of already validated, serialized output.
    if cfg!(any(target_os = "linux", windows))
        && job.compression == Compression::None
        && matches!(job.operations.as_slice(), [Operation::Partition { .. }])
        && bytes >= 2 * 1024 * 1024 * 1024
        && files >= 1_152
        && workers >= 4
    {
        4
    } else {
        1
    }
}

pub fn execute(prepared: &Prepared) -> Result<EnginePublication> {
    let Prepared {
        job,
        analysis,
        output_plan,
        ctx,
        ..
    } = prepared;
    ctx.pressure_boundary();
    let destination = std::path::absolute(&job.output)?;
    let existing_empty = empty_destination(&destination, ctx.destination_was_absent)?;
    let parent = destination.parent().context("invalid output directory")?;
    ensure!(parent.is_dir(), "output parent directory does not exist");
    let available = available_space(parent)?;
    ensure!(
        available
            > analysis
                .output_csv_bytes
                .saturating_add(analysis.output_csv_bytes / 10)
                .saturating_add(1024 * 1024),
        "insufficient output disk space for conservative estimate"
    );
    let mut stage = ctx.staging_directory(parent)?;
    let manifest_path =
        PublicationPath::join(stage.path(), "manifest.jsonl", Reservation::new(ctx))?;
    let mut manifest = PublicationWriter::new(&manifest_path, MANIFEST_BUFFER, ctx)?;
    serde_json::to_writer(
        &mut manifest,
        &job_manifest::ManifestTree::build(job, analysis, Reservation::new(ctx))?,
    )?;
    manifest.write_all(b"\n")?;
    let mut archive = if job.compression == Compression::Zip {
        Some(ZipStream::observed(
            PublicationPath::join(stage.path(), "outputs.zip", Reservation::new(ctx))?,
            job,
            ctx,
        )?)
    } else {
        None
    };
    let mut files = 0;
    let mut total = 0;
    let mut processed = 0;
    // Reuse the compressed-publication worker/memory ceiling. Every live task
    // still admits its own buffers, decoded lineage and retained result owners.
    let experimental_plain = cfg!(all(
        feature = "experimental-plain-publication",
        not(target_family = "wasm")
    )) && job.compression == Compression::None;
    let concurrency = if job.compression == Compression::None && !experimental_plain {
        if ctx.auto_run {
            auto_plain_publication_workers(job, output_plan.bytes, output_plan.files, ctx.workers())
        } else {
            1
        }
    } else {
        ctx.workers()
            .min((ctx.memory / (16 * 1024 * 1024 + 2 * ctx.max_record)).max(1))
    };
    let mut chunks = output_plan.chunks()?.peekable();
    loop {
        ctx.pressure_boundary();
        if chunks.peek().is_none() {
            break;
        }
        // A one-file or final partial plain batch needs no unused task slots.
        // Keep a slot for the existing catalog/plan disagreement error path.
        let batch_limit = if ctx.auto_run && !experimental_plain {
            ctx.publication_writer_limit(concurrency, output_plan.files.saturating_sub(files))
        } else if experimental_plain {
            concurrency.min(
                usize::try_from(output_plan.files.saturating_sub(files))
                    .unwrap_or(usize::MAX)
                    .max(1),
            )
        } else {
            concurrency
        };
        #[cfg(target_os = "wasi")]
        let batch_limit = match chunks.peek() {
            Some(Ok(chunk)) if parallel_deflate::hosted_files::small(chunk.bytes) => batch_limit
                .max(
                    parallel_deflate::hosted_files::batch_limit(job, ctx, output_plan).min(
                        usize::try_from(output_plan.files.saturating_sub(files))
                            .unwrap_or(usize::MAX),
                    ),
                ),
            _ => batch_limit,
        };
        let mut batch = PublicationBatch::new(batch_limit, Reservation::new(ctx))?;
        #[cfg(all(test, not(target_family = "wasm")))]
        plain_publication_contracts::observe_batch(batch.tasks.capacity());
        let mut reserved = 0u64;
        while batch.tasks.len() < batch_limit {
            if let Some(Ok(next)) = chunks.peek() {
                // A large hosted member uses the codec slots on its own. End
                // the smaller-file batch before opening that member's spool.
                #[cfg(target_os = "wasi")]
                if !batch.tasks.is_empty() && !parallel_deflate::hosted_files::small(next.bytes) {
                    break;
                }
                let estimate = next
                    .bytes
                    .saturating_add(next.bytes / 10)
                    .saturating_add(65536);
                if job.compression == Compression::Zip
                    && !batch.tasks.is_empty()
                    && reserved.saturating_add(estimate) > ctx.remaining_temp()
                {
                    break;
                }
                reserved = reserved.saturating_add(estimate);
            }
            match chunks.next() {
                Some(chunk) => batch.push(chunk?)?,
                None => break,
            }
        }
        if batch.tasks.is_empty() {
            break;
        }
        #[cfg(target_os = "wasi")]
        let hosted_files = parallel_deflate::hosted_files::write_batch(
            &mut batch,
            output_plan,
            job,
            analysis.header.as_deref(),
            stage.path(),
            ctx,
        )?;
        #[cfg(not(target_os = "wasi"))]
        let hosted_files = false;
        if ctx.auto_run {
            let concurrent = hosted_files || cfg!(not(target_os = "wasi"));
            ctx.bounded_writer_slots(if concurrent { batch.tasks.len() } else { 1 });
        }
        if !hosted_files {
            let parallel_files = cfg!(not(target_os = "wasi")) && batch.tasks.len() > 1;
            ctx.for_each_batch(&mut batch.tasks, |task| {
                let block_workers = if parallel_files {
                    1
                } else {
                    parallel_deflate::workers(job, ctx, task.chunk.bytes)
                };
                task.completed = Some(write_chunk(
                    &task.chunk,
                    output_plan,
                    job,
                    analysis.header.as_deref(),
                    stage.path(),
                    ctx,
                    block_workers,
                ));
            });
        }
        // Ordered collection keeps archive members and manifests independent of scheduling.
        for task in batch.tasks.drain(..) {
            let chunk = task.chunk;
            let CompletedChunk {
                name,
                compressed,
                stored: actual,
                crc,
            } = task
                .completed
                .context("publication task did not complete")??;
            if let Some(compressed) = compressed {
                archive.as_mut().unwrap().add(
                    name.as_str(),
                    compressed.reader(ctx)?,
                    actual,
                    chunk.bytes,
                    crc,
                    ctx,
                )?;
            }
            serde_json::to_writer(
                &mut manifest,
                &OutputRecord {
                    compressed_target_exceeded: job
                        .limits
                        .compressed_bytes
                        .is_some_and(|limit| actual > limit),
                    csv_bytes: chunk.bytes,
                    lineage: &chunk.group.lineage,
                    path: name.as_str(),
                    rows: chunk.rows,
                    stored_bytes: actual,
                    kind: "output",
                },
            )?;
            manifest.write_all(b"\n")?;
            files += 1;
            total += chunk.bytes;
            processed += chunk.rows;
            ctx.event("Writing output", processed)?;
        }
    }
    ensure!(
        (files, total) == (analysis.output_files, analysis.output_csv_bytes),
        "execution disagrees with analyzed output plan"
    );
    manifest.sync_all()?;
    drop(manifest);
    finish_archive(archive, manifest_path.as_ref(), ctx)?;
    commit_directory(&mut stage, &destination, existing_empty, ctx)?;
    // Publication is the commit point: a later cancellation must not turn success into failure.
    (ctx.notify)(Progress {
        phase: crate::storage::ProgressPhase::literal("Complete"),
        rows: analysis.rows,
        temp_bytes: ctx.used(),
    });
    Ok(EnginePublication(()))
}

fn finish_archive(archive: Option<ZipStream>, manifest_path: &Path, ctx: &Context) -> Result<()> {
    if let Some(archive) = archive {
        let mut encoder =
            deflate::raw(archive.open_entry("manifest.jsonl")?, Reservation::new(ctx))?;
        let mut input = File::open(manifest_path)?;
        let mut crc = crc32fast::Hasher::new();
        let mut total = 0u64;
        let mut buffer = [0u8; 65536];
        loop {
            ctx.check()?;
            let n = input.read(&mut buffer)?;
            if n == 0 {
                break;
            }
            crc.update(&buffer[..n]);
            encoder.write_all(&buffer[..n])?;
            total += n as u64;
        }
        encoder
            .finish(flate2::write::DeflateEncoder::finish)?
            .finish("manifest.jsonl", total, crc.finalize(), ctx)?
            .finish(ctx)?;
    }
    Ok(())
}

// One-shot test seam at the actual commit boundary, shared by both producers.
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod commit_test_hook {
    use super::*;
    type Hook = Box<dyn FnOnce(&Context)>;
    thread_local! { static HOOK: std::cell::RefCell<Option<Hook>> = const { std::cell::RefCell::new(None) }; }
    pub(crate) struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            HOOK.with(|hook| hook.borrow_mut().take());
        }
    }
    pub(crate) fn install(hook: impl FnOnce(&Context) + 'static) -> Reset {
        HOOK.with(|slot| {
            assert!(slot.borrow().is_none());
            *slot.borrow_mut() = Some(Box::new(hook));
        });
        Reset
    }
    pub(super) fn committed(ctx: &Context) {
        let hook = HOOK.with(|slot| slot.borrow_mut().take());
        if let Some(hook) = hook {
            hook(ctx);
        }
    }
}
fn commit_directory(
    stage: &mut JobDirectory,
    destination: &Path,
    existing_empty: bool,
    ctx: &Context,
) -> Result<()> {
    ctx.check()?;
    if existing_empty {
        empty_destination(destination, false)?;
        // Non-recursive removal fails if any files appeared while the job ran.
        std::fs::remove_dir(destination)
            .context("remove empty output folder before publication")?;
    }
    publish_directory(stage.path(), destination, ctx)
        .context("publish completed result directory")?;
    stage.published();
    #[cfg(any(test, feature = "resource-contract-tests"))]
    commit_test_hook::committed(ctx);
    Ok(())
}

#[cfg(not(target_os = "wasi"))]
pub(crate) fn preflight_destination(job: &Job) -> Result<bool> {
    let output = &job.output;
    let check = || {
        job.validate_output()?;
        let destination = std::path::absolute(output)?;
        let existing_empty = empty_destination(&destination, false)?;
        let parent = destination.parent().context("invalid output directory")?;
        ensure!(parent.is_dir(), "output parent directory does not exist");
        Ok(existing_empty)
    };
    check().with_context(|| format!("choose a new or empty output directory instead of {output:?}"))
}

fn empty_destination(path: &Path, must_be_absent: bool) -> Result<bool> {
    // On Unix a trailing separator would make symlink_metadata follow the leaf.
    #[cfg(unix)]
    let path = path.components().as_path();
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            ensure!(
                !must_be_absent,
                "output destination appeared during Run; choose a different output directory and retry"
            );
            ensure!(
                metadata.is_dir() && !metadata.file_type().is_symlink(),
                "output destination must be a new or empty directory, not a file or link"
            );
            ensure!(
                std::fs::read_dir(path)?.next().is_none(),
                "output destination already exists and is not empty"
            );
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

#[cfg(windows)]
fn windows_publication_path(path: &Path, memory: &mut Reservation) -> Result<Vec<u16>> {
    use std::{
        os::windows::ffi::OsStrExt,
        path::{Component, Prefix},
    };
    // Both callers use std::path::absolute before staging. Its Windows normal
    // paths use GetFullPathNameW; retain existing verbatim/device namespaces.
    ensure!(path.is_absolute(), "publication requires absolute paths");
    let capacity = path
        .as_os_str()
        .encode_wide()
        .count()
        .checked_add(9)
        .context("publication wide path overflow")?;
    let mut wide = Vec::new();
    memory.reserve_vec(&mut wide, capacity)?;
    let units = path.as_os_str().encode_wide();
    match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(_) => {
                wide.extend(r"\\?\".encode_utf16());
                wide.extend(units);
            }
            Prefix::UNC(_, _) => {
                wide.extend(r"\\?\UNC\".encode_utf16());
                wide.extend(units.skip(2));
            }
            _ => wide.extend(units),
        },
        _ => anyhow::bail!("invalid absolute Windows publication path"),
    }
    ensure!(!wide.contains(&0), "publication path contains NUL");
    wide.push(0);
    Ok(wide)
}

fn publish_directory(source: &Path, destination: &Path, _ctx: &Context) -> Result<()> {
    #[cfg(windows)]
    {
        let mut memory = Reservation::new(_ctx);
        let source = windows_publication_path(source, &mut memory)?;
        let destination = windows_publication_path(destination, &mut memory)?;
        // No REPLACE_EXISTING or COPY_ALLOWED: same-volume atomic publication
        // must fail even when a competing destination directory is empty.
        if unsafe {
            windows_sys::Win32::Storage::FileSystem::MoveFileExW(
                source.as_ptr(),
                destination.as_ptr(),
                0,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
    }
    #[cfg(target_os = "wasi")]
    {
        std::fs::rename(source, destination)?;
    }
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        let source = std::ffi::CString::new(source.as_os_str().as_bytes())?;
        let destination = std::ffi::CString::new(destination.as_os_str().as_bytes())?;
        #[cfg(target_os = "linux")]
        let result = unsafe {
            libc::renameat2(
                libc::AT_FDCWD,
                source.as_ptr(),
                libc::AT_FDCWD,
                destination.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        };
        #[cfg(target_os = "macos")]
        let result =
            unsafe { libc::renamex_np(source.as_ptr(), destination.as_ptr(), libc::RENAME_EXCL) };
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        compile_error!("Chopper publication currently supports Windows, macOS and Linux");
        if result != 0 {
            let error = std::io::Error::last_os_error();
            if matches!(
                error.raw_os_error(),
                Some(libc::EINVAL | libc::ENOSYS | libc::EOPNOTSUPP)
            ) {
                anyhow::bail!("output filesystem does not support atomic publication without replacement; choose a native local filesystem (for WSL, use the Linux filesystem rather than /mnt/c): {error}");
            }
            return Err(error.into());
        }
    }
    Ok(())
}

/// Streaming ZIP64 writer. Central-directory records are spooled under the same temp budget.
struct ObservedArchiveWriter<'a> {
    writer: &'a mut PublicationWriter,
    observation: &'a mut Option<OutputObservation>,
}
impl Write for ObservedArchiveWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let result = self.writer.write(bytes);
        if let Some(observation) = &mut self.observation {
            observation.written(&result);
        }
        result
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.writer.flush()
    }
}
impl ObservedArchiveWriter<'_> {
    fn sync_all(&mut self) -> Result<()> {
        self.writer.sync_all()
    }
}
struct ZipStream {
    observation: Option<OutputObservation>,
    output: PublicationWriter,
    directory: DiskFile,
    offset: u64,
    entries: u64,
}
// Keep the bounded in-memory member and its grant inline.
#[allow(clippy::large_enum_variant)]
enum ZipTarget {
    Spool(DiskFile),
    Memory {
        bytes: Vec<u8>,
        ctx: Context,
        _memory: Reservation,
    },
    Archive {
        entry: Box<ZipEntry>,
        _memory: Reservation,
    },
}
impl ZipTarget {
    fn spool(ctx: &Context, csv_bytes: u64) -> Result<Self> {
        const MIB: u64 = 1024 * 1024;
        if csv_bytes <= 2 * MIB {
            let capacity = (csv_bytes + csv_bytes / 8 + 256).min(MIB / 2) as usize;
            let mut memory = Reservation::new(ctx);
            let mut bytes = Vec::new();
            if memory.reserve_vec(&mut bytes, capacity).is_ok() {
                return Ok(Self::Memory {
                    bytes,
                    ctx: ctx.clone(),
                    _memory: memory,
                });
            }
        }
        Ok(Self::Spool(ctx.file()?))
    }
    fn len(&self) -> u64 {
        match self {
            Self::Spool(file) => file.len(),
            Self::Memory { bytes, .. } => bytes.len() as u64,
            Self::Archive { entry, .. } => entry.compressed_bytes,
        }
    }
    fn reader(&self, ctx: &Context) -> Result<ZipMemberReader<'_>> {
        match self {
            Self::Spool(file) => Ok(ZipMemberReader::Disk(publication_reader(file, ctx)?)),
            Self::Memory { bytes, .. } => Ok(ZipMemberReader::Memory(bytes)),
            Self::Archive { .. } => anyhow::bail!("ZIP member is already in the archive"),
        }
    }
    fn start(archive: ZipStream, name: &str, memory: Reservation) -> Result<Self> {
        Ok(Self::Archive {
            entry: Box::new(archive.open_entry(name)?),
            _memory: memory,
        })
    }
}
impl Write for ZipTarget {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        match self {
            Self::Spool(file) => file.write(bytes),
            Self::Memory {
                bytes: buffered,
                ctx,
                ..
            } => {
                if bytes.len() <= buffered.capacity() - buffered.len() {
                    buffered.extend_from_slice(bytes);
                    return Ok(bytes.len());
                }
                let mut file = ctx.file().map_err(std::io::Error::other)?;
                file.write_all(buffered)?;
                let written = file.write(bytes)?;
                *self = Self::Spool(file);
                Ok(written)
            }
            Self::Archive { entry, .. } => entry.write(bytes),
        }
    }
    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Self::Spool(file) => file.flush(),
            Self::Memory { .. } => Ok(()),
            Self::Archive { entry, .. } => entry.flush(),
        }
    }
}

enum ZipMemberReader<'a> {
    Disk(PublicationReader),
    Memory(&'a [u8]),
}
impl Read for ZipMemberReader<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        match self {
            Self::Disk(reader) => reader.read(bytes),
            Self::Memory(reader) => reader.read(bytes),
        }
    }
}

/// Own the archive while a serial publication path deflates directly into it.
struct ZipEntry {
    archive: ZipStream,
    compressed_bytes: u64,
}

impl Write for ZipEntry {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let written = self.archive.writer().write(bytes)?;
        self.compressed_bytes = self
            .compressed_bytes
            .checked_add(written as u64)
            .ok_or_else(|| std::io::Error::other("ZIP compressed size overflow"))?;
        Ok(written)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.archive.writer().flush()
    }
}
impl ZipEntry {
    fn finish(mut self, name: &str, size: u64, crc: u32, ctx: &Context) -> Result<ZipStream> {
        let result = (|| {
            ctx.check()?;
            let compressed = self.compressed_bytes;
            let offset = self.archive.offset;
            let end = offset
                .checked_add(50 + name.len() as u64)
                .and_then(|bytes| bytes.checked_add(compressed))
                .context("ZIP member offset overflow")?;
            // Patch the private ZIP64 local header in place. Keep archive
            // observations about the final logical byte stream, including the
            // original placeholders once and counting no patch-write bytes.
            let writer = &mut self.archive.output.writer;
            writer.seek(SeekFrom::Start(offset + 14))?;
            u32le(writer, crc)?;
            writer.seek(SeekFrom::Start(offset + 34 + name.len() as u64))?;
            u64le(writer, size)?;
            u64le(writer, compressed)?;
            writer.seek(SeekFrom::Start(end))?;
            self.archive.record_entry(name, compressed, size, crc, end)
        })();
        self.archive.report_entry_error(&result);
        result?;
        Ok(self.archive)
    }
}
fn u16le(w: &mut impl Write, n: u16) -> Result<()> {
    w.write_all(&n.to_le_bytes())?;
    Ok(())
}
fn u32le(w: &mut impl Write, n: u32) -> Result<()> {
    w.write_all(&n.to_le_bytes())?;
    Ok(())
}
fn u64le(w: &mut impl Write, n: u64) -> Result<()> {
    w.write_all(&n.to_le_bytes())?;
    Ok(())
}
impl ZipStream {
    fn new(path: impl AsRef<Path>, ctx: &Context) -> Result<Self> {
        Ok(Self {
            observation: None,
            output: PublicationWriter::new(path, PUBLICATION_BUFFER, ctx)?,
            directory: ctx.file()?,
            offset: 0,
            entries: 0,
        })
    }
    fn observed(path: impl AsRef<Path>, job: &Job, ctx: &Context) -> Result<Self> {
        let mut observation =
            OutputObservation::new(job, ctx, crate::observation::physical::Kind::ZipArchive);
        match Self::new(path, ctx) {
            Ok(mut archive) => {
                archive.observation = observation;
                Ok(archive)
            }
            Err(error) => {
                if let Some(observation) = &mut observation {
                    observation.finish(crate::observation::physical::error_status(&error));
                }
                Err(error)
            }
        }
    }
    fn writer(&mut self) -> ObservedArchiveWriter<'_> {
        ObservedArchiveWriter {
            writer: &mut self.output,
            observation: &mut self.observation,
        }
    }
    fn member_source(&mut self, name: &str) {
        if name != "manifest.jsonl" {
            if let Some(observation) = &mut self.observation {
                if let Some(attempt) = &mut observation.attempt {
                    attempt.source(
                        observation
                            .ctx
                            .physical_identity(crate::observation::physical::Kind::ZipDeflate),
                    );
                }
            }
        }
    }
    fn local_header(&mut self, name: &str, compressed: u64, size: u64, crc: u32) -> Result<()> {
        ensure!(name.len() <= u16::MAX as usize, "ZIP member name too long");
        let w = &mut self.writer();
        u32le(w, 0x04034b50)?;
        u16le(w, 45)?;
        u16le(w, 0x800)?;
        u16le(w, 8)?;
        u16le(w, 0)?;
        u16le(w, 33)?;
        u32le(w, crc)?;
        u32le(w, u32::MAX)?;
        u32le(w, u32::MAX)?;
        u16le(w, name.len() as u16)?;
        u16le(w, 20)?;
        w.write_all(name.as_bytes())?;
        u16le(w, 1)?;
        u16le(w, 16)?;
        u64le(w, size)?;
        u64le(w, compressed)?;
        Ok(())
    }
    fn report_entry_error<T>(&mut self, result: &Result<T>) {
        if let (Err(error), Some(observation)) = (result, &mut self.observation) {
            observation.finish(crate::observation::physical::error_status(error));
        }
    }
    fn open_entry(mut self, name: &str) -> Result<ZipEntry> {
        self.member_source(name);
        let result = self.local_header(name, 0, 0, 0);
        self.report_entry_error(&result);
        result?;
        Ok(ZipEntry {
            archive: self,
            compressed_bytes: 0,
        })
    }
    fn add(
        &mut self,
        name: &str,
        mut compressed: impl Read,
        compressed_size: u64,
        size: u64,
        crc: u32,
        ctx: &Context,
    ) -> Result<()> {
        self.member_source(name);
        let result = (|| {
            self.local_header(name, compressed_size, size, crc)?;
            let w = &mut self.writer();
            let mut buffer = [0u8; 65536];
            let mut copied = 0;
            loop {
                ctx.check()?;
                let n = compressed.read(&mut buffer)?;
                if n == 0 {
                    break;
                }
                w.write_all(&buffer[..n])?;
                copied += n as u64;
            }
            ensure!(copied == compressed_size, "truncated compressed ZIP member");
            let end = self
                .offset
                .checked_add(50 + name.len() as u64)
                .and_then(|bytes| bytes.checked_add(compressed_size))
                .context("ZIP member offset overflow")?;
            self.record_entry(name, compressed_size, size, crc, end)
        })();
        self.report_entry_error(&result);
        result
    }
    fn record_entry(
        &mut self,
        name: &str,
        compressed_size: u64,
        size: u64,
        crc: u32,
        end: u64,
    ) -> Result<()> {
        let local_offset = self.offset;
        self.offset = end;
        let d = &mut self.directory;
        u32le(d, 0x02014b50)?;
        u16le(d, 45)?;
        u16le(d, 45)?;
        u16le(d, 0x800)?;
        u16le(d, 8)?;
        u16le(d, 0)?;
        u16le(d, 33)?;
        u32le(d, crc)?;
        u32le(d, u32::MAX)?;
        u32le(d, u32::MAX)?;
        u16le(d, name.len() as u16)?;
        u16le(d, 28)?;
        u16le(d, 0)?;
        u16le(d, 0)?;
        u16le(d, 0)?;
        u32le(d, 0)?;
        u32le(d, u32::MAX)?;
        d.write_all(name.as_bytes())?;
        u16le(d, 1)?;
        u16le(d, 24)?;
        u64le(d, size)?;
        u64le(d, compressed_size)?;
        u64le(d, local_offset)?;
        self.entries += 1;
        if let Some(observation) = &mut self.observation {
            observation.entries += 1;
        }
        Ok(())
    }

    fn finish(mut self, ctx: &Context) -> Result<()> {
        let result = (|| -> Result<()> {
            ctx.check()?;
            let directory_size = self.directory.len();
            let mut reader = publication_reader(&self.directory, ctx)?;
            let mut buffer = [0u8; 65536];
            let w = &mut ObservedArchiveWriter {
                writer: &mut self.output,
                observation: &mut self.observation,
            };
            loop {
                ctx.check()?;
                let n = reader.read(&mut buffer)?;
                if n == 0 {
                    break;
                }
                w.write_all(&buffer[..n])?;
            }
            let zip64_offset = self.offset + directory_size;
            u32le(w, 0x06064b50)?;
            u64le(w, 44)?;
            u16le(w, 45)?;
            u16le(w, 45)?;
            u32le(w, 0)?;
            u32le(w, 0)?;
            u64le(w, self.entries)?;
            u64le(w, self.entries)?;
            u64le(w, directory_size)?;
            u64le(w, self.offset)?;
            u32le(w, 0x07064b50)?;
            u32le(w, 0)?;
            u64le(w, zip64_offset)?;
            u32le(w, 1)?;
            u32le(w, 0x06054b50)?;
            u16le(w, 0)?;
            u16le(w, 0)?;
            u16le(w, u16::MAX)?;
            u16le(w, u16::MAX)?;
            u32le(w, u32::MAX)?;
            u32le(w, u32::MAX)?;
            u16le(w, 0)?;
            w.sync_all()?;
            Ok(())
        })();
        if let Some(observation) = &mut self.observation {
            observation.finish(result.as_ref().err().map_or(
                crate::observation::Status::Completed,
                crate::observation::physical::error_status,
            ));
        }
        result
    }
}

impl PlanWriter<'_> {
    pub(crate) fn write_fields<'a>(
        &mut self,
        group: &mut Group,
        fields: impl IntoIterator<Item = &'a str> + Clone,
    ) -> Result<()> {
        let result = (|| -> Result<()> {
            self.ctx.check()?;
            let prefix_capacity = self.prefix.capacity();
            if let Some(span) = &mut self.observation {
                span.start();
            }
            let size = self
                .serializer
                .serialize_fields_reserved(fields, &mut |bytes| {
                    self._serialization.resize(
                        prefix_capacity
                            .checked_add(bytes)
                            .context("output serialization overflow")?,
                    )
                })?
                .len() as u64;
            self.prepare_encoded_row(group, size)?;
            self.target.write_all(self.serializer.bytes())?;
            self.finish_encoded_row(group, size)
        })();
        if let Err(error) = &result {
            self.observe_error(error);
        }
        result
    }
    fn prepare_encoded_row(&mut self, group: &Group, size: u64) -> Result<()> {
        let hard = self.job.limits.bytes.unwrap_or(u64::MAX);
        ensure!(
            self.prefix.len() as u64 + size <= hard,
            "one row plus header exceeds output byte limit"
        );
        let soft = self
            .job
            .limits
            .compressed_bytes
            .map(|v| v.saturating_sub(128).saturating_mul(100) / 105)
            .unwrap_or(u64::MAX);
        if let Some(chunk) = &self.chunk {
            let chunk = &chunk.value;
            let overflow = chunk.rows >= self.job.limits.rows.unwrap_or(u64::MAX)
                || chunk.bytes.saturating_add(size) > hard;
            if chunk.rows > 0
                && (overflow || (!group.exact && chunk.bytes.saturating_add(size) > soft))
            {
                ensure!(!group.exact, "balanced group cannot satisfy final row/byte limits without changing its exact file count");
                self.close()?;
            }
        }
        if self.chunk.is_none() {
            self.open(group)?;
        }
        Ok(())
    }
    fn finish_encoded_row(&mut self, group: &mut Group, size: u64) -> Result<()> {
        let chunk = &mut self.chunk.as_mut().unwrap().value;
        chunk.rows += 1;
        chunk.bytes += size;
        group.rows += 1;
        self.processed += 1;
        if let Some(span) = &mut self.observation {
            span.rows_processed(self.processed);
        }
        if self.processed.is_multiple_of(65536) {
            self.ctx.event("Serializing output", self.processed)?;
        }
        Ok(())
    }
    pub(crate) fn write_serialized(
        &mut self,
        group: &mut Group,
        serialized: &csv::Serializer,
    ) -> Result<()> {
        let result = (|| {
            self.ctx.check()?;
            if let Some(span) = &mut self.observation {
                span.start();
            }
            let bytes = serialized.bytes();
            let size = bytes.len() as u64;
            self.prepare_encoded_row(group, size)?;
            self.target.write_all(bytes)?;
            self.finish_encoded_row(group, size)
        })();
        if let Err(error) = &result {
            self.observe_error(error);
        }
        result
    }
}

#[cfg(test)]
mod buffer_tests {
    use super::*;
    use std::sync::{atomic::AtomicBool, Arc};

    fn context() -> Result<Context> {
        Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024)),
        )
    }

    #[test]
    fn prepared_zip_member_buffer_spills_in_order_at_its_bound() -> Result<()> {
        let ctx = context()?;
        let mut member = ZipTarget::spool(&ctx, 1024 * 1024)?;
        let prefix = vec![0x13; 512 * 1024];
        member.write_all(&prefix)?;
        assert!(matches!(member, ZipTarget::Memory { .. }));
        assert_eq!(ctx.used(), 0);
        member.write_all(&[0x37])?;
        assert!(matches!(member, ZipTarget::Spool(_)));
        assert_eq!(ctx.used(), prefix.len() as u64 + 1);
        let mut restored = Vec::new();
        member.reader(&ctx)?.read_to_end(&mut restored)?;
        assert_eq!(restored.pop(), Some(0x37));
        assert_eq!(restored, prefix);
        drop(member);
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn observed_archive_constructor_denial_is_attributed_and_releases_capacity() -> Result<()> {
        use crate::observation::{
            physical::{Fact, Kind},
            Status,
        };
        use std::sync::Mutex;
        let dir = tempfile::tempdir()?;
        let pool = Arc::new(crate::resources::MemoryPool::new(16 * 1024));
        let mut ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let path = dir.path().join("denied.zip");
        assert!(ZipStream::observed(&path, &Job::default(), &ctx).is_err());
        assert!(!path.exists());
        let facts = facts.lock().unwrap();
        assert!(facts
            .iter()
            .any(|f| f.kind == Kind::ZipArchive && f.status == Status::Failed && f.bytes == 0));
        assert!(!facts
            .iter()
            .any(|f| f.kind == Kind::ZipArchive && f.status == Status::Interrupted));
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn buffered_snapshot_flush_failure_retains_partial_rows_and_releases_owners() -> Result<()> {
        use crate::observation::{
            physical::{Fact, Kind},
            Status,
        };
        use std::sync::Mutex;
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let mut ctx = Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                temp_bytes: Some(1),
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let facts = Arc::new(Mutex::new(Vec::<Fact>::new()));
        let seen = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            seen.lock().unwrap().push(fact);
            true
        }));
        let job = Job {
            operations: vec![Operation::Balanced { files: 1 }],
            ..Default::default()
        };
        let header = vec!["id".to_owned()];
        let mut writer = PlanWriter::new(&job, Some(&header), &ctx)?;
        assert!(
            !facts
                .lock()
                .unwrap()
                .iter()
                .any(|f| f.kind == Kind::Serialize),
            "snapshot writer setup must not announce serialization before any rows"
        );
        let mut group = writer.begin(vec![], false);
        writer.row(
            &mut group,
            &Row {
                id: 0,
                ordinal: 0,
                key: vec![],
                fields: vec!["1".into()],
            },
        )?;
        writer.end(group)?;
        assert!(writer.finish().is_err());
        let facts = facts.lock().unwrap();
        assert!(facts
            .iter()
            .any(|f| f.kind == Kind::Serialize && f.status == Status::Failed && f.rows == 1));
        assert!(!facts
            .iter()
            .any(|f| f.kind == Kind::Serialize && f.status == Status::Completed));
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn publication_writer_boundaries_precede_file_creation_and_allow_retry() -> Result<()> {
        let dir = tempfile::tempdir()?;
        for capacity in [MANIFEST_BUFFER, PUBLICATION_BUFFER] {
            for limit in [capacity - 1, capacity, capacity + 1] {
                let path = dir.path().join(format!("{capacity}-{limit}"));
                let workspace = Arc::new(Workspace::new(limit));
                let result = PublicationWriter::with_reservation(
                    &path,
                    capacity,
                    Reservation::for_workspace(workspace.clone()),
                );
                assert_eq!(result.is_ok(), limit >= capacity);
                assert_eq!(path.exists(), limit >= capacity);
                if let Ok(mut writer) = result {
                    assert_eq!(writer.writer.capacity(), capacity);
                    assert_eq!(workspace.used(), capacity as u64);
                    writer.write_all(b"buffered")?;
                    writer.sync_all()?;
                    assert_eq!(workspace.used(), capacity as u64);
                    drop(writer);
                    assert_eq!(std::fs::read(&path)?, b"buffered");
                }
                assert_eq!(workspace.used(), 0);
                let mut competing = Reservation::for_workspace(workspace.clone());
                competing.resize(limit)?;
                assert!(PublicationWriter::with_reservation(
                    dir.path().join("denied"),
                    capacity,
                    Reservation::for_workspace(workspace.clone()),
                )
                .is_err());
                assert!(!dir.path().join("denied").exists());
                assert_eq!(workspace.used(), limit as u64);
                drop(competing);
                if limit >= capacity {
                    drop(PublicationWriter::with_reservation(
                        &path,
                        capacity,
                        Reservation::for_workspace(workspace.clone()),
                    )?);
                    assert_eq!(workspace.used(), 0);
                }
            }
        }
        let workspace = Arc::new(Workspace::new(PUBLICATION_BUFFER));
        assert!(PublicationWriter::with_reservation(
            dir.path().join("missing/output"),
            PUBLICATION_BUFFER,
            Reservation::for_workspace(workspace.clone()),
        )
        .is_err());
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn publication_read_and_heap_copy_exact_capacity_and_drop() -> Result<()> {
        let ctx = context()?;
        let mut file = ctx.file()?;
        file.write_all(b"snapshot")?;
        for limit in [DISK_READ_BUFFER - 1, DISK_READ_BUFFER, DISK_READ_BUFFER + 1] {
            let workspace = Arc::new(Workspace::new(limit));
            let result = PublicationReader::with_reservation(
                &file,
                Reservation::for_workspace(workspace.clone()),
            );
            assert_eq!(result.is_ok(), limit >= DISK_READ_BUFFER);
            if let Ok(mut reader) = result {
                assert_eq!(reader.reader.capacity(), DISK_READ_BUFFER);
                assert_eq!(workspace.used(), DISK_READ_BUFFER as u64);
                let mut bytes = [0; 8];
                reader.read_exact(&mut bytes)?;
                assert_eq!(&bytes, b"snapshot");
            }
            assert_eq!(workspace.used(), 0);
        }
        for limit in [256 * 1024 - 1, 256 * 1024, 256 * 1024 + 1] {
            let workspace = Arc::new(Workspace::new(limit));
            let result = PublicationCopyBuffer::with_reservation(Reservation::for_workspace(
                workspace.clone(),
            ));
            assert_eq!(result.is_ok(), limit >= 256 * 1024);
            if let Ok(buffer) = result {
                assert_eq!(buffer.bytes.len(), 256 * 1024);
                assert_eq!(workspace.used(), buffer.bytes.capacity() as u64);
            }
            assert_eq!(workspace.used(), 0);
        }
        let retained = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        let buffer = PublicationCopyBuffer::new(&ctx)?;
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            retained + buffer.bytes.capacity() as u64
        );
        drop(buffer);
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], retained);
        Ok(())
    }

    #[test]
    fn publication_codec_writer_charge_follows_worker_and_finish() -> Result<()> {
        let dir = tempfile::tempdir()?;
        for compression in [Compression::None, Compression::Gzip] {
            let required = PUBLICATION_BUFFER
                + match compression {
                    Compression::Gzip => deflate::CAPACITY,
                    _ => 0,
                };
            let workspace = Arc::new(Workspace::new(required));
            let writer = PublicationWriter::with_reservation(
                dir.path().join(format!("{compression:?}")),
                PUBLICATION_BUFFER,
                Reservation::for_workspace(workspace.clone()),
            )?;
            let mut sink = match compression {
                Compression::None => Sink::Plain(writer),
                Compression::Gzip => Sink::Gzip(deflate::gzip(
                    writer,
                    Reservation::for_workspace(workspace.clone()),
                )?),
                _ => unreachable!(),
            };
            sink.write_all(b"payload")?;
            let ready = Arc::new(std::sync::Barrier::new(2));
            let signal = ready.clone();
            let handle = std::thread::spawn(move || {
                signal.wait();
                signal.wait();
                sink.finish().map(|_| ())
            });
            ready.wait();
            assert_eq!(workspace.used(), required as u64);
            let mut other = Reservation::for_workspace(workspace.clone());
            assert!(other.resize(1).is_err());
            assert_eq!(workspace.used(), required as u64);
            ready.wait();
            handle.join().unwrap()?;
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn zip_writer_retains_buffer_through_assembly_and_failure() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let ctx = context()?;
        let baseline = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        let mut archive = ZipStream::new(dir.path().join("outputs.zip"), &ctx)?;
        let retained = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap();
        assert!(retained >= baseline + PUBLICATION_BUFFER as u64);
        assert_eq!(archive.output.writer.capacity(), PUBLICATION_BUFFER);
        let error = archive
            .add("bad", std::io::empty(), 1, 1, 0, &ctx)
            .unwrap_err();
        assert!(error.to_string().contains("truncated"));
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], retained);
        drop(archive);
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        let mut archive = ZipStream::new(dir.path().join("retry.zip"), &ctx)?;
        let mut encoder = flate2::write::DeflateEncoder::new(Vec::new(), Default::default());
        encoder.write_all(b"payload")?;
        let compressed = encoder.finish()?;
        archive.add(
            "data.csv",
            compressed.as_slice(),
            compressed.len() as u64,
            7,
            crc32fast::hash(b"payload"),
            &ctx,
        )?;
        archive.finish(&ctx)?;
        assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], baseline);
        let mut archive = zip::ZipArchive::new(File::open(dir.path().join("retry.zip"))?)?;
        let mut actual = String::new();
        archive.by_name("data.csv")?.read_to_string(&mut actual)?;
        assert_eq!(actual, "payload");
        Ok(())
    }

    #[test]
    fn publication_manifest_denial_and_cancellation_clean_staging_then_retry() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        std::fs::write(&input, "id,label\n1,one\n2,two\n")?;
        for compression in [Compression::None, Compression::Gzip, Compression::Zip] {
            let output = dir.path().join(format!("{compression:?}"));
            let job = Job {
                input: input.to_string_lossy().into(),
                output: output.to_string_lossy().into(),
                compression,
                random_seed: Some("publication-denial".into()),
                resources: chopper_core::Resources {
                    workers: 1,
                    memory_mb: 32.into(),
                    max_record_bytes: 1024 * 1024,
                    ..Default::default()
                },
                ..Default::default()
            };
            let limit = 64 * 1024 * 1024;
            let pool = Arc::new(crate::resources::MemoryPool::new(limit));
            let cancel = Arc::new(AtomicBool::new(false));
            let prepared = crate::engine::prepare_with_memory_pool(
                job,
                cancel.clone(),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let retained = pool.usage().reserved_bytes;
            let mut pressure = Reservation::for_workspace(Arc::new(Workspace::shared(
                limit as usize,
                pool.clone(),
            )));
            pressure.resize(limit as usize - retained as usize - MANIFEST_BUFFER + 1)?;
            let held = pool.usage().reserved_bytes;
            let error = execute(&prepared).unwrap_err();
            assert!(error.to_string().contains("memory"), "{error:#}");
            assert_eq!(pool.usage().reserved_bytes, held);
            assert!(!output.exists());
            drop(pressure);
            cancel.store(true, std::sync::atomic::Ordering::Relaxed);
            assert!(execute(&prepared).is_err());
            assert_eq!(pool.usage().reserved_bytes, retained);
            assert!(!output.exists());
            assert!(!std::fs::read_dir(dir.path())?.any(|entry| entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".chopper-staging-")));
            cancel.store(false, std::sync::atomic::Ordering::Relaxed);
            execute(&prepared)?;
            assert!(output.join("manifest.jsonl").is_file());
            assert_eq!(pool.usage().reserved_bytes, retained);
            drop(prepared);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn catalog_peek_batch_and_thread_owners_retain_decoded_lineage() -> Result<()> {
        let ctx = context()?;
        let job = Job::default();
        let mut writer = PlanWriter::new(&job, None, &ctx)?;
        for index in 0..2 {
            let mut group = writer.begin(
                vec![json!({"partition":{"values":["escaped界", index]}})],
                false,
            );
            writer.row(
                &mut group,
                &Row {
                    id: index,
                    ordinal: index,
                    key: vec![],
                    fields: vec![index.to_string()],
                },
            )?;
            writer.end(group)?;
        }
        let plan = writer.finish()?;
        let mut chunks = plan.chunks()?.peekable();
        let first_charge = chunks
            .peek()
            .unwrap()
            .as_ref()
            .unwrap()
            .group
            .lineage
            .json_capacity()?;
        assert!(first_charge > 0);
        let mut batch = vec![chunks.next().unwrap()?];
        batch.push(chunks.next().unwrap()?);
        let retained = batch
            .iter()
            .map(|chunk| chunk.group.lineage.json_capacity())
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .sum::<usize>() as u64;
        assert!(chunks.next().is_none());
        drop(chunks);
        drop(plan);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes() + retained
        );
        let ready = Arc::new(std::sync::Barrier::new(2));
        let signal = ready.clone();
        let handle = std::thread::spawn(move || {
            assert_eq!(
                batch[0].group.lineage[0]["partition"]["values"][0],
                "escaped界"
            );
            signal.wait();
            signal.wait();
            drop(batch);
        });
        ready.wait();
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes() + retained
        );
        ready.wait();
        handle.join().unwrap();
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }

    #[test]
    fn catalog_decode_denial_rolls_back_publication_then_retries() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        std::fs::write(&input, "id,label\n1,escaped\n2,wide\n")?;
        let job = Job {
            input: input.to_string_lossy().into(),
            output: dir.path().join("out").to_string_lossy().into(),
            random_seed: Some("catalog-denial".into()),
            resources: chopper_core::Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            ..Job::default()
        };
        let limit = 64 * 1024 * 1024;
        let pool = Arc::new(crate::resources::MemoryPool::new(limit));
        let prepared = crate::engine::prepare_with_memory_pool(
            job.clone(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let retained = pool.usage().reserved_bytes;
        let line = prepared.output_plan.catalog.len() as usize - 1;
        let reader_capacity = prepared.output_plan.catalog.reader()?.capacity();
        let scratch = line.max(8).next_power_of_two() * 2;
        let other = Arc::new(Workspace::shared(limit as usize, pool.clone()));
        let mut pressure = Reservation::for_workspace(other);
        // Admit the reader, encoded line and parser scratch, then deny the
        // decoded-tree grant after native staging/manifest creation has begun.
        pressure.resize(
            limit as usize - retained as usize - MANIFEST_BUFFER - reader_capacity - line - scratch,
        )?;
        let held = pool.usage().reserved_bytes;
        let error = execute(&prepared).unwrap_err();
        assert!(error.to_string().contains("memory"), "{error:#}");
        assert_eq!(pool.usage().reserved_bytes, held);
        assert!(!Path::new(&job.output).exists());
        assert!(!std::fs::read_dir(dir.path())?.any(|entry| entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".chopper-staging-")));
        drop(pressure);
        execute(&prepared)?;
        assert_eq!(pool.usage().reserved_bytes, retained);
        assert!(dir.path().join("out/manifest.jsonl").is_file());
        drop(prepared);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn borrowed_manifest_record_preserves_encoded_json_bytes() -> Result<()> {
        let lineage = vec![json!({"partition":{"values":["界", "quoted\nvalue"]}})];
        let record = OutputRecord {
            compressed_target_exceeded: false,
            csv_bytes: 12,
            lineage: &lineage,
            path: "part-1.csv",
            rows: 2,
            stored_bytes: 10,
            kind: "output",
        };
        let original = json!({"type":"output","path":"part-1.csv","rows":2,"csv_bytes":12,"stored_bytes":10,"lineage":lineage,"compressed_target_exceeded":false});
        assert_eq!(serde_json::to_vec(&record)?, serde_json::to_vec(&original)?);
        Ok(())
    }

    #[test]
    fn snapshot_buffers_exact_shared_capacity_and_retry() -> Result<()> {
        let ctx = context()?;
        let job = Job::default();
        let bytes = PLAN_DATA_BUFFER + PLAN_CATALOG_BUFFER;
        for limit in [bytes - 1, bytes, bytes + 1] {
            let workspace = Arc::new(Workspace::new(limit));
            let result = PlanWriter::with_buffers(
                &job,
                None,
                &ctx,
                Reservation::for_workspace(workspace.clone()),
            );
            assert_eq!(result.is_ok(), limit >= bytes);
            if let Ok(writer) = result {
                assert_eq!(workspace.used(), bytes as u64);
                let EncodedTarget::Snapshot { data, catalog } = &writer.target else {
                    unreachable!()
                };
                assert_eq!(data.capacity(), PLAN_DATA_BUFFER);
                assert_eq!(catalog.capacity(), PLAN_CATALOG_BUFFER);
                drop(writer);
            }
            assert_eq!(workspace.used(), 0);
            assert_eq!(ctx.used(), 0);
            let mut competing = Reservation::for_workspace(workspace.clone());
            competing.resize(limit)?;
            assert!(PlanWriter::with_buffers(
                &job,
                None,
                &ctx,
                Reservation::for_workspace(workspace.clone())
            )
            .is_err());
            assert_eq!(workspace.used(), limit as u64);
            drop(competing);
            if limit >= bytes {
                drop(PlanWriter::with_buffers(
                    &job,
                    None,
                    &ctx,
                    Reservation::for_workspace(workspace.clone()),
                )?);
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn finished_snapshot_releases_writer_buffers_but_keeps_output() -> Result<()> {
        let ctx = context()?;
        let job = Job::default();
        let workspace = Arc::new(Workspace::new(PLAN_DATA_BUFFER + PLAN_CATALOG_BUFFER));
        let mut writer = PlanWriter::with_buffers(
            &job,
            None,
            &ctx,
            Reservation::for_workspace(workspace.clone()),
        )?;
        let mut group = writer.begin(vec![], false);
        writer.row(
            &mut group,
            &Row {
                id: 0,
                ordinal: 0,
                key: vec![],
                fields: vec!["quoted,\n界".into()],
            },
        )?;
        writer.end(group)?;
        let plan = writer.finish()?;
        assert_eq!(workspace.used(), 0);
        let mut bytes = Vec::new();
        plan.data.reader()?.read_to_end(&mut bytes)?;
        assert_eq!(bytes, "\"quoted,\n界\"\n".as_bytes());
        assert_eq!(plan.chunks()?.count(), 1);
        drop(plan);
        assert_eq!(ctx.used(), 0);
        Ok(())
    }

    #[test]
    fn constructor_failures_release_buffers_and_partial_files() -> Result<()> {
        let ctx = context()?;
        let mut job = Job::default();
        job.limits.bytes = Some(1);
        let workspace = Arc::new(Workspace::new(PLAN_DATA_BUFFER + PLAN_CATALOG_BUFFER));
        assert!(PlanWriter::with_buffers(
            &job,
            Some(&["header".into()]),
            &ctx,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err());
        assert_eq!(workspace.used(), 0);
        assert_eq!(ctx.used(), 0);
        job.limits.bytes = None;
        job.output_csv.encoding = "invalid-encoding".into();
        assert!(PlanWriter::with_buffers(
            &job,
            None,
            &ctx,
            Reservation::for_workspace(workspace.clone())
        )
        .is_err());
        assert_eq!(workspace.used(), 0);
        assert_eq!(ctx.used(), 0);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }

    #[test]
    fn serializer_pressure_precedes_output_and_releases_at_finish() -> Result<()> {
        let ctx = context()?;
        let job = Job::default();
        let mut writer = PlanWriter::new(&job, None, &ctx)?;
        let workspace = Arc::new(Workspace::new(1000));
        writer._serialization = Reservation::for_workspace(workspace.clone());
        let mut group = writer.begin(vec![], false);
        let mut row = Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["x".repeat(1000)],
        };
        assert!(writer.row(&mut group, &row).is_err());
        assert_eq!(workspace.used(), 0);
        assert_eq!(writer.files, 0);
        assert_eq!(group.rows, 0);
        let mut other = Reservation::for_workspace(workspace.clone());
        other.resize(1000)?;
        row.fields[0] = "x".into();
        assert!(writer.row(&mut group, &row).is_err());
        assert_eq!(workspace.used(), 1000);
        assert_eq!(writer.files, 0);
        drop(other);
        writer.row(&mut group, &row)?;
        assert_eq!(workspace.used(), writer.serializer.capacity() as u64);
        writer.end(group)?;
        let plan = writer.finish()?;
        assert_eq!(workspace.used(), 0);
        assert_eq!(plan.bytes, 2);
        drop(plan);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }

    #[test]
    fn encoded_prefix_and_serializer_capacities_live_through_hard_cap_failure() -> Result<()> {
        let ctx = context()?;
        let mut job = Job::default();
        job.output_csv.encoding = "utf-16be".into();
        job.output_csv.bom = true;
        let header = vec!["名,\"".into()];
        let row = Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["界😀".into()],
        };
        let mut expected = csv::bom(&job.output_csv)?;
        expected.extend(csv::serialize(&header, &job.output_csv)?);
        expected.extend(csv::serialize(&row.fields, &job.output_csv)?);
        job.limits.bytes = Some(expected.len() as u64);
        let mut writer = PlanWriter::new(&job, Some(&header), &ctx)?;
        assert_eq!(
            writer._serialization.bytes() as usize,
            writer.prefix.capacity() + writer.serializer.capacity()
        );
        let mut group = writer.begin(vec![], false);
        let wide = Row {
            fields: vec!["x".repeat(1000)],
            ..row.clone()
        };
        assert!(writer.row(&mut group, &wide).is_err());
        assert_eq!(writer.files, 0);
        assert_eq!(
            writer._serialization.bytes() as usize,
            writer.prefix.capacity() + writer.serializer.capacity()
        );
        writer.row(&mut group, &row)?;
        writer.end(group)?;
        let plan = writer.finish()?;
        let mut actual = Vec::new();
        plan.data.reader()?.read_to_end(&mut actual)?;
        assert_eq!(actual, expected);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
                + ctx.diagnostics()["temporary_path_reserved_bytes"]
                    .as_u64()
                    .unwrap()
        );
        drop(plan);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }
}
