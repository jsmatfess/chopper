//! Immutable Progress phases retain their allocation grant through final deallocation.
use super::*;
struct Payload {
    value: String,
    memory: Option<Reservation>,
}
#[derive(Clone)]
struct Shared(Option<Arc<Payload>>);
impl Shared {
    const fn controller_bytes() -> usize {
        std::mem::size_of::<Payload>() + 4 * std::mem::size_of::<usize>()
    }
    fn get(&self) -> &String {
        &self.0.as_ref().unwrap().value
    }
    fn reserved_bytes(&self) -> u64 {
        self.0
            .as_ref()
            .unwrap()
            .memory
            .as_ref()
            .map_or(0, Reservation::bytes)
    }
}
impl Drop for Shared {
    fn drop(&mut self) {
        // Every clone participates: the winning into_inner deallocates the Arc
        // controller before dropping String, then its Workspace-retaining grant.
        // Neither Weak handles nor mutable payload access escape.
        if let Some(payload) = self.0.take() {
            drop(Arc::into_inner(payload));
        }
    }
}
/// Immutable progress phase. Clones share the String and its grant; JSON remains
/// a string. Explicit copies and caller construction/deserialization are outside
/// engine admission.
///
/// ```compile_fail
/// fn grow(mut value: chopper::storage::ProgressPhase) {
///     value.push_str("unadmitted growth");
/// }
/// ```
#[derive(Clone, Default)]
pub struct ProgressPhase(Repr);
#[derive(Clone)]
enum Repr {
    Static(&'static str),
    Owned(Shared),
}
impl Default for Repr {
    fn default() -> Self {
        Self::Static("")
    }
}
impl ProgressPhase {
    pub fn as_str(&self) -> &str {
        self
    }
    pub fn reserved_bytes(&self) -> u64 {
        match &self.0 {
            Repr::Static(_) => 0,
            Repr::Owned(value) => value.reserved_bytes(),
        }
    }
    pub fn capacity(&self) -> usize {
        match &self.0 {
            Repr::Static(_) => 0,
            Repr::Owned(value) => value.get().capacity(),
        }
    }
    /// Borrow a literal without allocation or admission, including after commit.
    pub const fn literal(value: &'static str) -> Self {
        Self(Repr::Static(value))
    }
    pub(super) fn copy(value: &str, mut memory: Reservation) -> Result<Self> {
        if value.is_empty() {
            return Ok(Self::default());
        }
        // Admit the controller before either heap allocation. copy_string adds
        // and reconciles actual backing capacity without dropping this charge.
        memory.resize(Shared::controller_bytes())?;
        let value = memory.copy_string(value)?;
        Ok(Self(Repr::Owned(Shared(Some(Arc::new(Payload {
            value,
            memory: Some(memory),
        }))))))
    }
}
impl std::ops::Deref for ProgressPhase {
    type Target = str;
    fn deref(&self) -> &str {
        match &self.0 {
            Repr::Static(value) => value,
            Repr::Owned(value) => value.get().as_str(),
        }
    }
}
impl AsRef<str> for ProgressPhase {
    fn as_ref(&self) -> &str {
        self
    }
}
impl std::fmt::Debug for ProgressPhase {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.as_ref().fmt(f)
    }
}
impl std::fmt::Display for ProgressPhase {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Display::fmt(self.as_ref(), f)
    }
}
impl Serialize for ProgressPhase {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.as_ref().serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for ProgressPhase {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        String::deserialize(deserializer).map(Self::from)
    }
}
impl From<String> for ProgressPhase {
    fn from(value: String) -> Self {
        if value.is_empty() {
            Self::default()
        } else {
            Self(Repr::Owned(Shared(Some(Arc::new(Payload {
                value,
                memory: None,
            })))))
        }
    }
}
impl From<&str> for ProgressPhase {
    fn from(value: &str) -> Self {
        Self::from(value.to_owned())
    }
}
impl PartialEq for ProgressPhase {
    fn eq(&self, other: &Self) -> bool {
        self.as_ref() == other.as_ref()
    }
}
impl Eq for ProgressPhase {}
impl PartialEq<String> for ProgressPhase {
    fn eq(&self, other: &String) -> bool {
        self.as_ref() == other.as_str()
    }
}
impl PartialEq<str> for ProgressPhase {
    fn eq(&self, other: &str) -> bool {
        self.as_ref() == other
    }
}
impl PartialEq<&str> for ProgressPhase {
    fn eq(&self, other: &&str) -> bool {
        self.as_ref() == *other
    }
}

// Decimal usize requires at most ceil(bits * log10(2)) digits.
const OPERATION_CAPACITY: usize =
    "Preparing operation  of ".len() + 2 * ((usize::BITS as usize * 30103).div_ceil(100000));
pub(super) struct OperationText {
    bytes: [u8; OPERATION_CAPACITY],
    len: usize,
}
impl Default for OperationText {
    fn default() -> Self {
        Self {
            bytes: [0; OPERATION_CAPACITY],
            len: 0,
        }
    }
}
impl OperationText {
    pub(super) fn as_str(&self) -> &str {
        std::str::from_utf8(&self.bytes[..self.len]).unwrap()
    }
}
impl std::fmt::Write for OperationText {
    fn write_str(&mut self, value: &str) -> std::fmt::Result {
        let end = self
            .len
            .checked_add(value.len())
            .filter(|end| *end <= self.bytes.len())
            .ok_or(std::fmt::Error)?;
        self.bytes[self.len..end].copy_from_slice(value.as_bytes());
        self.len = end;
        Ok(())
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;
