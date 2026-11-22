//! Admitted bounded writers sharing caps, row scratch and one publication witness.
use super::*;

struct Output<'a> {
    writer: output::PlanWriter<'a>,
    group: group_metadata::ClonedGroup,
}
pub(in crate::engine) struct Writers<'a> {
    entries: Vec<Option<Output<'a>>>,
    serializer: chopper_core::csv::Serializer,
    _serialization: Reservation,
    _memory: Reservation,
    maximum: usize,
    opened_files: u64,
    job: &'a Job,
    ctx: &'a Context,
}
impl<'a> Writers<'a> {
    pub(in crate::engine) fn new(job: &'a Job, ctx: &'a Context, count: usize) -> Result<Self> {
        // On construction failure, drop entries before returning their grant.
        let mut memory = Reservation::new(ctx);
        let mut entries = Vec::new();
        memory.reserve_vec(&mut entries, count)?;
        Ok(Self {
            entries,
            serializer: chopper_core::csv::Serializer::new(&job.output_csv)?,
            _serialization: Reservation::new(ctx),
            _memory: memory,
            maximum: count,
            opened_files: 0,
            job,
            ctx,
        })
    }
    pub(in crate::engine) fn push(
        &mut self,
        header: Option<&Header>,
        group: group_metadata::ClonedGroup,
    ) -> Result<()> {
        ensure!(
            self.entries.len() < self.maximum,
            "bounded writer capacity exceeded"
        );
        let single_chunk = group.group.exact
            || (self.job.limits.rows.is_none()
                && self.job.limits.bytes.is_none()
                && self.job.limits.compressed_bytes.is_none());
        let mut writer =
            output::PlanWriter::direct_fanout(self.job, header, self.ctx, single_chunk)?;
        if self.ctx.auto_final_writers
            || cfg!(feature = "experimental-release-final-header-scratch")
        {
            writer.release_serialization_scratch()?;
        }
        self.entries.push(Some(Output { writer, group }));
        self.ctx.bounded_writer_slots(self.entries.len());
        Ok(())
    }
    pub(in crate::engine) fn len(&self) -> usize {
        self.entries.len()
    }
    pub(in crate::engine) fn row(
        &mut self,
        index: usize,
        seen: u64,
        fields: FieldViews<'_>,
    ) -> Result<()> {
        let output = self
            .entries
            .get_mut(index)
            .and_then(Option::as_mut)
            .context("invalid bounded writer index")?;
        output.writer.continue_progress_at(seen);
        output
            .writer
            .allow_additional_files(self.ctx.max_files - self.opened_files)?;
        let before = output.writer.files();
        if self.ctx.auto_final_writers || cfg!(feature = "experimental-shared-final-serializer") {
            self.serializer
                .serialize_fields_reserved(fields, &mut |bytes| {
                    self._serialization.resize(bytes)
                })?;
            output
                .writer
                .write_serialized(&mut output.group.group, &self.serializer)?;
        } else {
            output
                .writer
                .write_fields(&mut output.group.group, fields)?;
        }
        self.opened_files += output.writer.files() - before;
        Ok(())
    }
    pub(in crate::engine) fn finish(self) -> Result<(output::DirectPublication, u64, u64)> {
        let count = self.entries.len();
        self.finish_in_order(None, 0..count)
    }
    pub(in crate::engine) fn statistics(&self) -> StageStats {
        let mut smallest = u64::MAX;
        let mut largest = 0;
        let mut empty = 0;
        for output in self.entries.iter().flatten() {
            let rows = output.group.group.rows;
            smallest = smallest.min(rows);
            largest = largest.max(rows);
            empty += u64::from(rows == 0);
        }
        StageStats {
            operation: 1,
            input_groups: 1,
            output_groups: self.entries.len() as u64,
            smallest_group: if self.entries.is_empty() { 0 } else { smallest },
            largest_group: largest,
            empty_groups: empty,
        }
    }
    pub(in crate::engine) fn finish_in_order(
        mut self,
        mut publication: Option<output::DirectPublication>,
        order: impl IntoIterator<Item = usize>,
    ) -> Result<(output::DirectPublication, u64, u64)> {
        let mut files = 0;
        let mut bytes = 0u64;
        let mut opened = self.opened_files;
        for index in order {
            let Output { mut writer, group } = self
                .entries
                .get_mut(index)
                .and_then(Option::take)
                .context("invalid bounded writer order")?;
            writer.allow_additional_files(self.ctx.max_files - opened)?;
            let before = writer.files();
            writer.end_group(&group.group)?;
            opened += writer.files() - before;
            let (mut part, part_files, size) = writer.finish_direct()?;
            bytes = bytes.checked_add(size).context("output size overflow")?;
            if let Some(publication) = &mut publication {
                publication.append_group(part, &group.group, &mut files, self.job, self.ctx)?;
            } else {
                // Local first-group indices are already canonical. Preserve its
                // original destination witness through final directory commit.
                part.materialize_group_records(&group.group, self.ctx)?;
                files = part_files;
                publication = Some(part);
            }
        }
        ensure!(
            self.entries.iter().all(Option::is_none),
            "unfinished bounded writers"
        );
        let mut publication = publication.context("missing bounded output writers")?;
        publication.seal()?;
        // Preserve the existing Analysis boundary: all buffers have flushed,
        // then every original handle is synced before returning final counts.
        publication.sync_pending(self.ctx)?;
        Ok((publication, files, bytes))
    }
}
