//! The declared physical-file ceiling also bounds all distinct value groups.
use super::*;
use std::collections::BTreeMap;

// A full internal-node envelope per entry, including split headroom. Keys own
// their independently counted Vec capacities; no hash stands in for equality.
const NODE_BYTES: usize = 16
    * (std::mem::size_of::<Vec<u8>>()
        + std::mem::size_of::<usize>()
        + std::mem::size_of::<usize>())
    + 4 * std::mem::size_of::<usize>();

pub(super) struct Partition<'a> {
    keys: BTreeMap<Vec<u8>, usize>,
    columns: Vec<usize>,
    key: keys::TupleBuffer,
    header: Option<Header>,
    publication: output::DirectPublication,
    // Destroy map keys/nodes and columns before returning their aggregate grant.
    memory: Reservation,
    ctx: &'a Context,
}
impl<'a> Partition<'a> {
    pub(super) fn new(
        job: &'a Job,
        header: Option<&Header>,
        width: usize,
        ctx: &'a Context,
    ) -> Result<(Self, Writers<'a>)> {
        let Operation::Partition { columns: requested } = &job.operations[0] else {
            unreachable!("bounded partition shape");
        };
        let mut memory = Reservation::new(ctx);
        let mut columns = Vec::new();
        memory.reserve_vec(&mut columns, requested.len())?;
        for column in requested {
            columns.push(resolve_column(column, header.map(|h| &h[..]), width)?);
        }
        let publication = output::DirectPublication::grouped(job, header, ctx)?;
        let writers = Writers::new(job, ctx, usize::try_from(job.resources.max_files)?)?;
        Ok((
            Self {
                keys: BTreeMap::new(),
                columns,
                key: keys::TupleBuffer::new(Reservation::new(ctx)),
                header: header.cloned(),
                publication,
                memory,
                ctx,
            },
            writers,
        ))
    }

    pub(super) fn row(
        &mut self,
        writers: &mut Writers<'a>,
        id: u64,
        fields: FieldViews<'_>,
    ) -> Result<()> {
        self.key.replace(fields.clone(), &self.columns)?;
        let index = if let Some(&index) = self.keys.get(self.key.bytes()) {
            index
        } else {
            ensure!(
                (writers.len() as u64) < self.ctx.max_files,
                "output count exceeds max_files"
            );
            self.memory.resize(
                (self.memory.bytes() as usize)
                    .checked_add(NODE_BYTES)
                    .context("partition catalog capacity overflow")?,
            )?;
            let mut key = Vec::new();
            self.memory.reserve_vec(&mut key, self.key.bytes().len())?;
            key.extend_from_slice(self.key.bytes());
            let parent = Group {
                offset: 0,
                rows: 0,
                lineage: vec![],
                exact: false,
            };
            let group = group_metadata::ClonedGroup::child(
                &parent,
                &child_metadata::Entry::values(0, fields.clone(), &self.columns),
                self.ctx,
                |lineage| Group {
                    offset: 0,
                    rows: 0,
                    lineage,
                    exact: false,
                },
            )?;
            let index = writers.len();
            writers.push(self.header.as_ref(), group)?;
            self.keys.insert(key, index);
            index
        };
        writers.row(index, id, fields)
    }

    pub(super) fn finish(
        self,
        writers: Writers<'a>,
    ) -> Result<(output::DirectPublication, u64, u64, StageStats)> {
        let stats = writers.statistics();
        let Self {
            keys,
            columns,
            key,
            header,
            publication,
            memory,
            ..
        } = self;
        drop(columns);
        drop(key);
        drop(header);
        // Escaped tuple bytes have the original sort order. IntoValues owns and
        // destroys every map node/key before this call returns its grant.
        let result = writers.finish_in_order(Some(publication), keys.into_values());
        drop(memory);
        let (publication, files, bytes) = result?;
        Ok((publication, files, bytes, stats))
    }
}
