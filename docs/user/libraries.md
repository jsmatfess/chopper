# Rust and Python libraries

<!-- chopper-docs:language-pages -->

Build a Job in your application, load one from the CLI, or save one for another
caller. Run Jobs synchronously with the native engine on Windows and Linux
x86-64 using the [versioned Job format](../job-json.md).

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

<!-- docs:rust -->

Use each Rust example as `src/main.rs` and run `cargo run`.

<!-- docs:end -->

<!-- docs:python -->

Run each Python example as a script.

<!-- docs:end -->

Use a fresh directory for the walkthrough, or change the output paths and saved
Job filenames when you repeat an example.

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
    let estimate = job.analyze()?;
    println!("{} input rows", estimate.rows());
    let result = job.run()?;
    println!("{}", result.manifest_path.display());
    job.save("job.json")?;
    Ok(())
}
```

`JobSettings::for_files` applies saved Job defaults, including automatic memory.
Set `resources` explicitly to choose a fixed budget.

## Python

Python wheels target standard CPython 3.11 or later. The Linux wheel targets
glibc 2.28 or later.

Once the wheel is published, install it with `python -m pip install chopper-csv`.
For a local build, follow the [wheel instructions](../../crates/chopper-python/README.md#build-and-check-a-local-wheel).

Partition by country, shuffle each country independently, and cap each CSV at
50 bytes. With the sample input, the Run writes four CSVs.

```python
from pathlib import Path

from chopper_csv import Job, Pipeline, partition, shuffle

pipeline = Pipeline().then(partition(["country"])).then(shuffle())
job = Job(
    {"input": Path("customers.csv"), "output": Path("results"), "limits": {"bytes": 50}},
    pipeline=pipeline,
)
job.validate()
print(f"{job.analyze().rows} input rows")
print(job.run().manifest_path)
job.save(Path("job.json"))
```

Use `Job(settings)` to construct a Job from a settings mapping. `validate`,
`analyze`, and `run` also accept settings mappings directly. `input`, `output`,
and `resources.temp_dir` accept strings and `os.PathLike[str]` objects.
Saved Jobs and `Job.to_dict()` use path strings. Execution releases the GIL,
so another Python thread can observe or cancel the Job. Engine errors raise
`ChopperError`.

`analyze()` returns an `AnalyzeReport`, and `run()` returns a `RunReport`.
Read their fields as attributes. The Run report's `.manifest_path` is a
`pathlib.Path`. Use `.to_dict()` for a JSON-ready copy, with the manifest
path as a string. `InputReport`, `DetectedDialect`, `Progress`,
`ManifestHeader`, and `ManifestOutput` also provide `.to_dict()`.

## Inspect an input

Use the input path and any [CSV settings](../job-json.md#csv-settings) you
already know. These methods also work with gzip and ZIP inputs. For a ZIP with
multiple CSV members, set `zip_member` to the exact member name. You can leave
the output path empty while deciding how to configure the Job.

| Method | What it reads | What it returns |
| --- | --- | --- |
| `detect_dialect` | Up to 64 KiB of decompressed input before text decoding | Suggested CSV settings, a delimiter status, a note, and the number of bytes sampled |
| `inspect` | The first parsed CSV record | Column count, optional header, and whether the input is ZIP |
| `preview` | The header, if configured, and up to eight data records | Column metadata and sampled rows with their record numbers |
| `analyze` | The full input | Bounded statistics and pipeline estimates for a configured Job |

<!-- docs:python -->

Python also exports `detect_dialect(settings)`, `inspect(settings)`, and
`preview(settings)` for use with a settings mapping.

<!-- docs:end -->

### Detect a dialect and list columns

Detection compares the configured delimiter and comma, tab, semicolon, and
pipe. It can recognize a supported encoding from a BOM and suggest an observed
line ending. When candidates tie or none fits, detection keeps the configured
delimiter.
Set header, quote, and escape behavior using what you know about the file.
Review the suggestion before applying it to a new Job's `input_csv`.

<!-- docs:rust -->

Read the recommendation with `DetectedDialect::settings()`. The
`delimiter_status()` method reports `Detected`, `Ambiguous`, or `NotDetected`.

<!-- docs:end -->

<!-- docs:python -->

`detect_dialect()` returns a `DetectedDialect`. Its `.settings` is a CSV
settings dictionary you can use as a Job's `input_csv`. The
`.delimiter_status` is `"detected"`, `"ambiguous"`, or `"not_detected"`.
Use `.sample_bytes` for the sample size and `.note` for a description of the
recommendation.

<!-- docs:end -->

Column positions are zero-based in parsed input order. Names reflect the
configured input parsing rules. Duplicate names keep their positions, so use
indices to distinguish them. With `headers` set to `false`, inspection gets
the width from the first data record, with no name for each column.

**Rust**

```rust
use chopper::job::{Error, Job, JobSettings};

fn main() -> Result<(), Error> {
    let input = Job::new(JobSettings::for_files("customers.csv", ""));
    let detected = input.detect_dialect()?;
    println!(
        "{:?} from {} bytes: {}",
        detected.delimiter_status(),
        detected.sample_bytes(),
        detected.note(),
    );

    let mut settings = input.settings().clone();
    settings.input_csv = detected.settings();
    let report = Job::new(settings).inspect()?;
    println!("{} columns", report.column_count());
    for column in report.columns() {
        println!("{}: {}", column.index, column.name.unwrap_or("(no header)"));
    }
    Ok(())
}
```

**Python**

```python
from chopper_csv import detect_dialect, inspect

source = {"input": "customers.csv"}
detected = detect_dialect(source)
print(f"{detected.delimiter_status} from {detected.sample_bytes} bytes")
print(detected.note)

report = inspect({**source, "input_csv": detected.settings})
print(f"{report.columns} columns")
for index, name in report.iter_columns():
    label = "(no header)" if name is None else name
    print(f"{index}: {label}")
```

<!-- docs:rust -->

The Rust `InputReport` exposes `column_count()`, `header()`, and
`input_is_zip()`. The `columns()` iterator borrows names from the report.

<!-- docs:end -->

<!-- docs:python -->

The `InputReport` exposes the count as `.columns`, the names or `None` as
`.header`, and the ZIP flag as `.input_is_zip`. `report.iter_columns()`
yields `(index, name)` pairs lazily. A preview report also has `.preview` with
sampled rows and `.preview_row_numbers` with their data record numbers.

<!-- docs:end -->

The sample reports `0: id`, `1: country`, and `2: segment`.

### Preview input rows

Preview retains up to 32 KiB of decoded field text across its sampled rows.
Large records can be omitted, so pair each returned row with its number.
Numbers start at one for the first data record after input filtering and
exclude the header. Preview rows contain text values.

**Rust**

```rust
use chopper::job::{Error, Job, JobSettings};

fn main() -> Result<(), Error> {
    let report = Job::new(JobSettings::for_files("customers.csv", "")).preview()?;
    for row in report.preview_rows() {
        let fields: Vec<_> = row.fields().collect();
        println!("{}: {fields:?}", row.number);
    }
    Ok(())
}
```

**Python**

```python
from chopper_csv import Job

report = Job({"input": "customers.csv"}).preview()
for number, row in zip(report.preview_row_numbers, report.preview, strict=True):
    print(f"{number}: {row}")
```

## Add calculated columns

Build expressions with `col`, named functions, and arithmetic operators.
`col("id")` selects the exact `id` header. CSV fields start as text, so use
`number` to convert them before doing arithmetic. The new columns are appended
in declaration order and can be used for partitioning or allocation strata.

**Rust**

```rust
use chopper::formula::{col, functions as f, lit};
use chopper::job::{Column, Error, Job, JobSettings, Operation};

fn main() -> Result<(), Error> {
    let by_country_label = Operation::partition(vec![Column::Name("country_label".into())]);
    let job = Job::new(JobSettings {
        calculated_columns: vec![
            f::upper(f::trim(col("country"))).alias("country_label"),
            (f::number(col("id")) * lit(2)).alias("double_id"),
        ],
        operations: vec![by_country_label],
        ..JobSettings::for_files("customers.csv", "calculated")
    });
    let report = job.run()?;
    println!("{} rows in {} groups", report.rows, report.groups);
    Ok(())
}
```

**Python**

```python
from chopper_csv import Job, Pipeline, col, functions as f, partition

job = Job(
    {"input": "customers.csv", "output": "calculated"},
    pipeline=Pipeline().then(partition(["country_label"])),
    calculated_columns={
        "country_label": f.upper(f.trim(col("country"))),
        "double_id": f.number(col("id")) * 2,
    },
)
report = job.run()
print(f"{report.rows} rows in {report.groups} groups")
```

With the sample input, the Run writes eight rows in two groups. `validate()`
checks formula syntax. Analyze and Run resolve column references against the
input.

<!-- docs:rust -->

Rust's `.alias(name)` produces a `CalculatedColumn` for
`JobSettings.calculated_columns`.

<!-- docs:end -->

<!-- docs:python -->

Python takes each column name from the `calculated_columns` mapping.

<!-- docs:end -->

### Use formulas with headerless CSVs

Save the eight data lines from the sample as `customers-no-header.csv`.
Turn off headers in the input and output CSV settings. `col(0)` selects the
first parsed field by position. `col("0")` selects a column with the exact
header `0`. Use positions for headerless input or duplicate headers.

**Rust**

```rust
use chopper::formula::{col, functions as f, lit};
use chopper::job::{CsvSettings, Error, Job, JobSettings};

fn main() -> Result<(), Error> {
    let csv = CsvSettings {
        headers: false,
        ..CsvSettings::default()
    };
    let job = Job::new(JobSettings {
        input_csv: csv.clone(),
        output_csv: csv,
        calculated_columns: vec![(f::number(col(0)) * lit(2)).alias("double_id")],
        ..JobSettings::for_files("customers-no-header.csv", "calculated-headerless")
    });
    println!("{} rows", job.run()?.rows);
    Ok(())
}
```

**Python**

```python
from chopper_csv import Job, col, functions as f

job = Job(
    {
        "input": "customers-no-header.csv",
        "output": "calculated-headerless",
        "input_csv": {"headers": False},
        "output_csv": {"headers": False},
    },
    calculated_columns={"double_id": f.number(col(0)) * 2},
)
print(f"{job.run().rows} rows")
```

`double_id` names the calculation inside the Job so other formulas and pipeline
steps can refer to it. The output CSV has no header. Its first record is
`1,US,new,2`, with the calculated value in the fourth field.

### Pass function arguments

Use `col` to refer to a field and `lit("US")` to build a text literal. Fixed
function arguments also accept strings, numbers, and booleans directly.

<!-- docs:rust -->

In Rust, pass `None` to use the function default for an optional parameter or
`Some(expr)` to supply a value. Use `null()` for an explicit formula `NULL`
in a required slot and `Some(null())` in an optional slot.
Enable case-insensitive matching with
`f::startswith(col("country"), lit("u"), Some(lit(true)))`.

For variable-length arguments, pass an array or iterator, as in
`f::concat([col("country"), lit("-"), col("segment")])`. For `IFS`, pass
condition-value pairs and a fallback with
`f::ifs([(condition, value)], fallback)`.

See the [Rust syntax notes](../formula-functions.md?lang=rust#rust-syntax) in
the formula reference.

<!-- docs:end -->

<!-- docs:python -->

In Python, omit an optional parameter to use the function default or pass
`None` for an explicit formula `NULL`. Enable case-insensitive matching with
`f.startswith(col("country"), "u", True)`.

For variable-length arguments, pass each value in order, as in
`f.concat(col("country"), "-", col("segment"))`. For `IFS`, pass
condition-value pairs and a named fallback with
`f.ifs((condition, value), fallback=fallback)`.

See the [Python syntax notes](../formula-functions.md?lang=python#python-syntax)
in the formula reference.

<!-- docs:end -->

`CONCAT_WS` takes literal Boolean flags after its text arguments. For `IF`,
call `if_else(condition, when_true, when_false)`. The
[formula reference](../formula-functions.md) describes how each function
handles nulls.

### Compare row values

Call `.equal()` or `.not_equal()` to compare values for equality, and use
`.lt()`, `.le()`, `.gt()`, or `.ge()` to order them. These methods build
conditions you can combine or pass to `if_else`. Use `==` and `!=` to
compare the formula text of two expression objects.

<!-- docs:rust -->

Convert the CSV text to a number and test whether it is odd with
`(f::number(col("id")) % 2).not_equal(0)`. The `%` operator takes an expression on
the left. Use `lit` when the left operand is a number literal.

<!-- docs:end -->

<!-- docs:python -->

Convert the CSV text to a number and test whether it is odd with
`(f.number(col("id")) % 2).not_equal(0)`. The `%` operator also accepts an
expression on the right, as in `100 % f.number(col("id"))`.

<!-- docs:end -->

Use `col(0)` in place of `col("id")` to refer to the first field by position.

### Compose Boolean formulas

Review customers who are in the US or in the returning segment. Customer `3`
has already been reviewed, so skip that row. Apply the exclusion after combining
the country and segment conditions. `if_else` turns the result into a
`review_status` column.

<!-- docs:rust -->

Use `.or()` or `|` for OR, `.and()` or `&` for AND, and `.not()` or `!` for
NOT. The method chain below is equivalent to
`(is_us | is_returning) & !already_reviewed`.

<!-- docs:end -->

**Rust**

```rust
use chopper::formula::{col, functions as f};
use chopper::job::{Error, Job, JobSettings};

fn main() -> Result<(), Error> {
    let is_us = col("country").equal("US");
    let is_returning = col("segment").equal("returning");
    let already_reviewed = f::number(col("id")).equal(3);
    let needs_review = is_us.or(is_returning).and(already_reviewed.not());

    let job = Job::new(JobSettings {
        calculated_columns: vec![f::if_else(needs_review, "review", "skip").alias("review_status")],
        ..JobSettings::for_files("customers.csv", "customer-review")
    });
    println!("{}", job.run()?.manifest_path.display());
    Ok(())
}
```

<!-- docs:python -->

Use `.or_()` or `|` for OR, `.and_()` or `&` for AND, and `.not_()` or `~` for
NOT. The method chain below is equivalent to
`(is_us | is_returning) & ~already_reviewed`. The method names end in `_`
because `or`, `and`, and `not` are Python keywords. A Python truth test on a
formula expression raises `TypeError`.

<!-- docs:end -->

**Python**

```python
from chopper_csv import Job, col, functions as f

is_us = col("country").equal("US")
is_returning = col("segment").equal("returning")
already_reviewed = f.number(col("id")).equal(3)
needs_review = is_us.or_(is_returning).and_(already_reviewed.not_())

job = Job(
    {"input": "customers.csv", "output": "customer-review"},
    calculated_columns={"review_status": f.if_else(needs_review, "review", "skip")},
)
print(job.run().manifest_path)
```

The output CSV starts with these records.

```csv
id,country,segment,review_status
1,US,new,review
2,GB,returning,review
3,US,returning,skip
4,GB,new,skip
```

### Reuse existing formula text

<!-- docs:rust -->

Parse a formula with `"NUMBER([id])".parse::<Expr>()?` or call
`chopper::formula::parse("NUMBER([id])")?`. Combine the resulting expression
with other expressions and literals. `Expr::as_str()` borrows its formula
text. Invalid formulas return `FormulaError`.

You can also put formula text directly in the `expression` field of a
`CalculatedColumn`.

<!-- docs:end -->

<!-- docs:python -->

Import `parse` from `chopper_csv` to incorporate a formula into an
expression, as in `parse("NUMBER([id])") * 2`. `str(expr)` reads the
resulting formula text. Invalid formulas raise `ValueError`.

The `calculated_columns` keyword accepts formula strings as values. You can
also pass `{"name": ..., "expression": ...}` records in the settings
dictionary's `calculated_columns` list.

<!-- docs:end -->

Saving a Job writes the formulas to the same
[Job JSON](../job-json.md#formulas) that the CLI accepts.

### Offer formula suggestions

Use `formula_functions()` to populate an editor with pairs of function names
and call signatures. The [formula reference](../formula-functions.md) explains
function behavior and shows how to refer to input columns.

**Rust**

```rust
use chopper::job::formula_functions;

fn main() {
    for (name, signature) in formula_functions() {
        println!("{name}: {signature}");
    }
}
```

**Python**

```python
from chopper_csv import formula_functions

for name, signature in formula_functions():
    print(f"{name}: {signature}")
```

## Compose, inspect, and replay

`then` returns a new Pipeline and accepts one operation or an entire Pipeline.
Each operation applies to each group produced by the preceding operation.
Available operations include `partition`, `assign`, `assign_probabilistic`,
`shuffle`, `balanced`, and `interleaved`.

<!-- docs:rust -->

Build steps with `Operation`. Use `Column::Name("0".into())` to select the
exact header `0` and `Column::Index(0)` to select the first column.

<!-- docs:end -->

<!-- docs:python -->

Import step constructors from `chopper_csv`. Use a string such as `"0"` to
select that exact header and an integer such as `0` to select a zero-based
column position.

<!-- docs:end -->

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
        let report = job.run()?;
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
    print(f"{output}: {report.output_files} files")
```

### Reload a Job with a new destination

Use `job.json` from the quickstart. Copy its settings and change
`output` to replay the recipe in a new directory. Change `input` as well to
apply the same recipe to another CSV.

**Rust**

```rust
use chopper::job::{Error, Job};

fn main() -> Result<(), Error> {
    let saved = Job::load("job.json")?;
    let mut settings = saved.settings().clone();
    settings.output = "results-replay".into();
    let report = Job::new(settings).run()?;
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
print(f"{report.output_files} files from {report.rows} rows")
print(f"Read {report.manifest_path}")
```

<!-- docs:rust -->

`Job::load` reads a saved Job. Call `job.save(path)` to create a new Job
JSON file.

<!-- docs:end -->

<!-- docs:python -->

`Job.load(path)` reads a saved Job. Call `job.save(path)` to create a new Job
JSON file.

<!-- docs:end -->

For CLI replay, set a fresh `output` in a copy of the Job and run
`chopper run --config job-for-cli.json --yes`.
Relative paths resolve from the process's current working directory, even when
the Job file is in a subdirectory. Keep that directory stable while Jobs run.

Validate checks configuration without opening the input, destination or
temporary directory. Analyze reads the current input and returns bounded
statistics and advisory estimates. Run validates the input it reads and
publishes to a new or empty destination on success. The strict byte cap applies
to each serialized CSV, including its header, BOM and record terminators.
Run reports row, column, group, output-file and CSV-byte counts. Its
`manifest_path` points to the [native manifest](../native-manifest.md).
A relative destination gives a relative manifest path. Independent shuffled
Runs preserve the same grouping and cap guarantees with independently
generated order.

## Stream published output metadata

Run the quickstart to create `results/manifest.jsonl`, then read one output
record at a time. Use the same API for a manifest from a CLI Run. The reader
opens the manifest only. Output records contain the path, row and byte counts,
`compressed_target_exceeded` flag, and lineage. For a ZIP result, keep `path`
as the exact member name inside `outputs.zip`.

The default per-line limit is 16 MiB. Raise it for a manifest with a large Job
record, which can include configuration and analysis data. The limit counts each
line's bytes up to its LF terminator. Opening reads the Job record and returns
a reader with a header containing version, input header, compression, and
aggregate counts. Iterating to exhaustion reconciles the output count, row
count, and total CSV bytes with the header.

**Rust**

```rust
use chopper::job::{Error, ManifestReader};

fn main() -> Result<(), Error> {
    let manifest = ManifestReader::open("results/manifest.jsonl")?;
    println!("{} published CSVs", manifest.header().output_files);
    for output in manifest {
        let output = output?;
        println!(
            "{}: {} rows, {} CSV bytes",
            output.path, output.rows, output.csv_bytes
        );
    }
    Ok(())
}
```

<!-- docs:rust -->

Use `report.outputs()` to open the reader from a `RunReport`. Set a custom
limit with `ManifestReader::open_with_record_limit(path, bytes)` or
`report.outputs_with_record_limit(bytes)`. Each iteration item is a
`Result<ManifestOutput, Error>`.

<!-- docs:end -->

**Python**

```python
from chopper_csv import open_manifest

with open_manifest("results/manifest.jsonl") as manifest:
    print(f"{manifest.header.output_files} published CSVs")
    for output in manifest:
        print(f"{output.path}: {output.rows} rows, {output.csv_bytes} CSV bytes")
```

<!-- docs:python -->

Use `RunReport.outputs()` to open a Run's manifest directly, or
`open_manifest(path)` if you have the manifest path. Both accept a custom
`max_record_bytes` keyword. The reader exposes `.header` as a
`ManifestHeader` and yields `ManifestOutput` records. Each record's `.path`
is a string, which can name a member inside `outputs.zip`. Manifest failures
raise `ChopperError`. The context manager closes the file. You can also call
`manifest.close()` directly.

<!-- docs:end -->

Use the [native manifest verification example](../native-manifest.md#verify-a-result)
when you also need to check the published CSV payloads.

## Handle errors and control execution

Job errors have a code and a readable message. Configuration errors can also
include a JSON Pointer and one-based line and column coordinates.

<!-- docs:rust -->

Read these details on `chopper::job::Error` through `code()`, `path()`,
`line()`, and `column()`.

<!-- docs:end -->

<!-- docs:python -->

Catch `ChopperError` and read its `code`, `path`, `line`, and `column`
attributes.

<!-- docs:end -->

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
| `manifest_read` | Could not open or read the result manifest |
| `manifest_format` | Invalid manifest record, unsupported schema version, or inconsistent totals |
| `manifest_limit` | A record exceeds the byte limit, the limit is zero, or the reader could not allocate its buffer |

### Report a configuration error

This Job supplies a string for its byte limit. The example reports
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

Pass a fresh `ExecutionControl` to each Analyze or Run. `progress()` reports
the latest phase, rows processed in that phase, and temporary bytes sampled
with the event. A terminal snapshot reports zero bytes of active temporary
storage.

<!-- docs:rust -->

Share a cloned control with the observing thread. Use
`job.run_with_control(&control)` or `job.analyze_with_control(&control)` for
the operation. `progress()` returns a `Progress` snapshot.

<!-- docs:end -->

<!-- docs:python -->

Share the same control object with the observing thread and pass it as
`control=control`. `progress()` returns a `Progress` snapshot with `.phase`,
`.rows`, and `.temp_bytes`.

<!-- docs:end -->

Call `cancel()` to request cooperative cancellation. Before publication,
cancellation follows the native staging and temporary cleanup rules. A
committed Run remains successful when cancellation arrives late. Concurrent
Jobs need separate destinations and share the process-wide working memory
ledger.

The example runs the Job on a background thread, reads one progress snapshot,
and requests cancellation. The snapshot can show `Pending` while the worker
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
        let worker = scope.spawn(move || job.run_with_control(&worker_control));
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
    future = pool.submit(job.run, control=control)
    progress = control.progress()
    print(f"{progress.phase}: {progress.rows} rows")
    control.cancel()
    try:
        report = future.result()
    except ChopperError as error:
        if error.code != "cancelled":
            raise
        print(f"Cancelled: {error}")
    else:
        print(f"Published {report.manifest_path}")
```
