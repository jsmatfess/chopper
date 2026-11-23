use anyhow::{Context, Result};
use chopper::{
    cli_job::{DecodedJob, JobJsonPath},
    core::JobValidationError,
};
use serde::Serialize;
use std::{
    io::{self, Write},
    path::Path,
};

#[derive(Serialize)]
struct Report {
    valid: bool,
    error: Option<Diagnostic>,
}

#[derive(Serialize)]
struct Diagnostic {
    code: &'static str,
    path: Option<String>,
    message: String,
    line: Option<usize>,
    column: Option<usize>,
}

impl Diagnostic {
    fn decode(error: anyhow::Error) -> Self {
        use serde_json::error::Category;
        let mut diagnostic = Self::new("config_read", &error);
        if let Some(json) = error.downcast_ref::<serde_json::Error>() {
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
        diagnostic.path = error
            .downcast_ref::<JobJsonPath>()
            .map(|path| path.as_str().into());
        diagnostic
    }

    fn new(code: &'static str, error: &anyhow::Error) -> Self {
        Self {
            code,
            path: None,
            message: format!("{error:#}"),
            line: None,
            column: None,
        }
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
                .map_err(|error| {
                    let mut diagnostic = Diagnostic::new("invalid_config", &error);
                    diagnostic.path = error
                        .downcast_ref::<JobValidationError>()
                        .map(|error| error.path().into());
                    diagnostic
                })
        });
    let report = Report {
        valid: result.is_ok(),
        error: result.err(),
    };
    if json {
        super::cli_json::write_pretty(&mut io::stdout().lock(), &report)?;
    } else if let Some(error) = &report.error {
        let mut stderr = io::stderr().lock();
        write!(stderr, "chopper: {}: {}", config.display(), error.message)
            .context("write validation diagnostic")?;
        if let Some(path) = &error.path {
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
