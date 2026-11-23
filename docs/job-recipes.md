# Native Job recipes

Start in the extracted [native package](../README.md#native-quickstart) with
the executable and `quickstart/customers.csv` in their original locations. The
bundled CSV has 12 synthetic customer records. In Windows PowerShell, replace
`./chopper` with `.\chopper.exe` in each command. On Linux, make the executable
runnable with `chmod +x ./chopper` if needed.

Each command publishes plain CSVs and `manifest.jsonl` in its own destination.
Check the exit status, then read the `--summary` JSON on stdout for row, group
and file counts. Use the manifest to map each output file to its row count,
serialized size and group. For each rerun, use a fresh `--output` path. See
[Run modes and automation](run-cli.md) and the [manifest contract](native-manifest.md).

## Make upload-sized chunks

Set both the maximum data records and the maximum serialized CSV size per file.

```sh
./chopper run --input quickstart/customers.csv --output recipe-upload --rows 2 --bytes 85 --yes --summary
```

Expect one logical group with seven CSVs containing `1, 1, 2, 2, 2, 2, 2` data
records in input order. Each file is at most 85 bytes including its header,
quotes and line endings. Raise the cap if a single record and its header cannot
fit. For uploads, substitute the receiver's actual limit. `--compressed-bytes`
is an advisory target for gzip or ZIP and can be exceeded. Use `--bytes` to
enforce a strict limit on the serialized CSV before compression.

## Make exactly N files

Use a Balanced step to divide one CSV into a fixed number of consecutive files.

```sh
./chopper run --input quickstart/customers.csv --output recipe-balanced --step balanced --files 3 --yes --summary
```

Expect three CSVs of four data rows each, in input order. The input needs at
least as many data rows as requested files. If you also set a row or byte cap,
Run fails when the balanced files would exceed it.

## Partition by a business column

```sh
./chopper run --input quickstart/customers.csv --output recipe-country --step partition --by country --yes --summary
```

Expect one CSV per country with `DE` (3 records), `GB` (4), and `US` (5). The
manifest lists each exact country in `lineage[0].values`. Each CSV contains
only that country's records, in their original relative order.

## Allocate exact treatment and control groups

```sh
./chopper run --input quickstart/customers.csv --output recipe-experiment --step assign --groups treatment=75,control=25 --yes --summary
```

Expect one CSV with 9 treatment records and one with 3 control records. The
manifest lists the group name in `lineage[0].allocation`. Every input record
belongs to exactly one group. Assignment randomizes membership and keeps the
original relative order within each group. A rerun can pick different members.
Chopper has no user seed or cross-run replay guarantee for randomized membership
or shuffle order. Keep the published CSVs and manifest to preserve an allocation.

The package also includes `quickstart/job.json` for a saved-Job example. Use the
[Job JSON guide](job-json.md) to author or edit saved Jobs and the
[CLI reference](cli-reference.md) to see the available flags for this release.
