# Native CLI and Job compatibility

Before upgrading, keep a copy of saved Jobs and scripts and review the release
notes for every version you are crossing. If the candidate provides
[`validate-config`](validate-cli.md), use `chopper validate-config --config job.json`
to check the saved settings without opening the input. Run a representative
Job in a fresh destination before switching automation.

| Interface | What scripts can rely on |
| --- | --- |
| [Documented CLI commands and arguments](run-cli.md) | Existing invocations are expected to keep working across upgrades. Check the target release's `--help` for commands and flags introduced since your pinned version. Use the exit status and documented native result directory when integrating a Run. Human-readable diagnostics and progress text may change. |
| [Job JSON](job-json.md) | A Job with a supported `version` and supported settings is expected to work without edits. Only Job version 1 is supported today. The reader rejects unknown fields and unsupported settings, so Jobs written with newer settings may fail on older binaries. |
| [Versioned Job schemas](job-json.md#editor-setup) | When a release provides a JSON Schema, use the schema shipped or tagged with the exact binary and select the artifact matching the Job's `version`. Schema validation checks structure. The binary also validates Job semantics and Run checks the actual input. |
| [Documented native manifest fields](native-manifest.md#schema-version-1) | Use the fields documented for the manifest's `schema_version`. Readers should accept additional fields in known records, reject unsupported schema versions, and use `path` and `lineage` to identify outputs. Filenames, record order, planner diagnostics, randomized membership within quotas, and randomized row order can vary. |

The release version shown by `chopper --version` identifies the application.
Job `version` identifies the JSON configuration format. Manifest
`schema_version` independently identifies the native result format. A release
can add settings or intentionally remove a capability while those format
versions stay the same. Release notes identify intentional incompatibilities
and explain the replacement or conversion. Keep the original executable and
its release identity when continued use of a removed capability is required.

## Migrate Zstandard Jobs from 0.3 to 0.4 or later

**Output compression.** Change the saved Job setting
`"compression": "zstd"` to `"compression": "gzip"` for compressed individual
files, `"compression": "zip"` for a ZIP archive, or `"compression": "none"`
for plain CSVs. In flag-based scripts, replace `--compression zstd` with
`--compression gzip`, `--compression zip`, or `--compression none` as
appropriate. Use a fresh destination and update downstream readers for the
new container or file extension.

**Compressed input.** Decompress an existing Zstandard input with the
standalone `zstd` tool and point the Job at the decoded CSV. Use a new output
path to preserve the original compressed input.

```sh
zstd -d -o converted.csv -- legacy.csv.zst
```

Change `"input": "legacy.csv.zst"` to `"input": "converted.csv"`, or update
`--input` in a script. Keep the original CSV encoding and dialect settings.
Changing the filename extension alone leaves the Zstandard signature intact.

### Pin and verify 0.3.0

If the workflow still requires Zstandard support, obtain the matching native
ZIP from the [v0.3.0 release](https://github.com/jsmatfess/chopper/releases/tag/v0.3.0).
Before extraction, compute SHA-256 with `sha256sum <archive>` on Linux or
`Get-FileHash -Algorithm SHA256 <archive>` in PowerShell. Compare with the
published archive identities below and stop on a mismatch.

| Archive | SHA-256 |
| --- | --- |
| `chopper-0.3.0-linux-x86_64.zip` | `254c222d80ff33e053c10f04a2653c1974695f653a799dc52ec22434c23d0a11` |
| `chopper-0.3.0-windows-x86_64.zip` | `57f7276311bd461de8ab05a3d697e206c3b496d0c6a37ae5a395e422ffeee0f3` |

Extract into a version-specific directory alongside the new release. Invoke
the pinned executable by its full path and check that `--version` prints
`chopper 0.3.0`. Point pinned scripts at that path so a PATH update does not
change their executable.
