use anyhow::{bail, ensure, Result};
use serde::{Deserialize, Serialize};
mod column;
mod memory_budget;
mod validation;
pub use memory_budget::MemoryBudget;
pub use validation::JobValidationError;

pub const JOB_VERSION: u32 = 1;
pub const LINE_ENDINGS: &[&str] = &["lf", "crlf"];

// The serialized spelling and the exposed choices come from the same declaration.
macro_rules! wire_choices {
    (
        $(#[$meta:meta])* pub enum $name:ident {
            $($(#[$variant_meta:meta])* $variant:ident $( { $($fields:tt)* } )? => $wire:literal),+ $(,)?
        }
        $(; $constructor:ident)?
    ) => {
        $(#[$meta])*
        pub enum $name {
            $($(#[$variant_meta])* #[serde(rename = $wire)] $variant $( { $($fields)* } )?),+
        }

        impl $name {
            pub const CHOICES: &'static [&'static str] = &[$($wire),+];
            wire_choices!(@constructor [$($variant $( { $($fields)* } )? => $wire),+] $($constructor)?);
        }
    };
    (@constructor [$($variants:tt)*]) => {};
    (@constructor [
        $($variant:ident $( { $($(#[$field_meta:meta])* $field:ident: $ty:ty),* $(,)? } )? => $wire:literal),+
    ] $constructor:ident) => {
        /// Create a draft step for ordered CLI parsing before filling its required fields.
        pub fn $constructor(name: &str) -> Option<Self> {
            match name {
                $($wire => Some(Self::$variant $( { $($field: Default::default()),* } )?),)+
                _ => None,
            }
        }
    };
}

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
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub calculated_columns: Vec<CalculatedColumn>,
    // Append fields so the decoder's legacy sequence form keeps its order.
    #[serde(skip_serializing_if = "InputDialect::is_default")]
    pub input_dialect: InputDialect,
}
impl Default for Job {
    fn default() -> Self {
        Self {
            version: JOB_VERSION,
            input: String::new(),
            output: String::new(),
            zip_member: None,
            input_csv: CsvSettings::default(),
            input_dialect: InputDialect::default(),
            output_csv: CsvSettings::default(),
            compression: Compression::None,
            calculated_columns: vec![],
            operations: vec![],
            limits: Limits::default(),
            resources: Resources::default(),
            random_seed: None,

            full_shuffle_rng: FullShuffleRng::Blake3CounterV1,
            full_shuffle_algorithm: FullShuffleAlgorithm::AdaptiveV1,
        }
    }
}
wire_choices! {
    /// Versioned counter source. Removed source names remain strict decoding errors.
    #[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
    pub enum FullShuffleRng {
        #[default]
        Blake3CounterV1 => "blake3_counter_v1",
    }
}
impl FullShuffleRng {
    pub fn is_v1(&self) -> bool {
        *self == Self::Blake3CounterV1
    }
}
wire_choices! {
    /// Explicit full-shuffle construction used by flexible auto requests.
    #[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
    pub enum FullShuffleAlgorithm {
        #[default]
        AdaptiveV1 => "adaptive_v1",
    }
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

/// Optional input-only changes to which records and cells enter the pipeline.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct InputDialect {
    pub trim: CsvTrim,
    pub comment_prefix: Option<String>,
    pub skip_rows: u64,
    pub skip_columns: usize,
    pub skip_blank_rows: bool,
}

impl InputDialect {
    pub fn is_default(&self) -> bool {
        *self == Self::default()
    }
}

wire_choices! {
    #[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
    pub enum CsvTrim {
        #[default]
        None => "none",
        Start => "start",
        End => "end",
        Both => "both",
    }
}

// Keep the legacy error while defining accepted wire spellings once.
macro_rules! compression_choices {
    ($($variant:ident => $wire:literal),+ $(,)?) => {
        wire_choices! {
            #[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
            #[serde(try_from = "CompressionSetting")]
            pub enum Compression {
                $($variant => $wire),+
            }
        }

        #[derive(Deserialize)]
        #[serde(rename = "Compression")]
        enum CompressionSetting {
            $(#[serde(rename = $wire)] $variant,)+
            #[serde(rename = "zstd")]
            Zstd,
        }

        impl TryFrom<CompressionSetting> for Compression {
            type Error = &'static str;

            fn try_from(setting: CompressionSetting) -> std::result::Result<Self, Self::Error> {
                match setting {
                    $(CompressionSetting::$variant => Ok(Self::$variant),)+
                    CompressionSetting::Zstd => Err(
                        "Zstandard output compression \"zstd\" was removed in 0.4.0; set \"compression\" to \"gzip\", \"zip\", or \"none\"",
                    ),
                }
            }
        }
    };
}

compression_choices! {
    None => "none",
    Gzip => "gzip",
    Zip => "zip",
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CalculatedColumn {
    pub name: String,
    pub expression: String,
}

wire_choices! {
    #[derive(Clone, Debug, Serialize, Deserialize)]
    #[serde(tag = "type", deny_unknown_fields)]
    pub enum Operation {
        Balanced {
            files: u64,
        } => "balanced",
        /// Round-robin membership; still exactly balanced and nonempty.
        Interleaved {
            files: u64,
        } => "interleaved",
        Partition {
            columns: Vec<Column>,
        } => "partition",
        Assign {
            groups: Vec<Allocation>,
            #[serde(default)]
            strata: Vec<Column>,
        } => "assign",
        /// Independent seeded draws, without exact per-stratum quotas.
        AssignProbabilistic {
            groups: Vec<Allocation>,
            #[serde(default)]
            strata: Vec<Column>,
        } => "assign_probabilistic",
        Shuffle {
            #[serde(default)]
            strategy: Shuffle,
        } => "shuffle",
    }; empty_step
}
impl Operation {
    pub fn partition(columns: Vec<Column>) -> Self {
        Self::Partition { columns }
    }

    pub fn assign(groups: Vec<Allocation>, strata: Vec<Column>) -> Self {
        Self::Assign { groups, strata }
    }

    pub fn assign_probabilistic(groups: Vec<Allocation>, strata: Vec<Column>) -> Self {
        Self::AssignProbabilistic { groups, strata }
    }

    pub fn shuffle(strategy: Shuffle) -> Self {
        Self::Shuffle { strategy }
    }

    pub fn balanced(files: u64) -> Self {
        Self::Balanced { files }
    }

    pub fn interleaved(files: u64) -> Self {
        Self::Interleaved { files }
    }
}
wire_choices! {
    #[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
    pub enum Shuffle {
        #[default]
        Uniform => "uniform",
        Auto => "auto",
        /// Uniform resident shuffle; never falls back to another permutation.
        FisherYates => "fisher_yates",
    }
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
wire_choices! {
    /// Physical grouping policy; both choices preserve identical logical results.
    #[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
    pub enum Grouping {
        #[default]
        Auto => "auto",
        Sort => "sort",
    }
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
