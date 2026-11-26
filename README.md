# Chopper

Chopper splits CSV files larger than memory using a native CLI for supported
64-bit Windows and Linux, or the [hosted browser app](https://chopper-1rx.pages.dev/).
Both use the Rust engine for ordered pipelines, strict validation, full random
shuffles and disk-backed processing. macOS source builds are unqualified and
not a supported release target. There is no native server or native UI.

- [Try in browser](https://chopper-1rx.pages.dev/) with desktop Chrome or Edge.
  Follow the [browser sample walkthrough](docs/browser.md#try-a-sample-export)
  to make and verify your first export.
- [Download the CLI for Windows or Linux](https://github.com/jsmatfess/chopper/releases/tag/v0.6.2).
  The [native quickstart](#native-quickstart) walks through verifying the ZIP
  and running the bundled sample.

The [user guide](docs/user/README.md) covers saved Jobs, recipes, and upgrades.

## Native quickstart

Download your platform ZIP and **SHA256SUMS** from the same
[Chopper 0.6.2 release](https://github.com/jsmatfess/chopper/releases/tag/v0.6.2).
Allow about five minutes to download and verify the bundled synthetic example.
Open a terminal in the download directory.

| Environment | Package and requirements |
| --- | --- |
| Windows x86-64 | `chopper-0.6.2-windows-x86_64.zip`. Use PowerShell. If Windows reports missing MSVC runtime DLLs, install or repair the [Microsoft Visual C++ v14 Redistributable for x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/). |
| Linux x86-64 | `chopper-0.6.2-linux-x86_64.zip`. Requires glibc 2.34 or later and shell tools including `unzip` and `sha256sum`. Check the host with `uname -m` and `getconf GNU_LIBC_VERSION`. |
| Hosted | [Desktop Chrome or Edge](docs/user/README.md#use-chopper-in-your-browser) with a secure, cross-origin-isolated page, File System Access, OPFS and Web Locks. Open the [hosted app](https://chopper-1rx.pages.dev/) directly. |
| Other native platforms | macOS is source-only and unqualified. Native release packages are x86-64. |

See [operator support](docs/operator-support.md) for runtime errors, memory and
disk guidance, and what to redact before sharing a report.

### Windows PowerShell

Verify the downloaded ZIP, then extract it into a fresh directory. Change
`$destination` if the directory already exists.

```powershell
$archive = 'chopper-0.6.2-windows-x86_64.zip'
$destination = 'chopper-0.6.2-windows-x86_64'
$pattern = '^([0-9a-f]{64})  ' + [regex]::Escape($archive) + '$'
$record = @(Get-Content -LiteralPath SHA256SUMS | Where-Object { $_ -match $pattern })
if ($record.Count -ne 1 -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $record[0].Substring(0, 64)) {
    throw 'Archive SHA-256 does not match SHA256SUMS'
}
if (Test-Path -LiteralPath $destination) { throw 'Choose a fresh extraction directory' }
Expand-Archive -LiteralPath $archive -DestinationPath $destination -ErrorAction Stop
Set-Location -LiteralPath $destination -ErrorAction Stop
.\chopper.exe --version
```

Confirm the version is `chopper 0.6.2`. From that same directory, run the Job
and inspect the CSVs and manifest.

```powershell
.\chopper.exe run --config quickstart/job.json --yes
if ($LASTEXITCODE -ne 0) { throw 'Quickstart Run failed' }
Get-ChildItem quickstart-output -Filter *.csv | Sort-Object Name | ForEach-Object {
    '{0} {1}' -f $_.Name, @(Import-Csv -LiteralPath $_.FullName).Count
}
Get-Content quickstart-output/manifest.jsonl
```

To rerun, save a copy of the supplied Job with a fresh output directory.

```powershell
(Get-Content -Raw quickstart/job.json).Replace('"quickstart-output"', '"quickstart-output-rerun"') |
    Set-Content -Encoding ascii quickstart/rerun-job.json
.\chopper.exe run --config quickstart/rerun-job.json --yes
```

### Linux shell

Verify the downloaded ZIP and extract it into a fresh directory. Change
`destination` if the directory already exists.

```sh
archive=chopper-0.6.2-linux-x86_64.zip
destination=chopper-0.6.2-linux-x86_64
awk -v file="$archive" '$2 == file' SHA256SUMS | sha256sum --check &&
  mkdir "$destination" &&
  unzip "$archive" -d "$destination" &&
  cd "$destination" &&
  chmod +x ./chopper &&
  ./chopper --version
```

Confirm the version is `chopper 0.6.2`. From that same directory, run the Job
and inspect the CSVs and manifest.

```sh
./chopper run --config quickstart/job.json --yes &&
  wc -l quickstart-output/part-*.csv &&
  cat quickstart-output/manifest.jsonl
```

`wc -l` includes each file's header. For these sample records it prints
`6`, `6` and `3` lines, plus a total.

To rerun, save a copy of the supplied Job with a fresh output directory.

```sh
sed 's/"quickstart-output"/"quickstart-output-rerun"/' quickstart/job.json > quickstart/rerun-job.json &&
  ./chopper run --config quickstart/rerun-job.json --yes
```

### Expected results

The three upload-ready CSV files keep the input order, with one header per file.

| File in `quickstart-output/` | Data rows |
| --- | ---: |
| `part-00000001.csv` | 5 |
| `part-00000002.csv` | 5 |
| `part-00000003.csv` | 2 |

`manifest.jsonl` contains one Job record and three output records with the
same filenames and row counts. Upload the CSVs and keep the
[manifest](docs/native-manifest.md) for verification. Use a different output
directory for each rerun. Chopper protects existing results.

### CLI and automation guides

Use `chopper --version` to match your executable to its release documentation.
Run `chopper --help` or `chopper help run` for help from the installed binary.
Use `./chopper` on Linux or `.\chopper.exe` in PowerShell from the extracted package.

- [CLI reference](docs/cli-reference.md) for commands and options in this release.
- [Saved Job format and schema](docs/job-json.md) for `--config`.
- [Formula functions](docs/formula-functions.md) for calculated columns.
- [Runnable recipes](docs/job-recipes.md) for upload chunks, country partitions and exact allocation.
- [Validate](docs/validate-cli.md), [Run automation](docs/run-cli.md#summary-json-for-automation) and
  [native manifests](docs/native-manifest.md) for exit status, structured reports and output verification.

![Chopper hosted workbench showing CSV configuration and execution views](docs/images/workbench.png)

## Build the CLI from source

Use Git and a stable Rust toolchain. Windows also
requires the Microsoft C++ Build Tools and Windows SDK. Keep vendor sources when
cloning. Native CLI builds need no Node installation and do not embed UI assets.

From the repository root:

```sh
cargo build --release --locked -p chopper
```

Run `target/release/chopper --help` on Linux or `target\release\chopper.exe --help`
in PowerShell. Optional repository-local toolchains and paired WSL/Windows
workflows are described in [Windows and WSL development](docs/windows-wsl-workflow.md).

## Try the sample

The repository includes a synthetic [12-row CSV](examples/customers.csv) and
[example job](examples/job.json). From the repository root, with `chopper` on
your PATH:

```sh
chopper run --config examples/job.json --yes
```

This partitions by country, allocates treatment/control groups, and writes
ZIP-compressed outputs and a manifest into a new `chopped-customers` directory.
Choose a new output directory in the JSON before running the example again;
Chopper protects existing destinations. You can also select the sample CSV in
the [hosted app](https://chopper-1rx.pages.dev/) to explore its columns.

## CLI examples

```sh
# Consecutive chunks, preserving input row order
chopper run --input input.csv --output results --rows 100000 --yes

# Shuffle, then split into ten balanced files
chopper run --input input.csv --output shuffled --step shuffle --step balanced --files 10 --yes

# Partition by country and allocate treatment/control
chopper run --input input.csv --output experiment --step partition --by country --step assign --groups treatment=80,control=20 --yes

# Analyze input statistics and pipeline estimates without producing output
chopper analyze --config examples/job.json
```

`run --step` preserves operation order. To update a script that calls
`chopper split`, follow the [migration guide](docs/compatibility.md#replace-split-with-run-in-05).
Use `--yes` to skip confirmation in automation. Run
validates the input and publishes atomically to a new or empty directory. It
prints the final Analysis JSON to stdout by default and sends progress and errors
to stderr. See the [Run CLI guide](docs/run-cli.md) and
[behavior specification](docs/specification.md) for the full contract.

## Build the hosted app

Hosted builds require Node.js 22+ and Rust with `wasm32-wasip1`. Follow [browser setup](docs/browser.md#local-development)
for Windows/Linux prerequisites and commands. Build the WASI engine first, then
the hosted UI; `npm run build` in `ui/` aliases the hosted build. The local
static development server is `npm run serve:hosted`. Hosted output is `ui/dist`.
The browser uses local file APIs and OPFS for input and working data, then
exports results with a completion marker; see [browser limits](docs/browser.md).

For development, validation, and release work, see the
[maintainer guide](docs/maintainer/README.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Feedback and support

Chopper is independently maintained. Report bugs and suggest improvements in
[GitHub Issues](https://github.com/jsmatfess/chopper/issues); replies depend on
maintainer availability. Share a small synthetic reproduction rather than real
customer data, private paths or unredacted logs. For security concerns, use the
[private reporting instructions](SECURITY.md).

If Chopper is useful to you, you can [buy me a coffee](https://buymeacoffee.com/tblflip).
