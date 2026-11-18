//! Header capacity follows immutable Analysis clones and returned execution data.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable Analysis header; clones share admitted fields and their grant.
/// Explicit field copies and caller-constructed/deserialized headers are caller
/// allocations outside engine admission. Serialization remains an array.
///
/// ```compile_fail
/// fn grow(mut header: chopper::engine::Header) {
///     header[0].push_str("unadmitted growth");
/// }
/// ```
#[derive(Clone, Default)]
pub struct Header(Shared<Vec<String>>);
impl Header {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
    pub fn capacity(&self) -> usize {
        self.0.get().map_or(0, Vec::capacity)
    }
    fn admit(fields: Vec<String>, memory: Reservation) -> Result<Self> {
        Shared::admit(fields, memory).map(Self)
    }
}
impl std::ops::Deref for Header {
    type Target = [String];
    fn deref(&self) -> &Self::Target {
        self.0.get().map_or(&[], Vec::as_slice)
    }
}
impl std::fmt::Debug for Header {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self[..].fmt(formatter)
    }
}
impl Serialize for Header {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self[..].serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for Header {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        Vec::<String>::deserialize(deserializer).map(Self::from)
    }
}
impl From<Vec<String>> for Header {
    fn from(fields: Vec<String>) -> Self {
        if fields.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(fields))
        }
    }
}
impl PartialEq for Header {
    fn eq(&self, other: &Self) -> bool {
        self[..] == other[..]
    }
}
impl Eq for Header {}

pub(super) fn read(input: &mut Intake<impl records::Records>) -> Result<Option<Header>> {
    input
        .header()?
        .map(|header| {
            let (fields, memory) = header.into_parts();
            Header::admit(fields, memory)
        })
        .transpose()
}
