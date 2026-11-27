mod cli_json;
mod cli_reference;
mod cli_summary;
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
    name = "chopper",
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
        /// Open an existing saved Job in the wizard.
        #[arg(long)]
        config: Option<PathBuf>,
    },
    /// Print a complete example job configuration.
    Example,
    /// Check a saved job without opening its input or creating output.
    Validate {
        /// Read settings from this saved Job JSON file.
        #[arg(short, long)]
        config: PathBuf,
        /// Write a machine-readable validation result to stdout.
        #[arg(long)]
        json: bool,
    },
    /// Inspect all input rows and report bounded statistics and pipeline estimates.
    Analyze {
        /// Read settings from this saved Job JSON file.
        #[arg(short, long)]
        config: PathBuf,
        /// Override the working budget in MiB, or use auto.
        #[arg(long)]
        memory_mb: Option<MemoryBudget>,
        /// Override the sort and compression worker count; 0 selects automatically.
        #[arg(long)]
        workers: Option<usize>,
        #[arg(long, help = cli_summary::HELP)]
        summary: bool,
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
fn run_job(source: CliJob, yes: bool, advice: Option<PathBuf>, summary: bool) -> Result<()> {
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
    let hint = advice.and_then(|path| match read_advice(&path) {
        Ok(hint) => hint,
        Err(error) => {
            let _ = writeln!(io::stderr(), "Analyze advice unavailable: {error:#}");
            None
        }
    });
    let analysis = source
        .execute(cancelled, notify, hint)
        .context("Run stopped before publication")?;
    if summary {
        cli_json::write_published(&cli_summary::RunSummary::from(&analysis))
    } else {
        cli_json::write_published(&analysis)
    }
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
fn cli_command() -> clap::Command {
    Cli::command()
        .disable_help_subcommand(true)
        .subcommand(run_cli::command())
        .subcommand(
            clap::Command::new("help")
                .about("Print help for Chopper or a subcommand")
                .disable_help_flag(true)
                .arg(
                    clap::Arg::new("command")
                        .value_name("COMMAND")
                        .num_args(0..)
                        .help("Subcommand path; omit it for top-level help"),
                ),
        )
}

fn print_command_help(arguments: &clap::ArgMatches) -> Result<()> {
    let mut root = cli_command();
    root.build();
    let mut command = &mut root;
    if let Some(path) = arguments.get_many::<String>("command") {
        for name in path {
            if command.find_subcommand(name).is_none() {
                return Err(clap::Error::raw(
                    clap::error::ErrorKind::InvalidSubcommand,
                    format!("unrecognized subcommand '{name}'"),
                )
                .with_cmd(command)
                .into());
            }
            command = command.find_subcommand_mut(name).unwrap();
        }
    }
    command.print_long_help()?;
    Ok(())
}

fn main_result() -> Result<()> {
    let mut matches = cli_command()
        .subcommand(clap::Command::new("reference-json").hide(true))
        .get_matches();
    if matches.subcommand_name() == Some("reference-json") {
        return cli_reference::write(cli_command());
    }
    if let Some(("help", arguments)) = matches.subcommand() {
        return print_command_help(arguments);
    }
    if matches.subcommand_name() == Some("run") {
        let (_, mut arguments) = matches
            .remove_subcommand()
            .expect("selected Run subcommand");
        let source = run_cli::source(&arguments)?;
        let yes = arguments.get_flag("yes");
        let advice = arguments.remove_one::<PathBuf>("analysis");
        let summary = arguments.get_flag("summary");
        // The Job now owns its settings. Release clap's parsed values before Run.
        drop(arguments);
        drop(matches);
        return run_job(source, yes, advice, summary);
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
            summary,
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
            let mut stdout = io::stdout().lock();
            if summary {
                cli_json::write_pretty(&mut stdout, &cli_summary::AnalyzeSummary::from(&profile))?;
            } else {
                cli_json::write_pretty(&mut stdout, &profile)?;
            }
        }
    }
    Ok(())
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
    }
}
