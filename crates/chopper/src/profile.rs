//! Full-file input profiling, independent of output preparation.
use crate::{
    csv_intake::Intake,
    engine,
    storage::{Notify, Reservation, Workspace},
};
use anyhow::{ensure, Context as _, Result};
#[cfg(test)]
use chopper_core::csv::DecodeReader;
use chopper_core::{resolve_column, Job, Operation, Shuffle};
use serde::Serialize;
use std::{
    io::{self, Read},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Instant, SystemTime},
};
#[cfg(all(
    test,
    feature = "experimental-parallel-profile",
    not(target_os = "wasi")
))]
mod parallel_tests;
mod records;
mod writers;
pub use writers::WriterEstimate;

/// Experimental scan diagnostics, excluded from the stable profile JSON.
#[derive(Clone, Copy, Default, Serialize)]
pub struct ProfileExecution {
    pub hash_workers: usize,
    pub hash_batches: u64,
    pub hashed_rows: u64,
    pub serial_retry: bool,
    pub scan_peak_reserved_bytes: u64,
}

#[derive(PartialEq)]
struct Key {
    path: PathBuf,
    length: u64,
    modified: SystemTime,
    created: Option<SystemTime>,
    input_options: String,
    memory_mb: u64,
    #[cfg(unix)]
    identity: (u64, u64, i64, i64),
}
impl Key {
    fn binding(&self) -> Option<[u8; 32]> {
        if cfg!(windows) {
            return None;
        }
        let mut hash = blake3::Hasher::new();
        // Virtual stat timestamps do not identify a File across new WASI
        // workers. The browser session verifies the selection before forwarding
        // observations; the reactor independently checks size and parser settings.
        #[cfg(target_os = "wasi")]
        serde_json::to_writer(&mut hash, &(&self.path, self.length, &self.input_options)).ok()?;
        #[cfg(not(target_os = "wasi"))]
        serde_json::to_writer(
            &mut hash,
            &(
                &self.path,
                self.length,
                self.modified,
                self.created,
                &self.input_options,
            ),
        )
        .ok()?;
        #[cfg(unix)]
        serde_json::to_writer(&mut hash, &self.identity).ok()?;
        Some(*hash.finalize().as_bytes())
    }

    fn read(job: &Job, memory_mb: u64) -> Result<Self> {
        #[cfg(not(target_os = "wasi"))]
        let path = std::fs::canonicalize(&job.input)?;
        // Browser inputs have virtual absolute paths; the adapter explicitly
        // clears this cache whenever the selected File object changes.
        #[cfg(target_os = "wasi")]
        let path = PathBuf::from(&job.input);
        let metadata = std::fs::metadata(&path)?;
        ensure!(metadata.is_file(), "input must be a regular file");
        Ok(Self {
            path,
            length: metadata.len(),
            modified: metadata.modified()?,
            created: metadata.created().ok(),
            input_options: if job.input_dialect.is_default() {
                serde_json::to_string(&(
                    &job.input_csv,
                    &job.zip_member,
                    job.resources.max_record_bytes,
                ))?
            } else {
                serde_json::to_string(&(
                    &job.input_csv,
                    &job.zip_member,
                    job.resources.max_record_bytes,
                    &job.input_dialect,
                ))?
            },
            memory_mb,
            #[cfg(unix)]
            identity: {
                use std::os::unix::fs::MetadataExt;
                (
                    metadata.dev(),
                    metadata.ino(),
                    metadata.ctime(),
                    metadata.ctime_nsec(),
                )
            },
        })
    }
}
pub(crate) fn auto_binding(job: &Job) -> Option<[u8; 32]> {
    Key::read(job, 0).ok()?.binding()
}

/// HyperLogLog with 1024 registers: about 3.25% relative standard error.
/// Only cardinality estimates use hashes; output equality never does.
/// Algorithm: https://dmtcs.episciences.org/3545/pdf (64-bit hashes here).
struct Cardinality {
    registers: [u8; 1024],
}
impl Default for Cardinality {
    fn default() -> Self {
        Self {
            registers: [0; 1024],
        }
    }
}
impl Cardinality {
    fn add(&mut self, hash: blake3::Hash) {
        let bits = u64::from_le_bytes(hash.as_bytes()[..8].try_into().unwrap());
        let index = (bits & 1023) as usize;
        let rank = ((bits >> 10).leading_zeros() - 10 + 1) as u8;
        self.registers[index] = self.registers[index].max(rank);
    }
    fn estimate(&self) -> u64 {
        let m = self.registers.len() as f64;
        let raw = (0.7213 / (1.0 + 1.079 / m)) * m * m
            / self
                .registers
                .iter()
                .map(|&r| 2f64.powi(-(r as i32)))
                .sum::<f64>();
        let zeros = self.registers.iter().filter(|&&r| r == 0).count();
        let count = if raw <= 2.5 * m && zeros > 0 {
            m * (m / zeros as f64).ln()
        } else {
            raw
        };
        count.round() as u64
    }
}
// One full internal-node envelope per key covers retained nodes and BTree splits
// for the same <=100-key bound as engine column summaries. Strings are separate.
const FREQUENCY_NODE_BYTES: usize = 16
    * (std::mem::size_of::<String>() + std::mem::size_of::<u64>() + std::mem::size_of::<usize>())
    + 4 * std::mem::size_of::<usize>();

#[derive(Clone, Serialize)]
pub struct ColumnProfile {
    pub column: usize,
    pub values: Vec<String>,
    #[serde(skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub frequencies: std::collections::BTreeMap<String, u64>,
    pub truncated: bool,
    pub distinct: u64,
    pub distinct_exact: bool,
}
#[derive(Clone, Serialize)]
pub struct StageProfile {
    pub operation: usize,
    pub strategy: String,
    pub input_distinct_keys: Option<u64>,
    pub distinct_exact: bool,
}
#[derive(Serialize)]
pub struct InputProfile {
    pub rows: u64,
    pub columns: usize,
    pub header: Option<Vec<String>>,
    pub preview: Vec<Vec<String>>,
    pub column_values: Vec<ColumnProfile>,
    pub stages: Vec<StageProfile>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub writer_estimate: Option<WriterEstimate>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_observations: Option<engine::AutoObservations>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suggested_run_memory_mb: Option<u64>,
    pub cache_hit: bool,
    pub seconds: f64,
    pub accuracy: String,
    #[serde(skip)]
    header_buffers: Reservation,
    #[serde(skip)]
    preview_buffers: Reservation,
    #[serde(skip)]
    metadata_buffers: Reservation,
    #[serde(skip)]
    execution: ProfileExecution,
}
impl InputProfile {
    pub fn execution(&self) -> ProfileExecution {
        self.execution
    }
    /// Copy retained rows against the same workspace as the cached profile.
    /// Includes summaries, sorted values, stage strings and accuracy text.
    pub fn try_clone(&self) -> Result<Self> {
        let mut header_buffers = self.header_buffers.sibling();
        let header = self
            .header
            .as_ref()
            .map(|fields| clone_fields_reserved(fields, &mut header_buffers))
            .transpose()?;
        let mut preview_buffers = self.preview_buffers.sibling();
        let mut preview = Vec::new();
        reserve_preview(&mut preview, self.preview.len(), &mut preview_buffers)?;
        for fields in &self.preview {
            preview.push(clone_fields_reserved(fields, &mut preview_buffers)?);
        }
        let mut metadata_buffers = self.metadata_buffers.sibling();
        let mut column_values = Vec::new();
        metadata_buffers.reserve_vec(&mut column_values, self.column_values.len())?;
        for summary in &self.column_values {
            let mut values = Vec::new();
            metadata_buffers.reserve_vec(&mut values, summary.values.len())?;
            for value in &summary.values {
                values.push(metadata_buffers.copy_string(value)?);
            }
            let mut frequencies = std::collections::BTreeMap::new();
            for (value, count) in &summary.frequencies {
                metadata_buffers
                    .resize(metadata_buffers.bytes() as usize + FREQUENCY_NODE_BYTES)?;
                frequencies.insert(metadata_buffers.copy_string(value)?, *count);
            }
            column_values.push(ColumnProfile {
                column: summary.column,
                values,
                frequencies,
                truncated: summary.truncated,
                distinct: summary.distinct,
                distinct_exact: summary.distinct_exact,
            });
        }
        let mut stages = Vec::new();
        metadata_buffers.reserve_vec(&mut stages, self.stages.len())?;
        for stage in &self.stages {
            stages.push(StageProfile {
                operation: stage.operation,
                strategy: metadata_buffers.copy_string(&stage.strategy)?,
                input_distinct_keys: stage.input_distinct_keys,
                distinct_exact: stage.distinct_exact,
            });
        }
        let accuracy = metadata_buffers.copy_string(&self.accuracy)?;
        Ok(Self {
            rows: self.rows,
            columns: self.columns,
            header,
            preview,
            column_values,
            stages,
            writer_estimate: self.writer_estimate,
            auto_observations: self.auto_observations,
            suggested_run_memory_mb: self.suggested_run_memory_mb,
            cache_hit: self.cache_hit,
            seconds: self.seconds,
            accuracy,
            header_buffers,
            preview_buffers,
            metadata_buffers,
            execution: self.execution,
        })
    }
}
// These vectors reserve their final capacity once. Each string takes ownership
// of its byte buffer, so neither descriptor growth nor string boxing adds an
// uncharged replacement allocation. On error the caller discards the copy and
// its reservation together.
fn clone_fields_reserved(fields: &[String], reservation: &mut Reservation) -> Result<Vec<String>> {
    let base = reservation.bytes() as usize;
    let descriptors = fields
        .len()
        .checked_mul(std::mem::size_of::<String>())
        .context("profile descriptor capacity overflow")?;
    reservation.resize(
        base.checked_add(descriptors)
            .context("profile capacity overflow")?,
    )?;
    let mut result = Vec::new();
    result.try_reserve_exact(fields.len())?;
    let mut bytes = base
        .checked_add(result.capacity() * std::mem::size_of::<String>())
        .context("profile capacity overflow")?;
    reservation.resize(bytes)?;
    for field in fields {
        reservation.resize(
            bytes
                .checked_add(field.len())
                .context("profile capacity overflow")?,
        )?;
        let mut copy = String::new();
        copy.try_reserve_exact(field.len())?;
        bytes = bytes
            .checked_add(copy.capacity())
            .context("profile capacity overflow")?;
        reservation.resize(bytes)?;
        copy.push_str(field);
        result.push(copy);
    }
    Ok(result)
}
fn reserve_preview(
    preview: &mut Vec<Vec<String>>,
    capacity: usize,
    reservation: &mut Reservation,
) -> Result<()> {
    debug_assert!(preview.is_empty() && preview.capacity() == 0);
    reservation.resize(
        capacity
            .checked_mul(std::mem::size_of::<Vec<String>>())
            .context("profile preview capacity overflow")?,
    )?;
    preview.try_reserve_exact(capacity)?;
    reservation.resize(preview.capacity() * std::mem::size_of::<Vec<String>>())
}
struct Observations {
    profile: InputProfile,
    combinations: Vec<(Vec<usize>, u64)>,
    partition: Option<engine::auto::PartitionObservation>,
    decoded_field_bytes: u64,
    largest_decoded_row_bytes: u64,
    _combination_buffers: Reservation,
    key_buffers: Reservation,
}
impl Observations {
    fn partition_for(
        &self,
        configured_columns: [u8; 32],
        indices: &[usize],
    ) -> Option<engine::auto::PartitionObservation> {
        if let Some(mut partition) = self
            .partition
            .filter(|p| p.columns == selection_hash(indices))
        {
            partition.columns = configured_columns;
            return Some(partition);
        }
        let [column] = indices else {
            return None;
        };
        let summary = self
            .profile
            .column_values
            .iter()
            .find(|s| s.column == *column && s.distinct_exact)?;
        Some(engine::auto::PartitionObservation {
            columns: configured_columns,
            keys: summary.distinct,
            keys_exact: true,
            largest_key_bucket_rows: summary.frequencies.values().copied().max().unwrap_or(0),
            skew_exact: true,
        })
    }
}

// Cache coverage uses resolved columns, so aliases and permutations can reuse
// the same joint statistics. Run receives a separate binding to the job syntax.
fn selection_hash(indices: &[usize]) -> [u8; 32] {
    let mut hash = blake3::Hasher::new();
    for index in indices {
        hash.update(&index.to_le_bytes());
    }
    *hash.finalize().as_bytes()
}

#[derive(Default)]
pub struct ProfileCache {
    entry: Option<(Key, Observations)>,
    pool: Option<Arc<crate::resources::MemoryPool>>,
}
fn selections(
    job: &Job,
    header: Option<&[String]>,
    width: usize,
    owner: &Reservation,
    bind_formulas: bool,
) -> Result<(Vec<Vec<usize>>, Reservation)> {
    let mut reservation = owner.sibling();
    let mut selections = Vec::new();
    reservation.reserve_vec(&mut selections, job.operations.len())?;
    let expanded = if job.calculated_columns.is_empty() {
        None
    } else if bind_formulas {
        Some(engine::calculation::Plan::prepare(job, header, width, owner.sibling())?.header)
    } else {
        Some(engine::calculation::schema(
            job,
            header,
            width,
            owner.sibling(),
        )?)
    };
    let current_header = expanded.as_deref().or(header);
    let current_width = width + job.calculated_columns.len();
    for operation in &job.operations {
        let columns = match operation {
            Operation::Partition { columns } => columns.as_slice(),
            Operation::Assign { strata, .. } | Operation::AssignProbabilistic { strata, .. } => {
                strata.as_slice()
            }
            _ => &[],
        };
        let mut indices = Vec::new();
        reservation.reserve_vec(&mut indices, columns.len())?;
        for column in columns {
            indices.push(resolve_column(column, current_header, current_width)?);
        }
        // These observations describe source fields. A tuple with a calculated
        // field cannot be estimated by profiling its input members alone.
        if indices.iter().any(|&index| index >= width) {
            indices.clear();
        }
        indices.sort_unstable();
        indices.dedup();
        selections.push(indices);
    }
    Ok((selections, reservation))
}
fn strategy(operation: &Operation, job: &Job) -> &'static str {
    match operation {
        Operation::Partition { .. } if engine::bounded_final_partition_shape(job) => {
            "Bounded final writers (experimental shape; admission still required)"
        }
        Operation::Partition { .. } if job.resources.grouping == chopper_core::Grouping::Sort => {
            "Stable grouping by sorting (forced)"
        }
        Operation::Partition { .. } => {
            "Stable grouping; bounded routing when eligible, sorting fallback"
        }
        Operation::Assign { .. } => "Count groups, then draw exact allocation quotas",
        Operation::AssignProbabilistic { .. } => {
            "Independent seeded allocation; approximate percentages, bounded routing"
        }
        Operation::Interleaved { .. } => {
            "Round-robin routing; exact balance, interleaved membership"
        }
        Operation::Shuffle {
            strategy: Shuffle::FisherYates,
            ..
        } => "Uniform Fisher–Yates v1; each group must fit in memory",
        Operation::Balanced { .. } => "Count groups, then split exact balanced ranges",
        Operation::Shuffle { .. } => "Uniform random-key sort; spill and merge when needed",
    }
}
impl ProfileCache {
    pub fn with_memory_pool(pool: Arc<crate::resources::MemoryPool>) -> Self {
        Self {
            entry: None,
            pool: Some(pool),
        }
    }
    pub fn clear(&mut self) {
        self.entry = None;
    }
    pub fn profile(
        &mut self,
        job: &Job,
        cancel: Arc<AtomicBool>,
        notify: Notify,
    ) -> Result<InputProfile> {
        let started = Instant::now();
        job.validate_for_execution()?;
        ensure!(!cancel.load(Ordering::Relaxed), "cancelled");
        let pool = self
            .pool
            .clone()
            .map(Ok)
            .unwrap_or_else(crate::resources::process_memory)?;
        let memory_mb = pool.resolve_memory(&job.resources)?;
        let key = Key::read(job, memory_mb)?;
        let partition_columns = engine::auto::partition_columns(job);
        let mut cache_hit = false;
        if let Some((old, observations)) = &self.entry {
            // Windows timestamp metadata can remain unchanged across rapid
            // same-size writes. Until a durable source-change token is available,
            // rescan instead of reusing observations on that runtime.
            if !cfg!(windows) && *old == key {
                let p = &observations.profile;
                let (wanted, _selection_buffers) = selections(
                    job,
                    p.header.as_deref(),
                    p.columns,
                    &p.metadata_buffers,
                    false,
                )?;
                cache_hit = partition_columns.is_none_or(|columns| {
                    observations.partition_for(columns, &wanted[0]).is_some()
                }) && wanted.iter().all(|indices| match indices.as_slice() {
                    [] | [_] => true,
                    _ => observations
                        .combinations
                        .iter()
                        .any(|(key, _)| key == indices),
                });
            }
        }
        let mut uncached = None;
        if !cache_hit {
            self.clear();
            let parallel = cfg!(all(
                feature = "experimental-parallel-profile",
                not(target_os = "wasi")
            ));
            let attempt = scan(
                job,
                &cancel,
                &notify,
                &key,
                pool.clone(),
                parallel,
                memory_mb,
            );
            let mut observations = match attempt {
                Err(error)
                    if parallel
                        && error
                            .downcast_ref::<crate::resources::MemoryAdmission>()
                            .is_some()
                        && !cancel.load(Ordering::Relaxed) =>
                {
                    // No batch/partial observations survive the failed attempt.
                    // Reopen rather than resuming a partially consumed CSV record.
                    ensure!(
                        key == Key::read(job, memory_mb)?,
                        "input changed during profiling; retry with a stable source"
                    );
                    let mut serial =
                        scan(job, &cancel, &notify, &key, pool.clone(), false, memory_mb)?;
                    serial.profile.execution.serial_retry = true;
                    serial
                }
                result => result?,
            };
            // Retained key bytes are charged before cache installation. Filesystem
            // canonicalization and JSON construction scratch remain runtime overhead.
            observations
                .key_buffers
                .resize(key.path.capacity() + key.input_options.capacity())?;
            ensure!(!cancel.load(Ordering::Relaxed), "cancelled");
            ensure!(
                key == Key::read(job, memory_mb)?,
                "input changed during profiling; retry with a stable source"
            );
            if cfg!(windows) {
                uncached = Some((key, observations));
            } else {
                self.entry = Some((key, observations));
            }
        }
        ensure!(!cancel.load(Ordering::Relaxed), "cancelled");
        // Do not retain a cache owner that this runtime cannot safely reuse.
        let (key, observations) = uncached.as_ref().or(self.entry.as_ref()).unwrap();
        let mut profile = observations.profile.try_clone()?;
        let (wanted, _selection_buffers) = selections(
            job,
            profile.header.as_deref(),
            profile.columns,
            &profile.metadata_buffers,
            true,
        )?;
        let partition =
            partition_columns.and_then(|columns| observations.partition_for(columns, &wanted[0]));
        // Cached observations have no stages. Returned copies own their stage
        // allocation and text independently of the cache and other responses.
        profile
            .metadata_buffers
            .reserve_vec(&mut profile.stages, job.operations.len())?;
        for (index, (op, indices)) in job.operations.iter().zip(wanted).enumerate() {
            let (distinct, exact) = match indices.as_slice() {
                [] => (None, false),
                [column] => profile
                    .column_values
                    .get(*column)
                    .map_or((None, false), |c| (Some(c.distinct), c.distinct_exact)),
                _ => (
                    observations
                        .combinations
                        .iter()
                        .find(|(key, _)| key == &indices)
                        .map(|(_, value)| *value),
                    false,
                ),
            };
            profile.stages.push(StageProfile {
                operation: index + 1,
                strategy: profile.metadata_buffers.copy_string(strategy(op, job))?,
                input_distinct_keys: distinct,
                distinct_exact: exact,
            });
        }
        profile.writer_estimate = writers::estimate(job, &profile);
        profile.auto_observations = key.binding().map(|binding| engine::AutoObservations {
            binding,
            rows: profile.rows,
            columns: profile.columns as u64,
            decoded_field_bytes: observations.decoded_field_bytes,
            largest_decoded_row_bytes: observations.largest_decoded_row_bytes,
            partition,
        });
        profile.suggested_run_memory_mb = profile
            .auto_observations
            .and_then(|hint| engine::auto::analyzed_memory_target(job, key.length, hint));
        profile.cache_hit = cache_hit;
        profile.seconds = started.elapsed().as_secs_f64();
        Ok(profile)
    }
}
struct Cancellable<'a, R> {
    source: R,
    cancel: &'a AtomicBool,
}
impl<R: Read> Read for Cancellable<'_, R> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        if self.cancel.load(Ordering::Relaxed) {
            return Err(io::Error::other("cancelled"));
        }
        self.source.read(buffer)
    }
}
fn scan(
    job: &Job,
    cancel: &AtomicBool,
    notify: &Notify,
    key: &Key,
    pool: Arc<crate::resources::MemoryPool>,
    parallel: bool,
    memory_mb: u64,
) -> Result<Observations> {
    // Profiling does not create a job Context or temporary files. Use the same
    // half-budget workspace policy for its parser and retained header/preview.
    let workspace = Arc::new(Workspace::shared(
        (memory_mb * 1024 * 1024 / 2) as usize,
        pool,
    ));
    let mut key_buffers = Reservation::for_workspace(workspace.clone());
    key_buffers.resize(key.path.capacity() + key.input_options.capacity())?;
    let mut observations = engine::with_input(
        job,
        Reservation::for_workspace(workspace.clone()),
        |source| scan_configured(source, job, cancel, notify, workspace, parallel),
    )?;
    observations.key_buffers = key_buffers;
    Ok(observations)
}
#[cfg(test)]
fn scan_reserved(
    source: Box<dyn Read + '_>,
    job: &Job,
    cancel: &AtomicBool,
    notify: &Notify,
    workspace: Arc<Workspace>,
) -> Result<Observations> {
    scan_configured(source, job, cancel, notify, workspace, false)
}
fn scan_configured(
    source: Box<dyn Read + '_>,
    job: &Job,
    cancel: &AtomicBool,
    notify: &Notify,
    workspace: Arc<Workspace>,
    parallel: bool,
) -> Result<Observations> {
    let input = Intake::new(
        Cancellable { source, cancel },
        &job.input_csv,
        job.resources.max_record_bytes,
        Reservation::for_workspace(workspace.clone()),
    )?;
    crate::csv_intake::with_dialect!(input, &job.input_dialect, |input| scan_records(
        input, job, cancel, notify, workspace, parallel,
    ))
}

fn scan_records(
    mut input: Intake<impl crate::csv_intake::Records>,
    job: &Job,
    cancel: &AtomicBool,
    notify: &Notify,
    workspace: Arc<Workspace>,
    parallel: bool,
) -> Result<Observations> {
    // Declare the retained grant before its payload for early-return cleanup.
    let mut header_buffers = input.reservation();
    let mut preview_buffers = Reservation::for_workspace(workspace.clone());
    let mut metadata_buffers = Reservation::for_workspace(workspace.clone());
    let mut scan_buffers = Reservation::for_workspace(workspace.clone());
    let mut combination_buffers = Reservation::for_workspace(workspace.clone());
    let key_buffers = Reservation::for_workspace(workspace.clone());
    let header = input.header()?.map(|header| {
        let (fields, memory) = header.into_parts();
        header_buffers = memory;
        fields
    });
    let first = input.prefetch()?;
    let columns = input.columns();
    let (wanted, _selection_buffers) =
        selections(job, header.as_deref(), columns, &scan_buffers, false)?;
    // Source column summaries are independent of the pipeline. Admit the
    // summary descriptors up front and allocate sketches only on truncation.
    let mut column_values = Vec::new();
    metadata_buffers.reserve_vec(&mut column_values, columns)?;
    let mut sketches: Vec<Option<Box<Cardinality>>> = Vec::new();
    scan_buffers.reserve_vec(&mut sketches, columns)?;
    for column in 0..columns {
        column_values.push(ColumnProfile {
            column,
            values: Vec::new(),
            frequencies: Default::default(),
            truncated: false,
            distinct: 0,
            distinct_exact: false,
        });
        sketches.push(None);
    }
    let mut combinations: Vec<(Vec<usize>, Cardinality)> = Vec::new();
    scan_buffers.reserve_vec(
        &mut combinations,
        wanted.iter().filter(|c| c.len() > 1).count(),
    )?;
    for indices in wanted.iter().filter(|c| c.len() > 1) {
        if combinations.iter().any(|(key, _)| key == indices) {
            continue;
        }
        let mut key = Vec::new();
        combination_buffers.reserve_vec(&mut key, indices.len())?;
        key.extend_from_slice(indices);
        combinations.push((key, Cardinality::default()));
    }
    let first_partition = engine::auto::partition_columns(job).map(|_| wanted[0].as_slice());
    let mut partition_buckets = [0u64; 64];
    let mut decoded_field_bytes = 0u64;
    let mut largest_decoded_row_bytes = 0u64;
    let mut rows = 0;
    let mut values_bytes = 0;
    let mut preview = Vec::new();
    let mut preview_bytes = 0;
    let mut records =
        records::Records::new(input, first, job, columns + combinations.len(), parallel);
    while let Some(record) = records.next(&combinations, cancel)? {
        let fields = record.fields;
        let row_bytes = fields.iter().map(|field| field.len() as u64).sum();
        decoded_field_bytes += row_bytes;
        largest_decoded_row_bytes = largest_decoded_row_bytes.max(row_bytes);
        if let Some([column]) = first_partition {
            let hash = blake3::hash(fields[*column].as_bytes());
            partition_buckets[hash.as_bytes()[0] as usize % 64] += 1;
        }
        ensure!(!cancel.load(Ordering::Relaxed), "cancelled");
        for (i, (summary, cardinality)) in column_values.iter_mut().zip(&mut sketches).enumerate() {
            let value = &fields[i];
            if let Some(count) = summary.frequencies.get_mut(value.as_str()) {
                *count += 1;
                continue;
            }
            let hash = || {
                record
                    .hashes
                    .map_or_else(|| blake3::hash(value.as_bytes()), |hashes| hashes[i])
            };
            if let Some(sketch) = cardinality {
                sketch.add(hash());
                continue;
            }
            if summary.values.len() == 100 || values_bytes + value.len() + 64 > 256 * 1024 {
                scan_buffers
                    .resize(scan_buffers.bytes() as usize + std::mem::size_of::<Cardinality>())?;
                let mut sketch = Box::<Cardinality>::default();
                for previous in &summary.values {
                    sketch.add(blake3::hash(previous.as_bytes()));
                }
                sketch.add(hash());
                *cardinality = Some(sketch);
                summary.truncated = true;
                let frequency_bytes = summary.frequencies.len() * FREQUENCY_NODE_BYTES
                    + summary
                        .frequencies
                        .keys()
                        .map(String::capacity)
                        .sum::<usize>();
                summary.frequencies.clear();
                metadata_buffers.resize(metadata_buffers.bytes() as usize - frequency_bytes)?;
            } else {
                values_bytes += value.len() + 64;
                let capacity = (summary.values.capacity() * 2).clamp(1, 100);
                if summary.values.len() == summary.values.capacity() {
                    metadata_buffers.reserve_vec(&mut summary.values, capacity)?;
                }
                metadata_buffers
                    .resize(metadata_buffers.bytes() as usize + FREQUENCY_NODE_BYTES)?;
                let counted = metadata_buffers.copy_string(value)?;
                let copy = metadata_buffers.copy_string(value)?;
                let position = summary.values.binary_search(value).unwrap_err();
                summary.frequencies.insert(counted, 1);
                summary.values.insert(position, copy);
            }
        }
        for (i, (indices, cardinality)) in combinations.iter_mut().enumerate() {
            let hash = record.hashes.map_or_else(
                || combination_hash(fields, indices),
                |hashes| hashes[columns + i],
            );
            cardinality.add(hash);
            if first_partition.is_some_and(|wanted| wanted == indices) {
                partition_buckets[hash.as_bytes()[0] as usize % 64] += 1;
            }
        }
        if preview.len() < 8 {
            // Preserve v1 preview selection: its byte-at-a-time parser grew
            // nonempty fields from 8 bytes by doubling. Actual capacity now
            // depends on chunk sizes and previous rows, not this row's content.
            let size = fields
                .iter()
                .map(|value| {
                    let capacity = if value.is_empty() {
                        0
                    } else {
                        value.len().next_power_of_two().max(8)
                    };
                    capacity + std::mem::size_of::<String>()
                })
                .sum::<usize>();
            if preview_bytes + size <= 32 * 1024 {
                preview_bytes += size;
                if preview.capacity() == 0 {
                    reserve_preview(&mut preview, 8, &mut preview_buffers)?;
                }
                preview.push(clone_fields_reserved(fields, &mut preview_buffers)?);
            }
        }
        #[cfg(feature = "resource-contract-tests")]
        crate::guide_test_control::checkpoint("profile-row");
        rows += 1;
        if rows % 16_384 == 0 {
            workspace.recheck_pressure();
            notify(crate::storage::Progress {
                phase: crate::storage::ProgressPhase::literal("Profiling all input records"),
                rows,
                temp_bytes: 0,
            });
        }
    }
    let mut execution = records.execution;
    for (summary, cardinality) in column_values.iter_mut().zip(sketches) {
        summary.distinct_exact = !summary.truncated;
        let retained = summary.values.len() as u64;
        summary.distinct =
            cardinality.map_or(retained, |sketch| sketch.estimate().max(retained).min(rows));
    }
    let mut retained_combinations = Vec::new();
    combination_buffers.reserve_vec(&mut retained_combinations, combinations.len())?;
    for (indices, cardinality) in combinations {
        retained_combinations.push((indices, cardinality.estimate().min(rows)));
    }
    let partition = first_partition.and_then(|indices| {
        let bucket = partition_buckets.into_iter().max().unwrap_or(0);
        let (keys, keys_exact, largest_key_bucket_rows) = match indices {
            [column] => {
                let summary = column_values
                    .iter()
                    .find(|summary| summary.column == *column)?;
                let largest = summary.frequencies.values().copied().max().unwrap_or(0);
                (
                    summary.distinct,
                    summary.distinct_exact,
                    if summary.distinct_exact {
                        largest
                    } else {
                        bucket
                    },
                )
            }
            _ => {
                let (_, keys) = retained_combinations
                    .iter()
                    .find(|(key, _)| key == indices)?;
                (*keys, false, bucket)
            }
        };
        Some(engine::auto::PartitionObservation {
            columns: selection_hash(indices),
            keys,
            keys_exact,
            largest_key_bucket_rows,
            skew_exact: keys_exact,
        })
    });
    notify(crate::storage::Progress {
        phase: crate::storage::ProgressPhase::literal("Input profile complete"),
        rows,
        temp_bytes: 0,
    });
    Ok(Observations {
        profile: InputProfile { rows, columns, header, preview, column_values, stages: vec![], writer_estimate: None, auto_observations: None, suggested_run_memory_mb: None, cache_hit: false, seconds: 0.0,
            accuracy: metadata_buffers.copy_string("Every input record validated; row count is exact. Distinct counts marked approximate use full-file sketches (about 3.25% relative standard error, not a bound). Input key counts are not final pipeline group counts. Run applies operations and validates output limits independently.")?, header_buffers, preview_buffers, metadata_buffers,
            execution: { execution.scan_peak_reserved_bytes = workspace.peak(); execution } },
        combinations: retained_combinations, partition, decoded_field_bytes, largest_decoded_row_bytes, _combination_buffers: combination_buffers, key_buffers,
    })
}

fn combination_hash(fields: &[String], indices: &[usize]) -> blake3::Hash {
    let mut hash = blake3::Hasher::new();
    for &index in indices {
        let value = &fields[index];
        hash.update(&(value.len() as u64).to_le_bytes());
        hash.update(value.as_bytes());
    }
    hash.finalize()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(windows)]
    fn windows_rescans_and_returned_copies_keep_independent_capacity_owners() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("input.csv");
        std::fs::write(&path, "id,key\n1,a\n2,b\n")?;
        let job = Job {
            input: path.to_string_lossy().into_owned(),
            operations: vec![Operation::Partition {
                columns: vec![chopper_core::Column::Index(1)],
            }],
            ..Job::default()
        };
        let limit = 1024 * 1024;
        let pool = Arc::new(crate::resources::MemoryPool::new(limit as u64));
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let first = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert!(!first.cache_hit);
        assert!(cache.entry.is_none());
        let first_bytes = retained_bytes(&first) as u64;
        assert_eq!(pool.usage().reserved_bytes, first_bytes);
        assert!(!first.stages[0].strategy.is_empty());
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(limit, pool.clone())));
        pressure.resize(limit - first_bytes as usize - 1024)?;
        let held = pool.usage().reserved_bytes;
        assert!(cache
            .profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
            .is_err());
        assert!(cache.entry.is_none());
        assert_eq!(pool.usage().reserved_bytes, held);
        drop(pressure);
        for delta in [-1isize, 0, 1] {
            let mut pressure =
                Reservation::for_workspace(Arc::new(Workspace::shared(limit, pool.clone())));
            pressure.resize(
                limit
                    - first_bytes as usize
                    - (first_bytes as usize).checked_add_signed(delta).unwrap(),
            )?;
            let held = pool.usage().reserved_bytes;
            let copy = first.try_clone();
            assert_eq!(copy.is_ok(), delta >= 0);
            if let Ok(copy) = &copy {
                assert_eq!(serde_json::to_value(copy)?, serde_json::to_value(&first)?);
                assert_eq!(
                    pool.usage().reserved_bytes,
                    held + retained_bytes(copy) as u64
                );
            } else {
                assert_eq!(pool.usage().reserved_bytes, held);
            }
            drop(copy);
            assert_eq!(pool.usage().reserved_bytes, held);
        }
        let second = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert!(!second.cache_hit);
        assert!(cache.entry.is_none());
        assert_eq!(first.preview, second.preview);
        assert_eq!(
            pool.usage().reserved_bytes,
            first_bytes + retained_bytes(&second) as u64
        );
        drop(cache);
        drop(first);
        assert_eq!(pool.usage().reserved_bytes, retained_bytes(&second) as u64);
        drop(second);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn compressed_profile_adapter_shares_pool_and_releases_on_denial() -> Result<()> {
        use std::io::Write;
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("input.csv.gz");
        let mut encoder = flate2::write::GzEncoder::new(Vec::new(), Default::default());
        encoder.write_all(b"id,key\n1,a\n2,b\n")?;
        std::fs::write(&path, encoder.finish()?)?;
        let job = Job {
            input: path.to_string_lossy().into_owned(),
            ..Job::default()
        };
        let limit = 1024 * 1024;
        let pool = Arc::new(crate::resources::MemoryPool::new(limit));
        let mut cache = ProfileCache::with_memory_pool(pool.clone());
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(limit as usize, pool.clone())));
        pressure.resize(limit as usize - 8191)?;
        let held = pool.usage().reserved_bytes;
        let error = cache
            .profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))
            .err()
            .expect("compressed input must be denied");
        assert!(error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .is_some());
        assert_eq!(pool.usage().reserved_bytes, held);
        assert!(cache.entry.is_none());
        drop(pressure);
        let profile = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert_eq!(profile.rows, 2);
        assert!(pool.usage().reserved_bytes > 0);
        cache.clear();
        assert!(pool.usage().reserved_bytes > 0);
        drop(profile);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn complete_profile_metadata_checks_shared_peak_and_combination_deduplication() -> Result<()> {
        let job = Job {
            operations: vec![
                Operation::Partition {
                    columns: vec![
                        chopper_core::Column::Index(0),
                        chopper_core::Column::Index(1),
                    ],
                },
                Operation::Partition {
                    columns: vec![
                        chopper_core::Column::Index(1),
                        chopper_core::Column::Index(0),
                        chopper_core::Column::Index(0),
                    ],
                },
            ],
            ..Job::default()
        };
        let mut text = "id,key\n".to_owned();
        for id in 0..300 {
            text.push_str(&format!("{id},{}\n", id % 7));
        }
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let observations = scan_text(text.as_bytes(), &job, workspace.clone())?;
        assert_eq!(observations.combinations.len(), 1);
        assert!(observations.profile.column_values[0].truncated);
        assert!(observations.profile.column_values[0].frequencies.is_empty());
        let frequencies = &observations.profile.column_values[1].frequencies;
        assert_eq!(frequencies.values().sum::<u64>(), 300);
        assert_eq!(frequencies["0"], 43);
        assert_eq!(frequencies["6"], 42);
        assert_eq!(
            observations.profile.column_values[1].values,
            ["0", "1", "2", "3", "4", "5", "6"]
        );
        let retained = retained_bytes(&observations.profile)
            + observations.combinations.capacity() * std::mem::size_of::<(Vec<usize>, u64)>()
            + observations
                .combinations
                .iter()
                .map(|(indices, _)| indices.capacity() * std::mem::size_of::<usize>())
                .sum::<usize>();
        assert_eq!(workspace.used(), retained as u64);
        let expected = serde_json::to_value(&observations.profile)?;
        drop(observations);
        let peak = workspace.peak() as usize;
        assert_eq!(workspace.used(), 0);
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(peak + 100));
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(100usize.checked_add_signed(-delta).unwrap())?;
            let result = scan_text(text.as_bytes(), &job, workspace.clone());
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(observations) = &result {
                assert_eq!(serde_json::to_value(&observations.profile)?, expected);
            }
            drop(result);
            assert_eq!(workspace.used(), other.bytes());
        }
        Ok(())
    }

    #[test]
    #[cfg(not(windows))]
    fn returned_stage_text_and_cache_keys_are_charged_and_survive_cache_clear() -> Result<()> {
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let (_dir, mut job, mut cache) = cached_profile(workspace.clone())?;
        job.operations = vec![Operation::Partition {
            columns: vec![chopper_core::Column::Index(1)],
        }];
        let key = &cache.entry.as_ref().unwrap().0;
        let key_bytes = key.path.capacity() + key.input_options.capacity();
        cache
            .entry
            .as_mut()
            .unwrap()
            .1
            .key_buffers
            .resize(key_bytes)?;
        let first = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert!(first.cache_hit);
        assert!(!first.stages[0].strategy.is_empty());
        let second = first.try_clone()?;
        assert_eq!(
            serde_json::to_value(&first)?,
            serde_json::to_value(&second)?
        );
        assert_eq!(
            second.metadata_buffers.bytes() as usize,
            retained_bytes(&second)
                - second.header_buffers.bytes() as usize
                - second.preview_buffers.bytes() as usize
        );
        cache.clear();
        assert_eq!(
            workspace.used(),
            (retained_bytes(&first) + retained_bytes(&second)) as u64
        );
        drop(first);
        assert_eq!(workspace.used(), retained_bytes(&second) as u64);
        drop(second);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    fn retained_bytes(profile: &InputProfile) -> usize {
        let fields_bytes = |fields: &Vec<String>| {
            fields.capacity() * std::mem::size_of::<String>()
                + fields.iter().map(String::capacity).sum::<usize>()
        };
        profile.header.as_ref().map_or(0, fields_bytes)
            + profile.preview.capacity() * std::mem::size_of::<Vec<String>>()
            + profile.preview.iter().map(fields_bytes).sum::<usize>()
            + profile.column_values.capacity() * std::mem::size_of::<ColumnProfile>()
            + profile
                .column_values
                .iter()
                .map(|c| {
                    c.frequencies.len() * FREQUENCY_NODE_BYTES
                        + c.frequencies.keys().map(String::capacity).sum::<usize>()
                        + c.values.capacity() * std::mem::size_of::<String>()
                        + c.values.iter().map(String::capacity).sum::<usize>()
                })
                .sum::<usize>()
            + profile.stages.capacity() * std::mem::size_of::<StageProfile>()
            + profile
                .stages
                .iter()
                .map(|s| s.strategy.capacity())
                .sum::<usize>()
            + profile.accuracy.capacity()
    }

    #[test]
    fn profile_row_copy_reserves_shared_capacity_before_materialization() -> Result<()> {
        let fields = vec!["界\0\n".into(), String::new(), "tail".into()];
        let needed = fields.len() * std::mem::size_of::<String>() + 9;
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(1024));
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(1024 - needed.checked_add_signed(delta).unwrap())?;
            let mut reservation = Reservation::for_workspace(workspace.clone());
            let copy = clone_fields_reserved(&fields, &mut reservation);
            assert_eq!(copy.is_ok(), delta >= 0);
            if let Ok(copy) = &copy {
                assert_eq!(copy, &fields);
                assert_eq!(reservation.bytes(), needed as u64);
            }
            drop(copy);
            drop(reservation);
            assert_eq!(workspace.used(), other.bytes());
        }
        Ok(())
    }

    #[cfg(not(windows))]
    fn cached_profile(workspace: Arc<Workspace>) -> Result<(tempfile::TempDir, Job, ProfileCache)> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        let text = "id,key\n1,界\n2,\"a\nb\"\n3,\n";
        std::fs::write(&input, text)?;
        let job = Job {
            input: input.to_string_lossy().into(),
            ..Job::default()
        };
        let observations = scan_text(text.as_bytes(), &job, workspace)?;
        let cache = ProfileCache {
            entry: Some((Key::read(&job, 256)?, observations)),
            pool: None,
        };
        Ok((dir, job, cache))
    }

    #[test]
    #[cfg(not(windows))]
    fn cached_profile_rows_and_independent_copies_retain_charges_until_drop() -> Result<()> {
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let (_dir, job, mut cache) = cached_profile(workspace.clone())?;
        let base = retained_bytes(&cache.entry.as_ref().unwrap().1.profile) as u64;
        assert_eq!(workspace.used(), base);
        let first = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let second = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        assert!(first.cache_hit && second.cache_hit);
        assert_eq!(first.header, second.header);
        assert_eq!(first.preview, second.preview);
        let first_bytes = retained_bytes(&first) as u64;
        let second_bytes = retained_bytes(&second) as u64;
        assert_eq!(workspace.used(), base + first_bytes + second_bytes);
        cache.clear();
        assert_eq!(workspace.used(), first_bytes + second_bytes);
        drop(cache);
        drop(first);
        assert_eq!(workspace.used(), second_bytes);
        drop(second);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    #[cfg(not(windows))]
    fn cached_profile_copy_denial_preserves_cache_and_releases_partial_copies() -> Result<()> {
        let limit = 1024 * 1024;
        let workspace = Arc::new(Workspace::new(limit));
        let (_dir, job, mut cache) = cached_profile(workspace.clone())?;
        let copy = cache.entry.as_ref().unwrap().1.profile.try_clone()?;
        let needed = retained_bytes(&copy);
        drop(copy);
        let base = workspace.used();
        let expected = serde_json::to_value(&cache.entry.as_ref().unwrap().1.profile)?;
        for delta in [-1isize, 0, 1] {
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(limit - base as usize - needed.checked_add_signed(delta).unwrap())?;
            let held = workspace.used();
            let result = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}));
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(copy) = &result {
                assert!(copy.cache_hit);
                assert_eq!(workspace.used(), held + needed as u64);
            } else {
                assert_eq!(workspace.used(), held);
            }
            drop(result);
            assert_eq!(workspace.used(), held);
            assert_eq!(
                serde_json::to_value(&cache.entry.as_ref().unwrap().1.profile)?,
                expected
            );
            drop(other);
        }
        cache.clear();
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    fn scan_text(text: &[u8], job: &Job, workspace: Arc<Workspace>) -> Result<Observations> {
        let notify: Notify = Arc::new(|_| {});
        scan_reserved(
            Box::new(text),
            job,
            &AtomicBool::new(false),
            &notify,
            workspace,
        )
    }

    #[test]
    fn profiling_parser_capacity_edges_include_headers_and_growth_overlap() -> Result<()> {
        let late_wide = format!("id,value\n1,a\n2,{}\n3,z\n", "界".repeat(24_000));
        let many_columns = format!(
            "{}\n{}\n",
            vec!["h"; 1000].join(","),
            vec!["v"; 1000].join(",")
        );
        for (text, headers) in [
            (late_wide.as_str(), true),
            (late_wide.as_str(), false),
            (many_columns.as_str(), true),
            ("", true),
        ] {
            let mut job = Job::default();
            job.input_csv.headers = headers;
            let workspace = Arc::new(Workspace::new(4 * 1024 * 1024));
            let expected =
                serde_json::to_value(scan_text(text.as_bytes(), &job, workspace.clone())?.profile)?;
            assert_eq!(workspace.used(), 0);
            let peak = workspace.peak() as usize;
            assert!(peak >= 64 * 1024);
            for delta in [-1, 0, 1] {
                let workspace = Arc::new(Workspace::new(peak.checked_add_signed(delta).unwrap()));
                let result = scan_text(text.as_bytes(), &job, workspace.clone());
                assert_eq!(
                    result.is_ok(),
                    delta >= 0,
                    "headers={headers}, delta={delta}"
                );
                if let Ok(result) = result {
                    assert_eq!(serde_json::to_value(result.profile)?, expected);
                }
                assert_eq!(workspace.used(), 0, "reservation leaked");
            }
            // Independent live reservations compete with the parser at the same edge.
            let workspace = Arc::new(Workspace::new(peak + 123));
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(124)?;
            assert!(scan_text(text.as_bytes(), &job, workspace.clone()).is_err());
            assert_eq!(workspace.used(), 124);
            other.resize(123)?;
            assert!(scan_text(text.as_bytes(), &job, workspace.clone()).is_ok());
            assert_eq!(workspace.used(), 123);
            drop(other);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn profiling_header_remains_charged_through_scan_completion() -> Result<()> {
        let columns = 1000;
        let text = format!(
            "{}\n{}\n",
            vec!["h"; columns].join(","),
            vec!["v"; columns].join(",")
        );
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let observed = workspace.clone();
        let notify: Notify = Arc::new(move |_| {
            let fixed =
                64 * 1024 + std::mem::size_of::<DecodeReader<Cancellable<'_, Box<dyn Read>>>>();
            // Even after EOF, both the retained header and reusable data-field
            // descriptor arrays still exist, independently of parser scratch.
            assert!(
                observed.used() >= (fixed + 2 * columns * std::mem::size_of::<String>()) as u64
            );
        });
        let result = scan_reserved(
            Box::new(text.as_bytes()),
            &Job::default(),
            &AtomicBool::new(false),
            &notify,
            workspace.clone(),
        )?;
        assert_eq!(result.profile.rows, 1);
        assert!(workspace.used() > 0, "retained rows lost their charge");
        drop(result);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn profiling_parser_releases_on_corruption_oversize_and_cancellation() -> Result<()> {
        let job = Job::default();
        for text in ["id\na\n\"unterminated", "id\n\"bad\"x\n", "id,value\n1\n"] {
            let workspace = Arc::new(Workspace::new(1024 * 1024));
            assert!(scan_text(text.as_bytes(), &job, workspace.clone()).is_err());
            assert_eq!(workspace.used(), 0);
        }
        let mut small = job.clone();
        small.resources.max_record_bytes = 32;
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        assert!(scan_text(
            format!("id\n{}\n", "x".repeat(33)).as_bytes(),
            &small,
            workspace.clone()
        )
        .is_err());
        assert_eq!(workspace.used(), 0);

        let cancel = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let observed = workspace.clone();
        let notify: Notify = Arc::new(move |_| {
            assert!(observed.used() > 64 * 1024, "live parser was uncharged");
            signal.store(true, Ordering::Relaxed);
        });
        let text = "id\n".to_owned() + &"x\n".repeat(20_000);
        let result = scan_reserved(
            Box::new(text.as_bytes()),
            &job,
            &cancel,
            &notify,
            workspace.clone(),
        );
        assert!(result.is_err());
        assert!(cancel.load(Ordering::Relaxed));
        assert_eq!(workspace.used(), 0);
        Ok(())
    }
}
