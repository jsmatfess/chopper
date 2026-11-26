//! Temporary spool-header key storage. Fixed keys stay inline until their
//! consumer chooses packed or independently admitted owned-row storage.
use super::{PackedKey, Reservation, RoutedKey};
use anyhow::Result;
use std::sync::Arc;

pub(super) enum FrameKey {
    Random([u8; 16]),
    Index([u8; 8]),
    Heap(Vec<u8>),
    Routed(Arc<RoutedKey>),
}

impl FrameKey {
    pub(super) fn capacity(&self) -> usize {
        match self {
            Self::Random(_) | Self::Index(_) | Self::Routed(_) => 0,
            Self::Heap(bytes) => bytes.capacity(),
        }
    }

    pub(super) fn into_packed(self) -> PackedKey {
        match self {
            Self::Random(bytes) => PackedKey::Random(bytes),
            Self::Index(bytes) => PackedKey::Index(bytes),
            Self::Heap(bytes) => PackedKey::new(bytes),
            Self::Routed(key) => PackedKey::Routed(key),
        }
    }

    pub(super) fn into_vec(self) -> Vec<u8> {
        match self {
            Self::Random(bytes) => bytes.to_vec(),
            Self::Index(bytes) => bytes.to_vec(),
            Self::Heap(bytes) => bytes,
            Self::Routed(key) => key.bytes.to_vec(),
        }
    }

    pub(super) fn into_vec_reserved(self, charge: &mut Reservation) -> Result<Vec<u8>> {
        if let Self::Heap(bytes) = self {
            return Ok(bytes);
        }
        let mut bytes = Vec::new();
        charge.reserve_vec(&mut bytes, self.len())?;
        bytes.extend_from_slice(&self);
        Ok(bytes)
    }
}

impl From<Vec<u8>> for FrameKey {
    fn from(bytes: Vec<u8>) -> Self {
        // Retain the original capacity for variable-key boxing overlap tests.
        Self::Heap(bytes)
    }
}

impl std::ops::Deref for FrameKey {
    type Target = [u8];

    fn deref(&self) -> &[u8] {
        match self {
            Self::Random(bytes) => bytes,
            Self::Index(bytes) => bytes,
            Self::Heap(bytes) => bytes,
            Self::Routed(key) => &key.bytes,
        }
    }
}
