# Benchmark data guide

For current build/validation entry points and historical command status, use the
[script guide](../../scripts/README.md). The nine retired shuffle harnesses live
in a [source archive](../history/shuffle-harnesses-2026-11-16/README.md) with their
original bytes and dependency copies. Catalog source links route there; fenced
commands in old narratives retain their recorded checkout paths and engine
schemas. They do not authorize comparisons against current main.

Start with the [evidence index](INDEX.md) to find an experiment, its raw files and reproduction scripts. [catalog.json](catalog.json) provides hashes, sizes, record kinds, available top-level fields, context-record locations and evidence links for all artifacts. [Investigation narratives](../performance/investigations/) own interpretation and exclusions; the [compatibility index](../performance.md) retains legacy anchors; [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns future work.

For selected current conclusions, delivery status and supersession, start with the
[generated overview](../performance-overview.md) and [decision registry queries](../performance/README.md).
Registry decisions are reviewed interpretation, not extra benchmark observations.
The [narrative topic queries](../performance/README.md#investigation-narratives),
[normalized observation/receipt views](../performance/README.md#normalized-observations-and-validation)
and [validation index](../validation-index.md) provide narrower retrieval paths.

The catalog inventories retained evidence without moving or rewriting raw artifacts. Older filenames and section anchors stay usable. A section's artifact/script links are extracted from explicit references, including reproduction code; they do not assert a complete dependency graph or establish eligibility for analysis. Unlinked artifacts are still indexed. The JSON/JSONL schemas vary across harness versions; inspect the original fields before comparing.

## Find, refresh and export

Raw evidence under `docs/benchmarks/` preserves its exact stored bytes, with Git
text conversion disabled in [`.gitattributes`](../../.gitattributes). Markdown
here and `docs/performance.md` use LF, and generated navigation explicitly writes
LF. The catalog and exporter hash actual bytes; Windows CRLF conversion must not
change those identities. Preserve historical content when refreshing the catalog.
The decision-table and strategy-coverage analysis scripts also use LF because their
exact source hashes are retained in the derived audits; checkout line endings must
preserve those identities.
In PowerShell, set `$env:PYTHONUTF8 = '1'` before running the decision-table
analysis script so its Markdown reads use UTF-8 rather than the Windows locale.

Run from the repository root; Python's standard library is sufficient. The script also works from other directories.

```sh
# Refresh the coverage audit first: it retains performance.md identity even
# when an edit adds no sections or raw artifacts. Review new family assignments
# if the audit reports an unknown section; do not infer timing eligibility.
python3 scripts/performance-narratives.py
python3 scripts/audit-strategy-evidence.py
python3 scripts/benchmark-catalog.py
python3 scripts/performance-registry.py
python3 scripts/evidence-views.py --build
python3 scripts/performance-narratives.py --check
python3 scripts/audit-strategy-evidence.py --check
python3 scripts/benchmark-catalog.py --check
python3 scripts/performance-registry.py --check
python3 scripts/evidence-views.py --check

# Locate candidate evidence without reading tens of megabytes of results.
rg 'random-buckets|allocation-ranges' docs/benchmarks/INDEX.md

# Export original records with source identity and location, preserving every field.
python3 scripts/benchmark-catalog.py --export-records --match 'random-buckets-*.jsonl' > /tmp/chopper-bucket-records.jsonl

# Restrict to raw timed measurements; inspect build/runtime/fixture context before grouping.
jq -c 'select(.kind == "measurement") | {source, line, data}' /tmp/chopper-bucket-records.jsonl
```

Export emits one envelope per nonblank JSONL line or one envelope for an entire JSON document. Each has `schema_version`, `source`, `source_sha256`, `kind`, `data`, and either a physical 1-based `line` or JSON `pointer` (the empty pointer denotes the document root). Original values, units and nesting remain in `data`. Untyped records remain `untyped`; the tool does not infer their purpose from the presence of a timing field. Text logs appear in the inventory but are not JSON record exports. `context_records` in the catalog locates declared environment/design/fixture records; some documents embed environment objects instead. Missing metadata is unknown, not inherited from a nearby file.

The exporter intentionally includes environment, summaries, controls and failure records. Select an analysis population explicitly. A `*-summary-*.json` is a report referencing existing observations, not another independent experiment. Browser `tests[].seconds` are contract durations, not baseline/candidate speedups. Declared record counts are inventory counts, not verified-job totals. Exact duplicate file contents are listed separately to help prevent double counting.

The [full strategy review](../strategy-review.md) adds explicit family coverage
beyond the selected 38 historical contrasts. Reproduce its derived coverage with
`python scripts/audit-strategy-evidence.py` and `--check` before refreshing the
catalog. It reuses this catalog's parser/record reader; unknown sections or
unlinked artifacts require a reviewed family assignment. Coverage is not timing
eligibility. Keep the historical numerical synthesis and its source hashes intact.

## Evidence checks

Run these existing checks from the repository root with Python 3 (standard library
only). In PowerShell set `$env:PYTHONUTF8 = '1'` first, as above.

```sh
python3 scripts/test-benchmark-catalog.py
python3 scripts/test-performance-registry.py
python3 scripts/performance-registry.py --check
python3 scripts/test-performance-narratives.py
python3 scripts/performance-narratives.py --check
python3 scripts/test-evidence-views.py
python3 scripts/test-evidence-resolver.py
python3 scripts/test-evidence-migration.py
python3 scripts/evidence-resolver.py check
python3 scripts/evidence-resolver.py index --check
python3 scripts/benchmark-catalog.py --check
python3 scripts/summarize-performance-decisions.py --check
python3 scripts/audit-strategy-evidence.py --check
python3 scripts/evidence-views.py --check
```

These are the CI evidence job's read-only checks, not benchmark runs. They test
catalog behavior and reject stale navigation, historical numerical synthesis or
strategy-family provenance. A failure requires reviewing the source change;
CI must not regenerate outputs to accept drift. For intended evidence updates,
use the refresh commands above (strategy audit before catalog when applicable),
then rerun this group. Preserve raw bytes, exclusions and numerical synthesis
unless an explicitly authorized analysis changes them.

## Comparison and future meta-analysis

For the Windows exact shuffle/partition harness, `--retained-parent` selects
`balanced(1) -> uniform -> partition(c0)` and verifies one completed charged
retained-parent audit record. Legacy ingestion-fusion cells do not initialize
that audit and cannot measure its costs. The verifier retains the exact live
owner equation, including a validated audit charge. Fresh build provenance must
include both tracked and nonignored untracked compilation inputs; the harness
source inventory includes both, including the patched ZIP and Zstandard
dependencies under `vendor/`. Reused builds still require their original
source/features evidence rather than relabeling them with today's checkout.
The retained-parent skew fixture partitions the 90/9/1 payload key; earlier
balanced-key runs are different workloads. The verifier reads UTF-8 explicitly
on Windows. `--space-sample-ms 0` disables live directory scans and records final
output size after process exit only, not a live storage peak. Preserve publication
failures and partial cells when using that mode to investigate interference.

For native Windows profiling, `scripts/benchmark-windows-profile.py` reuses the
historical profile fixtures and normalization with Win32 CPU/working-set/transfer
counters. Its required build record pins both CLI and separate allocation-census
artifacts, matching sources and feature sets. Census runs are excluded from timing;
complete profiles are not complete preparation/publication jobs. The raw output
refuses overwrite and retains failures, settings and profile/cleanup verification.

Use a within-experiment comparison as the initial unit of analysis. Keep repeated runs nested under the same fixture/build/runtime cell; a seed, worker count or repeated browser replay does not automatically create an independent study. For an architecture synthesis, maintain an explicit inclusion/exclusion table with artifact hash, record location, baseline/candidate mapping, timing scope, effect estimate, uncertainty and reason for inclusion. Do not pool historical percentage gains or add test/job counts from different passes.

| Dimension | Preserve or check before comparing |
| --- | --- |
| Build identity | Native/WASM hashes, feature flags, harness/source hashes and revision. A later date does not prove a matching baseline. |
| Workload | Fixture hash or exact generator parameters, row/column counts, widths, cardinality/skew, ordering, pipeline, group counts and downstream operations. |
| Runtime/resources | OS/host, native versus WASI, worker count, per-job/shared memory settings, actual resident/spill/fallback plan and merge depth. |
| Storage | Warm/cold/uncontrolled cache, filesystem/device, temporary/private versus persistent browser profile, export destination and sampled storage scope. |
| Timing boundary | Profile/prepare/execute/export, CLI startup, conversion/source validation and publication; separate censuses and microbenchmarks. |
| Correctness/replay | Verified conservation, membership, logical metadata and strict caps; exact bytes/order only for matching pinned algorithms/plans or exact rewrites. Preserve RNG/seed/plan identity and flexible replay limitations. |
| Sample eligibility | Initial/revised/superseded passes, stale baselines, interrupted/partial logs, invalid configurations, failure controls, diagnostic flags and exclusion notes. Read the dated narrative and summary. |

Report individual sample counts, median and spread before more elaborate estimates; three repetitions rarely support a stable tail claim. Match baseline/candidate runs within the same controlled cell where possible, account for alternating order and shared controls, and avoid treating correlated observations as independent. Aggregate only after establishing compatible outcomes and scope; otherwise present separate strata and uncertainty. The catalog supplies provenance, not a claim that the corpus supports a pooled effect.

Keep wall time, CPU time, requested allocation traffic, peak live reservations, RSS, logical temporary I/O, stored bytes and physical device I/O as different outcomes. A reservation ledger is not an RSS cap. Sampled file peaks are lower bounds. Independent component peaks cannot be summed into a simultaneous total. Physical I/O cannot be inferred from warm-cache logical traffic. Accounting work may improve safe admission while adding time.

Browser context matters: older temporary-context OPFS timings do not establish persistent disk-backed behavior. The [context correction](../performance.md) and [storage reproducer](browser-opfs-contexts-2026-10-17.jsonl) explain the distinction. Preserve failed runs and original statistical flags; a successful follow-up does not erase them. Finite diagnostic success is not proof of uniformity.

## Recording the next experiment

`scripts/probe-zip-metadata.py` and `scripts/probe-browser-zip-metadata.mjs`
exercise small deterministic ZIP selection/allocation cases. The native command
requires the matching allocation-example build record and preserves rejected
attempts; the browser uses the same fixture bytes through the public profile API.
These are accounting/compatibility diagnostics, not timed A/B jobs or a ZIP
metadata ownership grant. Preserve their mixed outcomes rather than presenting
all executed profiles as successful acceptance. Browser fixture files live only
in a task-owned scratch directory and are removed after the run.

Use the [experiment criteria](../performance-opportunities.md#acceptance-for-experiments) and state the architectural decision first. Reuse an existing harness where its measurement scope fits. Record the dimensions above and retain raw per-repetition observations, including failed attempts; do not overwrite a prior pass to make a summary look final. Add and [register a dated investigation](../performance/README.md#investigation-narratives) explaining the candidate, controls, exclusions, correctness checks, resource tradeoffs and decision, then refresh the derived navigation and views.

For future normalized datasets, keep source hash/location as the primary provenance key, define each metric's unit and timing scope, and use null for unavailable metadata. Extract report/document fields with explicit JSON pointers and distinguish observations from derived summaries. Any manual eligibility or baseline mapping should be a separate reviewed analysis table; never silently rewrite raw data or infer missing values from filenames.

## Bounded shuffle comparisons

`python3 scripts/bench-shuffle-swarm.py --help` and
`node scripts/bench-shuffle-swarm-browser.mjs --help` describe the explicit named
recipe harnesses. Both require fresh owned work/output paths and separately
pinned baseline/candidate build manifests. Native timing covers CLI startup
through publication/cleanup; the persistent-Chromium clock covers prepare,
confirmation and destination export/marker after picker setup. They are separate
runtime comparisons. Verification handles quoted/multiline CSV, exact quotas,
named empties, original stages/lineage and caps outside the clock. No recipe
matrix runs implicitly. Preserve failed attempts and source snapshots, use a
separate fresh compilation target for each frozen source forest, and inspect
compiler dependencies before accepting its artifact identity.

`python3 -B scripts/test-shuffle-swarm.py` and
`python3 -B scripts/verify-shuffle-swarm-browser.py --self-test` are synthetic
harness controls, not product jobs or performance evidence.
The native process/timeout control requires Linux GNU `time` and POSIX process
groups; Linux tooling CI installs `time`. Windows runs the portable verifier
controls and explicitly skips that one Linux-only control.

## Bounded random-draw comparisons

`node scripts/benchmark-hosted-memory.mjs BASELINE.wasm CANDIDATE.wasm OUTPUT MODE`
compares explicitly pinned hosted artifacts in a disposable persistent Chromium
context. Choose `pilot` (256/512/1024/2048 MiB screen), `paired` (three complete-job
pairs after excluded warmups), `control` (unchanged 256 MiB small fixture), or
`resident` (old-ceiling denial and larger-budget Fisher–Yates capacity control).
OUTPUT must be fresh. The clock covers prepare/confirm/export/marker/retirement;
binary collection and independent CSV/manifest verification are outside it.
Identical benchmark-only worker instrumentation records linear-memory high water,
not RSS. The resident baseline denial is retained and must leave no exported files
or workspace bytes; it is not a timing observation. Pin source/toolchains and retain
the original harness identity with each cohort, including failed attempts. This
bounded harness does not establish installed-browser or 25-million-row performance.

`python3 scripts/benchmark-random-draws.py --help` compares two explicitly supplied
native binaries on small named recipes, retaining per-attempt configurations,
Analysis, GNU-time resources and independent CSV/manifest verification. It uses
one excluded warmup and alternating variant order; successful verified CSV payloads
are removed while their hashes remain in receipts. `--case direct-control --rows
1000000` is the bounded larger negative control. Bind binaries to frozen source
forests and toolchains before running; this harness does not infer build identity.
The optional `probability-control` recipe independently checks source fields,
conservation, stable within-allocation order and named-zero membership without
pretending that probabilistic counts are exact quotas. Use a fresh output
directory for every attempt, including failed attempts.

`node scripts/benchmark-random-draws-browser.mjs BASELINE.wasm CANDIDATE.wasm OUTPUT
NATIVE_FIXTURES` uses the same fixtures/verifier and existing bounded browser driver.
Its three measured pairs follow one warmup in a persistent disposable bundled
Chromium context. The clock covers preparation, confirmation, export, marker close
and session retirement. Host collection/verification and successful destination
removal are outside that clock. The driver checks retained-owner sums, handles,
export byte counts and empty post-retirement workspace. Browser path translation
and its added export warning are checked explicitly before manifest comparison.
These are development cells, not large-scale or native Windows acceptance.

Current product builds accept no seed setting. Record available internal entropy
and algorithm diagnostics, and compare independent randomized Runs through the
specified membership/order distributions, exact quotas, fields, conservation and
caps. Fixed-seed controls belong to explicit internal tests or matching historical
builds; they do not restore a public replay requirement. Prepared confirmation
continues to require the exact retained snapshot.
