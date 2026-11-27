use chopper::job::{Column, Job, JobSettings, Limits, Operation, Pipeline, Shuffle};
use std::{error::Error, fs, path::Path};

fn main() -> Result<(), Box<dyn Error>> {
    #[cfg(feature = "admission")]
    if std::env::args().nth(1).as_deref() == Some("admission") {
        let report = std::thread::Builder::new()
            .stack_size(8 * 1024 * 1024)
            .spawn(chopper::engine::run_resource_contracts)?
            .join()
            .expect("admission controls panicked")?;
        println!("{report}");
        return Ok(());
    }

    // This constructor requires a different backend on ordinary crates.io flate2.
    let _consumer_codec =
        flate2::Compress::new_with_window_bits(flate2::Compression::default(), false, 15);
    let consumer_json: serde_json::Value =
        serde_json::from_str(r#"{"z":184467440737095516160,"a":0.1}"#)?;
    assert_eq!(consumer_json["z"].to_string(), "184467440737095516160");
    assert_eq!(consumer_json.as_object().unwrap().keys().next().unwrap(), "z");
    let pipeline = Pipeline::default()
        .then(Operation::partition(vec![Column::Name("country".into())]))
        .then(Operation::shuffle(Shuffle::Uniform));
    let mut settings = JobSettings {
        zip_member: Some("nested/records.csv".into()),
        operations: pipeline.into_operations(),
        limits: Limits {
            bytes: Some(53),
            ..Limits::default()
        },
        ..JobSettings::for_files("input.zip", "rust")
    };
    settings.input_csv.encoding = "utf-16le".into();
    fs::create_dir("recipes")?;
    Job::new(settings.clone()).save("recipes/rust.json")?;
    let report = Job::load("recipes/rust.json")?.run(None)?;
    assert_eq!(
        (
            report.rows,
            report.columns,
            report.groups,
            report.output_files
        ),
        (4, 3, 2, 4)
    );
    assert_eq!(report.manifest_path, Path::new("rust/manifest.jsonl"));
    println!("{}", serde_json::to_string(&report)?);

    settings.output = "cli".into();
    Job::new(settings.clone()).save("recipes/cli.json")?;

    settings.input = "too-many-members.zip".into();
    settings.output = "denied".into();
    settings.resources.memory_mb = 32.into();
    settings.resources.max_record_bytes = 2 * 1024 * 1024;
    settings.resources.temp_dir = Some("temporary".into());
    fs::create_dir("temporary")?;
    let error = Job::new(settings)
        .run(None)
        .expect_err("ZIP metadata budget was not enforced");
    assert!(
        error
            .to_string()
            .contains("ZIP input directory exceeds metadata budget"),
        "{error}"
    );
    assert!(!Path::new("denied").exists());
    assert_eq!(fs::read_dir("temporary")?.count(), 0);
    Ok(())
}
