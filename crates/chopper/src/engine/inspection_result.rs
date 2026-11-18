//! Returned inspection trees retain their own preallocation allowance.
use super::*;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable inspection JSON with admission retained through serialization/drop.
/// Borrow through Deref or Serialize; an explicitly cloned JSON tree is a new,
/// caller-owned allocation outside this owner's boundary.
#[derive(Debug)]
pub struct Inspection {
    value: serde_json::Value,
    // Value drops before its grant.
    _memory: Reservation,
}
impl Inspection {
    pub(super) fn build(
        mut memory: Reservation,
        array_items: usize,
        string_bytes: usize,
        build: impl FnOnce() -> serde_json::Value,
    ) -> Result<Self> {
        // These fixed schemas contain at most 16 object fields in total.
        // serde_json's default BTreeMap nodes use the same conservative full
        // node allowance as decoded catalogs, including spare slots/edges.
        // Header and nested preview arrays reserve their known
        // length and serialize strings with exact byte lengths. Input parser
        // owners remain independently charged during tree construction.
        let bytes = array_items
            .checked_mul(std::mem::size_of::<serde_json::Value>())
            .and_then(|n| n.checked_add(string_bytes))
            .and_then(|n| {
                n.checked_add(
                    16 * 16
                        * (std::mem::size_of::<String>()
                            + std::mem::size_of::<serde_json::Value>()
                            + std::mem::size_of::<usize>())
                        + 512,
                )
            })
            .context("inspection result allowance overflow")?;
        memory.resize(bytes)?;
        Ok(Self {
            value: build(),
            _memory: memory,
        })
    }
}
impl std::ops::Deref for Inspection {
    type Target = serde_json::Value;
    fn deref(&self) -> &Self::Target {
        &self.value
    }
}
impl serde::Serialize for Inspection {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.value.serialize(serializer)
    }
}
impl std::fmt::Display for Inspection {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.value.fmt(formatter)
    }
}
impl PartialEq for Inspection {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value
    }
}
impl PartialEq<serde_json::Value> for Inspection {
    fn eq(&self, other: &serde_json::Value) -> bool {
        self.value == *other
    }
}
