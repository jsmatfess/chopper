# Guided native CLI implementation specification

Status: slice A [#106](history/prior-issues.md#issue-106) is delivered and
included in the current [0.2 scope](releases/0.2.0.md).
[Validation entry points](guided-cli-validation.md) record the scoped Linux and
native Windows evidence and distinguish real terminal coverage from injected
transcripts. Slices B/C remain future work in
[#8](https://github.com/jsmatfess/chopper/issues/8) and
[#7](https://github.com/jsmatfess/chopper/issues/7); slice A does not complete
[the broader Guide task](https://github.com/jsmatfess/chopper/issues/13).

The owner selected a step-by-step wizard with back/edit/save/reload and the
existing engine with incremental proven improvements in
[#13's interaction decision](https://github.com/jsmatfess/chopper/issues/13)
and [#20's execution decision](https://github.com/jsmatfess/chopper/issues/20).
All of #81/#82/#83 need not close first. This document consumes those decisions;
it does not promote any experimental implementation.

[Product direction](product-direction.md) owns future scope;
[behavior](specification.md), [rewrites](pipeline-rewrites.md),
[direct execution](direct-execution.md) and [resource controls](specification.md#resources-publication-and-interfaces)
own current engine contracts. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active backlog and specs.
The sections below define the complete journey. Slice A implements only its
bounded subset; B/C behavior remains proposed and creates no validation claim.

## Entry point and interaction

Slice A adds explicit `chopper guide [--config PATH]`. Keep bare invocation's
help and existing `split`, `profile`, `analyze`, `run`, `example`, and `serve`
behavior. Do not automatically launch a browser, dialog or full-screen UI.

Require terminal stdin and stderr before loading a session or reading input.
Reject non-TTY invocation promptly with guidance to use
`chopper run --config PATH --yes`. The wizard has no `--yes` shortcut; a saved
job is the automation boundary. Redirected stdout is allowed: prompts, previews,
progress and the human completion summary go to stderr; stdout receives only the
existing streamed final Analysis JSON after a completed Run. Save-only and abort
emit no Analysis. Existing scripted commands retain their output contracts.

Use numbered choices and line input, without cursor positioning, mandatory ANSI
color, mouse interaction or alternate-screen mode. Show the step name, current
value and available commands at every prompt. Empty input keeps the current
value except at final Run confirmation, whose default is No. Use a separate value
prompt after selecting an action so paths or column names literally equal to
`back`, `save` or `cancel` remain enterable as data. Escape control characters in
all displayed source text, including paths, headers and values.

At navigation prompts provide Back, Edit step, Save, Reload, Help, and Cancel.
Back moves one step without losing accepted values; Edit jumps to a named step.
Reload replaces the draft only after explicit discard confirmation if dirty.
Invalid input stays at the prompt with an actionable error and the prior draft.
Cancel asks whether to save a dirty draft, then exits without starting work.
Ctrl+C and EOF never become a Yes, save, overwrite or discard confirmation.

## Journey and state

The complete journey is:

1. Start new or load a version-1 Job JSON.
2. Select input and parsing settings; optionally inspect input.
3. Compose and reorder operations; optionally explore selected column values.
4. Select output, final limits and packaging.
5. Review reproducibility and resources.
6. Review the complete job, optionally save, explicitly confirm Run.
7. Process through the existing engine, then inspect the completion summary and
   optionally save the effective job or return to editing.

Retain one draft Job, dirty state, current step, one session ProfileCache, and
bounded presentation state. Keep profile responses and their grants together;
drop superseded responses before requesting another profile. Do not persist
observations, entire transcripts, row spools or prepared output snapshots in the
draft. There is one active task (profile, picker or Run) at a time. Navigation
while a task runs is limited to cancellation; edit only after it stops and joins.

Any accepted edit clears final confirmation. Input/member/parser changes clear
observations and re-resolve column references. An input change must show existing
column bindings and require reconfirmation, rather than silently rebinding an
index to a different schema. Operation edits invalidate derived stage explanations;
output/cap changes may retain only observations the existing cache considers
compatible. Resource changes go through the cache's normal identity checks.
Every Run validates again; a profile is never an execution snapshot.

## Input, columns and bounded exploration

Always permit a typed local path. Show its absolute interpretation and current
working directory before accepting it. No glob expansion, shell evaluation,
recursive discovery or multiple-input concatenation. Input support remains the
engine's CSV/gzip/ZIP support. Detect container type through the engine,
not filename guesses. A multi-CSV ZIP needs an explicit member; show the engine's
error and allow editing the member name rather than adding an independent ZIP
reader. Reject unsupported/encrypted archives through existing validation.

Advanced input/output CSV prompts expose the current encoding list and supported
delimiter, quote, escape, headers, bare-blank-line policy, output line ending and
BOM. Defaults come from Job/CsvSettings. Offer Copy input settings to output as an
explicit action; retain later output overrides. Never silently repair malformed
CSV, normalize field values or infer numeric types.

The first slice uses **Inspect input (full scan)**, not a new quick-preview parser.
Explain before starting: reads and validates the entire selected source/member,
can decompress it fully, writes no output CSVs or temporary row spools, and is
cancellable. Inspection is optional; a user can configure known indices without
scanning. The returned small preview is a bounded selection of input rows, not a
random sample or a certificate about a later Run. There is no fast sampled scan
in these children.

Display bounds are independent of engine admission:

| Surface | Wizard display bound and meaning |
| --- | --- |
| Preview | At most the profile's 8 rows; show at most 8 columns per page |
| Column list | 20 columns per page, with next/previous and direct index lookup |
| Value list | 20 retained values per page; no collect-all action |
| Field/header/path display | At most 256 Unicode scalar values per rendered item, escaped; mark omitted text |
| Render/input buffers | Stream pages; cap each prompt response at 64 KiB UTF-8 and imported Job at the existing 1 MiB; reject oversize without accumulating the rest |

Presentation truncation never mutates stored values, selectors, paths or the
saved job. Full values may be used by selecting their index without printing
arbitrarily large text. Existing record, configuration and admission limits still
apply; a display bound is not a process RSS bound.

The profiler currently retains up to 64 selected columns, up to 100 values per
column under a shared 256 KiB value budget, and an admitted preview under its
32 KiB selection budget. Do not increase those limits. Each displayed statistic
must carry its coverage and accuracy:

- `rows`: exact for that completed full scan, not a prediction of a later source.
- `distinct_exact=true`: exact distinct count; call the values a complete set only
  when `truncated=false` and the displayed pages include all retained values.
- `distinct_exact=false`: approximate full-file HLL cardinality (currently about
  3.25% relative standard error, not a hard error bound). Retained values are
  examples, not all values, a frequency ranking or a representative sample.
- Preview rows: bounded examples; skipped wide rows can mean these are not the
  first eight records. Never extrapolate distinct counts from these rows.
- Unmeasured tuple counts, frequencies, skew, output count, disk need and time:
  unknown unless the current response provides them. Individual column counts
  cannot establish joint cardinality or post-operation group sizes.

Use a separate **Explore values for columns** action. The current profiler derives
selected columns/combinations from partition and allocation-strata operations;
it has no arbitrary-selection argument. For an exploration request, construct a
short-lived profile-only Job copy with one Partition over the requested column
indices and the same input/parser/resources. Never insert this operation into the
saved or executable draft. This copy asks for statistics only, never prepares or
runs outputs. Bound selection to 64 columns; paginate wider schemas. Test that
inspection cannot change the executable operation list.

Before each scan explain its reason: initial inspection; source/parser/resource
identity changed; requested column or tuple not retained; or native Windows needs
a rescan. Reuse only through ProfileCache and label actual cache hits after the
request. On Linux an already measured compatible selection may reuse observations;
on Windows even a repeated profile call rescans under the current contract.
A new tuple may need another full scan despite having its separate columns.
Do not promise persistent reuse, arbitrary exact enumeration, or an extra pass
shared with Run. Errors/cancellation discard incomplete observations.

Column menus show both the zero-based index used by JSON and escaped header text.
Store an explicitly chosen name as Column::Name and an index as Column::Index.
Duplicate names require index selection; headerless inputs require indices.
The text name `"0"` remains distinct from numeric index `0`. Names containing
commas are single names; do not route them through split's comma-delimited flags.
Engine resolution remains authoritative for missing, ambiguous or invalid columns.

## Ordered operations and final constraints

Append, edit, remove or move an operation to a numbered position, then show the
entire numbered pipeline. At most 64 operations, matching Job validation.
Explain that every step runs within each preceding logical group and that moving
a step changes membership, seed domains and possibly success. Require review of
the new order; never automatically reorder or delete requested steps.

| Menu operation | Existing Job mapping and explanation |
| --- | --- |
| Partition | `partition`, one or more named/index columns; exact decoded tuple equality, preserves encounter order within children |
| Allocate exact percentages | `assign`, named decimal weights summing exactly to 100, optional strata; largest-remainder quotas within each parent/stratum, randomized membership and preserved encounter order |
| Allocate approximate percentages | `assign_probabilistic`, same weight/strata form; independent draws, variable counts, potentially empty destinations/strata |
| Shuffle | `shuffle`, default `uniform`; external random-key sorting where needed; `auto` preserves the current policy's guarantee; advanced explicit `fisher_yates` fails if a parent cannot fit, without changing algorithms |
| Balanced count | `balanced`, N consecutive child ranges per parent, sizes differ by at most one; fails for fewer than N rows |
| Interleaved count | `interleaved`, N alternating children per parent; exact balance, concatenating outputs does not restore input order |

Final `limits.rows` and `limits.bytes` are a separate section after the operations,
not movable intermediate steps. Bytes mean actual encoded uncompressed CSV,
including BOM/header/quotes/line endings. Show decimal versus binary units.
A record is never split. A terminal balanced/interleaved count cannot silently
create more files to fit a cap; data-dependent conflicts fail without publication.
Intermediate N is per parent, not a promise of N files globally. Named empty
allocations and subsequent balanced failures keep existing engine behavior.

Field sorting, intermediate ordinary row batches, and balanced groups of at most
X rows are future product operations. Do not offer them as available choices or
translate them into final caps or balanced file counts. No filtering, joins,
calculated columns, data cleaning or general explorer is added. Future ordering
relaxations in product-direction do not change today's assignment-order contract.

## Output, reproducibility, resources and review

Choose a destination whose parent exists and which is absent or empty. Explain
no overwrite, staging on the destination filesystem, atomic native directory
publication and failure cleanup. Do not pre-create output results to test access.
An empty selected directory is handled only by existing publication code. Recheck
at commit through that code; wizard preflight does not remove destination races.

Packaging choices map to none/gzip/zip. ZIP is one archive containing all CSV
members and a manifest, plus the existing adjacent manifest. Row/strict-byte caps
apply per CSV member; `compressed_bytes` is an advisory member-payload target,
not a total archive ceiling. Explain filenames, safe labels and where manifests
retain original group values. Large fanout is limited by `max_files`, not an
estimated cardinality permission.

New jobs default to automatic working memory and automatic workers (`workers = 0`).
Exact versus approximate allocation remains independent from profile accuracy;
approximate counts do not weaken CSV caps or full-shuffle guarantees. There is no
reproducibility requirement control, user seed or seeded-output policy. Saved Job
JSON rejects `seed` and the guided Resources menu contains only resource settings.
The engine generates internal entropy for each new execution; preparation fixes
the exact encoded output snapshot used by confirmation. No rerun order is promised.

Expose memory_mb (numeric MiB or `auto`), workers (0 automatic), temp_dir,
temp_bytes, max_files and max_record_bytes; advanced grouping auto/sort uses the
existing physical selector. Explicit values remain exact. Explain that auto memory
is resolved from shared admission at task start, grants compete, and working
allocation is not an RSS cap. Workers do not parallelize every phase. Show requested
settings at review and actual budget/workers from completed Analysis. Do not guess
future free disk, effective values or an optimal strategy. Invalid combinations
return the existing validation error without silently reducing a record limit.

Review displays resolved paths/member, input/output dialects, ordered operations
with column bindings, final caps/packaging, requested resources,
policy and guarantee, inspection coverage/age, and warnings. Mark final file
count/bytes/time unknown before Run unless actually known; a full input profile
does not prepare exact outputs. No mandatory `engine::prepare` pass is added.
Point users needing the separate exact workflow to existing `analyze`; do not
promise its CLI invocation retains a prepared object for later wizard execution.

Run confirmation defaults to No and names source/destination. Only explicit Yes
starts engine::run. After success show destination/manifest, rows, logical groups,
physical files, CSV bytes, algorithm version/resources and warnings. Return
to edit only explicitly; rerunning requires another confirmation and an available
new destination. Failure to print final JSON after committed output reports
that output may already be complete; do not retry or delete it automatically.

## Save, reload and scripted rerun

Persist the existing strict version-1 Job JSON, not a wizard-specific schema or
observations. Preserve fields the wizard does not edit. Validate before saving;
refuse drafts unsupported by the current slice with an explanation, while leaving
the original imported file untouched. Bound load to the existing 1 MiB limit and
apply strict decoding/version/removed-option errors; no migration by guessing.

Save asks for a file path and refuses input/output collisions. A new file uses
exclusive no-clobber publication of a complete sibling temporary file. Existing
configuration replacement needs a separate explicit overwrite confirmation and
atomic replacement; on write/flush/rename failure retain the old file and draft,
report any owned temporary cleanup failure. Do not write a config inside the
job's output directory or replace the source CSV. This is configuration persistence,
not engine publication or a new resumable-job format.

Keep the existing process-working-directory interpretation of relative Job paths
on save, load and `run`. Display that directory and absolute interpretations on
reload; never silently switch to the config file's directory. Offer an explicit
Convert paths to absolute action covering input/output/temp_dir before portable
save. Do not promise portability between Windows and Linux path namespaces.

After saving, print a platform-appropriate quoted command for the absolute config
path: `chopper run --config PATH --yes`.
Treat paths as arguments, not shell code; include spaces, apostrophes and Unicode
in quoting acceptance. Also explain existing optional run memory/worker overrides
and that a completed destination needs a new path for rerun. The saved JSON records the requested configuration; the displayed command does not
rely on terminal history.

## Progress, cancellation and errors

Install one process cancellation handler, not one per profile/Run; refactor CLI
orchestration narrowly to reuse it. Pass the existing AtomicBool and Notify into
profile/engine calls. Render emitted phase/rows/temp_bytes on stderr in order,
without claiming a global percentage, ETA or progress graph. Profile StageProfile
strings are expected strategies; actual strategy claims require returned execution
metadata or emitted phases. State unknown when that information is absent. Do not
infer that a spill, fusion, retry or algorithm switch occurred from a guessed plan.

At idle prompts Ctrl+C or EOF aborts with exit 1 and no auto-save. During a task,
Ctrl+C requests cancellation and waits for task/helper shutdown and owned cleanup;
then exit 1 without continuing the journey. EOF encountered at any prompt also
aborts, including confirmation and overwrite prompts. Task execution does not
consume stdin as CSV or accept queued edit commands. A second interrupt must not
claim cleanup completed; forced termination can leave staging. Normal successful
Run, explicit save-and-exit and deliberate menu Cancel exit 0. Unrecovered parse/validation, I/O, task and terminal errors exit 1, retaining
clap's existing argument-error behavior. Recoverable errors remain in the session;
a later successful Run or deliberate menu Cancel determines the final status. These new wizard statuses do not change existing command statuses.

Recoverable editing/load/save/profile errors keep the draft and allow correction,
Back or Cancel. Failed Run returns to review only after engine owners and workers
are finished; preserve configuration and show that no successful result was
published, unless failure occurred after commit while reporting. Do not blindly
retry, change strategies, or delete an existing destination. Surface engine errors
and owned cleanup failure paths. Source changes require renewed inspection or an
explicit decision to run with fresh validation; profiles never bypass that check.

Optional **Browse** is future scope. The former hidden `pick-path` helper and
native server/picker modules have been retired; they are not current reuse seams.
Any future picker must keep blocking dialogs outside the wizard worker.
Picker dismissal returns to the path prompt; missing GUI/WSL interop or helper
failure offers typed input. Stop/reap helpers before session release on cancellation.
A picker lifetime is not an HTTP-body lifetime. Do not create an HTTP server for
this workflow or duplicate picker process/resource management.

## Implementation seams and boundaries

The table originated against main `77eec95`; current reusable modules remain
linked below. The picker proposal was superseded by native-server retirement:

| Responsibility | Reuse / proposed narrow change |
| --- | --- |
| Command parsing, Job import, confirmation, signal and progress | [main.rs](../crates/chopper/src/main.rs); add a private guided module and shared orchestration only where required |
| Stream final Analysis | [cli_json.rs](../crates/chopper/src/cli_json.rs); retain short-write/error propagation and bounded buffering |
| Input observations | [profile.rs](../crates/chopper/src/profile.rs), ProfileCache::profile/clear and InputProfile accuracy fields; no new parser or profiler backend |
| Native picker | Deferred; the former picker/helper-session implementation is retired. Any new implementation needs its own ownership and acceptance contract. |
| Job/column validation | [config.rs](../crates/chopper-core/src/config.rs) and existing resolve_column; no new schema, defaults, operation semantics or core changes needed |
| Run and publication | engine::run, existing direct/prepared dispatch, output/storage owners; no new engine plan, retry or publication implementation |

Keep interactive presentation private to the binary; do not spread prompt state
through the engine or hosted adapter. Use injectable terminal I/O/actions for
small transcript tests, plus actual binary journeys for contract acceptance.
The current interfaces are the native CLI and hosted browser app; see
[retirement scope](https://github.com/jsmatfess/chopper/issues/12). Guide changes
must preserve the hosted WASI behavior and native publication contracts.

## Bounded delivery and acceptance

The three child issues below are sequential reviewable end-to-end slices. A is
owner-authorized; B/C each still require explicit runtime authorization. They do not wait for all engine candidate
investigations or authorize simultaneous engine work. No benchmark panel, timed
Run, large generated input, new default, or release/deployment work is included.

| Slice | Complete journey and limit |
| --- | --- |
| [A: initial journey](history/prior-issues.md#issue-106) | Explicit guide, typed UTF-8 headered CSV, optional full-scan preview, no operations, plain CSV with final row/byte caps, resources/reproducibility, back/edit/save/reload, confirmation, Run/progress/cancel and summary |
| [B: ordered pipelines](https://github.com/jsmatfess/chopper/issues/8) | Add all six existing Operation variants, named/index selectors, reorder, strata, bounded value/tuple exploration and exact/approximate explanations; same save/run journey |
| [C: format and picker completion](https://github.com/jsmatfess/chopper/issues/7) | Add input/output dialect/encoding/header controls, compressed sources/member entry, output packaging/advisory targets and optional owned native pickers; same save/run journey |

Each slice refuses unsupported imports/settings before execution, without dropping
fields or silently defaulting them. It can direct the user to existing `run` or a
later slice. Slice A still permits quoted/multiline UTF-8 records; headerless and
nondefault CSV settings arrive in C. A must deliver useful capped exports, not a
prompt-only framework. B must deliver reordered outputs, not menu snapshots.
C must deliver decoded/re-encoded/packaged outputs, not only picker stubs.

Acceptance uses tiny deterministic fixtures and independently parses resulting
CSV/manifests. Preserve failures and actual platform identities in PR validation;
no performance/scale claim follows. Each child requires native Linux **and native
Windows** binary acceptance at its committed revision; WSL is Linux coverage only.
Parent serializes applicable real CI and main delivery. The original specification-only PR required documentation/link/command review;
runtime slice delivery requires the actual platform acceptance above.

Required journey coverage, apportioned in child bodies:

- A: start, inspect or skip, edit caps, save/reload, decline then confirm, inspect
  actual output and rerun through existing `run --yes` to another destination.
  Independently verify row/encoded-byte caps including quoting/newlines/header,
  field/ID conservation and manifest counts; saved configuration omits seed settings.
- A: non-TTY returns promptly; stderr/stdout separation; EOF at every prompt type;
  Ctrl+C at idle and during profile/direct Run; malformed late row, oversize
  record/header cap, invalid resources, save failure, nonempty destination and
  destination-created-before-commit race. Assert no published partial success,
  cleanup of job-owned staging/temp, and preservation of unrelated files.
- B: same source with partition→shuffle versus shuffle→partition is saved in
  exact chosen order and matches existing scripted engine results for each order.
  Test duplicate/numeric/comma headers, headerless indices when C is available,
  exact largest-remainder and stratified quotas, approximate actual counts without
  asserting target quotas, balanced/interleaved cap conflicts and named empties.
- B: low/high cardinality, >64-column schema with selected late columns, long
  escaped values, display truncation versus exact-count status, tuple rescan,
  cache reuse/invalidation and Windows rescan. Prove profile-only selection never
  enters executable operations. Cancel during prepared pipeline processing and
  publication; no partial success or leaked private outputs, configuration retained.
- C: gzip/ZIP with explicit multi-member choice, nondefault delimiter/encoding,
  BOM and multiline records; independent decoded-field and encoded-cap checks,
  ZIP member/manifest counts and advisory-target wording. Exercise codec failure,
  unrepresentable output and cancellation during finalization without publication.
- C: actual optional dialog input/output selection and dismissal on each supported
  native platform, missing-GUI typed fallback, cancellation with helper reaping,
  Windows drive/space/Unicode paths and Linux paths. Record real-dialog checks
  separately from injected helper tests; a blocked platform stays blocked.

Use existing fault-injection seams for commit/finalization boundaries where
available; do not rely on elapsed sleeps or huge inputs to hit cancellation.
Verify postcommit cancellation/reporting cannot relabel completed output as an
unpublished failure. Retain existing scripted CLI regressions and server/hosted
checks under normal contributor routing when shared seams change. Do not broaden
claims to macOS, other terminals, power-loss recovery or unsupported filesystems.

Child issue links and authorization state are routed through
[guided CLI issue #13](https://github.com/jsmatfess/chopper/issues/13).
