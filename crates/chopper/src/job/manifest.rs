//! Bounded reading of the native result manifest's documented metadata.

use super::{error::ManifestLocation, Compression, Error};
use anyhow::{anyhow, Context as _};
use serde::{
    de::{self, value::MapAccessDeserializer, DeserializeOwned, MapAccess, Visitor},
    Deserialize, Deserializer, Serialize,
};
use std::{
    fmt,
    fs::File,
    io::{self, BufRead, BufReader},
    iter::FusedIterator,
    marker::PhantomData,
    num::NonZeroU64,
    path::Path,
};

/// Metadata from the first record of a native result manifest.
#[derive(Debug, Serialize)]
#[non_exhaustive]
pub struct ManifestHeader {
    pub schema_version: u64,
    pub application_version: String,
    pub algorithm_version: String,
    pub compression: Compression,
    pub rows: u64,
    pub output_files: u64,
    pub output_csv_bytes: u64,
    pub input_header: Option<Vec<String>>,
}

/// Metadata for one physical CSV chunk. A ZIP output's `path` names a member
/// inside `outputs.zip`. For plain or gzip output, it names a file relative to
/// the result directory.
#[derive(Debug, Serialize)]
#[non_exhaustive]
pub struct ManifestOutput {
    pub path: String,
    pub rows: u64,
    pub csv_bytes: u64,
    pub stored_bytes: u64,
    pub compressed_target_exceeded: bool,
    pub lineage: Vec<ManifestLineage>,
}

/// A grouping decision and its zero-based index in the job's operations.
#[derive(Debug, Serialize)]
#[non_exhaustive]
pub struct ManifestLineage {
    pub operation: u64,
    #[serde(flatten)]
    pub decision: ManifestDecision,
}

/// A decision recorded for an output's group.
#[derive(Debug, Serialize)]
#[serde(untagged)]
#[non_exhaustive]
pub enum ManifestDecision {
    Partition { values: Vec<String> },
    Allocation { allocation: String },
    Part { part: u64 },
}

#[derive(Deserialize)]
struct HeaderRecord {
    #[serde(rename = "type", deserialize_with = "job_kind")]
    _kind: (),
    schema_version: u64,
    application_version: String,
    algorithm_version: String,
    #[serde(deserialize_with = "object")]
    config: HeaderConfig,
    #[serde(deserialize_with = "object")]
    analysis: HeaderAnalysis,
}

#[derive(Deserialize)]
struct HeaderConfig {
    #[serde(deserialize_with = "manifest_compression")]
    compression: Compression,
}

fn manifest_compression<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Compression, D::Error> {
    let name = String::deserialize(deserializer)?;
    Compression::deserialize(de::value::StringDeserializer::new(name))
}

#[derive(Deserialize)]
struct HeaderAnalysis {
    rows: u64,
    output_files: u64,
    output_csv_bytes: u64,
    #[serde(deserialize_with = "Deserialize::deserialize")]
    header: Option<Vec<String>>,
}

#[derive(Deserialize)]
struct OutputRecord {
    #[serde(rename = "type", deserialize_with = "output_kind")]
    _kind: (),
    path: String,
    rows: u64,
    csv_bytes: u64,
    stored_bytes: u64,
    compressed_target_exceeded: bool,
    lineage: Vec<ManifestLineage>,
}

impl From<OutputRecord> for ManifestOutput {
    fn from(record: OutputRecord) -> Self {
        Self {
            path: record.path,
            rows: record.rows,
            csv_bytes: record.csv_bytes,
            stored_bytes: record.stored_bytes,
            compressed_target_exceeded: record.compressed_target_exceeded,
            lineage: record.lineage,
        }
    }
}

#[derive(Deserialize)]
struct LineageRecord {
    operation: u64,
    #[serde(default, deserialize_with = "present")]
    values: Option<Vec<String>>,
    #[serde(default, deserialize_with = "present")]
    allocation: Option<String>,
    #[serde(default, deserialize_with = "present")]
    part: Option<NonZeroU64>,
}

fn expect_kind<'de, D: Deserializer<'de>>(deserializer: D, expected: &str) -> Result<(), D::Error> {
    if String::deserialize(deserializer)? != expected {
        return Err(de::Error::custom(format!("expected a {expected} record")));
    }
    Ok(())
}

fn job_kind<'de, D: Deserializer<'de>>(deserializer: D) -> Result<(), D::Error> {
    expect_kind(deserializer, "job")
}

fn output_kind<'de, D: Deserializer<'de>>(deserializer: D) -> Result<(), D::Error> {
    expect_kind(deserializer, "output")
}

// Serde's default struct decoding accepts sequences as well as objects.
fn object<'de, D: Deserializer<'de>, T: Deserialize<'de>>(deserializer: D) -> Result<T, D::Error> {
    struct Object<T>(PhantomData<T>);
    impl<'de, T: Deserialize<'de>> Visitor<'de> for Object<T> {
        type Value = T;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a manifest JSON object")
        }

        fn visit_map<M: MapAccess<'de>>(self, map: M) -> Result<T, M::Error> {
            T::deserialize(MapAccessDeserializer::new(map))
        }
    }
    deserializer.deserialize_map(Object(PhantomData))
}

// A decision key may be absent. A present key must have its documented type.
fn present<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}

impl TryFrom<LineageRecord> for ManifestLineage {
    type Error = &'static str;

    fn try_from(record: LineageRecord) -> Result<Self, Self::Error> {
        let decision = match (record.values, record.allocation, record.part) {
            (Some(values), None, None) => ManifestDecision::Partition { values },
            (None, Some(allocation), None) => ManifestDecision::Allocation { allocation },
            (None, None, Some(part)) => ManifestDecision::Part { part: part.get() },
            _ => return Err("a manifest lineage entry must contain one grouping decision"),
        };
        Ok(Self {
            operation: record.operation,
            decision,
        })
    }
}

impl<'de> Deserialize<'de> for ManifestLineage {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let record: LineageRecord = object(deserializer)?;
        Self::try_from(record).map_err(de::Error::custom)
    }
}

struct ManifestInput {
    reader: BufReader<File>,
    record: Vec<u8>,
    limit: usize,
    number: u64,
}

impl ManifestInput {
    fn record(&mut self) -> Result<bool, Error> {
        self.record.clear();
        self.number = self.number.saturating_add(1);
        let number = self.number;
        loop {
            let buffer = match self.reader.fill_buf() {
                Ok(buffer) => buffer,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => {
                    return Err(Error::new(
                        "manifest_read",
                        anyhow::Error::new(error).context(format!("read manifest line {number}")),
                    ));
                }
            };
            if buffer.is_empty() {
                return Ok(!self.record.is_empty());
            }
            let newline = buffer.iter().position(|byte| *byte == b'\n');
            let count = newline.unwrap_or(buffer.len());
            let needed = self
                .record
                .len()
                .checked_add(count)
                .filter(|length| *length <= self.limit)
                .ok_or_else(|| {
                    Error::new(
                        "manifest_limit",
                        anyhow!(
                            "manifest line {number} exceeds the {} byte limit",
                            self.limit
                        ),
                    )
                })?;
            if needed > self.record.capacity() {
                let capacity = needed
                    .max(self.record.capacity().saturating_mul(2))
                    .min(self.limit);
                self.record
                    .try_reserve_exact(capacity - self.record.len())
                    .with_context(|| format!("allocate buffer for manifest line {number}"))
                    .map_err(|error| Error::new("manifest_limit", error))?;
            }
            self.record.extend_from_slice(&buffer[..count]);
            self.reader.consume(count + usize::from(newline.is_some()));
            if newline.is_some() {
                return Ok(true);
            }
        }
    }

    fn next<T: DeserializeOwned>(&mut self) -> Result<Option<T>, Error> {
        if !self.record()? {
            return Ok(None);
        }
        // Validate the whole line, since deserialization can skip unknown strings.
        std::str::from_utf8(&self.record)
            .map_err(anyhow::Error::from)
            .and_then(|line| {
                let mut decoder = serde_json::Deserializer::from_str(line);
                let record = object(&mut decoder)?;
                decoder.end()?;
                Ok(record)
            })
            .with_context(|| ManifestLocation(self.number))
            .map(Some)
            .map_err(|error| Error::new("manifest_format", error))
    }
}

#[derive(Default, PartialEq, Eq)]
struct Totals {
    rows: u64,
    files: u64,
    csv_bytes: u64,
}

impl Totals {
    fn after(&self, output: &OutputRecord) -> Option<Self> {
        Some(Self {
            rows: self.rows.checked_add(output.rows)?,
            files: self.files.checked_add(1)?,
            csv_bytes: self.csv_bytes.checked_add(output.csv_bytes)?,
        })
    }
}

/// Stream output metadata from a published native result's `manifest.jsonl`.
///
/// The reader opens only the manifest path supplied by the caller. It does not
/// open output files or inspect ZIP contents. It retains the header, a fixed
/// read buffer, and at most one record's working storage. Callers own yielded
/// records and the memory used to collect them. This reader's allocation bound
/// is separate from the engine's execution memory budget.
pub struct ManifestReader {
    input: Option<ManifestInput>,
    header: ManifestHeader,
    totals: Totals,
}

impl fmt::Debug for ManifestReader {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManifestReader")
            .field("closed", &self.input.is_none())
            .finish_non_exhaustive()
    }
}

impl ManifestReader {
    /// The default byte limit for each JSON Lines record, including the header.
    pub const DEFAULT_MAX_RECORD_BYTES: usize = 16 * 1024 * 1024;

    /// Read and validate the v1 header with a 16 MiB per-record byte limit.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, Error> {
        Self::open_with_record_limit(path, Self::DEFAULT_MAX_RECORD_BYTES)
    }

    /// Read and validate the v1 header. The positive `max_record_bytes` limit
    /// applies to each JSON line, including the header. Count all bytes before
    /// the line feed, including a carriage return if present.
    /// Choose a larger limit for manifests containing large records.
    pub fn open_with_record_limit(
        path: impl AsRef<Path>,
        max_record_bytes: usize,
    ) -> Result<Self, Error> {
        if max_record_bytes == 0 {
            return Err(Error::new(
                "manifest_limit",
                anyhow!("max_record_bytes must be positive"),
            ));
        }
        let path = path.as_ref();
        let open_file = || -> anyhow::Result<File> {
            anyhow::ensure!(
                path.metadata()?.is_file(),
                "manifest must be a regular file"
            );
            Ok(File::open(path)?)
        };
        let file = open_file()
            .with_context(|| format!("open manifest {}", path.display()))
            .map_err(|error| Error::new("manifest_read", error))?;
        let mut input = ManifestInput {
            reader: BufReader::new(file),
            record: Vec::new(),
            limit: max_record_bytes,
            number: 0,
        };
        let record = input
            .next::<HeaderRecord>()?
            .ok_or_else(|| Error::new("manifest_format", anyhow!("manifest has no job record")))?;
        if record.schema_version != 1 {
            return Err(Error::new(
                "manifest_format",
                anyhow!(
                    "unsupported manifest schema version {}",
                    record.schema_version
                ),
            ));
        }
        Ok(Self {
            input: Some(input),
            header: ManifestHeader {
                schema_version: record.schema_version,
                application_version: record.application_version,
                algorithm_version: record.algorithm_version,
                compression: record.config.compression,
                rows: record.analysis.rows,
                output_files: record.analysis.output_files,
                output_csv_bytes: record.analysis.output_csv_bytes,
                input_header: record.analysis.header,
            },
            totals: Totals::default(),
        })
    }

    pub fn header(&self) -> &ManifestHeader {
        &self.header
    }

    /// Release the file and record buffer early. The header remains available.
    /// Read to the end to check the manifest's totals.
    pub fn close(&mut self) {
        self.input = None;
    }

    fn verify_totals(&self) -> Result<(), Error> {
        let expected = Totals {
            rows: self.header.rows,
            files: self.header.output_files,
            csv_bytes: self.header.output_csv_bytes,
        };
        if self.totals != expected {
            return Err(Error::new(
                "manifest_format",
                anyhow!(
                    "manifest totals differ from the job record: expected {} rows, {} files and {} CSV bytes; read {} rows, {} files and {} CSV bytes",
                    expected.rows,
                    expected.files,
                    expected.csv_bytes,
                    self.totals.rows,
                    self.totals.files,
                    self.totals.csv_bytes,
                ),
            ));
        }
        Ok(())
    }
}

impl Iterator for ManifestReader {
    type Item = Result<ManifestOutput, Error>;

    fn next(&mut self) -> Option<Self::Item> {
        let input = self.input.as_mut()?;
        match input.next::<OutputRecord>() {
            Ok(Some(output)) => match self.totals.after(&output) {
                Some(totals) => {
                    self.totals = totals;
                    Some(Ok(output.into()))
                }
                None => {
                    let number = input.number;
                    self.close();
                    Some(Err(Error::new(
                        "manifest_format",
                        anyhow!("manifest totals overflow at line {number}"),
                    )))
                }
            },
            Ok(None) => {
                self.close();
                self.verify_totals().err().map(Err)
            }
            Err(error) => {
                self.close();
                Some(Err(error))
            }
        }
    }
}

impl FusedIterator for ManifestReader {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job::{Column, Job, JobSettings, Operation};
    use serde_json::{json, Value};
    use std::fs;

    const LIMIT: usize = 16 * 1024;

    fn header(rows: u64, files: u64, csv_bytes: u64) -> Value {
        json!({
            "type": "job", "schema_version": 1,
            "application_version": "0.7.0", "algorithm_version": "opaque",
            "config": {"compression": "zip", "other_config": true},
            "analysis": {
                "rows": rows, "output_files": files, "output_csv_bytes": csv_bytes,
                "header": ["a", "b"], "other_analysis": [1, 2],
            },
            "extra": "ignored",
        })
    }

    fn output(rows: u64, csv_bytes: u64) -> Value {
        json!({
            "type": "output", "path": "literal.csv", "rows": rows,
            "csv_bytes": csv_bytes, "stored_bytes": 3, "compressed_target_exceeded": true,
            "lineage": [
                {"operation": 0, "values": ["café\n\u{0000}"], "extra": 42},
                {"operation": 1, "allocation": "sample"},
                {"operation": 2, "part": 1},
            ],
            "extra": null,
        })
    }

    #[test]
    fn reads_metadata_from_each_native_publication_format() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let input = temp.path().join("input.csv");
        fs::write(&input, "id,city\n1,Montréal\n2,Berlin\n3,Montréal\n")?;
        for (compression, directory) in [
            (Compression::None, "plain"),
            (Compression::Gzip, "gzip"),
            (Compression::Zip, "zip"),
        ] {
            let destination = temp.path().join(directory);
            let mut settings =
                JobSettings::for_files(input.to_str().unwrap(), destination.to_str().unwrap());
            settings.compression = compression;
            settings.limits.rows = Some(1);
            settings
                .operations
                .push(Operation::partition(vec![Column::Name("city".into())]));
            let report = Job::new(settings).run()?;
            let mut reader = ManifestReader::open(report.manifest_path)?;
            assert_eq!(reader.header().compression, compression);
            assert_eq!(reader.header().output_files, 3);
            assert_eq!(
                reader.header().input_header.as_deref().unwrap(),
                ["id", "city"]
            );
            let records: Vec<_> = reader.by_ref().collect::<Result<_, _>>()?;
            let rows = records.iter().map(|record| record.rows).sum::<u64>();
            let bytes = records.iter().map(|record| record.csv_bytes).sum::<u64>();
            assert_eq!((rows, bytes), (3, report.output_csv_bytes));
            for record in &records {
                assert_eq!(record.rows, 1);
                assert!(record.stored_bytes > 0);
                assert_eq!(record.lineage.len(), 1);
                let ManifestDecision::Partition { values } = &record.lineage[0].decision else {
                    panic!("expected partition lineage");
                };
                assert_eq!(record.lineage[0].operation, 0);
                assert!(
                    matches!(values.as_slice(), [value] if value == "Montréal" || value == "Berlin")
                );
                if compression == Compression::Zip {
                    assert!(destination.join("outputs.zip").is_file());
                    assert!(!destination.join(&record.path).exists());
                } else {
                    assert!(destination.join(&record.path).is_file());
                }
            }
            assert!(reader.input.is_none());
        }
        Ok(())
    }

    #[test]
    fn preserves_u64_and_lineage_without_opening_output_paths() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("manifest.jsonl");
        let mut record = output(u64::MAX, u64::MAX);
        record["path"] = json!("missing.csv");
        fs::write(
            &path,
            format!("{}\n{record}", header(u64::MAX, 1, u64::MAX)),
        )?;
        let mut reader = ManifestReader::open_with_record_limit(&path, LIMIT)?;
        let value = serde_json::to_value(reader.next().unwrap()?)?;
        assert_eq!(value["rows"].as_u64(), Some(u64::MAX));
        assert_eq!(value["csv_bytes"].as_u64(), Some(u64::MAX));
        assert_eq!(value["path"], "missing.csv");
        assert_eq!(
            value["lineage"][0],
            json!({"operation": 0, "values": ["café\n\u{0000}"]})
        );
        assert_eq!(
            value["lineage"][1],
            json!({"operation": 1, "allocation": "sample"})
        );
        assert_eq!(value["lineage"][2], json!({"operation": 2, "part": 1}));
        assert!(reader.next().is_none());
        Ok(())
    }

    #[test]
    fn enforces_the_byte_bound_and_closes_after_a_terminal_error() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("manifest.jsonl");
        let first = header(1, 1, 2);
        let record = output(1, 2).to_string();
        let limit = 24 * 1024;
        let padding = " ".repeat(limit - record.len());
        fs::write(&path, format!("{first}\r\n{record}{padding}\n"))?;
        let mut exact = ManifestReader::open_with_record_limit(&path, limit)?;
        assert!(exact.next().unwrap().is_ok());
        assert!(exact.next().is_none());
        fs::write(&path, format!("{first}\n{record}{padding}\r\n"))?;
        let mut oversized = ManifestReader::open_with_record_limit(&path, limit)?;
        assert_eq!(
            oversized.next().unwrap().unwrap_err().code(),
            "manifest_limit"
        );
        assert!(oversized.next().is_none());
        assert!(oversized.input.is_none());
        assert_eq!(
            ManifestReader::open_with_record_limit(&path, 1)
                .unwrap_err()
                .code(),
            "manifest_limit"
        );
        assert_eq!(
            ManifestReader::open_with_record_limit(&path, 0)
                .unwrap_err()
                .code(),
            "manifest_limit"
        );
        Ok(())
    }

    #[test]
    fn validates_header_and_reconciles_record_counts_at_eof() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("manifest.jsonl");
        assert_eq!(
            ManifestReader::open_with_record_limit(&path, LIMIT)
                .unwrap_err()
                .code(),
            "manifest_read"
        );
        fs::write(&path, b"")?;
        assert_eq!(
            ManifestReader::open_with_record_limit(&path, LIMIT)
                .unwrap_err()
                .code(),
            "manifest_format"
        );
        let mut first = header(0, 0, 0);
        first["schema_version"] = json!(2);
        fs::write(&path, first.to_string())?;
        assert!(ManifestReader::open_with_record_limit(&path, LIMIT)
            .unwrap_err()
            .to_string()
            .contains("schema version 2"));
        first["schema_version"] = json!(1);
        first["analysis"]["header"] = Value::Null;
        fs::write(&path, first.to_string())?;
        let mut empty = ManifestReader::open_with_record_limit(&path, LIMIT)?;
        assert!(empty.header().input_header.is_none());
        assert!(empty.next().is_none());
        first["config"] = json!(["zip"]);
        fs::write(&path, first.to_string())?;
        assert_eq!(
            ManifestReader::open_with_record_limit(&path, LIMIT)
                .unwrap_err()
                .code(),
            "manifest_format"
        );

        for (first, output_records) in [
            (header(1, 1, 2), vec![]),
            (header(1, 1, 2), vec![output(1, 2), output(0, 0)]),
            (header(1, 1, 3), vec![output(1, 2)]),
        ] {
            let records = output_records
                .iter()
                .map(Value::to_string)
                .collect::<Vec<_>>()
                .join("\n");
            fs::write(&path, format!("{first}\n{records}"))?;
            let mut reader = ManifestReader::open_with_record_limit(&path, LIMIT)?;
            for _ in output_records {
                assert!(reader.next().unwrap().is_ok());
            }
            assert_eq!(
                reader.next().unwrap().unwrap_err().code(),
                "manifest_format"
            );
            assert!(reader.next().is_none());
        }

        fs::write(
            &path,
            format!(
                "{}\n{}\n{}\n",
                header(u64::MAX, 2, 2),
                output(u64::MAX, 1),
                output(1, 1)
            ),
        )?;
        let mut reader = ManifestReader::open_with_record_limit(&path, LIMIT)?;
        assert_eq!(reader.next().unwrap()?.rows, u64::MAX);
        let overflow = reader.next().unwrap().unwrap_err();
        assert_eq!(overflow.code(), "manifest_format");
        assert!(overflow.to_string().contains("overflow at line 3"));
        assert!(reader.next().is_none());
        Ok(())
    }

    #[test]
    fn manifest_compression_requires_a_supported_string() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("manifest.jsonl");
        let mut first = header(0, 0, 0);
        for compression in [
            json!({"zip": null}),
            json!(["zip"]),
            json!("zstd"),
            Value::Null,
        ] {
            first["config"]["compression"] = compression;
            fs::write(&path, first.to_string())?;
            assert_eq!(
                ManifestReader::open_with_record_limit(&path, LIMIT)
                    .unwrap_err()
                    .code(),
                "manifest_format"
            );
        }
        Ok(())
    }

    #[test]
    fn rejects_bad_records_and_releases_the_manifest_on_early_close() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = temp.path().join("manifest.jsonl");
        let first = header(1, 1, 2);
        let mut ambiguous = output(1, 2);
        ambiguous["lineage"][0]["part"] = json!(1);
        let mut wrong_lineage = output(1, 2);
        wrong_lineage["lineage"] = json!([[0, ["name"]]]);
        let mut wrong_kind = output(1, 2);
        wrong_kind["type"] = json!({"output": null});
        let mut invalid_utf8 = output(1, 2).to_string().into_bytes();
        invalid_utf8.pop();
        invalid_utf8.extend_from_slice(b",\"bad_string\":\"\xff\"}");
        for malformed in [
            b"\n".to_vec(),
            first.to_string().into_bytes(),
            ambiguous.to_string().into_bytes(),
            wrong_lineage.to_string().into_bytes(),
            wrong_kind.to_string().into_bytes(),
            invalid_utf8,
        ] {
            let mut contents = format!("{first}\n").into_bytes();
            contents.extend(malformed);
            fs::write(&path, contents)?;
            let mut reader = ManifestReader::open_with_record_limit(&path, LIMIT)?;
            assert_eq!(
                reader.next().unwrap().unwrap_err().code(),
                "manifest_format"
            );
            assert!(reader.next().is_none());
        }

        fs::write(&path, first.to_string())?;
        let mut reader = ManifestReader::open_with_record_limit(&path, LIMIT)?;
        reader.close();
        reader.close();
        assert!(reader.next().is_none());
        assert_eq!(reader.header().output_files, 1);
        fs::remove_file(&path)?;
        Ok(())
    }
}
