//! Writer lifetime and successful commitment for selected retained-data spans.
//! Selection and each caller's retry rules remain outside this module.
use super::*;

#[derive(Debug)]
pub(super) enum Failure {
    Setup(anyhow::Error),
    Execution(anyhow::Error),
}
impl Failure {
    #[cfg(any(
        test,
        feature = "resource-contract-tests",
        feature = "experimental-streaming-chain"
    ))]
    pub fn is_setup(&self) -> bool {
        matches!(self, Self::Setup(_))
    }
    pub fn error(&self) -> &anyhow::Error {
        match self {
            Self::Setup(error) | Self::Execution(error) => error,
        }
    }
    pub fn into_error(self) -> anyhow::Error {
        match self {
            Self::Setup(error) | Self::Execution(error) => error,
        }
    }
}

// Keep the real writers inline: boxing would introduce an unadmitted allocation.
#[allow(clippy::large_enum_variant)]
pub(super) enum Writer<'a> {
    Dataset(DatasetWriter),
    Final(output::PlanWriter<'a>),
}
impl Writer<'_> {
    fn finish(self) -> Result<Output> {
        match self {
            Self::Dataset(writer) => Ok(Output::Dataset(writer.finish()?)),
            Self::Final(writer) => Ok(Output::Final(writer.finish()?)),
        }
    }
}
impl RowSink for Writer<'_> {
    fn physical_input(&mut self, source: Option<u32>) {
        match self {
            Self::Dataset(writer) => writer.physical_input(source),
            Self::Final(writer) => writer.physical_input(source),
        }
    }
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        match self {
            Self::Dataset(writer) => writer.begin(lineage, exact),
            Self::Final(writer) => writer.begin(lineage, exact),
        }
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        match self {
            Self::Dataset(writer) => writer.row(group, row),
            Self::Final(writer) => writer.row(group, row),
        }
    }
    fn packed_row(&mut self, group: &mut Group, row: PackedRow) -> Result<()> {
        match self {
            Self::Dataset(writer) => writer.packed_row(group, row),
            Self::Final(writer) => writer.packed_row(group, row),
        }
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        match self {
            Self::Dataset(writer) => writer.packed_row_ref(group, row),
            Self::Final(writer) => writer.packed_row_ref(group, row),
        }
    }
    fn end(&mut self, group: Group) -> Result<()> {
        match self {
            Self::Dataset(writer) => writer.end(group),
            Self::Final(writer) => writer.end(group),
        }
    }
}
enum Output {
    Dataset(Dataset),
    Final(output::OutputPlan),
}

pub(super) struct Completed<S> {
    output: Output,
    stats: S,
    consumed: usize,
}
impl<S> Completed<S> {
    /// Statistics retain their existing bounded representation and append logic.
    /// Drop the previous dataset only after that admitted append succeeds.
    pub fn commit(
        self,
        dataset: &mut Dataset,
        final_plan: &mut Option<output::OutputPlan>,
        analysis: &mut Analysis,
        index: &mut usize,
        append: impl FnOnce(S, &mut Analysis) -> Result<()>,
    ) -> Result<()> {
        append(self.stats, analysis)?;
        match self.output {
            Output::Dataset(result) => *dataset = result,
            Output::Final(output) => *final_plan = Some(output),
        }
        *index += self.consumed;
        Ok(())
    }
}

/// Declining an optimization drops its tentative writer without finalizing or
/// committing. Streaming callers can distinguish setup from all later errors.
pub(super) fn execute<'a, S>(
    job: &'a Job,
    analysis: &'a Analysis,
    ctx: &'a Context,
    index: usize,
    consumed: usize,
    apply: impl FnOnce(&mut Writer<'a>) -> Result<Option<S>>,
) -> std::result::Result<Option<Completed<S>>, Failure> {
    let mut writer = if index + consumed == job.operations.len() {
        Writer::Final(
            output::PlanWriter::new(job, analysis.header.as_deref(), ctx)
                .map_err(Failure::Setup)?,
        )
    } else {
        Writer::Dataset(DatasetWriter::new(ctx).map_err(Failure::Setup)?)
    };
    let Some(stats) = apply(&mut writer).map_err(Failure::Execution)? else {
        return Ok(None);
    };
    Ok(Some(Completed {
        output: writer.finish().map_err(Failure::Execution)?,
        stats,
        consumed,
    }))
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;
