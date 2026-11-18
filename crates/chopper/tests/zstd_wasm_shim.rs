#![cfg(not(target_arch = "wasm32"))]

extern crate alloc;

use std::{
    alloc::{GlobalAlloc, Layout, System},
    cell::Cell,
    mem::{align_of, size_of},
    ptr::null_mut,
};

#[rustfmt::skip] // Preserve the vendored upstream formatting.
#[path = "../../../vendor/zstd-sys-2.1.1/src/wasm_shim.rs"]
mod wasm_shim;
use wasm_shim::{
    rust_zstd_wasm_shim_calloc as calloc, rust_zstd_wasm_shim_free as free,
    rust_zstd_wasm_shim_malloc as malloc,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Probe {
    Idle,
    FailAlloc(Layout),
    FailZeroed(Layout),
    Free(Layout),
    Observed,
}

thread_local! {
    // Only intercept the expected callback on the calling test thread.
    static PROBE: Cell<Probe> = const { Cell::new(Probe::Idle) };
}

fn observe(callback: Probe) -> bool {
    PROBE
        .try_with(|probe| {
            if probe.get() == callback {
                probe.set(Probe::Observed);
                true
            } else {
                false
            }
        })
        .unwrap_or(false)
}

struct TestAllocator;

// SAFETY: Successful allocations and all deallocations use System with the
// caller's original layout. The armed callback can fail once by returning NULL.
unsafe impl GlobalAlloc for TestAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        if observe(Probe::FailAlloc(layout)) {
            null_mut()
        } else {
            unsafe { System.alloc(layout) }
        }
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        if observe(Probe::FailZeroed(layout)) {
            null_mut()
        } else {
            unsafe { System.alloc_zeroed(layout) }
        }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        observe(Probe::Free(layout));
        unsafe { System.dealloc(ptr, layout) };
    }
}

#[global_allocator]
static ALLOCATOR: TestAllocator = TestAllocator;

fn expect_callback<T>(callback: Probe, call: impl FnOnce() -> T) -> T {
    PROBE.set(callback);
    let result = call();
    assert_eq!(PROBE.replace(Probe::Idle), Probe::Observed, "{callback:?}");
    result
}

const PAYLOAD: [u8; 21] = *b"shim allocation bytes";

fn allocation_layout() -> Layout {
    Layout::from_size_align(PAYLOAD.len() + size_of::<usize>(), align_of::<usize>()).unwrap()
}

#[test]
fn reports_underlying_allocator_failure() {
    let layout = allocation_layout();
    assert!(expect_callback(Probe::FailAlloc(layout), || malloc(PAYLOAD.len())).is_null());
    assert!(expect_callback(Probe::FailZeroed(layout), || calloc(3, 7)).is_null());
}

#[test]
fn rejects_invalid_sizes_and_accepts_null_free() {
    assert!(calloc(usize::MAX / 2 + 1, 2).is_null(), "calloc overflow");
    assert!(malloc(usize::MAX).is_null(), "header overflow");
    assert!(
        malloc(isize::MAX as usize - size_of::<usize>()).is_null(),
        "alignment would exceed the Layout size bound"
    );
    // SAFETY: The shim accepts a null pointer.
    unsafe { free(null_mut()) };
}

#[test]
fn preserves_zeroing_bytes_and_deallocation_layout() {
    for (ptr, zeroed) in [(malloc(PAYLOAD.len()), false), (calloc(3, 7), true)] {
        assert!(!ptr.is_null());
        let bytes = ptr.cast::<u8>();
        // SAFETY: Each successful call owns PAYLOAD.len() writable bytes. Only
        // calloc is read before the test initializes the bytes.
        unsafe {
            if zeroed {
                assert_eq!(
                    std::slice::from_raw_parts(bytes, PAYLOAD.len()),
                    &[0; PAYLOAD.len()]
                );
            }
            bytes.copy_from_nonoverlapping(PAYLOAD.as_ptr(), PAYLOAD.len());
            assert_eq!(std::slice::from_raw_parts(bytes, PAYLOAD.len()), PAYLOAD);
            expect_callback(Probe::Free(allocation_layout()), || free(ptr));
        }
    }
}
