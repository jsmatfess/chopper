//! Public reference data from the complete, built native command tree.
use anyhow::{ensure, Context, Result};
use chopper::core::{
    csv::ENCODINGS, Compression, FullShuffleAlgorithm, FullShuffleRng, Grouping, Operation,
    Shuffle, JOB_VERSION, LINE_ENDINGS,
};
use clap::{Arg, Command};
use serde_json::{json, Value};
use std::io::{self, Write};

fn argument(arg: &Arg) -> Result<Value> {
    let syntax = match (arg.get_short(), arg.get_long()) {
        (Some(short), Some(_)) => format!("-{short}, {arg}"),
        _ => arg.to_string(),
    };
    let description = arg
        .get_help()
        .context(format!("missing description for {syntax}"))?;
    let description = description.to_string();
    ensure!(
        !description.trim().is_empty(),
        "empty description for {syntax}"
    );
    let mut accepted_values: Vec<String> = arg
        .get_possible_values()
        .iter()
        .filter(|value| !value.is_hide_set())
        .map(|value| value.get_name().to_owned())
        .collect();
    if arg.get_id() == "job-version" {
        accepted_values.push(chopper::core::JOB_VERSION.to_string());
    }
    let defaults: Vec<_> = arg
        .get_default_values()
        .iter()
        .filter(|_| arg.get_action().takes_values())
        .map(|value| value.to_string_lossy())
        .collect();
    Ok(json!({
        "id": arg.get_id().as_str(),
        "heading": arg.get_help_heading().unwrap_or(if arg.is_positional() { "Arguments" } else { "Options" }),
        "syntax": syntax,
        "description": description,
        "accepted_values": accepted_values,
        "defaults": defaults,
    }))
}

fn commands(command: &Command, name: &str, output: &mut Vec<Value>) -> Result<()> {
    let mut subcommands = Vec::new();
    if command.get_name() != "help" {
        for subcommand in command
            .get_subcommands()
            .filter(|command| !command.is_hide_set())
        {
            let child = subcommand.get_name();
            let description = subcommand
                .get_about()
                .context(format!("missing description for {name} {child}"))?;
            subcommands.push(json!({ "syntax": child, "description": description.to_string() }));
        }
    }
    let arguments = command
        .get_arguments()
        .filter(|arg| !arg.is_hide_set())
        .map(argument)
        .collect::<Result<Vec<_>>>()?;
    output.push(json!({
        "name": name,
        "description": command.get_about().map(ToString::to_string).unwrap_or_default(),
        "usage": command.clone().render_usage().to_string(),
        "notes": command.get_after_help().map(ToString::to_string).unwrap_or_default(),
        "subcommands": subcommands,
        "arguments": arguments,
    }));
    if command.get_name() != "help" {
        for subcommand in command
            .get_subcommands()
            .filter(|command| !command.is_hide_set())
        {
            commands(
                subcommand,
                &format!("{name} {}", subcommand.get_name()),
                output,
            )?;
        }
    }
    Ok(())
}

pub fn write(mut command: Command) -> Result<()> {
    command.build();
    let mut reference = Vec::new();
    commands(&command, "chopper", &mut reference)?;
    let mut output = io::stdout().lock();
    serde_json::to_writer_pretty(
        &mut output,
        &json!({
            "version": env!("CARGO_PKG_VERSION"),
            "commands": reference,
            "job_values": {
                "version": JOB_VERSION,
                "compression": Compression::CHOICES,
                "grouping": Grouping::CHOICES,
                "operation": Operation::CHOICES,
                "shuffle": Shuffle::CHOICES,
                "full_shuffle_rng": FullShuffleRng::CHOICES,
                "full_shuffle_algorithm": FullShuffleAlgorithm::CHOICES,
                "line_ending": LINE_ENDINGS,
                "encoding": ENCODINGS,
            },
        }),
    )?;
    writeln!(output)?;
    Ok(())
}
