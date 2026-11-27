use crate::engine::Inspection;
use chopper_core::CsvSettings;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fmt;

/// Metadata for one physical input column after applying the CSV settings.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InputColumn<'a> {
    /// Zero-based position in the parsed input.
    pub index: usize,
    /// Exact parsed header name, if the input has headers.
    pub name: Option<&'a str>,
}

/// One retained row from a bounded input preview.
#[derive(Clone, Copy, Debug)]
pub struct PreviewRow<'a> {
    /// One-based data-record number, excluding the header.
    pub number: usize,
    fields: &'a [Value],
}

impl<'a> PreviewRow<'a> {
    pub fn fields(self) -> impl ExactSizeIterator<Item = &'a str> {
        self.fields.iter().map(text)
    }
}

fn text(value: &Value) -> &str {
    value.as_str().expect("inspection text")
}

/// Input observations from the configured parser, with their memory admission retained.
#[derive(Serialize)]
#[serde(transparent)]
pub struct InputReport(Inspection);

impl fmt::Debug for InputReport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("InputReport")
            .field("column_count", &self.column_count())
            .field("input_is_zip", &self.input_is_zip())
            .finish_non_exhaustive()
    }
}

impl InputReport {
    pub(super) fn new(inspection: Inspection) -> Self {
        Self(inspection)
    }

    pub fn column_count(&self) -> usize {
        usize::deserialize(&self.0["columns"]).expect("inspection column count")
    }

    /// Borrow columns in input order, retaining duplicate header names.
    pub fn columns(&self) -> impl ExactSizeIterator<Item = InputColumn<'_>> {
        let header = self.0["header"].as_array();
        (0..self.column_count()).map(move |index| InputColumn {
            index,
            name: header.map(|fields| text(&fields[index])),
        })
    }

    /// Borrow parsed header names in input order.
    pub fn header(&self) -> Option<impl ExactSizeIterator<Item = &str>> {
        self.0["header"]
            .as_array()
            .map(|fields| fields.iter().map(text))
    }

    pub fn input_is_zip(&self) -> bool {
        self.0["input_is_zip"]
            .as_bool()
            .expect("inspection ZIP flag")
    }

    /// Borrow retained preview rows. Column-only inspection returns an empty iterator.
    pub fn preview_rows(&self) -> impl ExactSizeIterator<Item = PreviewRow<'_>> {
        let rows = self.0["preview"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default();
        let numbers = self.0["preview_row_numbers"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default();
        rows.iter().zip(numbers).map(|(row, number)| PreviewRow {
            number: usize::deserialize(number).expect("inspection row number"),
            fields: row.as_array().expect("inspection preview fields"),
        })
    }
}

/// Outcome of comparing delimiters on the sampled input.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DelimiterStatus {
    /// One delimiter best fit the sample.
    Detected,
    /// Multiple delimiters tied, so the configured delimiter was retained.
    Ambiguous,
    /// No delimiter fit, so the configured delimiter was retained.
    NotDetected,
}

/// Advisory CSV settings based on a bounded input sample.
#[derive(Serialize)]
#[serde(transparent)]
pub struct DetectedDialect(Inspection);

impl fmt::Debug for DetectedDialect {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("DetectedDialect")
            .field("delimiter_status", &self.delimiter_status())
            .field("sample_bytes", &self.sample_bytes())
            .finish_non_exhaustive()
    }
}

impl DetectedDialect {
    pub(super) fn new(inspection: Inspection) -> Self {
        Self(inspection)
    }

    /// Return a caller-owned copy of the suggested settings.
    pub fn settings(&self) -> CsvSettings {
        CsvSettings::deserialize(&self.0["settings"]).expect("detection CSV settings")
    }

    pub fn delimiter_status(&self) -> DelimiterStatus {
        DelimiterStatus::deserialize(&self.0["delimiter_status"])
            .expect("detection delimiter status")
    }

    /// Number of bytes sampled before text decoding and after decompression.
    pub fn sample_bytes(&self) -> usize {
        usize::deserialize(&self.0["sample_bytes"]).expect("detection sample length")
    }

    pub fn note(&self) -> &str {
        text(&self.0["note"])
    }
}
