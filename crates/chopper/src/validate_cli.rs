use anyhow::{Context, Result};
use chopper::{
    cli_job::{DecodedJob, JobJsonPath},
    core::JobValidationError,
};
use serde::{ser::SerializeStruct, Serialize, Serializer};
use std::{
    fmt,
    io::{self, Write},
    path::Path,
};

#[derive(Serialize)]
struct Report {
    valid: bool,
    error: Option<Diagnostic>,
}

struct Diagnostic {
    code: &'static str,
    error: anyhow::Error,
    line: Option<usize>,
    column: Option<usize>,
}

struct ErrorMessage<'a>(&'a anyhow::Error);

impl fmt::Display for ErrorMessage<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:#}", self.0)
    }
}

impl Serialize for ErrorMessage<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl Serialize for Diagnostic {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut fields = serializer.serialize_struct("Diagnostic", 5)?;
        fields.serialize_field("code", self.code)?;
        fields.serialize_field("path", &self.path())?;
        fields.serialize_field("message", &ErrorMessage(&self.error))?;
        fields.serialize_field("line", &self.line)?;
        fields.serialize_field("column", &self.column)?;
        fields.end()
    }
}

impl Diagnostic {
    fn decode(error: anyhow::Error) -> Self {
        use serde_json::error::Category;
        let mut diagnostic = Self::new("config_read", error);
        if let Some(json) = diagnostic.error.downcast_ref::<serde_json::Error>() {
            diagnostic.code = match json.classify() {
                Category::Io => "config_read",
                Category::Syntax | Category::Eof => "json_syntax",
                Category::Data => "json_schema",
            };
            if json.line() > 0 {
                diagnostic.line = Some(json.line());
                diagnostic.column = Some(json.column());
            }
        }
        diagnostic
    }

    fn new(code: &'static str, error: anyhow::Error) -> Self {
        Self {
            code,
            error,
            line: None,
            column: None,
        }
    }

    fn path(&self) -> Option<&str> {
        self.error
            .downcast_ref::<JobJsonPath>()
            .map(JobJsonPath::as_str)
            .or_else(|| {
                self.error
                    .downcast_ref::<JobValidationError>()
                    .map(JobValidationError::path)
            })
    }
}

pub(super) fn run(config: &Path, json: bool) -> Result<bool> {
    let result = DecodedJob::read_with_diagnostics(config)
        .map_err(Diagnostic::decode)
        .and_then(|decoded| {
            decoded
                .job()
                .validate()
                .and_then(|()| decoded.job().validate_output())
                .map_err(|error| Diagnostic::new("invalid_config", error))
        });
    let report = Report {
        valid: result.is_ok(),
        error: result.err(),
    };
    if json {
        super::cli_json::write_pretty(&mut io::stdout().lock(), &report)?;
    } else if let Some(error) = &report.error {
        let mut stderr = io::stderr().lock();
        write!(
            stderr,
            "chopper: {}: {}",
            config.display(),
            ErrorMessage(&error.error)
        )
        .context("write validation diagnostic")?;
        if let Some(path) = error.path() {
            write!(stderr, " (field {path:?})").context("write validation field path")?;
        }
        writeln!(stderr).context("end validation diagnostic")?;
    } else {
        let mut stdout = io::stdout().lock();
        writeln!(stdout, "Configuration is valid.").context("write validation result")?;
        stdout.flush().context("flush validation result")?;
    }
    Ok(report.valid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn streamed_diagnostic_matches_legacy_json_bytes() -> Result<()> {
        #[derive(Serialize)]
        struct LegacyDiagnostic {
            code: &'static str,
            path: Option<String>,
            message: String,
            line: Option<usize>,
            column: Option<usize>,
        }

        let source = "雪\u{1f980}\n\"\t\\\0".repeat(16_384);
        let fixture = tempfile::NamedTempFile::new()?;
        let mut file = fixture.as_file();
        write!(file, "{{\"resources\":{{\"memory_mb\":")?;
        serde_json::to_writer(&mut file, &source)?;
        write!(file, "}}}}")?;

        let error = DecodedJob::read_with_diagnostics(fixture.path())
            .err()
            .context("fixture must produce a typed decode error")?;
        let expected = LegacyDiagnostic {
            code: "json_schema",
            path: Some("/resources/memory_mb".into()),
            message: format!("{error:#}"),
            line: Some(1),
            column: Some(
                error
                    .downcast_ref::<serde_json::Error>()
                    .context("missing serde source")?
                    .column(),
            ),
        };
        assert!(expected.message.contains("雪"));
        assert!(expected.message.len() > 64 * 1024);
        let mut legacy = Vec::new();
        super::super::cli_json::write_pretty(&mut legacy, &expected)?;
        let mut streamed = Vec::new();
        super::super::cli_json::write_pretty(&mut streamed, &Diagnostic::decode(error))?;
        assert!(streamed == legacy, "streaming changed diagnostic bytes");
        Ok(())
    }
}
