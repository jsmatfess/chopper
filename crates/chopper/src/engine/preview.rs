//! Immutable Analysis previews share both retained rows and their capacity grant.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Read-only Analysis preview. Clones share the same admitted rows and grant.
/// Explicitly copied rows and deserialized/caller-constructed previews are
/// caller-owned allocations outside engine admission.
///
/// ```compile_fail
/// fn grow(mut preview: chopper::engine::Preview) {
///     preview[0].push("unadmitted growth".into());
/// }
/// ```
#[derive(Clone, Default)]
pub struct Preview(Shared<Vec<Vec<String>>>);
impl Preview {
    /// Working capacity retained by this engine-created preview, shared by clones.
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
}
impl std::ops::Deref for Preview {
    type Target = [Vec<String>];
    fn deref(&self) -> &Self::Target {
        self.0.get().map_or(&[], Vec::as_slice)
    }
}
impl std::fmt::Debug for Preview {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self[..].fmt(formatter)
    }
}
impl Serialize for Preview {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self[..].serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Preview {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        Vec::<Vec<String>>::deserialize(deserializer).map(Self::from)
    }
}
impl From<Vec<Vec<String>>> for Preview {
    fn from(values: Vec<Vec<String>>) -> Self {
        if values.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(values))
        }
    }
}
impl PartialEq for Preview {
    fn eq(&self, other: &Self) -> bool {
        self[..] == other[..]
    }
}
impl Eq for Preview {}
impl PartialEq<Vec<Vec<String>>> for Preview {
    fn eq(&self, other: &Vec<Vec<String>>) -> bool {
        self[..] == other[..]
    }
}

pub(super) struct Builder {
    values: Vec<Vec<String>>,
    memory: Reservation,
    payload: usize,
}
impl Builder {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            values: Vec::new(),
            memory,
            payload: 0,
        }
    }
    pub(super) fn consider(&mut self, fields: FieldViews<'_>, payload: usize) -> Result<()> {
        if self.values.len() == 8 || payload > 32 * 1024 - self.payload {
            return Ok(());
        }
        // Reserve the known maximum once. Many empty fields still require a
        // String slot each, independently of the historical payload-only limit.
        self.memory.reserve_vec(&mut self.values, 8)?;
        let mut row = RowOwner {
            values: Vec::new(),
            memory: self.memory.sibling(),
        };
        row.memory.reserve_vec(&mut row.values, fields.len())?;
        for field in fields {
            row.values.push(row.memory.copy_string(field)?);
        }
        let RowOwner { values, memory } = row;
        self.memory.absorb(memory);
        self.values.push(values);
        self.payload += payload;
        Ok(())
    }
    pub(super) fn finish(self) -> Result<Preview> {
        if self.values.is_empty() {
            return Ok(Preview::default());
        }
        Shared::admit(self.values, self.memory).map(Preview)
    }
}
struct RowOwner {
    values: Vec<String>,
    memory: Reservation,
}
