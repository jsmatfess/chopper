//! Unified Run keeps admitted JSON and caller-owned flag-built Jobs distinct.
use anyhow::{bail, ensure, Context, Result};
use chopper::core::*;
use clap::{Arg, ArgAction, ArgMatches, Command};
use std::{path::PathBuf, str::FromStr};

const LOCAL: &[(&str, &str)] = &[
    (
        "step",
        "Append a step: partition, assign, assign_probabilistic, shuffle, balanced, interleaved",
    ),
    (
        "by",
        "Partition column names, comma-separated; use --column for literal names",
    ),
    (
        "column",
        "Append one literal partition column name (including numeric names)",
    ),
    (
        "column-index",
        "Append one zero-based partition column index",
    ),
    (
        "groups",
        "Allocation name=percent pairs, comma-separated; use --group for literal names",
    ),
    (
        "group",
        "Append one allocation name=percent (split at the last = sign)",
    ),
    (
        "strata",
        "Allocation stratum names, comma-separated; use --stratum for literal names",
    ),
    ("stratum", "Append one literal allocation stratum name"),
    (
        "stratum-index",
        "Append one zero-based allocation stratum index",
    ),
    ("strategy", "Shuffle strategy: uniform, auto, fisher_yates"),
    ("files", "Balanced/interleaved file count"),
];
const GLOBAL: &[(&str, &str)] = &[
    ("input", "Input file path"),
    ("output", "New or empty output directory path"),
    ("job-version", "Job schema version (default 1)"),
    ("zip-member", "Input ZIP member"),
    ("compression", "none, gzip or zip"),
    ("rows", "Maximum rows per output CSV"),
    ("bytes", "Maximum serialized bytes per CSV"),
    ("compressed-bytes", "Advisory compressed-byte target"),
    ("memory-mb", "Working budget in MiB or auto (default auto)"),
    (
        "workers",
        "Sort/compression workers; 0 selects automatically",
    ),
    ("grouping", "auto or sort"),
    ("max-files", "Maximum files/groups"),
    ("max-record-bytes", "Maximum record working size in bytes"),
    ("temp-dir", "Temporary directory"),
    ("temp-bytes", "Optional temporary-space budget"),
    ("full-shuffle-rng", "Versioned source: blake3_counter_v1"),
    (
        "full-shuffle-algorithm",
        "Versioned construction: adaptive_v1",
    ),
];
const CSV: &[(&str, &str)] = &[
    ("encoding", "Encoding name"),
    ("headers", "true or false"),
    (
        "delimiter",
        "One ASCII character (pass a literal tab for tab-separated CSV)",
    ),
    ("quote", "One ASCII character distinct from the delimiter"),
    (
        "escape",
        "One ASCII character distinct from delimiter and quote; omit for doubled quotes",
    ),
    ("line-ending", "lf or crlf"),
    ("bom", "true or false"),
    ("skip-empty-lines", "true or false"),
];

pub fn command() -> Command {
    let mut command = Command::new("run")
        .about("Run a JSON job (--config) or ordered --step operations")
        .after_help("Each --step appends an operation. Step options belong to the preceding --step. Job-wide settings may appear anywhere.\nUse --flag=value for values beginning with '-'. Names and indices have separate flags.\nExample: chopper run --input input.csv --output results --step shuffle --strategy auto --step partition --by country --yes");
    let mut config_conflicts = Vec::new();
    for &(id, help) in GLOBAL {
        let mut argument = Arg::new(id).long(id).help(help);
        if !matches!(id, "memory-mb" | "workers") {
            config_conflicts.push(id);
            argument = argument.help_heading("Flag-built Jobs");
        }
        if matches!(id, "input" | "output") {
            argument = argument.required_unless_present("config");
        }
        command = command.arg(argument);
    }
    for &(id, help) in LOCAL {
        config_conflicts.push(id);
        command = command.arg(
            Arg::new(id)
                .long(id)
                .help(help)
                .help_heading("Ordered steps")
                .action(ArgAction::Append),
        );
    }
    // Static names keep clap's owned-string feature unnecessary.
    for (ids, prefix) in [
        (
            [
                "input-encoding",
                "input-headers",
                "input-delimiter",
                "input-quote",
                "input-escape",
                "input-line-ending",
                "input-bom",
                "input-skip-empty-lines",
            ],
            "Flag-built input CSV",
        ),
        (
            [
                "output-encoding",
                "output-headers",
                "output-delimiter",
                "output-quote",
                "output-escape",
                "output-line-ending",
                "output-bom",
                "output-skip-empty-lines",
            ],
            "Flag-built output CSV",
        ),
    ] {
        for (id, &(_, help)) in ids.into_iter().zip(CSV) {
            config_conflicts.push(id);
            command = command.arg(Arg::new(id).long(id).help(help).help_heading(prefix));
        }
    }
    command = command.arg(
        Arg::new("config")
            .long("config")
            .short('c')
            .value_parser(clap::value_parser!(PathBuf))
            .conflicts_with_all(config_conflicts)
            .help("JSON job file; allows --memory-mb, --workers, --analysis, --summary and --yes"),
    );
    command = command.arg(
        Arg::new("analysis")
            .long("analysis")
            .value_parser(clap::value_parser!(PathBuf))
            .help("Optional full JSON report from chopper analyze"),
    );
    command = command.arg(
        Arg::new("summary")
            .long("summary")
            .action(ArgAction::SetTrue)
            .help(super::cli_summary::HELP),
    );
    command.arg(
        Arg::new("yes")
            .long("yes")
            .short('y')
            .action(ArgAction::SetTrue)
            .help("Skip execution confirmation; validation still applies"),
    )
}
fn number<T: FromStr>(value: &str, flag: &str) -> Result<T> {
    value
        .parse()
        .map_err(|_| anyhow::anyhow!("invalid value for --{flag}: {value:?}"))
}
fn enumeration<T: serde::de::DeserializeOwned>(value: &str, flag: &str) -> Result<T> {
    serde_json::from_value(serde_json::Value::String(value.into()))
        .with_context(|| format!("invalid --{flag}"))
}
fn character(value: &str, flag: &str) -> Result<char> {
    let mut chars = value.chars();
    let first = chars
        .next()
        .with_context(|| format!("--{flag} requires exactly one character"))?;
    ensure!(
        chars.next().is_none(),
        "--{flag} requires exactly one character"
    );
    Ok(first)
}
fn csv(matches: &ArgMatches, prefix: &str, settings: &mut CsvSettings) -> Result<()> {
    for &(suffix, _) in CSV {
        let flag = format!("{prefix}-{suffix}");
        if let Some(value) = matches.get_one::<String>(&flag) {
            match suffix {
                "encoding" => settings.encoding = value.clone(),
                "headers" => settings.headers = number(value, &flag)?,
                "delimiter" => settings.delimiter = character(value, &flag)?,
                "quote" => settings.quote = character(value, &flag)?,
                "escape" => settings.escape = Some(character(value, &flag)?),
                "line-ending" => settings.line_ending = value.clone(),
                "bom" => settings.bom = number(value, &flag)?,
                "skip-empty-lines" => settings.skip_empty_lines = number(value, &flag)?,
                _ => unreachable!(),
            }
        }
    }
    Ok(())
}
fn allocation(value: &str) -> Result<Allocation> {
    let (name, percent) = value
        .rsplit_once('=')
        .context("--group/--groups requires name=percent")?;
    Ok(Allocation {
        name: name.into(),
        percent: percent.into(),
    })
}

pub fn source(matches: &ArgMatches) -> Result<super::CliJob> {
    if let Some(config) = matches.get_one::<PathBuf>("config") {
        let memory = matches
            .get_one::<String>("memory-mb")
            .map(|value| number(value, "memory-mb"))
            .transpose()
            .map_err(usage_error)?;
        let workers = matches
            .get_one::<String>("workers")
            .map(|value| number(value, "workers"))
            .transpose()
            .map_err(usage_error)?;
        Ok(super::CliJob::Decoded(
            chopper::cli_job::DecodedJob::read(config)?.resource_overrides(memory, workers),
        ))
    } else {
        Ok(super::CliJob::Ordinary(
            parse(matches).map_err(usage_error)?.0,
        ))
    }
}

fn usage_error(error: anyhow::Error) -> clap::Error {
    clap::Error::raw(clap::error::ErrorKind::InvalidValue, format!("{error:#}"))
        .with_cmd(&command())
}

pub fn parse(matches: &ArgMatches) -> Result<(Job, bool)> {
    let mut job = Job {
        resources: Resources::automatic(),
        ..Job::default()
    };
    for &(flag, _) in GLOBAL {
        let Some(value) = matches.get_one::<String>(flag) else {
            continue;
        };
        match flag {
            "input" => job.input = value.clone(),
            "output" => job.output = value.clone(),
            "job-version" => job.version = number(value, flag)?,
            "zip-member" => job.zip_member = Some(value.clone()),
            "compression" => job.compression = enumeration(value, flag)?,
            "rows" => job.limits.rows = Some(number(value, flag)?),
            "bytes" => job.limits.bytes = Some(parse_bytes(value)?),
            "compressed-bytes" => job.limits.compressed_bytes = Some(parse_bytes(value)?),
            "memory-mb" => job.resources.memory_mb = number(value, flag)?,
            "workers" => job.resources.workers = number(value, flag)?,
            "grouping" => job.resources.grouping = enumeration(value, flag)?,
            "max-files" => job.resources.max_files = number(value, flag)?,
            "max-record-bytes" => job.resources.max_record_bytes = number(value, flag)?,
            "temp-dir" => job.resources.temp_dir = Some(value.clone()),
            "temp-bytes" => job.resources.temp_bytes = Some(parse_bytes(value)?),
            "full-shuffle-rng" => job.full_shuffle_rng = enumeration(value, flag)?,
            "full-shuffle-algorithm" => job.full_shuffle_algorithm = enumeration(value, flag)?,
            _ => unreachable!(),
        }
    }
    csv(matches, "input", &mut job.input_csv)?;
    csv(matches, "output", &mut job.output_csv)?;
    let mut ordered = Vec::new();
    for &(flag, _) in LOCAL {
        if let (Some(indices), Some(values)) =
            (matches.indices_of(flag), matches.get_many::<String>(flag))
        {
            ordered.extend(
                indices
                    .zip(values)
                    .map(|(index, value)| (index, flag, value.as_str())),
            );
        }
    }
    ordered.sort_unstable_by_key(|entry| entry.0);
    let mut seen = Vec::new();
    for (_, flag, value) in ordered {
        if flag == "step" {
            ensure!(
                job.operations.len() < 64,
                "pipeline supports at most 64 steps"
            );
            job.operations.push(match value {
                "partition" => Operation::Partition { columns: vec![] },
                "assign" => Operation::Assign {
                    groups: vec![],
                    strata: vec![],
                },
                "assign_probabilistic" => Operation::AssignProbabilistic {
                    groups: vec![],
                    strata: vec![],
                },
                "shuffle" => Operation::Shuffle {
                    strategy: Shuffle::default(),
                },
                "balanced" => Operation::Balanced { files: 0 },
                "interleaved" => Operation::Interleaved { files: 0 },
                _ => bail!("unknown --step {value:?}"),
            });
            seen.clear();
            continue;
        }
        let index = job.operations.len();
        let step = job
            .operations
            .last_mut()
            .with_context(|| format!("--{flag} requires a preceding --step"))?;
        if matches!(flag, "files" | "strategy") {
            ensure!(!seen.contains(&flag), "step {index}: repeated --{flag}");
            seen.push(flag);
        }
        match (flag, step) {
            ("by" | "column" | "column-index", Operation::Partition { columns }) => {
                if flag == "by" {
                    columns.extend(value.split(',').map(|name| Column::Name(name.into())));
                } else if flag == "column-index" {
                    columns.push(Column::Index(number(value, flag)?));
                } else {
                    columns.push(Column::Name(value.into()));
                }
            }
            (
                "groups" | "group",
                Operation::Assign { groups, .. } | Operation::AssignProbabilistic { groups, .. },
            ) => {
                if flag == "groups" {
                    for group in value.split(',') {
                        groups.push(allocation(group)?);
                    }
                } else {
                    groups.push(allocation(value)?);
                }
            }
            (
                "strata" | "stratum" | "stratum-index",
                Operation::Assign { strata, .. } | Operation::AssignProbabilistic { strata, .. },
            ) => {
                if flag == "strata" {
                    strata.extend(value.split(',').map(|name| Column::Name(name.into())));
                } else if flag == "stratum-index" {
                    strata.push(Column::Index(number(value, flag)?));
                } else {
                    strata.push(Column::Name(value.into()));
                }
            }
            ("strategy", Operation::Shuffle { strategy }) => *strategy = enumeration(value, flag)?,
            ("files", Operation::Balanced { files } | Operation::Interleaved { files }) => {
                *files = number(value, flag)?
            }
            _ => bail!("step {index}: --{flag} does not apply to this operation"),
        }
    }
    job.validate()?;
    Ok((job, matches.get_flag("yes")))
}

#[cfg(test)]
mod tests;
