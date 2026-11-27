use super::{percentage_weight, Column, Compression, Job, Operation, Resources};
use anyhow::Result;
use std::{borrow::Cow, error::Error, fmt};

/// The field associated with a config-only validation failure.
#[derive(Debug)]
pub struct JobValidationError {
    path: Cow<'static, str>,
    cause: anyhow::Error,
}

impl JobValidationError {
    fn new(path: impl Into<Cow<'static, str>>, cause: anyhow::Error) -> Self {
        Self {
            path: path.into(),
            cause,
        }
    }

    /// JSON Pointer using the canonical Job field names.
    pub fn path(&self) -> &str {
        &self.path
    }
}

impl fmt::Display for JobValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&self.cause, formatter)
    }
}

impl Error for JobValidationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        self.cause.source()
    }
}

macro_rules! ensure_field {
    ($condition:expr, $path:expr, $message:literal) => {
        if !$condition {
            return Err(JobValidationError::new($path, anyhow::anyhow!($message)).into());
        }
    };
}

impl Resources {
    /// Check the configured cap before comparing it with actual storage.
    pub fn validate_temp_bytes(&self) -> Result<()> {
        ensure_field!(
            self.temp_bytes != Some(0),
            "/resources/temp_bytes",
            "temp_bytes must be positive"
        );
        Ok(())
    }

    /// Validate a resolved budget without changing the requested configuration.
    pub fn validate_effective_memory(&self, memory_mb: u64) -> Result<()> {
        ensure_field!(
            (32..=1_048_576).contains(&memory_mb),
            "/resources/memory_mb",
            "memory_mb must be between 32 and 1048576"
        );
        ensure_field!(
            (1..=memory_mb * 1024 * 1024 / 16).contains(&(self.max_record_bytes as u64)),
            "/resources/max_record_bytes",
            "max_record_bytes must fit within 1/16 of memory budget"
        );
        ensure_field!(
            self.workers <= 64 && self.workers as u64 <= memory_mb / 8,
            "/resources/workers",
            "workers must be 0 (automatic) or at most min(64, memory_mb/8)"
        );
        Ok(())
    }
}

impl Job {
    /// Check configuration values and cross-field rules without accessing any job paths.
    pub fn validate(&self) -> Result<()> {
        self.validate_configuration(true)
    }

    /// Execution prepares formulas under its own reservation.
    pub fn validate_for_execution(&self) -> Result<()> {
        self.validate_configuration(false)
    }

    fn validate_configuration(&self, prepare_formulas: bool) -> Result<()> {
        ensure_field!(
            self.version == super::JOB_VERSION,
            "/version",
            "unsupported configuration version"
        );
        ensure_field!(!self.input.is_empty(), "/input", "input path is required");
        ensure_field!(
            self.input_dialect
                .comment_prefix
                .as_deref()
                .is_none_or(|prefix| {
                    !prefix.is_empty() && !prefix.contains(['\0', '\r', '\n'])
                }),
            "/input_dialect/comment_prefix",
            "comment prefix must be nonempty and cannot contain NUL or a line ending"
        );
        if let Some(memory_mb) = self.resources.memory_mb.as_mib() {
            self.resources.validate_effective_memory(memory_mb)?;
        } else {
            ensure_field!(
                self.resources.max_record_bytes > 0,
                "/resources/max_record_bytes",
                "max_record_bytes must fit within 1/16 of memory budget"
            );
            ensure_field!(
                self.resources.workers <= 64,
                "/resources/workers",
                "workers must be 0 (automatic) or at most min(64, memory_mb/8)"
            );
        }
        ensure_field!(
            self.resources.max_files > 0,
            "/resources/max_files",
            "max_files must be positive"
        );
        self.resources.validate_temp_bytes()?;
        ensure_field!(
            self.operations.len() <= 64,
            "/operations",
            "at most 64 operations are supported per job"
        );
        for (path, cap) in [
            ("/limits/rows", self.limits.rows),
            ("/limits/bytes", self.limits.bytes),
            ("/limits/compressed_bytes", self.limits.compressed_bytes),
        ] {
            ensure_field!(cap != Some(0), path, "limits must be positive");
        }
        if self.limits.compressed_bytes.is_some() {
            ensure_field!(
                self.compression != Compression::None,
                "/limits/compressed_bytes",
                "compressed_bytes requires output compression"
            );
        }
        for (path, settings) in [
            ("/input_csv", &self.input_csv),
            ("/output_csv", &self.output_csv),
        ] {
            for (field, value) in [
                ("delimiter", Some(settings.delimiter)),
                ("quote", Some(settings.quote)),
                ("escape", settings.escape),
            ] {
                ensure_field!(
                    value.is_none_or(|ch| ch.is_ascii() && !matches!(ch, '\r' | '\n' | '\0')),
                    format!("{path}/{field}"),
                    "CSV delimiter, quote and escape must be non-newline ASCII characters"
                );
            }
            ensure_field!(
                settings.delimiter != settings.quote,
                format!("{path}/quote"),
                "delimiter and quote must differ"
            );
            ensure_field!(
                settings.escape != Some(settings.delimiter)
                    && settings.escape != Some(settings.quote),
                format!("{path}/escape"),
                "escape must differ from delimiter and quote; omit escape for doubled quotes"
            );
            ensure_field!(
                super::LINE_ENDINGS.contains(&settings.line_ending.as_str()),
                format!("{path}/line_ending"),
                "line_ending must be lf or crlf"
            );
            let encoding = crate::csv::encoding(&settings.encoding)
                .map_err(|cause| JobValidationError::new(format!("{path}/encoding"), cause))?;
            if path == "/output_csv" && settings.bom {
                crate::csv::bom_bytes(encoding)
                    .map_err(|cause| JobValidationError::new("/output_csv/bom", cause))?;
            }
        }
        ensure_field!(
            !self.output_csv.headers || self.input_csv.headers,
            "/output_csv/headers",
            "cannot copy a header from headerless input; disable output headers"
        );
        ensure_field!(
            self.calculated_columns.len() <= 64,
            "/calculated_columns",
            "at most 64 calculated columns are supported"
        );
        for (index, column) in self.calculated_columns.iter().enumerate() {
            ensure_field!(
                !column.name.is_empty()
                    && !self.calculated_columns[..index]
                        .iter()
                        .any(|prior| prior.name == column.name),
                format!("/calculated_columns/{index}/name"),
                "calculated column names must be nonempty and unique"
            );
            ensure_field!(
                !column.expression.trim().is_empty()
                    && column.expression.len() <= crate::expression::MAX_SOURCE_BYTES,
                format!("/calculated_columns/{index}/expression"),
                "calculated column formula is empty or exceeds the size limit"
            );
            if prepare_formulas {
                crate::expression::Expression::parse(&column.expression).map_err(|cause| {
                    JobValidationError::new(
                        format!("/calculated_columns/{index}/expression"),
                        anyhow::anyhow!(cause),
                    )
                })?;
            }
        }
        for (index, op) in self.operations.iter().enumerate() {
            match op {
                Operation::Balanced { files } | Operation::Interleaved { files } => ensure_field!(
                    *files > 0 && *files <= self.resources.max_files,
                    format!("/operations/{index}/files"),
                    "balanced file count must be positive and at most max_files"
                ),
                Operation::Partition { columns } => {
                    ensure_field!(
                        !columns.is_empty(),
                        format!("/operations/{index}/columns"),
                        "partition requires columns"
                    );
                }
                Operation::Assign { groups, .. }
                | Operation::AssignProbabilistic { groups, .. } => {
                    ensure_field!(
                        !groups.is_empty() && groups.len() <= 1024,
                        format!("/operations/{index}/groups"),
                        "allocation needs 1 to 1024 groups"
                    );
                    for (i, group) in groups.iter().enumerate() {
                        ensure_field!(
                            !group.name.is_empty()
                                && !groups[..i]
                                    .iter()
                                    .any(|previous| previous.name == group.name),
                            format!("/operations/{index}/groups/{i}/name"),
                            "allocation names must be nonempty and unique"
                        );
                    }
                    let mut total = 0;
                    for (i, group) in groups.iter().enumerate() {
                        total += percentage_weight(&group.percent).map_err(|cause| {
                            JobValidationError::new(
                                format!("/operations/{index}/groups/{i}/percent"),
                                cause,
                            )
                        })?;
                    }
                    ensure_field!(
                        total == 100_000_000,
                        format!("/operations/{index}/groups"),
                        "percentages must sum exactly to 100"
                    );
                }
                Operation::Shuffle { .. } => {}
            }
            if !self.input_csv.headers {
                let (field, selectors) = match op {
                    Operation::Partition { columns } => ("columns", columns),
                    Operation::Assign { strata, .. }
                    | Operation::AssignProbabilistic { strata, .. } => ("strata", strata),
                    _ => continue,
                };
                for (selector, column) in selectors.iter().enumerate() {
                    ensure_field!(
                        matches!(column, Column::Index(_))
                            || self.calculated_columns.iter().any(|calculated| {
                                matches!(column, Column::Name(name) if *name == calculated.name)
                            }),
                        format!("/operations/{index}/{field}/{selector}"),
                        "name selection requires headers"
                    );
                }
            }
        }
        Ok(())
    }

    /// Require an output path for commands intended to publish a result.
    pub fn validate_output(&self) -> Result<()> {
        ensure_field!(
            !self.output.is_empty(),
            "/output",
            "output path is required"
        );
        Ok(())
    }
}
