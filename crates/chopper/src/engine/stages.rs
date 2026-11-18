//! Stage counters have one admitted, fixed-capacity owner through Analysis clones.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable logical-stage counters. Clones share storage and its admission.
/// Caller-created/deserialized counters are outside engine admission; JSON is
/// unchanged. Engine construction is private and cannot grow a shared payload.
///
/// ```compile_fail
/// fn grow(mut stages: chopper::engine::Stages) {
///     stages[0].operation = 99;
/// }
/// ```
#[derive(Clone, Default)]
pub struct Stages {
    values: Shared<Vec<StageStats>>,
    limit: usize,
}
impl Stages {
    pub fn reserved_bytes(&self) -> u64 {
        self.values.reserved_bytes()
    }
    pub fn capacity(&self) -> usize {
        self.values.get().map_or(0, Vec::capacity)
    }
    pub(super) fn new(limit: usize, mut memory: Reservation) -> Result<Self> {
        if limit == 0 {
            return Ok(Self::default());
        }
        let mut values = Vec::new();
        memory.reserve_vec(&mut values, limit)?;
        Ok(Self {
            values: Shared::admit(values, memory)?,
            limit,
        })
    }
    pub(super) fn push(&mut self, value: StageStats) -> Result<()> {
        self.extend(std::iter::once(value))
    }
    pub(super) fn extend<I>(&mut self, values: I) -> Result<()>
    where
        I: IntoIterator<Item = StageStats>,
        I::IntoIter: ExactSizeIterator,
    {
        let values = values.into_iter();
        let length = self
            .len()
            .checked_add(values.len())
            .context("stage counter length overflow")?;
        ensure!(
            length <= self.limit,
            "stage counters exceed admitted operation count"
        );
        if values.len() == 0 {
            return Ok(());
        }
        let target = self
            .values
            .get_mut()
            .context("stage counters cannot change while shared")?;
        // All slots and the shared controller were admitted before CSV read.
        // The logical limit can be smaller than allocator-reported capacity.
        ensure!(
            length <= target.capacity(),
            "stage counter capacity invariant"
        );
        target.extend(values);
        Ok(())
    }
}
impl std::ops::Deref for Stages {
    type Target = [StageStats];
    fn deref(&self) -> &Self::Target {
        self.values.get().map_or(&[], Vec::as_slice)
    }
}
impl std::fmt::Debug for Stages {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self[..].fmt(formatter)
    }
}
impl Serialize for Stages {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self[..].serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Stages {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        Vec::<StageStats>::deserialize(deserializer).map(Self::from)
    }
}
impl From<Vec<StageStats>> for Stages {
    fn from(values: Vec<StageStats>) -> Self {
        if values.is_empty() {
            Self::default()
        } else {
            Self {
                limit: values.len(),
                values: Shared::caller_owned(values),
            }
        }
    }
}
