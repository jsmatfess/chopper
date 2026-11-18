//! Admission for the existing canonical job-manifest JSON tree.
use super::*;
use serde::Serialize;
mod estimate;

#[derive(Serialize)]
struct JobRecord<'a> {
    #[serde(rename = "type")]
    kind: &'static str,
    schema_version: u32,
    algorithm_version: &'static str,
    config: &'a Job,
    analysis: &'a crate::engine::Analysis,
    application_version: &'static str,
}
impl<'a> JobRecord<'a> {
    fn new(job: &'a Job, analysis: &'a crate::engine::Analysis) -> Self {
        Self {
            kind: "job",
            schema_version: 1,
            algorithm_version: crate::engine::Analysis::algorithm_version_for(job),
            config: job,
            analysis,
            application_version: env!("CARGO_PKG_VERSION"),
        }
    }
}

pub(super) struct ManifestTree {
    value: serde_json::Value,
    // The complete/partial tree is destroyed before its construction grant.
    _memory: Reservation,
}
impl ManifestTree {
    pub(super) fn build(
        job: &Job,
        analysis: &crate::engine::Analysis,
        memory: Reservation,
    ) -> Result<Self> {
        let source = JobRecord::new(job, analysis);
        Self::from_serializable(&source, memory)
    }

    fn from_serializable(source: &impl Serialize, mut memory: Reservation) -> Result<Self> {
        // The supported schema uses borrowed Serialize implementations. This
        // pass only counts tree capacity; it allocates no intermediate JSON.
        let allowance = source.serialize(estimate::Estimator)?.bytes;
        memory.resize(allowance)?;
        let value = serde_json::to_value(source)?;
        let retained = value.json_capacity()?;
        ensure!(
            retained <= allowance,
            "manifest tree exceeds admitted capacity"
        );
        memory.resize(retained)?;
        Ok(Self {
            value,
            _memory: memory,
        })
    }
}
impl Serialize for ManifestTree {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.value.serialize(serializer)
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;
