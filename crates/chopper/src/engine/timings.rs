//! Bounded stack observations become one admitted immutable timing map.
use super::*;
use shared_analysis::Shared;
use std::collections::BTreeMap;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable Analysis phase timings. Clones share the map and admission; JSON
/// remains an object. Caller construction/deserialization and explicit copies
/// are outside engine admission.
///
/// ```compile_fail
/// fn grow(mut timings:chopper::engine::Timings) {
///     timings.insert("extra".into(),1.0);
/// }
/// ```
#[derive(Clone, Default)]
pub struct Timings(Shared<BTreeMap<String, f64>>);
impl Timings {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
}
impl std::ops::Deref for Timings {
    type Target = BTreeMap<String, f64>;
    fn deref(&self) -> &Self::Target {
        static EMPTY: BTreeMap<String, f64> = BTreeMap::new();
        self.0.get().unwrap_or(&EMPTY)
    }
}
impl std::fmt::Debug for Timings {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Debug::fmt(&**self, f)
    }
}
impl Serialize for Timings {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        (**self).serialize(s)
    }
}
impl<'de> Deserialize<'de> for Timings {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        BTreeMap::<String, f64>::deserialize(d).map(Self::from)
    }
}
impl From<BTreeMap<String, f64>> for Timings {
    fn from(values: BTreeMap<String, f64>) -> Self {
        if values.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(values))
        }
    }
}
impl PartialEq for Timings {
    fn eq(&self, other: &Self) -> bool {
        **self == **other
    }
}

const MAX_TIMINGS: usize = 5;
// The audited Rust BTree has 11 key/value slots per leaf. Five insertions
// cannot split it. One conservative full-node envelope also includes alignment
// and child-edge headroom, though only a leaf is constructed here.
const NODE_ALLOWANCE: usize = 16
    * (std::mem::size_of::<String>() + std::mem::size_of::<f64>() + std::mem::size_of::<usize>())
    + 4 * std::mem::size_of::<usize>();
const _: () = assert!(
    MAX_TIMINGS <= 11,
    "re-audit timing tree admission before raising its entry bound"
);
pub(super) struct Builder {
    values: [Option<(&'static str, f64)>; MAX_TIMINGS],
    memory: Reservation,
}
impl Builder {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            values: [None; MAX_TIMINGS],
            memory,
        }
    }
    pub(super) fn insert(&mut self, key: &'static str, value: f64) -> Result<()> {
        if let Some(entry) = self
            .values
            .iter_mut()
            .flatten()
            .find(|entry| entry.0 == key)
        {
            entry.1 = value;
            return Ok(());
        }
        let target = self
            .values
            .iter_mut()
            .find(|entry| entry.is_none())
            .context("timing count exceeds admitted bound")?;
        *target = Some((key, value));
        Ok(())
    }
    pub(super) fn finish(self) -> Result<Timings> {
        let Self { values, mut memory } = self;
        if values.iter().all(Option::is_none) {
            return Ok(Timings::default());
        }
        let mut result = BTreeMap::new();
        memory.resize(NODE_ALLOWANCE)?;
        for (key, value) in values.into_iter().flatten() {
            let copied = memory.copy_string(key)?;
            result.insert(copied, value);
        }
        Shared::admit(result, memory).map(Timings)
    }
}
