//! Immutable admitted text retained by Analysis and its clones.
use super::*;
use shared_analysis::Shared;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable Analysis text. Clones share the String and its grant; JSON remains
/// a string. Explicit copies and caller construction/deserialization are outside
/// engine admission.
///
/// ```compile_fail
/// fn grow(mut value: chopper::engine::AnalysisText) {
///     value.push_str("unadmitted growth");
/// }
/// ```
#[derive(Clone, Default)]
pub struct AnalysisText(Shared<String>);
impl AnalysisText {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
    pub fn capacity(&self) -> usize {
        self.0.get().map_or(0, String::capacity)
    }
    pub(super) fn copy(value: &str, mut memory: Reservation) -> Result<Self> {
        if value.is_empty() {
            return Ok(Self::default());
        }
        let value = memory.copy_string(value)?;
        Shared::admit(value, memory).map(Self)
    }
}
impl std::ops::Deref for AnalysisText {
    type Target = str;
    fn deref(&self) -> &str {
        self.0.get().map_or("", String::as_str)
    }
}
impl AsRef<str> for AnalysisText {
    fn as_ref(&self) -> &str {
        self
    }
}
impl std::fmt::Debug for AnalysisText {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.as_ref().fmt(f)
    }
}
impl std::fmt::Display for AnalysisText {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Display::fmt(self.as_ref(), f)
    }
}
impl Serialize for AnalysisText {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.as_ref().serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for AnalysisText {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        String::deserialize(deserializer).map(Self::from)
    }
}
impl From<String> for AnalysisText {
    fn from(value: String) -> Self {
        if value.is_empty() {
            Self::default()
        } else {
            Self(Shared::caller_owned(value))
        }
    }
}
impl From<&str> for AnalysisText {
    fn from(value: &str) -> Self {
        Self::from(value.to_owned())
    }
}
impl PartialEq for AnalysisText {
    fn eq(&self, other: &Self) -> bool {
        self.as_ref() == other.as_ref()
    }
}
impl Eq for AnalysisText {}
impl PartialEq<String> for AnalysisText {
    fn eq(&self, other: &String) -> bool {
        self.as_ref() == other.as_str()
    }
}
impl PartialEq<str> for AnalysisText {
    fn eq(&self, other: &str) -> bool {
        self.as_ref() == other
    }
}
impl PartialEq<&str> for AnalysisText {
    fn eq(&self, other: &&str) -> bool {
        self.as_ref() == *other
    }
}
