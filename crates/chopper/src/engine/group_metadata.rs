//! Independently cloned groups retain their lineage's construction grant.
use super::*;

pub(super) struct ClonedGroup {
    pub(super) group: Group,
    // Drop the cloned tree before returning its working-capacity grant.
    memory: Reservation,
}
impl ClonedGroup {
    #[cfg(feature = "experimental-consecutive-partitions")]
    pub(super) fn append(
        &mut self,
        entry: &child_metadata::Entry<'_>,
        ctx: &Context,
    ) -> Result<()> {
        child_metadata::append(&mut self.group, entry, ctx, &mut self.memory)
    }

    #[cfg(feature = "experimental-consecutive-partitions")]
    pub(super) fn truncate(&mut self, length: usize) -> Result<()> {
        self.group.lineage.truncate(length);
        self.memory.resize(self.group.json_capacity()?)
    }

    #[cfg(feature = "experimental-constant-partition")]
    pub(super) fn restart(&mut self, output: &impl RowSink) {
        let lineage = std::mem::take(&mut self.group.lineage);
        self.group = output.begin(lineage, self.group.exact);
    }
    pub(super) fn child(
        parent: &Group,
        entry: &child_metadata::Entry<'_>,
        ctx: &Context,
        build: impl FnOnce(Vec<serde_json::Value>) -> Group,
    ) -> Result<Self> {
        let (lineage, memory) = child_metadata::build(parent, entry, ctx, Reservation::new(ctx))?;
        Ok(Self {
            group: build(lineage),
            memory,
        })
    }

    pub(super) fn begin_child(
        parent: &Group,
        entry: &child_metadata::Entry<'_>,
        exact: bool,
        output: &impl RowSink,
        ctx: &Context,
    ) -> Result<Self> {
        Self::child(parent, entry, ctx, |lineage| output.begin(lineage, exact))
    }

    pub(super) fn begin(
        parent: &Group,
        output: &impl RowSink,
        memory: Reservation,
    ) -> Result<Self> {
        Self::build(parent, memory, |group| {
            output.begin(group.lineage, group.exact)
        })
    }

    pub(super) fn build(
        parent: &Group,
        mut memory: Reservation,
        build: impl FnOnce(Group) -> Group,
    ) -> Result<Self> {
        // Vec/String Clone know their lengths. The source capacities bound
        // their copies; JsonCapacity includes conservative BTreeMap nodes.
        let allowance = parent.json_capacity()?;
        memory.resize(allowance)?;
        let group = build(parent.clone());
        let retained = group.json_capacity()?;
        ensure!(
            retained <= allowance,
            "cloned group lineage exceeds admitted capacity"
        );
        memory.resize(retained)?;
        Ok(Self { group, memory })
    }

    pub(super) fn finish(self, output: &mut impl RowSink) -> Result<()> {
        let Self { group, memory } = self;
        // end consumes/serializes the group; hold admission through both success
        // and sink failure. The sink must not retain the consumed lineage.
        let result = output.end(group);
        drop(memory);
        result
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;
