#![cfg(not(target_os = "wasi"))]

use anyhow::Result;
use chopper::{core::*, engine};
use std::{
    fs,
    path::Path,
    process::Command,
    sync::{atomic::AtomicBool, Arc},
};

fn run_cli(root: &Path, output: &str, prepared: bool) -> Result<std::process::Output> {
    let mut command = Command::new(env!("CARGO_BIN_EXE_chopper"));
    command.current_dir(root).args([
        "run",
        "--input",
        "input.csv",
        "--output",
        output,
        "--yes",
        "--memory-mb",
        "32",
        "--workers",
        "1",
        "--max-record-bytes",
        "1048576",
    ]);
    if prepared {
        command.args([
            "--step",
            "shuffle",
            "--step",
            "balanced",
            "--files",
            "1",
            "--compression",
            "gzip",
        ]);
    }
    Ok(command.output()?)
}

#[test]
fn nonempty_destination_is_rejected_before_input() -> Result<()> {
    for prepared in [false, true] {
        let dir = tempfile::tempdir()?;
        let root = dir.path();
        fs::create_dir(root.join("results"))?;
        fs::write(root.join("results/keep.csv"), b"existing output\n")?;

        let result = run_cli(root, "results", prepared)?;
        let stderr = String::from_utf8(result.stderr)?;
        assert!(!result.status.success());
        assert!(
            stderr.contains("destination already exists and is not empty"),
            "{stderr}"
        );
        assert!(
            stderr.contains("choose a new or empty output directory"),
            "{stderr}"
        );
        assert!(
            !stderr.contains("open input") && !stderr.contains("Reading"),
            "{stderr}"
        );
        assert_eq!(
            fs::read(root.join("results/keep.csv"))?,
            b"existing output\n"
        );
        assert_eq!(fs::read_dir(root)?.count(), 1);

        let control = run_cli(root, "fresh", prepared)?;
        assert!(!control.status.success());
        assert!(String::from_utf8(control.stderr)?.contains("open input"));
        assert!(!root.join("fresh").exists());
    }
    Ok(())
}

#[test]
fn new_and_empty_destinations_accept_output() -> Result<()> {
    for prepared in [false, true] {
        let dir = tempfile::tempdir()?;
        let root = dir.path();
        fs::write(root.join("input.csv"), b"id\n1\n2\n")?;
        fs::create_dir(root.join("empty"))?;
        for output in ["fresh", "empty"] {
            let result = run_cli(root, output, prepared)?;
            assert!(
                result.status.success(),
                "{}",
                String::from_utf8_lossy(&result.stderr)
            );
            assert!(root.join(output).join("manifest.jsonl").is_file());
        }
    }
    Ok(())
}

#[test]
fn file_destination_is_rejected_before_input() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let root = dir.path();
    let output = root.join("results");
    fs::write(&output, b"existing output\n")?;
    reject_file_or_link_before_input(root, "results")?;
    assert_eq!(fs::read(output)?, b"existing output\n");
    assert_eq!(fs::read_dir(root)?.count(), 1);
    Ok(())
}

fn reject_file_or_link_before_input(root: &Path, output: &str) -> Result<()> {
    for prepared in [false, true] {
        let result = run_cli(root, output, prepared)?;
        let stderr = String::from_utf8(result.stderr)?;
        assert!(!result.status.success());
        assert!(stderr.contains("not a file or link"), "{stderr}");
        assert!(
            !stderr.contains("open input") && !stderr.contains("Reading"),
            "{stderr}"
        );
    }
    Ok(())
}

#[cfg(any(unix, windows))]
#[test]
fn destination_link_is_rejected_before_input_even_with_trailing_separator() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let root = dir.path();
    fs::create_dir(root.join("target"))?;
    #[cfg(unix)]
    std::os::unix::fs::symlink("target", root.join("results"))?;
    #[cfg(windows)]
    {
        let junction = Command::new("cmd.exe")
            .current_dir(root)
            .args(["/d", "/c", "mklink", "/J", "results", "target"])
            .output()?;
        assert!(
            junction.status.success(),
            "could not create junction: {}",
            String::from_utf8_lossy(&junction.stderr)
        );
    }
    for output in ["results", "results/"] {
        reject_file_or_link_before_input(root, output)?;
    }
    #[cfg(unix)]
    assert_eq!(fs::read_link(root.join("results"))?, Path::new("target"));
    #[cfg(windows)]
    assert_eq!(
        root.join("results").canonicalize()?,
        root.join("target").canonicalize()?
    );
    assert_eq!(fs::read_dir(root.join("target"))?.count(), 0);
    assert_eq!(fs::read_dir(root)?.count(), 2);
    Ok(())
}

#[test]
fn competing_empty_destination_survives_intake_and_publication_races() -> Result<()> {
    for (initially_empty, prepared, phase, rows) in [false, true].into_iter().flat_map(|empty| {
        [
            (empty, false, "Reading and writing CSV", 0),
            (empty, true, "Reading and validating CSV", 0),
            (empty, false, "Serializing output", 65_536),
            (empty, true, "Writing output", 65_536),
        ]
    }) {
        let dir = tempfile::tempdir()?;
        let root = dir.path();
        let output = root.join("results");
        let original = root.join("original");
        if initially_empty {
            fs::create_dir(&output)?;
        }
        let temp = root.join("temp");
        fs::create_dir(&temp)?;
        let input = root.join("input.csv");
        fs::write(&input, format!("id\n{}", "1\n".repeat(65_536)))?;
        let mut job = Job {
            input: input.to_string_lossy().into(),
            output: output.to_string_lossy().into(),
            resources: Resources {
                memory_mb: 32.into(),
                workers: 1,
                max_record_bytes: 1024 * 1024,
                temp_dir: Some(temp.to_string_lossy().into()),
                ..Default::default()
            },
            ..Default::default()
        };
        if prepared {
            job.operations = vec![
                Operation::Shuffle {
                    strategy: Shuffle::Uniform,
                },
                Operation::Balanced { files: 1 },
            ];
            job.compression = Compression::Gzip;
        }
        let competing = output.clone();
        let moved = original.clone();
        let result = engine::run(
            job,
            Arc::new(AtomicBool::new(false)),
            Arc::new(move |progress| {
                if progress.phase == phase && progress.rows == rows {
                    if initially_empty {
                        fs::rename(&competing, &moved).unwrap();
                    }
                    fs::create_dir(&competing).unwrap();
                }
            }),
        );
        let error = result.expect_err("Run accepted a competing directory");
        let diagnostic = format!("{error:#}");
        let expected = if initially_empty {
            "output destination changed during Run"
        } else if rows == 0 {
            "output destination appeared during Run"
        } else {
            "publish completed result directory"
        };
        assert!(diagnostic.contains(expected), "{phase}: {diagnostic}");
        assert_eq!(fs::read_dir(output)?.count(), 0, "{phase}");
        assert_eq!(fs::read_dir(temp)?.count(), 0, "{phase}");
        if initially_empty {
            assert_eq!(fs::read_dir(original)?.count(), 0, "{phase}");
        }
        assert_eq!(
            fs::read_dir(root)?.count(),
            3 + usize::from(initially_empty),
            "{phase}"
        );
    }
    Ok(())
}
