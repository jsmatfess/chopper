//! Chopper patch: admission envelopes at the parser's allocation sites.
use crate::{
    extra_fields::ExtraField,
    result::{ZipError, ZipResult},
    types::ZipFileData,
};
use std::{fmt, io, mem::size_of};

// Two 2048-byte directory finders, Shared/Arc/map control state and one u16-sized
// malformed extra-field scratch allocation. Stack/codec/runtime storage is not
// covered. This allowance stays live until the caller drops its archive owner.
const SCRATCH: usize = 128 * 1024;

#[derive(Debug)]
struct Denied(io::Error);
impl fmt::Display for Denied {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl std::error::Error for Denied {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.0)
    }
}
fn denied(error: io::Error) -> ZipError {
    ZipError::Io(io::Error::new(error.kind(), Denied(error)))
}
pub(crate) fn is_denial(error: &ZipError) -> bool {
    matches!(error, ZipError::Io(error) if error.get_ref().is_some_and(|inner| inner.is::<Denied>()))
}

pub(crate) struct MetadataBudget<'a> {
    reserve: Option<&'a mut dyn FnMut(usize) -> io::Result<()>>,
    bytes: usize,
}
impl<'a> MetadataBudget<'a> {
    pub(crate) fn disabled() -> Self {
        Self {
            reserve: None,
            bytes: 0,
        }
    }
    pub(crate) fn new(reserve: &'a mut dyn FnMut(usize) -> io::Result<()>) -> Self {
        Self {
            reserve: Some(reserve),
            bytes: 0,
        }
    }
    pub(crate) fn checkpoint(&self) -> usize {
        self.bytes
    }
    pub(crate) fn restore(&mut self, bytes: usize) -> ZipResult<()> {
        if let Some(reserve) = self.reserve.as_mut() {
            reserve(bytes).map_err(denied)?;
            self.bytes = bytes;
        }
        Ok(())
    }
    pub(crate) fn begin_attempt(&mut self) -> ZipResult<()> {
        self.restore(SCRATCH)
    }
    pub(crate) fn add(&mut self, bytes: usize) -> ZipResult<()> {
        if self.reserve.is_none() {
            return Ok(());
        }
        let total = self.bytes.checked_add(bytes).ok_or_else(|| {
            denied(io::Error::new(
                io::ErrorKind::OutOfMemory,
                "ZIP metadata allowance overflow",
            ))
        })?;
        self.restore(total)
    }
    pub(crate) fn zip64_extension(&mut self, bytes: u64) -> ZipResult<()> {
        if self.reserve.is_none() {
            return Ok(());
        }
        let bytes = usize::try_from(bytes).map_err(|_| {
            denied(io::Error::new(
                io::ErrorKind::OutOfMemory,
                "ZIP64 metadata exceeds address space",
            ))
        })?;
        self.add(bytes)
    }
    pub(crate) fn entries(&mut self, count: usize) -> ZipResult<()> {
        if self.reserve.is_none() {
            return Ok(());
        }
        // Vec growth/construction plus the simultaneous IndexMap entry vector
        // and hash table. Pinned indexmap/hashbrown allocate at most power-of-two
        // hash capacity; 256 bytes/entry also covers their indices/control bytes.
        let bytes = count
            .checked_mul(4 * size_of::<ZipFileData>() + 256)
            .ok_or_else(|| {
                denied(io::Error::new(
                    io::ErrorKind::OutOfMemory,
                    "ZIP entry allowance overflow",
                ))
            })?;
        self.add(bytes)
    }
    pub(crate) fn entry(&mut self, name: u16, extra: u16, comment: u16) -> ZipResult<()> {
        // Up to 3x decoded UTF-8 expansion, String growth/shrink overlap, raw
        // names, Unicode replacements and the map's duplicated name. Parsed
        // extra-field vectors have at least five serialized bytes/retained item;
        // eight item widths cover growth/overlap, plus sixteen byte-buffer copies.
        let extra_factor = (8 * size_of::<ExtraField>() + 4) / 5 + 16;
        self.add(16 * name as usize + 16 * comment as usize + extra_factor * extra as usize)
    }
}
