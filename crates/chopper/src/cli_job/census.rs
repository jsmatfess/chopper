use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::RefCell,
};

// Allocation observer is independent of the prefix implementation. A fixed
// pointer census counts requested layouts; realloc observes old + new before
// replacing the old entry. Fixture/pool/harness construction is outside it.
#[derive(Clone, Copy)]
struct Block {
    pointer: usize,
    size: usize,
}
pub(super) struct Census {
    pub(super) enabled: bool,
    checking: bool,
    grant: usize,
    pub(super) live: usize,
    peak: usize,
    #[cfg(all(test, target_os = "linux"))]
    requested: usize,
    violations: usize,
    pub(super) first_request: usize,
    blocks: [Block; 32768],
}
thread_local! {
    static CENSUS: RefCell<Census> = const { RefCell::new(Census {
        enabled: false, checking: false, grant: 0, live: 0, peak: 0, violations: 0, first_request: 0,
        #[cfg(all(test, target_os = "linux"))]
        requested: 0,
        blocks: [Block { pointer: 0, size: 0 }; 32768],
    }) };
}
pub(super) fn census(f: impl FnOnce(&mut Census)) {
    let _ = CENSUS.try_with(|cell| {
        if let Ok(mut c) = cell.try_borrow_mut() {
            f(&mut c);
        }
    });
}
fn allocated(pointer: *mut u8, size: usize) {
    census(|c| {
        if !c.enabled || pointer.is_null() {
            return;
        }
        if c.first_request == 0 {
            c.first_request = size;
        }
        let entry = c
            .blocks
            .iter_mut()
            .find(|b| b.pointer == 0)
            .expect("census exhausted");
        *entry = Block {
            pointer: pointer as usize,
            size,
        };
        c.live += size;
        #[cfg(all(test, target_os = "linux"))]
        {
            c.requested += size;
        }
        c.peak = c.peak.max(c.live);
        c.violations += usize::from(c.live > c.grant);
    });
}
fn freed(pointer: *mut u8) {
    census(|c| {
        if c.live == 0 {
            return;
        }
        if let Some(b) = c.blocks.iter_mut().find(|b| b.pointer == pointer as usize) {
            c.live -= b.size;
            *b = Block {
                pointer: 0,
                size: 0,
            };
        }
    });
}
struct Observer;
unsafe impl GlobalAlloc for Observer {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = System.alloc(layout);
        allocated(pointer, layout.size());
        pointer
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let pointer = System.alloc_zeroed(layout);
        allocated(pointer, layout.size());
        pointer
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        // Observe a hypothetical fresh layout while the old block remains live.
        census(|c| {
            if c.enabled && c.blocks.iter().any(|b| b.pointer == pointer as usize) {
                c.peak = c.peak.max(c.live + size);
                c.violations += usize::from(c.live + size > c.grant);
            }
        });
        let next = System.realloc(pointer, layout, size);
        if !next.is_null() {
            freed(pointer);
            allocated(next, size);
        }
        next
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        freed(pointer);
        System.dealloc(pointer, layout);
    }
}
#[global_allocator]
static OBSERVER: Observer = Observer;
pub(super) fn observe_grant(bytes: usize) {
    census(|c| {
        if c.checking {
            c.violations += usize::from(c.live > bytes);
            c.grant = bytes;
        }
    });
}
pub(crate) fn begin() {
    census(|c| {
        assert_eq!(c.live, 0);
        c.enabled = true;
        c.checking = true;
        c.grant = 0;
        c.peak = 0;
        #[cfg(all(test, target_os = "linux"))]
        {
            c.requested = 0;
        }
        c.violations = 0;
        c.first_request = 0;
    });
}
pub(crate) fn end() -> (usize, usize, usize) {
    let mut result = (0, 0, 0);
    census(|c| {
        c.enabled = false;
        c.checking = false;
        result = (c.live, c.peak, c.violations);
    });
    result
}

/// Successful allocation and replacement layouts requested in this observation.
#[cfg(all(test, target_os = "linux"))]
pub(crate) fn observed_allocation_requests() -> usize {
    let mut requested = 0;
    census(|c| requested = c.requested);
    requested
}
