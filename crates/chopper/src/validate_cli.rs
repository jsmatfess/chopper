use anyhow::{Context, Result};
use chopper::job::{Error, Job};
use serde::Serialize;
use std::{
    io::{self, Write},
    path::Path,
};

#[derive(Serialize)]
struct Report {
    valid: bool,
    error: Option<Error>,
}

pub(super) fn run(config: &Path, json: bool) -> Result<bool> {
    let result = Job::load(config).and_then(|job| job.validate());
    let report = Report {
        valid: result.is_ok(),
        error: result.err(),
    };
    if json {
        super::cli_json::write_pretty(&mut io::stdout().lock(), &report)?;
    } else if let Some(error) = &report.error {
        let mut stderr = io::stderr().lock();
        write!(stderr, "chopper: {}: {}", config.display(), error)
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
    use chopper::cli_job::DecodedJob;

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
        super::super::cli_json::write_pretty(
            &mut streamed,
            &Job::load(fixture.path())
                .err()
                .context("expected a Job decode error")?,
        )?;
        assert!(streamed == legacy, "streaming changed diagnostic bytes");
        Ok(())
    }
}
