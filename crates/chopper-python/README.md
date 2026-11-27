# Chopper for Python

Chopper processes file-to-file CSV Jobs with bounded working memory. The
`chopper-csv` wheel provides the `chopper_csv` import for standard CPython
3.11 and newer on Linux and Windows x86-64.

Install a published version with `python -m pip install chopper-csv`.

```python
from pathlib import Path

from chopper_csv import Job, Pipeline, partition, shuffle

pipeline = Pipeline().then(partition(["country"])).then(shuffle())
job = Job({
    "input": Path("customers.csv"),
    "output": Path("results"),
    "limits": {"bytes": 25_000_000},
}, pipeline=pipeline)
job.validate()
print(job.analyze().rows)
print(job.run().manifest_path)
job.save(Path("job.json"))
```

The [library guide](https://github.com/jsmatfess/chopper/blob/main/docs/user/libraries.md)
includes sample input and runnable examples for input inspection, calculated
columns, pipeline reuse, replay, streaming manifests, and cancellation.

`Job.save` creates a new file. `Job.load("job.json")` reads a saved Job from
Chopper's CLI or another caller.
`Job(settings)` and the module's `validate`, `analyze`, and `run` functions also
accept settings mappings. The fields, including CSV settings, limits,
resources, calculated columns, and operations, follow the versioned [Job format](https://github.com/jsmatfess/chopper/blob/main/docs/job-json.md).
Use strings or `Path` objects for `input`, `output`, and `resources.temp_dir`.
Saved Jobs and `to_dict()` use path strings.
Relative paths resolve from the current working directory. Run requires a new
or empty destination directory and publishes it only after execution succeeds.
Byte limits apply to the serialized CSV, including the header and record endings.

`Pipeline.then` returns a new pipeline. It accepts a pipeline or an operation
from `partition`, `assign`, `assign_probabilistic`, `shuffle`, `balanced`, or
`interleaved`. Use a string such as `"0"` to select a header by name and an integer
such as `0` to select a column by position. The allocation helpers accept ordered
`{"name": ..., "percent": ...}` records and an optional `strata` sequence.

Build calculated columns with `col` and the named helpers in `chopper_csv.functions`.
Use `from chopper_csv import col, functions as f`, then pass
`calculated_columns={"country_label": f.upper(f.trim(col("country")))}` to
`Job`. Use `col(0)` for the first field
of a headerless CSV and `col("0")` for the exact header `0`. Compose Boolean
expressions with `&`, `|`, and `~`. The
[calculated column examples](https://github.com/jsmatfess/chopper/blob/main/docs/user/libraries.md#add-calculated-columns)
show both forms and how to reuse existing formula text with `parse`.

`validate` returns `None` on success. Analyze returns an `AnalyzeReport` with
bounded statistics and advisory estimates. Run reads the current input and
returns a `RunReport` with `.rows`, `.columns`, `.groups`, `.output_files`,
`.output_csv_bytes`, and `.manifest_path`. The manifest path is a
`pathlib.Path`. Use `.to_dict()` to get a JSON-ready report dictionary with
the path as a string. Job and execution failures raise `ChopperError` with a
stable `code`, a readable message, and `path`, `line`, and `column` when
available.

`Job.detect_dialect()` returns a `DetectedDialect` with a CSV settings
dictionary in `.settings`. `Job.inspect()` and `Job.preview()` return an
`InputReport` for column names and sampled input records. Use
`report.iter_columns()` to yield `(index, name)` pairs in input order. Use
`report.outputs()` on a `RunReport` or `open_manifest(path)` to iterate
through published output metadata. The reader exposes a `ManifestHeader` as
`.header` and yields `ManifestOutput` records. Each record's `.path` is a
string, which can name a ZIP member. These reports also provide `.to_dict()`.
`formula_functions()` returns the built-in function names and call signatures.

Analyze and Run are synchronous. Pass a fresh `ExecutionControl()` as the
`control` argument to let another thread poll `control.progress()` for a `Progress` report
with `.phase`, `.rows`, and `.temp_bytes`, or call `control.cancel()`.
`Progress.to_dict()` gives the same snapshot as a JSON-ready dictionary.
A Run cancelled before publication removes its temporary and staging data.
A cancellation received after publication preserves the successful result.

## Build and check a local wheel

From the repository root with Rust and the native build tools installed:

```sh
python -m pip install maturin==1.16.0
maturin build --release --locked --out scratch/python-wheels
cargo build --release --locked -p chopper-csv --bin chopper
python -m venv scratch/python-wheel-check
```

Use the fresh environment's Python to install the generated wheel with
`python -m pip install --no-deps /path/to/wheel.whl`, then run the installed
wheel checks:

```sh
python -I crates/chopper-python/tests/installed_wheel.py target/release/chopper
```

On Windows the executable is `target/release/chopper.exe`. Linux release
wheels use the glibc baseline documented for the release candidate.

To align the wheel's shared Rust dependencies after a workspace dependency
update, copy the root `Cargo.lock` to `crates/chopper-python/Cargo.lock`, then
run `cargo metadata --manifest-path crates/chopper-python/Cargo.toml` to
resolve the Python binding dependencies and review the resulting lockfile.

The wheel includes the Chopper license, the upstream notices for the patched
ZIP, flate2 and serde_json crates, and the MIT notice used by PyO3 0.30.1 and
its associated PyO3 crates.
