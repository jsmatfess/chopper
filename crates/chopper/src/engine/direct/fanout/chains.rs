//! Bounded count-independent membership tree with original per-parent domains.
use super::*;

pub(in crate::engine) fn eligible(job: &Job) -> bool {
    cfg!(all(
        feature = "experimental-final-writer-chains",
        not(target_os = "wasi")
    )) && job.compression == chopper_core::Compression::None
        && job.resources.grouping == chopper_core::Grouping::Auto
        && (2..=4).contains(&job.operations.len())
        && job
            .operations
            .iter()
            .try_fold(1usize, |product, operation| {
                let count = match operation {
                    Operation::Interleaved { files } => usize::try_from(*files).ok()?,
                    Operation::AssignProbabilistic { groups, .. } => groups.len(),
                    _ => return None,
                };
                product
                    .checked_mul(count)
                    .filter(|product| *product <= writer_limit(job))
            })
            .is_some()
}

struct Level<'a> {
    members: Vec<streaming::Membership<'a>>,
    fanout: usize,
    _memory: Reservation,
}
pub(in crate::engine) struct Chains<'a> {
    writers: Writers<'a>,
    levels: Vec<Level<'a>>,
    _levels: Reservation,
}
impl<'a> Chains<'a> {
    pub(in crate::engine) fn new(
        job: &'a Job,
        header: Option<&Header>,
        width: usize,
        ctx: &'a Context,
    ) -> Result<Self> {
        let root = Group {
            offset: 0,
            rows: 0,
            lineage: vec![],
            exact: false,
        };
        let mut parent_memory = Reservation::new(ctx);
        let mut parents = Vec::new();
        parent_memory.reserve_vec(&mut parents, 1)?;
        parents.push(group_metadata::ClonedGroup::build(
            &root,
            Reservation::new(ctx),
            |group| group,
        )?);
        let mut level_memory = Reservation::new(ctx);
        let mut levels = Vec::new();
        level_memory.reserve_vec(&mut levels, job.operations.len())?;
        for (step, operation) in job.operations.iter().enumerate() {
            let fanout = match operation {
                Operation::Interleaved { files } => usize::try_from(*files)?,
                Operation::AssignProbabilistic { groups, .. } => groups.len(),
                _ => unreachable!("bounded membership tree eligibility"),
            };
            let mut memory = Reservation::new(ctx);
            let mut members = Vec::new();
            memory.reserve_vec(&mut members, parents.len())?;
            let mut child_memory = Reservation::new(ctx);
            let mut children = Vec::new();
            child_memory.reserve_vec(
                &mut children,
                parents
                    .len()
                    .checked_mul(fanout)
                    .context("fanout overflow")?,
            )?;
            for parent in &parents {
                let member = streaming::Membership::new(
                    operation,
                    header.map(|h| &h[..]),
                    width,
                    random::json_domain(
                        job.random_seed.as_deref().unwrap(),
                        step as u64,
                        &parent.group.lineage,
                    )?,
                    ctx,
                )?;
                for index in 0..fanout {
                    children.push(group_metadata::ClonedGroup::child(
                        &parent.group,
                        &member.entry(step, index),
                        ctx,
                        |lineage| Group {
                            offset: 0,
                            rows: 0,
                            lineage,
                            exact: member.exact(),
                        },
                    )?);
                }
                members.push(member);
            }
            levels.push(Level {
                members,
                fanout,
                _memory: memory,
            });
            // Release each old lineage before its Vec grant; children own their
            // independently admitted immutable lineage clones.
            parents = children;
            parent_memory = child_memory;
        }
        let mut writers = Writers::new(job, ctx, parents.len())?;
        for group in parents {
            writers.push(header, group)?;
        }
        drop(parent_memory);
        Ok(Self {
            writers,
            levels,
            _levels: level_memory,
        })
    }

    pub(in crate::engine) fn row(&mut self, id: u64, fields: FieldViews<'_>) -> Result<()> {
        let mut parent = 0;
        for level in &mut self.levels {
            let index = level.members[parent].index(id, fields.clone());
            parent = parent * level.fanout + index;
        }
        self.writers.row(parent, id, fields)
    }

    pub(in crate::engine) fn finish(
        self,
        stages: &mut Stages,
    ) -> Result<(output::DirectPublication, u64, u64, u64)> {
        for (step, level) in self.levels.iter().enumerate() {
            let mut smallest = u64::MAX;
            let mut largest = 0;
            let mut empty = 0;
            for member in &level.members {
                member.validate_seen(member.seen())?;
                for count in member.counts() {
                    smallest = smallest.min(*count);
                    largest = largest.max(*count);
                    empty += u64::from(*count == 0);
                }
            }
            stages.push(StageStats {
                operation: step + 1,
                input_groups: level.members.len() as u64,
                output_groups: (level.members.len() * level.fanout) as u64,
                smallest_group: smallest,
                largest_group: largest,
                empty_groups: empty,
            })?;
        }
        let groups = self.writers.len() as u64;
        let (publication, files, bytes) = self.writers.finish()?;
        Ok((publication, files, bytes, groups))
    }
}
