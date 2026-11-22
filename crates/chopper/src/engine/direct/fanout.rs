//! Bounded configured fanout with original count-independent membership.
use super::*;
pub(super) mod chains;
#[cfg(not(target_os = "wasi"))]
mod partition;
mod writers;
pub(in crate::engine) use writers::Writers;

fn writer_limit(job: &Job) -> usize {
    if !cfg!(feature = "experimental-memory-final-writers") {
        return crate::engine::auto::descriptor_writer_ceiling(2).min(16);
    }
    // Selection precedes automatic memory resolution. Its minimum valid budget
    // keeps this advisory cap conservative; every allocation still needs a grant.
    let memory_mb = job.resources.memory_mb.as_mib().unwrap_or(32);
    let one_descriptor = cfg!(feature = "experimental-single-catalog-capacity")
        && job.limits.rows.is_none()
        && job.limits.bytes.is_none()
        && job.limits.compressed_bytes.is_none();
    let (per_mib, maximum) = if one_descriptor {
        (16, 16384)
    } else if cfg!(feature = "experimental-small-final-buffers") {
        (8, 8192)
    } else {
        (4, 4096)
    };
    let limit = memory_mb.saturating_mul(per_mib).min(maximum) as usize;
    #[cfg(all(unix, not(target_os = "wasi")))]
    let limit = limit.min(crate::engine::auto::descriptor_writer_ceiling(
        if one_descriptor { 1 } else { 2 },
    ));
    limit
}

pub(super) fn writer_capacity(job: &Job) -> Option<usize> {
    (cfg!(all(
        feature = "experimental-final-writers",
        not(target_os = "wasi")
    )) && job.resources.grouping == chopper_core::Grouping::Auto
        && job.compression == chopper_core::Compression::None)
        .then(|| writer_limit(job))
}

pub(super) fn partition_eligible(job: &Job) -> bool {
    cfg!(feature = "experimental-bounded-final-partition")
        && matches!(job.operations.as_slice(), [Operation::Partition { .. }])
        && writer_capacity(job).is_some_and(|limit| job.resources.max_files <= limit as u64)
}

pub(super) fn eligible(job: &Job) -> bool {
    partition_eligible(job)
        || (cfg!(all(
            feature = "experimental-final-writers",
            not(target_os = "wasi")
        )) && job.resources.grouping == chopper_core::Grouping::Auto
            && job.compression == chopper_core::Compression::None
            && matches!(job.operations.as_slice(), [operation] if match operation {
                Operation::Interleaved { files } => *files <= writer_limit(job) as u64,
                Operation::AssignProbabilistic { groups, .. } => groups.len() <= writer_limit(job),
                _ => false,
            }))
}

// Keep admitted owners inline rather than introducing an uncharged box.
#[allow(clippy::large_enum_variant)]
enum Selection<'a> {
    Configured(streaming::Membership<'a>),
    #[cfg(not(target_os = "wasi"))]
    Partition(partition::Partition<'a>),
}

pub(super) struct Fanout<'a> {
    writers: Writers<'a>,
    selection: Selection<'a>,
}
impl<'a> Fanout<'a> {
    pub(super) fn new(
        job: &'a Job,
        header: Option<&Header>,
        width: usize,
        ctx: &'a Context,
    ) -> Result<Self> {
        #[cfg(not(target_os = "wasi"))]
        if matches!(job.operations.as_slice(), [Operation::Partition { .. }]) {
            // Run already selected the bounded shape. A later descriptor-limit
            // change may fail an open, but must not select another membership.
            let (partition, writers) = partition::Partition::new(job, header, width, ctx)?;
            return Ok(Self {
                writers,
                selection: Selection::Partition(partition),
            });
        }
        let membership = streaming::Membership::new(
            &job.operations[0],
            header.map(|h| &h[..]),
            width,
            random::domain(job.random_seed.as_deref().unwrap(), 0, "[]"),
            ctx,
        )?;
        let mut writers = Writers::new(job, ctx, membership.counts().len())?;
        let parent = Group {
            offset: 0,
            rows: 0,
            lineage: vec![],
            exact: false,
        };
        // Admit every configured group's catalog/header before emitting data.
        for index in 0..membership.counts().len() {
            let group = group_metadata::ClonedGroup::child(
                &parent,
                &membership.entry(0, index),
                ctx,
                |lineage| Group {
                    offset: 0,
                    rows: 0,
                    lineage,
                    exact: membership.exact(),
                },
            )?;
            writers.push(header, group)?;
        }
        Ok(Self {
            writers,
            selection: Selection::Configured(membership),
        })
    }
    pub(super) fn row(&mut self, id: u64, fields: FieldViews<'_>) -> Result<()> {
        match &mut self.selection {
            Selection::Configured(membership) => {
                let index = membership.index(id, fields.clone());
                self.writers.row(index, id, fields)
            }
            #[cfg(not(target_os = "wasi"))]
            Selection::Partition(partition) => partition.row(&mut self.writers, id, fields),
        }
    }
    pub(super) fn finish(self) -> Result<(output::DirectPublication, u64, u64, StageStats)> {
        match self.selection {
            Selection::Configured(membership) => {
                membership.validate_seen(membership.seen())?;
                let stats = StageStats {
                    operation: 1,
                    input_groups: 1,
                    output_groups: membership.counts().len() as u64,
                    smallest_group: *membership.counts().iter().min().unwrap(),
                    largest_group: *membership.counts().iter().max().unwrap(),
                    empty_groups: membership.counts().iter().filter(|n| **n == 0).count() as u64,
                };
                let (publication, files, bytes) = self.writers.finish()?;
                Ok((publication, files, bytes, stats))
            }
            #[cfg(not(target_os = "wasi"))]
            Selection::Partition(partition) => partition.finish(self.writers),
        }
    }
}

#[cfg(all(
    test,
    feature = "experimental-single-catalog-capacity",
    not(target_os = "wasi")
))]
mod capacity_tests {
    use super::*;
    #[test]
    fn cap_is_finite_and_chunk_caps_keep_the_previous_selector() {
        let mut job = Job {
            resources: chopper_core::Resources {
                memory_mb: 1024.into(),
                ..Default::default()
            },
            operations: vec![Operation::Interleaved { files: 16385 }],
            ..Default::default()
        };
        assert!(writer_limit(&job) <= 16384);
        assert!(!eligible(&job));
        job.resources.memory_mb = 32.into();
        assert!(writer_limit(&job) <= 512);
        for cap in ["rows", "bytes", "compressed"] {
            let mut capped = job.clone();
            match cap {
                "rows" => capped.limits.rows = Some(1000),
                "bytes" => capped.limits.bytes = Some(1000),
                _ => capped.limits.compressed_bytes = Some(1000),
            }
            assert!(writer_limit(&capped) <= 256, "{cap}");
            capped.operations = vec![Operation::Interleaved { files: 257 }];
            assert!(!eligible(&capped), "{cap}");
        }
    }
}
