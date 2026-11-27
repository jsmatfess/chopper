//! Native atomic publication of saved Job settings.
use super::JobSettings;
use crate::cli_job::MAX_JOB_BYTES;
use anyhow::{bail, ensure, Context, Result};
use std::{
    fs,
    io::{self, Write},
    path::Path,
};

pub(super) enum Mode {
    CompactNew,
    Pretty { overwrite: bool },
}

pub fn save_guide_configuration(
    job: &JobSettings,
    destination: &Path,
    overwrite: bool,
) -> Result<()> {
    write(job, destination, Mode::Pretty { overwrite })
}

/// Escape presentation only. Never feed this text back into the draft.
pub fn display_guide_text(value: &str) -> String {
    let mut shown: String = value
        .chars()
        .take(256)
        .flat_map(|c| {
            if c.is_control() {
                c.escape_default().collect::<Vec<_>>()
            } else {
                vec![c]
            }
        })
        .collect();
    if value.chars().nth(256).is_some() {
        shown.push_str(" [truncated]");
    }
    shown
}

#[cfg(test)]
thread_local! {
    static SAVE_WRITE_FAULT: std::cell::Cell<u8> = const { std::cell::Cell::new(0) };
    static SAVE_PERSIST_LEFTOVER: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub(super) fn write(job: &JobSettings, destination: &Path, mode: Mode) -> Result<()> {
    let parent = destination
        .parent()
        .context("configuration parent is required")?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    let result = (|| -> Result<()> {
        match mode {
            Mode::CompactNew => serde_json::to_writer(temp.as_file_mut(), job)?,
            Mode::Pretty { .. } => serde_json::to_writer_pretty(temp.as_file_mut(), job)?,
        }
        temp.write_all(b"\n")?;
        if matches!(mode, Mode::CompactNew) {
            ensure!(
                temp.as_file().metadata()?.len() <= MAX_JOB_BYTES,
                "configuration exceeds 1 MiB"
            );
        }
        #[cfg(test)]
        SAVE_WRITE_FAULT.with(|fault| -> Result<()> {
            match fault.replace(0) {
                1 => bail!("injected configuration write failure"),
                2 => {
                    let path = temp.path().to_owned();
                    fs::rename(&path, path.with_extension("retained"))?;
                    fs::create_dir(path)?;
                    bail!("injected configuration write failure with unlink denial");
                }
                _ => Ok(()),
            }
        })?;
        temp.flush()?;
        temp.as_file().sync_all()?;
        Ok(())
    })();
    if let Err(error) = result {
        let owned_path = temp.path().to_owned();
        return match temp.close() {
            Ok(()) => Err(error),
            Err(cleanup) => Err(error.context(format!(
                "temporary configuration cleanup {} failed: {cleanup}",
                display_guide_text(&owned_path.to_string_lossy())
            ))),
        };
    }
    let temporary_path = temp.path().to_owned();
    let persisted = match mode {
        Mode::Pretty { overwrite: true } => temp.persist(destination),
        _ => temp.persist_noclobber(destination),
    };
    if let Err(error) = persisted {
        let message = format!("atomic configuration save failed: {}", error.error);
        let owned_path = error.file.path().to_path_buf();
        if let Err(cleanup) = error.file.close() {
            bail!(
                "{message}; cleanup {} failed: {cleanup}",
                display_guide_text(&owned_path.to_string_lossy())
            );
        }
        bail!("{message}");
    }
    #[cfg(test)]
    SAVE_PERSIST_LEFTOVER.with(|fault| -> Result<()> {
        if fault.replace(false) {
            fs::hard_link(destination, &temporary_path)?;
        }
        Ok(())
    })?;
    // tempfile's no-clobber hard-link fallback can silently ignore unlink
    // failure after a successful publication. Report that committed save and
    // leftover path; do not risk deleting a pathname replaced by someone else.
    match fs::symlink_metadata(&temporary_path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => (),
        Err(error) => bail!(
            "configuration saved, but temporary cleanup {} could not be verified: {error}",
            display_guide_text(&temporary_path.to_string_lossy())
        ),
        Ok(_) => bail!(
            "configuration saved, but temporary cleanup {} did not complete; draft retained",
            display_guide_text(&temporary_path.to_string_lossy())
        ),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job::Job;

    #[test]
    fn atomic_write_failure_preserves_old_file_and_reports_cleanup_path() {
        let dir = tempfile::tempdir().unwrap();
        let job = JobSettings::for_files("input.csv", "out");
        let path = dir.path().join("job.json");
        save_guide_configuration(&job, &path, false).unwrap();
        let original = fs::read(&path).unwrap();
        for mode in [1, 2] {
            SAVE_WRITE_FAULT.with(|fault| fault.set(mode));
            let error = save_guide_configuration(&job, &path, true).unwrap_err();
            let text = format!("{error:#}");
            assert!(text.contains("injected configuration write failure"));
            assert_eq!(fs::read(&path).unwrap(), original);
            if mode == 2 {
                assert!(text.contains("temporary configuration cleanup"));
                assert!(text.contains(&display_guide_text(&dir.path().to_string_lossy())));
                for entry in fs::read_dir(dir.path()).unwrap() {
                    let path = entry.unwrap().path();
                    if path
                        .file_name()
                        .unwrap()
                        .to_string_lossy()
                        .starts_with(".tmp")
                    {
                        if path.is_dir() {
                            fs::remove_dir(path).unwrap();
                        } else {
                            fs::remove_file(path).unwrap();
                        }
                    }
                }
            } else {
                assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
            }
        }
    }
    #[test]
    fn successful_save_with_leftover_link_is_reported_without_deleting_config() {
        let dir = tempfile::tempdir().unwrap();
        let job = JobSettings::for_files("input.csv", "out");
        let path = dir.path().join("job.json");
        SAVE_PERSIST_LEFTOVER.with(|fault| fault.set(true));
        let error = Job::new(job).save(&path).unwrap_err();
        assert_eq!(error.code(), "config_write");
        assert!(error
            .to_string()
            .contains("configuration saved, but temporary cleanup"));
        assert_eq!(Job::load(&path).unwrap().settings().output, "out");
        for entry in fs::read_dir(dir.path()).unwrap() {
            let path = entry.unwrap().path();
            if path
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with(".tmp")
            {
                fs::remove_file(path).unwrap();
            }
        }
    }

    #[test]
    fn oversized_compact_save_removes_sibling_without_publishing() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("job.json");
        let job = Job::new(JobSettings::for_files(
            "x".repeat(MAX_JOB_BYTES as usize),
            "out",
        ));
        let error = job.save(&path).unwrap_err();
        assert_eq!(error.code(), "config_write");
        assert!(error.to_string().contains("configuration exceeds 1 MiB"));
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
    }
}
