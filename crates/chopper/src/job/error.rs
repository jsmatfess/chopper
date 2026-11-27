use crate::{
    cli_job::JobJsonPath,
    output::{DestinationError, OutputLimitError},
    profile::ProfileCancelled,
    resources::MemoryAdmission,
    storage::Cancelled,
};
use chopper_core::JobValidationError;
use serde::{ser::SerializeStruct, Serialize, Serializer};
use std::{fmt, io};

/// A Job failure with a stable code and available configuration location.
#[derive(Debug)]
pub struct Error {
    code: &'static str,
    source: anyhow::Error,
}

impl Error {
    pub(super) fn new(code: &'static str, source: anyhow::Error) -> Self {
        Self { code, source }
    }

    pub(super) fn decode(source: anyhow::Error) -> Self {
        use serde_json::error::Category;
        let code = match source
            .downcast_ref::<serde_json::Error>()
            .map(|e| e.classify())
        {
            Some(Category::Syntax | Category::Eof) => "json_syntax",
            Some(Category::Data) => "json_schema",
            Some(Category::Io) | None => "config_read",
        };
        Self::new(code, source)
    }

    pub(super) fn execution(source: anyhow::Error) -> Self {
        let code = if source.is::<Cancelled>()
            || source.is::<ProfileCancelled>()
            || source.chain().any(|error| {
                error
                    .downcast_ref::<io::Error>()
                    .and_then(io::Error::get_ref)
                    .is_some_and(|inner| inner.is::<Cancelled>() || inner.is::<ProfileCancelled>())
            }) {
            "cancelled"
        } else if source.is::<JobValidationError>() {
            "invalid_config"
        } else if source.is::<MemoryAdmission>() {
            "resource_limit"
        } else if source.is::<DestinationError>() {
            "destination"
        } else if source.is::<OutputLimitError>() {
            "record_limit"
        } else {
            "execution"
        };
        Self::new(code, source)
    }

    pub fn code(&self) -> &'static str {
        self.code
    }

    /// JSON Pointer to the failing field or enclosing object, if available.
    pub fn path(&self) -> Option<&str> {
        self.source
            .downcast_ref::<JobJsonPath>()
            .map(JobJsonPath::as_str)
            .or_else(|| {
                self.source
                    .downcast_ref::<JobValidationError>()
                    .map(JobValidationError::path)
            })
    }

    pub fn line(&self) -> Option<usize> {
        self.json_location().map(|error| error.line())
    }

    pub fn column(&self) -> Option<usize> {
        self.json_location().map(|error| error.column())
    }

    fn json_location(&self) -> Option<&serde_json::Error> {
        self.source
            .downcast_ref::<serde_json::Error>()
            .filter(|e| e.line() > 0)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:#}", self.source)
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.source.as_ref())
    }
}

impl Serialize for Error {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        struct Message<'a>(&'a Error);
        impl Serialize for Message<'_> {
            fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                serializer.collect_str(self.0)
            }
        }
        let mut fields = serializer.serialize_struct("Diagnostic", 5)?;
        fields.serialize_field("code", self.code())?;
        fields.serialize_field("path", &self.path())?;
        fields.serialize_field("message", &Message(self))?;
        fields.serialize_field("line", &self.line())?;
        fields.serialize_field("column", &self.column())?;
        fields.end()
    }
}
