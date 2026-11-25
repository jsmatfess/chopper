use super::*;
use std::{fs, path::PathBuf};

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;

#[derive(Default)]
pub(crate) enum RunDestination {
    #[default]
    Unchecked,
    #[cfg(not(target_os = "wasi"))]
    Absent,
    #[cfg(not(target_os = "wasi"))]
    Existing(DirectoryWitness),
}

impl RunDestination {
    #[cfg(not(target_os = "wasi"))]
    pub(crate) fn preflight(job: &Job) -> Result<Self> {
        let check = || -> Result<Self> {
            job.validate_output()?;
            let destination = std::path::absolute(&job.output)?;
            let existing = empty_destination(&destination, false)?;
            check_parent(&destination)?;
            if existing {
                Ok(Self::Existing(DirectoryWitness::open(&destination)?))
            } else {
                Ok(Self::Absent)
            }
        };
        check().with_context(|| {
            format!(
                "choose a new or empty output directory instead of {:?}",
                job.output
            )
        })
    }

    pub(super) fn check(&self, path: &Path) -> Result<bool> {
        match self {
            Self::Unchecked => empty_destination(path, false),
            #[cfg(not(target_os = "wasi"))]
            Self::Absent => empty_destination(path, true),
            #[cfg(not(target_os = "wasi"))]
            Self::Existing(original) => {
                let changed = "output destination changed during Run; choose a different output directory and retry";
                ensure!(empty_destination(path, false)?, "{changed}");
                let current = DirectoryWitness::open(path)?;
                ensure!(current.identity == original.identity, "{changed}");
                Ok(true)
            }
        }
    }
}

pub(super) struct DestinationPath {
    path: PathBuf,
    // The resolved allocation drops before its grant, including on error.
    memory: Reservation,
}

impl DestinationPath {
    fn admit(path: PathBuf, memory: Reservation) -> Result<Self> {
        let mut destination = Self { path, memory };
        destination
            .memory
            .resize(destination.path.capacity())
            .context("reserve absolute publication destination")?;
        Ok(destination)
    }

    pub(super) fn as_path(&self) -> &Path {
        &self.path
    }
}

pub(super) fn staging_destination(job: &Job, ctx: &Context) -> Result<(DestinationPath, bool)> {
    ctx.check()?;
    let path = std::path::absolute(&job.output)?;
    let destination = DestinationPath::admit(path, Reservation::new(ctx))?;
    let existing_empty = ctx.run_destination().check(destination.as_path())?;
    check_parent(destination.as_path())?;
    Ok((destination, existing_empty))
}

fn check_parent(destination: &Path) -> Result<()> {
    let parent = destination.parent().context("invalid output directory")?;
    ensure!(parent.is_dir(), "output parent directory does not exist");
    Ok(())
}

fn empty_destination(path: &Path, must_be_absent: bool) -> Result<bool> {
    // A trailing separator can make symlink_metadata follow the leaf.
    #[cfg(any(unix, windows))]
    let path = path.components().as_path();
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            ensure!(
                !must_be_absent,
                "output destination appeared during Run; choose a different output directory and retry"
            );
            ensure!(
                is_plain_directory(&metadata),
                "output destination must be a new or empty directory, not a file or link"
            );
            ensure!(
                fs::read_dir(path)?.next().is_none(),
                "output destination already exists and is not empty"
            );
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

fn is_plain_directory(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return false;
        }
    }
    metadata.is_dir() && !metadata.file_type().is_symlink()
}

#[cfg(not(target_os = "wasi"))]
pub(crate) struct DirectoryWitness {
    #[cfg(unix)]
    identity: (u64, u64),
    #[cfg(windows)]
    identity: (u64, [u8; 16]),
    // Keep the original object alive so removing it cannot recycle its identity.
    _handle: File,
}

#[cfg(not(target_os = "wasi"))]
impl DirectoryWitness {
    fn open(path: &Path) -> Result<Self> {
        let mut options = fs::OpenOptions::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options
                .read(true)
                .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW);
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            use windows_sys::Win32::Storage::FileSystem::*;
            options
                .access_mode(FILE_READ_ATTRIBUTES)
                .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
        }
        let handle = options
            .open(path.components().as_path())
            .context("open output directory for identity check")?;
        let metadata = handle.metadata()?;
        ensure!(
            is_plain_directory(&metadata),
            "output destination must be a new or empty directory, not a file or link"
        );
        #[cfg(unix)]
        let identity = {
            use std::os::unix::fs::MetadataExt;
            (metadata.dev(), metadata.ino())
        };
        #[cfg(windows)]
        let identity = {
            use std::os::windows::io::AsRawHandle;
            use windows_sys::Win32::Storage::FileSystem::*;
            let mut info = FILE_ID_INFO::default();
            // The handle is live and the writable buffer is sized for FileIdInfo.
            if unsafe {
                GetFileInformationByHandleEx(
                    handle.as_raw_handle(),
                    FileIdInfo,
                    (&mut info as *mut FILE_ID_INFO).cast(),
                    std::mem::size_of::<FILE_ID_INFO>() as u32,
                )
            } == 0
            {
                return Err(std::io::Error::last_os_error())
                    .context("read output directory identity");
            }
            (info.VolumeSerialNumber, info.FileId.Identifier)
        };
        Ok(Self {
            identity,
            _handle: handle,
        })
    }
}
