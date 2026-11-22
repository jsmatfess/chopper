//! Native, line-oriented slice A. Engine and configuration remain authoritative.
use anyhow::{bail, ensure, Context, Result};
use chopper::{core::*, engine, profile::ProfileCache, storage::Notify};
use std::{
    fs::{self, File},
    io::{self, IsTerminal, Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

const LINE_LIMIT: usize = 64 * 1024;
const JOB_LIMIT: u64 = 1024 * 1024;
const STEPS: [&str; 6] = [
    "Input",
    "Inspection",
    "Output",
    "Final caps",
    "Resources",
    "Review",
];

/// Escape presentation only. Never feed this text back into the draft.
fn display(value: &str) -> String {
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

trait Terminal {
    fn line(&mut self, prompt: &str, cancel: &AtomicBool) -> Result<String>;
    fn say(&mut self, text: &str) -> Result<()>;
}
#[derive(Debug)]
struct TerminalFailure(anyhow::Error);
impl std::fmt::Display for TerminalFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}
impl std::error::Error for TerminalFailure {}
fn terminal_error(error: anyhow::Error) -> anyhow::Error {
    TerminalFailure(error).into()
}
struct Console;
impl Terminal for Console {
    fn say(&mut self, text: &str) -> Result<()> {
        let mut err = io::stderr().lock();
        writeln!(err, "{text}").map_err(|e| terminal_error(e.into()))?;
        err.flush().map_err(|e| terminal_error(e.into()))?;
        Ok(())
    }
    fn line(&mut self, prompt: &str, cancel: &AtomicBool) -> Result<String> {
        self.say(prompt)?;
        #[cfg(windows)]
        {
            read_windows_line(cancel).map_err(terminal_error)
        }
        #[cfg(unix)]
        {
            use std::os::fd::AsFd;
            // Stdin's Rust line buffer can retain bytes after poll reports the
            // descriptor empty. Use an unbuffered duplicate for this response.
            let descriptor = io::stdin()
                .as_fd()
                .try_clone_to_owned()
                .map_err(|e| terminal_error(e.into()))?;
            read_line(&mut File::from(descriptor), cancel, wait_stdin).map_err(terminal_error)
        }
        #[cfg(not(any(unix, windows)))]
        {
            read_line(&mut io::stdin(), cancel, wait_stdin).map_err(terminal_error)
        }
    }
}
#[cfg(any(not(windows), test))]
fn read_line(
    reader: &mut impl Read,
    cancel: &AtomicBool,
    mut ready: impl FnMut() -> Result<bool>,
) -> Result<String> {
    let mut bytes = Vec::new();
    loop {
        ensure!(
            !cancel.load(Ordering::Relaxed),
            "guided session cancelled; no automatic save"
        );
        if !ready()? {
            continue;
        }
        let mut byte = [0];
        match reader.read(&mut byte) {
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            result => ensure!(
                result? == 1,
                "end of input; guided session aborted without saving"
            ),
        }
        if byte[0] == b'\n' {
            if bytes.last() == Some(&b'\r') {
                bytes.pop();
            }
            return String::from_utf8(bytes).context("response must be UTF-8");
        }
        // Do not drain an arbitrary remainder or interpret its suffix as a command.
        ensure!(
            bytes.len() < LINE_LIMIT,
            "response exceeds 64 KiB; session aborted without saving"
        );
        bytes.push(byte[0]);
    }
}
#[cfg(unix)]
fn wait_stdin() -> Result<bool> {
    let mut fd = libc::pollfd {
        fd: 0,
        events: libc::POLLIN,
        revents: 0,
    };
    let result = unsafe { libc::poll(&mut fd, 1, 50) };
    if result < 0 {
        let e = io::Error::last_os_error();
        if e.kind() == io::ErrorKind::Interrupted {
            return Ok(false);
        }
        return Err(e.into());
    }
    Ok(result > 0)
}
#[cfg(windows)]
fn wait_stdin() -> Result<bool> {
    use windows_sys::Win32::{
        Foundation::{WAIT_FAILED, WAIT_OBJECT_0},
        System::{
            Console::{GetStdHandle, STD_INPUT_HANDLE},
            Threading::WaitForSingleObject,
        },
    };
    let result = unsafe { WaitForSingleObject(GetStdHandle(STD_INPUT_HANDLE), 50) };
    ensure!(
        result != WAIT_FAILED,
        "wait for terminal input: {}",
        io::Error::last_os_error()
    );
    Ok(result == WAIT_OBJECT_0)
}
#[cfg(any(windows, test))]
fn console_character(
    unit: u16,
    repeats: u16,
    high: &mut Option<(u16, u16)>,
) -> Result<Option<(char, u16)>> {
    if repeats == 0 {
        return Ok(None);
    }
    if (0xd800..=0xdbff).contains(&unit) {
        ensure!(high.is_none(), "invalid UTF-16 terminal character");
        *high = Some((unit, repeats));
        return Ok(None);
    }
    let character = if (0xdc00..=0xdfff).contains(&unit) {
        let (h, count) = high.take().context("invalid UTF-16 terminal character")?;
        ensure!(count == repeats, "invalid UTF-16 terminal repeat count");
        char::from_u32(0x10000 + ((h as u32 - 0xd800) << 10) + unit as u32 - 0xdc00)
            .context("invalid UTF-16 terminal character")?
    } else {
        ensure!(high.is_none(), "invalid UTF-16 terminal character");
        char::from_u32(unit as u32).unwrap()
    };
    Ok(Some((character, repeats)))
}
// Read console events rather than blocking ReadFile in cooked line mode: a
// Ctrl+C must wake an idle value prompt even before Enter is pressed.
#[cfg(windows)]
fn read_windows_line(cancel: &AtomicBool) -> Result<String> {
    use windows_sys::Win32::System::Console::{
        GetStdHandle, ReadConsoleInputW, INPUT_RECORD, KEY_EVENT, STD_INPUT_HANDLE,
    };
    let mut line = String::new();
    let mut high = None;
    loop {
        ensure!(
            !cancel.load(Ordering::Relaxed),
            "guided session cancelled; no automatic save"
        );
        if !wait_stdin()? {
            continue;
        }
        let mut event: INPUT_RECORD = unsafe { std::mem::zeroed() };
        let mut count = 0;
        ensure!(
            unsafe { ReadConsoleInputW(GetStdHandle(STD_INPUT_HANDLE), &mut event, 1, &mut count) }
                != 0,
            "read terminal: {}",
            io::Error::last_os_error()
        );
        if count == 0 || event.EventType != KEY_EVENT as u16 {
            continue;
        }
        let key = unsafe { event.Event.KeyEvent };
        if key.bKeyDown == 0 {
            continue;
        }
        let unit = unsafe { key.uChar.UnicodeChar };
        if unit == 0 || key.wRepeatCount == 0 {
            continue;
        }
        if unit == 13 {
            ensure!(high.is_none(), "incomplete UTF-16 terminal character");
            writeln!(io::stderr())?;
            return Ok(line);
        }
        if unit == 26 || unit == 4 {
            bail!("end of input; guided session aborted without saving");
        }
        if unit == 8 {
            high = None;
            for _ in 0..key.wRepeatCount {
                ensure!(
                    !cancel.load(Ordering::Relaxed),
                    "guided session cancelled; no automatic save"
                );
                if line.pop().is_some() {
                    write!(io::stderr(), "\x08 \x08")?;
                }
            }
            continue;
        }
        let Some((character, repeats)) = console_character(unit, key.wRepeatCount, &mut high)?
        else {
            continue;
        };
        for _ in 0..repeats {
            ensure!(
                !cancel.load(Ordering::Relaxed),
                "guided session cancelled; no automatic save"
            );
            ensure!(
                line.len() + character.len_utf8() <= LINE_LIMIT,
                "response exceeds 64 KiB; session aborted without saving"
            );
            line.push(character);
            write!(io::stderr(), "{}", display(&character.to_string()))?;
        }
        io::stderr().flush()?;
    }
}
#[cfg(not(any(unix, windows)))]
fn wait_stdin() -> Result<bool> {
    bail!("guided terminal input is unsupported on this platform")
}

fn load(path: &Path) -> Result<Job> {
    // Bound actual reads too, including files that grow after metadata inspection.
    let mut data = Vec::new();
    File::open(path)?
        .take(JOB_LIMIT + 1)
        .read_to_end(&mut data)?;
    ensure!(
        data.len() as u64 <= JOB_LIMIT,
        "configuration exceeds 1 MiB"
    );
    let job: Job = serde_json::from_slice(&data).context("read version-1 Job JSON")?;
    ensure!(job.version == 1, "unsupported configuration version");
    Ok(job)
}
fn supported(job: &Job) -> Result<()> {
    ensure!(job.operations.is_empty(), "slice A does not support operations; use chopper run or slice B; imported operations retained");
    let defaults = serde_json::to_value(CsvSettings::default())?;
    ensure!(serde_json::to_value(&job.input_csv)? == defaults && serde_json::to_value(&job.output_csv)? == defaults,
        "slice A requires default UTF-8 headered CSV settings; use chopper run or slice C; import retained");
    ensure!(
        job.compression == Compression::None
            && job.zip_member.is_none()
            && job.limits.compressed_bytes.is_none(),
        "slice A supports plain CSV only; use chopper run or slice C; import retained"
    );
    Ok(())
}
fn absolute(path: &str) -> Result<PathBuf> {
    let path = Path::new(path);
    let joined = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    // Canonicalize existing ancestors, including symlinks, for collision checks.
    if joined.exists() {
        return Ok(fs::canonicalize(joined)?);
    }
    let parent = joined.parent().context("path needs a parent")?;
    Ok(fs::canonicalize(parent)?.join(joined.file_name().context("path needs a filename")?))
}
fn validate(job: &Job) -> Result<()> {
    supported(job)?;
    job.validate()?;
    ensure!(!job.output.is_empty(), "output path is required");
    ensure!(
        fs::metadata(&job.input)?.is_file(),
        "input must be a local regular file"
    );
    ensure!(
        engine::input_is_plain_csv(job)?,
        "slice A supports plain CSV input; compressed sources require scripted run or slice C"
    );
    let output = absolute(&job.output)?;
    ensure!(
        absolute(&job.input)? != output,
        "input and output must differ"
    );
    if output.exists() {
        ensure!(
            !fs::symlink_metadata(&job.output)?.file_type().is_symlink()
                && output.is_dir()
                && fs::read_dir(output)?.next().is_none(),
            "output must be absent or an empty directory; nothing will be overwritten"
        );
    }
    Ok(())
}
fn quote(path: &str) -> String {
    if cfg!(windows) {
        format!("'{}'", path.replace('\'', "''"))
    } else {
        format!("'{}'", path.replace('\'', "'\"'\"'"))
    }
}
#[cfg(test)]
thread_local! {
    static SAVE_WRITE_FAULT: std::cell::Cell<u8> = const { std::cell::Cell::new(0) };
    static SAVE_PERSIST_LEFTOVER: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

fn resource_description(job: &Job) -> String {
    format!("memory {:?} MiB (or auto), workers {}, temp_dir {}, temp_bytes {:?}, max_files {}, max_record_bytes {}, grouping {:?}", job.resources.memory_mb, job.resources.workers, display(job.resources.temp_dir.as_deref().unwrap_or("default")), job.resources.temp_bytes, job.resources.max_files, job.resources.max_record_bytes, job.resources.grouping)
}
fn save_file(job: &Job, path: &Path, overwrite: bool) -> Result<()> {
    let destination = absolute(path.to_str().context("configuration path must be UTF-8")?)?;
    let input = absolute(&job.input)?;
    let output = absolute(&job.output)?;
    ensure!(
        destination != input && !destination.starts_with(&output),
        "configuration must not replace input or be inside output"
    );
    ensure!(
        !path.exists() || !fs::symlink_metadata(path)?.file_type().is_symlink(),
        "refusing configuration symlink"
    );
    let parent = destination
        .parent()
        .context("configuration parent is required")?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    let result = (|| -> Result<()> {
        serde_json::to_writer_pretty(temp.as_file_mut(), job)?;
        temp.write_all(b"\n")?;
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
                display(&owned_path.to_string_lossy())
            ))),
        };
    }
    let temporary_path = temp.path().to_owned();
    let persisted = if overwrite {
        temp.persist(&destination)
    } else {
        temp.persist_noclobber(&destination)
    };
    if let Err(error) = persisted {
        let message = format!("atomic configuration save failed: {}", error.error);
        let owned_path = error.file.path().to_path_buf();
        if let Err(cleanup) = error.file.close() {
            bail!(
                "{message}; cleanup {} failed: {cleanup}",
                display(&owned_path.to_string_lossy())
            );
        }
        bail!("{message}");
    }
    #[cfg(test)]
    SAVE_PERSIST_LEFTOVER.with(|fault| -> Result<()> {
        if fault.replace(false) {
            fs::hard_link(&destination, &temporary_path)?;
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
            display(&temporary_path.to_string_lossy())
        ),
        Ok(_) => bail!(
            "configuration saved, but temporary cleanup {} did not complete; draft retained",
            display(&temporary_path.to_string_lossy())
        ),
    }
    Ok(())
}

struct Session {
    job: Job,
    dirty: bool,
    step: usize,
    cache: ProfileCache,
    inspected: bool,
}
impl Session {
    fn new(job: Job) -> Self {
        Self {
            job,
            dirty: false,
            step: 0,
            cache: ProfileCache::default(),
            inspected: false,
        }
    }
    fn confirm(&self, io: &mut impl Terminal, cancel: &AtomicBool, prompt: &str) -> Result<bool> {
        Ok(matches!(
            io.line(&format!("{prompt} [y/N]"), cancel)?
                .trim()
                .to_ascii_lowercase()
                .as_str(),
            "y" | "yes"
        ))
    }
    fn save(&mut self, io: &mut impl Terminal, cancel: &AtomicBool) -> Result<bool> {
        validate(&self.job)?;
        let path = io.line("Save: configuration path (empty returns)", cancel)?;
        if path.is_empty() {
            return Ok(false);
        }
        let path = PathBuf::from(path);
        let overwrite = path.try_exists()?;
        if overwrite && !self.confirm(io, cancel, "Overwrite existing configuration atomically?")? {
            return Ok(false);
        }
        save_file(&self.job, &path, overwrite)?;
        self.dirty = false;
        let path = absolute(path.to_str().context("configuration path must be UTF-8")?)?;
        // Command text is copyable shell syntax. Escape terminal controls, but do
        // not truncate this one actionable command; reject controls in paths.
        let path = path.to_str().context("configuration path must be UTF-8")?;
        if path.chars().count() <= 256 && !path.chars().any(char::is_control) {
            io.say(&format!(
                "Saved. {}chopper run --config {} --yes",
                if cfg!(windows) {
                    "PowerShell: "
                } else {
                    "POSIX shell: "
                },
                quote(path)
            ))?;
        } else {
            io.say("Saved. Configuration path is long or contains controls; pass it as a literal argument to chopper run --config PATH --yes.")?;
        }
        io.say("Reruns need an available output destination. Optional run --memory-mb/--workers override saved resources. Relative paths use the process working directory.")?;
        Ok(true)
    }
    fn edit(&mut self, io: &mut impl Terminal, cancel: &AtomicBool) -> Result<()> {
        let prompt = match self.step {
            0 => "Input path (literal UTF-8; empty keeps current)",
            2 => "Output directory (literal UTF-8; empty keeps current)",
            3 => "Caps: 1 rows, 2 serialized CSV bytes (includes header/quoting/newlines; KB decimal, KiB binary)",
            4 => "Resources: 1 memory MiB/auto, 2 workers, 3 temp_dir, 4 temp_bytes, 5 max_files, 6 max_record_bytes, 7 grouping auto/sort",
            _ => return Ok(()),
        };
        let value = io.line(prompt, cancel)?;
        if value.is_empty() {
            return Ok(());
        }
        match self.step {
            0 | 2 => {
                io.say(&format!(
                    "cwd: {}; absolute interpretation: {}",
                    display(&std::env::current_dir()?.to_string_lossy()),
                    display(&absolute(&value)?.to_string_lossy())
                ))?;
                if self.confirm(io, cancel, "Accept path?")? {
                    if self.step == 0 {
                        self.job.input = value;
                        self.cache.clear();
                        self.inspected = false;
                    } else {
                        self.job.output = value;
                    }
                    self.dirty = true;
                }
            }
            3 => {
                ensure!(matches!(value.as_str(), "1" | "2"), "choose 1 or 2");
                let answer = io.line("Value (empty keeps current; 0 removes cap)", cancel)?;
                if answer.is_empty() {
                    return Ok(());
                }
                let parsed = if value == "1" {
                    answer.parse()?
                } else {
                    parse_bytes(&answer)?
                };
                let cap = if parsed == 0 { None } else { Some(parsed) };
                if value == "1" {
                    self.job.limits.rows = cap;
                } else {
                    self.job.limits.bytes = cap;
                }
                self.dirty = true;
            }
            4 => {
                let answer = io.line(
                    "Value (empty keeps current; '-' clears optional temp setting)",
                    cancel,
                )?;
                if answer.is_empty() {
                    return Ok(());
                }
                match value.as_str() {
                    "1" => {
                        self.job.resources.memory_mb = answer.parse().map_err(anyhow::Error::msg)?
                    }
                    "2" => self.job.resources.workers = answer.parse()?,
                    "3" => {
                        self.job.resources.temp_dir =
                            if answer == "-" { None } else { Some(answer) }
                    }
                    "4" => {
                        self.job.resources.temp_bytes = if answer == "-" {
                            None
                        } else {
                            Some(parse_bytes(&answer)?)
                        }
                    }
                    "5" => self.job.resources.max_files = answer.parse()?,
                    "6" => {
                        self.job.resources.max_record_bytes = parse_bytes(&answer)?.try_into()?
                    }
                    "7" => {
                        self.job.resources.grouping = match answer.as_str() {
                            "auto" => Grouping::Auto,
                            "sort" => Grouping::Sort,
                            _ => bail!("grouping must be auto or sort"),
                        }
                    }
                    _ => bail!("choose resource 1 through 7"),
                }
                self.cache.clear();
                self.inspected = false;
                self.dirty = true;
            }
            _ => unreachable!(),
        }
        Ok(())
    }
    fn review(&mut self, io: &mut impl Terminal) -> Result<()> {
        validate(&self.job)?;
        io.say(&format!("Review: cwd {}\nInput {}\nOutput {}\nDefault UTF-8, headered comma CSV, doubled quotes, LF, no BOM. No operations; plain CSV.\nRows cap {:?}; serialized CSV bytes cap {:?}. File count, bytes and time unknown.\nAlgorithm {}; randomized output order may vary.\nInspection {}; Run validates fresh input. Use analyze for a separate input scan and pipeline estimates.\nResources: {}\nNo overwrite. Native private staging and atomic directory publication; cleanup on failure/cancellation.",
            display(&std::env::current_dir()?.to_string_lossy()), display(&absolute(&self.job.input)?.to_string_lossy()), display(&absolute(&self.job.output)?.to_string_lossy()), self.job.limits.rows, self.job.limits.bytes,
            ALGORITHM_VERSION, if self.inspected { "completed previously; advisory only" } else { "not retained" }, resource_description(&self.job)))
    }
    fn journey(
        &mut self,
        io: &mut impl Terminal,
        cancel: Arc<AtomicBool>,
        notify: Notify,
    ) -> Result<Option<engine::Analysis>> {
        loop {
            ensure!(
                !cancel.load(Ordering::Relaxed),
                "guided session cancelled; owners stopped; no automatic save"
            );
            io.say(&format!(
                "Step {}: {} | input {} | output {} | dirty {}\nRows {:?}; bytes {:?}",
                self.step + 1,
                STEPS[self.step],
                display(&self.job.input),
                display(&self.job.output),
                self.dirty,
                self.job.limits.rows,
                self.job.limits.bytes
            ))?;
            if self.step == 4 {
                io.say(&resource_description(&self.job))?;
            }
            let action = io.line("1 Edit / inspect / review; 2 Next; 90 Back; 91 Edit step; 92 Save; 93 Reload; 94 Help; 95 Cancel; 96 Save and exit; 97 Convert paths to absolute; 98 Run (review)", &cancel)?;
            let result = (|| -> Result<Option<bool>> {
                match action.trim() {
                    "" => (),
                    "2" => self.step = (self.step + 1).min(5),
                    "90" => self.step = self.step.saturating_sub(1),
                    "91" => {
                        let n: usize = io.line("Edit step 1 Input, 2 Inspection, 3 Output, 4 Caps, 5 Resources, 6 Review", &cancel)?.parse()?;
                        ensure!((1..=6).contains(&n), "step must be 1 through 6"); self.step = n - 1;
                    }
                    "92" => { self.save(io, &cancel)?; }
                    "93" => {
                        if !self.dirty || self.confirm(io, &cancel, "Discard unsaved changes and reload?")? {
                            let path = io.line("Reload configuration path (empty returns)", &cancel)?;
                            if !path.is_empty() {
                                let job = load(Path::new(&path))?;
                                self.job = job; self.dirty = false; self.cache.clear(); self.inspected = false;
                                io.say(&format!("Loaded intact; cwd remains {}", display(&std::env::current_dir()?.to_string_lossy())))?;
                                supported(&self.job)?;
                            }
                        }
                    }
                    "94" => io.say("Slice A: typed local default UTF-8 headered CSV, no operations, strict row/serialized-byte caps. Data prompts accept literal command words. Inspection is optional. Memory defaults to 256 MiB; workers 0 automatic. Auto memory resolves at task start from shared admission; working allocations are not an RSS cap. Workers do not parallelize every phase. Existing engine validation remains authoritative. Ctrl+C/EOF abort without saving.")?,
                    "95" => {
                        if self.dirty && self.confirm(io, &cancel, "Save dirty draft before cancelling?")? && !self.save(io, &cancel)? { return Ok(None); }
                        return Ok(Some(false));
                    }
                    "96" => { if self.save(io, &cancel)? { return Ok(Some(false)); } }
                    "97" => {
                        // Compute every conversion before accepting the edit.
                        let input = absolute(&self.job.input)?.to_str().context("input path must be UTF-8")?.to_owned();
                        let output = absolute(&self.job.output)?.to_str().context("output path must be UTF-8")?.to_owned();
                        let temp = self.job.resources.temp_dir.as_deref().map(absolute).transpose()?.map(|p| p.to_str().context("temp path must be UTF-8").map(str::to_owned)).transpose()?;
                        self.job.input = input; self.job.output = output; self.job.resources.temp_dir = temp; self.dirty = true;
                    }
                    "1" => match self.step {
                        1 => {
                            supported(&self.job)?; self.job.validate()?;
                            ensure!(fs::metadata(&self.job.input)?.is_file(), "input must be a local regular file");
                            ensure!(engine::input_is_plain_csv(&self.job)?, "slice A supports plain CSV input; use scripted run or slice C");
                            io.say(if self.inspected { "Repeat inspection: the cache checks source/parser/resources; a changed identity or Windows requires a new full scan." } else { "Initial inspection, or input/resource identity changed: request full-file observations." })?;
                            io.say("Inspect input (full scan): reads and validates the entire source, writes no output CSV or row spool. Bounded examples may skip wide rows; not a random sample or a later Run certificate. Cache identity decides reuse; Windows rescans.")?;
                            if self.confirm(io, &cancel, "Start full scan?")? {
                                let profile = self.cache.profile(&self.job, cancel.clone(), notify.clone())?;
                                io.say(&format!("Completed full scan: {} exact rows; {} columns; cache hit {}. Bounded preview (first 8 columns only):", profile.rows, profile.columns, profile.cache_hit))?;
                                if let Some(header) = &profile.header { for (i, field) in header.iter().take(8).enumerate() { io.say(&format!("column {i}: {}", display(field)))?; } }
                                for row in profile.preview.iter().take(8) { io.say(&row.iter().take(8).map(|v| display(v)).collect::<Vec<_>>().join(" | "))?; }
                                self.inspected = true;
                            }
                        }
                        5 => self.review(io)?,
                        _ => self.edit(io, &cancel)?,
                    },
                    "98" => {
                        ensure!(self.step == 5, "move to Review before Run");
                        self.review(io)?;
                        if self.confirm(io, &cancel, &format!("Run fresh validation of {} to {}?", display(&self.job.input), display(&self.job.output)))? { return Ok(Some(true)); }
                    }
                    _ => bail!("choose a displayed number; data is entered at a separate value prompt"),
                }
                Ok(None)
            })();
            // EOF/terminal errors must not turn into recoverable editing errors.
            match result {
                Ok(Some(false)) => return Ok(None),
                Ok(Some(true)) => {
                    self.cache.clear();
                    match engine::run(self.job.clone(), cancel.clone(), notify.clone()) {
                        Ok(analysis) => return Ok(Some(analysis)),
                        Err(error) => {
                            io.say(&format!("Run failed after owners stopped: {}. No successful result published; draft retained.", display(&format!("{error:#}"))))?;
                            self.step = 5;
                        }
                    }
                }
                Ok(None) => (),
                Err(error) => {
                    if cancel.load(Ordering::Relaxed) || error.is::<TerminalFailure>() {
                        return Err(error);
                    }
                    io.say(&format!(
                        "Error: {}. Draft retained.",
                        display(&format!("{error:#}"))
                    ))?;
                }
            }
        }
    }
}

pub(super) fn run(config: Option<PathBuf>) -> Result<()> {
    run_inner(config).map_err(|error| anyhow::anyhow!("{}", display(&format!("{error:#}"))))
}
fn run_inner(config: Option<PathBuf>) -> Result<()> {
    ensure!(io::stdin().is_terminal() && io::stderr().is_terminal(), "guide requires terminal stdin and stderr; use chopper run --config PATH --yes for automation");
    let cancel = Arc::new(AtomicBool::new(false));
    let signal = cancel.clone();
    ctrlc::set_handler(move || {
        signal.store(true, Ordering::Relaxed);
        #[cfg(feature = "resource-contract-tests")]
        if std::env::var_os("CHOPPER_GUIDE_TEST_PHASE").is_some() {
            eprintln!("guide test interrupt received");
        }
    })?;
    let job = config.as_deref().map(load).transpose()?.unwrap_or_default();
    let mut session = Session::new(job);
    let mut console = Console;
    if let Err(error) = supported(&session.job) {
        console.say(&format!(
            "Import retained: {}",
            display(&format!("{error:#}"))
        ))?;
    }
    let progress_cancel = cancel.clone();
    let notify: Notify = Arc::new(move |p| {
        if writeln!(
            io::stderr(),
            "{} | {} rows | {} temporary bytes",
            display(&p.phase),
            p.rows,
            p.temp_bytes
        )
        .is_err()
        {
            progress_cancel.store(true, Ordering::Relaxed);
        }
    });
    if let Some(analysis) = session.journey(&mut console, cancel, notify)? {
        // Publication is complete. No subsequent I/O error retries/deletes it.
        console.say(&format!("Completed: {} / manifest.jsonl; {} rows, {} groups, {} CSV files, {} CSV bytes; version {}, memory {} bytes, {} workers.", display(&session.job.output), analysis.rows, analysis.groups, analysis.output_files, analysis.output_csv_bytes, analysis.algorithm_version, analysis.memory_budget_bytes, analysis.workers)).context("output committed; completion reporting failed; do not retry or delete output")?;
        for warning in analysis.warnings.iter() {
            console
                .say(&format!("Warning: {}", display(warning)))
                .context("output committed; warning reporting failed")?;
        }
        super::cli_json::write_pretty(&mut io::stdout().lock(), &analysis)
            .context("output committed; stdout reporting failed; do not retry or delete output")?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;
    use std::collections::VecDeque;
    struct Transcript {
        answers: VecDeque<String>,
        output: String,
    }
    impl Transcript {
        fn new(lines: &[&str]) -> Self {
            Self {
                answers: lines.iter().map(|s| s.to_string()).collect(),
                output: String::new(),
            }
        }
    }
    impl Terminal for Transcript {
        fn say(&mut self, text: &str) -> Result<()> {
            self.output.push_str(text);
            self.output.push('\n');
            Ok(())
        }
        fn line(&mut self, prompt: &str, _: &AtomicBool) -> Result<String> {
            self.say(prompt)?;
            self.answers
                .pop_front()
                .ok_or_else(|| terminal_error(anyhow::anyhow!("end of input")))
        }
    }
    fn fixture() -> (tempfile::TempDir, Job) {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("source 雪.csv");
        fs::write(&input, "id,text\n1,\"a,b\"\n2,\"a\nline\"\n3,end\n").unwrap();
        let job = Job {
            input: input.to_str().unwrap().into(),
            output: dir.path().join("out").to_str().unwrap().into(),
            ..Job::default()
        };
        (dir, job)
    }
    fn journey(
        session: &mut Session,
        transcript: &mut Transcript,
    ) -> Result<Option<engine::Analysis>> {
        session.journey(
            transcript,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )
    }
    #[test]
    fn response_bounds_utf8_eof_and_cancel() {
        let cancel = AtomicBool::new(false);
        for mut data in [b"".as_slice(), b"unterminated", &[255, b'\n']] {
            assert!(read_line(&mut data, &cancel, || Ok(true)).is_err());
        }
        let mut exact = vec![b'x'; LINE_LIMIT];
        exact.push(b'\n');
        assert_eq!(
            read_line(&mut exact.as_slice(), &cancel, || Ok(true))
                .unwrap()
                .len(),
            LINE_LIMIT
        );
        exact.insert(0, b'x');
        assert!(read_line(&mut exact.as_slice(), &cancel, || Ok(true))
            .unwrap_err()
            .to_string()
            .contains("64 KiB"));
        cancel.store(true, Ordering::Relaxed);
        assert!(read_line(&mut b"yes\n".as_slice(), &cancel, || panic!(
            "must not read after cancel"
        ))
        .is_err());
    }
    #[test]
    fn console_repeats_preserve_characters_and_surrogate_pairs() {
        let mut high = None;
        assert_eq!(
            console_character('z' as u16, 3, &mut high).unwrap(),
            Some(('z', 3))
        );
        assert_eq!(console_character(0xd83d, 3, &mut high).unwrap(), None);
        assert_eq!(
            console_character(0xde00, 3, &mut high).unwrap(),
            Some(('😀', 3))
        );
        assert!(high.is_none());
        assert_eq!(console_character(0xd83d, 2, &mut high).unwrap(), None);
        assert!(console_character(0xde00, 1, &mut high).is_err());
        assert!(console_character(0xde00, 1, &mut high).is_err());
        assert_eq!(console_character('z' as u16, 0, &mut high).unwrap(), None);
    }
    #[test]
    fn presentation_preserves_data_and_shell_quoting() {
        assert_eq!(display("雪\n\u{1b}[31m"), "雪\\n\\u{1b}[31m");
        assert!(display(&"x".repeat(257)).ends_with("[truncated]"));
        if !cfg!(windows) {
            assert_eq!(quote("a'b 雪"), "'a'\"'\"'b 雪'");
        }
    }
    #[test]
    fn command_words_are_literal_data_and_empty_navigation_keeps_step() {
        let mut s = Session::new(Job::default());
        let mut t = Transcript::new(&["", "1", "back", "yes", "95", ""]);
        journey(&mut s, &mut t).unwrap();
        assert_eq!(s.job.input, "back");
        assert_eq!(s.step, 0);
        assert!(crate::Cli::try_parse_from(["chopper", "guide", "--yes"]).is_err());
    }
    #[test]
    fn atomic_write_failure_preserves_old_file_and_reports_cleanup_path() {
        let (dir, job) = fixture();
        let path = dir.path().join("job.json");
        save_file(&job, &path, false).unwrap();
        let original = fs::read(&path).unwrap();
        for mode in [1, 2] {
            SAVE_WRITE_FAULT.with(|fault| fault.set(mode));
            let error = save_file(&job, &path, true).unwrap_err();
            let text = format!("{error:#}");
            assert!(text.contains("injected configuration write failure"));
            assert_eq!(fs::read(&path).unwrap(), original);
            if mode == 2 {
                assert!(text.contains("temporary configuration cleanup"));
                assert!(text.contains(&display(&dir.path().to_string_lossy())));
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
            }
        }
    }
    #[test]
    fn successful_save_with_leftover_link_is_reported_without_deleting_config() {
        let (dir, job) = fixture();
        let path = dir.path().join("job.json");
        SAVE_PERSIST_LEFTOVER.with(|fault| fault.set(true));
        let error = save_file(&job, &path, false).unwrap_err();
        assert!(error
            .to_string()
            .contains("configuration saved, but temporary cleanup"));
        assert_eq!(load(&path).unwrap().random_seed, job.random_seed);
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
    fn imported_unsupported_fields_are_retained() {
        let (_, mut job) = fixture();
        job.operations.push(Operation::Balanced { files: 2 });
        let before = serde_json::to_value(&job).unwrap();
        assert!(supported(&job).is_err());
        assert_eq!(before, serde_json::to_value(&job).unwrap());
        job.operations.clear();

        assert!(supported(&job).is_ok());

        job.input_csv.headers = false;
        assert!(supported(&job).is_err());
    }
    #[test]
    fn import_actual_byte_bound_and_strict_schema() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("job.json");
        for data in [
            "{\"version\":2}".to_string(),
            "{\"unknown\":1}".into(),
            "{".into(),
            " ".repeat(JOB_LIMIT as usize + 1),
        ] {
            fs::write(&path, data).unwrap();
            let result = load(&path);
            assert!(result.is_err());
        }
    }
    #[test]
    fn unsupported_reload_keeps_the_edited_draft() {
        let (dir, mut job) = fixture();
        job.limits.rows = Some(7);
        let before = serde_json::to_value(&job).unwrap();
        let path = dir.path().join("future-job.json");
        fs::write(&path, r#"{"version":2}"#).unwrap();
        let mut session = Session::new(job);
        session.dirty = true;
        session.inspected = true;
        let mut transcript = Transcript::new(&["93", "yes", path.to_str().unwrap(), "95", ""]);
        assert!(journey(&mut session, &mut transcript).unwrap().is_none());
        assert_eq!(serde_json::to_value(&session.job).unwrap(), before);
        assert!(session.dirty);
        assert!(session.inspected);
        assert!(transcript
            .output
            .contains("unsupported configuration version"));
        assert!(!transcript.output.contains("Loaded intact"));
    }
    #[test]
    fn back_edit_and_default_no_never_run() {
        let (_dir, job) = fixture();
        let mut s = Session::new(job);
        let mut t = Transcript::new(&[
            "91", "4", "1", "1", "2", "90", "91", "6", "98", "", "95", "",
        ]);
        assert!(journey(&mut s, &mut t).unwrap().is_none());
        assert_eq!(s.job.limits.rows, Some(2));
        assert!(s.job.random_seed.is_none());
        assert!(!Path::new(&s.job.output).exists());
    }
    #[test]
    fn eof_at_all_navigation_and_confirmation_types_never_saves() {
        for lines in [
            vec![],
            vec!["1"],
            vec!["1", "back"],
            vec!["92"],
            vec!["91", "6", "98"],
            vec!["93"],
            vec!["95"],
        ] {
            let (_dir, job) = fixture();
            let mut s = Session::new(job);
            s.dirty = true;
            let mut t = Transcript::new(&lines);
            assert!(journey(&mut s, &mut t).is_err(), "{lines:?}: {}", t.output);
            assert!(!Path::new(&s.job.output).exists());
        }
    }
    #[test]
    fn atomic_save_collisions_noclobber_replace_and_failure() {
        let (dir, mut job) = fixture();
        let saved_seed = job.random_seed.clone();
        let path = dir.path().join("job's 雪.json");
        save_file(&job, &path, false).unwrap();
        assert_eq!(load(&path).unwrap().random_seed, saved_seed);
        job.limits.rows = Some(1);
        assert!(save_file(&job, &path, false).is_err());
        assert!(load(&path).unwrap().limits.rows.is_none());
        save_file(&job, &path, true).unwrap();
        assert_eq!(load(&path).unwrap().limits.rows, Some(1));
        assert!(save_file(&job, Path::new(&job.input), true).is_err());
        fs::create_dir(&job.output).unwrap();
        assert!(save_file(&job, &Path::new(&job.output).join("job.json"), false).is_err());
        assert!(save_file(&job, Path::new(&job.output), true).is_err());
        assert_eq!(job.random_seed, saved_seed);
        assert!(!fs::read_dir(dir.path()).unwrap().any(|p| p
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".tmp")));
    }
    #[test]
    fn save_reload_discard_default_no_and_overwrite_eof() {
        let (dir, job) = fixture();
        let path = dir.path().join("job.json");
        let mut s = Session::new(job);
        let mut t = Transcript::new(&[path.to_str().unwrap()]);
        assert!(s.save(&mut t, &AtomicBool::new(false)).unwrap());
        let saved = fs::read(&path).unwrap();
        let retained_seed = s.job.random_seed.clone();
        s.job.limits.rows = Some(2);
        s.dirty = true;
        let mut t = Transcript::new(&["93", "", "95", ""]);
        assert!(journey(&mut s, &mut t).unwrap().is_none());
        assert_eq!(s.job.limits.rows, Some(2));
        assert_eq!(s.job.random_seed, retained_seed);
        let mut t = Transcript::new(&[path.to_str().unwrap(), ""]);
        assert!(!s.save(&mut t, &AtomicBool::new(false)).unwrap());
        assert_eq!(fs::read(&path).unwrap(), saved);
        let mut t = Transcript::new(&[path.to_str().unwrap()]);
        assert!(s.save(&mut t, &AtomicBool::new(false)).is_err());
        assert_eq!(fs::read(&path).unwrap(), saved);
        let mut t = Transcript::new(&["93", "yes", path.to_str().unwrap(), "95"]);
        journey(&mut s, &mut t).unwrap();
        assert!(s.job.limits.rows.is_none());
        assert_eq!(s.job.random_seed, retained_seed);
    }
    #[test]
    fn inspection_does_not_modify_executable_job_and_cancel_joins() {
        let (_dir, job) = fixture();
        let before = serde_json::to_value(&job).unwrap();
        let mut s = Session::new(job);
        let mut t = Transcript::new(&["2", "1", "yes", "95"]);
        journey(&mut s, &mut t).unwrap();
        assert!(s.inspected);
        assert_eq!(before, serde_json::to_value(&s.job).unwrap());
        assert!(t.output.contains("3 exact rows"));
        let cancel = Arc::new(AtomicBool::new(false));
        let signal = cancel.clone();
        let mut cache = ProfileCache::default();
        let result = cache.profile(
            &s.job,
            cancel.clone(),
            Arc::new(move |_| signal.store(true, Ordering::Relaxed)),
        );
        drop(result);
        drop(cache);
        assert!(cancel.load(Ordering::Relaxed));
        assert!(!Path::new(&s.job.output).exists());
    }
    #[test]
    fn recoverable_load_save_run_errors_retain_draft() {
        let (_dir, job) = fixture();
        let mut s = Session::new(job);
        s.step = 5;
        s.job.limits.bytes = Some(1);
        let mut t = Transcript::new(&["98", "yes", "95", ""]);
        assert!(journey(&mut s, &mut t).unwrap().is_none());
        assert!(t.output.contains("Run failed after owners stopped"));
        assert!(s.job.random_seed.is_none());
        assert_eq!(s.job.limits.bytes, Some(1));
        assert!(!Path::new(&s.job.output).exists());
        let mut t = Transcript::new(&["92", "/missing-parent-106/job.json", "95", ""]);
        assert!(journey(&mut s, &mut t).unwrap().is_none());
        assert!(t.output.contains("Error:"));
    }
}
