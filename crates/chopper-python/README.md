# Chopper for Python

Chopper processes file-to-file CSV Jobs with bounded working memory. The
`chopper-csv` wheel provides the `chopper_csv` import for standard CPython
3.11 and newer on Linux and Windows x86-64.

Install a published version with `python -m pip install chopper-csv`.

```python
from chopper_csv import Job, Pipeline, partition, shuffle

pipeline = Pipeline().then(partition(["country"])).then(shuffle())
job = Job({
    "input": "customers.csv",
    "output": "results",
    "limits": {"bytes": 25_000_000},
}, pipeline=pipeline)
job.validate()
print(job.analyze()["rows"])
print(job.run()["manifest_path"])
job.save("job.json")
```

The [library guide](https://github.com/jsmatfess/chopper/blob/main/docs/user/libraries.md)
includes sample input and runnable examples for pipeline reuse, replay,
configuration errors, and cancellation.

`Job.save` creates a new file. `Job.load("job.json")` reads a saved Job from
Chopper's CLI or another caller.
`Job(settings)` and the module's `validate`, `analyze`, and `run` functions also
accept Job dictionaries. The dictionary fields, including CSV settings, limits,
resources, and operations, follow the versioned [Job format](https://github.com/jsmatfess/chopper/blob/main/docs/job-json.md).
Relative paths resolve from the current working directory. Run requires a new
or empty destination directory and publishes it only after execution succeeds.
Byte limits apply to the serialized CSV, including the header and record endings.

`Pipeline.then` returns a new pipeline. It accepts a pipeline or an operation
from `partition`, `assign`, `assign_probabilistic`, `shuffle`, `balanced`, or
`interleaved`. Use a string such as `"0"` to select a header by name and an integer
such as `0` to select a column by position. The allocation helpers accept ordered
`{"name": ..., "percent": ...}` records and an optional `strata` sequence.

`validate` returns `None` on success. Analyze returns bounded statistics and
advisory estimates. Run reads the current input and returns `rows`, `columns`,
`groups`, `output_files`, `output_csv_bytes`, and `manifest_path`. Job and
execution failures raise `ChopperError` with a stable `code`, a readable message,
and `path`, `line`, and `column` when available.

Analyze and Run are synchronous. Pass a fresh `ExecutionControl()` to each
call to let another thread poll `control.progress()` for `phase`, `rows`, and
`temp_bytes`, or call `control.cancel()`. Progress is the latest engine event.
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
