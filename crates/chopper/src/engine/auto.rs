//! Resource policy, strategy eligibility and the completed Run report.
use super::*;
use chopper_core::{Compression, Grouping, Resources, Shuffle};
use std::path::Path;

/// Compact, bounded observations from one successful Analyze. The adapters
/// supply these only for the current session or an explicitly chosen report.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct AutoObservations {
    pub(crate) binding: [u8; 32],
    pub(crate) rows: u64,
    #[serde(default)]
    pub(crate) columns: u64,
    pub(crate) decoded_field_bytes: u64,
    pub(crate) largest_decoded_row_bytes: u64,
    pub(crate) partition: Option<PartitionObservation>,
}

/// Bounded facts from the existing hosted input preview. The browser only
/// forwards them for the same selected File and parser configuration.
#[derive(Debug, Clone, Copy, Deserialize)]
pub struct PreviewObservations {
    max_record_bytes: usize,
    rows: u64,
    columns: u64,
    decoded_field_bytes: u64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub(crate) struct PartitionObservation {
    pub(crate) columns: [u8; 32],
    pub(crate) keys: u64,
    pub(crate) keys_exact: bool,
    // Exact max for complete frequencies, otherwise a hash bucket upper bound.
    pub(crate) largest_key_bucket_rows: u64,
    pub(crate) skew_exact: bool,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Accuracy {
    Exact,
    Estimated,
    Unknown,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct Fact {
    value: Option<u64>,
    accuracy: Accuracy,
}
impl Fact {
    fn exact(value: u64) -> Self {
        Self {
            value: Some(value),
            accuracy: Accuracy::Exact,
        }
    }
    fn estimated(value: u64) -> Self {
        Self {
            value: Some(value),
            accuracy: Accuracy::Estimated,
        }
    }
    fn unknown() -> Self {
        Self {
            value: None,
            accuracy: Accuracy::Unknown,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Strategy {
    Existing,
    ProbabilisticShuffleFusion,
    IndexedExactQuotaLookup,
    CountedBalanced,
    CountedPartitionBalanced,
    BoundedWriterChain,
    BoundedFinalWriters,
    BatchedFinalSync,
    WideUniformMerge,
    ShortTailUniformMerge,
    RetainedExactWriters,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Route {
    Streaming,
    Counted,
    BoundedWriters,
    PrivateTerminal,
    Snapshot,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Advice {
    Absent,
    Unverified,
    Matched,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub(crate) struct RunMeasurements {
    pub(crate) temporary_bytes_written: u64,
    pub(crate) temporary_bytes_read: u64,
    pub(crate) peak_workspace_reserved_bytes: u64,
    pub(crate) peak_writer_slots: u64,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub(crate) peak_deflate_workers: u64,
    #[serde(default)]
    pub(crate) peak_merge_fan_in: u64,
    #[serde(default)]
    pub(crate) retained_exact_writers: bool,
    #[serde(default)]
    pub(crate) retained_exact_fallbacks: u64,
    #[serde(default)]
    pub(crate) used_short_tail: bool,
}

fn is_zero(value: &u64) -> bool {
    *value == 0
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct AutoPlan {
    version: u32,
    physical_plan: Route,
    actual_strategy: Strategy,
    analysis_status: Advice,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    native_merge_fan_in: Option<usize>,
    #[serde(default)]
    pub(super) try_retained_exact: bool,
    #[serde(default)]
    pub(super) direct_preflight_fallback: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    suggested_max_files: Option<u64>,
    #[serde(default)]
    worker_limit_from_analyze: bool,
    input_file_bytes: Fact,
    analyzed_rows: Fact,
    decoded_field_bytes: Fact,
    largest_decoded_row_bytes: Fact,
    partition_joint_keys: Fact,
    largest_partition_rows: Fact,
    expected_live_fanout: Fact,
    root_partition: bool,
    effective_memory_bytes: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    memory_plan: Option<MemoryPlan>,
    effective_workers: usize,
    effective_grouping: Grouping,
    validated_rows: Fact,
    validated_largest_record_bytes: Fact,
    probabilistic_shuffle_attempts: u64,
    probabilistic_shuffle_retries: u64,
    validated_largest_partition_rows: Fact,
    #[serde(default = "Fact::unknown")]
    validated_root_partitions: Fact,
    routing_fallbacks: u64,
    measurements: RunMeasurements,
}

pub(crate) fn workers(resources: &Resources, memory_mb: u64, automatic_limit: usize) -> usize {
    if cfg!(target_os = "wasi") {
        1
    } else if resources.workers == 0 {
        std::thread::available_parallelism()
            .map(usize::from)
            .unwrap_or(1)
            .min(4)
            .min(automatic_limit)
            .min((memory_mb / 64).max(1) as usize)
    } else {
        resources.workers
    }
}

const MIN_BOUNDED_PARTITION_BYTES: u64 = 307_200_000;
// A small retained config can round the default Windows 128 MiB pool down to
// 255 MiB nominal. Keep the real working-headroom floor separate.
pub(super) const NATIVE_DIRECT_MIN_MEMORY_MB: u64 = 255;
pub(super) const NATIVE_DIRECT_HEADROOM_BYTES: u64 = 96 * 1024 * 1024;

pub(crate) fn suggested_partition_max_files(
    job: &Job,
    exact_groups: u64,
    memory_mb: u64,
) -> Option<u64> {
    let cap = descriptor_writer_ceiling(2).min(32) as u64;
    (cfg!(any(target_os = "linux", windows))
        && matches!(job.operations.as_slice(), [Operation::Partition { .. }])
        && job.compression == chopper_core::Compression::None
        && job.resources.grouping == Grouping::Auto
        && job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        && job.output_csv.encoding.eq_ignore_ascii_case("utf-8")
        && job.resources.max_record_bytes <= 128 * 1024
        && job.limits.rows.is_none()
        && job.limits.bytes.is_none()
        && job.limits.compressed_bytes.is_none()
        && memory_mb >= NATIVE_DIRECT_MIN_MEMORY_MB
        && exact_groups > 0
        && exact_groups <= cap
        && job.resources.max_files > cap
        && super::direct::native_input_hint(job)
            .is_some_and(|bytes| bytes >= MIN_BOUNDED_PARTITION_BYTES))
    .then_some(exact_groups)
}

/// Route only from declared caps and current native resources. Analyze cannot
/// authorize the retained writer owners or substitute for the count pass.
pub(super) fn native_direct_candidate(
    job: &Job,
    pool: &crate::resources::MemoryPool,
) -> Option<super::direct::Plan> {
    use super::direct::Plan;
    const MIB: u64 = 1024 * 1024;
    let utf8_output = job.output_csv.encoding.eq_ignore_ascii_case("utf-8");
    let wide_interleaved = cfg!(target_os = "linux")
        && job.output_csv.encoding.eq_ignore_ascii_case("utf-16le")
        && matches!(
            job.operations.as_slice(),
            [Operation::Interleaved { files: 16 }]
        );
    if !cfg!(any(target_os = "linux", windows))
        || job.compression != chopper_core::Compression::None
        || job.resources.grouping != chopper_core::Grouping::Auto
        || !job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        || !(utf8_output || wide_interleaved)
        || !matches!(
            job.operations.first(),
            Some(
                Operation::Partition { .. }
                    | Operation::Balanced { .. }
                    | Operation::Interleaved { .. }
                    | Operation::AssignProbabilistic { .. }
            )
        )
    {
        return None;
    }
    let bytes = super::direct::native_input_hint(job)?;
    let memory = pool.resolve_memory(&job.resources).ok()?;
    let available = pool
        .admission_limit()
        .saturating_sub(pool.reservation_counts().0);
    if memory < NATIVE_DIRECT_MIN_MEMORY_MB || available < NATIVE_DIRECT_HEADROOM_BYTES {
        return None;
    }
    let writer_ceiling = descriptor_writer_ceiling(2) as u64;
    let narrow = job.resources.max_record_bytes <= 128 * 1024;
    match job.operations.as_slice() {
        [Operation::Interleaved { files: 16 }]
            if wide_interleaved
                && bytes >= 1536 * MIB
                && job.resources.max_record_bytes <= MIB as usize
                && job.resources.max_files >= 16
                && writer_ceiling >= 16 =>
        {
            Some(Plan::Fanout {
                chain: false,
                automatic: true,
            })
        }
        [Operation::Interleaved { files }]
            if cfg!(target_os = "linux")
                && bytes >= 2048 * MIB
                && (8_192..=16_384).contains(files)
                && *files <= job.resources.max_files
                && *files <= linux_live_descriptors() as u64
                && available >= 512 * MIB
                && pool
                    .resolve_memory_for_run(&job.resources, [1024, 256])
                    .ok()?
                    >= 1024
                && job.resources.max_record_bytes <= 4 * 1024
                && job.limits.rows.is_none()
                && job.limits.bytes.is_none()
                && job.limits.compressed_bytes.is_none() =>
        {
            Some(Plan::BatchedFanout)
        }
        [Operation::Interleaved { files }]
            if utf8_output
                && bytes >= 2048 * MIB
                && narrow
                && *files > 1
                && *files <= writer_ceiling.min(16)
                && *files <= job.resources.max_files =>
        {
            Some(Plan::Fanout {
                chain: false,
                automatic: true,
            })
        }
        [Operation::AssignProbabilistic { groups, .. }]
            if utf8_output
                && bytes >= 2048 * MIB
                && narrow
                && (2..=16).contains(&groups.len())
                && groups.len() as u64 <= writer_ceiling.min(job.resources.max_files) =>
        {
            Some(Plan::Fanout {
                chain: false,
                automatic: true,
            })
        }
        [Operation::Partition { .. }]
            if bytes >= MIN_BOUNDED_PARTITION_BYTES
                && narrow
                && job.resources.max_files <= writer_ceiling.min(32) =>
        {
            Some(Plan::Fanout {
                chain: false,
                automatic: true,
            })
        }
        [Operation::Balanced { .. }] if bytes >= 2048 * MIB => Some(Plan::Counted {
            partition: false,
            automatic: true,
        }),
        [Operation::Partition { .. }, Operation::Balanced { files }]
            if bytes >= 2048 * MIB
                && narrow
                && *files <= writer_ceiling.min(64)
                && job.resources.max_files <= writer_ceiling.min(64) =>
        {
            Some(Plan::Counted {
                partition: true,
                automatic: true,
            })
        }
        operations @ [_, _] if bytes >= 2048 * MIB && narrow => {
            let leaves = operations.iter().try_fold(1u64, |product, operation| {
                let children = match operation {
                    Operation::Interleaved { files } => *files,
                    Operation::AssignProbabilistic { groups, .. } => groups.len() as u64,
                    _ => return None,
                };
                product.checked_mul(children)
            })?;
            (leaves <= writer_ceiling.min(16) && leaves <= job.resources.max_files).then_some(
                Plan::Fanout {
                    chain: true,
                    automatic: true,
                },
            )
        }
        _ => None,
    }
}

pub(super) fn native_retained_exact(job: &Job, pool: &crate::resources::MemoryPool) -> bool {
    const MIB: u64 = 1024 * 1024;
    cfg!(any(target_os = "linux", windows))
        && job.compression == chopper_core::Compression::None
        && job.resources.grouping == Grouping::Auto
        && job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        && job.output_csv.encoding.eq_ignore_ascii_case("utf-8")
        && matches!(job.operations.as_slice(), [Operation::Assign { groups, strata }]
            if !strata.is_empty() && (2..=8).contains(&groups.len())
                && groups.len() <= descriptor_writer_ceiling(2))
        && super::direct::native_input_hint(job).is_some_and(|bytes| bytes >= 2048 * MIB)
        && pool
            .resolve_memory(&job.resources)
            .is_ok_and(|memory| memory >= NATIVE_DIRECT_MIN_MEMORY_MB)
        && pool
            .admission_limit()
            .saturating_sub(pool.reservation_counts().0)
            >= NATIVE_DIRECT_HEADROOM_BYTES
}

pub(super) fn native_terminal_merge(
    job: &Job,
    pool: &crate::resources::MemoryPool,
) -> Option<usize> {
    const MIB: u64 = 1024 * 1024;
    if !cfg!(target_os = "linux")
        || job.compression != chopper_core::Compression::None
        || job.resources.grouping != Grouping::Auto
        || !matches!(
            job.operations.as_slice(),
            [
                Operation::Shuffle {
                    strategy: Shuffle::Uniform
                },
                Operation::Balanced { .. }
            ]
        )
        || linux_live_descriptors() < 4032
    {
        return None;
    }
    let bytes = super::direct::native_input_hint(job)?;
    let memory = pool.resolve_memory(&job.resources).ok()?;
    if bytes < 8 * 1024 * MIB
        || workers(&job.resources, memory, usize::MAX) != 1
        || pool
            .admission_limit()
            .saturating_sub(pool.reservation_counts().0)
            < memory * MIB
    {
        return None;
    }
    match memory {
        96 if !cfg!(feature = "experimental-spill-blocks") => Some(512),
        256 => Some(256),
        _ => None,
    }
}

#[cfg(target_os = "linux")]
pub(super) fn use_quota_index(quota: &[u64], rows: u64) -> bool {
    // The estimate is exact for the flat cursor once quotas have been rounded.
    quota.len() == 1000
        && rows >= 4_200_000
        && quota
            .iter()
            .enumerate()
            .map(|(i, &count)| u128::from(count) * (i + 1) as u128)
            .sum::<u128>()
            >= u128::from(rows) * 500
}

/// Keep the existing descriptor reserve and also leave room for current owners.
fn linux_live_descriptors() -> usize {
    if !cfg!(target_os = "linux") {
        return 0;
    }
    let Ok(active) = std::fs::read_dir("/proc/self/fd") else {
        return 0;
    };
    let active = active.take(65_536).count();
    if active == 65_536 {
        0
    } else {
        descriptor_writer_ceiling(1).saturating_sub(active)
    }
}

/// This is a scheduling ceiling. Actual opens and allocations still need to succeed.
pub(crate) fn descriptor_writer_ceiling(descriptors_per_writer: usize) -> usize {
    #[cfg(all(unix, not(target_os = "wasi")))]
    {
        let mut limit = std::mem::MaybeUninit::<libc::rlimit>::uninit();
        // SAFETY: a successful call initializes the entire limit.
        if unsafe { libc::getrlimit(libc::RLIMIT_NOFILE, limit.as_mut_ptr()) } == 0 {
            let soft = unsafe { limit.assume_init() }.rlim_cur;
            return (soft.saturating_sub(64) / descriptors_per_writer as libc::rlim_t)
                .min(usize::MAX as _) as usize;
        }
    }
    let _ = descriptors_per_writer;
    if cfg!(target_os = "wasi") {
        1
    } else {
        16
    }
}

pub(crate) fn partition_columns(job: &Job) -> Option<[u8; 32]> {
    let Some(Operation::Partition { columns }) = job.operations.first() else {
        return None;
    };
    // Stream into the hash to avoid a copy proportional to the configured keys.
    let mut hash = blake3::Hasher::new();
    serde_json::to_writer(&mut hash, columns).ok()?;
    Some(*hash.finalize().as_bytes())
}

const MIB: u64 = 1024 * 1024;

// RFC 1952 stores the last member's decoded length modulo 2^32 here.
fn gzip_last_member_bytes(path: &Path) -> Option<u64> {
    use std::io::{Read, Seek, SeekFrom};

    let mut file = std::fs::File::open(path).ok()?;
    let mut signature = [0; 3];
    file.read_exact(&mut signature).ok()?;
    if signature != [0x1f, 0x8b, 8] {
        return None;
    }
    file.seek(SeekFrom::End(-4)).ok()?;
    let mut bytes = [0; 4];
    file.read_exact(&mut bytes).ok()?;
    Some(u32::from_le_bytes(bytes).into())
}

fn interior_sort_estimate(path: &Path, file_bytes: u64, columns: u64) -> Option<u64> {
    use std::io::{Read, Seek, SeekFrom};

    let mut file = std::fs::File::open(path).ok()?;
    let mut window = [0; 64 * 1024];
    let mut sampled_bytes = 0u64;
    let mut sampled_rows = 0u64;
    for eighths in [2, 4, 6, 7] {
        let offset = file_bytes / 8 * eighths + (file_bytes % 8) * eighths / 8;
        file.seek(SeekFrom::Start(offset)).ok()?;
        file.read_exact(&mut window).ok()?;
        if window.iter().any(|byte| matches!(byte, b'"' | b'\r')) {
            return None;
        }
        let first = window.iter().position(|&byte| byte == b'\n')?;
        let last = window.iter().rposition(|&byte| byte == b'\n')?;
        let complete = window.get(first + 1..last)?;
        let rows = std::str::from_utf8(complete).ok()?.split('\n');
        let mut count = 0;
        for row in rows {
            if row.bytes().filter(|&byte| byte == b',').count() as u64 + 1 != columns {
                return None;
            }
            count += 1;
        }
        if count < 8 {
            return None;
        }
        sampled_bytes += (last - first) as u64;
        sampled_rows += count;
    }
    // Widths at these offsets are observations, not a CSV parse or a row census.
    let projected = u128::from(file_bytes)
        * u128::from(sampled_bytes + sampled_rows * (200 + 7 * columns))
        / u128::from(sampled_bytes);
    u64::try_from(projected).ok()
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
struct MemoryPlan {
    file_size_tier_mb: u64,
    #[serde(default)]
    preview_tier_mb: Option<u64>,
    #[serde(default)]
    gzip_member_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    interior_sort_bytes: Option<u64>,
    #[serde(default)]
    starting_tier_mb: Option<u64>,
    #[serde(default)]
    analyze_outside_range: bool,
    target_mb: u64,
    estimated_sort_bytes: Fact,
    from_analyze: bool,
}

fn memory_plan(
    job: &Job,
    file_bytes: Option<u64>,
    hint: Option<AutoObservations>,
    preview: Option<PreviewObservations>,
) -> Option<MemoryPlan> {
    if job.resources.memory_mb.as_mib().is_some()
        || job.compression != Compression::None
        || job.resources.grouping != Grouping::Auto
    {
        return None;
    }
    let partitioned = match job.operations.as_slice() {
        [Operation::Shuffle {
            strategy: Shuffle::Auto | Shuffle::Uniform,
        }] => false,
        [Operation::Partition { .. }, Operation::Shuffle {
            strategy: Shuffle::Auto | Shuffle::Uniform,
        }] => true,
        _ => return None,
    };
    let with_keys = |bytes: u64| {
        if partitioned {
            bytes.saturating_add(bytes / 8)
        } else {
            bytes
        }
    };
    let tier = |bytes| {
        [256, 512, 1024, 2048]
            .into_iter()
            .find(|mb| bytes <= mb * MIB / 4)
    };
    let csv = &job.input_csv;
    let path = Path::new(&job.input);
    let utf8 = csv.encoding.eq_ignore_ascii_case("utf-8");
    let extension_is = |suffix: &str| {
        path.extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case(suffix))
    };
    let plain = utf8 && extension_is("csv");
    let rough_from_length =
        |length: u64| (length >= 48 * MIB).then(|| with_keys(length.saturating_add(length / 2)));
    let rough = file_bytes.filter(|_| plain).and_then(rough_from_length);
    let size_tier = rough.and_then(tier).unwrap_or(256);
    let preview_facts = preview.filter(|sample| {
        utf8 && csv.delimiter == ','
            && csv.quote == '"'
            && csv.escape.is_none()
            && !csv.skip_empty_lines
            && sample.max_record_bytes == job.resources.max_record_bytes
            && sample.rows == 8
            && sample.columns > 0
            && sample.columns <= 32768
            && sample.decoded_field_bytes <= 32768
    });
    let gzip = (preview_facts.is_some()
        && (extension_is("gz") || extension_is("gzip"))
        && file_bytes.is_some_and(|bytes| bytes >= 18))
    .then(|| gzip_last_member_bytes(path))
    .flatten();
    let preview = file_bytes
        .filter(|_| plain)
        .or(gzip)
        .filter(|bytes| *bytes >= 32 * MIB)
        .zip(preview_facts)
        .and_then(|(bytes, sample)| {
            let raw_sample = sample.decoded_field_bytes + sample.rows * sample.columns;
            let sort_sample = sample.decoded_field_bytes + sample.rows * (200 + 8 * sample.columns);
            let projected = u128::from(bytes) * u128::from(sort_sample) / u128::from(raw_sample);
            let projected = with_keys(u64::try_from(projected).unwrap_or(u64::MAX));
            // For gzip, combine the preview projection and the rough length model.
            // The trailer can raise a starting target. The stream remains unvalidated.
            [gzip.and_then(rough_from_length), Some(projected)]
                .into_iter()
                .flatten()
                .filter_map(|estimate| tier(estimate).map(|target| (target, estimate)))
                .max_by_key(|(target, _)| *target)
                .filter(|(target, _)| *target > size_tier)
        });
    let starting_tier = preview.map_or(size_tier, |(target, _)| target);
    let interior = file_bytes
        .filter(|_| plain && csv.headers && starting_tier == 1024)
        .zip(preview_facts)
        .and_then(|(bytes, sample)| interior_sort_estimate(path, bytes, sample.columns))
        .map(with_keys)
        .filter(|estimate| (256 * MIB + 1..=528 * MIB).contains(estimate));
    let starting_tier = if interior.is_some() {
        2048
    } else {
        starting_tier
    };
    let analyzed = hint.filter(|hint| hint.columns > 0).map(|hint| {
        // Calibrated allowance for row descriptors, capacity growth and
        // packed field lengths. The sorter still admits every allocation.
        let row_overhead = 200u64.saturating_add(hint.columns.saturating_mul(8));
        with_keys(
            hint.decoded_field_bytes
                .saturating_add(hint.rows.saturating_mul(row_overhead)),
        )
    });
    let analyzed_tier = analyzed.and_then(|bytes| {
        // Analyze slightly overshot the top tier on the repeated narrow-tail
        // fixture that fit. Keep the calibrated margin local to that tier.
        tier(bytes).or_else(|| (bytes <= 528 * MIB).then_some(2048))
    });
    let estimated = analyzed_tier
        .and(analyzed)
        .or(interior)
        .or(preview.map(|(_, bytes)| bytes))
        .or(rough);
    Some(MemoryPlan {
        file_size_tier_mb: size_tier,
        preview_tier_mb: preview.map(|(target, _)| target),
        gzip_member_bytes: gzip.filter(|_| preview.is_some()),
        interior_sort_bytes: interior,
        starting_tier_mb: Some(starting_tier),
        analyze_outside_range: analyzed.is_some() && analyzed_tier.is_none(),
        target_mb: analyzed_tier.unwrap_or(starting_tier),
        estimated_sort_bytes: estimated.map_or_else(Fact::unknown, Fact::estimated),
        from_analyze: analyzed_tier.is_some(),
    })
}

// Linux measurements removed an intermediate merge in this band. Use
// existing Analyze observations so serialized size alone cannot trigger it.
fn linux_merge_memory_plan(job: &Job, hint: AutoObservations) -> Option<MemoryPlan> {
    if job.resources.memory_mb.as_mib().is_some()
        || job.compression != Compression::None
        || job.resources.grouping != Grouping::Auto
        || !job.input_csv.encoding.eq_ignore_ascii_case("utf-8")
        || !Path::new(&job.input)
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("csv"))
        || !matches!(
            job.operations.as_slice(),
            [Operation::Shuffle {
                strategy: Shuffle::Auto | Shuffle::Uniform
            }]
        )
        || hint.rows == 0
        || hint.columns == 0
        || hint.largest_decoded_row_bytes > MIB
    {
        return None;
    }
    let average_payload = hint.decoded_field_bytes / hint.rows;
    if !(384..=2048).contains(&average_payload) {
        return None;
    }

    // One descriptor and the packed u64 field count and lengths. The sort
    // buffer also reserves growth overlap and independently checks admission.
    let row_overhead = (std::mem::size_of::<crate::storage::PackedRow>() as u64)
        .saturating_add(hint.columns.saturating_add(1).saturating_mul(8));
    let footprint = hint
        .decoded_field_bytes
        .saturating_add(hint.rows.saturating_mul(row_overhead));
    if !(4096 * MIB + 1..=5120 * MIB).contains(&footprint) {
        return None;
    }
    Some(MemoryPlan {
        file_size_tier_mb: 256,
        preview_tier_mb: None,
        gzip_member_bytes: None,
        interior_sort_bytes: None,
        starting_tier_mb: Some(256),
        analyze_outside_range: false,
        target_mb: 384,
        estimated_sort_bytes: Fact::estimated(footprint),
        from_analyze: true,
    })
}

pub(crate) fn analyzed_memory_target(
    job: &Job,
    file_bytes: u64,
    hint: AutoObservations,
) -> Option<u64> {
    if cfg!(target_os = "wasi") {
        memory_plan(job, Some(file_bytes), Some(hint), None).map(|plan| plan.target_mb)
    } else {
        None
    }
}

impl AutoPlan {
    pub(super) fn start(
        job: &Job,
        pool: &crate::resources::MemoryPool,
        hint: Option<AutoObservations>,
        route: Route,
        preview: Option<PreviewObservations>,
    ) -> Self {
        let input_file_bytes = std::fs::metadata(&job.input)
            .ok()
            .filter(|metadata| metadata.is_file())
            .map_or_else(Fact::unknown, |metadata| Fact::exact(metadata.len()));
        let matched = hint.filter(|hint| crate::profile::auto_binding(job) == Some(hint.binding));
        let status = match (hint, matched) {
            (_, Some(_)) => Advice::Matched,
            (Some(_), None) => Advice::Unverified,
            _ => Advice::Absent,
        };
        let partition = matched
            .and_then(|hint| hint.partition)
            .filter(|partition| partition_columns(job) == Some(partition.columns));
        let memory_plan = if matches!(route, Route::Snapshot) {
            if cfg!(target_os = "wasi") {
                memory_plan(job, input_file_bytes.value, matched, preview)
            } else if cfg!(target_os = "linux") {
                matched.and_then(|hint| linux_merge_memory_plan(job, hint))
            } else {
                None
            }
        } else {
            None
        };
        let memory_mb = pool.resolve_memory(&job.resources).ok().unwrap_or(0);
        let memory_bytes = memory_mb * 1024 * 1024;
        let worker_limit_from_analyze = !cfg!(target_os = "wasi")
            && job.resources.workers == 0
            && matches!(route, Route::Snapshot | Route::PrivateTerminal)
            && matched
                .is_some_and(|hint| hint.rows <= 10_000 && hint.decoded_field_bytes <= 1024 * 1024);
        let workers = workers(&job.resources, memory_mb, usize::MAX);
        let expected_live_fanout = match job.operations.first() {
            Some(Operation::Partition { .. }) => partition.map_or_else(Fact::unknown, |p| {
                // Distinct keys estimate demand. Routing can still stream or sort.
                Fact::estimated(p.keys)
            }),
            Some(Operation::Interleaved { files }) => Fact::exact(*files),
            Some(
                Operation::Assign { groups, .. } | Operation::AssignProbabilistic { groups, .. },
            ) => Fact::exact(groups.len() as u64),
            _ => Fact::exact(1),
        };
        Self {
            version: 2,
            physical_plan: route,
            actual_strategy: Strategy::Existing,
            analysis_status: status,
            native_merge_fan_in: None,
            try_retained_exact: false,
            direct_preflight_fallback: false,
            suggested_max_files: partition
                .filter(|facts| facts.keys_exact)
                .and_then(|facts| suggested_partition_max_files(job, facts.keys, memory_mb)),
            worker_limit_from_analyze,
            input_file_bytes,
            analyzed_rows: matched.map_or_else(Fact::unknown, |hint| Fact::exact(hint.rows)),
            decoded_field_bytes: matched
                .map_or_else(Fact::unknown, |hint| Fact::exact(hint.decoded_field_bytes)),
            largest_decoded_row_bytes: matched.map_or_else(Fact::unknown, |hint| {
                Fact::exact(hint.largest_decoded_row_bytes)
            }),
            partition_joint_keys: partition.map_or_else(Fact::unknown, |p| {
                if p.keys_exact {
                    Fact::exact(p.keys)
                } else {
                    Fact::estimated(p.keys)
                }
            }),
            largest_partition_rows: partition.map_or_else(Fact::unknown, |p| {
                if p.skew_exact {
                    Fact::exact(p.largest_key_bucket_rows)
                } else {
                    Fact::estimated(p.largest_key_bucket_rows)
                }
            }),
            expected_live_fanout,
            root_partition: matches!(job.operations.first(), Some(Operation::Partition { .. })),
            effective_memory_bytes: memory_bytes,
            memory_plan,
            effective_workers: workers,
            effective_grouping: job.resources.grouping,
            validated_rows: Fact::unknown(),
            validated_largest_record_bytes: Fact::unknown(),
            probabilistic_shuffle_attempts: 0,
            probabilistic_shuffle_retries: 0,
            validated_largest_partition_rows: Fact::unknown(),
            validated_root_partitions: Fact::unknown(),
            routing_fallbacks: 0,
            measurements: RunMeasurements::default(),
        }
    }

    pub(super) fn set_native_merge_fan_in(&mut self, ceiling: Option<usize>) {
        self.native_merge_fan_in = ceiling;
    }

    pub(super) fn native_merge_fan_in(&self) -> Option<usize> {
        self.native_merge_fan_in
    }

    pub(super) fn memory_targets_mb(&self) -> [u64; 2] {
        self.memory_plan.map_or([256, 256], |plan| {
            let lower = if plan.target_mb == 2048 && plan.interior_sort_bytes.is_some() {
                1024
            } else {
                256
            };
            [plan.target_mb, lower]
        })
    }

    pub(super) fn automatic_worker_limit(&self) -> usize {
        if self.worker_limit_from_analyze {
            1
        } else {
            usize::MAX
        }
    }

    pub(super) fn finish(
        mut self,
        analysis: &mut Analysis,
        measurements: RunMeasurements,
        direct_strategy: Option<Strategy>,
    ) {
        self.measurements = measurements;
        self.routing_fallbacks = analysis.diagnostics["routing_fallbacks"]
            .as_u64()
            .unwrap_or(0);
        self.effective_memory_bytes = analysis.memory_budget_bytes;
        self.effective_workers = analysis.workers;
        self.validated_rows = Fact::exact(analysis.rows);
        if self.root_partition {
            if let Some(stage) = analysis.stages.first().filter(|stage| stage.operation == 1) {
                self.validated_largest_partition_rows = Fact::exact(stage.largest_group);
                self.validated_root_partitions = Fact::exact(stage.output_groups);
            }
        }
        self.validated_largest_record_bytes = Fact::exact(analysis.largest_record_bytes);
        self.probabilistic_shuffle_attempts = analysis.diagnostics
            ["probabilistic_shuffle_attempts"]
            .as_u64()
            .unwrap_or(0);
        self.probabilistic_shuffle_retries = analysis.diagnostics["probabilistic_shuffle_retries"]
            .as_u64()
            .unwrap_or(0);
        self.actual_strategy = if let Some(strategy) = direct_strategy {
            strategy
        } else if self.probabilistic_shuffle_attempts > self.probabilistic_shuffle_retries {
            Strategy::ProbabilisticShuffleFusion
        } else if analysis.diagnostics["indexed_exact_quota_scopes"]
            .as_u64()
            .unwrap_or(0)
            != 0
        {
            Strategy::IndexedExactQuotaLookup
        } else if measurements.retained_exact_writers {
            Strategy::RetainedExactWriters
        } else if measurements.peak_merge_fan_in > 64 {
            match self.native_merge_fan_in {
                Some(512) if measurements.used_short_tail => Strategy::ShortTailUniformMerge,
                Some(256 | 512) => Strategy::WideUniformMerge,
                _ => Strategy::Existing,
            }
        } else {
            Strategy::Existing
        };
        analysis.auto_plan = Some(self);
    }
}

#[cfg(any(target_os = "linux", target_os = "wasi"))]
pub(super) fn fuse_probabilistic(
    memory: u64,
    workers: usize,
    rows: u64,
    payload_bytes: u64,
    partition: &StageStats,
) -> bool {
    const MIB: u64 = 1024 * 1024;
    if workers != 1 {
        return false;
    }
    if cfg!(target_os = "wasi") {
        return matches!(memory / MIB, 32 | 256)
            && rows >= 40_000
            && payload_bytes >= 4 * MIB
            && (2..=8).contains(&partition.output_groups);
    }
    // Keep Linux at the measured external regime. The narrow 128 MiB
    // comparison does not calibrate a general Linux resident crossover.
    memory == 128 * MIB
        && rows >= 8_000_000
        && payload_bytes >= 1900 * MIB
        && partition.output_groups == 4
        && u128::from(payload_bytes) * u128::from(partition.largest_group)
            >= u128::from(rows) * u128::from(256 * MIB)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(any(target_os = "linux", windows))]
    fn native_routes_keep_declared_caps_and_recheck_ready_headroom() -> anyhow::Result<()> {
        use super::super::direct::Plan;
        const MIB: u64 = 1024 * 1024;
        let source = tempfile::NamedTempFile::new()?;
        source.as_file().set_len(2048 * MIB)?;
        let pool = crate::resources::MemoryPool::new(1024 * MIB);
        let pressured = crate::resources::MemoryPool::new(64 * MIB);
        let mut job = Job {
            input: source.path().to_string_lossy().into_owned(),
            compression: chopper_core::Compression::None,
            resources: chopper_core::Resources {
                max_record_bytes: 128 * 1024,
                max_files: 16,
                memory_mb: 256.into(),
                ..chopper_core::Resources::automatic()
            },
            operations: vec![Operation::Partition {
                columns: vec![chopper_core::Column::Index(0)],
            }],
            ..Job::default()
        };
        assert!(matches!(
            native_direct_candidate(&job, &pool),
            Some(Plan::Fanout {
                chain: false,
                automatic: true
            })
        ));
        assert!(native_direct_candidate(&job, &pressured).is_none());
        let pressured = std::sync::Arc::new(pressured);
        let ctx = super::super::Context::with_memory_pool(
            &job.resources,
            std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false)),
            std::sync::Arc::new(|_| {}),
            pressured,
        )?;
        assert!(!Plan::Fanout {
            chain: false,
            automatic: true
        }
        .ready(&ctx));
        job.resources.max_files = 100_000;
        assert!(native_direct_candidate(&job, &pool).is_none());
        job.resources.max_files = 16;
        job.resources.max_record_bytes *= 2;
        assert!(native_direct_candidate(&job, &pool).is_none());

        job.operations = vec![Operation::Balanced { files: 8 }];
        assert!(matches!(
            native_direct_candidate(&job, &pool),
            Some(Plan::Counted {
                partition: false,
                automatic: true,
                ..
            })
        ));
        job.operations = vec![Operation::Interleaved { files: 8192 }];
        job.resources.max_files = 8192;
        job.resources.max_record_bytes = 4 * 1024;
        assert!(
            native_direct_candidate(&job, &pool).is_none(),
            "explicit memory is binding"
        );

        #[cfg(target_os = "linux")]
        if linux_live_descriptors() >= 8192 {
            let automatic = crate::resources::MemoryPool::new(1024 * MIB);
            job.resources.memory_mb = chopper_core::Resources::automatic().memory_mb;
            assert!(matches!(
                native_direct_candidate(&job, &automatic),
                Some(Plan::BatchedFanout)
            ));
            job.limits.rows = Some(1024);
            assert!(native_direct_candidate(&job, &automatic).is_none());
        }
        Ok(())
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn quota_policy_accounts_for_exact_positions_of_final_quota() {
        let mut quotas = vec![0; 1000];
        quotas[0] = 4_200_000;
        assert!(!use_quota_index(&quotas, 4_200_000));
        quotas[999] = 4_200_000;
        quotas[0] = 0;
        assert!(use_quota_index(&quotas, 4_200_000));
        assert!(!use_quota_index(&quotas, 998));
    }

    #[test]
    fn calibrated_memory_uses_size_then_decoded_rows_without_overriding_explicit_requests() {
        let mut job = Job {
            input: "input.csv".into(),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Auto,
            }],
            resources: Resources::automatic(),
            ..Job::default()
        };
        let narrow = AutoObservations {
            binding: [0; 32],
            rows: 550_000,
            columns: 3,
            decoded_field_bytes: 55 * MIB,
            largest_decoded_row_bytes: 115,
            partition: None,
        };
        for (mb, target) in [(20, 256), (55, 512), (95, 1024), (190, 2048), (500, 256)] {
            let plan = memory_plan(&job, Some(mb * MIB), None, None).unwrap();
            assert_eq!(plan.target_mb, target);
            assert!(!plan.from_analyze);
        }
        let plan = memory_plan(&job, Some(55 * MIB), Some(narrow), None).unwrap();
        assert_eq!(plan.file_size_tier_mb, 512);
        assert_eq!(plan.target_mb, 1024);
        assert!(plan.from_analyze);
        assert_eq!(plan.estimated_sort_bytes.accuracy, Accuracy::Estimated);
        job.input = "input.csv.gz".into();
        assert_eq!(
            memory_plan(&job, Some(MIB), None, None).unwrap().target_mb,
            256
        );
        assert_eq!(
            memory_plan(&job, Some(MIB), Some(narrow), None)
                .unwrap()
                .target_mb,
            1024
        );
        job.operations.insert(
            0,
            Operation::Partition {
                columns: vec![Column::Index(0)],
            },
        );
        assert_eq!(
            memory_plan(&job, None, Some(narrow), None)
                .unwrap()
                .target_mb,
            1024
        );
        job.operations.insert(1, Operation::Balanced { files: 2 });
        assert!(memory_plan(&job, None, Some(narrow), None).is_none());
        job.operations.remove(1);
        job.resources.memory_mb = 768.into();
        assert!(memory_plan(&job, None, Some(narrow), None).is_none());
    }

    #[test]
    fn preview_can_raise_memory_and_out_of_range_analysis_keeps_the_starting_target() {
        let mut job = Job {
            input: "input.csv".into(),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }],
            resources: Resources::automatic(),
            ..Job::default()
        };
        let wide = PreviewObservations {
            max_record_bytes: job.resources.max_record_bytes,
            rows: 8,
            columns: 42,
            decoded_field_bytes: 8 * 320,
        };
        let size = Some(164 * MIB);
        let report = |job: &Job, hint, preview| memory_plan(job, size, hint, preview).unwrap();
        let plan = report(&job, None, Some(wide));
        assert_eq!(plan.file_size_tier_mb, 1024);
        assert_eq!(plan.preview_tier_mb, Some(2048));
        assert_eq!(plan.target_mb, 2048);
        assert_eq!(plan.estimated_sort_bytes.accuracy, Accuracy::Estimated);
        job.input_csv.skip_empty_lines = true;
        assert_eq!(report(&job, None, Some(wide)).preview_tier_mb, None);
        job.input_csv.skip_empty_lines = false;
        job.resources.max_record_bytes /= 2;
        assert_eq!(report(&job, None, Some(wide)).preview_tier_mb, None);
        job.resources.max_record_bytes = wide.max_record_bytes;
        let near_limit = AutoObservations {
            binding: [0; 32],
            rows: 1_700_000,
            columns: 3,
            decoded_field_bytes: 161 * MIB,
            largest_decoded_row_bytes: 900,
            partition: None,
        };
        let plan = report(&job, Some(near_limit), None);
        assert_eq!(plan.target_mb, 2048);
        assert!(plan.from_analyze);
        let outside_range = AutoObservations {
            rows: 3_000_000,
            ..near_limit
        };
        let plan = report(&job, Some(outside_range), None);
        assert!(plan.analyze_outside_range);
        assert_eq!(plan.target_mb, 1024);
        assert_eq!(
            report(&job, Some(outside_range), Some(wide)).target_mb,
            2048
        );
        let smaller = AutoObservations {
            rows: 100_000,
            ..near_limit
        };
        assert_eq!(report(&job, Some(smaller), Some(wide)).target_mb, 1024);
    }

    #[test]
    fn interior_width_probe_ignores_partial_rows_and_declines_quoted_windows() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let input = directory.path().join("probe.csv");
        let simple = "1,2,payload\n".repeat(60_000);
        std::fs::write(&input, &simple)?;
        let bytes = simple.len() as u64;
        let estimate = interior_sort_estimate(&input, bytes, 3).unwrap();
        assert_eq!(estimate, bytes * (12 + 200 + 21) / 12);
        assert_eq!(interior_sort_estimate(&input, bytes, 2), None);
        let quoted = simple.replace("payload", "\"a\nb\"");
        std::fs::write(&input, &quoted)?;
        assert_eq!(interior_sort_estimate(&input, quoted.len() as u64, 3), None);
        Ok(())
    }

    #[test]
    fn linux_merge_rule_uses_matching_shape_and_bounded_footprint() {
        let mut job = Job {
            input: "input.csv".into(),
            operations: vec![Operation::Shuffle {
                strategy: Shuffle::Uniform,
            }],
            resources: Resources::automatic(),
            ..Job::default()
        };
        let mut hint = AutoObservations {
            binding: [0; 32],
            rows: 4_200_000,
            columns: 3,
            decoded_field_bytes: 4_200_000 * 1021,
            largest_decoded_row_bytes: 1021,
            partition: None,
        };
        assert_eq!(linux_merge_memory_plan(&job, hint).unwrap().target_mb, 384);
        job.resources.memory_mb = 512.into();
        assert!(linux_merge_memory_plan(&job, hint).is_none());
        job.resources.memory_mb = chopper_core::MemoryBudget::Auto;
        hint.rows /= 2;
        hint.decoded_field_bytes /= 2;
        assert!(linux_merge_memory_plan(&job, hint).is_none());
        hint.rows *= 4;
        hint.decoded_field_bytes *= 4;
        assert!(linux_merge_memory_plan(&job, hint).is_none());
    }

    fn fixture() -> Result<(tempfile::TempDir, Job)> {
        let dir = tempfile::tempdir()?;
        let input = dir.path().join("input.csv");
        std::fs::write(&input, "a,b,value\nx,y,abc\nx,y,def\nz,w,large\n")?;
        let job = Job {
            input: input.to_string_lossy().into_owned(),
            output: dir.path().join("out").to_string_lossy().into_owned(),
            operations: vec![Operation::Partition {
                columns: vec![
                    chopper_core::Column::Index(0),
                    chopper_core::Column::Index(1),
                ],
            }],
            resources: Resources {
                memory_mb: chopper_core::MemoryBudget::MiB(32),
                workers: 1,
                max_record_bytes: 1024 * 1024,
                ..Resources::default()
            },
            ..Job::default()
        };
        Ok((dir, job))
    }

    #[test]
    fn run_without_analyze_validates_and_reports_physical_work() -> Result<()> {
        let (_dir, job) = fixture()?;
        let report = run(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let plan = report.auto_plan.unwrap();
        assert_eq!(plan.analysis_status, Advice::Absent);
        assert_eq!(plan.analyzed_rows, Fact::unknown());
        assert_eq!(plan.validated_rows, Fact::exact(3));
        assert_eq!(plan.validated_largest_partition_rows, Fact::exact(2));
        assert_eq!(plan.effective_workers, 1);
        assert_eq!(plan.effective_memory_bytes, 32 * 1024 * 1024);
        assert!(matches!(
            plan.physical_plan,
            Route::Snapshot | Route::PrivateTerminal
        ));
        assert!(plan.measurements.temporary_bytes_read > 0);
        Ok(())
    }

    #[test]
    #[cfg(not(windows))]
    fn analyze_binds_rows_widths_and_joint_keys_to_input_and_parser() -> Result<()> {
        let (_dir, mut job) = fixture()?;
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let cancel = Arc::new(AtomicBool::new(false));
        let notify: Notify = Arc::new(|_| {});
        let observations = crate::profile::ProfileCache::with_memory_pool(pool.clone())
            .profile(&job, cancel.clone(), notify.clone())?
            .auto_observations
            .unwrap();
        let plan = AutoPlan::start(&job, &pool, Some(observations), Route::Snapshot, None);
        assert_eq!(plan.analysis_status, Advice::Matched);
        assert_eq!(plan.analyzed_rows, Fact::exact(3));
        assert_eq!(plan.decoded_field_bytes, Fact::exact(17));
        assert_eq!(plan.largest_decoded_row_bytes, Fact::exact(7));
        assert_eq!(plan.partition_joint_keys, Fact::estimated(2));
        assert_eq!(plan.largest_partition_rows, Fact::estimated(2));
        assert_eq!(plan.expected_live_fanout, Fact::estimated(2));

        job.operations.clear();
        let changed_operations =
            AutoPlan::start(&job, &pool, Some(observations), Route::Streaming, None);
        assert_eq!(changed_operations.analyzed_rows, Fact::exact(3));
        assert_eq!(changed_operations.partition_joint_keys, Fact::unknown());

        job.input_csv.delimiter = ';';
        let changed_parser =
            AutoPlan::start(&job, &pool, Some(observations), Route::Streaming, None);
        assert_eq!(changed_parser.analysis_status, Advice::Unverified);
        job.input_csv.delimiter = ',';
        std::fs::write(&job.input, "bad CSV\n\x22unterminated")?;
        let changed_input =
            AutoPlan::start(&job, &pool, Some(observations), Route::Streaming, None);
        assert_eq!(changed_input.analysis_status, Advice::Unverified);
        let output = job.output.clone();
        assert!(run_with_auto(job, cancel, notify, pool, Some(observations)).is_err());
        assert!(!std::path::Path::new(&output).exists());
        Ok(())
    }

    #[test]
    #[cfg(target_os = "linux")]
    fn linux_fusion_gate_uses_retained_partition_stats() {
        let mib = 1024 * 1024;
        let partition = StageStats {
            operation: 1,
            input_groups: 1,
            output_groups: 4,
            smallest_group: 2_000_000,
            largest_group: 2_000_000,
            empty_groups: 0,
        };
        assert!(fuse_probabilistic(
            128 * mib,
            1,
            8_000_000,
            1900 * mib,
            &partition
        ));
        assert!(!fuse_probabilistic(
            128 * mib,
            2,
            8_000_000,
            1900 * mib,
            &partition
        ));
        assert!(!fuse_probabilistic(
            256 * mib,
            1,
            8_000_000,
            1900 * mib,
            &partition
        ));
        assert!(!fuse_probabilistic(
            128 * mib,
            1,
            8_000_000,
            1024 * mib,
            &partition
        ));
    }
}
