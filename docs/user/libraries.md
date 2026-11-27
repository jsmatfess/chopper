# Rust and Python libraries

Build a Job in your application, load one from the CLI, or save one for another
caller. Both libraries run the native engine synchronously and accept the
[versioned Job format](../job-json.md). They process files on Windows and Linux
x86-64. Python wheels target standard CPython 3.11 or later. The Linux wheel
targets glibc 2.28 or later.

## Rust

Once version 0.7.0 is published, add `chopper-csv = "0.7"` to your dependencies.
The library target is `chopper`. During candidate testing, use the staged Cargo
packages described in the [maintainer guide](../maintainer/library-release.md).

```rust
use chopper::job::{Column, Job, JobSettings, Limits, Operation, Pipeline, Resources, Shuffle};

fn main() -> Result<(), chopper::job::Error> {
    let pipeline = Pipeline::new()
        .then(Operation::partition(vec![Column::Name("country".into())]))
        .then(Operation::shuffle(Shuffle::Uniform));
    let job = Job::new(JobSettings {
        input: "customers.csv".into(),
        output: "results".into(),
        operations: pipeline.into_operations(),
        limits: Limits { bytes: Some(25_000_000), ..Limits::default() },
        resources: Resources::automatic(),
        ..JobSettings::default()
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

## Python

Once the wheel is published, install it with `python -m pip install chopper-csv`.
For a local build, follow the [wheel instructions](../../crates/chopper-python/README.md#build-and-check-a-local-wheel).

```python
from chopper_csv import Job, Pipeline, partition, shuffle

pipeline = Pipeline().then(partition(["country"])).then(shuffle())
job = Job({"input": "customers.csv", "output": "results",
           "limits": {"bytes": 25_000_000}}, pipeline=pipeline)
job.validate()
print(job.analyze()["rows"])
print(job.run()["manifest_path"])
job.save("job.json")
```

Use `Job(settings)` to load a dictionary or pass one to `validate`, `analyze`,
or `run`. Execution releases the GIL, so another Python thread can observe or
cancel the Job. Python failures raise `ChopperError`.

## Compose, inspect, and replay

`then` returns a new Pipeline and accepts one operation or an entire Pipeline.
Each operation applies to each group produced by the preceding operation.
Both interfaces supply `partition`, `assign`, `assign_probabilistic`, `shuffle`,
`balanced`, and `interleaved`. Use a string for an exact column name such as
`"0"` and an integer for a zero-based index such as `0`.

`Job.load` reads a saved Job, and `Job.save` creates a new Job JSON file. For CLI
replay, select a fresh `output` and run `chopper run --config job.json --yes`.
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
| `config_read`, `config_write` | Could not read or save Job JSON |
| `json_syntax`, `json_schema` | Invalid JSON or a value outside the Job schema |
| `invalid_config` | A decoded setting fails configuration validation |
| `destination` | The output directory could not be reserved or committed |
| `record_limit` | Output could not satisfy the configured strict size or exact split limits |
| `resource_limit` | The execution's working memory could not be admitted |
| `cancelled` | Execution observed a cancellation request before completion |
| `control_in_use` | The control already belongs to an execution |
| `execution` | Another execution failure, described by the message |

Pass a fresh `ExecutionControl` to each Analyze or Run. Share a cloned Rust
handle or the same Python object with the observing thread. `progress()` reports
the latest phase, rows processed in that phase, and temporary bytes sampled
with the event. Call `cancel()` to request cooperative cancellation. Before
publication, cancellation follows the native staging and temporary cleanup
rules. A committed Run remains successful when cancellation arrives late.
Concurrent Jobs need separate destinations and share the process-wide working
memory ledger.
