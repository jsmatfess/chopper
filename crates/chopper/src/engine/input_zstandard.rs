//! Zstandard input with per-allocation admission, including legacy children.
use super::*;
use std::{cell::UnsafeCell, io, ptr::NonNull};
use zstd::stream::raw::{InBuffer, OutBuffer, WriteBuf};
mod allocator;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

struct Operation<'a> {
    context: NonNull<zstd_sys::ZSTD_DCtx>,
    state: &'a UnsafeCell<allocator::State>,
}
impl<'a> Operation<'a> {
    fn new(state: &'a UnsafeCell<allocator::State>, window: u32) -> io::Result<Self> {
        let memory = zstd_sys::ZSTD_customMem {
            customAlloc: Some(allocator::allocate),
            customFree: Some(allocator::release),
            opaque: (state as *const UnsafeCell<allocator::State>)
                .cast_mut()
                .cast(),
        };
        // State is stable and lives beyond the C context and every callback.
        // The patched dispatch forwards this allocator to all legacy children.
        let context = unsafe { zstd_sys::ZSTD_createDCtx_advanced(memory) };
        let context =
            NonNull::new(context).ok_or_else(|| io::Error::from(io::ErrorKind::OutOfMemory))?;
        let mut operation = Self { context, state };
        operation.check(unsafe { zstd_sys::ZSTD_initDStream(context.as_ptr()) })?;
        operation.check(unsafe {
            zstd_sys::ZSTD_DCtx_loadDictionary(context.as_ptr(), std::ptr::null(), 0)
        })?;
        operation.check(unsafe {
            zstd_sys::ZSTD_DCtx_setParameter(
                context.as_ptr(),
                zstd_sys::ZSTD_dParameter::ZSTD_d_windowLogMax,
                window as i32,
            )
        })?;
        Ok(operation)
    }
    fn check(&mut self, code: usize) -> io::Result<usize> {
        // The callback borrow has ended before C returns. Admission is terminal
        // even if a codec attempted a fallback after a failed allocation.
        if unsafe { (&*self.state.get()).denial.is_some() } {
            return Err(io::ErrorKind::OutOfMemory.into());
        }
        if unsafe { zstd_sys::ZSTD_isError(code) } != 0 {
            return Err(io::Error::other(zstd_safe::get_error_name(code)));
        }
        Ok(code)
    }
}
impl Drop for Operation<'_> {
    fn drop(&mut self) {
        // Free all modern/legacy allocations before the opaque State can drop.
        unsafe {
            zstd_sys::ZSTD_freeDCtx(self.context.as_ptr());
        }
    }
}
impl zstd::stream::raw::Operation for Operation<'_> {
    fn run<C: WriteBuf + ?Sized>(
        &mut self,
        input: &mut InBuffer<'_>,
        output: &mut OutBuffer<'_, C>,
    ) -> io::Result<usize> {
        if unsafe { (&*self.state.get()).denial.is_some() } {
            return Err(io::ErrorKind::OutOfMemory.into());
        }
        let mut source = zstd_sys::ZSTD_inBuffer {
            src: input.src.as_ptr().cast(),
            size: input.src.len(),
            pos: input.pos(),
        };
        let mut destination = zstd_sys::ZSTD_outBuffer {
            dst: output.as_mut_ptr().cast(),
            size: output.capacity(),
            pos: output.pos(),
        };
        // Both buffers remain borrowed for this call, are disjoint, and C updates
        // positions only within their bounds. Match zstd-safe's cursor transfer.
        let code = unsafe {
            zstd_sys::ZSTD_decompressStream(self.context.as_ptr(), &mut destination, &mut source)
        };
        input.set_pos(source.pos);
        unsafe {
            output.set_pos(destination.pos);
        }
        self.check(code)
    }
    fn flush<C: WriteBuf + ?Sized>(&mut self, output: &mut OutBuffer<'_, C>) -> io::Result<usize> {
        self.run(&mut InBuffer::around(&[]), output)?;
        Ok(usize::from(output.pos() == output.capacity()))
    }
    fn reinit(&mut self) -> io::Result<()> {
        self.check(unsafe {
            zstd_sys::ZSTD_DCtx_reset(
                self.context.as_ptr(),
                zstd_sys::ZSTD_ResetDirective::ZSTD_reset_session_only,
            )
        })?;
        Ok(())
    }
    fn finish<C: WriteBuf + ?Sized>(
        &mut self,
        _output: &mut OutBuffer<'_, C>,
        finished_frame: bool,
    ) -> io::Result<usize> {
        if finished_frame {
            Ok(0)
        } else {
            Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "incomplete frame",
            ))
        }
    }
}

pub(super) fn consume<T>(
    file: File,
    job: &Job,
    buffer: Reservation,
    consume: impl FnOnce(Box<dyn Read + '_>) -> Result<T>,
) -> Result<T> {
    let memory = job
        .resources
        .memory_mb
        .as_mib()
        .map_or_else(|| buffer.effective_memory_bytes(), |mb| mb * 1024 * 1024);
    let window = (memory / 8).ilog2().min(30);
    let codec = buffer.sibling();
    let source = InputBuffer::new(file, zstd_safe::DCtx::in_size(), buffer)?;
    drive(source, window, codec, consume)
}

fn drive<R: BufRead, T>(
    source: R,
    window: u32,
    fixed: Reservation,
    consume: impl FnOnce(Box<dyn Read + '_>) -> Result<T>,
) -> Result<T> {
    drive_control(source, window, fixed, consume, |_| {}, |_| {})
}

fn drive_control<R: BufRead, T>(
    source: R,
    window: u32,
    mut fixed: Reservation,
    consume: impl FnOnce(Box<dyn Read + '_>) -> Result<T>,
    configure: impl FnOnce(&mut allocator::State),
    observe: impl FnOnce(&allocator::State),
) -> Result<T> {
    fixed.resize(fixed_capacity::<R>())?;
    let mut initial = allocator::State::new(fixed.sibling());
    configure(&mut initial);
    let state = Box::new(UnsafeCell::new(initial));
    let result = (|| {
        let operation = Operation::new(&state, window)?;
        // Reuse zstd-rs's reader state machine and its EOF/concatenation rules.
        consume(Box::new(zstd::stream::zio::Reader::new(source, operation)))
    })();
    let mut state = state.into_inner();
    debug_assert_eq!(state.reserved(), 0);
    observe(&state);
    if let Some(error) = state.denial.take() {
        return Err(error);
    }
    result
}

fn fixed_capacity<R>() -> usize {
    std::mem::size_of::<allocator::State>()
        + std::mem::size_of::<zstd::stream::zio::Reader<R, Operation<'static>>>()
}
