use serde::{Serialize, Serializer};
use std::io::Write;

struct ErrorMessage<'a>(&'a anyhow::Error);

impl Serialize for ErrorMessage<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(&format_args!("{:#}", self.0))
    }
}

fn write_line(writer: &mut impl Write, value: &impl Serialize) -> bool {
    serde_json::to_writer(&mut *writer, value).is_ok() && writer.write_all(b"\n").is_ok()
}

pub(super) fn write_report<T: Serialize>(
    writer: &mut impl Write,
    result: anyhow::Result<T>,
) -> i32 {
    match result {
        Ok(value) => i32::from(!write_line(writer, &value)),
        Err(error) => {
            #[derive(Serialize)]
            struct ErrorReport<'a> {
                error: ErrorMessage<'a>,
            }

            let _ = write_line(
                writer,
                &ErrorReport {
                    error: ErrorMessage(&error),
                },
            );
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io;

    #[test]
    fn streamed_error_matches_legacy_line_and_handles_write_failure() {
        struct FailAfter {
            prefix: Vec<u8>,
            limit: usize,
        }

        impl Write for FailAfter {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                let written = bytes.len().min(self.limit - self.prefix.len());
                if written == 0 {
                    return Err(io::ErrorKind::BrokenPipe.into());
                }
                self.prefix.extend_from_slice(&bytes[..written]);
                Ok(written)
            }

            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }

        let error = || {
            anyhow::Error::msg("雪🦀\n\t\"\\\0".repeat(16_384)).context("read job JSON\ncontext")
        };
        let legacy = format!(
            "{}\n",
            serde_json::json!({"error": format!("{:#}", error())})
        );
        let mut actual = Vec::new();
        assert_eq!(write_report::<()>(&mut actual, Err(error())), 1);
        assert!(actual == legacy.as_bytes(), "report bytes changed");

        let mut sink = FailAfter {
            prefix: Vec::new(),
            limit: legacy.len() / 2,
        };
        assert_eq!(write_report::<()>(&mut sink, Err(error())), 1);
        assert!(
            sink.prefix == legacy.as_bytes()[..sink.limit],
            "prefix changed"
        );
    }
}
