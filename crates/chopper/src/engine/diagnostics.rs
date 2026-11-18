//! Admission before diagnostic tree construction; clones retain one immutable snapshot.
use super::*;
use crate::storage::{json_estimate::Estimator, JsonCapacity};
use shared_analysis::Shared;
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable retained diagnostic JSON. Clones share its tree and grant; JSON
/// remains unchanged apart from the explicit owner-admission diagnostic. Caller
/// construction/deserialization and explicit Value copies are outside admission.
///
/// ```compile_fail
/// fn grow(mut value:chopper::engine::Diagnostics) {
///     value["extra"] = serde_json::json!("unadmitted growth");
/// }
/// ```
#[derive(Clone, Default)]
pub struct Diagnostics(Shared<serde_json::Value>);
impl std::ops::Deref for Diagnostics {
    type Target = serde_json::Value;
    fn deref(&self) -> &Self::Target {
        self.0.get().unwrap_or(&serde_json::Value::Null)
    }
}
impl std::fmt::Debug for Diagnostics {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Debug::fmt(&**self, f)
    }
}
impl Serialize for Diagnostics {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        (**self).serialize(s)
    }
}
impl<'de> Deserialize<'de> for Diagnostics {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        serde_json::Value::deserialize(d).map(Self::from)
    }
}
impl From<serde_json::Value> for Diagnostics {
    fn from(value: serde_json::Value) -> Self {
        if value.is_null() {
            Self::default()
        } else {
            Self(Shared::caller_owned(value))
        }
    }
}
impl PartialEq for Diagnostics {
    fn eq(&self, other: &Self) -> bool {
        **self == **other
    }
}
impl PartialEq<serde_json::Value> for Diagnostics {
    fn eq(&self, other: &serde_json::Value) -> bool {
        **self == *other
    }
}

#[derive(Serialize)]
struct Fields {
    prepared_job_reserved_bytes: u64,
    analysis_preview_reserved_bytes: u64,
    analysis_warnings_reserved_bytes: u64,
    analysis_timings_reserved_bytes: u64,
    analysis_text_reserved_bytes: u64,
    stage_stats_reserved_bytes: u64,
    column_values_reserved_bytes: u64,
    input_header_reserved_bytes: u64,
    analysis_diagnostics_reserved_bytes: u64,
}
#[derive(Serialize)]
struct Source<'a, 'b> {
    #[serde(flatten)]
    context: &'a crate::storage::diagnostics::Snapshot<'b>,
    #[serde(flatten)]
    fields: Option<&'a Fields>,
}
enum Attempt {
    Need(usize),
    Built(serde_json::Value),
}
fn attempt(source: &impl Serialize, admitted: usize) -> Result<Attempt> {
    // Every supported source is a borrowed, stable view for both Serialize passes.
    let allowance = source.serialize(Estimator)?.bytes;
    if allowance > admitted {
        return Ok(Attempt::Need(allowance));
    }
    let value = serde_json::to_value(source)?;
    ensure!(
        value.json_capacity()? <= allowance,
        "diagnostic tree exceeds admitted capacity"
    );
    Ok(Attempt::Built(value))
}
impl Diagnostics {
    pub fn reserved_bytes(&self) -> u64 {
        self.0.reserved_bytes()
    }
    fn build(
        mut memory: Reservation,
        mut visit: impl FnMut(usize) -> Result<Attempt>,
    ) -> Result<Self> {
        loop {
            match visit(memory.bytes() as usize)? {
                // The visitor has released all audit/pressure locks here.
                Attempt::Need(bytes) => memory.resize(bytes)?,
                Attempt::Built(value) => {
                    memory.resize(value.json_capacity()?)?;
                    return Shared::admit(value, memory).map(Self);
                }
            }
        }
    }
    pub(super) fn analysis(ctx: &Context, job: &PreparedJob, analysis: &Analysis) -> Result<Self> {
        Self::capture(
            ctx,
            Some(Fields {
                prepared_job_reserved_bytes: job.reserved_bytes(),
                analysis_preview_reserved_bytes: analysis.preview.reserved_bytes(),
                analysis_warnings_reserved_bytes: analysis.warnings.reserved_bytes(),
                analysis_timings_reserved_bytes: analysis.timings.reserved_bytes(),
                analysis_text_reserved_bytes: analysis.text_reserved_bytes(),
                stage_stats_reserved_bytes: analysis.stages.reserved_bytes(),
                column_values_reserved_bytes: analysis.column_values.reserved_bytes(),
                input_header_reserved_bytes: analysis
                    .header
                    .as_ref()
                    .map_or(0, Header::reserved_bytes),
                analysis_diagnostics_reserved_bytes: 0,
            }),
        )
    }
    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(super) fn context(ctx: &Context) -> Result<Self> {
        Self::capture(ctx, None)
    }
    fn capture(ctx: &Context, fields: Option<Fields>) -> Result<Self> {
        let mut result = Self::build(Reservation::new(ctx), |admitted| {
            ctx.check()?;
            ctx.with_diagnostic_snapshot(|context| {
                attempt(
                    &Source {
                        context,
                        fields: fields.as_ref(),
                    },
                    admitted,
                )
            })
        })?;
        // Reconciliation/controller admission changed the live counts. Updating
        // existing numeric slots allocates nothing and leaves capacity unchanged.
        let reserved = result.reserved_bytes();
        let value = result
            .0
            .get_mut()
            .context("new diagnostic owner is shared")?;
        let (used, peak, process) = ctx.diagnostic_reservations();
        set(value, "workspace_reserved_bytes", used)?;
        set(value, "peak_workspace_reserved_bytes", peak)?;
        if let Some((used, peak)) = process {
            let process = value
                .get_mut("process_memory")
                .context("missing process snapshot")?;
            set(process, "reserved_bytes", used)?;
            set(process, "peak_reserved_bytes", peak)?;
        }
        if fields.is_some() {
            set(value, "analysis_diagnostics_reserved_bytes", reserved)?;
        }
        Ok(result)
    }
}
fn set(value: &mut serde_json::Value, key: &str, number: u64) -> Result<()> {
    *value
        .get_mut(key)
        .context("missing diagnostic numeric slot")? = number.into();
    Ok(())
}
