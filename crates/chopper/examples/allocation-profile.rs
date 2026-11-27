//! Opt-in allocation census: cargo run --release -p chopper-csv --example allocation-profile -- job.json
//! Uses the system allocator, counts requested bytes (not RSS), and publishes the job.
//! Add `profile` after the config path to measure a fresh full-file profile instead.
//! Global atomics perturb timing, especially with multiple workers: use normal builds for speed.
use anyhow::Result;
use chopper::{core::Job, engine};
use std::{
    alloc::{GlobalAlloc, Layout, System},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering::Relaxed},
        Arc,
    },
};

struct Census;
static ALLOCATIONS: AtomicU64 = AtomicU64::new(0);
static REALLOCATIONS: AtomicU64 = AtomicU64::new(0);
static REQUESTED: AtomicU64 = AtomicU64::new(0);
static LIVE: AtomicU64 = AtomicU64::new(0);
static PEAK: AtomicU64 = AtomicU64::new(0);
// <=32, <=128, <=512, <=4096, <=65536, larger; includes realloc requests.
static SIZES: [AtomicU64; 6] = [const { AtomicU64::new(0) }; 6];

fn request(size: usize) {
    REQUESTED.fetch_add(size as u64, Relaxed);
    let bucket = [32, 128, 512, 4096, 65536].partition_point(|&bound| size > bound);
    SIZES[bucket].fetch_add(1, Relaxed);
}
fn grow(size: usize) {
    let live = LIVE.fetch_add(size as u64, Relaxed) + size as u64;
    PEAK.fetch_max(live, Relaxed);
}
// No allocations, locks or unwinding inside the allocator callbacks.
unsafe impl GlobalAlloc for Census {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = System.alloc(layout);
        if !ptr.is_null() {
            ALLOCATIONS.fetch_add(1, Relaxed);
            request(layout.size());
            grow(layout.size());
        }
        ptr
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let ptr = System.alloc_zeroed(layout);
        if !ptr.is_null() {
            ALLOCATIONS.fetch_add(1, Relaxed);
            request(layout.size());
            grow(layout.size());
        }
        ptr
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        System.dealloc(ptr, layout);
        LIVE.fetch_sub(layout.size() as u64, Relaxed);
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let result = System.realloc(ptr, layout, size);
        if !result.is_null() {
            REALLOCATIONS.fetch_add(1, Relaxed);
            request(size);
            if size >= layout.size() {
                grow(size - layout.size());
            } else {
                LIVE.fetch_sub((layout.size() - size) as u64, Relaxed);
            }
        }
        result
    }
}
#[global_allocator]
static ALLOCATOR: Census = Census;

#[derive(Clone, Copy)]
struct Snapshot {
    allocations: u64,
    reallocations: u64,
    requested: u64,
    sizes: [u64; 6],
}
impl Snapshot {
    fn now() -> Self {
        Self {
            allocations: ALLOCATIONS.load(Relaxed),
            reallocations: REALLOCATIONS.load(Relaxed),
            requested: REQUESTED.load(Relaxed),
            sizes: std::array::from_fn(|i| SIZES[i].load(Relaxed)),
        }
    }
    fn since(self, before: Self) -> serde_json::Value {
        serde_json::json!({"allocations": self.allocations - before.allocations,
            "reallocations": self.reallocations - before.reallocations,
            "requested_bytes": self.requested - before.requested,
            "request_size_buckets": std::array::from_fn::<_, 6, _>(|i| self.sizes[i] - before.sizes[i])})
    }
}
fn main() -> Result<()> {
    let path = std::env::args_os()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("usage: allocation-profile job.json"))?;
    let job: Job = serde_json::from_slice(&std::fs::read(path)?)?;
    let before = Snapshot::now();
    if std::env::args_os().nth(2).as_deref() == Some(std::ffi::OsStr::new("profile")) {
        let mut cache = chopper::profile::ProfileCache::default();
        let profile = cache.profile(&job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
        let finished = Snapshot::now();
        let peak = PEAK.load(Relaxed);
        println!(
            "{}",
            serde_json::json!({"execution": profile.execution(), "profile": profile,
            "allocation_profile": {"whole_profile": finished.since(before),
                "process_peak_live_requested_bytes": peak,
                "size_bucket_upper_bounds": [32, 128, 512, 4096, 65536, null]}})
        );
        return Ok(());
    }
    let prepared = engine::prepare(job, Arc::new(AtomicBool::new(false)), Arc::new(|_| {}))?;
    // Keep the shared counters alive through publication. Timing censuses are
    // separate from uninstrumented jobs; the observer delays final context teardown.
    let diagnostic_context = prepared.ctx.clone();
    let ready = Snapshot::now();
    let analysis = prepared.execute()?;
    let finished = Snapshot::now();
    let peak = PEAK.load(Relaxed);
    let post_publication_diagnostics = diagnostic_context.diagnostics();
    let post_publication_peak_temp_bytes = diagnostic_context.peak();
    drop(diagnostic_context);
    println!(
        "{}",
        serde_json::json!({"analysis": analysis, "post_publication_diagnostics": post_publication_diagnostics, "post_publication_peak_temp_bytes": post_publication_peak_temp_bytes, "allocation_profile": {
        "prepare": ready.since(before), "publish": finished.since(ready), "whole_job": finished.since(before),
        "process_peak_live_requested_bytes": peak,
        "size_bucket_upper_bounds": [32, 128, 512, 4096, 65536, null]}})
    );
    Ok(())
}
