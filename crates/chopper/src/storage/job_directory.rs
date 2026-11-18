use super::*;
use std::{borrow::Cow, path::Path};

/// Reports cleanup failures while retaining the original path through removal.
pub struct JobDirectory {
    dir: Option<Directory>,
    reservation: Option<Reservation>,
    counter: Option<Arc<AtomicU64>>,
}
enum Directory {
    External(TempDir),
    Owned(Box<Path>),
}
impl Directory {
    fn path(&self) -> &Path {
        match self {
            Self::External(dir) => dir.path(),
            Self::Owned(path) => path,
        }
    }
    fn keep(self) -> std::path::PathBuf {
        match self {
            Self::External(dir) => dir.keep(),
            Self::Owned(path) => path.into_path_buf(),
        }
    }
}
impl JobDirectory {
    #[cfg(any(
        test,
        all(
            feature = "resource-contract-tests",
            feature = "experimental-spill-blocks"
        )
    ))]
    pub(super) fn rebind_for_test(&mut self, workspace: Arc<Workspace>) -> Result<()> {
        let mut next = Reservation::for_workspace(workspace);
        next.resize(self.reservation.as_ref().unwrap().bytes() as usize)?;
        self.reservation = Some(next);
        Ok(())
    }
    /// Wrap an externally constructed directory. Its allocation is not charged.
    pub fn new(dir: TempDir) -> Self {
        Self {
            dir: Some(Directory::External(dir)),
            reservation: None,
            counter: None,
        }
    }
    pub(crate) fn create(
        parent: Option<&Path>,
        prefix: &str,
        reservation: Reservation,
        counter: Arc<AtomicU64>,
    ) -> Result<Self> {
        // Platform discovery/absolutization remains separate. Once the parent
        // is known, temp_path admits every owned name/path construction step.
        let parent = parent
            .map(Cow::Borrowed)
            .unwrap_or_else(|| Cow::Owned(std::env::temp_dir()));
        let parent = if parent.is_absolute() {
            parent
        } else {
            Cow::Owned(std::path::absolute(&parent)?)
        };
        let (path, reservation) = temp_path::directory(&parent, prefix, reservation)?;
        let bytes = path.as_os_str().len();
        let mut owner = Self {
            dir: Some(Directory::Owned(path)),
            reservation: Some(reservation),
            counter: None,
        };
        ensure!(
            owner.path().as_os_str().len() == bytes,
            "unexpected temporary directory path size"
        );
        counter.fetch_add(bytes as u64, AtomicOrdering::Relaxed);
        owner.counter = Some(counter);
        Ok(owner)
    }
    pub fn path(&self) -> &Path {
        self.dir.as_ref().expect("directory already closed").path()
    }
    pub fn published(&mut self) {
        if let Some(dir) = self.dir.take() {
            // keep moves the boxed path, without cloning it. Publication has
            // already renamed the directory or finalized the WASI destination.
            drop(dir.keep());
        }
        self.release();
    }
    fn release(&mut self) {
        if let Some(counter) = self.counter.take() {
            counter.fetch_sub(
                self.reservation.as_ref().unwrap().bytes(),
                AtomicOrdering::Relaxed,
            );
        }
        self.reservation.take();
    }
}
impl Drop for JobDirectory {
    fn drop(&mut self) {
        if let Some(dir) = self.dir.take() {
            // TempDir::close clones its path to decorate deletion errors.
            // Keep the original instead. Recursive-delete/platform internals
            // and logging remain outside allocation accounting.
            let path = dir.keep();
            if let Err(error) = std::fs::remove_dir_all(&path) {
                eprintln!("chopper: cleanup failed for {}: {error}", path.display());
            }
            drop(path);
        }
        self.release();
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts {
    use super::*;
    use crate::resources::{MemoryAdmission, MemoryPool};

    fn create(parent: &Path, workspace: Arc<Workspace>) -> Result<JobDirectory> {
        JobDirectory::create(
            Some(parent),
            "chopper-",
            Reservation::for_workspace(workspace),
            Arc::new(AtomicU64::new(0)),
        )
    }

    pub(crate) fn run() -> Result<serde_json::Value> {
        #[cfg(target_os = "wasi")]
        let fixture = tempfile::tempdir_in("/tmp")?;
        #[cfg(not(target_os = "wasi"))]
        let fixture = tempfile::tempdir_in(std::env::current_dir()?)?;
        let unicode = fixture.path().join("directory-界-é");
        std::fs::create_dir(&unicode)?;
        let probe_workspace = Arc::new(Workspace::new(1024 * 1024));
        let probe = create(&unicode, probe_workspace.clone())?;
        let bytes = probe.path().as_os_str().len();
        ensure!(
            probe_workspace.used() == bytes as u64,
            "directory path charge differs from retained boxed path"
        );
        drop(probe);
        ensure!(probe_workspace.used() == 0, "directory probe leaked");
        let mut local_denials = 0;
        let mut shared_denials = 0;
        for delta in [-1, 0, 1] {
            let limit = bytes.checked_add_signed(delta).unwrap();
            let workspace = Arc::new(Workspace::new(limit));
            let result = create(&unicode, workspace.clone());
            ensure!(
                result.is_ok() == (delta >= 0),
                "local directory admission edge changed"
            );
            if let Err(error) = &result {
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Local)
                    ),
                    "untyped local directory denial"
                );
                local_denials += 1;
                ensure!(
                    std::fs::read_dir(&unicode)?.next().is_none(),
                    "local denial created a directory"
                );
            }
            drop(result);
            ensure!(workspace.used() == 0, "local directory edge leaked");
            let pool = Arc::new(MemoryPool::new(limit as u64));
            let workspace = Arc::new(Workspace::shared(bytes + 1, pool.clone()));
            let result = create(&unicode, workspace.clone());
            ensure!(
                result.is_ok() == (delta >= 0),
                "shared directory admission edge changed"
            );
            if let Err(error) = &result {
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "untyped shared directory denial"
                );
                shared_denials += 1;
                ensure!(
                    std::fs::read_dir(&unicode)?.next().is_none(),
                    "shared denial created a directory"
                );
            }
            drop(result);
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "shared directory edge leaked"
            );
        }
        let pool = Arc::new(MemoryPool::new(bytes as u64));
        let workspace = Arc::new(Workspace::shared(bytes + 1, pool.clone()));
        let mut sibling =
            Reservation::for_workspace(Arc::new(Workspace::shared(bytes + 1, pool.clone())));
        sibling.resize(1)?;
        let error = create(&unicode, workspace.clone())
            .err()
            .context("sibling pressure should deny directory")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && pool.usage().reserved_bytes == 1,
            "directory denial lost sibling owner"
        );
        drop(sibling);
        let retry = create(&unicode, workspace)?;
        let retry_path = retry.path().to_owned();
        std::fs::write(retry.path().join("child"), b"cleanup")?;
        drop(retry);
        ensure!(
            !retry_path.try_exists()? && pool.usage().reserved_bytes == 0,
            "fresh retry cleanup failed"
        );

        // A relative Unicode parent resolves before sizing. No global chdir.
        let cwd = std::env::current_dir()?;
        let relative = unicode
            .strip_prefix(&cwd)
            .context("fixture must be beneath current directory")?;
        let workspace = Arc::new(Workspace::new(bytes));
        let relative_owner = create(relative, workspace.clone())?;
        ensure!(
            relative_owner.path().is_absolute()
                && relative_owner.path().as_os_str().len() == bytes
                && workspace.used() == bytes as u64,
            "relative Unicode parent changed boxed-path sizing"
        );
        drop(relative_owner);
        let mut trailing_parent = unicode.as_os_str().to_owned();
        trailing_parent.push(std::path::MAIN_SEPARATOR.to_string());
        let workspace = Arc::new(Workspace::new(bytes));
        let trailing_owner = create(Path::new(&trailing_parent), workspace.clone())?;
        ensure!(
            trailing_owner.path().as_os_str().len() == bytes && workspace.used() == bytes as u64,
            "trailing separator changed directory path sizing"
        );
        drop(trailing_owner);
        ensure!(
            workspace.used() == 0,
            "trailing parent leaked directory owner"
        );
        let missing = unicode.join("missing");
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        ensure!(
            create(&missing, workspace.clone()).is_err()
                && workspace.used() == 0
                && workspace.peak() > 0,
            "constructor failure leaked or skipped directory admission"
        );

        let resources = chopper_core::Resources {
            workers: 1,
            memory_mb: 32.into(),
            max_record_bytes: 1024 * 1024,
            temp_dir: Some(unicode.to_string_lossy().into_owned()),
            ..Default::default()
        };
        let pool = Arc::new(MemoryPool::new(1024 * 1024));
        let make_context = |resources: &chopper_core::Resources, cancelled| {
            Context::with_memory_pool(
                resources,
                Arc::new(AtomicBool::new(cancelled)),
                Arc::new(|_| {}),
                pool.clone(),
            )
        };
        ensure!(
            make_context(&resources, true).is_err()
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&unicode)?.next().is_none(),
            "cancelled directory construction leaked"
        );
        let invalid = chopper_core::Resources {
            temp_bytes: Some(0),
            ..resources.clone()
        };
        ensure!(
            make_context(&invalid, false).is_err()
                && pool.usage().reserved_bytes == 0
                && std::fs::read_dir(&unicode)?.next().is_none(),
            "early context failure leaked directory"
        );
        let ctx = make_context(&resources, false)?;
        let context_bytes = ctx.directory_reserved_bytes();
        ensure!(
            context_bytes == bytes as u64
                && ctx.workspace.used() == context_bytes
                && pool.usage().reserved_bytes == context_bytes,
            "idle context directory ownership mismatch"
        );
        let directory = ctx.dir.clone();
        let path = directory.path().to_owned();
        let clone = ctx.clone();
        drop(ctx);
        drop(clone);
        ensure!(
            pool.usage().reserved_bytes == context_bytes && path.is_dir(),
            "directory grant did not survive final context owner"
        );
        drop(directory);
        ensure!(
            pool.usage().reserved_bytes == 0 && !path.try_exists()?,
            "final directory Arc leaked path or grant"
        );
        let ctx = make_context(&resources, false)?;
        let mut stage = ctx.staging_directory(&unicode)?;
        let staging_bytes = stage.path().as_os_str().len() as u64;
        ensure!(
            ctx.directory_reserved_bytes() == context_bytes + staging_bytes
                && ctx.workspace.used() == context_bytes + staging_bytes,
            "staging directory ownership mismatch"
        );
        let stage_path = stage.path().to_owned();
        drop(stage);
        ensure!(
            !stage_path.try_exists()? && ctx.directory_reserved_bytes() == context_bytes,
            "unpublished staging directory leaked"
        );
        let mut pressure =
            Reservation::for_workspace(Arc::new(Workspace::shared(1024 * 1024, pool.clone())));
        pressure.resize((1024 * 1024 - context_bytes - staging_bytes + 1) as usize)?;
        let error = ctx
            .staging_directory(&unicode)
            .err()
            .context("staging grant must deny held sibling")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Shared { .. })
            ) && ctx.directory_reserved_bytes() == context_bytes
                && ctx.workspace.used() == context_bytes
                && std::fs::read_dir(&unicode)?.count() == 1,
            "staging denial created output or changed live owners"
        );
        drop(pressure);
        stage = ctx.staging_directory(&unicode)?;
        let final_path = unicode.join("published");
        std::fs::rename(stage.path(), &final_path)?;
        stage.published();
        ensure!(
            ctx.directory_reserved_bytes() == context_bytes
                && ctx.workspace.used() == context_bytes
                && final_path.is_dir(),
            "publication disarm lost directory ownership"
        );
        drop(stage);
        ensure!(final_path.is_dir(), "published directory was removed");
        std::fs::remove_dir_all(&final_path)?;
        drop(ctx);
        ensure!(
            pool.usage().reserved_bytes == 0 && std::fs::read_dir(&unicode)?.next().is_none(),
            "directory contract leaked"
        );
        drop(fixture);
        Ok(serde_json::json!({
            "contract": "retained-directory-path-resource-contract-v1",
            "local_edge_cases": 3, "shared_edge_cases": 3,
            "typed_local_denials": local_denials, "typed_shared_denials": shared_denials + 2,
            "retained_unicode_path_bytes": bytes, "context_path_bytes": context_bytes,
            "staging_path_bytes": staging_bytes,
            "held_sibling_release_retry": true, "relative_unicode_parent": true,
            "trailing_separator_parent": true, "staging_denial_release_retry": true,
            "constructor_error_cleanup": true, "cancelled_before_construction": true,
            "early_context_error_cleanup": true, "final_arc_owner_lifetime": true,
            "published_disarm": true, "final_reserved_bytes": 0
        }))
    }

    #[cfg(test)]
    mod tests {
        #[test]
        fn directory_path_shared_capacity_and_lifetime_contract() -> anyhow::Result<()> {
            super::run()?;
            Ok(())
        }
    }
}
