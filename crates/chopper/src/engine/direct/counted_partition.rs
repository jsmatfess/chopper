//! Count exact Partition parents, then stream consecutive Balanced quotas.
use super::*;

#[derive(Default)]
struct Parent {
    rows: u64,
    seen: u64,
    first_writer: Option<usize>,
}

pub(super) struct Counts {
    parents: Vec<(Vec<u8>, Parent)>,
    columns: Vec<usize>,
    key: keys::TupleBuffer,
    memory: Reservation,
    parts: u64,
    max_parents: u64,
}

impl Counts {
    pub(super) fn new(
        job: &Job,
        header: Option<&Header>,
        width: usize,
        ctx: &Context,
    ) -> Result<Self> {
        let [Operation::Partition { columns }, Operation::Balanced { files }] =
            job.operations.as_slice()
        else {
            unreachable!("counted Partition and Balanced shape");
        };
        let mut memory = Reservation::new(ctx);
        let mut indices = Vec::new();
        memory.reserve_vec(&mut indices, columns.len())?;
        for column in columns {
            indices.push(resolve_column(column, header.map(|h| &h[..]), width)?);
        }
        Ok(Self {
            parents: Vec::new(),
            columns: indices,
            key: keys::TupleBuffer::new(Reservation::new(ctx)),
            memory,
            parts: *files,
            max_parents: job.resources.max_files / files,
        })
    }

    pub(super) fn count<'a>(
        &mut self,
        fields: impl Iterator<Item = &'a str> + Clone,
    ) -> Result<()> {
        self.key.replace(fields, &self.columns)?;
        let index = match self.find() {
            Ok(index) => index,
            Err(index) => {
                ensure!(
                    (self.parents.len() as u64) < self.max_parents,
                    "output count exceeds max_files"
                );
                if self.parents.len() == self.parents.capacity() {
                    let capacity = (self.parents.len().max(1) * 2).min(self.max_parents as usize);
                    self.memory.reserve_vec(&mut self.parents, capacity)?;
                }
                let mut key = Vec::new();
                self.memory.reserve_vec(&mut key, self.key.bytes().len())?;
                key.extend_from_slice(self.key.bytes());
                self.parents.insert(index, (key, Parent::default()));
                index
            }
        };
        let parent = &mut self.parents[index].1;
        parent.rows = parent.rows.checked_add(1).context("row count overflow")?;
        Ok(())
    }

    fn find(&self) -> std::result::Result<usize, usize> {
        self.parents
            .binary_search_by(|(key, _)| key.as_slice().cmp(self.key.bytes()))
    }

    pub(super) fn validate(&self) -> Result<()> {
        for (_, parent) in &self.parents {
            ensure!(
                parent.rows >= self.parts,
                "cannot split {} rows into {} nonempty balanced groups",
                parent.rows,
                self.parts
            );
        }
        Ok(())
    }
}

pub(super) struct Emit<'a> {
    counts: Counts,
    writers: Writers<'a>,
    publication: output::DirectPublication,
    header: Option<Header>,
    ctx: &'a Context,
}

impl<'a> Emit<'a> {
    pub(super) fn new(
        counts: Counts,
        job: &'a Job,
        header: Option<&Header>,
        ctx: &'a Context,
    ) -> Result<Self> {
        let capacity = counts.parents.len() * usize::try_from(counts.parts)?;
        Ok(Self {
            counts,
            writers: Writers::new(job, ctx, capacity)?,
            publication: output::DirectPublication::grouped(job, header, ctx)?,
            header: header.cloned(),
            ctx,
        })
    }

    pub(super) fn row(&mut self, seen: u64, fields: FieldViews<'_>) -> Result<()> {
        self.counts
            .key
            .replace(fields.clone(), &self.counts.columns)?;
        let index = self
            .counts
            .find()
            .map_err(|_| anyhow::anyhow!("input partition keys changed after counting"))?;
        let parent = &mut self.counts.parents[index].1;
        ensure!(
            parent.seen < parent.rows,
            "input partition row count changed after counting"
        );
        let first = if let Some(first) = parent.first_writer {
            first
        } else {
            let root = empty_group(Vec::new(), false);
            let partition = group_metadata::ClonedGroup::child(
                &root,
                &child_metadata::Entry::values(0, fields.clone(), &self.counts.columns),
                self.ctx,
                |lineage| empty_group(lineage, false),
            )?;
            let first = self.writers.len();
            for part in 1..=self.counts.parts {
                let group = group_metadata::ClonedGroup::child(
                    &partition.group,
                    &child_metadata::Entry::part(1, part),
                    self.ctx,
                    |lineage| empty_group(lineage, true),
                )?;
                self.writers.push(self.header.as_ref(), group)?;
            }
            parent.first_writer = Some(first);
            first
        };
        let quota = parent.rows / self.counts.parts;
        let extra = parent.rows % self.counts.parts;
        let early_rows = if extra == 0 { 0 } else { (quota + 1) * extra };
        let part = if parent.seen < early_rows {
            parent.seen / (quota + 1)
        } else {
            extra + (parent.seen - early_rows) / quota
        };
        self.writers.row(first + part as usize, seen, fields)?;
        parent.seen += 1;
        Ok(())
    }

    pub(super) fn finish(
        self,
        stages: &mut Stages,
    ) -> Result<(output::DirectPublication, u64, u64, u64)> {
        let parents = &self.counts.parents;
        let parts = self.counts.parts;
        let parent_count = parents.len() as u64;
        for (_, parent) in parents {
            ensure!(
                parent.seen == parent.rows,
                "input partition row count changed after counting"
            );
        }
        let smallest = parents
            .iter()
            .map(|(_, parent)| parent.rows)
            .min()
            .unwrap_or(0);
        let largest = parents
            .iter()
            .map(|(_, parent)| parent.rows)
            .max()
            .unwrap_or(0);
        let groups = parent_count * parts;
        stages.push(StageStats {
            operation: 1,
            input_groups: 1,
            output_groups: parent_count,
            smallest_group: smallest,
            largest_group: largest,
            empty_groups: 0,
        })?;
        stages.push(StageStats {
            operation: 2,
            input_groups: parent_count,
            output_groups: groups,
            smallest_group: smallest / parts,
            largest_group: largest.div_ceil(parts),
            empty_groups: 0,
        })?;
        let order = parents.iter().flat_map(|(_, parent)| {
            let first = parent
                .first_writer
                .expect("all counted parents were emitted");
            first..first + parts as usize
        });
        let (publication, files, bytes) = self
            .writers
            .finish_in_order(Some(self.publication), order)?;
        Ok((publication, files, bytes, groups))
    }
}

fn empty_group(lineage: Vec<serde_json::Value>, exact: bool) -> Group {
    Group {
        offset: 0,
        rows: 0,
        lineage,
        exact,
    }
}
