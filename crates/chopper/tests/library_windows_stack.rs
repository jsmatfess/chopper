#![cfg(windows)]

use chopper::job::{Column, Job, JobSettings, Limits, Operation, Pipeline, Resources, Shuffle};
use std::{fs, thread};

#[test]
fn embedded_run_publishes_from_a_one_mib_host_stack() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let input = directory.path().join("input.csv");
    let output = directory.path().join("output");
    let note = "café \"\"hello\"\"\r\nworld";
    fs::write(
        &input,
        format!("id,country,note\r\n1,CA,\"{note}\"\r\n2,US,\"{note}\"\r\n3,CA,\"{note}\"\r\n4,US,\"{note}\"\r\n"),
    )?;
    let pipeline = Pipeline::new()
        .then(Operation::partition(vec![Column::Name("country".into())]))
        .then(Operation::shuffle(Shuffle::Uniform));
    let cap = 64;
    let job = Job::new(JobSettings {
        input: input.to_str().unwrap().into(),
        output: output.to_str().unwrap().into(),
        operations: pipeline.into_operations(),
        limits: Limits {
            bytes: Some(cap),
            ..Limits::default()
        },
        resources: Resources {
            memory_mb: 32.into(),
            max_record_bytes: 64 * 1024,
            workers: 1,
            temp_dir: Some(directory.path().to_str().unwrap().into()),
            ..Resources::default()
        },
        ..JobSettings::default()
    });

    let result = thread::scope(|scope| {
        let host = thread::Builder::new()
            .stack_size(1024 * 1024)
            .spawn_scoped(scope, || job.run())?;
        Ok::<_, std::io::Error>(host.join().expect("embedded host thread panicked"))
    })?;
    let report = result?;
    assert_eq!((report.rows, report.groups, report.output_files), (4, 2, 4));
    assert_eq!(report.manifest_path, output.join("manifest.jsonl"));
    assert!(report.manifest_path.is_file());
    let mut files = 0;
    for entry in fs::read_dir(&output)? {
        let path = entry?.path();
        if path.extension().is_some_and(|extension| extension == "csv") {
            let csv = fs::read_to_string(path)?;
            assert!(csv.len() as u64 <= cap);
            assert!(csv.contains(note));
            files += 1;
        }
    }
    assert_eq!(files, report.output_files);
    Ok(())
}
