//! Controlled temporary-name/path construction; no owned path is attached to errors.
use super::*;
use std::path::{Path, PathBuf};

const RANDOM_BYTES: usize = TEMP_FILE_RANDOM_BYTES;
const ATTEMPTS: usize = 128;

fn random_name(
    mut fill_entropy: impl FnMut(&mut [u8]) -> Result<(), getrandom::Error>,
) -> Result<[u8; RANDOM_BYTES]> {
    const ALPHABET: &[u8; 62] = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let mut name = [0; RANDOM_BYTES];
    let mut filled = 0;
    while filled < name.len() {
        let mut entropy = [0; 32];
        fill_entropy(&mut entropy)
            .map_err(|error| anyhow::anyhow!("temporary-name randomness failed: {error}"))?;
        for byte in entropy {
            // Rejection avoids modulo bias, with one stack batch normally enough.
            if byte < 248 {
                name[filled] = ALPHABET[byte as usize % ALPHABET.len()];
                filled += 1;
                if filled == name.len() {
                    break;
                }
            }
        }
    }
    Ok(name)
}

fn create_with<T>(
    parent: &Path,
    prefix: &str,
    mut memory: Reservation,
    mut random: impl FnMut() -> Result<[u8; RANDOM_BYTES]>,
    mut create: impl FnMut(&Path) -> io::Result<T>,
) -> Result<(T, Box<Path>, Reservation)> {
    ensure!(
        parent.is_absolute(),
        "temporary construction requires an absolute parent"
    );
    ensure!(
        prefix
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte)),
        "invalid internal temporary prefix"
    );
    let separator = usize::from(
        !parent
            .as_os_str()
            .as_encoded_bytes()
            .last()
            .is_some_and(|byte| std::path::is_separator(*byte as char)),
    );
    let length = parent
        .as_os_str()
        .len()
        .checked_add(separator)
        .and_then(|bytes| bytes.checked_add(prefix.len()))
        .and_then(|bytes| bytes.checked_add(RANDOM_BYTES))
        .context("temporary path construction size overflow")?;
    memory.resize(length)?;
    let mut path = PathBuf::new();
    path.try_reserve_exact(length)?;
    memory.resize(path.capacity())?;
    for _ in 0..ATTEMPTS {
        let random = random()?;
        ensure!(
            random.iter().all(u8::is_ascii_alphanumeric),
            "invalid temporary random component"
        );
        path.clear();
        let text = path.as_mut_os_string();
        text.push(parent.as_os_str());
        if separator != 0 {
            text.push(std::path::MAIN_SEPARATOR_STR);
        }
        text.push(prefix);
        text.push(std::str::from_utf8(&random)?);
        ensure!(
            path.as_os_str().len() == length && path.capacity() as u64 == memory.bytes(),
            "temporary path construction exceeded admitted capacity"
        );
        // Boxing may shrink an allocator-rounded Vec. Admit old plus replacement
        // before that conversion; an exactly sized Vec transfers without growth.
        if path.capacity() != length {
            memory.resize(
                path.capacity()
                    .checked_add(length)
                    .context("temporary boxing overlap overflow")?,
            )?;
        }
        let boxed = path.into_boxed_path();
        memory.resize(length)?;
        match create(&boxed) {
            Ok(value) => return Ok((value, boxed, memory)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                // This is someone else's file/directory. No cleanup guard exists.
                path = boxed.into_path_buf();
            }
            Err(error) => return Err(error.into()),
        }
    }
    anyhow::bail!("temporary name collision retry limit reached")
}

pub(super) fn directory(
    parent: &Path,
    prefix: &str,
    memory: Reservation,
) -> Result<(Box<Path>, Reservation)> {
    let ((), path, memory) = create_with(
        parent,
        prefix,
        memory,
        || random_name(getrandom::getrandom),
        |path| std::fs::DirBuilder::new().create(path),
    )?;
    Ok((path, memory))
}

pub(super) fn file(parent: &Path, memory: Reservation) -> Result<(NamedTempFile, Reservation)> {
    let (file, path, memory) = create_with(
        parent,
        TEMP_FILE_PREFIX,
        memory,
        || random_name(getrandom::getrandom),
        |path| {
            let mut options = std::fs::OpenOptions::new();
            options.read(true).write(true).create_new(true);
            #[cfg(all(unix, not(target_os = "wasi")))]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::OpenOptionsExt;
                options.custom_flags(
                    windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_TEMPORARY,
                );
            }
            options.open(path)
        },
    )?;
    // The absolute boxed path transfers into TempPath without discovery, joins
    // or a shrink allocation. Platform identity-preserving reopen is below.
    let path = tempfile::TempPath::try_from_path(path.into_path_buf())
        .expect("constructed temporary path is absolute");
    Ok((NamedTempFile::from_parts(file, path), memory))
}

/// Reopen the same file without tempfile's heap-owning with_err_path adapter.
/// Identity checks and independent file offsets match its platform implementation.
pub(super) fn reopen(file: &NamedTempFile) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::io::{AsRawHandle, FromRawHandle};
        use windows_sys::Win32::{
            Foundation::INVALID_HANDLE_VALUE,
            Storage::FileSystem::{
                ReOpenFile, FILE_GENERIC_READ, FILE_GENERIC_WRITE, FILE_SHARE_DELETE,
                FILE_SHARE_READ, FILE_SHARE_WRITE,
            },
        };
        // SAFETY: the borrowed NamedTempFile keeps its source handle live.
        // On success ReOpenFile returns a new owned handle, transferred once.
        let handle = unsafe {
            ReOpenFile(
                file.as_file().as_raw_handle(),
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                0,
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            Err(io::Error::last_os_error())
        } else {
            Ok(unsafe { File::from_raw_handle(handle) })
        }
    }
    #[cfg(any(unix, target_os = "wasi"))]
    {
        let reopened = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(file.path())?;
        let original = rustix::fs::fstat(file.as_file())?;
        let current = rustix::fs::fstat(&reopened)?;
        if original.st_dev != current.st_dev || original.st_ino != current.st_ino {
            return Err(io::ErrorKind::NotFound.into());
        }
        Ok(reopened)
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn temporary_names_reject_biased_entropy_and_refill() -> Result<()> {
        let mut usable = [255; 32];
        usable[..RANDOM_BYTES].copy_from_slice(&[0, 61, 62, 123, 124, 247]);
        let mut batches = [[248; 32], usable].into_iter();
        let name = random_name(|out| {
            out.copy_from_slice(&batches.next().expect("requested unexpected entropy"));
            Ok(())
        })?;
        assert_eq!(name, *b"a9a9a9");
        assert!(batches.next().is_none());
        Ok(())
    }
}
