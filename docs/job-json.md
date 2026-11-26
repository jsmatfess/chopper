# Saved Job JSON

A saved Job describes the input, output, ordered operations and limits that
Chopper should use. These fields describe Chopper **0.6.2**. The release number
selects the editor schema, while the Job's own `version` field selects the
configuration format, currently `1`.

## Editor setup

Check the installed version with `chopper --version`. For 0.6.2, use the
[release-pinned Job schema](https://raw.githubusercontent.com/jsmatfess/chopper/v0.6.2/schemas/0.6.2/job.schema.json).
Both native archives include the same `job.schema.json` at their root.
For offline use, use the included copy, save the download, or copy it from the
[matching source checkout](../schemas/0.6.2/job.schema.json).

To associate the schema in VS Code, open the repository folder and add this
entry to its `.vscode/settings.json`. Change `fileMatch` for your own Job files.
If the schema is at the workspace root, set `url` to
`"./job.schema.json"`. See the
[VS Code schema association documentation](https://code.visualstudio.com/docs/languages/json#json-schemas-and-settings).

```json
{
  "json.schemas": [
    {
      "fileMatch": ["/examples/job.json"],
      "url": "https://raw.githubusercontent.com/jsmatfess/chopper/v0.6.2/schemas/0.6.2/job.schema.json"
    }
  ]
}
```

Keep the association in editor settings. Chopper rejects unrecognized fields at
all levels, including an inline `$schema`, old seed fields and fields belonging
to a different operation. Existing binaries can read the same Job if its field
values and operations are supported by that release.

Open [the sample Job](../examples/job.json) for completions and run it from the
repository root using the [sample CSV](../examples/customers.csv).

```sh
chopper analyze --config examples/job.json
chopper run --config examples/job.json --yes
```

The Run writes a new `chopped-customers` directory. Set a fresh `output` before
running again.

## Job fields

All top-level fields can be omitted when decoding. Chopper requires an input
path for processing and a new output directory for Run. Omitted settings use
their defaults. Only fields that list `null` also accept an explicit JSON null.
Numeric fields use whole-number JSON syntax, such as `256`.

| Field | Default | Accepted values and meaning |
| --- | --- | --- |
| `version` | `1` | Job format. The supported version is `1`. |
| `input` | Empty string | CSV, gzip or ZIP path, for example `"examples/customers.csv"`. |
| `output` | Empty string | New output directory, for example `"chopped-customers"`. |
| `zip_member` | `null` | Exact member name within a ZIP, or `null` to select the sole member with a case-insensitive `.csv` extension. |
| `input_csv`, `output_csv` | Each uses the CSV defaults below | Independent CSV settings objects. |
| `compression` | `"none"` | `"none"`, `"gzip"` or `"zip"` for output. |
| `calculated_columns` | `[]` | Up to 64 named row formulas, in output column order. |
| `operations` | `[]` | List of operation objects in execution order, applied within each current group. |
| `limits` | Each cap is unset | Final physical file limits object. |
| `resources` | Each resource uses the default below | Execution resources object. |
| `full_shuffle_rng` | `"blake3_counter_v1"` | The only accepted full-shuffle random source. Usually omitted. |
| `full_shuffle_algorithm` | `"adaptive_v1"` | The only accepted full-shuffle algorithm version. Usually omitted. |

## CSV settings

| Field | Default | Accepted values and meaning |
| --- | --- | --- |
| `encoding` | `"utf-8"` | UTF-8, UTF-16LE, UTF-16BE, Windows-1250 through Windows-1258, Shift_JIS, GBK, Big5, EUC-KR and ISO-8859-2. Chopper also accepts recognized labels that resolve to those encodings. |
| `headers` | `true` | Boolean. Read a header from input or write the input header to output. For headerless files, set both to `false`. |
| `delimiter` | `","` | One ASCII character, for example `"\t"` for tab. |
| `quote` | `"\""` | One ASCII character, distinct from the delimiter. |
| `escape` | `null` | One ASCII character distinct from the delimiter and quote, or `null` for doubled quotes. |
| `line_ending` | `"lf"` | `"lf"` or `"crlf"`. Controls serialized output line endings. |
| `bom` | `false` | Boolean. Output can emit the encoding's BOM for UTF-8 or UTF-16. Input decoding handles its BOM. |
| `skip_empty_lines` | `false` | Boolean. Set to `true` to ignore bare blank input records. |

Chopper rejects NUL, CR and LF as delimiter, quote or escape characters.

## Operations

Each operation requires a `type`. The following objects can go inside
`operations`. A field shown in an example is required unless listed as optional.

| Type | Example | Behavior and optional fields |
| --- | --- | --- |
| `balanced` | `{"type":"balanced","files":4}` | Split into four consecutive balanced parts within each group. `files` must be positive, at most `max_files`, and feasible for the group's row count. |
| `interleaved` | `{"type":"interleaved","files":4}` | Split into four balanced parts using round-robin membership. The same file count rules apply. |
| `partition` | `{"type":"partition","columns":["country",0]}` | Group by distinct tuples of values. Supply at least one column. |
| `assign` | `{"type":"assign","groups":[{"name":"control","percent":"20"},{"name":"treatment","percent":"80"}]}` | Allocate exact quotas. Optional `strata` is a column list and defaults to `[]`. |
| `assign_probabilistic` | `{"type":"assign_probabilistic","groups":[{"name":"control","percent":"20"},{"name":"treatment","percent":"80"}],"strata":["country"]}` | Draw assignments independently, so group counts can vary. Optional `strata` defaults to `[]`. |
| `shuffle` | `{"type":"shuffle","strategy":"auto"}` | Fully permute the records in each group. Optional `strategy` defaults to `"uniform"`. `"auto"` selects a physical implementation. `"fisher_yates"` requires the rows to fit in resident memory. |

In `columns` and `strata`, the JSON number `0` selects the first column.
The JSON string `"0"` selects the header whose exact text is `0`. Header names
are case-sensitive and must resolve to a unique column. Use an index for
headerless input or an ambiguous header. A column index and other sizes modeled
as unsigned 64-bit integers in the schema may have a narrower bound on a
32-bit runtime for fields backed by an index or platform-sized count.

Each allocation needs 1 to 1,024 groups with nonempty, unique names. Each
`percent` is a JSON string with an unsigned decimal percentage, such as
`"12.5"`, with up to six fractional digits and no percent sign. Weights must
sum exactly to 100.

## Formulas

The top-level `calculated_columns` array defines the formulas for `sales.csv` in this example.

```json
{
  "input": "sales.csv",
  "output": "by-region",
  "calculated_columns": [
    {"name": "region", "expression": "UPPER(TRIM([Sales Region]))"}
  ],
  "operations": [{"type": "partition", "columns": ["region"]}]
}
```

Formulas can reference any calculated column regardless of declaration order.
Cycles fail when binding the job to input. Output columns follow declaration
order. The planner evaluates the formulas before the first step that needs a
calculated field, or during output preparation when only export needs them.

Use **Calculated Columns** in the hosted editor or the guided CLI. For flag-built
jobs, repeat `--calculated-column 'name=formula'` for each definition.
See [Formula functions](formula-functions.md) for column references, operators,
and the complete function reference.

## Limits and resources

All `limits` fields default to `null`, which leaves that cap unset.
Set a cap using a positive JSON integer.

| Field | Unit and meaning |
| --- | --- |
| `limits.rows` | Data records per file, excluding the header. |
| `limits.bytes` | Serialized uncompressed CSV bytes per file, including headers, encoding and any BOM. This cap is strict. |
| `limits.compressed_bytes` | Advisory compressed bytes per file. Requires `"gzip"` or `"zip"`. The actual compressed size can exceed the target. |

| Field | Default | Accepted values and meaning |
| --- | --- | --- |
| `resources.memory_mb` | `"auto"` | Exact string `"auto"` or a whole JSON number in MiB from 32 to 1,048,576. The string `"256"` is invalid. This is a working allocation budget. |
| `resources.workers` | `0` | `0` for automatic selection. A positive count may be at most 64 and at most one per 8 MiB of effective memory. |
| `resources.temp_dir` | `null` | Directory path for temporary storage, or `null` for the system temporary location. |
| `resources.temp_bytes` | `null` | Positive byte count for temporary storage, or `null` for no configured cap. Available storage still applies. |
| `resources.max_files` | `100000` | Positive output file count limit. |
| `resources.max_record_bytes` | `8388608` | Positive record size limit in bytes, at most one sixteenth of effective memory. The default is 8 MiB. |
| `resources.grouping` | `"auto"` | `"auto"` or `"sort"`. Both preserve the same logical grouping. |

## Validation boundaries

The schema describes named-object Jobs. It diagnoses fields, operation shapes
and scalar types. The decoder also accepts certain positional arrays as an
artifact of Serde's struct decoding. Use the named fields shown here. JSON
Schema validates parsed values, while the decoder can reject duplicate keys,
whole-valued decimal or exponent spellings such as `256.0` or `256e0`, and
other lexical details. Native config files must fit within 1 MiB.

Chopper checks configuration rules such as the supported version, compatible
CSV settings, exact allocation totals, at most 64 operations, compression
requirements and valid resource or cap combinations. When it reads input, it
also checks the file or selected ZIP member, CSV data and encoding, column
existence and ambiguity, and whether the pipeline and limits can fit the actual
records. Analyze can inspect an input and report feasibility. Run checks its
input and destination independently. See the [behavior specification](specification.md).

## Verify the release schema

The Linux native CI job checks the current binary against the tracked schema,
the sample Job, structural fixtures and decoded defaults. A release keeps its
schema under `schemas/<version>/job.schema.json` in the matching Git tag.
After publishing the tag, run these commands from the matching source checkout
with a release binary on your PATH. Use a Python virtual environment for the
validation dependency.

```sh
python3 -m pip install -r scripts/requirements-job-schema.txt
python3 scripts/test-job-schema.py "$(command -v chopper)" --published
```

The published check downloads the exact URL from the editor setup, compares the
bytes with the tracked schema, and validates the example using a local copy.
