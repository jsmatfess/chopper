# Rust and Python libraries

Build a Job in your application, load one from the CLI, or save one for another
caller. Both libraries run the native engine synchronously and accept the
[versioned Job format](../job-json.md). They process files on Windows and Linux
x86-64. Python wheels target standard CPython 3.11 or later. The Linux wheel
targets glibc 2.28 or later.

## Sample input

Save this as `customers.csv` in your working directory.

```csv
id,country,segment
1,US,new
2,GB,returning
3,US,returning
4,GB,new
5,US,new
6,GB,new
7,US,returning
8,GB,returning
```

Use each Rust block as `src/main.rs` and run `cargo run`. Run each Python block
as a script. Use a fresh directory for each language's walkthrough, or change
the output paths and saved Job filenames when you repeat an example.

## Rust

Once version 0.7.0 is published, add `chopper-csv = "0.7"` to your dependencies.
The library target is `chopper`. During candidate testing, use the staged Cargo
packages described in the [maintainer guide](../maintainer/library-release.md).

Partition by country, shuffle each country independently, and cap each CSV at
50 bytes. With the sample input, the Run writes four CSVs.

```rust
use chopper::job::{Column, Job, JobSettings, Limits, Operation, Pipeline, Shuffle};

fn main() -> Result<(), chopper::job::Error> {
    let pipeline = Pipeline::new()
        .then(Operation::partition(vec![Column::Name("country".into())]))
        .then(Operation::shuffle(Shuffle::Uniform));
    let job = Job::new(JobSettings {
        operations: pipeline.into_operations(),
        limits: Limits {
            bytes: Some(50),
            ..Limits::default()
        },
        ..JobSettings::for_files("customers.csv", "results")
    });
    job.validate()?;
    let estimate = job.analyze(None)?;
    println!("{} input rows", estimate.rows());
    let result = job.run(None)?;
    println!("{}", result.manifest_path.display());
    job.save("job.json")?;
    Ok(())
}
```

`JobSettings::for_files` applies saved Job defaults, including automatic memory.
Set `resources` explicitly to choose a fixed budget.

## Python

Once the wheel is published, install it with `python -m pip install chopper-csv`.
For a local build, follow the [wheel instructions](../../crates/chopper-python/README.md#build-and-check-a-local-wheel).
This example runs the same country partition, shuffle, and byte cap.

```python
from chopper_csv import Job, Pipeline, partition, shuffle

pipeline = Pipeline().then(partition(["country"])).then(shuffle())
job = Job(
    {"input": "customers.csv", "output": "results", "limits": {"bytes": 50}},
    pipeline=pipeline,
)
job.validate()
print(f"{job.analyze()['rows']} input rows")
print(job.run()["manifest_path"])
job.save("job.json")
```

Use `Job(settings)` to construct a Job from a dictionary, or pass a dictionary
to `validate`, `analyze`, or `run`. Execution releases the GIL, so another
Python thread can observe or cancel the Job. Python failures raise `ChopperError`.

## Compose, inspect, and replay

`then` returns a new Pipeline and accepts one operation or an entire Pipeline.
Each operation applies to each group produced by the preceding operation.
Both interfaces supply `partition`, `assign`, `assign_probabilistic`, `shuffle`,
`balanced`, and `interleaved`. Use a string for an exact column name such as
`"0"` and an integer for a zero-based index such as `0`.

### Reuse a country partition

Derive four pipelines from the same country partition. The exact variant fills
50/50 quotas within each country. The probabilistic variant uses independent
draws, so its counts can vary. The balanced variant shuffles each country
before making two consecutive parts. The interleaved variant distributes each
country's rows between two parts in round-robin order.

**Rust**

```rust
use chopper::job::{Allocation, Column, Error, Job, JobSettings, Operation, Pipeline, Shuffle};

fn main() -> Result<(), Error> {
    let country = Pipeline::new().then(Operation::partition(vec![Column::Index(1)]));
    let groups = vec![
        Allocation {
            name: "control".into(),
            percent: "50".into(),
        },
        Allocation {
            name: "treatment".into(),
            percent: "50".into(),
        },
    ];
    let exact = Operation::assign(groups.clone(), vec![]);
    let probabilistic = Operation::assign_probabilistic(groups, vec![]);
    let shuffled_parts = Pipeline::new()
        .then(Operation::shuffle(Shuffle::Uniform))
        .then(Operation::balanced(2));
    let variants = [
        ("exact", country.then(exact)),
        ("probabilistic", country.then(probabilistic)),
        ("balanced", country.then(shuffled_parts)),
        ("interleaved", country.then(Operation::interleaved(2))),
    ];

    for (output, pipeline) in variants {
        let job = Job::new(JobSettings {
            operations: pipeline.into_operations(),
            ..JobSettings::for_files("customers.csv", output)
        });
        let report = job.run(None)?;
        println!("{output}: {} files", report.output_files);
    }
    Ok(())
}
```

**Python**

```python
from chopper_csv import (
    Job, Pipeline, assign, assign_probabilistic, balanced, interleaved, partition, shuffle,
)

country = Pipeline().then(partition([1]))
groups = [
    {"name": "control", "percent": "50"},
    {"name": "treatment", "percent": "50"},
]
shuffled_parts = Pipeline().then(shuffle()).then(balanced(2))
variants = (
    ("exact", country.then(assign(groups))),
    ("probabilistic", country.then(assign_probabilistic(groups))),
    ("balanced", country.then(shuffled_parts)),
    ("interleaved", country.then(interleaved(2))),
)

for output, pipeline in variants:
    job = Job({"input": "customers.csv", "output": output}, pipeline=pipeline)
    report = job.run()
    print(f"{output}: {report['output_files']} files")
```

### Reload a Job with a new destination

Use `job.json` from either first example. Copy its settings and change
`output` to replay the recipe in a new directory. Change `input` as well to
apply the same recipe to another CSV.

**Rust**

```rust
use chopper::job::{Error, Job};

fn main() -> Result<(), Error> {
    let saved = Job::load("job.json")?;
    let mut settings = saved.settings().clone();
    settings.output = "results-replay".into();
    let report = Job::new(settings).run(None)?;
    println!("{} files from {} rows", report.output_files, report.rows);
    println!("Read {}", report.manifest_path.display());
    Ok(())
}
```

**Python**

```python
from chopper_csv import Job, run

settings = Job.load("job.json").to_dict()
settings["output"] = "results-replay"
report = run(settings)
print(f"{report['output_files']} files from {report['rows']} rows")
print(f"Read {report['manifest_path']}")
```

`Job.load` reads a saved Job, and `Job.save` creates a new Job JSON file. For CLI
replay, set a fresh `output` in a copy of the Job and run
`chopper run --config job-for-cli.json --yes`.
Relative paths resolve from the process's current working directory, even when
the Job file is in a subdirectory. Keep that directory stable while Jobs run.

Validate checks configuration without opening the input, destination or
temporary directory. Analyze reads the current input and returns bounded
statistics and advisory estimates. Run validates the input it reads and
publishes to a new or empty destination on success. The strict byte cap applies
to each serialized CSV, including its header, BOM and record terminators.
Run returns row, column, group, output-file and CSV-byte counts and the path to
the [native manifest](../native-manifest.md). A relative destination gives a
relative manifest path. Independent shuffled Runs preserve the same grouping
and cap guarantees with independently generated order.

## Handle errors and control execution

Errors expose a `code` and a readable message. Configuration errors may also
include a JSON Pointer in `path` and one-based `line` and `column` coordinates.

| Code | Meaning |
| --- | --- |
| `config_read`, `config_write` | Could not read Job JSON, save it, or verify temporary-file cleanup |
| `json_syntax`, `json_schema` | Invalid JSON or a value outside the Job schema |
| `invalid_config` | A decoded setting fails configuration validation |
| `destination` | The output directory could not be reserved or committed |
| `record_limit` | Output could not satisfy the configured strict size or exact split limits |
| `resource_limit` | The execution's working memory could not be admitted |
| `cancelled` | Execution observed a cancellation request before completion |
| `control_in_use` | The control already belongs to an execution |
| `execution` | Another execution failure, described by the message |

### Report a configuration error

This Job supplies a string for its byte limit. Both examples report
`json_schema` and the field `/limits/bytes`. Use a JSON number for the limit.

**Rust**

```rust
use chopper::job::Job;

fn main() {
    let source = r#"{
        "input": "customers.csv",
        "output": "results-errors",
        "limits": {"bytes": "50"}
    }"#;
    if let Err(error) = Job::from_json(source).and_then(|job| job.validate()) {
        eprintln!("{}: {error}", error.code());
        if let Some(path) = error.path() {
            eprintln!("Field {path}");
        }
    }
}
```

**Python**

```python
from chopper_csv import ChopperError, validate

try:
    validate({"input": "customers.csv", "output": "results-errors", "limits": {"bytes": "50"}})
except ChopperError as error:
    print(f"{error.code}: {error}")
    if error.path is not None:
        print(f"Field {error.path}")
```

### Observe and cancel a Run

Pass a fresh `ExecutionControl` to each Analyze or Run. Share a cloned Rust
handle or the same Python object with the observing thread. `progress()` reports
the latest phase, rows processed in that phase, and temporary bytes sampled
with the event. A terminal snapshot reports zero bytes of active temporary
storage. Call `cancel()` to request cooperative cancellation. Before
publication, cancellation follows the native staging and temporary cleanup
rules. A committed Run remains successful when cancellation arrives late.
Concurrent Jobs need separate destinations and share the process-wide working
memory ledger.

The examples run the Job on a background thread, read one progress snapshot,
and request cancellation. The snapshot can show `Pending` while the worker
starts. A late request can still return a published manifest.

**Rust**

```rust
use chopper::job::{Error, ExecutionControl, Job, JobSettings};
use std::thread;

fn main() -> Result<(), Error> {
    let job = Job::new(JobSettings::for_files("customers.csv", "cancel-demo"));
    let control = ExecutionControl::new();
    let result = thread::scope(|scope| {
        let worker_control = control.clone();
        let worker = scope.spawn(move || job.run(Some(&worker_control)));
        let progress = control.progress();
        println!("{}: {} rows", progress.phase, progress.rows);
        control.cancel();
        worker.join().expect("Job worker panicked")
    });

    match result {
        Ok(report) => println!("Published {}", report.manifest_path.display()),
        Err(error) if error.code() == "cancelled" => println!("Cancelled: {error}"),
        Err(error) => return Err(error),
    }
    Ok(())
}
```

**Python**

```python
from concurrent.futures import ThreadPoolExecutor
from chopper_csv import ChopperError, ExecutionControl, Job

job = Job({"input": "customers.csv", "output": "cancel-demo"})
control = ExecutionControl()
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(job.run, control)
    progress = control.progress()
    print(f"{progress['phase']}: {progress['rows']} rows")
    control.cancel()
    try:
        report = future.result()
    except ChopperError as error:
        if error.code != "cancelled":
            raise
        print(f"Cancelled: {error}")
    else:
        print(f"Published {report['manifest_path']}")
```
