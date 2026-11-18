//! Synchronous C allocator callbacks, with admission before each allocation.
use super::*;
use std::{
    alloc::{alloc, dealloc, Layout},
    ffi::c_void,
    ptr,
};

#[repr(C, align(16))]
#[derive(Clone, Copy)]
struct Header {
    charged: usize,
    payload: usize,
}

pub(super) struct State {
    memory: Reservation,
    pub(super) denial: Option<anyhow::Error>,
    pub(super) requests: usize,
    pub(super) frees: usize,
    pub(super) payload: usize,
    pub(super) peak_payload: usize,
    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(super) deny_at: Option<usize>,
}
impl State {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            memory,
            denial: None,
            requests: 0,
            frees: 0,
            payload: 0,
            peak_payload: 0,
            #[cfg(any(test, feature = "resource-contract-tests"))]
            deny_at: None,
        }
    }
    pub(super) fn reserved(&self) -> u64 {
        self.memory.bytes()
    }
}

// The C context and all legacy children use this same opaque UnsafeCell. Calls
// are synchronous and single-threaded; no Rust reference to State is held over
// a C call. Allocations carry their layout in an aligned prefix, avoiding an
// uncharged pointer map. This includes header bytes and growth overlap.
pub(super) unsafe extern "C" fn allocate(opaque: *mut c_void, bytes: usize) -> *mut c_void {
    let state = &mut *(*opaque.cast::<UnsafeCell<State>>()).get();
    state.requests = state.requests.saturating_add(1);
    if state.denial.is_some() {
        return ptr::null_mut();
    }
    #[cfg(any(test, feature = "resource-contract-tests"))]
    if state.deny_at == Some(state.requests) {
        state.denial = Some(crate::resources::MemoryAdmission::Local.into());
        return ptr::null_mut();
    }
    let Some(charged) = bytes.checked_add(std::mem::size_of::<Header>()) else {
        return ptr::null_mut();
    };
    let Ok(layout) = Layout::from_size_align(charged, std::mem::align_of::<Header>()) else {
        return ptr::null_mut();
    };
    let old = state.memory.bytes() as usize;
    let Some(total) = old.checked_add(charged) else {
        return ptr::null_mut();
    };
    if let Err(error) = state.memory.resize(total) {
        state.denial = Some(error);
        return ptr::null_mut();
    }
    let base = alloc(layout);
    if base.is_null() {
        let _ = state.memory.resize(old);
        return ptr::null_mut();
    }
    ptr::write(
        base.cast::<Header>(),
        Header {
            charged,
            payload: bytes,
        },
    );
    state.payload += bytes;
    state.peak_payload = state.peak_payload.max(state.payload);
    base.add(std::mem::size_of::<Header>()).cast()
}

pub(super) unsafe extern "C" fn release(opaque: *mut c_void, pointer: *mut c_void) {
    if pointer.is_null() {
        return;
    }
    let state = &mut *(*opaque.cast::<UnsafeCell<State>>()).get();
    let base = pointer.cast::<u8>().sub(std::mem::size_of::<Header>());
    let header = ptr::read(base.cast::<Header>());
    let layout = Layout::from_size_align_unchecked(header.charged, std::mem::align_of::<Header>());
    dealloc(base, layout);
    state.frees = state.frees.saturating_add(1);
    state.payload -= header.payload;
    let _ = state
        .memory
        .resize(state.memory.bytes() as usize - header.charged);
}
