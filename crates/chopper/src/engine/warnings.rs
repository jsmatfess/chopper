//! Warning capacity follows immutable Analysis clones and returned execution data.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable Analysis warnings; clones share admitted values and their grant.
/// Explicit field copies and caller-constructed/deserialized warningss are caller
/// allocations outside engine admission. Serialization remains an array.
///
/// ```compile_fail
/// fn grow(mut warnings: chopper::engine::Warnings) {
///     warnings[0].push_str("unadmitted growth");
/// }
/// ```
#[derive(Clone, Default)]
pub struct Warnings(Shared<Vec<String>>);
impl Warnings {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
    pub fn capacity(&self) -> usize {
        self.0.get().map_or(0, Vec::capacity)
    }
    fn admit(values: Vec<String>, memory: Reservation) -> Result<Self> {
        Shared::admit(values, memory).map(Self)
    }
}
impl std::ops::Deref for Warnings {
    type Target = [String];
    fn deref(&self) -> &Self::Target {
        self.0.get().map_or(&[], Vec::as_slice)
    }
}
impl std::fmt::Debug for Warnings {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self[..].fmt(formatter)
    }
}
impl Serialize for Warnings {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self[..].serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Warnings {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        Vec::<String>::deserialize(deserializer).map(Self::from)
    }
}
impl From<Vec<String>> for Warnings {
    fn from(values: Vec<String>) -> Self {
        if values.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(values))
        }
    }
}
impl PartialEq for Warnings {
    fn eq(&self, other: &Self) -> bool {
        self[..] == other[..]
    }
}
impl Eq for Warnings {}

// There are eight independent preparation warning conditions. Re-audit this
// bound when adding warnings; it controls both vector admission and construction.
const MAX_WARNINGS: usize = 8;
pub(super) struct Builder {
    values: Vec<String>,
    memory: Reservation,
}
impl Builder {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            values: Vec::new(),
            memory,
        }
    }
    pub(super) fn copy(&mut self, value: &str) -> Result<()> {
        ensure!(
            self.values.len() < MAX_WARNINGS,
            "warning count exceeds admitted bound"
        );
        self.memory.reserve_vec(&mut self.values, MAX_WARNINGS)?;
        let mut memory = self.memory.sibling();
        let copied = memory.copy_string(value)?;
        self.values.push(copied);
        self.memory.absorb(memory);
        Ok(())
    }
    pub(super) fn finish(self) -> Result<Warnings> {
        if self.values.is_empty() {
            Ok(Warnings::default())
        } else {
            Warnings::admit(self.values, self.memory)
        }
    }
}

pub(super) fn build(job: &Job, analysis: &Analysis, memory: Reservation) -> Result<Warnings> {
    use std::io::Write;
    let mut builder = Builder::new(memory);

    if analysis.stages.iter().any(|s| s.empty_groups > 0) {
        builder.copy("Some named allocation groups contain no data rows; their outputs contain only the configured header/BOM.")?;
    }
    if analysis.output_files > 10_000 {
        let mut bytes = [0u8; 80];
        let mut text = std::io::Cursor::new(bytes.as_mut_slice());
        write!(
            &mut text,
            "This job creates {} CSV files/members.",
            analysis.output_files
        )?;
        let len = text.position() as usize;
        builder.copy(std::str::from_utf8(&bytes[..len])?)?;
    }
    if job.limits.compressed_bytes.is_some() {
        builder.copy("Compressed target is advisory: boundaries conservatively assume no compression plus 5% and 128 bytes overhead. Actual compressed size may exceed target. For ZIP this targets each member, not the whole archive.")?;
    }
    if job.operations.iter().any(|o| {
        matches!(
            o,
            Operation::Balanced { .. } | Operation::Interleaved { .. }
        )
    }) && (job.limits.bytes.is_some() || job.limits.rows.is_some())
    {
        builder.copy("Balanced groups retain exact counts through shuffling. Hard caps that require extra chunks are rejected.")?;
    }
    if job
        .operations
        .iter()
        .any(|o| matches!(o, Operation::AssignProbabilistic { .. }))
    {
        builder.copy("Probabilistic allocation uses target percentages, not exact quotas. Small strata may receive no rows in a destination; displayed counts are the actual prepared results.")?;
    }
    if job
        .operations
        .iter()
        .any(|o| matches!(o, Operation::Interleaved { .. }))
    {
        builder.copy("Interleaved splitting distributes consecutive rows across parts. Concatenating the files does not restore input order.")?;
    }
    if job.operations.iter().any(|o| {
        matches!(
            o,
            Operation::Shuffle {
                strategy: Shuffle::FisherYates,
                ..
            }
        )
    }) {
        builder.copy("Fisher–Yates v1 is a uniform in-memory shuffle with a different seeded order from random-key v1. Every group must fit the resident shuffle budget.")?;
    }
    builder.finish()
}
