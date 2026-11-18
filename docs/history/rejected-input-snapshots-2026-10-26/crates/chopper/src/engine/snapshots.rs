//! Explicit source-bound parsed-input experiments. No automatic cache lookup.
use super::{records::Records, *};
use std::{
    io::Write,
    path::{Path, PathBuf},
};
mod ipc;
mod rows;
#[cfg(test)]
mod tests;

const MAX_COLUMNS: usize = 1024;
const MAX_BATCH_ROWS: usize = 1024;
const TARGET_BATCH_BYTES: usize = 1024 * 1024;
const MAX_BATCHES: usize = 8192;
const MAX_MANIFEST: usize = 8192;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Format {
    CompactRowsV1,
    ArrowIpcV1,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    version: u32,
    format: Format,
    source_blake3: String,
    settings_blake3: String,
    artifact_blake3: String,
    logical_digest: String,
    source_bytes: u64,
    artifact_bytes: u64,
    records: u64,
    data_rows: u64,
    columns: usize,
    headers: bool,
    maximum_record_bytes: usize,
}
// Pinned serde/Rust construction derivation: R10 owner-derivation.md.
// Sum fixed grammar/expectations, including mutually exclusive alternatives.
const MANIFEST_ERROR_FIXED: usize = concat!(
    "version format source_blake3 settings_blake3 artifact_blake3 logical_digest ",
    "source_bytes artifact_bytes records data_rows columns headers maximum_record_bytes ",
    "compact_rows_v1 arrow_ipc_v1 ",
    "invalid type: , expected invalid value: , expected invalid length , expected ",
    "unknown variant ``, expected unknown field ``, expected missing field ``duplicate field ``",
    "one of , or struct Manifest enum Format field identifier variant identifier ",
    "u32 u64 usize a boolean a string unit variant boolean ``integer ``floating point ``",
    "null sequence map string byte array unit value Option value newtype struct enum ",
    "unit variant newtype variant tuple variant struct variant"
)
.len()
    + 15 * 4
    + 20
    + 1
    + 24
    + 2;
const MANIFEST_ERROR_TEXT: usize = 6 * MAX_MANIFEST + MANIFEST_ERROR_FIXED;
// Disjoint enum payloads + discriminant + line/column; includes layout padding.
const MANIFEST_ERROR_CARRIER: usize =
    std::mem::size_of::<(Box<str>, std::io::Error, usize, usize, usize)>();
// fix_position temporarily owns the moved-from and replacement boxes. Later,
// deserialize_struct retains ret while constructing an end_map/end_seq error.
// These phases do not overlap; scalar/String/unit-enum fields add no recursive
// struct visitor. Each phase has at most two boxes and one owned message.
const MANIFEST_DECODE_ERROR_CARRIERS: usize = 2 * MANIFEST_ERROR_CARRIER;
const MANIFEST_DECODE_BYTES: usize = MAX_MANIFEST + 1
    + 3 * MAX_MANIFEST // scratch old/new requests
    + MAX_MANIFEST // four retained decoded Strings
    + 3 * MANIFEST_ERROR_TEXT // error String growth or boxed shrink overlap
    + MANIFEST_DECODE_ERROR_CARRIERS;
const MANIFEST_ENCODE_BYTES: usize = MAX_MANIFEST + MANIFEST_ERROR_CARRIER;

struct AdmittedManifest {
    value: Manifest,
    _grant: Reservation,
}
impl std::ops::Deref for AdmittedManifest {
    type Target = Manifest;
    fn deref(&self) -> &Manifest {
        &self.value
    }
}
impl Manifest {
    fn string_capacity(&self) -> usize {
        self.source_blake3.capacity()
            + self.settings_blake3.capacity()
            + self.artifact_blake3.capacity()
            + self.logical_digest.capacity()
    }
}
struct ManifestBytes {
    value: Vec<u8>,
    _grant: Reservation,
}
impl Write for ManifestBytes {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > MAX_MANIFEST - self.value.len() {
            return Err(std::io::ErrorKind::WriteZero.into());
        }
        self.value.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
fn encode_manifest(manifest: &Manifest, ctx: &Context) -> Result<ManifestBytes> {
    let mut grant = Reservation::new(ctx);
    grant.resize(MANIFEST_ENCODE_BYTES)?;
    let mut value = Vec::new();
    value.try_reserve_exact(MAX_MANIFEST)?;
    ensure!(
        value.capacity() == MAX_MANIFEST,
        "snapshot manifest output capacity changed"
    );
    let mut output = ManifestBytes {
        value,
        _grant: grant,
    };
    if let Err(error) = serde_json::to_writer(&mut output, manifest) {
        // Includes the serde IO carrier, destroyed before the output grant.
        drop(error);
        anyhow::bail!("snapshot manifest encoding exceeded its fixed bound or failed");
    }
    Ok(output)
}
fn decode_manifest(mut reader: impl Read, ctx: &Context) -> Result<AdmittedManifest> {
    let mut grant = Reservation::new(ctx);
    grant.resize(MANIFEST_DECODE_BYTES)?;
    let mut bytes = Vec::new();
    bytes.try_reserve_exact(MAX_MANIFEST + 1)?;
    ensure!(
        bytes.capacity() == MAX_MANIFEST + 1,
        "snapshot manifest input capacity changed"
    );
    bytes.resize(MAX_MANIFEST + 1, 0);
    let mut length = 0;
    while length < bytes.len() {
        match reader.read(&mut bytes[length..]) {
            Ok(0) => break,
            Ok(n) => length += n,
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
    ensure!(
        length <= MAX_MANIFEST,
        "snapshot manifest grew beyond its bound"
    );
    let value = match serde_json::from_slice::<Manifest>(&bytes[..length]) {
        Ok(value) => value,
        Err(error) => {
            // Never return or format attacker-sized serde error text after grant release.
            drop(error);
            anyhow::bail!("invalid parsed-input snapshot manifest JSON or field type");
        }
    };
    drop(bytes);
    grant.resize(value.string_capacity())?;
    Ok(AdmittedManifest {
        value,
        _grant: grant,
    })
}
#[derive(Serialize)]
pub struct Created {
    pub format: Format,
    pub records: u64,
    pub data_rows: u64,
    pub columns: usize,
    pub source_bytes: u64,
    pub artifact_bytes: u64,
    pub peak_snapshot_bytes: u64,
    pub diagnostics: Diagnostics,
}
struct OwnedDirectory {
    path: AdmittedPath,
    armed: bool,
}
impl OwnedDirectory {
    fn cleanup(&mut self) -> std::io::Result<()> {
        // An ordinary rollback gets exactly one explicit attempt. A denied
        // deletion remains a known caller-supplied orphan, never a success.
        self.armed = false;
        #[cfg(test)]
        tests::lifecycle::before_cleanup(&self.path.value)?;
        std::fs::remove_dir_all(&self.path.value)
    }
    fn report(&self, error: &std::io::Error) {
        // Like storage::JobDirectory, retain the original admitted path through
        // reporting; logging/platform deletion internals are not working memory.
        // Ignore stderr failures so the unwind fallback cannot panic on them.
        let _ = writeln!(
            std::io::stderr().lock(),
            "chopper: snapshot cleanup failed for {}: {error}",
            self.path.value.display()
        );
    }
}
impl Drop for OwnedDirectory {
    fn drop(&mut self) {
        if self.armed {
            if let Err(error) = self.cleanup() {
                self.report(&error);
            }
        }
    }
}

// Keep payloads before their grants, including on early return/unwind.
struct AdmittedPath {
    value: PathBuf,
    _grant: Reservation,
}
impl AdmittedPath {
    fn new(parent: &Path, member: Option<&str>, ctx: &Context) -> Result<Self> {
        let separator = usize::from(
            member.is_some()
                && !parent.as_os_str().is_empty()
                && !parent
                    .as_os_str()
                    .as_encoded_bytes()
                    .last()
                    .is_some_and(|b| std::path::is_separator(*b as char)),
        );
        let length = parent
            .as_os_str()
            .len()
            .checked_add(separator)
            .and_then(|n| n.checked_add(member.map_or(0, str::len)))
            .context("snapshot path size overflow")?;
        let mut grant = Reservation::new(ctx);
        grant.resize(length)?;
        let mut value = PathBuf::new();
        value.try_reserve_exact(length)?;
        grant.resize(value.capacity())?;
        value.push(parent);
        if let Some(member) = member {
            value.push(member);
        }
        ensure!(
            value.capacity() as u64 == grant.bytes(),
            "snapshot path exceeded admission"
        );
        Ok(Self {
            value,
            _grant: grant,
        })
    }
}

struct FrozenJob {
    value: Job,
    _grant: Reservation,
}
fn visit_path_text(path: &Path, mut visit: impl FnMut(&str)) {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        let mut encoded = [0; 4];
        for scalar in char::decode_utf16(path.as_os_str().encode_wide()) {
            visit(
                scalar
                    .unwrap_or(char::REPLACEMENT_CHARACTER)
                    .encode_utf8(&mut encoded),
            );
        }
    }
    #[cfg(not(windows))]
    for chunk in path.as_os_str().as_encoded_bytes().utf8_chunks() {
        visit(chunk.valid());
        if !chunk.invalid().is_empty() {
            visit("\u{fffd}");
        }
    }
}
impl FrozenJob {
    fn new(job: &Job, path: &Path, ctx: &Context) -> Result<Self> {
        // The pinned derived Clone requests at most each source Vec/String's
        // capacity. The old input and replacement coexist during assignment.
        let original = job_owner::capacity(job)?;
        let mut grant = Reservation::new(ctx);
        grant.resize(original)?;
        let mut value = job.clone();
        grant.resize(job_owner::capacity(&value)?)?;
        // Cow may own a lossy UTF-8 replacement. Count its exact encoded size
        // without constructing it, then build directly into one admitted String.
        let mut length = Some(0usize);
        visit_path_text(path, |text| {
            length = length.and_then(|n| n.checked_add(text.len()))
        });
        let length = length.context("snapshot input path size overflow")?;
        let retained = job_owner::capacity(&value)?;
        grant.resize(
            retained
                .checked_add(length)
                .context("snapshot job size overflow")?,
        )?;
        let mut input = String::new();
        input.try_reserve_exact(length)?;
        grant.resize(
            retained
                .checked_add(input.capacity())
                .context("snapshot job size overflow")?,
        )?;
        visit_path_text(path, |text| input.push_str(text));
        value.input = input;
        grant.resize(job_owner::capacity(&value)?)?;
        Ok(Self {
            value,
            _grant: grant,
        })
    }
}
fn clone_parser_settings(
    job: &Job,
    grant: &mut Reservation,
) -> Result<chopper_core::config::CsvSettings> {
    let bytes = job
        .input_csv
        .encoding
        .len()
        .checked_add(job.input_csv.line_ending.len())
        .context("snapshot parser settings size overflow")?;
    grant.resize(bytes)?;
    let settings = job.input_csv.clone();
    ensure!(
        settings.encoding.capacity() + settings.line_ending.capacity() == bytes,
        "snapshot parser settings capacity changed"
    );
    Ok(settings)
}

struct LimitedWriter {
    file: File,
    bytes: u64,
    limit: u64,
}
impl Write for LimitedWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() as u64 > self.limit.saturating_sub(self.bytes) {
            return Err(std::io::Error::other(
                "parsed-input snapshot disk budget exhausted",
            ));
        }
        let written = self.file.write(bytes)?;
        self.bytes += written as u64;
        Ok(written)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.file.flush()
    }
}
fn hash_file(path: &Path, ctx: &Context) -> Result<(blake3::Hash, u64)> {
    copy_and_hash_file(path, None, ctx)
}
fn copy_and_hash_file(
    path: &Path,
    mut destination: Option<LimitedWriter>,
    ctx: &Context,
) -> Result<(blake3::Hash, u64)> {
    let mut grant = Reservation::new(ctx);
    grant.resize(65536 + std::mem::size_of::<blake3::Hasher>())?;
    let mut buffer = vec![0; 65536];
    let mut file = File::open(path)?;
    let expected = file.metadata()?.len();
    let mut hash = blake3::Hasher::new();
    let mut count = 0u64;
    loop {
        ctx.check()?;
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hash.update(&buffer[..read]);
        if let Some(output) = destination.as_mut() {
            output.write_all(&buffer[..read])?;
        }
        count = count
            .checked_add(read as u64)
            .context("input byte count overflow")?;
        #[cfg(test)]
        tests::lifecycle::hash_block(path, destination.is_some(), count, hash.clone().finalize());
    }
    ensure!(
        count == expected && file.metadata()?.len() == expected,
        "input changed while hashing parsed-input binding"
    );
    Ok((hash.finalize(), count))
}
fn settings_hash(job: &Job) -> Result<String> {
    struct HashWriter(blake3::Hasher);
    impl Write for HashWriter {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            self.0.update(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = HashWriter(blake3::Hasher::new());
    serde_json::to_writer(&mut writer, &(&job.input_csv, &job.zip_member))?;
    Ok(writer.0.finalize().to_hex().to_string())
}

/// Create one fresh explicitly owned artifact. Existing paths are never reused
/// or removed. The disk ceiling includes the frozen source, data file and
/// manifest staging at their peak overlap.
pub fn create(
    job: &Job,
    directory: &Path,
    format: Format,
    disk_limit: u64,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Created> {
    job.validate()?;
    let ctx = Context::with_memory_pool(&job.resources, cancel, notify, pool)?;
    let directory_path = AdmittedPath::new(directory, None, &ctx)?;
    std::fs::create_dir(directory).context("create fresh parsed-input snapshot directory")?;
    let mut owner = OwnedDirectory {
        path: directory_path,
        armed: true,
    };
    // All handles and construction owners die before explicit rollback. The
    // directory's admitted path remains live until the attempt and reporting.
    let result = (|| {
        let frozen_path = AdmittedPath::new(directory, Some("source.partial"), &ctx)?;
        let frozen = LimitedWriter {
            file: std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&frozen_path.value)?,
            bytes: 0,
            limit: disk_limit,
        };
        let (source_hash, source_bytes) =
            copy_and_hash_file(Path::new(&job.input), Some(frozen), &ctx)?;
        #[cfg(test)]
        tests::lifecycle::checkpoint(tests::lifecycle::Stage::Frozen);
        let frozen_job = FrozenJob::new(job, &frozen_path.value, &ctx)?;
        let data_path = AdmittedPath::new(directory, Some("records.bin"), &ctx)?;
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&data_path.value)?;
        let limited = LimitedWriter {
            file,
            bytes: 0,
            limit: disk_limit.saturating_sub(source_bytes),
        };
        let mut manifest_grant = Reservation::new(&ctx);
        manifest_grant.resize(4 * 64)?;
        let mut manifest = with_input(&frozen_job.value, Reservation::new(&ctx), |source| {
            let mut input = Reservation::new(&ctx);
            input.resize(64 * 1024 + std::mem::size_of::<DecodeReader<Box<dyn Read>>>())?;
            let mut parser_grant = Reservation::new(&ctx);
            let mut settings_grant = Reservation::new(&ctx);
            let parser_settings = clone_parser_settings(job, &mut settings_grant)?;
            let mut parser = Parser::new(
                BufReader::with_capacity(
                    64 * 1024,
                    DecodeReader::new(source, &job.input_csv.encoding)?,
                ),
                parser_settings,
                ctx.max_record,
            );
            let mut record = chopper_core::csv::CompactRecord::default();
            let mut digest = crate::digest::LogicalDigest::reserved(Reservation::new(&ctx))?;
            let mut writer = None;
            let mut output = Some(limited);
            let mut width = None;
            let mut count = 0u64;
            while parser
                .next_compact_record_into_reserved(&mut record, &mut |n| parser_grant.resize(n))?
            {
                ctx.check()?;
                let columns = *width.get_or_insert(record.len());
                ensure!(
                    columns > 0 && columns <= MAX_COLUMNS && record.len() == columns,
                    "snapshot requires a consistent width of 1–{MAX_COLUMNS} text columns"
                );
                ensure!(
                    record
                        .payload_bytes()
                        .checked_add(columns * 32)
                        .is_some_and(|n| n <= ctx.max_record),
                    "decoded snapshot record exceeds its working limit"
                );
                if writer.is_none() {
                    writer = Some(Encoder::new(format, output.take().unwrap(), columns, &ctx)?);
                }
                writer.as_mut().unwrap().row(&record)?;
                #[cfg(test)]
                tests::lifecycle::checkpoint(tests::lifecycle::Stage::Row);
                if count != 0 || !job.input_csv.headers {
                    digest.compact_record(&record);
                }
                count = count
                    .checked_add(1)
                    .context("snapshot record count overflow")?;
                if count.is_multiple_of(65536) {
                    ctx.event("Creating parsed input snapshot", count)?;
                }
            }
            let writer = match writer {
                Some(writer) => writer,
                None => Encoder::new(format, output.take().unwrap(), 0, &ctx)?,
            };
            #[cfg(test)]
            tests::lifecycle::checkpoint(tests::lifecycle::Stage::BeforeFinish);
            ctx.check()?;
            let bytes = writer.finish()?;
            Ok(Manifest {
                version: 1,
                format,
                source_blake3: source_hash.to_hex().to_string(),
                settings_blake3: settings_hash(job)?,
                artifact_blake3: String::new(),
                logical_digest: digest.finalize().to_hex().to_string(),
                source_bytes,
                artifact_bytes: bytes,
                records: count,
                data_rows: count.saturating_sub(u64::from(job.input_csv.headers)),
                columns: width.unwrap_or(0),
                headers: job.input_csv.headers,
                maximum_record_bytes: ctx.max_record,
            })
        })?;
        ensure!(
            hash_file(Path::new(&job.input), &ctx)?.0 == source_hash,
            "source changed while building parsed-input snapshot"
        );
        drop(frozen_job);
        std::fs::remove_file(&frozen_path.value)?;
        drop(frozen_path);
        let (hash, bytes) = hash_file(&data_path.value, &ctx)?;
        ensure!(
            bytes == manifest.artifact_bytes,
            "snapshot writer byte count changed"
        );
        manifest.artifact_blake3 = hash.to_hex().to_string();
        ensure!(
            manifest.string_capacity() == 4 * 64,
            "snapshot digest capacity changed"
        );
        let metadata = encode_manifest(&manifest, &ctx)?;
        #[cfg(test)]
        tests::preserve_created_manifest(&metadata.value)?;
        let total = bytes
            .checked_add(metadata.value.len() as u64)
            .context("snapshot byte count overflow")?;
        ensure!(
            total <= disk_limit,
            "parsed-input snapshot disk budget exhausted including manifest"
        );
        let partial = AdmittedPath::new(directory, Some("manifest.partial"), &ctx)?;
        std::fs::write(&partial.value, &metadata.value)?;
        #[cfg(test)]
        tests::lifecycle::checkpoint(tests::lifecycle::Stage::ManifestPartial);
        let completion = AdmittedPath::new(directory, Some("manifest.json"), &ctx)?;
        let diagnostics = commit_manifest(&ctx, &partial.value, &completion.value)?;
        Ok(Created {
            format,
            records: manifest.records,
            data_rows: manifest.data_rows,
            columns: manifest.columns,
            source_bytes,
            artifact_bytes: bytes,
            peak_snapshot_bytes: total.max(source_bytes + bytes),
            diagnostics,
        })
    })();
    match result {
        Ok(created) => {
            owner.armed = false;
            Ok(created)
        }
        Err(error) => {
            if let Err(cleanup) = owner.cleanup() {
                owner.report(&cleanup);
                drop(cleanup);
                return Err(error.context(
                    "parsed-input snapshot rollback deletion failed; caller cleanup required at the supplied snapshot directory",
                ));
            }
            Err(error)
        }
    }
}

// The caller retains its fresh artifact-directory guard until this succeeds.
fn commit_manifest(ctx: &Context, partial: &Path, completion: &Path) -> Result<Diagnostics> {
    let diagnostics = Diagnostics::context(ctx)?;
    ctx.check()?;
    std::fs::rename(partial, completion)?;
    Ok(diagnostics)
}

enum Encoder {
    Rows(rows::Writer),
    Ipc(Box<ipc::Writer>, Reservation),
}
impl Encoder {
    fn new(format: Format, writer: LimitedWriter, columns: usize, ctx: &Context) -> Result<Self> {
        Ok(match format {
            Format::CompactRowsV1 => Self::Rows(rows::Writer::new(writer, ctx)?),
            Format::ArrowIpcV1 => {
                let mut grant = Reservation::new(ctx);
                grant.resize(std::mem::size_of::<ipc::Writer>())?;
                Self::Ipc(Box::new(ipc::Writer::new(writer, columns, ctx)?), grant)
            }
        })
    }
    fn row(&mut self, row: &chopper_core::csv::CompactRecord) -> Result<()> {
        match self {
            Self::Rows(writer) => writer.row(row),
            Self::Ipc(writer, _) => writer.row(row),
        }
    }
    fn finish(self) -> Result<u64> {
        match self {
            Self::Rows(writer) => writer.finish(),
            Self::Ipc(writer, _grant) => writer.finish(),
        }
    }
}

fn binding(directory: &Path, job: &Job, ctx: &Context) -> Result<AdmittedManifest> {
    let path = AdmittedPath::new(directory, Some("manifest.json"), ctx)?;
    let file = File::open(&path.value).context("open completed parsed-input snapshot manifest")?;
    ensure!(
        file.metadata()?.len() <= MAX_MANIFEST as u64,
        "snapshot manifest exceeds its fixed bound"
    );
    let manifest = decode_manifest(file, ctx)?;
    ensure!(
        manifest.version == 1
            && manifest.columns <= MAX_COLUMNS
            && manifest.headers == job.input_csv.headers,
        "unsupported snapshot version or header/column convention"
    );
    ensure!(
        manifest.maximum_record_bytes <= ctx.max_record,
        "snapshot was created under a larger record working limit; rebuild it for this limit"
    );
    ensure!(
        manifest
            .records
            .checked_sub(u64::from(manifest.headers && manifest.records > 0))
            == Some(manifest.data_rows),
        "invalid snapshot record counts"
    );
    for text in [
        &manifest.source_blake3,
        &manifest.settings_blake3,
        &manifest.artifact_blake3,
        &manifest.logical_digest,
    ] {
        let _: blake3::Hash = text.parse().context("invalid snapshot digest")?;
    }
    let mut settings_grant = Reservation::new(ctx);
    settings_grant.resize(64)?;
    let settings = settings_hash(job)?;
    ensure!(
        settings.capacity() == 64,
        "snapshot settings digest capacity changed"
    );
    ensure!(
        manifest.settings_blake3 == settings,
        "parsed-input snapshot CSV settings/member changed"
    );
    let (source_hash, source_bytes) = hash_file(Path::new(&job.input), ctx)?;
    ensure!(
        source_bytes == manifest.source_bytes
            && source_hash.to_hex().as_str() == manifest.source_blake3,
        "parsed-input snapshot source changed"
    );
    let artifact_path = AdmittedPath::new(directory, Some("records.bin"), ctx)?;
    let (artifact_hash, artifact_bytes) = hash_file(&artifact_path.value, ctx)?;
    ensure!(
        artifact_bytes == manifest.artifact_bytes
            && artifact_hash.to_hex().as_str() == manifest.artifact_blake3,
        "parsed-input snapshot artifact changed or is incomplete"
    );
    Ok(manifest)
}

/// Copy and authenticate the exact private object consumed by the decoder.
/// The caller's completed cache is never owned or removed by this job.
fn authenticated_artifact(
    directory: &Path,
    manifest: &Manifest,
    ctx: &Context,
) -> Result<crate::storage::DiskFile> {
    let mut scratch_grant = Reservation::new(ctx);
    scratch_grant.resize(65536 + std::mem::size_of::<blake3::Hasher>())?;
    let mut scratch = Vec::new();
    scratch.try_reserve_exact(65536)?;
    scratch_grant.resize(scratch.capacity() + std::mem::size_of::<blake3::Hasher>())?;
    scratch.resize(65536, 0);
    let mut path_grant = Reservation::new(ctx);
    let path_bytes = directory
        .as_os_str()
        .len()
        .checked_add(1 + "records.bin".len())
        .context("snapshot path size overflow")?;
    path_grant.resize(path_bytes)?;
    let mut path = PathBuf::new();
    path.try_reserve_exact(path_bytes)?;
    path_grant.resize(path.capacity())?;
    path.push(directory);
    path.push("records.bin");
    ensure!(
        path.capacity() as u64 == path_grant.bytes(),
        "snapshot path exceeded admitted capacity"
    );
    let source = File::open(&path)?;
    drop(path);
    drop(path_grant);
    ensure!(
        source.metadata()?.len() == manifest.artifact_bytes,
        "parsed-input snapshot artifact changed or is incomplete"
    );
    let mut source = ctx.artifact_reader(source);
    #[cfg(test)]
    tests::before_private_file();
    let mut private = ctx.file()?;
    let mut hash = blake3::Hasher::new();
    let mut count = 0u64;
    loop {
        ctx.check()?;
        let read = source.read(&mut scratch)?;
        if read == 0 {
            break;
        }
        count = count
            .checked_add(read as u64)
            .context("snapshot copy length overflow")?;
        ensure!(
            count <= manifest.artifact_bytes,
            "parsed-input snapshot artifact changed or is incomplete"
        );
        private.write_all(&scratch[..read])?;
        hash.update(&scratch[..read]);
        #[cfg(test)]
        tests::copy_block(count);
    }
    private.flush()?;
    ensure!(
        count == manifest.artifact_bytes
            && hash.finalize().to_hex().as_str() == manifest.artifact_blake3,
        "parsed-input snapshot artifact changed or is incomplete"
    );
    ctx.check()?;
    Ok(private)
}

/// Prepare using the ordinary consumer and output plan after validating both
/// source and artifact. Decode only a job-owned, authenticated private copy:
/// mutation before private authentication rejects, while later caller-cache
/// replacement or writes cannot change the frozen records being consumed.
/// The resulting prepared CSV snapshot owns no caller cache file. Source
/// identity validation retains its existing separate binding contract.
pub fn prepare(
    job: Job,
    directory: &Path,
    cancel: Arc<AtomicBool>,
    notify: Notify,
    pool: Arc<crate::resources::MemoryPool>,
) -> Result<Prepared> {
    prepare_using(
        job,
        cancel,
        notify,
        pool,
        |job, ctx, partitions, balanced, streaming| {
            ctx.event("Validating parsed input snapshot", 0)?;
            let manifest = binding(directory, job, ctx)?;
            #[cfg(test)]
            tests::after_binding();
            let private = authenticated_artifact(directory, &manifest, ctx)?;
            #[cfg(test)]
            tests::after_authentication();
            ctx.check()?;
            let input = private.unbuffered_reader()?;
            let data = match manifest.format {
                Format::CompactRowsV1 => Decoder::Rows(rows::Reader::new(input, &manifest, ctx)?),
                Format::ArrowIpcV1 => Decoder::Ipc(ipc::Reader::new(input, &manifest, ctx)?),
            };
            let reader = Reader {
                data,
                _artifact: private,
                record: 0,
                maximum: ctx.max_record,
            };
            let result = ingest_records(
                reader,
                job,
                ctx,
                Reservation::new(ctx),
                partitions,
                balanced,
                streaming,
            )?;
            ensure!(
                result.analysis.rows == manifest.data_rows
                    && result.analysis.columns == manifest.columns
                    && result.analysis.logical_digest == manifest.logical_digest,
                "parsed-input snapshot logical records do not match its binding"
            );
            Ok(result)
        },
    )
}

enum Decoder {
    Rows(rows::Reader),
    Ipc(ipc::Reader),
}
#[derive(Clone)]
enum Fields<'a> {
    Rows(rows::Fields<'a>),
    Ipc(ipc::Fields<'a>),
}
impl<'a> Iterator for Fields<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<Self::Item> {
        match self {
            Self::Rows(fields) => fields.next(),
            Self::Ipc(fields) => fields.next(),
        }
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = self.len();
        (n, Some(n))
    }
}
impl ExactSizeIterator for Fields<'_> {
    fn len(&self) -> usize {
        match self {
            Self::Rows(fields) => fields.len(),
            Self::Ipc(fields) => fields.len(),
        }
    }
}
impl Decoder {
    fn next_fields(&mut self) -> Result<Option<Fields<'_>>> {
        match self {
            Self::Rows(reader) => Ok(reader.next_fields()?.map(Fields::Rows)),
            Self::Ipc(reader) => Ok(reader.next_fields()?.map(Fields::Ipc)),
        }
    }
}
struct Reader {
    data: Decoder,
    // Declared after the decoder so its handle closes before unlink/release.
    _artifact: crate::storage::DiskFile,
    record: u64,
    maximum: usize,
}
impl Records for Reader {
    fn record_number(&self) -> u64 {
        self.record
    }
    fn scratch_capacity(&self) -> usize {
        0
    }
    fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        #[cfg(test)]
        tests::consuming(self.record);
        let Some(next) = self.data.next_fields()? else {
            fields.clear();
            reserve(fields.capacity() * std::mem::size_of::<String>())?;
            return Ok(false);
        };
        chopper_core::csv::copy_text_fields_into_reserved(next, fields, self.maximum, reserve)?;
        self.record = self
            .record
            .checked_add(1)
            .context("snapshot record count overflow")?;
        Ok(true)
    }
    fn next_compact_record_into_reserved(
        &mut self,
        fields: &mut chopper_core::csv::CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        #[cfg(test)]
        tests::consuming(self.record);
        let Some(next) = self.data.next_fields()? else {
            fields.clear();
            reserve(fields.capacity())?;
            return Ok(false);
        };
        fields.set_text_fields_reserved(next, self.maximum, reserve)?;
        self.record = self
            .record
            .checked_add(1)
            .context("snapshot record count overflow")?;
        Ok(true)
    }
}
