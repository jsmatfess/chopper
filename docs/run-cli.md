# Unified Run CLI

`chopper run` accepts either a JSON config or ordered flag-built operations:

```sh
chopper run --config job.json --yes
```

The forms are mutually exclusive. `--config` permits the `--memory-mb` and
`--workers` overrides and the `--analysis`, `--summary` and `--yes` options.
It rejects job-building flags before opening the config. Ordered Run flags
require the current source build: the published v0.1.0 Windows executable
supports only the JSON Run form. The separate
`pipeline` subcommand has been removed, with no alias. Existing `split` commands
retain their fixed partition → assign → shuffle → balanced/interleaved → limits order.

```sh
chopper run --input input.csv --output results \
  --step shuffle --strategy auto \
  --step partition --by country \
  --step assign --groups treatment=80,control=20 --strata segment \
  --memory-mb 256 --yes
```

Each `--step` appends an operation. Repeated operations remain separate, with the
same parent-group semantics as the JSON operations array. Step-specific options
belong to the preceding step, even when job-wide flags occur between them.
Wrong-scope options, duplicate scalar step settings and unknown options fail;
they never leak forward or change another step. Repeated global settings fail.
Defaults and semantic validation come from the existing Job types. Flag-built Run
constructs a caller-owned Job as `split` does; JSON Run retains its existing
admitted decoded owner through confirmation and execution. Flag construction
does not use or extend the
[scripted JSON decode-origin admission envelope](cli-job-decoding.md).

| Step | Step-specific options |
| --- | --- |
| `partition` | `--by country,segment`; literal repeated `--column NAME` / `--column-index N` |
| `assign` | `--groups treatment=80,control=20` or repeated `--group NAME=PERCENT`; optional strata |
| `assign_probabilistic` | Same allocation options; approximate independent draws |
| `shuffle` | `--strategy uniform`, `auto` or `fisher_yates`; omitted strategy is JSON's `uniform` default |
| `balanced` | `--files N` |
| `interleaved` | `--files N` |

Allocation strata use `--strata country,segment`, or repeated literal
`--stratum NAME` / `--stratum-index N`. All indices are zero-based. `--column 123`
means the column **named** `123`; `--column-index 123` means index 123. Repeated
literal selectors preserve their encounter order and can mix names and indices.
The comma shorthands split names; use literal selectors for names containing
commas. `--group` splits at the last `=` so names can contain commas and `=`.
Percentages remain strings and pass through the existing exact validation.

Job-wide flags may occur anywhere and do not start or end a step:

| Job fields | Flags |
| --- | --- |
| Paths / schema | Required `--input`, `--output`; optional `--zip-member`, `--job-version` (only 1 supported) |
| Output format / caps | `--compression none\|gzip\|zip`, `--rows`, `--bytes`, `--compressed-bytes` |
| Resources | `--memory-mb N\|auto`, `--workers`, `--grouping auto\|sort`, `--max-files`, `--max-record-bytes`, `--temp-dir`, `--temp-bytes` |
| Input CSV | `--input-encoding`, `--input-headers`, `--input-delimiter`, `--input-quote`, `--input-escape`, `--input-line-ending`, `--input-bom`, `--input-skip-empty-lines` |
| Output CSV | The same eight options with `--output-` prefix |
| Versioned shuffle contracts | `--full-shuffle-rng blake3_counter_v1`, `--full-shuffle-algorithm adaptive_v1` |

Boolean CSV options take `true` or `false`. Delimiter, quote and escape take
exactly one literal Unicode character; a tab must be passed as an actual tab,
not the two characters `\t`. Omitted escape is null (doubled-quote behavior).
Byte caps accept the existing byte-size syntax, such as `100MB` or `64MiB`.
`--max-record-bytes` takes an integer byte count. Omitted resources match Job
JSON defaults, including automatic memory and workers, an 8 MiB record size and no temporary-space cap;
there is no seed flag or public replay guarantee. Use `--help` for the full list.

Parsing and Job validation do not read the input. Execution uses the existing
confirmation path (`--yes` for noninteractive runs), engine dispatch, cancellation
and native atomic publication. The output path must be a new directory. CLI
ordering changes requested logical operations, not the rewrite eligibility rules.

Run includes an `auto_plan` in its default stdout report with the effective
memory and workers, publication route and strategy, peak writer slots and merge reader
fan-in, validated facts, and fallback counts. For an eligible uncapped native
Partition, Analyze can report `writer_estimate.suggested_max_files` using the
exact key count. A matching Run can include that recommendation in
`auto_plan.suggested_max_files`. It is a limit for this input and remains a
user setting. The large Linux file-sync rule can raise automatic working
memory when live headroom permits. See [native Auto paths](direct-execution.md#native-auto-paths)
for the workload bounds. To reuse compact advice from a completed Analyze:

```sh
chopper analyze --config job.json > input-analysis.json
chopper run --config job.json --analysis input-analysis.json --yes
```

`--analysis` also works with ordered flags. Run checks source and parser identity,
uses only applicable observations, and validates the current input normally.
Native Windows currently uses fresh Run facts because the existing profile
identity cannot reliably check rapid same-size edits on that runtime.
See [Auto planning](execution-decisions.md#3-current-auto-planning).

`chopper analyze --config job.json` scans input statistics and reports pipeline
estimates without building output files. It replaces the former exact-plan
Analyze behavior and the former `profile` command. Run always processes its own
submitted configuration and validates the input it consumes; no prepared-result
approval command remains. Run's normal path confirmation still precedes input
consumption (`--yes` for noninteractive use).

## Summary JSON for automation

Use `--summary` on Analyze, either form of Run, or Split to print a small
success report to stdout. The default detailed JSON remains available by
omitting the flag.

```sh
chopper analyze --config job.json --summary > analyze-summary.json
chopper run --config job.json --yes --summary > run-summary.json
```

Analyze reports `status: "analyzed"`, `rows` (data rows scanned) and `columns`
(input columns). Run and Split report `status: "published"`, `rows`, `columns`,
`groups` (final pipeline groups), `output_files` (CSV chunks, including members
inside ZIP output), and `output_csv_bytes` (total serialized CSV bytes before
compression, including any emitted headers). Automation should check the command's
exit status before consuming stdout.

The summary omits preview rows, headers, column and partition values, paths,
the job configuration, and diagnostic text. The flag applies only to the
successful stdout report. Prompts, progress and errors on stderr, command
arguments, output CSVs and full manifests can contain sensitive information.
Review them separately before sharing. Run and Split still publish the full
results and manifest through native atomic publication.

Keep the default Analyze JSON if you plan to use `run --analysis`. A summary has
no advisory observations, so passing one to `--analysis` has the same effect
on planning as omitting the advice file.

## Hosted command export and quoting

The hosted output plan generates an equivalent command, using `--flag=value`
arguments so values beginning with `-` remain values. Literal column/group flags
avoid lossy comma parsing. The tab-styled platform radio group offers Windows PowerShell 7.3+,
Linux Bash, and macOS zsh/Bash, using `.\chopper.exe` or `./chopper` and matching
JSON config paths. Its initial browser-platform suggestion can always be changed;
selection and Job values persist across edits without rewriting paths.

For **PowerShell 7.3+ with its default native argument handling**, single-quoted
strings double embedded `'`
and leave `$`, backticks and other shell syntax literal. Older Windows PowerShell
can alter embedded double quotes when passing native arguments; see
[Microsoft's argument-passing documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing?view=powershell-7.6#passing-arguments-that-contain-quote-characters).
Linux/macOS previews use POSIX single-quote escaping, including embedded
apostrophes, and quote backslashes so paths and values remain literal. The same
argument fixture is executed against a capture executable in a real POSIX shell;
this establishes quoting round trips, not native macOS engine qualification.

Browser file/folder names are not native absolute paths. Replace them with the
full input path and a new output directory path before running. Export always
reflects the current draft, including operation order and settings.

Large jobs remain better suited to `chopper run --config job.json`. The UI uses
that form above a conservative 24,000-character threshold, or for NUL-containing
values that native argv cannot carry; shell and OS argument
limits still apply. JSON export remains available for every job. Both forms
construct the same Job and execute through the same engine; randomized runs do
not promise identical row membership or order across separate executions.

## Verification

Downstream scripts can reconcile a completed native Job from its
[published manifest](native-manifest.md), even when the stdout report is unavailable.

Native parser tests cover every public Job field, repeated operations,
interleaved global flags, literal names versus indices, wrong scopes and errors.
A shared fixture in `crates/chopper/tests/fixtures/run-cli.json` is checked by
both the UI argument generator and the actual native clap parser. Real native
CLI tests compare partition/balanced orderings and their JSON equivalents, require
confirmation and check malformed-input cleanup. UI tests cover draft refresh,
clipboard success/denial/fallback and oversized-command JSON fallback. Coverage
is build/platform-specific; these checks do not establish native Windows
execution or PowerShell 7 argument-marshalling acceptance.
