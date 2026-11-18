//! Optional limits-only Run observations. Fixed records contain no user text or row data.
use crate::storage::{Context, Reservation};
use serde::Serialize;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Unknown,
    Active,
    Completed,
    HandedOff,
    Interrupted,
    Failed,
}
#[derive(Clone, Copy, Debug, Serialize)]
pub struct Step {
    pub status: Status,
    pub rows: u64,
    pub seconds: f64,
}
#[derive(Clone, Copy, Debug, Serialize)]
pub struct Snapshot {
    pub read: Step,
    pub write: Step,
    pub unavailable: bool,
}
pub type Sink<'a> = &'a mut dyn FnMut(Snapshot) -> bool;

pub(crate) struct Observer<'a> {
    // Admission for callback serialization overlap and adapter scratch only.
    // Retained state is inline stack data; release before required CSV work.
    _grant: Reservation,
    sink: Sink<'a>,
    snapshot: Snapshot,
    started: [Option<Instant>; 2],
    last: Instant,
    enabled: bool,
}
impl<'a> Observer<'a> {
    pub(crate) fn new(ctx: &Context, sink: Sink<'a>) -> Option<Self> {
        let mut grant = Reservation::new(ctx);
        let step = Step {
            status: Status::Unknown,
            rows: 0,
            seconds: 0.0,
        };
        let mut snapshot = Snapshot {
            read: step,
            write: step,
            unavailable: false,
        };
        if grant.resize(8192).is_err() {
            snapshot.unavailable = true;
            sink(snapshot);
            return None;
        }
        Some(Self {
            _grant: {
                grant.resize(0).expect("release");
                grant
            },
            sink,
            snapshot,
            started: [None; 2],
            last: Instant::now(),
            enabled: true,
        })
    }
    pub(crate) fn update(&mut self, write: bool, status: Status, rows: u64, force: bool) {
        if !self.enabled {
            return;
        }
        let index = usize::from(write);
        let start = self.started[index].get_or_insert_with(Instant::now);
        let step = Step {
            status,
            rows,
            seconds: start.elapsed().as_secs_f64(),
        };
        if write {
            self.snapshot.write = step;
        } else {
            self.snapshot.read = step;
        }
        if force || self.last.elapsed() >= Duration::from_millis(100) {
            self.emit();
            self.last = Instant::now();
        }
    }
    fn emit(&mut self) {
        if self._grant.resize(8192).is_err() {
            self.snapshot.unavailable = true;
            (self.sink)(self.snapshot);
            self.enabled = false;
            return;
        }
        self.enabled = (self.sink)(self.snapshot);
        self._grant.resize(0).expect("release");
    }
}
impl Drop for Observer<'_> {
    fn drop(&mut self) {
        if !self.enabled {
            return;
        }
        let mut changed = false;
        for step in [&mut self.snapshot.read, &mut self.snapshot.write] {
            if step.status == Status::Active {
                step.status = Status::Interrupted;
                changed = true;
            }
        }
        if changed {
            self.emit();
        }
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) fn resource_contracts() -> anyhow::Result<serde_json::Value> {
    use crate::resources::MemoryPool;
    use std::sync::{atomic::AtomicBool, Arc};
    let pool = Arc::new(MemoryPool::new(1024 * 1024 * 1024));
    let resources = chopper_core::Resources {
        #[cfg(target_os = "wasi")]
        temp_dir: Some("/tmp".into()),
        ..Default::default()
    };
    let ctx = Context::with_memory_pool(
        &resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let before = pool.usage().reserved_bytes;
    // Leave exactly 8191 bytes of local working capacity: optional observer
    // admission must fail transactionally, emit unavailability, and not cancel.
    let mut held = Reservation::new(&ctx);
    held.resize(ctx.memory / 2 - before as usize - 8191)?;
    let occupied = pool.usage().reserved_bytes;
    let mut unavailable = false;
    let mut sink = |s: Snapshot| {
        unavailable = s.unavailable;
        true
    };
    assert!(Observer::new(&ctx, &mut sink).is_none());
    assert!(unavailable);
    assert_eq!(pool.usage().reserved_bytes, occupied);
    ctx.check()?;
    drop(held);
    let mut sink = |_| {
        assert_eq!(pool.usage().reserved_bytes, before + 8192);
        true
    };
    let mut observer = Observer::new(&ctx, &mut sink).expect("8192 bytes admitted");
    assert_eq!(pool.usage().reserved_bytes, before);
    observer.update(false, Status::Active, 0, true);
    assert_eq!(pool.usage().reserved_bytes, before);
    drop(observer);
    assert_eq!(pool.usage().reserved_bytes, before);
    let mut held = Reservation::new(&ctx);
    let mut later_unavailable = false;
    let mut sink = |snapshot: Snapshot| {
        later_unavailable = snapshot.unavailable;
        true
    };
    let mut observer = Observer::new(&ctx, &mut sink).expect("initial admission");
    held.resize(ctx.memory / 2 - before as usize - 8191)?;
    let occupied = pool.usage().reserved_bytes;
    observer.update(false, Status::Active, 0, true);
    assert_eq!(pool.usage().reserved_bytes, occupied);
    drop(observer);
    assert!(later_unavailable);
    ctx.check()?;
    drop(held);
    drop(ctx);
    assert_eq!(pool.usage().reserved_bytes, 0);
    Ok(serde_json::json!({"observer_bytes":8192,"denied_with_available_bytes":8191}))
}
#[cfg(test)]
mod tests {
    #[test]
    fn optional_admission_and_last_owner_release() {
        super::resource_contracts().unwrap();
    }
}

pub mod physical;
pub(crate) mod rows;
