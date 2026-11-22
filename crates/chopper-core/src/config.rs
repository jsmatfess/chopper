use anyhow::{bail, ensure, Result};
use serde::{Deserialize, Serialize};
mod column;
mod memory_budget;
pub use memory_budget::MemoryBudget;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Job {
    pub version: u32,
    pub input: String,
    pub output: String,
    pub zip_member: Option<String>,
    pub input_csv: CsvSettings,
    pub output_csv: CsvSettings,
    pub compression: Compression,
    pub operations: Vec<Operation>,
    pub limits: Limits,
    #[serde(default = "Resources::automatic")]
    pub resources: Resources,
    /// Internal execution/test state; never accepted or emitted in Job JSON.
    #[doc(hidden)]
    #[serde(skip)]
    pub random_seed: Option<String>,
    #[serde(skip_serializing_if = "FullShuffleRng::is_v1")]
    pub full_shuffle_rng: FullShuffleRng,
    #[serde(skip_serializing_if = "FullShuffleAlgorithm::is_adaptive")]
    pub full_shuffle_algorithm: FullShuffleAlgorithm,
}
impl Default for Job {
    fn default() -> Self {
        Self {
            version: 1,
            input: String::new(),
            output: String::new(),
            zip_member: None,
            input_csv: CsvSettings::default(),
            output_csv: CsvSettings::default(),
            compression: Compression::None,
            operations: vec![],
            limits: Limits::default(),
            resources: Resources::default(),
            random_seed: None,

            full_shuffle_rng: FullShuffleRng::Blake3CounterV1,
            full_shuffle_algorithm: FullShuffleAlgorithm::AdaptiveV1,
        }
    }
}
/// Versioned counter source. Removed source names remain strict decoding errors.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FullShuffleRng {
    #[default]
    Blake3CounterV1,
}
impl FullShuffleRng {
    pub fn is_v1(&self) -> bool {
        *self == Self::Blake3CounterV1
    }
}
/// Explicit full-shuffle construction used by flexible auto requests.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FullShuffleAlgorithm {
    #[default]
    AdaptiveV1,
}
impl FullShuffleAlgorithm {
    pub fn is_adaptive(&self) -> bool {
        *self == Self::AdaptiveV1
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CsvSettings {
    pub encoding: String,
    pub headers: bool,
    pub delimiter: char,
    pub quote: char,
    pub escape: Option<char>,
    pub line_ending: String,
    pub bom: bool,
    pub skip_empty_lines: bool,
}
impl Default for CsvSettings {
    fn default() -> Self {
        Self {
            encoding: "utf-8".into(),
            headers: true,
            delimiter: ',',
            quote: '"',
            escape: None,
            line_ending: "lf".into(),
            bom: false,
            skip_empty_lines: false,
        }
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Compression {
    None,
    Gzip,
    Zstd,
    Zip,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Operation {
    Balanced {
        files: u64,
    },
    /// Round-robin membership; still exactly balanced and nonempty.
    Interleaved {
        files: u64,
    },
    Partition {
        columns: Vec<Column>,
    },
    Assign {
        groups: Vec<Allocation>,
        #[serde(default)]
        strata: Vec<Column>,
    },
    /// Independent seeded draws, without exact per-stratum quotas.
    AssignProbabilistic {
        groups: Vec<Allocation>,
        #[serde(default)]
        strata: Vec<Column>,
    },
    Shuffle {
        #[serde(default)]
        strategy: Shuffle,
    },
}
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Shuffle {
    #[default]
    Uniform,
    Auto,
    /// Uniform resident shuffle; never falls back to another permutation.
    FisherYates,
}
#[derive(Clone, Debug, Serialize)]
#[serde(untagged)]
pub enum Column {
    Index(usize),
    Name(String),
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Allocation {
    pub name: String,
    pub percent: String,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Limits {
    pub rows: Option<u64>,
    pub bytes: Option<u64>,
    pub compressed_bytes: Option<u64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default = "Resources::automatic", deny_unknown_fields)]
pub struct Resources {
    pub memory_mb: MemoryBudget,
    pub workers: usize,
    pub temp_dir: Option<String>,
    pub temp_bytes: Option<u64>,
    pub max_files: u64,
    pub max_record_bytes: usize,
    pub grouping: Grouping,
}
/// Physical grouping policy; both choices preserve identical logical results.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Grouping {
    #[default]
    Auto,
    Sort,
}
impl Default for Resources {
    fn default() -> Self {
        Self {
            memory_mb: MemoryBudget::MiB(256),
            workers: 0,
            temp_dir: None,
            temp_bytes: None,
            max_files: 100_000,
            max_record_bytes: 8 * 1024 * 1024,
            grouping: Grouping::Auto,
        }
    }
}
impl Resources {
    /// Resource defaults for user-authored jobs and forms.
    pub fn automatic() -> Self {
        Self {
            memory_mb: MemoryBudget::Auto,
            ..Self::default()
        }
    }

    /// Validate a resolved budget without changing the requested configuration.
    pub fn validate_effective_memory(&self, memory_mb: u64) -> Result<()> {
        ensure!(
            (32..=1_048_576).contains(&memory_mb),
            "memory_mb must be between 32 and 1048576"
        );
        ensure!(
            self.max_record_bytes > 0
                && self.max_record_bytes as u64 <= memory_mb * 1024 * 1024 / 16,
            "max_record_bytes must fit within 1/16 of memory budget"
        );
        ensure!(
            self.workers <= 64 && self.workers as u64 <= memory_mb / 8,
            "workers must be 0 (automatic) or at most min(64, memory_mb/8)"
        );
        Ok(())
    }
}
impl Job {
    pub fn validate(&self) -> Result<()> {
        ensure!(self.version == 1, "unsupported configuration version");
        ensure!(!self.input.is_empty(), "input path is required");
        if let Some(memory_mb) = self.resources.memory_mb.as_mib() {
            self.resources.validate_effective_memory(memory_mb)?;
        } else {
            ensure!(
                self.resources.max_record_bytes > 0,
                "max_record_bytes must fit within 1/16 of memory budget"
            );
            ensure!(
                self.resources.workers <= 64,
                "workers must be 0 (automatic) or at most min(64, memory_mb/8)"
            );
        }
        ensure!(self.resources.max_files > 0, "max_files must be positive");
        ensure!(
            self.operations.len() <= 64,
            "at most 64 operations are supported per job"
        );
        for cap in [
            self.limits.rows,
            self.limits.bytes,
            self.limits.compressed_bytes,
        ]
        .into_iter()
        .flatten()
        {
            ensure!(cap > 0, "limits must be positive");
        }
        if self.limits.compressed_bytes.is_some() {
            ensure!(
                self.compression != Compression::None,
                "compressed_bytes requires output compression"
            );
        }
        for settings in [&self.input_csv, &self.output_csv] {
            for c in [
                Some(settings.delimiter),
                Some(settings.quote),
                settings.escape,
            ]
            .into_iter()
            .flatten()
            {
                ensure!(
                    c.is_ascii() && !matches!(c, '\r' | '\n' | '\0'),
                    "CSV delimiter, quote and escape must be non-newline ASCII characters"
                );
            }
            ensure!(
                settings.delimiter != settings.quote,
                "delimiter and quote must differ"
            );
            ensure!(
                settings.escape != Some(settings.delimiter)
                    && settings.escape != Some(settings.quote),
                "escape must differ from delimiter and quote; omit escape for doubled quotes"
            );
            ensure!(
                matches!(settings.line_ending.as_str(), "lf" | "crlf"),
                "line_ending must be lf or crlf"
            );
            crate::csv::encoding(&settings.encoding)?;
        }
        ensure!(
            !self.output_csv.headers || self.input_csv.headers,
            "cannot copy a header from headerless input; disable output headers"
        );
        for op in &self.operations {
            match op {
                Operation::Balanced { files } | Operation::Interleaved { files } => ensure!(
                    *files > 0 && *files <= self.resources.max_files,
                    "balanced file count must be positive and at most max_files"
                ),
                Operation::Partition { columns } => {
                    ensure!(!columns.is_empty(), "partition requires columns")
                }
                Operation::Assign { groups, .. }
                | Operation::AssignProbabilistic { groups, .. } => {
                    ensure!(
                        !groups.is_empty() && groups.len() <= 1024,
                        "allocation needs 1 to 1024 groups"
                    );
                    for (i, g) in groups.iter().enumerate() {
                        ensure!(
                            !g.name.is_empty() && !groups[..i].iter().any(|p| p.name == g.name),
                            "allocation names must be nonempty and unique"
                        );
                    }
                    let mut total = 0;
                    for group in groups {
                        total += percentage_weight(&group.percent)?;
                    }
                    ensure!(total == 100_000_000, "percentages must sum exactly to 100");
                }
                Operation::Shuffle { .. } => {}
            }
        }
        Ok(())
    }
}
pub fn resolve_columns(
    columns: &[Column],
    header: Option<&[String]>,
    width: usize,
) -> Result<Vec<usize>> {
    columns
        .iter()
        .map(|c| resolve_column(c, header, width))
        .collect()
}
/// Resolve one selection without allocating a temporary matches vector.
pub fn resolve_column(c: &Column, header: Option<&[String]>, width: usize) -> Result<usize> {
    let index = match c {
        Column::Index(i) => *i,
        Column::Name(name) => {
            let h = header.ok_or_else(|| anyhow::anyhow!("name selection requires headers"))?;
            let mut matches = h
                .iter()
                .enumerate()
                .filter(|(_, v)| *v == name)
                .map(|(i, _)| i);
            let first = matches.next();
            ensure!(
                first.is_some() && matches.next().is_none(),
                "column {name:?} is missing or ambiguous; use a zero-based index"
            );
            first.unwrap()
        }
    };
    ensure!(
        index < width,
        "column index {index} exceeds record width {width}"
    );
    Ok(index)
}
// Millionths of one percent; exact decimal parsing and u128 products.
pub fn weights(groups: &[Allocation]) -> Result<Vec<u64>> {
    let mut result = vec![0; groups.len()];
    weights_into(groups, &mut result)?;
    Ok(result)
}
/// Parse weights into caller-owned storage without allocating scratch.
pub fn weights_into(groups: &[Allocation], result: &mut [u64]) -> Result<()> {
    ensure!(
        groups.len() == result.len(),
        "weight storage length mismatch"
    );
    for (g, value) in groups.iter().zip(result.iter_mut()) {
        *value = percentage_weight(&g.percent)?;
    }
    ensure!(
        result.iter().sum::<u64>() == 100_000_000,
        "percentages must sum exactly to 100"
    );
    Ok(())
}
fn percentage_weight(percent: &str) -> Result<u64> {
    let (whole, fractional) = percent.split_once('.').unwrap_or((percent, ""));
    ensure!(
        !whole.is_empty() && whole.bytes().all(|b| b.is_ascii_digit()) && !fractional.contains('.'),
        "invalid percentage: {}",
        percent
    );
    ensure!(
        fractional.len() <= 6 && fractional.bytes().all(|b| b.is_ascii_digit()),
        "percentages support at most 6 decimal places"
    );
    let whole: u64 = whole.parse()?;
    ensure!(whole <= 100, "percentage exceeds 100");
    Ok(whole * 1_000_000
        + if fractional.is_empty() {
            0
        } else {
            fractional.parse::<u64>()? * 10_u64.pow(6 - fractional.len() as u32)
        })
}
pub fn quotas(n: u64, weights: &[u64]) -> Vec<u64> {
    let mut q = vec![0; weights.len()];
    let mut order = vec![0; weights.len()];
    quotas_into(n, weights, &mut q, &mut order);
    q
}
/// Largest-remainder allocation using caller-owned quota and ordering scratch.
/// `weights` must sum to 100,000,000, as returned by `weights`/`weights_into`.
pub fn quotas_into(n: u64, weights: &[u64], q: &mut [u64], order: &mut [usize]) {
    assert_eq!(weights.len(), q.len());
    assert_eq!(weights.len(), order.len());
    for (i, w) in weights.iter().enumerate() {
        q[i] = ((n as u128 * *w as u128) / 100_000_000) as u64;
        order[i] = i;
    }
    // The index breaks every tie, so unstable sorting preserves the v1 order
    // while avoiding stable-sort heap scratch.
    order.sort_unstable_by_key(|i| {
        (
            std::cmp::Reverse(n as u128 * weights[*i] as u128 % 100_000_000),
            *i,
        )
    });
    for i in order.iter().take((n - q.iter().sum::<u64>()) as usize) {
        q[*i] += 1;
    }
}
pub fn parse_bytes(text: &str) -> Result<u64> {
    let cut = text
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(text.len());
    let number: u64 = text[..cut].parse()?;
    let multiplier = match text[cut..].trim().to_ascii_lowercase().as_str() {
        "" | "b" => 1,
        "kb" => 1000,
        "mb" => 1_000_000,
        "gb" => 1_000_000_000,
        "tb" => 1_000_000_000_000,
        "kib" => 1024,
        "mib" => 1024 * 1024,
        "gib" => 1024 * 1024 * 1024,
        "tib" => 1024_u64.pow(4),
        _ => bail!("unknown byte unit"),
    };
    number
        .checked_mul(multiplier)
        .ok_or_else(|| anyhow::anyhow!("byte size overflow"))
}

#[cfg(test)]
mod removed_shuffle_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn obsolete_shuffle_requests_fail_for_wire_and_owned_json() {
        for operation in [
            json!({"type":"shuffle","strategy":"buffer"}),
            json!({"type":"shuffle","strategy":"buffer","buffer_rows":7}),
            json!({"type":"shuffle","buffer_rows":7}),
            json!({"type":"shuffle","strategy":"uniform","buffer_rows":0}),
            json!({"type":"shuffle","strategy":"auto","buffer_rows":7}),
            json!({"type":"shuffle","strategy":"fisher_yates","buffer_rows":7}),
        ] {
            let value = json!({"operations":[operation]});
            for error in [
                serde_json::from_str::<Job>(&value.to_string()).unwrap_err(),
                serde_json::from_value::<Job>(value).unwrap_err(),
            ] {
                let error = error.to_string();
                assert!(
                    error.contains("unknown variant `buffer`")
                        || error.contains("unknown field `buffer_rows`"),
                    "{error}"
                );
            }
        }
        for strategy in ["uniform", "auto", "fisher_yates"] {
            let value = json!({"operations":[{"type":"shuffle","strategy":strategy}]});
            let job: Job = serde_json::from_value(value).unwrap();
            assert_eq!(
                serde_json::to_value(job).unwrap()["operations"],
                json!([{"type":"shuffle","strategy":strategy}])
            );
        }
        let job: Job = serde_json::from_value(json!({"operations":[{"type":"shuffle"}]})).unwrap();
        assert!(matches!(
            job.operations[0],
            Operation::Shuffle {
                strategy: Shuffle::Uniform
            }
        ));
    }
}
