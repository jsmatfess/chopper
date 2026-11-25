# Performance decision registry

Start with the generated [current overview](../performance-overview.md). It covers
selected recent delivered changes and retained/rejected experiments. It does not
claim exhaustive historical coverage. The [benchmark catalog](../benchmarks/INDEX.md)
still locates all inventoried artifacts; [performance.md](../performance.md) preserves
old anchors and routes individual [investigation narratives](investigations/).
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) is the sole active
backlog and specification tracker.

## Query without reading the historical log

Run from the repository root; Python's standard library is sufficient. Queries
validate records but never download evidence, launch benchmarks or write files.

```sh
# Current decisions, with exact filter values from decision.schema.json.
python3 scripts/performance-registry.py --query
python3 scripts/performance-registry.py --query --subsystem storage --runtime native-windows --json
python3 scripts/performance-registry.py --query --disposition reject --json
python3 scripts/performance-registry.py --query --delivery opt-in --json

# Trace a superseded decision or read all of a record's bounds and provenance.
python3 scripts/performance-registry.py --query --include-superseded --json
python3 scripts/performance-registry.py --show fusion-observation-only-2026-11-05
```

JSON queries return a versioned envelope with an explicit selected-coverage label
and the matching complete records. Text queries return tab-separated ID, decision,
delivery and summary. Filters combine with AND; no matches produce an empty result.
`--show` also accepts superseded IDs. Query `scope.runtimes` describes runtimes
studied for that decision; `validation.runtimes` describes recorded checks. Neither
means that every metric, variant or feature combination was tested on each runtime.
Read the workload, measurement boundary and validation summary before applying a
claim. A WASM compile alone is not browser execution coverage.

## Record contract

Each file under [decisions/](decisions/) follows [decision.schema.json](decision.schema.json).
Use stable descriptive IDs matching the filename. These records summarize reviewed
interpretation; they are not benchmark observations or new statistical samples.

- `disposition` states the decision: adopt, retain-experimental, reject,
  block-promotion or informational.
- `outcome` states the measured result: favorable, unfavorable, mixed, inconclusive,
  diagnostic or acceptance-only. Favorable does not mean shipped.
- `delivery` independently records default, opt-in, unapplied or unchanged.
- `scope`, `validation`, `limitations` and `exclusions` preserve workload/runtime
  boundaries and distinguish complete-Run measurements from diagnostics and checks.
- `sources` pins dated H2 interpretations using their stable legacy references.
  The loader follows the narrative manifest and restores original link spellings
  before checking source identity. Its SHA-256 covers the catalog parser's
  section lines joined with LF, without an added final newline. A source edit
  requires reviewing the decision and deliberately refreshing that hash; adding
  unrelated navigation does not invalidate records.
- `artifacts` pins explicitly linked raw/report identities from the catalog.
  These are document/file references, not selectors for independent observations.
  Use the existing lossless exporter and physical JSONL lines or JSON pointers for
  numerical analysis. Missing metadata remains unknown.
- `contracts` routes current specifications and ownership guidance. Links with
  fragments currently target H2 headings, checked using the catalog's parser.
- `supersedes` names earlier registry IDs, not narrative anchors. The checker
  rejects missing targets, cycles and references to later decisions. Supersession
  replaces a disposition or candidate revision; it does not erase the earlier
  counterexample or make its evidence eligible for the new variant.
- `reopen_when` records a documented condition for revisiting a result, or null
  when no condition was recorded. It is not an instruction to start work.

The schema is authoritative for fields, types and enums. The standard-library
checker implements only the JSON Schema assertions used here and rejects unknown
assertions when encountered. Extend the checker and its controls when extending
the schema; do not assume it supports arbitrary JSON Schema features.

## Maintain and verify

Add records for new decisions and backfill relevant older investigations as needed.
Preserve historical narrative content and raw artifacts. Do not mechanically infer outcomes,
eligibility, delivery or supersession from filenames, dates or timing fields.
Confirm delivery against current source; the checks establish structure and
provenance, not the truth or continuing completeness of an interpretation.

After reviewing source changes, refresh the existing evidence navigation when
needed, then generate the overview:

```sh
python3 scripts/performance-narratives.py
python3 scripts/audit-strategy-evidence.py
python3 scripts/benchmark-catalog.py
python3 scripts/performance-registry.py
python3 scripts/evidence-views.py --build
python3 scripts/test-performance-registry.py
python3 scripts/performance-registry.py --check
```

Run the full [read-only evidence checks](../benchmarks/README.md#evidence-checks)
for evidence changes. CI rejects stale output and never regenerates it. The
registry checker verifies section hashes, catalog artifact identities, any present
local raw files, contract links and supersession. Archived originals need no
hydration for registry queries; this does not verify unavailable raw bytes or
replace the existing authenticated historical-evidence checks.

## Investigation narratives

Each document under [investigations/](investigations/) owns one historical H2 section.
The [manifest](narratives.v1.json) pins its bytes, topic, legacy anchors and Markdown
link relocations. Topics reuse the existing reviewed strategy-family assignments,
with navigation material labeled separately. Query by topic or title:

```sh
python3 scripts/performance-narratives.py --query --match publication --json
python3 scripts/performance-narratives.py --query --topic compact-parser-and-consumers --json
python3 scripts/performance-narratives.py --check
```

The migration restores each section's original link spellings and reconstructs the
entire pre-migration document to verify its SHA-256. Code fences retain repo-root
reproduction commands. Former H2 and nested-heading anchors resolve through the
generated compatibility index. Existing citations and decision source hashes stay
usable; the catalog and current overview link directly to the new documents.
Links to archived originals route through their hash-addressed retrieval guidance,
preserving the existing private access boundary rather than exposing raw originals.
Inter-section separator newlines stay in reconstruction metadata, so standalone
documents have canonical file endings without changing original section identities.

Historical findings stay immutable. Put corrections or new findings in a new dated
investigation and state what it supersedes. To add one, create an investigation
Markdown file with exactly one H2; its heading anchor must match its filename.
Save it as UTF-8 with LF line endings; registration rejects CRLF before pinning
bytes that Git would normalize on commit.
Use links relative to that new file, and run:

```sh
python3 scripts/performance-narratives.py --register docs/performance/investigations/example-decision-2026-11-06.md --topic reviewed-family
```

Replace the example path/topic with the actual reviewed document. Registration adds
its stable legacy alias without changing the frozen migration identities. Add its
title to the strategy audit's explicit family assignments as required, add a decision
record when appropriate, then run the refresh sequence above. The manifest's
`migrated_count` separates the frozen original corpus from newly registered work.

## Normalized observations and validation

[views.v1.json](views.v1.json) defines versioned metric units, document-layout adapters
and reviewed comparison/contract bindings. [The generated inventory](evidence-views-index.v1.json)
lists extraction coverage for every cataloged content identity, including unsupported
artifacts and byte-identical aliases. It contains navigation/counts, not another copy
of the raw observations. Queries read only matching sources, verify their catalog
hashes, and emit bounded JSONL; `--all` explicitly exports every matching record.
Use the existing resolver for authenticated hydration when a selected source is absent.
No query downloads evidence implicitly.
Every emitted observation or receipt is checked against its versioned
[observation schema](observation.schema.json) or
[validation receipt schema](validation-receipt.schema.json). CI pins the adapter,
schema and configuration identities alongside extraction coverage.

```sh
python3 scripts/evidence-views.py coverage --source '*inline-spool*'
python3 scripts/evidence-views.py record --source 'plain-publication-feature-2026-11-05.json' --pointer /native_cli
python3 scripts/evidence-views.py observations --source 'inline-spool-key-*.json' --metric wall_time
python3 scripts/evidence-views.py observations --source 'shuffle-partition-native-2026-10-16.jsonl' --comparison shuffle-native
python3 scripts/evidence-views.py observations --source '*allocation-ranges*' --classification allocation-census --limit 5
python3 scripts/evidence-views.py validation --contract native-plain-publication-parity-and-cleanup
python3 scripts/evidence-views.py validation --source 'probabilistic-shuffle-spill-browser-*.json' --runtime wasi-chrome-persistent
python3 scripts/evidence-views.py validation --source '*.json' --status failed --limit 10
```

Each observation retains source SHA-256, canonical alias, all byte-identical aliases,
physical JSONL line and/or explicit document pointer. Each scalar metric also retains
its source pointer/value/unit, conversion scale, normalized unit and measurement scope.
For JSONL, the pointer is relative to the selected physical line. Repetitions remain
individual records; no averages, pooled effects or speed rankings are produced.
IDs use source hash plus location, so identical bytes are not additional observations.

Dimensions come from explicit fields on the observation. Missing build, fixture,
workers, runtime, seed, plan or cache metadata stays null. Environment records on
adjacent JSONL lines are not inherited. Document-level `metadata_refs` locate recorded
build/source identities and workload/runtime context without broadcasting them as
row facts; use `record --pointer` (and `--line` for JSONL) to inspect those exact values. A record's timing boundary remains unknown
unless recorded explicitly or supplied by a named reviewed comparison. Resource
counters from Analysis retain their snapshot scope; RSS, reservations, sampled
storage, logical traffic and physical I/O remain different quantities.

Execution-graph compact projections use explicit adapters: `/samples/*` stays
`summary`, `/runs/*` stays `diagnostic`, and `/batches/*/commands/*` retains each
command's recorded status (missing means `unknown`). Context/cohort/build references
remain document metadata references; they never populate absent row dimensions.
[Reviewed raw locations](../benchmarks/execution-graph-comparison-locations-2026-11-05.json)
pin the original paired cells and clock, but local raw sources outside the catalog
are not normalized comparison bindings. Do not count their summary copies as
additional executions.

Every extraction starts `unreviewed`. A named comparison binding assigns exact
baseline/candidate locations and records its review provenance; that assignment
does not make a sample eligible for any other comparison. The historical bindings
reproduce the unchanged 38-cell numerical audit, and the additional recent bindings
select each documented primary cohort explicitly. CI checks historical memberships
and exact clock fields against the pinned audit. The `clock_pointer` identifies the
reviewed wall-time field when a source records multiple clocks; comparison queries
retain only that wall clock, alongside separately scoped resource metrics.
Controls, derived summaries, allocation censuses and
contract durations do not become complete-job speed samples. Distinct report files
can reuse observations: source hashes identify stored records, not universally unique
engine executions. Do not aggregate the unreviewed corpus or count a derived report
as an independent experiment. Unsupported layouts remain visible in the inventory
until a reviewed adapter and its controls are added.

## Validation receipts and claims

Start with the generated [validation index](../validation-index.md) for reviewed
contract routes and every existing validation narrative. Structured check records
preserve passed, failed, blocked, unrun, skipped, invalidated, incomplete or unknown
outcomes and original status/exit codes. No status is inferred from prose, a duration,
the presence of a test array, or the name of a batch. Declared platform aliases and
reviewed pinned contract bindings are the only sources of canonical runtime labels.
Compile checks remain distinct from executed browser acceptance.

To inspect a local [validation runner](../validation-runner.md) batch:

```sh
python3 scripts/evidence-views.py validation --batch scratch/my-validation-batch --all > scratch/my-validation-receipts.jsonl
```

The importer reads `manifest.json` and optional `status.json`, preserving every attempt,
input/artifact identities, runtime identity, command and available log references.
Numbered runner logs are located using the documented runner naming contract and
hashed when available; missing logs stay explicitly unavailable.
Manifest-only batches and never-attempted steps are `unrun`. The `latest` flag and
stable `receipt_id`/`attempt_key` distinguish later failures and repeated snapshots.
Import is a historical snapshot; it does not execute commands, recheck external
build bytes, grant reuse, or turn an older passing attempt into current acceptance.

For future plans, optional step metadata can explicitly declare the intended coverage:

```json
{
  "coverage": {
    "contract": "native-publication-cleanup",
    "contract_refs": ["docs/direct-execution.md"],
    "runtime": "native-windows",
    "browser": null,
    "features": ["experimental-plain-publication"]
  }
}
```

This metadata is retained in the immutable runner manifest; it does not alter runner
execution or prove that a verifier is adequate. Absent coverage/build/browser data
remains unknown. Existing historical receipts with unavailable builds/logs retain
their source references and limitations; importing them does not hydrate or recreate
the missing artifacts. Test durations never become performance gains, and test counts
from different passes are not added.

### Review product observations from a failed attempt

Use the attempt view to read a historical acceptance attempt alongside its
independent verification, controller completion and cleanup records.

```sh
python3 scripts/evidence-views.py attempt --review docs/performance/attempt-reviews/chrome-g-export.json --summary
```

Omit `--summary` for JSON with each selected receipt value, path, SHA-256 and
JSON pointer. A review is a separate annotation. It pins the retained JSON
receipts (or a committed release record that identifies private receipts) and
records the reviewer’s interpretation and coverage for each field. The view
checks the selected source bytes and pointers and preserves the original
outcome. Treat unavailable proof as `unknown`. An attempt passes only when the
original outcome, controller completion and cleanup all passed. A failure in
any of those fields makes the attempt failed, and missing mandatory proof
leaves it incomplete.

Add `reviewed_reuse` only with a specific independently verified claim, its
relevance to the original attempt and the reason its verifier evidence can be
reused. The Chrome G review credits the retained export checks on that exact
fixture, product and browser. Its original controller failure remains visible.
The command exits successfully when it renders the evidence, so use the JSON
`status` field to inspect the attempt outcome.

The [Native UI Cancel review](attempt-reviews/native-processing-cancel.json)
uses the privately retained Windows r5 receipts. Run the same command with its
review path and `--receipt-root` pointing to the local directory containing
`native105-smoke-processing-cancel-r5`. That attempt has separate after-exit
process and lock proof. The cancellation observation is supported by the worker
receipt. Keep private receipt bytes and exports in the appropriate storage.
[Evidence storage policy](../evidence-storage.md)
