#[cfg(target_os = "linux")]
use serde_json::Value;
use std::{fs, path::Path, process::Command};

fn run(input: &Path, destination: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_chopper"));
    command
        .args(["run", "--input"])
        .arg(input)
        .arg("--output")
        .arg(destination)
        .args(["--memory-mb", "128", "--workers", "1", "--yes"]);
    command
}

#[test]
fn invalid_ordered_arguments_have_usage_exit_status() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("missing.csv");
    let destination = dir.path().join("result");
    let failed = run(&input, &destination)
        .args(["--step", "shuffle", "--by", "name"])
        .output()
        .unwrap();

    let diagnostic = String::from_utf8_lossy(&failed.stderr);
    assert_eq!(failed.status.code(), Some(2), "{diagnostic}");
    assert!(diagnostic.contains("does not apply"), "{diagnostic}");
    assert!(failed.stdout.is_empty());
    assert!(!destination.exists());
}

#[test]
fn unhandled_calculation_error_keeps_the_destination_private() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let destination = dir.path().join("result");
    fs::write(&input, "amount\n120\nunknown\n").unwrap();
    let failed = run(&input, &destination)
        .args(["--calculated-column", "total=NUMBER(amount)"])
        .output()
        .unwrap();
    let diagnostic = String::from_utf8_lossy(&failed.stderr);
    assert_eq!(failed.status.code(), Some(1), "{diagnostic}");
    assert!(
        diagnostic.contains("input record 2, calculated column \"total\""),
        "{diagnostic}"
    );
    assert!(diagnostic.contains("invalid number"), "{diagnostic}");
    assert!(failed.stdout.is_empty());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
}

#[test]
fn malformed_input_reports_prepublication_failure_and_cleans_staging() {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let destination = dir.path().join("result");
    fs::write(&input, "id,name\n1,A\n2,B,extra\n").unwrap();
    let failed = run(&input, &destination)
        .args(["--rows", "1"])
        .output()
        .unwrap();

    let diagnostic = String::from_utf8_lossy(&failed.stderr);
    assert_eq!(failed.status.code(), Some(1), "{diagnostic}");
    assert!(diagnostic.contains("before publication"), "{diagnostic}");
    assert!(diagnostic.contains("fields"), "{diagnostic}");
    assert!(failed.stdout.is_empty());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    assert!(!destination.exists());
}

#[cfg(target_os = "linux")]
#[test]
fn stdout_failure_reports_committed_run_and_preserves_results() {
    check_stdout_failure(&[]);
    check_stdout_failure(&["--summary"]);
}

#[cfg(target_os = "linux")]
fn check_stdout_failure(args: &[&str]) {
    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let destination = dir.path().join("result");
    fs::write(&input, "id,name\n1,A\n2,B\n").unwrap();
    let full = fs::OpenOptions::new()
        .write(true)
        .open("/dev/full")
        .unwrap();
    let failed = run(&input, &destination)
        .args(args)
        .stdout(full)
        .output()
        .unwrap();

    let diagnostic = String::from_utf8_lossy(&failed.stderr);
    assert_eq!(failed.status.code(), Some(3), "{diagnostic}");
    assert!(diagnostic.contains("output committed"), "{diagnostic}");
    assert!(diagnostic.contains("stdout report"), "{diagnostic}");
    assert!(diagnostic.contains("before retrying"), "{diagnostic}");
    assert!(
        diagnostic.contains("configured destination"),
        "{diagnostic}"
    );

    let manifest = fs::read_to_string(destination.join("manifest.jsonl")).unwrap();
    let records: Vec<Value> = manifest
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(records.len(), 2);
    assert_eq!(records[0]["type"], "job");
    assert_eq!(records[0]["analysis"]["rows"], 2);
    assert_eq!(records[0]["analysis"]["output_files"], 1);
    assert_eq!(records[1]["rows"], 2);
    assert_eq!(
        fs::read_to_string(destination.join(records[1]["path"].as_str().unwrap())).unwrap(),
        "id,name\n1,A\n2,B\n"
    );
}

#[cfg(all(target_os = "linux", feature = "resource-contract-tests"))]
#[test]
fn sigint_during_run_stops_before_commit_and_cleans_staging() {
    use std::{
        io::{BufRead, BufReader, Write},
        process::Stdio,
        sync::mpsc,
        time::Duration,
    };

    let dir = tempfile::tempdir().unwrap();
    let input = dir.path().join("input.csv");
    let destination = dir.path().join("result");
    fs::write(&input, "id,name\n1,A\n2,B\n").unwrap();
    let mut child = run(&input, &destination)
        .env("CHOPPER_GUIDE_TEST_PHASE", "direct-row")
        .env("CHOPPER_GUIDE_TEST_RELEASE", "/proc/self/fd/0")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    let (send, receive) = mpsc::channel();
    let stderr = child.stderr.take().unwrap();
    let reader = std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            if send.send(line.unwrap()).is_err() {
                break;
            }
        }
    });
    let wait_for = |marker: &str| loop {
        let line = receive
            .recv_timeout(Duration::from_secs(5))
            .unwrap_or_else(|error| panic!("waiting for {marker:?}: {error}"));
        if line.contains(marker) {
            break;
        }
    };
    wait_for("guide test barrier: direct-row");
    assert!(fs::read_dir(dir.path()).unwrap().count() > 1);
    assert!(!destination.exists());
    // The barrier holds this child before publication while its SIGINT handler runs.
    assert_eq!(
        unsafe { libc::kill(child.id() as libc::pid_t, libc::SIGINT) },
        0
    );
    wait_for("guide test interrupt received");
    child.stdin.take().unwrap().write_all(b"x").unwrap();

    let failed = child.wait_with_output().unwrap();
    reader.join().unwrap();
    let diagnostic = receive.into_iter().collect::<Vec<_>>().join("\n");
    assert_eq!(failed.status.code(), Some(1), "{diagnostic}");
    assert!(diagnostic.contains("before publication"), "{diagnostic}");
    assert!(diagnostic.contains("job cancelled"), "{diagnostic}");
    assert!(failed.stdout.is_empty());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 1);
    assert!(!destination.exists());
}
