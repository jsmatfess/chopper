use anyhow::{Context, Result};
use serde::Serialize;
use std::{
    fmt,
    io::{self, Write},
};

#[derive(Debug)]
pub(super) struct PublishedReportFailure;

impl fmt::Display for PublishedReportFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("output committed, but delivery of the stdout report failed. Check the manifest and result files in the configured destination before retrying")
    }
}

/// Use only after the engine has committed the native destination.
pub(super) fn write_published<T: Serialize + ?Sized>(response: &T) -> Result<()> {
    write_pretty(&mut io::stdout().lock(), response).context(PublishedReportFailure)
}

/// Borrow the response so its payload owners remain alive throughout output.
/// A stdout failure can leave a JSON prefix.
pub(super) fn write_pretty<W: Write, T: Serialize + ?Sized>(
    writer: &mut W,
    response: &T,
) -> Result<()> {
    serde_json::to_writer_pretty(&mut *writer, response).context("write CLI JSON")?;
    writer.write_all(b"\n").context("write CLI JSON newline")?;
    writer.flush().context("flush CLI JSON")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        alloc::{GlobalAlloc, Layout, System},
        cell::Cell,
        io,
    };

    struct ObservedAllocator;
    thread_local! {
        // Only allocations on the observing test thread count; fixture construction
        // and the test harness stay outside the observation window.
        static REQUESTED: Cell<Option<usize>> = const { Cell::new(None) };
    }
    fn record(size: usize) {
        let _ = REQUESTED.try_with(|requested| {
            if let Some(total) = requested.get() {
                requested.set(Some(total.saturating_add(size)));
            }
        });
    }
    unsafe impl GlobalAlloc for ObservedAllocator {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            record(layout.size());
            System.alloc(layout)
        }
        unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
            record(layout.size());
            System.alloc_zeroed(layout)
        }
        unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
            record(size);
            System.realloc(ptr, layout, size)
        }
        unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
            System.dealloc(ptr, layout)
        }
    }
    #[global_allocator]
    static ALLOCATOR: ObservedAllocator = ObservedAllocator;

    #[derive(Serialize)]
    struct Payload {
        escaped: String,
        unicode: String,
        empty: Vec<String>,
        large: String,
    }
    fn payload(repetitions: usize) -> Payload {
        Payload {
            escaped: "\"\\\n\r\t\0".into(),
            unicode: "雪 café 🦀".into(),
            empty: vec![],
            large: "x\n雪\"".repeat(repetitions),
        }
    }

    #[derive(Default)]
    struct CountingSink {
        bytes: usize,
        flushes: usize,
    }
    impl Write for CountingSink {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.bytes += bytes.len();
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            self.flushes += 1;
            Ok(())
        }
    }

    #[test]
    fn large_preconstructed_payload_has_bounded_output_allocation() {
        let response = payload(1024 * 1024);
        // Reference encoding is deliberately outside observation too.
        let expected_bytes = serde_json::to_string_pretty(&response).unwrap().len() + 1;
        let mut sink = CountingSink::default();
        REQUESTED.with(|requested| requested.set(Some(0)));
        let result = write_pretty(&mut sink, &response);
        let requested = REQUESTED.with(|requested| requested.replace(None).unwrap());
        result.unwrap();
        assert_eq!(sink.bytes, expected_bytes);
        assert_eq!(sink.flushes, 1);
        assert!(requested <= 16 * 1024, "requested {requested} output bytes");
        // This bounds observed requests for this success path, not RSS or all
        // serializer/error/runtime internals, and excludes the source payload.
    }

    struct ShortWriter {
        bytes: Vec<u8>,
        remaining: usize,
        zero: bool,
        fail_flush: bool,
        flushes: usize,
    }
    impl Write for ShortWriter {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.remaining == 0 {
                return if self.zero {
                    Ok(0)
                } else {
                    Err(io::Error::new(io::ErrorKind::BrokenPipe, "injected write"))
                };
            }
            let count = bytes.len().min(3).min(self.remaining);
            self.bytes.extend_from_slice(&bytes[..count]);
            self.remaining -= count;
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            self.flushes += 1;
            if self.fail_flush {
                Err(io::Error::other("injected flush"))
            } else {
                Ok(())
            }
        }
    }
    fn writer(remaining: usize) -> ShortWriter {
        ShortWriter {
            bytes: vec![],
            remaining,
            zero: false,
            fail_flush: false,
            flushes: 0,
        }
    }

    #[test]
    fn short_writes_preserve_pretty_bytes_and_one_newline() {
        for repetitions in [0, 1, 64 * 1024] {
            let response = payload(repetitions);
            let expected = format!("{}\n", serde_json::to_string_pretty(&response).unwrap());
            let mut sink = writer(usize::MAX);
            write_pretty(&mut sink, &response).unwrap();
            assert_eq!(sink.bytes, expected.as_bytes());
            assert_eq!(sink.flushes, 1);
        }
    }

    #[test]
    fn write_zero_and_errors_in_json_newline_and_flush_propagate() {
        let response = payload(1);
        let json = serde_json::to_string_pretty(&response).unwrap();
        for zero in [false, true] {
            for limit in [0, 5, json.len()] {
                let mut sink = writer(limit);
                sink.zero = zero;
                let error = write_pretty(&mut sink, &response).unwrap_err();
                let kind = error
                    .chain()
                    .find_map(|e| {
                        e.downcast_ref::<io::Error>()
                            .map(io::Error::kind)
                            .or_else(|| {
                                e.downcast_ref::<serde_json::Error>()
                                    .and_then(serde_json::Error::io_error_kind)
                            })
                    })
                    .unwrap();
                assert_eq!(
                    kind,
                    if zero {
                        io::ErrorKind::WriteZero
                    } else {
                        io::ErrorKind::BrokenPipe
                    }
                );
                assert_eq!(sink.bytes, json.as_bytes()[..limit]);
                assert_eq!(sink.flushes, 0);
                assert!(error.to_string().contains(if limit == json.len() {
                    "newline"
                } else {
                    "write CLI JSON"
                }));
            }
        }
        let mut sink = writer(usize::MAX);
        sink.fail_flush = true;
        let error = write_pretty(&mut sink, &response).unwrap_err();
        assert!(error.to_string().contains("flush CLI JSON"));
        assert_eq!(sink.bytes, format!("{json}\n").as_bytes());
        assert_eq!(sink.flushes, 1);
    }

    #[test]
    fn successful_serialization_has_no_duplicate_preflight() {
        struct Counted<'a> {
            payload: &'a Payload,
            visits: Cell<usize>,
        }
        impl Serialize for Counted<'_> {
            fn serialize<S: serde::Serializer>(
                &self,
                serializer: S,
            ) -> std::result::Result<S::Ok, S::Error> {
                self.visits.set(self.visits.get() + 1);
                self.payload.serialize(serializer)
            }
        }
        let payload = payload(1);
        let response = Counted {
            payload: &payload,
            visits: Cell::new(0),
        };
        let mut sink = CountingSink::default();
        write_pretty(&mut sink, &response).unwrap();
        assert_eq!(response.visits.get(), 1);
        assert_eq!(sink.flushes, 1);
    }

    #[test]
    fn serializer_is_visited_once_and_its_error_propagates() {
        struct Failing(Cell<usize>);
        impl Serialize for Failing {
            fn serialize<S: serde::Serializer>(
                &self,
                _: S,
            ) -> std::result::Result<S::Ok, S::Error> {
                self.0.set(self.0.get() + 1);
                Err(serde::ser::Error::custom("injected serialization"))
            }
        }
        let response = Failing(Cell::new(0));
        let mut sink = CountingSink::default();
        let error = write_pretty(&mut sink, &response).unwrap_err();
        assert!(format!("{error:#}").contains("injected serialization"));
        assert_eq!(response.0.get(), 1);
        assert_eq!(sink.bytes, 0);
        assert_eq!(sink.flushes, 0);
    }
}
