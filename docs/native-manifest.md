# Native result manifest

A completed native Job publishes its CSV outputs and manifest together by
committing the result directory. Read this directory even if the final stdout
report was lost. Use the configured destination, after publication, as your
starting point. A staging directory can contain a manifest before commit.
The native commit protects against partial publication during a failed or
cancelled Run. Files can still be changed or lost after commit, and directory
publication does not guarantee power-loss durability on every filesystem.
Hosted exports have a separate [completion protocol](browser.md#result-ownership-and-publication-contracts).

| Job compression | Published manifest | Where each output `path` points |
| --- | --- | --- |
| `none` | `manifest.jsonl` in the result directory | A plain CSV in the same directory |
| `gzip` | `manifest.jsonl` in the result directory | A gzip-compressed CSV in the same directory |
| `zip` | `manifest.jsonl` in the result directory and an identical `manifest.jsonl` member in `outputs.zip` | A CSV member inside `outputs.zip` |

## Schema version 1

The manifest is UTF-8 JSON Lines with one JSON object per line. The first line
is the single `job` record. Each following line is an `output` record for one
physical CSV chunk. A zero-output Job has only the job record. There is no
completion footer. Ignore additional fields in known records, require a schema
version your reader supports, and use `type` to identify each record.

### Job record

| Field | Meaning |
| --- | --- |
| `type` | String `"job"`. |
| `schema_version` | Integer `1`. This versions the manifest format. |
| `application_version` | String with the Chopper package version of the writer. Builds from different source revisions can share a package version. |
| `algorithm_version` | String identifying the engine algorithm version reported by the writer. Treat its value as opaque. It provides no guarantee of exact randomized replay across runs. |
| `config` | The Job configuration in effect for the run. `config.version` versions the Job JSON independently of the manifest. `config.compression` selects the layout above, and `config.output_csv` specifies the CSV dialect and encoding after decompression. Automatic settings may remain as requested in the configuration. |
| `analysis.rows` | Number of input data records processed, excluding the input header. It equals the sum of output `rows`. |
| `analysis.output_files` | Number of output records. A ZIP Job counts its CSV members individually. |
| `analysis.output_csv_bytes` | Sum of output `csv_bytes`. |
| `analysis.header` | Input header as an array of strings, or null if there is no header. A chunk includes a header when this is present and `config.output_csv.headers` is true. |

### Output record

| Field | Meaning |
| --- | --- |
| `type` | String `"output"`. |
| `path` | Exact filename relative to the result directory, or exact member name relative to the root of `outputs.zip`. Use the recorded name as provided. |
| `rows` | Number of data records in this chunk, excluding its header. A quoted field can span multiple physical lines. A chunk can have zero data records. |
| `csv_bytes` | Length in bytes of the serialized CSV, before any compression. Includes the bytes of the configured encoding, record terminators, and any BOM and header written to this chunk. This is the unit of the strict CSV byte cap. |
| `stored_bytes` | Length in bytes of the plain or gzip file. For ZIP, this is the compressed size of that CSV member's payload, excluding ZIP container overhead. The sum does not give the size of the complete ZIP archive. |
| `compressed_target_exceeded` | Boolean. True when an advisory compressed-byte target was configured and the output's `stored_bytes` exceeds it. This is compatible with a successful Job. |
| `lineage` | Array of group decisions in pipeline order. Each entry has an `operation` index into `config.operations` (zero-based) and a decision field. Partition entries have a `values` array of strings in selector order, allocation entries have an `allocation` group name, and balanced/interleaved entries have a one-based `part` number. Several capped chunks can share the same lineage. |

Counts and byte lengths are nonnegative integer JSON numbers. Use a reader
that preserves their full unsigned 64-bit range. Keep paths opaque and use
lineage to identify groups. Filename construction, output-record ordering
within the manifest, and JSON property order are implementation details.
Other Analysis fields, including planner diagnostics, execution routes, seed,
digest, timings, stage statistics and warnings, are outside this contract.

## Verify a result

From the repository root, with the [synthetic sample Job](../examples/job.json)
and a fresh destination:

```sh
chopper run --config examples/job.json --yes
python3 examples/verify_manifest.py chopped-customers
```

The [standard-library Python example](../examples/verify_manifest.py) accepts a
native result directory and checks plain, gzip and ZIP output. It checks the
directory inventory, compares both ZIP manifests, reads the CSV payloads,
and reconciles their logical record counts, serialized bytes and stored bytes
with the manifest. It prints JSON totals on success and exits nonzero on
failure. Keep other files such as redirected stdout outside the result
directory. The example supports `utf-8` output with doubled-quote escaping.
For other supported CSV settings, use a parser that implements the Job's
encoding and dialect.

File existence alone does not verify a result. Count and size checks detect
missing files, malformed manifests and many forms of damage. Different row
contents can still have identical counts and sizes. Where row identity or
authenticity matters, validate against trusted input or an independently
recorded checksum. Work from a trusted, quiescent result directory.

To test the example with a built binary, pass its path to
`python3 scripts/test-native-manifest.py`, for example
`python3 scripts/test-native-manifest.py target/debug/chopper`. On Windows,
use `python` and `target\debug\chopper.exe`.

## Share safely

Manifests can expose input, output and temporary-directory paths, input ZIP
member names, CSV column names, preview and summary values, and full partition
values and allocation labels. Output filenames can also contain portions of
group values. The ZIP itself contains a copy of the manifest alongside the
CSV data. For a support report, reproduce with synthetic data and paths.
If you share an excerpt from an existing result, review it for private paths
and data values first and keep the original manifest with its outputs.
