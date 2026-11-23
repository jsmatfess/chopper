mod cli_json;
mod guide;
mod run_cli;
mod validate_cli;

use anyhow::{ensure, Context, Result};
use chopper::{core::*, engine, storage::Notify};
use clap::{CommandFactory, FromArgMatches, Parser, Subcommand};
use std::{
    io::{self, IsTerminal, Write},
    path::PathBuf,
    process::ExitCode,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

#[derive(Parser)]
#[command(
    version,
    about = "Split large CSVs with bounded memory, ordered pipelines and full random shuffles"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
#[allow(clippy::large_enum_variant)] // Parsed once; boxing CLI strings adds no useful bound.
enum Command {
    /// Build, save and run a capped plain CSV export in a terminal wizard.
    Guide {
        #[arg(long)]
        config: Option<PathBuf>,
    },
    /// Print a complete example job configuration.
    Example,
    /// Check a saved job without opening its input or creating output.
    Validate {
        #[arg(short, long)]
        config: PathBuf,
        /// Write a machine-readable validation result to stdout.
        #[arg(long)]
        json: bool,
    },
    /// Inspect all input rows and report bounded statistics and pipeline estimates.
    Analyze {
        #[arg(short, long)]
        config: PathBuf,
        #[arg(long)]
        memory_mb: Option<MemoryBudget>,
        #[arg(long)]
        workers: Option<usize>,
    },
    /// Convenience form: partition, assign, shuffle, balanced split, then final limits.
    Split {
        input: String,
        #[arg(short, long)]
        output: String,
        #[arg(long)]
        files: Option<u64>,
        /// Distribute consecutive rows cyclically instead of consecutive ranges.
        #[arg(long, requires = "files")]
        interleaved: bool,
        #[arg(long)]
        rows: Option<u64>,
        #[arg(long)]
        bytes: Option<String>,
        #[arg(long)]
        compressed_bytes: Option<String>,
        #[arg(long, value_delimiter = ',')]
        by: Vec<String>,
        /// Named percentages, e.g. treatment=80,control=20.
        #[arg(long)]
        groups: Option<String>,
        /// Use independent draws with approximate counts instead of exact quotas.
        #[arg(long, requires = "groups")]
        probabilistic: bool,
        #[arg(long, value_parser = ["uniform", "auto", "fisher_yates"])]
        shuffle: Option<String>,
        #[arg(long, default_value = "none", value_parser = ["none", "gzip", "zip"])]
        compression: String,
        #[arg(long)]
        zip_member: Option<String>,
        #[arg(long, default_value = "auto")]
        memory_mb: MemoryBudget,
        #[arg(long, default_value_t = 0)]
        workers: usize,
        /// Physical grouping implementation; logical results are identical.
        #[arg(long, default_value = "auto", value_parser = ["auto", "sort"])]
        grouping: String,
        #[arg(long)]
        temp_dir: Option<String>,
        #[arg(long)]
        temp_bytes: Option<String>,
        #[arg(long, default_value_t = 100000)]
        max_files: u64,
        #[arg(long)]
        no_headers: bool,
        #[arg(short, long)]
        yes: bool,
    },
}
// Keep flag-built Jobs separate from admitted scripted JSON decoding.
#[allow(clippy::large_enum_variant)]
enum CliJob {
    Ordinary(Job),
    Decoded(chopper::cli_job::DecodedJob),
}
impl CliJob {
    fn job(&self) -> &Job {
        match self {
            Self::Ordinary(job) => job,
            Self::Decoded(owner) => owner.job(),
        }
    }
    fn execute(
        self,
        cancel: Arc<AtomicBool>,
        notify: Notify,
        hint: Option<engine::AutoObservations>,
    ) -> Result<engine::Analysis> {
        match self {
            Self::Ordinary(job) => engine::run_advised(job, cancel, notify, hint),
            Self::Decoded(owner) => owner.run_advised(cancel, notify, hint),
        }
    }
}
fn run_job(source: CliJob, yes: bool, advice: Option<&std::path::Path>) -> Result<()> {
    let job = source.job();
    if !yes {
        ensure!(
            io::stdin().is_terminal(),
            "non-interactive execution requires --yes"
        );
    }
    let cancelled = Arc::new(AtomicBool::new(false));
    let signal = cancelled.clone();
    ctrlc::set_handler(move || {
        signal.store(true, Ordering::Relaxed);
        #[cfg(feature = "resource-contract-tests")]
        chopper::guide_test_control::signal_received();
    })?;
    let notify: Notify = Arc::new(|p| {
        // Progress delivery, including Complete, must not change the Run outcome.
        let _ = writeln!(
            io::stderr(),
            "{} | {} rows | {} MiB temporary",
            p.phase,
            p.rows,
            p.temp_bytes / 1024 / 1024
        );
    });
    if !yes {
        write!(
            io::stderr(),
            "Process {} and write output to {}? [y/N] ",
            job.input,
            job.output
        )?;
        io::stderr().flush()?;
        let mut answer = String::new();
        io::stdin().read_line(&mut answer)?;
        ensure!(
            matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes"),
            "execution declined"
        );
    }
    let hint = advice.and_then(|path| match read_advice(path) {
        Ok(hint) => hint,
        Err(error) => {
            let _ = writeln!(io::stderr(), "Analyze advice unavailable: {error:#}");
            None
        }
    });
    let analysis = source
        .execute(cancelled, notify, hint)
        .context("Run stopped before publication")?;
    cli_json::write_published(&analysis)
}

fn read_advice(path: &std::path::Path) -> Result<Option<engine::AutoObservations>> {
    use std::io::Read;
    #[derive(serde::Deserialize)]
    struct Report {
        auto_observations: Option<engine::AutoObservations>,
    }
    let limit = 8 * 1024 * 1024;
    let metadata = std::fs::metadata(path)?;
    ensure!(
        metadata.is_file() && metadata.len() <= limit,
        "expected an Analyze JSON file up to 8 MiB"
    );
    let report: Report = serde_json::from_reader(io::BufReader::new(
        std::fs::File::open(path)?.take(limit + 1),
    ))?;
    Ok(report.auto_observations)
}

fn main() -> ExitCode {
    let Err(error) = main_result() else {
        return ExitCode::SUCCESS;
    };
    if let Some(usage) = error.downcast_ref::<clap::Error>() {
        usage.exit();
    }
    let _ = writeln!(io::stderr(), "chopper: {error:#}");
    if error.is::<cli_json::PublishedReportFailure>() {
        ExitCode::from(3)
    } else {
        ExitCode::FAILURE
    }
}
fn main_result() -> Result<()> {
    let matches = Cli::command().subcommand(run_cli::command()).get_matches();
    if let Some(("run", arguments)) = matches.subcommand() {
        let source = run_cli::source(arguments)?;
        return run_job(
            source,
            arguments.get_flag("yes"),
            arguments
                .get_one::<PathBuf>("analysis")
                .map(PathBuf::as_path),
        );
    }
    match Cli::from_arg_matches(&matches)?.command {
        Command::Guide { config } => guide::run(config)?,
        Command::Validate { config, json } => {
            if !validate_cli::run(&config, json)? {
                std::process::exit(1);
            }
        }
        Command::Example => {
            let mut job = Job {
                input: "input.csv".into(),
                output: "chopped".into(),
                resources: Resources::automatic(),
                ..Job::default()
            };
            job.limits.rows = Some(100_000);
            job.operations = vec![
                Operation::Partition {
                    columns: vec![Column::Name("country".into())],
                },
                Operation::Assign {
                    groups: vec![
                        Allocation {
                            name: "treatment".into(),
                            percent: "80".into(),
                        },
                        Allocation {
                            name: "control".into(),
                            percent: "20".into(),
                        },
                    ],
                    strata: vec![],
                },
            ];
            println!("{}", serde_json::to_string_pretty(&job)?);
        }
        Command::Analyze {
            config,
            memory_mb,
            workers,
        } => {
            let cancelled = Arc::new(AtomicBool::new(false));
            let signal = cancelled.clone();
            ctrlc::set_handler(move || signal.store(true, Ordering::Relaxed))?;
            let profile = chopper::cli_job::DecodedJob::read(config)?
                .resource_overrides(memory_mb, workers)
                .analyze(
                    cancelled,
                    Arc::new(|p| eprintln!("{} | {} rows", p.phase, p.rows)),
                )?;
            cli_json::write_pretty(&mut io::stdout().lock(), &profile)?;
        }
        Command::Split {
            input,
            output,
            files,
            interleaved,
            rows,
            bytes,
            compressed_bytes,
            by,
            groups,
            probabilistic,
            shuffle,

            compression,
            zip_member,
            memory_mb,
            workers,
            grouping,
            temp_dir,
            temp_bytes,
            max_files,
            no_headers,
            yes,
        } => {
            let mut job = Job {
                input,
                output,
                zip_member,
                ..Job::default()
            };
            job.input_csv.headers = !no_headers;
            job.output_csv.headers = !no_headers;
            job.limits = Limits {
                rows,
                bytes: bytes.map(|s| parse_bytes(&s)).transpose()?,
                compressed_bytes: compressed_bytes.map(|s| parse_bytes(&s)).transpose()?,
            };
            job.resources = Resources {
                memory_mb,
                workers,
                grouping: serde_json::from_value(serde_json::Value::String(grouping))?,
                temp_dir,
                temp_bytes: temp_bytes.map(|s| parse_bytes(&s)).transpose()?,
                max_files,
                max_record_bytes: memory_mb.as_mib().map_or(8 * 1024 * 1024, |mb| {
                    (mb.saturating_mul(1024 * 1024) / 32).min(8 * 1024 * 1024) as usize
                }),
            };
            job.compression = serde_json::from_value(serde_json::Value::String(compression))?;
            if !by.is_empty() {
                job.operations.push(Operation::Partition {
                    columns: by.into_iter().map(Column::Name).collect(),
                });
            }
            if let Some(groups) = groups {
                let groups: Result<Vec<_>> = groups
                    .split(',')
                    .map(|g| {
                        let (name, percent) = g
                            .split_once('=')
                            .context("groups must be name=percent pairs")?;
                        Ok(Allocation {
                            name: name.into(),
                            percent: percent.into(),
                        })
                    })
                    .collect();
                let groups = groups?;
                job.operations.push(if probabilistic {
                    Operation::AssignProbabilistic {
                        groups,
                        strata: vec![],
                    }
                } else {
                    Operation::Assign {
                        groups,
                        strata: vec![],
                    }
                });
            }
            if let Some(strategy) = shuffle {
                job.operations.push(Operation::Shuffle {
                    strategy: serde_json::from_value(serde_json::Value::String(strategy))?,
                });
            }
            if let Some(files) = files {
                job.operations.push(if interleaved {
                    Operation::Interleaved { files }
                } else {
                    Operation::Balanced { files }
                });
            }
            run_job(CliJob::Ordinary(job), yes, None)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_rejects_removed_shuffle_controls() {
        for args in [
            vec![
                "chopper",
                "split",
                "input.csv",
                "--output",
                "result",
                "--shuffle",
                "buffer",
            ],
            vec![
                "chopper",
                "split",
                "input.csv",
                "--output",
                "result",
                "--buffer-rows",
                "7",
            ],
        ] {
            let error = Cli::try_parse_from(args).err().unwrap().to_string();
            assert!(
                error.contains("invalid value 'buffer'")
                    || error.contains("unexpected argument '--buffer-rows'"),
                "{error}"
            );
        }
        for strategy in ["radix", "prefix_distribution"] {
            let error = Cli::try_parse_from([
                "chopper",
                "split",
                "input.csv",
                "--output",
                "result",
                "--shuffle",
                strategy,
            ])
            .err()
            .unwrap()
            .to_string();
            assert!(
                error.contains(&format!("invalid value '{strategy}'")),
                "{error}"
            );
        }
        for strategy in ["uniform", "auto", "fisher_yates"] {
            assert!(Cli::try_parse_from([
                "chopper",
                "split",
                "input.csv",
                "--output",
                "result",
                "--shuffle",
                strategy
            ])
            .is_ok());
        }
    }
}

#[cfg(test)]
mod automatic_cli_tests {
    use super::*;
    #[test]
    fn parse_and_apply_resource_overrides() {
        let parsed = Cli::try_parse_from([
            "chopper",
            "analyze",
            "--config",
            "job.json",
            "--memory-mb",
            "auto",
            "--workers",
            "2",
        ])
        .unwrap();
        let (memory_mb, workers) = match parsed.command {
            Command::Analyze {
                memory_mb, workers, ..
            } => (memory_mb, workers),
            _ => panic!("wrong command"),
        };
        let mut imported = Job::default();
        imported.resources.memory_mb = 512.into();
        imported.resources.workers = 3;
        let file = tempfile::NamedTempFile::new().unwrap();
        serde_json::to_writer(file.as_file(), &imported).unwrap();
        let applied = chopper::cli_job::DecodedJob::read(file.path())
            .unwrap()
            .resource_overrides(memory_mb, workers);
        assert_eq!(applied.job().resources.memory_mb, MemoryBudget::Auto);
        assert_eq!(applied.job().resources.workers, 2);
        let retained = applied.resource_overrides(None, None);
        assert_eq!(retained.job().resources.memory_mb, MemoryBudget::Auto);
        assert_eq!(retained.job().resources.workers, 2);

        assert!(matches!(
            Cli::try_parse_from([
                "chopper",
                "split",
                "in.csv",
                "--output",
                "out",
                "--memory-mb",
                "auto"
            ])
            .unwrap()
            .command,
            Command::Split {
                memory_mb: MemoryBudget::Auto,
                ..
            }
        ));
    }
}
