//! Admitted lineage clones for output planning, independent of decoded owners.
use super::*;

/// Only scalar metadata may change after construction. Lineage growth needs a
/// separate preallocation seam. The cloned tree drops before its grant.
pub(super) struct PlannedMetadata<T> {
    pub(super) value: T,
    pub(super) _memory: Reservation,
}

impl<T: JsonCapacity> PlannedMetadata<T> {
    pub(super) fn clone_lineage(
        source: &Group,
        mut memory: Reservation,
        build: impl FnOnce(Group) -> T,
    ) -> Result<Self> {
        // Vec/String Clone reserve known lengths, bounded by the source's
        // reported capacities. BTreeMap Clone is covered by JsonCapacity's
        // conservative full-node allowance per entry. No JSON parse/scratch.
        let allowance = source.json_capacity()?;
        memory.resize(allowance)?;
        let value = build(source.clone());
        let retained = value.json_capacity()?;
        ensure!(
            retained <= allowance,
            "cloned lineage exceeds admitted capacity"
        );
        memory.resize(retained)?;
        Ok(Self {
            value,
            _memory: memory,
        })
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;
