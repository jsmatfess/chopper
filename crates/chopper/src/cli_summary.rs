//! Successful native CLI reports with an explicit allowlist of fields.
use chopper::{engine::Analysis, profile::InputProfile};
use serde::Serialize;

pub(super) const HELP: &str = "Print only completion status and aggregate counts in stdout JSON";

#[derive(Serialize)]
pub(super) struct AnalyzeSummary {
    status: &'static str,
    rows: u64,
    columns: usize,
}

impl From<&InputProfile> for AnalyzeSummary {
    fn from(profile: &InputProfile) -> Self {
        Self {
            status: "analyzed",
            rows: profile.rows,
            columns: profile.columns,
        }
    }
}

#[derive(Serialize)]
pub(super) struct RunSummary {
    status: &'static str,
    rows: u64,
    columns: usize,
    groups: u64,
    output_files: u64,
    output_csv_bytes: u64,
}

impl From<&Analysis> for RunSummary {
    fn from(analysis: &Analysis) -> Self {
        Self {
            status: "published",
            rows: analysis.rows,
            columns: analysis.columns,
            groups: analysis.groups,
            output_files: analysis.output_files,
            output_csv_bytes: analysis.output_csv_bytes,
        }
    }
}
