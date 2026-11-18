//! Retained joined path buffers; discovery, OS conversion and opaque std scratch
//! are separate from this working-capacity owner.
use super::*;
use std::path::PathBuf;

pub(super) struct PublicationPath {
    path: PathBuf,
    // Path allocation drops before its grant, also on failed file operations.
    _memory: Reservation,
}
impl PublicationPath {
    pub(super) fn join(parent: &Path, filename: &str, mut memory: Reservation) -> Result<Self> {
        // Callers provide fixed names or output_name's sanitized single component.
        // Reject cross-platform separators before doing any path allocation.
        ensure!(
            !filename.is_empty()
                && filename != "."
                && filename != ".."
                && !filename.contains(['/', '\\', ':', '\0']),
            "invalid publication filename component"
        );
        let requested = parent
            .as_os_str()
            .len()
            .checked_add(1)
            .and_then(|n| n.checked_add(filename.len()))
            .context("publication path capacity overflow")?;
        memory
            .resize(requested)
            .context("reserve publication path memory")?;
        let mut path = PathBuf::new();
        path.try_reserve_exact(requested)?;
        memory.resize(path.capacity())?;
        // Preserve Path::join semantics, including Windows prefixes. Opaque
        // standard-library normalization scratch is not a retained allocation.
        path.push(parent);
        path.push(filename);
        memory.resize(path.capacity())?;
        Ok(Self {
            path,
            _memory: memory,
        })
    }
}
impl AsRef<Path> for PublicationPath {
    fn as_ref(&self) -> &Path {
        &self.path
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;
