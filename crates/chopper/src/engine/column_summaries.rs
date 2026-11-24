//! Bounded selected-column observations retain admitted trees through Analysis.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

const MAX_COLUMNS: usize = 64;
const MAX_VALUES: usize = 100;
const DISPLAY_BYTES: usize = 256 * 1024;
// Keep the historical display-selection cost distinct from heap admission.
const DISPLAY_VALUE_OVERHEAD: usize = 64;
const _: () = assert!(
    MAX_VALUES <= 100,
    "re-audit summary BTree split bounds before raising the value limit"
);

// Conservative internal-node allowances for both the value set and frequency map.
// The audited std tree has eleven key slots, twelve edges and a small header.
// At <=100 keys, retained plus splitting nodes fit within the key count bound.
// String payload capacity is separately admitted before copying.
const NODE_ALLOWANCE: usize = 16
    * (2 * std::mem::size_of::<String>()
        + std::mem::size_of::<u64>()
        + 2 * std::mem::size_of::<usize>())
    + 8 * std::mem::size_of::<usize>();

/// Immutable selected-column summaries. Clones share the same trees and grant.
/// Caller construction/deserialization and explicit summary copies allocate
/// outside engine admission. Serialization remains the original array schema.
///
/// ```compile_fail
/// fn grow(mut summaries: chopper::engine::ColumnSummaries) {
///     summaries[0].values.insert("unadmitted growth".into());
/// }
/// ```
#[derive(Clone, Default)]
pub struct ColumnSummaries(Shared<Vec<ColumnValues>>);
impl ColumnSummaries {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
}
impl std::ops::Deref for ColumnSummaries {
    type Target = [ColumnValues];
    fn deref(&self) -> &Self::Target {
        self.0.get().map_or(&[], Vec::as_slice)
    }
}
impl std::fmt::Debug for ColumnSummaries {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self[..].fmt(formatter)
    }
}
impl Serialize for ColumnSummaries {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self[..].serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for ColumnSummaries {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        Vec::<ColumnValues>::deserialize(deserializer).map(Self::from)
    }
}
impl From<Vec<ColumnValues>> for ColumnSummaries {
    fn from(values: Vec<ColumnValues>) -> Self {
        if values.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(values))
        }
    }
}

pub(super) struct Builder {
    values: Vec<ColumnValues>,
    memory: Reservation,
    initialized: bool,
    display_bytes: usize,
}
impl Builder {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            values: Vec::new(),
            memory,
            initialized: false,
            display_bytes: 0,
        }
    }
    fn initialize(&mut self, job: &Job, header: Option<&[String]>, width: usize) -> Result<()> {
        // Only the lowest 64 unique indices are displayed. Continue resolving
        // every request, preserving late missing/ambiguous/out-of-range errors.
        // This fixed stack array replaces unbounded temporary Vec/BTreeSet work.
        let mut selected = [0usize; MAX_COLUMNS];
        let mut len = 0;
        for operation in &job.operations {
            let columns = match operation {
                Operation::Partition { columns } => columns,
                Operation::Assign { strata, .. }
                | Operation::AssignProbabilistic { strata, .. } => strata,
                _ => continue,
            };
            for column in columns {
                let index = match resolve_column(column, header, width) {
                    Ok(index) => index,
                    Err(_) if !job.calculated_columns.is_empty() => continue,
                    Err(error) => return Err(error),
                };
                if let Err(position) = selected[..len].binary_search(&index) {
                    if len < MAX_COLUMNS {
                        selected.copy_within(position..len, position + 1);
                        selected[position] = index;
                        len += 1;
                    } else if position < MAX_COLUMNS {
                        selected.copy_within(position..MAX_COLUMNS - 1, position + 1);
                        selected[position] = index;
                    }
                }
            }
        }
        self.memory.reserve_vec(&mut self.values, len)?;
        for column in selected.into_iter().take(len) {
            self.values.push(ColumnValues {
                column,
                values: Default::default(),
                frequencies: Default::default(),
                truncated: false,
            });
        }
        self.initialized = true;
        Ok(())
    }
    pub(super) fn observe(
        &mut self,
        job: &Job,
        header: Option<&[String]>,
        fields: FieldViews<'_>,
    ) -> Result<()> {
        if !self.initialized {
            self.initialize(job, header, fields.len())?;
        }
        let mut fields = fields;
        let mut next_column = 0;
        for summary in &mut self.values {
            if summary.truncated {
                continue;
            }
            let value = fields
                .nth(summary.column - next_column)
                .context("summary column exceeds record width")?;
            next_column = summary.column + 1;
            if let Some(count) = summary.frequencies.get_mut(value) {
                *count += 1;
                continue;
            }
            let display = value
                .len()
                .checked_add(DISPLAY_VALUE_OVERHEAD)
                .and_then(|n| n.checked_add(self.display_bytes));
            if summary.values.len() == MAX_VALUES || display.is_none_or(|n| n > DISPLAY_BYTES) {
                summary.truncated = true;
                summary.frequencies.clear();
                continue;
            }
            let mut memory = self.memory.sibling();
            memory.resize(NODE_ALLOWANCE)?;
            let copied = memory.copy_string(value)?;
            let counted = memory.copy_string(value)?;
            // Admission precedes BTree node allocation. Inserting String keys
            // cannot call a user comparator; the counter lookup rejected equality.
            summary.frequencies.insert(counted, 1);
            let inserted = summary.values.insert(copied);
            debug_assert!(inserted);
            self.memory.absorb(memory);
            self.display_bytes = display.unwrap();
        }
        Ok(())
    }
    pub(super) fn finish(self) -> Result<ColumnSummaries> {
        if self.values.is_empty() {
            return Ok(ColumnSummaries::default());
        }
        Shared::admit(self.values, self.memory).map(ColumnSummaries)
    }
}
