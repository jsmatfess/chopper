//! Original output handles retained only until the bounded flush-all barrier.
use crate::storage::{Context, Reservation};
use anyhow::{Context as _, Result};
use std::fs::File;

pub(super) struct Queue {
    files: Vec<File>,
    // Destroy handles and their Vec before returning its capacity grant.
    memory: Reservation,
}
impl Queue {
    pub(super) fn new(ctx: &Context) -> Self {
        Self {
            files: Vec::new(),
            memory: Reservation::new(ctx),
        }
    }
    pub(super) fn take(&mut self, pending: &mut Option<File>) -> Result<()> {
        if pending.is_some() {
            let count = self
                .files
                .len()
                .checked_add(1)
                .context("sync queue overflow")?;
            self.memory.reserve_vec(&mut self.files, count)?;
            self.files.push(pending.take().unwrap());
        }
        Ok(())
    }
    pub(super) fn absorb(&mut self, other: &mut Self) -> Result<()> {
        if !other.files.is_empty() {
            let count = self
                .files
                .len()
                .checked_add(other.files.len())
                .context("sync queue overflow")?;
            self.memory.reserve_vec(&mut self.files, count)?;
            self.files.append(&mut other.files);
        }
        Ok(())
    }
    pub(super) fn sync(&mut self, ctx: &Context) -> Result<()> {
        // On failure the drain drops every remaining handle before publication
        // and before the queue grant/stage owners can be destroyed.
        for file in self.files.drain(..) {
            ctx.check()?;
            file.sync_all().context("synchronizing final output")?;
        }
        Ok(())
    }
    #[cfg(all(test, target_os = "linux"))]
    pub(super) fn len(&self) -> usize {
        self.files.len()
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use chopper_core::Resources;
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    };

    #[test]
    fn denied_transfer_retains_source_and_error_or_cancel_drains_every_handle() -> Result<()> {
        for mode in ["denial", "error", "cancel", "success"] {
            let dir = tempfile::tempdir()?;
            let resources = Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                temp_dir: Some(dir.path().to_string_lossy().into()),
                ..Default::default()
            };
            let cancel = Arc::new(AtomicBool::new(false));
            let pool = Arc::new(crate::resources::MemoryPool::new(32 * 1024 * 1024));
            let ctx = Context::with_memory_pool(
                &resources,
                cancel.clone(),
                Arc::new(|_| {}),
                pool.clone(),
            )?;
            let before = ctx.diagnostics()["workspace_reserved_bytes"]
                .as_u64()
                .unwrap();
            let mut queue = Queue::new(&ctx);
            let mut file = Some(File::create(dir.path().join("data"))?);
            let mut held = Reservation::new(&ctx);
            if mode == "denial" {
                held.resize(ctx.memory / 2 - before as usize)?;
                assert!(queue.take(&mut file).is_err());
                assert!(file.is_some());
                assert_eq!(queue.len(), 0);
            } else {
                queue.take(&mut file)?;
                assert!(file.is_none());
                if mode == "error" {
                    queue.take(&mut Some(File::open("/dev/null")?))?;
                    queue.take(&mut Some(File::create(dir.path().join("remaining"))?))?;
                }
                if mode == "cancel" {
                    cancel.store(true, Ordering::SeqCst);
                }
                let result = queue.sync(&ctx);
                assert_eq!(result.is_ok(), mode == "success");
                assert_eq!(queue.len(), 0);
                cancel.store(false, Ordering::SeqCst);
                queue.sync(&ctx)?; // Empty second guard never duplicates a sync.
            }
            drop(file);
            drop(queue);
            drop(held);
            assert_eq!(ctx.diagnostics()["workspace_reserved_bytes"], before);
            ctx.check()?;
            drop(ctx);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }
}
