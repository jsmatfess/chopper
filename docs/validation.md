# Validation evidence

Use the [validation index](validation-index.md) and
[receipt queries](performance/README.md#validation-receipts-and-claims) to locate
structured checks and individual attempts. This document owns supported claims;
query metadata and test counts do not extend their recorded coverage.

<a id="csv-compatibility-coverage"></a>
**CSV compatibility coverage**

The checked-in suite for issue #113 verifies headers, field values, record
counts and rejections with explicit settings. It exercises owned and compact
parser records, fragmented reads, native CLI export and publication. See
[#113](https://github.com/jsmatfess/chopper/issues/113) and the
[fixture inventory](../crates/chopper/tests/fixtures/csv-compatibility/README.md).

| Fixtures | Exact Chopper output | Expected rejections | Unsupported settings |
| --- | ---: | ---: | ---: |
| Local RFC 4180-style, dialect, encoding and record-limit cases | 28 | 10 | 1 |
| Selected W3C CSVW header and cell-parsing cases | 14 | 0 | 0 |
| Selected Go standard library cases | 3 | 4 | 1 |
| **Total** | **45** | **14** | **2** |

Expected rejections cover invalid input and configured record limits.
Unsupported cases check configuration errors for UTF-32LE encoding and a
non-ASCII delimiter. Three Go cases check deliberate differences, one in
each outcome column. Chopper preserves CRLF inside quoted fields, rejects
a lone CR outside quotes and requires ASCII delimiters.

CSVW fixture results cover headers and decoded string cells. Six fixtures
exercise explicit opt-in settings. CSVW metadata discovery and import,
schema and datatype validation, and conversion to JSON or RDF are outside
Chopper's support. See [optional input dialect](job-json.md#optional-input-dialect).

Run `cargo test --locked -p chopper-csv --test csv_compatibility` to see the
breakdown by source and any unexpected failures. The local gate's workspace
test runs the same suite, including a 40,000-row forced spill that checks
exact row multiplicities, partition membership and chunk manifests.
See [contributor checks](../CONTRIBUTING.md#choose-the-checks-for-your-change).

Separate tests cover Sniff suggestions and hosted preview and publication
with optional settings. See [Sniff tests](../crates/chopper/tests/inspection.rs)
and [hosted browser checks](browser.md#tests).

## Analyze Run and payload-pass removal (2026-11-18)

The [investigation](performance/investigations/csv-data-movement-and-analyze-run-2026-11-18.md)
and [comparison summary](benchmarks/data-movement-summary-2026-11-18.json) identify
unmerged source overlays on `1a7742732b0a75d698bd36d917bf8dcad3488063`, the separate
FY-only and final native binaries, exact fixtures and exclusions. They do not
identify a new release or deployment.

Linux workspace tests (default and all features), formatting and Clippy passed.
Native Windows workspace tests passed in a new NTFS validation checkout; final
CLI source/grant lifetime, interfaces and automatic-memory checks passed again
after the last CLI-only teardown correction. The existing Windows checkout was
not changed. Resource and failure controls cover exact realized FY-to-Balanced
cuts, downstream order, strict serialized caps, final competing-owner admission,
cancellation, destination races and private/temp cleanup, without raw-input replay.

Bundled Chromium 156 passed the hosted UI and processing/graph/lifecycle sequence,
including cleanup, persistent restart and forced-process interruption variants.
Baseline and experimental shuffle/partition WASI resource-contract suites passed.
After the final correction changed rebuilt WASM bytes, core processing and full
graph acceptance passed again against the final production artifact; receipts
record before/after asset hashes. Default production WASM and hosted assets were
restored after test builds. This is small-fixture correctness evidence, not new
Windows/browser throughput or large-scale acceptance.

The selected performance cells contain 58 measured complete native Runs and 18
excluded warmups across nine separate comparisons. Five pairs confirm small plain
Balanced after a mixed three-pair result; other cells have three pairs. Their warm
WSL2/ext4 scope reaches 1,986.26 MiB input under a 256 MiB working budget, without
exhausting physical host RAM. Do not pool these fixtures with the earlier four-column
DuckDB/qsv comparison or infer 40 GiB/cold-storage/native Windows/browser speed.
Full logs, complete source/vendor identities and interrupted attempts remain in
the local ignored provenance packet linked from the investigation. Historical
archive hydration still blocks complete evidence-index regeneration.

## Selected native D/G scale acceptance (2026-11-15)

The [sanitized acceptance record](releases/0.2.0-native-scale-acceptance.json)
records selected product `639d1fe`, runtime build `feb9e09` and artifact receipt `1720f28`.
Linux and native Windows D/G each processed an exact 10,000,000,000-byte input
with 64 MiB engine working memory, one worker and a strict 10,000,000-byte
serialized CSV chunk cap. This is working-allocation accounting, not an RSS cap.
Windows G's independently verified seeded report equals its accepted Linux peer;
it records 712 disk sort runs, 720 merge inputs and 16 merge operations.

Windows D retains its earlier accepted report and canonical claim from harness
`3f06f23`; that session's later G-generation failure remains failed. Fresh G used
harness `8a543af`, consumed only the remaining G slot and independently checked
three current G cleanup roles, owned process absence and normal Original release.
Historical D cleanup is pinned separately. Failed preparations, capacity samples
and their charges remain retained; administrative retirement of a failed read-only
observer is separate from these normal product cleanup proofs.

The recorded temporary traffic is logical engine traffic, not physical I/O or a
peak allocation measurement. These proofs support the selected native scale
scope in [#103](history/prior-issues.md#issue-103), not a general
performance or arbitrary-build claim. Browser scale
[#104](history/prior-issues.md#issue-104), final package readiness
and publication remain separate. See the [native controller guide](../scripts/scale_acceptance/NATIVE.md)
for admission and proof boundaries.

## Selected hosted scale and final-package smoke (2026-11-15)

The [four-cell browser record](releases/0.2.0-browser-scale-acceptance.json)
records exact 1,000,000,000-byte D/G inputs in installed Windows Chrome
157.0.8103.51 and Edge 157.0.4341.60, using the same selected product/package
bytes as native acceptance. Each used 64 MiB engine working allocation, one
worker and strict 10,000,000-byte CSV chunks. Independent streaming verification
checked all fields, IDs, quotas, conservation, names, manifests and markers;
Chrome/Edge seeded output reports match exactly. G recorded 72 completed spill
runs and eight interrupted merge cursors after visiting the full 999,999-row
quota. That interruption is retained as observed, with no failed or omitted
graph details; it is not relabeled completed.

Chrome G's original harness failed after its product Run completed. Separate
read-only recovery copied the closed profile and independently verified its
completed export, without another Run, fixture generation or canonical claim.
Current Edge completed all 15 SMALL contracts at `6afaffb`, then complete scale
Tiny and both Large cells at frozen `94a4b76`. Each accepted path has normal
cleanup and independent process/Original-lock proof. All four Large claims
remain consumed; previous failures and charges retain their original scope.
Scale uses injected File/OPFS handles and does not establish actual dialogs.

The [final-package eight-case record](releases/0.2.0-final-package-smoke-acceptance.json)
separately records actual Windows dialogs and ordinary filesystem cancellation
and recovery: native processing/export Cancel, plus Chrome/Edge processing/export
Cancel and preserved-baseline malformed-input/retry. Earlier successful actual
exports and selected CLI filesystem controls retain their exact scope. Edge
processing Cancel occurred during active preparation; partial browser output
without a marker remains distinct from native atomic publication. These proofs
support the selected #87/#103–#105 claims, not device faults, arbitrary workloads,
RSS, general performance or other platforms. Exact local delivery passed at `3f02e85` through matched Linux/native Windows
gates. Owner publication approval and subsequent served-app verification remain
required.

## Native experimental plain publication (2026-11-05)

The [feature delivery record](performance.md#native-experimental-plain-publication-delivery-2026-11-05)
contains fresh Linux default/all-feature checks and native Windows release feature
contracts plus a packaged CLI smoke. Coverage includes seeded byte/manifest parity,
independently parsed multiline Unicode rows, strict caps, one-file/partial-batch
capacity, and cancellation/shared-denial cleanup after output begins. This
validates the native opt-in path on those fixtures; it adds no default/Auto policy,
browser throughput, universal admission or RSS claim. The initial Windows runner
artifact-path failure remains incomplete beside the successful fresh batch.

## Execution graph main integration (2026-11-05)

The [merged-source investigation](performance/investigations/execution-graph-merged-source-correctness-2026-11-05.md)
and [structured receipt](evidence-originals.md#sha256-c1bd573196f9b3cc545246f760b9609606dc4485ec39b9f3984fec29bc19f055)
record current Linux/WSL native/UI/portable checks, bundled Chromium graph and
termination checks, both resource variants and test-free production restoration.
They are developer correctness checks, separate from the earlier build's overhead
acceptance. The first hosted plan's helper-input limitation is explicit. Native
Windows/macOS and installed Chrome/Edge were not run; no local-CI landing receipt
or origin push is claimed.

## Integrated hosted graph acceptance (2026-11-05)

Issue [#58](history/prior-issues.md#issue-58) completes the local
acceptance gates for [#48](history/prior-issues.md#issue-48).
The [path inventory and bounds](execution-graph-acceptance.md),
[validation receipt](benchmarks/execution-graph-validation-summary-2026-11-05.json)
and [126-job result](evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830)
retain source/build/browser identities and original log/raw locators.

The source-matched hosted campaign passes 42 production graph parity families,
16 direct lifecycle cases, both inspection workloads, focused bounds/cancellation,
16 composed gzip/partition/uniform lifecycle cases, 35 existing browser cases,
bridge/cleanup and all temporary/persistent/process-kill termination modes,
including direct and composed codec/operation paths. Independent readers verify
literal fields/IDs, memberships, seeded order, strict CSV caps, manifest records
and valid markers. Processing interruption preserves confirmed work; omitted
terminal facts do not become successful outcomes. A regression found during the
interrupted first timing cohort now preserves the newest attempt's last observed
rows/bytes/time after local shutdown, with earlier completed totals separate.
Actual terminal measurements still take precedence.

Focused synthetic saturation supplements a real public Run; it does not replace
strategy execution evidence. It retains 1156 cards, 128 significant events and
one queued message, with explicit clipping. The observed logical-value census is
14,651,007 bytes and serialized snapshot content 3,108,261 bytes, within their
32 MiB/4 MiB envelopes. Cancellation of a real 32 MiB Run while observation
acknowledgement is withheld takes about 463 ms in the recorded case and publishes
no destination output/marker. JS/container/backend overhead is outside the
logical census; these are not heap/RSS caps or tail responsiveness guarantees.
Native and both isolated WASI resource reactors verify optional 8192-byte
admission/denial, 65536-record saturation/omission and callback-grant release.

Linux x86_64 source-matched native checks pass formatting, all-target workspace
Clippy, 368 default locked Rust tests across 19 suites and 64 UI tests. Retained
433 all-feature tests/Clippy and portable-core WASM checks have unchanged relevant
Rust/core/vendor/embedded-asset identities; their earlier broad source snapshot
predates only the separately tested hosted counter-label correction. Hosted
checks use Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled Chromium 156.0.8078.4.
Default production artifacts are restored after resource/experimental tests,
with test-only WASM entry points, prototype HTML and test assets excluded; the
native embedded executable is rebuilt. Current Python analysis/provenance,
CI-routing and evidence-integrity regression checks pass separately.

All 126 eligible complete hosted Runs pass exact cross-mode/cohort output parity
and all eight <=5% median/conditional-upper95 overhead gates. Direct/resident
use six matched blocks, high-cardinality twelve, external merge eighteen. The
actual running Headless Shell executable/version/hash is attested per block.
Six/twelve-block resampling is exact; eighteen-block Monte Carlo uses a
conservative numerical-error bound and fixed recorded PRNG implementation.
The earlier unmet 72/108-job reports and slow observations remain retained.
Precision studies were selected after unmet gates: no population/tail or
optional-stopping-adjusted confidence claim follows. Native Windows/macOS
performance, exhaustive compositions and deployment remain unestablished here.

## Advanced hosted graph inspection (2026-11-05)

Issue [#57](history/prior-issues.md#issue-57) adds one shared
keyboard-operable step presentation, bidirectional configured-operation mapping,
default/advanced detail and a bounded significant-event history captured before
worker delivery coalescing. The [observation contract](execution-observation.md#advanced-inspection-and-significant-events)
owns the 128-event/2312-byte-mask, serialization, page and DOM envelopes. The
existing 4 MiB message and 32 MiB logical payload envelopes remain unchanged;
these are not browser heap/RSS limits.

The public inspection harness uses real workers, production WASI and OPFS for
fused partition/uniform work and 100000 rows across 64 parent groups followed by
Fisher–Yates. Independently read CSVs conserve literal IDs and group membership,
satisfy strict caps and agree with manifests and valid markers. Actual updates
after a test-only pause preserve focused button identity, card position relative
to the viewport and scroll offset. Checks cover collapsed event capture, fused
operation mappings, event navigation, shared graph/list selection, supporting
work, frozen limits after edits and retained history through real Analyze,
Prepare and cancellation. Targeted 1280px and 390px default/advanced screenshots
were visually inspected for readability; they supplement semantic checks.

Linux x86_64 native validation passes format, workspace/all-target Clippy, 368
locked workspace tests across 19 suites and 64 UI tests, using Rust 1.99.1 /
Node 22.23.4. Hosted checks use WASI SDK 33 and bundled Chromium 156.0.8078.4.
The initial hosted attempt retains its rendering-fault fixture failure: the new
renderer updates frozen flow only at Run replacement, so the ordinary render
fault now targets the current note update after cards exist. The focused fault
case passes and confirms explicit observation unavailability without CSV failure.
A subsequent combined attempt showed that a replacement Run first retires old
history; arming the fault only after the actual Run request prevents injection
into that prior history. Both failed harness attempts remain recorded. The older page smoke test now
focuses the selectable native step button instead of its former focusable list
container; its focused rerun passes with the same keyboard-focus assertion.

The final full hosted batch passes all 42 graph parity families, 16 lifecycle
cases, both inspection workloads, 35 existing browser cases, bridge, cleanup and
all temporary/persistent/process-kill termination modes. Default production
artifacts and the native embedded executable are rebuilt after hosted checks.

Both review axes found the still-zero-event ownership documentation stale; it is
updated with the new fixed prefix, copies, masks, lifetime, explicit saturation
and command routing. Neither axis found another functional defect or actionable
smell. Focused observable-state tests saturate event capture while delivery has
no credit, deduplicate repeated work, retain chronological events/omissions on the
page and label clipped configuration. Final composed resource/cancellation and
representative long-job overhead acceptance remain #58; these fixtures alone do
not establish comparative performance, broad scale or another platform.

## Interrupted and degraded execution observation (2026-11-05)

Issue [#56](history/prior-issues.md#issue-56) preserves confirmed
work across shutdown and guards asynchronous cleanup against replacement Runs.
The [observation contract](execution-observation.md#interrupted-and-degraded-observation)
owns stale-message, attribution and bounded degradation behavior.

Linux x86_64 checks use Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled
Chromium 156.0.8078.4. Format, workspace/all-target Clippy, 368 default locked
workspace tests across 19 suites and 61 UI tests pass. All-feature Clippy and 433
locked workspace tests across 19 suites pass as well. Two experimental test
fixtures needed correction: the composite-key denial case retains its exact
quarter-workspace boundary with enough room for current inline sorter metadata;
the corrupt-v1 merge case explicitly constructs a v1 run instead of being rejected
by the optional compact-spill constructor before reaching merge. Their denial,
partial-row-visit and owner-release assertions remain intact. No algorithm or
budget policy changes follow.

The lifecycle harness's sixteen real hosted Run cases independently inspect
destination CSVs, manifests and v1 markers. It covers processing/worker failure,
writer closure, marker write/close/readback, cancellation around confirmation,
late actual marker facts and a replacement Run, observer transport/loss/render
faults and success/cancel cleanup errors. Its faults are test-only worker routes.
The initial combined run exposed a wrapper mode tied to worker construction;
workers started for column loading may be reused. Assigning the mode to the
actual Run request fixes the fixture. The failed attempt is retained separately.

All 42 graph parity families, the existing 35 browser cases, bridge, cleanup and
temporary/persistent/process-kill termination modes pass. The generated native
bundle is rebuilt. Default production packaging and the embedded executable are
rebuilt separately after hosted checks. Resource-denial reactor coverage is retained
from the prior slice; final composed resource acceptance remains #58.

The two-axis review found no documented standards violation. Its spec review
found a stale success-cleanup continuation that could overwrite a replacement
Run; success and overlapping cancellation now check captured generations after
awaits, with deterministic success/error regression cases. Native tests also
cover attributable prepared input/snapshot/materialization failures and exact
partial counts. These fixture checks do not establish scale, RSS, physical-I/O,
Windows/macOS or the representative comparative-overhead gate, which remains #58.

## Codec execution graph (2026-11-05)

Issue [#55](history/prior-issues.md#issue-55) adds actual input
adaptation, output compressor and ZIP assembly observations. Decoded input bytes
are measured before text decoding; compressor counts are encoded CSV bytes;
archive bytes/counts describe the outer container. Output codec work maps to the
final operation. The [observation contract](execution-observation.md#compressed-input-and-output)
and [ownership audit](resource-policy-research.md#hosted-codec-observation-ownership-2026-11-05)
record scopes and retained bounds.

Eleven real hosted codec fixtures cover gzip, Zstandard and ZIP input/output,
explicit ZIP member selection among multiple CSVs, signature detection despite
CSV filenames, UTF-16/BOM gzip input, prepared partition/uniform output, corrupted
gzip and ambiguous ZIP failure. Independent Node gzip, Python 3.14.4 ZIP and
system Zstandard 1.5.7 decoding checks CSV contents/caps, manifests, ZIP member and
outer archive bytes, actual saved-file marker counts and observing-disabled
parity. The independent library path/hash and failed/debug attempts are retained
with task-owned validation records; engine codec pins/backends remain unchanged.

Native regressions verify codec byte scopes, archive entries/provenance, exact
CSV/compressed parity after callback rejection, attributed checksum failure with
unchanged error placement, and cancellation at real input/output codec boundaries.
A denied archive constructor reports failure before file creation and releases
all working capacity. The two-axis review identified archive construction outside
the observed lifetime and a false raw-CSV archive dependency; both are fixed and
covered. Duplicate output-write observation policy was consolidated.

Linux x86_64 validation uses Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled
Chromium 156.0.8078.4. Format, workspace/all-target Clippy, 361 locked workspace
tests across 19 suites and 53 UI tests pass. All 42 graph fixtures, the existing
35 browser cases, bridge/cleanup and all documented termination modes pass. The
first full hosted attempt retained a fixture import race as an incomplete batch;
the corrected fresh-import wait passed in a new frozen attempt. Base and isolated experimental-shuffle-partition resource contracts pass. The
first experimental build exposed stale test-only reader callers; all affected
callers were corrected, and an all-target/all-feature workspace compile check
passes without enabling experiments in production. Default production artifacts
are restored and pass test-only packaging exclusions. The final codec UI recheck
and native embedded-asset rebuild pass after the unit-label correction. No native Windows/macOS, broad scale,
RSS, physical-I/O or comparative-overhead claim follows; #58 retains the final
combined acceptance gates.

## Balanced and interleaved execution graph (2026-11-05)

Issue [#54](history/prior-issues.md#issue-54) distinguishes shared
balanced frame scans/child metadata, terminal consecutive emission, fused sorted
traversal and inclusive interleaved membership. Existing exact-group caps and
seeded domains remain unchanged. The [observation contract](execution-observation.md)
owns units, original operation mappings and fixed per-parent summary bounds.

Thirteen hosted split fixtures use real workers, production WASI and OPFS, with
collection enabled/disabled. Independently read CSVs verify literal consecutive,
alternating, nested and preceding-parent memberships/lineage; separate real Run
prefix controls verify fused traversal order and exact child sizes. Cases cover
shared ranges followed by shuffle, repeated parent ranges, standalone/fused
terminal emission, strict row/byte caps, insufficient rows and impossible caps.
Failure runs await owned worker termination before starting the next comparison.
The harness also waits for operation-count import completion when matched prefix
controls intentionally share a seed. These are fixture synchronization checks,
not new production lifecycle behavior.

Focused native regressions verify shared metadata writes zero framed rows,
actual counts and fused source/index mapping. Cancellation at shared-range start
preserves completed input, reports interruption and cleans private output. The
two-axis review found no documented standards violation; its optional duplicated
kind mapping was consolidated. Independent combined membership checks, batched
live progress and per-parent omission accounting address the spec review concerns.

Linux x86_64 validation uses Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled
Chromium 156.0.8078.4. Format, workspace/all-target Clippy, 354 locked workspace
tests across 19 suites and 51 UI tests pass; the generated UI and embedded native
executable are rebuilt. All 31 graph fixtures, 35 existing browser cases, bridge,
cleanup and temporary/persistent/process-kill termination modes pass. Default
production artifacts are restored with test-only packaging exclusions checked.
The existing inline/schema envelopes are unchanged; this slice does not add scale, RSS, physical-I/O, Windows/macOS or
comparative-overhead acceptance. The final combined gates remain #58.

## Allocation and stratification execution graph (2026-11-05)

Issue [#53](history/prior-issues.md#issue-53) observes exact and
probabilistic membership, exact strata work and actual intermediate Dataset
producers. Requested percentages remain distinct from observed memberships.
No stratum values enter observations. The [observation contract](execution-observation.md)
records the expanded fixed role and membership envelopes.

Linux x86_64 validation uses Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled
Chromium 156.0.8078.4. Format, workspace/all-target Clippy, 349 locked workspace
tests across 19 suites and 51 UI tests pass. The generated native bundle and
embedded executable are rebuilt. Focused regressions compare quotas, empty groups,
rounding and CSV parity for exact/probabilistic allocation with/without strata;
an actual sorter admission failure is attributed as failed and releases all grants.

Seven real hosted allocation fixtures cover standalone membership, strata,
following uniform shuffle, preceding partition parents and downstream shuffle.
Independent CSV/manifest reads verify named counts, zero quota and rounding,
strict row/CSV-byte caps and observing-disabled parity. Graph checks verify
original operation mappings and actual intermediate producer edges. These cases
join the previous 11 fixture families. The two-axis review found missing parent
producer edges and failure attribution during probabilistic push; both were fixed
and covered by the focused checks above. Snapshot count arrays are copied.

The existing 35 browser cases, bridge/cleanup and all temporary, persistent and
process-kill termination modes pass. Both the base and isolated experimental
resource reactors pass with the enlarged inline/serialization envelopes; no
experimental feature is promoted. Default production packaging is restored and
checked for test-only asset/entry-point exclusion. There is no
new native Windows/macOS, scale, RSS, physical-I/O or performance acceptance claim;
the representative overhead gate remains #58.

## External execution graph and ordered-file reuse (2026-11-05)

Issue [#52](history/prior-issues.md#issue-52) adds observation at
real spill, materialized merge, hierarchical merge and final traversal boundaries.
Grouping handoff retains ordered files as explicit reuse inputs. Run provenance
comes from the actual consumed SortRun catalog, not historical sorter counters.
The [observation contract](execution-observation.md) owns capacities and metrics.

Validation used Linux x86_64, Rust 1.99.1, Node 22.23.4, WASI SDK 33 and bundled
Chromium 156.0.8078.4. The durable validation runner records complete source/vendor/
embedded-asset identities, commands, full logs, exit codes and per-attempt status.
New runs use the toolchain's real Cargo executable; the initial attempt that
resolved Cargo's proxy to rustup is preserved as a launcher failure, not a code
failure or an omitted pass.

Passed native checks include format, workspace/all-target Clippy and 347 locked
workspace tests across 19 suites. All 48 UI tests passed, including the expanded
576-slot envelope, separate handed-off/failed outcomes and duplicate terminal
attempt handling. The native executable was rebuilt with its generated UI.

The real hosted Run suite now includes 11 fixture families, each with observing
and non-observing CSV/manifest parity. New fixtures are 80,000 narrow rows forcing
spills; 40,000 rows with late keys forcing grouping handoff and reuse; and 12
rows with 1,800,000-byte key prefixes forcing small fan-in and multiple merge
levels at 32 MiB, with a 2 MiB record/CSV cap. Independently read CSVs conserve
IDs and satisfy row/encoded-byte caps; output records, logical digests and valid
completion markers agree. These fixtures establish those paths, not generic
larger-than-memory throughput or broad scale certification.

Focused native regressions check that final traversal references its actual
materialized runs rather than already-consumed ancestors, cancellation remains
interrupted while preserving completed spills, and a corrupted intermediate
merge reports two measured partial row visits as an attributed failure. Private
output and temporary owners retain their existing cleanup behavior. The base
and isolated experimental-shuffle-partition resource reactors retain the common
admission/saturation checks; experimental features are validation-only and are
not enabled to manufacture production observation coverage.

The existing 35 browser cases, bridge/peer cleanup and all documented temporary,
persistent and process-kill termination modes also pass. Default production
artifacts are restored afterward and retain the test-only asset/entry-point
exclusions. Windows/macOS, physical-I/O/RSS and comparative-overhead claims remain
unestablished for this slice; final overhead acceptance belongs to #58.

The two-axis review identified cancellation classification, historical rather
than consumed-run dependency attribution, and lost partial metrics on intermediate
merge failure. All three were corrected with the regressions above. Native error
text remains unchanged; an internal cancellation type avoids string-based graph
inference. Catalog admission uses the updated entry layout, and inline observation
state never retains an optional callback grant during required work.

## Prepared hosted execution graph (2026-11-04)

Issue [#51](history/prior-issues.md#issue-51), stacked on the
limits-only slice, observes the real internal-preparation route for partitioning
and resident shuffles. The [observation contract](execution-observation.md) owns
its fixed bounds and incomplete coverage. Validation used Linux x86_64, Rust
1.99.1, Node 22.23.4, WASI SDK 33 and bundled Chromium 156.0.8078.4. No native
Windows/macOS, external-destination, broad scale or overhead claim is added.

Passed checks:

- Format and workspace/all-target Clippy with warnings denied; full locked Rust
  workspace suite: 343 tests across 19 suites. Focused native tests compare capped
  CSV output when prepared observation rejects delivery, check original fusion
  mappings/final-output mapping, and cancel at a real child Fisher–Yates boundary
  while retaining completed input facts and cleaning private output.
- All 46 UI tests, TypeScript/native bundle generation and rebuilding the native
  executable with that embedded UI. Focused histories cover repeated summaries,
  separate completed/interrupted outcomes, unsafe counters, 144-category
  saturation and the existing generation/coalescing/marker regressions. Submission
  tests mutate caller configuration during asynchronous setup and verify that
  the worker receives the original request snapshot.
- `node scripts/test-browser-graph.mjs`: eight public-page Run fixtures, each with
  observation enabled and disabled using real processing/storage workers, WASI
  and OPFS. Cases cover direct → prepared history replacement, partitioning,
  uniform comparison sort, explicit Fisher–Yates, exact partition/uniform fusion,
  initial and later uniform-shuffle elision and repeated child-group shuffles.
  Independent reads compare exact CSV files, row membership, output manifest
  records and logical digests, enforce two-row/20-byte caps, and validate marker
  file counts. Fixtures use 32 MiB and 1 MiB maximum records. Serialization cards
  are checked against only the final operation number. This command is routed
  into hosted CI and AGENTS.md's acceptance sequence.
- The existing 35-case production browser suite, bridge and peer-cleanup checks,
  temporary/persistent termination, persistent process-kill and direct persistent
  process-kill modes passed. These retain their existing workload/platform limits.
- Base and experimental-shuffle-partition WASI resource variants passed. New
  contracts verify the exact 65,536 ordinary-record plus one-omission cap,
  fixed inline record/span envelopes, transactional denial with 8191 bytes
  available, sink rejection, continued context health and callback-grant release.
- Default production engine/hosted packaging restored after resource builds;
  test-only entry-point and asset exclusions retained. Graphify refreshed with
  code-only extraction and no model backend.

The two-axis review found missing later-span elisions, conflated completed and
interrupted summaries, an absent prepared-export source link, incomplete transition
assertions and missing CI routing. These were corrected with focused regressions.
Producer-assigned wire IDs replaced TypeScript's duplicated enum-position
calculation. During fixture development, a tiny partition initially expected routed
work but actually selected resident sorting; the fixture now checks the selected
path rather than changing execution selection. An asynchronous import race was
fixed by waiting for the imported fixture seed before submitting Run.

These are correctness, ownership and lifecycle checks. No comparative performance
measurement was run, and neither representative long-running 5% overhead acceptance
nor complete external sort/fallback/reuse, allocation/split/codec graphs are
established. Repeated-work saturation is tested at bounded producer/state seams;
small hosted fixtures do not establish large-cardinality browser performance.

## Limits-only hosted execution graph (2026-11-03)

Issue [#50](history/prior-issues.md#issue-50) adds the first
production observation slice described by the [scope and ownership
contract](execution-observation.md). Validation used Linux x86_64, Rust 1.99.1,
Node 22.23.4, WASI SDK 33 and bundled Chromium 156.0.8078.4 in disposable OPFS
contexts. This does not establish native Windows/macOS graph coverage, external
destination faults, larger-than-memory graph scale or the parent's representative
long-running overhead target. Other pipeline/codec graphs remain later slices.

Passed checks:

- Rust format and workspace/all-target Clippy with warnings denied; the full
  locked workspace suite (340 tests across 19 suites), plus the final focused
  observation grant contract after extending its later-denial assertion.
- All 41 UI tests, TypeScript checking, native UI regeneration and rebuilding
  the native executable with that embedded bundle.
- Production hosted build and all 35 browser acceptance cases. The page Run
  case keeps the panel collapsed during collection, checks four observed steps,
  keyboard focus and frozen flow, then independently reads fixed-seed exports:
  two CSVs of exactly 11 bytes with one data row each, manifest and a valid
  marker counting all three result files. A second public Run disables only
  telemetry at the worker request boundary and compares exact CSVs, configuration,
  logical digest and completion marker through real workers/WASI/OPFS/export.
- Bridge and peer-cleanup harnesses; termination in temporary and persistent
  contexts, persistent process-kill mode and persistent direct process-kill mode.
  Direct termination was rerun after the final export-adapter changes.
- Base WASI resource contracts and the isolated experimental-shuffle-partition
  resource suite. The optional observer contract checks 8191-byte denial,
  serialization grant release, later denial and continued context health. The
  real OPFS export resource fixture checks saved-and-closed file counts, marker
  confirmation and attributed write/close/marker failures with observation on.
- Default production WASM and hosted packaging restored after resource builds;
  test assets removed and the existing production entry-point guard retained.
  Code-only Graphify extraction refreshed without a model backend.

Initial checks exposed a missing Playwright browser binary (installed), the new
resource fixture's native temporary-directory default in WASI (changed to /tmp),
and a page-test race reading the previous COMPLETE state before a replacement
Run finished (changed to wait for its new result path). Marker observation now
reuses its existing handle, preserving the one-marker-acquisition export check.
A later grant-test extension had a moved-reservation compile error, corrected
before rerunning it and both WASI resource variants. No runtime contract was
weakened to pass those checks.

The two-axis code review identified optional grant retention and duplicated Run
dispatch, plus missing export-failure attribution, unknown-marker retention,
unavailable-stream reporting, frozen flow on denial and hosted enabled/disabled
parity. These were corrected with focused regressions and the checks above.
The grant now covers emission only, with no optional capacity retained while
mandatory CSV work resumes. No new dispatch eligibility, algorithm, seeded,
strict-cap or publication contract is introduced.

## PR 22 CI follow-up (2026-11-01)

A subsequent duplicate CI run reached persistent termination and failed while
reading a destination entry. The matching one-CPU Linux run reproduced it on its
first attempt; failure-only instrumentation identified `getFile()` on
`CHOPPER-COMPLETE.json.crswap`, a Chromium writer staging entry removed during
termination. The destination observer now tolerates only `NotFoundError` for
recognized writer-swap names. Observable pending payloads, committed result
bytes/counts and marker semantics retain their existing checks. Injected read
failures against real OPFS entries verify that real-result loss, an unrecognized
swap name and non-NotFound swap errors still fail. Production workers/export code
are unchanged. Failed and superseded diagnostic attempts remain in `scratch/pr22-*`;
they are not counted as successful acceptance runs.
The final narrow observer passes eight persistent-profile Linux one-CPU runs,
plus ordinary termination, forced persistent-browser process kill, and forced
process kill with direct Run. Each includes the negative observer controls and
the existing success, restart, closed-output hash and marker assertions, using
bundled Chromium 156.0.8078.4 and Node 22.23.4.

The browser cleanup contract reproduced the CI `afterTabExit` count of zero on
Linux/Chromium 156.0.8078.4 under one-CPU stress. A failure-only diagnostic trace
showed the tab workspace was enumerated but its `ifAvailable` lock request was
declined after the test's lock-query snapshot reported no owner. A subsequent
request acquired it; its sentinel remained intact. The harness now waits for one
bounded queued acquisition/release after worker termination and tab close before
asserting cleanup. Production cleanup and all active-owner/unrelated-data
preservation and exact deletion-count assertions are unchanged.

The fixed contract passes 40 consecutive Linux one-CPU repetitions with Node
22.23.4 and bundled Chromium 156.0.8078.4, plus a native Windows bundled-Chromium
pass. This covers Web Locks/OPFS cleanup synchronization, not WASM execution,
aggregate memory, performance or broader browser acceptance. Original CI logs,
local failures/diagnostics and successful repetitions remain in ignored
`scratch/pr22-*` paths.

The evidence failure was stale generated navigation, not failed archive access:
CI had already verified all 655 originals. Local authenticated hydration now
provides the same hash-verified cache. Catalog/index and the maintained derived
coverage audit were regenerated with explicit classifications for the two new
sections; original raw evidence and the strict section-drift check remain intact.
The audit script now has pinned LF bytes for reproducible source hashes. Catalog
and coverage checks, their four/six parser/resolver tests, and the unchanged
38-cell numerical checker pass. The legacy numerical checker ran against exact
resolved originals in ignored scratch, keeping confidential aliases out of the
public working tree.

## Browser OPFS workspace deletion conflict

The [browser cleanup contract](../scripts/test-browser-cleanup.mjs) exercises a
same-origin worker with an open OPFS sync access handle inside an otherwise
abandoned workspace. The cleaner can take the Chopper Web Lock, but Chromium
rejects recursive workspace deletion with `NoModificationAllowedError`. The
production sweep removes a separate abandoned workspace, reports one remaining,
and preserves the occupied workspace and its sentinel. After the worker closes
the handle, the production retry removes the last abandoned workspace.

The harness uses a disposable browser context and real OPFS methods for this
case. It also retains the active-owner and injected UI retry controls. This
covers the Chromium lock conflict. Filesystem permission changes, hardware
failure and power loss have separate acceptance requirements.

## Browser OPFS selected destination removal

The [destination control](../scripts/test-browser-quota.mjs) removes a selected
OPFS directory through the real origin root in disposable bundled Chromium.
Production Run reports the resulting `NotFoundError` before any output writes.
The root inventory and workspace retirement confirm the failed Run left no
output or marker. Reselecting an OPFS parent in the same page produces exact
capped CSVs, the manifest and a valid completion marker. The picker returns
a real OPFS handle through the test fixture. Installed pickers and physical
device faults have their own acceptance requirements.

## First workload baseline harness (2026-10-31)

The [baseline slice](maintainer/workload-baselines.md) passes 14 small Python controls for
deterministic generation, CSV edge fields, field/order/lineage corruption, missing
empty arms, browser markers, caps/chunk boundaries, isolated runtime plans,
artifact/build matching and seeded parity. UI source and the new browser test
entry pass TypeScript checks.

Fresh default native Windows and WASI SDK 33 builds run two jobs on the same
2,000-row, 298,027-byte generated entity list: ordered 4,096-byte-capped export
(76 CSV files), and region partition -> probabilistic 80/20 allocation -> child
uniform shuffle (16 outputs). Both native and fresh persistent Chrome
156.0.8078.48 pass independent checks and same-version seeded CSV/lineage parity.
Browser output uses an OPFS-backed picker with completion markers, not a native
File System Access performance measurement. No engine source or default changes.

Local manifests, toolchain/source/artifact identities, logs and checks are retained
under `scratch/workload-baseline-final/`; no claim of public evidence hosting or
private archive upload is made. An earlier ordered verifier attempt under
`scratch/workload-baseline-smoke/` failed because Python's default writer omits
empty-field quotes. Its independent encoder was corrected and the failed logs
remain. Follow-up v2 and final passes are distinct attempts, not extra samples of
one performance experiment. The missing SDK prerequisite was resolved by a
SHA-256-verified WASI SDK 33 installation in ignored tooling storage.

These are small correctness/harness controls. They do not prove probability laws,
add a large-scale verifier, compare candidate speed, exercise full-scale spill
boundaries or extend platform/runtime support beyond the recorded cases. Archive
selected local evidence under the existing policy before cleanup.

## Portable Progress phase ownership (2026-10-28)

Windows MSVC Rust 1.99.1 passes formatting, default/all-feature workspace Clippy
with warnings denied, and 332 default / 397 all-feature locked workspace tests
including doctests. The portable reactor contains local/shared minus-one/exact/
plus-one owner edges, actual String/controller accounting, static and shared
clones, Unicode/decimal stack formatting, competition/retry, denied callback/cache
preservation and Context teardown. Native controls additionally cover concurrent
final drops and independent cached source/HTTP response lifetimes.

Real preparation emits the exact admitted formatted operation phase. Real profile
completion borrows static text. Both real prepared/direct publication paths deliver
static Complete after the commit hook exhausts shared admission and sets
cancellation, preserving successful output counts. Existing workspace controls
retain failure/cancellation/cleanup and optional-path coverage.

Windows WASI SDK 33 / wasm32-wasip1 and bundled Chromium 156.0.8078.4 pass
35 hosted correctness cases, bridge, cleanup, temporary/persistent interruption,
forced process termination/recovery (including direct publication), and base plus
shuffle-partition resource reactors. Both reactors execute the Progress controls
on wasm32 layout, including the real formatted event and both actual postcommit
Complete producers. Default production engine/package restoration passes and
removes test assets; production export rejection remains enabled. An initial
reactor attempt exposed the new fixture's omitted temporary parent (WASI does
not support default temp-path discovery); explicit fixture parents fix that
attempt, which remains retained with full logs. See the
[ownership scope](resource-policy-research.md#portable-progress-phase-ownership-2026-10-28).
This slice does not admit caller-owned decoding or CLI/WASI framing, prove total
RSS bounds, or extend scale, Linux/macOS or device coverage. No portable-core
source changed in this slice, so no new core-only WASM check is claimed.

## Native static status source (2026-10-28)

Native server status now uses static text instead of a retained String. The
[ownership contract](resource-policy-research.md#native-static-status-source-2026-10-28)
records the fixed vocabulary, unchanged JSON and remaining error/progress gaps.
Windows MSVC Rust 1.99.1 passes formatting, default workspace Clippy with warnings
denied, 323 locked default workspace tests including doctests, and 26 focused
native server tests. The added interface control covers every status, response
denial preserving status, unlocked state and retained response snapshots after
replacement. The real HTTP zero-pool cancellation control now begins ready and
verifies cancellation state/flag as well as the allocation-free acknowledgement.
Existing server tests cover local/shared capacity edges, competing owners and
release/retry, cached source replacement, response abandonment and error fallback.
Static status itself has no heap capacity or reservation contention to test.

`scratch/state-status-source-2026-10-28/` retains the declared source/vendor/input
identities, toolchain/deadline plan, all logs and final SHA-256 report. Failed
attempts retain a test type-qualification error and a needless-borrow Clippy error;
the final four-step batch passes. Code-only Graphify refresh exits 0 (the first
nested PowerShell redirection reported stderr as a shell error after writing the
graph; its log is preserved). Native `server` is excluded on WASI, so hosted/UI
and optional-feature/platform expansion were not run. Existing production hosted
artifacts and earlier validation claims are unchanged. This removes only status
source allocation; it establishes no complete state/runtime or RSS bound.

## Native cached output-path ownership (2026-10-28)

Analyze and direct Run now independently admit the cached state output String
before state replacement or worker launch. String/null wire representation and
job schema/defaults/strategies are unchanged. The
[ownership contract](resource-policy-research.md#native-cached-output-path-source-owner-2026-10-28)
describes the narrow scope and remaining allocation gaps.

Windows MSVC Rust 1.99.1 passes formatting, default workspace Clippy with warnings
denied, 321 locked default workspace tests (including doctests) and two focused
state-output tests. The
focused controls cover empty/Unicode/long paths, local/shared capacity edges,
independent competing owners, denial/retry, cached-state preservation,
cancellation retention and response-reader lifetime after state replacement.
Existing response tests also exercise a populated prepared/profile state with
the admitted output source. Code-only Graphify was refreshed.

Local `scratch/state-output-owner-2026-10-28/` retains declared-input/deadline plans,
full logs, runner identities and final SHA-256 report. The initial attempt retains
its failed legacy response-fixture compile and incorrectly targeted binary test
invocation (zero tests); the corrected library-target batch passes all four steps.
Only native server code changed (`server` is excluded on WASI), so no hosted/UI
rebuild or optional-feature/platform expansion was run for this slice. Existing
hosted production artifacts were preserved. This is working-allocation coverage
for one cached source, not a complete state/runtime or RSS bound.

## Reproducibility and opt-in automatic memory (2026-10-28)

CLI/app reproducibility controls retain the effective seed and algorithm version.
The app persists generated seeds across Run, exact preparation and configuration
export. Opt-in `memory_mb: "auto"` resolves against currently free shared tracked
capacity; omitted memory remains numeric 256. Requested configuration stays
immutable and distinct from effective Analysis memory/workers. No Auto default,
experimental strategy or speed selector is promoted.

The frozen Windows batch `.tools/todo-auto-20261028/` retains plans, full logs,
toolchains, attempts, corrections and complete source/vendor identities.
`final-acceptance.json` combines 34 passing final gates; original failed or
incomplete attempts remain in their original phases. Default/all-feature locked
workspace tests pass (319/384 including doctests), as do both Clippy configurations,
formatting, portable-core WASM, 37 UI tests and native bundle generation.

Coverage includes strict scalar decoding/defaults, typed request grants, CLI/import
precedence and policy conflicts, byte-boundary resolution, live owners/pressure,
denial/retry/cleanup, prepared execution without re-resolution, requested/effective
manifests and seeded parity across numeric/Auto budgets and worker counts. Analysis
version reporting shares static literals and is covered by manifest admission.

Bundled Chromium 156.0.8078.4 passes 35 standard checks, including real-page Auto
selection, seed reuse, export/reimport, manifest values and native/WASI golden
output. Bridge/cleanup and all temporary, persistent and process-kill interruption
modes pass, including direct Run. Both base and shuffle-partition resource reactors
pass automatic ledger, numeric preservation, direct admission and owner-release
contracts. These contract durations are not performance comparisons.

Corrections preserve the failed Clippy borrow check, invalid old test resource
combinations, codec format limits accidentally derived from injected reservation
ceilings, and an internal WASI fixture requesting two workers. Numeric codec limits
again use nominal requested memory; Auto uses its resolved budget. Feature-only
fixture corrections reuse matching default behavior and rerun affected feature
checks; the WASI fixture correction also reruns native publication metadata.

The final default engine and seven-asset test-free hosted package pass production
export inspection. `source/package-proof.json`, `final-source-identities.json` and
`installed-package.json` identify the checked and locally installed artifact.
No deployment occurred. Current Linux/macOS, installed Chrome/Edge, other devices,
external picker/destination, scale and physical-I/O acceptance are not established
by this Windows/bundled-Chromium batch. E4/E5 and omitted-mode promotion remain
separate work.

## Limits-only direct Run (2026-10-27)

Run now validates and writes limits-only seeded-policy jobs directly into private
publication output, sharing encoded chunk/cap decisions with exact preparation.
All current input/output codecs are supported. Nonempty pipelines and flexible
policies select existing preparation/execution before input consumption. Direct
errors never retry raw input. Explicit preparation and prepared confirmation remain.
This does not promote Auto strategies or automatic resource sizing.

Raw source/tool identities, plans, complete logs, attempts, corrections, summaries
and built artifacts are retained under `.tools/todo-direct-20261027/`. Original
source bytes are sealed before corrections; `final-source-identities.json` and
the final comparison verify current maintained build sources/full vendors against
the checked copy. The portable core is unchanged and reuses the matching WASM
check identified in the preceding checkpoint.

Windows checks pass: formatting, locked default/all-feature workspace Clippy with
warnings denied, and locked workspace tests (302/367 including doctests). The
focused direct contracts cover field/order/digest/filename/manifest parity,
UTF-16/BOM and strict caps, late-wide/invalid/codec failures, local/shared denial
and owner release/retry, cancellation, source changes, destination races and
all-codec execution under a 4 KiB temp limit without an encoded CSV snapshot.
UI unit tests (29) and generated native build pass. A subsequent HTML correction
does not change engine sources: affected native interfaces (eight each in default
and all-feature configurations), embedded controls and both Clippy configurations
were rechecked, and corrected native binaries are retained separately.

Bundled Chromium 156.0.8078.4 passes 32 standard checks, including actual hosted
page Run submission/export, direct/prepared parity, codec roundtrips, fallback,
late failure and cancellation. Bridge/peer cleanup and all prepared temporary,
persistent and forced-process interruption modes pass. The additional direct
persistent/process-kill pass covers ten cancellation/tab-close cases and five
abrupt-restart checkpoints through input processing, CSV writes and marker
write/close, preserving committed exports and completing a fresh retry.
Base and shuffle-partition WASI resource reactors also pass direct local/shared
denial/retry, final-clone release and cleanup assertions.

Failed controls remain retained: an exact-fit 21-byte fixture incorrectly expected
three files rather than two; markup initially omitted the Run control; and new
cancellation-test edits inspected the wrong workspace folder. The corrected native
embedding/real-page controls and final full browser suite pass. These were not
discarded or counted as passes. `summary.json`, `corrections/` and the numbered
logs separate original failures from affected reruns.

The final default WASI build and seven-asset test-free hosted package pass the
production export guard. `source/package-proof.json` records engine SHA256
`164c69bc9de1b6e73a036c6fe088f332e1ab9ebe97d72bbb6832bb13607f3db4`.
The validated package is restored to local `ui/dist`; no deployment was performed.
Native binaries here are debug validation artifacts, not a new native release.
These runs add no Linux/macOS, installed Chrome/Edge, actual picker/external
filesystem, device/scale, physical-I/O or power-loss claim. Working-allocation
accounting remains distinct from RSS; local macOS acceptance stays deferred.

## Accumulated-change validation checkpoint (2026-10-27)

This closes TODO's accumulated-change batch against a frozen source snapshot,
before the following direct-Run implementation. It does not validate later edits.
Raw plans, source/toolchain identities, logs, attempts and summaries are retained
under `.tools/todo-validation-20261027/`. `reuse-inventory.json` compares current
entry bytes and directory membership against each reused command's manifest;
all eleven scoped comparisons match, including full vendor inputs where relevant.

Reused passing Windows evidence: R03 formatting, default/all-feature Clippy and
workspace tests, R25 portable-core WASM, R05 UI tests/native generation, and R03
base/spill-block/combined WASI resource gates. R05's later historical cache
preservation failure remains a failure; reuse is limited to its earlier matching
UI command results, not whole-round acceptance. Earlier logs retain their own
toolchains, fixtures and platform limits.

The missing complete hosted coverage ran fresh through the local runner:
production WASI build, TypeScript/hosted packaging, browser test build, 26 standard
contracts, bridge, peer cleanup, temporary interruption, persistent restart and
forced-process termination/recovery. All eleven steps pass in bundled Chromium
156.0.8078.4 on Windows. A separate two-step restore/proof batch removes test
assets and checks production exports. Four evidence freshness/unit checks pass.
The runner's fifteen tiny subprocess controls also pass.

The sealed seven-asset package is in `source/ui/dist`, with identities in
`source/package-proof.json`; engine SHA256 is
`727deb68fb14f049896253e30484e4c057f87d8e9a71a14c7fdb867ff69a7801`.
The initial hidden launcher failed to start through Windows Store Python, and
the subsequent detached launch was interrupted after Cargo finished. Its running
attempt remains incomplete, logs are preserved, and resume retried it using the
incremental cache in a managed terminal session. No interrupted attempt became a
pass. Final `completion.json` records exit zero.

The older checkout `ui/dist` was preserved in `hosted-before`; the sealed checkpoint
package is separate while the next implementation slice changes current sources.
No deployment, Linux/macOS, installed Chrome/Edge, new device/scale, physical-I/O
or performance acceptance is implied. macOS local acceptance remains deferred.

## Direct input snapshot removal (2026-10-26)

Compact and IPC were separately rejected by Astra before removal authorization.
The [decision](performance.md#direct-input-snapshot-rejection-and-removal-2026-10-26)
retains exact R24 samples, ranges, interruption sensitivity, instrumentation and
historical limitations. The [archive](history/rejected-input-snapshots-2026-10-26/README.md)
retains complete pre-removal integration/replay requirements and exclusive source
identities. `experimental-input-snapshots` and `engine::snapshots` are removed;
use ordinary direct CSV input. Shared compact storage/codecs, CSV parsing,
comparison/external merge, resource grants and generic failure/cancellation/
publication tests remain. There was no public CLI/Job selector to migrate.

R25 verification passed on native Windows: formatting, default/all-feature
workspace all-target Clippy with locked dependencies and warnings denied,
default locked workspace tests (285 passing tests including doctests),
all-feature locked workspace tests (347), all ten isolated survivor feature
workspace/all-target compile checks and portable-core wasm32-unknown-unknown.
Counts describe separate configurations and must not be combined. The removed
native/browser Cargo feature and Node/Bash build controls fail explicitly.
The external Rust import probe records the removed API as a compile error.

Fresh bundled Chromium 156.0.8078.4 passes 26 standard contracts, bridge/peer cleanup,
workspace cleanup, temporary/persistent termination and persistent process-kill
recovery. Base and shuffle-partition resource reactors pass; the latter uses
`--resource-contracts --shuffle-partition`. No prior browser matrix is reused.
This does not establish current Chrome/Edge/macOS/Linux/device/scale coverage
or every isolated optional WASI execution combination. TypeScript/native UI source
and its committed bundle are unchanged; no new native UI tests/build are claimed.

After test builds, a fresh default production engine build and hosted build pass.
The seven-asset package has no test assets and passes the production export guard;
engine SHA256 `cc478b5f1b09b0b8c6bab928a89ccf2848df75632a0c21e8ca5263970465a725`.
Full package/source/vendor/native/WASM identities and every raw EOF/exit are under
`.tools/e3-removal-20261026-r25/`; each invocation has a fresh absolute target,
TMP/TEMP/output root and source/full-vendor manifest. Historical source and pins
remain preserved. Catalog tests, refreshed catalog/family audit, unchanged 38-cell
historical numerical audit, focused local-link review and code-only Graphify pass.

Initial offline full metadata resolution encountered an uncached arbitrary crate;
subsequent locked builds passed. The first evidence check exposed a new-copy
documentation destination error, preserved before restoring exact original bytes;
the second exposed expected stale derived navigation. Both failures remain logged.
Early helper toolchain logs attempted absent repository-local rustc; they retain
WinError2. Actual builds used PATH Rust; later corrected identities/version are
explicitly later provenance. Python aliases remain inaccessible, with loaded-module
identity recorded separately. Unchanged vendored ZIP emits an existing WASI unused
variable warning; no vendor edit was made. No engine correctness/cap/admission/
cleanup/replay failure occurred and no performance rerun was performed.
Astra accepted the R25 implementation and raw verification and the R26 final
documentation diff. E3 is complete. R26 corrected documentation only and checked
links, commands and evidence navigation. No engine build or test was rerun for
R26; the R25 coverage above retains its recorded scope.


## Contributor and check routing (2026-10-24)

This documentation/CI slice adds the [contributor entry point](../CONTRIBUTING.md),
one Ubuntu combined surviving-feature Clippy/locked-test job and the existing
[read-only evidence checks](benchmarks/README.md#evidence-checks). Default native
Windows/Linux/macOS, portable core, generated native bundle parity and every
browser/resource/interruption step remain configured. The browser job now runs
the default engine build explicitly before final test-free hosted packaging;
the production export guard is unchanged. This bounded combination does not
establish every isolated feature combination or optional WASI execution path.

Local Windows verification passed: YAML parsing and structural comparison of
preserved jobs/steps, native/browser feature-forwarding inspection, contributor
links/anchors, four catalog unit tests, catalog freshness, 38-cell historical
synthesis freshness and strategy-family audit freshness. Catalog regeneration
leaves derived navigation byte-identical. No raw evidence, source snapshots,
numerical synthesis, engine/UI source, manifests or lockfiles changed.

The accepted [partition-first/Parquet removal checks](#partition-first-and-dormant-parquet-removal-2026-10-24)
are reused for default/all-feature native Clippy/tests, isolated survivors,
portable core, UI and full bundled-Chromium acceptance, including resource
shuffle-partition mode and temporary/persistent/process-kill interruption.
Reuse is supported by rehashing all compilation sources, generated native bundle,
Cargo/package manifests/lockfiles, scripts/harnesses, fixtures and complete
vendored dependencies against that accepted source manifest. All seven final
hosted files and the native executable also match its recorded package identities.
No broad engine/browser tests were rerun for this documentation/CI change.

Fresh `node scripts/build-browser.mjs` without feature flags and
`npm --prefix ui run build:hosted` pass. The resulting seven-file `ui/dist` is
test-free and byte-identical to the accepted default package; its engine has no
resource-contract export and passes the production guard. The unchanged guard's
actual resource-reactor rejection is reused from the accepted pass. Resource
builds currently write a separate test WASM; the added default rebuild makes the
final production identity explicit even after experimental production builds.

These are local Windows results and configured CI coverage, not executed
GitHub-hosted Ubuntu/macOS results. No new Linux/macOS, scale or performance claim
is made. Actionlint was unavailable; an external PyYAML parser plus focused
workflow structure checks were used. The pre-existing direct Bash wrapper CRLF
limitation remains disclosed in the prior slice; no shell file was changed.
The existing vendored ZIP WASI warning remains. MIT package metadata versus a
missing root project license remains an owner wording issue in TODO; no license
or policy was invented.

## Partition-first and dormant Parquet removal (2026-10-24)

This bounded slice deletes the flexible partition-first executable planner,
its selector/child domain, exclusive streamed diagnostics and dedicated tests,
native/browser feature gates and active multi-engine cases. Cargo removes the
unused Parquet dependency and only its exclusive lockfile packages. Exact
shuffle/partition, counter-v1, ordered flexible auto and allocation ranges remain.
Direct compact/Arrow IPC snapshot APIs also remained at this earlier slice; those
APIs were subsequently removed after the separate E3 rejections. See the
[current removal section above](#direct-input-snapshot-removal-2026-10-26). No Auto/default/direct-execution promotion
or contributor/CI changes are included. See the
[ownership audit](resource-policy-research.md#partition-first-and-dormant-parquet-removal-ownership-audit-2026-10-24).

Windows Rust 1.99.1 and bundled Chromium 156.0.8078.4 checks passed:

- Required formatting, workspace Clippy/all targets with warnings denied and
  locked workspace tests; all-feature workspace Clippy/tests; portable-core
  `wasm32-unknown-unknown` check (dependency effects checked although config did
  not change). No Linux/macOS or new scale/performance coverage is inferred.
- Isolated `experimental-flexible --test flexible`, flexible-allocation
  `allocation`, input-snapshots `snapshot` and exact shuffle-partition
  `shuffle_partition` tests. The added auto-then-partition regression checks
  logical parent/counter domain, original indices, exact CSV/metadata parity
  with counter Fisher-Yates, caps, terminal/downstream stages and absence of
  removed rewrite/feature records. Existing named-zero/exact quotas, fallback,
  collision refinement, snapshot corruption/source-change and resource equations
  remain, including the validated optional decision-audit owner grant.
- Both removed features fail Cargo resolution in native/browser packages,
  Node browser build and PowerShell Cargo wrappers. Neither experiment had a
  dedicated public runtime selector, and no Rust Parquet decoder existed;
  CLI/JSON/HTTP/WASI schemas/defaults are unchanged. Existing strict public
  invalid-request regressions pass. Flexible auto remains a supported ordinary
  ordered request. Removed `flex_reverse_*` harness cases reject explicitly.
- UI tests (28) and native UI build passed; generated `ui/public/app.js` remains
  byte-identical. Native release was rebuilt after the UI build.
- The full AGENTS/browser sequence passed: default production/hosted/tests,
  standard browser contracts (26), bridge, peer cleanup, temporary/persistent
  termination and persistent process-kill, base resource contracts, and exact
  shuffle-partition resource contracts with `--shuffle-partition`. Surviving
  `--all-features` WASI resource compilation and the same shuffle-partition
  resource harness also passed.
- Final default production engine rebuild and test-free `build:hosted` passed.
  Production guard accepts the default reactor and rejects the resource reactor;
  no resource export/test assets remain. Final exports and all seven hosted
  files plus native EXE, bundle and lockfile SHA256/size identities are retained
  in the coordinator audit's `iteration-2/final-package-v2.json`. Nothing deployed.
- Maintained strategy coverage regeneration/check and benchmark catalog
  regeneration/check passed. Historical numerical synthesis, all 638 raw evidence
  artifacts/source snapshots and 168 fixture/vendor files remain byte-identical.
  No benchmarks ran. Only derived provenance/navigation JSON changed in evidence.

The unmodified Bash wrapper in this Windows checkout has CRLF and fails before
Cargo when invoked directly. A relocated LF audit copy, changing only its
location-dependent cd and bridging installed Windows Cargo into WSL, verifies
both missing-feature rejections. Earlier attempts encountered WSL argv quoting,
missing Cargo, incorrect `$0`/working-directory handling and stdin permissions;
all attempts/logs are retained. This does not establish a Linux build or repair
that pre-existing shell-checkout limitation. Node/PowerShell wrapper checks are
direct and passed. Browser builds retain the baseline vendor ZIP `target_str`
warning; vendor sources are unchanged. No required Windows/Chromium acceptance
check remains blocked.

Remaining removed names are explicit rejection/regression controls, current
removal guidance, historical narrative/research/reproduction harnesses or
immutable raw evidence/source snapshots. Python Parquet/CSV adapter research is
explicitly historical and separate from Rust snapshot APIs. Historical harnesses
require pinned pre-removal builds; the accepted harness snapshot is retained in
the coordinator audit. The full per-hit classification, accepted-iteration-1
relative diff, command logs, dependency/source/package identities and original
baseline preservation comparison are in `iteration-2`. Contributor/CI work,
calibration and future Auto work remain separate.

Recorded results through 2026-10-23, including decoded group ownership, controlled WASI input-adapter admission, native Windows SSD calibration, bounded parallel profiling, compact external-spill blocks, dynamic Linux pressure rechecks, catalog/lineage buffers, shared process admission, operation-key/serializer accounting, format prototypes and one billion-row full-shuffle acceptance point. Dated counts below describe successive builds, not a cumulative test total. See [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for active work and [performance](performance.md) for fixtures, reproduction commands, raw data and measurement caveats.

## Independent buckets and buffered XOF removal (2026-10-24)

This isolated slice deletes independent bucket routing/leaf execution, the core
and flexible XOF sources, exclusive examples/tests, Cargo features/forwarding,
XOF resource fields and dedicated plan/cache/node diagnostics. The surviving
single-variant algorithm/RNG enums retain explicit `adaptive_v1` and
`blake3_counter_v1`; default serialization still omits them. Removed algorithm,
source and `shuffle_rng_buffer_bytes` requests fail strict decoding under both
policies. No dependency was exclusive; Cargo.lock remains unchanged. Counter-v1
code, domains and draws, flexible ordered stages, partition-first, allocation
ranges, exact fusions, shared packed storage, resident admission, random-key
collision refinement and external merge survive. See the
[ownership re-audit](resource-policy-research.md#independent-buckets-and-buffered-xof-removal-ownership-audit-2026-10-24).

Checks completed on Windows with Rust 1.99.1 and bundled Chromium 156.0.8078.4:

- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  `cargo test --workspace --locked` and the locked portable-core
  `wasm32-unknown-unknown` check passed. The workspace Clippy and tests also passed
  with `--all-features`, covering remaining exact fusions, input snapshots and
  dormant Parquet wiring. No Linux/macOS or larger-scale coverage is inferred.
- Bounded isolated feature tests passed:
  `cargo test --locked -p chopper --features experimental-flexible --test flexible`,
  `cargo test --locked -p chopper --features experimental-flexible-allocation allocation`,
  and `cargo test --locked -p chopper --features experimental-flexible-partition flexible`.
  Allocation checks retain named zero quotas, membership, original indices and
  counter-domain uniform/Fisher-Yates range cuts. Generic correctness/resource
  assertions and the validated optional decision-audit owner equation remain.
- New core, CLI `profile`/`analyze`/`run`, native HTTP
  `/api/profile`/`analyze`/`columns`/`sniff`, and WASI profile/prepare regressions
  reject the three removed requests before source access/publication. HTTP stays
  idle, WASI cannot authorize execution and publishes no destination entries.
  Existing buffer/radix/prefix rejection regressions remain. Cargo checks reject
  `experimental-fast-rng` in core/native/browser and
  `experimental-random-buckets` in native/browser; both also reject through
  `node scripts/build-browser.mjs --features FEATURE` with Cargo's missing-feature error.
- UI tests (28) and `npm --prefix ui run build` passed; regenerated
  `ui/public/app.js` is byte-identical to the coordinator baseline. Native release
  was rebuilt afterward with `cargo build --release --locked -p chopper`.
- The complete AGENTS/browser sequence passed: default WASI/hosted build and
  browser contracts (26), bridge, peer cleanup, temporary and persistent
  termination, persistent process-kill recovery, base resource contracts and
  `experimental-shuffle-partition` resource contracts. Additionally,
  `node scripts/build-browser.mjs --resource-contracts --all-features` and its
  `node scripts/test-browser.mjs --resource-contracts --shuffle-partition` suite
  passed, checking surviving WASI forwarding and admitted ownership together.
- The iteration ended with `node scripts/build-browser.mjs` and
  `npm --prefix ui run build:hosted`. The production guard accepted the default
  engine, rejected the resource reactor, and all listed test assets were absent
  from `ui/dist`. Final file sizes, SHA256s and WASM exports are retained in the
  coordinator audit's `iteration-1/final-package-v2.json`; nothing was deployed.
- `python scripts/audit-strategy-evidence.py` and `--check`, followed by
  `python scripts/benchmark-catalog.py` and `--check`, passed. These regenerate
  derived navigation/provenance only; no benchmark or numerical reinterpretation ran.

Initial failed attempts are retained in the coordinator audit: the PowerShell
Cargo wrapper dropped Clippy's `--` separator, then direct Clippy identified a
now-redundant Resources struct update, which was removed before the passing run.
An edit-script regex matched two indentation levels and stopped before writing
that harness; its corrected pass and syntax check are recorded. Browser builds
retain the existing vendored ZIP unused-variable warning; no vendor source was
changed. No required check remains blocked.

Remaining names are rejection tests/current removal guidance, immutable historical
raw evidence and source/fixture snapshots, historical narrative/design/protocols,
or unrelated tuple-routing/merge buckets and generic BLAKE3 XOF API usage.
Dedicated reproduction scripts are explicitly historical and require pinned
pre-removal builds. Active multi-engine cases and surviving range/partition
validators no longer select the removed algorithms. Historical diagnostic flags
and measurements remain intact. The per-hit classification, baseline-relative
diff/source identities and raw/snapshot hash comparison are retained under the
coordinator audit's `iteration-1` directory. Only derived catalog/strategy audit
outputs are exceptions to raw evidence immutability. Partition-first/Parquet,
contributor routing, Auto/default/direct execution and calibration remain separate
work, with no promotion in this slice.

## Radix and prefix-distribution removal (2026-10-24)

Implementation removes both physical experiments, native/browser Cargo features,
Sorter state/branches, flexible feature/plan entries and dedicated diagnostic
counters. Comparison sorting, hierarchical external merge, collision refinement,
routing, spill adapters and generic resource/correctness tests survive. The
[ownership audit](resource-policy-research.md#radix-and-prefix-distribution-removal-ownership-audit-2026-10-24)
records capacity and serialization boundaries. No dependencies were exclusive to
these features, so no lockfile change is required by this slice.

These features never added a public Job/CLI algorithm. Cargo rejects each former
feature for both packages. Native CLI saved-job and HTTP inspection/profile/prepare
regressions and hosted WASI profile/prepare regressions additionally reject
`radix` and `prefix_distribution` strategy values before input/publication.
Surviving strategies remain explicit. Verification completed on Windows with
bundled Chromium 156.0.8078.4:

- Rust formatting, default and all-features workspace Clippy with all targets
  and warnings denied, and default/all-features locked workspace tests passed.
  Focused CLI and HTTP tests passed again in both configurations after tightening
  the exact rejection assertions. Native release workspace build passed.
- Portable-core `wasm32-unknown-unknown` locked check passed. Core/schema, resource
  defaults, Auto defaults, preparation requirements and surviving RNGs are unchanged.
- UI tests (28), TypeScript/native bundle build and repeat bundle generation
  passed. The generated `ui/public/app.js` is byte-identical to the working-tree
  baseline, which already contained the completed buffer removal.
- The entire AGENTS/browser sequence passed: production WASI/hosted build,
  standard contracts, bridge, peer cleanup, temporary/persistent interruption,
  persistent process-kill recovery, base resource reactor and shuffle/partition
  resource reactor. A combined build enabling every surviving browser feature
  also compiled; its candidate resource suite, standard production contracts
  and independent-bucket routing cancellation/disk-denial controls passed.
- Default production WASI/hosted output was rebuilt and standard contracts rerun,
  followed by final `build:hosted` to remove all test assets/reactors. Packaging
  checks confirm the production engine has no resource-contract export.
- Strategy coverage audit and benchmark catalog were regenerated and checked;
  catalog tests and the unchanged 38-cell numerical audit check passed. No timed
  benchmark was launched and no raw historical artifact was rewritten.

Two combined-validation issues were resolved without changing engine contracts.
The candidate resource reactor requires `--shuffle-partition` to create its
isolated export destination; using the base runner failed with
`Missing isolated OPFS export directory`, then the correct candidate mode passed.
The standard browser retained-parent fixture initially omitted the live 3,200-byte
WASI decision-audit grant. Diagnostics proved the exact difference. Its equation
now validates the optional audit schema, bounded record/state/count fields and
reservation, then includes that owner alongside the original admitted payloads.
The original combined repro and final default suite pass; debug probes were removed.

Self-review compared edits against the saved working-tree baseline, checked
shared sorter/merge/routing and ownership boundaries, strict rejection and
remaining-name searches. Deleted modules have exact-byte historical snapshots;
all unrelated pre-existing files, raw evidence and lockfile retain their baseline
identities. No check is blocked and no acceptance gap remains for this slice.
Results establish these Windows/Chromium fixtures and builds, not broader scale,
physical-I/O, macOS/Linux or complete-RSS coverage.

Historical references are deliberately retained: dated performance/research and
completed checklists, the pre-removal strategy inventory, benchmark JSON/JSONL,
logs and pinned script/source snapshots, generated catalog/index entries and the
strategy evidence auditor's family names. The new [source archive](history/rejected-sort-experiments-2026-10-24/README.md)
preserves the removed working-tree modules byte-for-byte as noncompiled text,
including pre-existing uncommitted edits; it is not retroactive build provenance.
Shared active harnesses contain no dedicated radix/distribution cases. Ordinary
`from_str_radix` HTTP chunk decoding, key prefixes, probability/distribution
proofs and independent buckets are unrelated surviving uses.

## Buffer-shuffle removal (2026-10-24)

The current build rejects obsolete shuffle strategies and fields rather than
substituting another algorithm. Focused coverage checks wire and owned core
Job decoding, CLI flags, native HTTP profile/prepare/inspection endpoints and
WASI profile/prepare requests, including `buffer_rows` on supported strategies.
Rejected requests cannot authorize execution or publish output. Surviving seeded
fixtures, logical stage/lineage metadata, field conservation, exact allocation,
strict serialized caps and cleanup remain acceptance requirements.

The [ownership re-audit](resource-policy-research.md#buffer-shuffle-removal-ownership-audit-2026-10-24)
covers typed defaults/capacity, prepared configuration, warning bounds and the
removed diagnostic entry. The [first-slice brief](strategy-review.md#buffer-shuffle-removal-surface-and-first-slice)
remains the pre-removal scope record. Verification completed on Windows with bundled Chromium 156.0.8078.4:

- `cargo fmt --all -- --check`, default and all-features workspace Clippy
  (`--all-targets -- -D warnings`), `cargo test --workspace --locked` and its
  `--all-features` variant passed. The added native HTTP/CLI saved-job checks
  also passed in the focused `--test interfaces` rerun. Native release build
  (`cargo build --release --locked`) passed after regenerating embedded UI.
- `cargo check --locked -p chopper-core --target wasm32-unknown-unknown` passed.
- UI tests/build and plan-example regeneration passed. A second native build
  produced the identical committed `ui/public/app.js` hash.
- The complete AGENTS/browser sequence passed: production WASI/hosted builds,
  hosted tests, bridge, peer cleanup, temporary and persistent termination,
  persistent process-kill recovery, base resource contracts and the resource
  variant with `experimental-shuffle-partition`. Production tests and all
  interruption modes were rerun against the final default production reactor.
- Final `build:hosted` removed test assets; the explicit packaging audit found
  no test files/reactor and verified the production WASM export boundary.
  Python harness syntax, changed JavaScript harness syntax, evidence coverage
  audit and benchmark catalog regeneration/checks passed.

No required check is blocked. WASI builds retain the existing vendored ZIP
unused-variable warning; the vendor source was preserved. These are local
Windows/Chromium results, not new Linux/macOS, deployed-site, external-directory,
scale, performance or complete RSS-cap claims. No benchmark, commit, publication
or deployment was performed. Initial warning-count regression failures were
resolved by auditing the eight surviving conditions and rerunning native/WASI
resource coverage.

Remaining search references are deliberately classified:

- Core, CLI, native-request and hosted tests contain rejected request fixtures.
  `pipeline.rs` skips obsolete cases and strips the old irrelevant scalar only
  from immutable pre-change fixture copies for surviving seeded parity checks.
- `tests/fixtures/buffer-fusion-v1.json` and buffer cases in `pipeline-v1.json`
  are historical snapshots, preserved byte-for-byte and never accepted as jobs.
- `docs/benchmarks/`, dated `performance.md` sections, completed history and
  dated research retain original algorithms, diagnostics and source identities.
  Research/implementation-plan headers explicitly distinguish past support.
- `diagnose-shuffle.py`, `diagnose-shuffle-browser.mjs`,
  `reproduce-bucket-window.py` and `simulate-resources.py` are marked historical
  reproduction/model tools for pinned pre-removal builds. Their obsolete fields
  and negative controls are necessary to interpret those results. They are not
  current-engine usage guidance. Current benchmark/validation harness cases no
  longer emit obsolete requests.
- TODO, the agreed brief, strategy review and rejection guidance name the
  removed surface to document its disposition. Generic I/O buffers, packed-row
  storage and the separate buffered XOF random source remain supported.

## Latest recorded coverage

The [native picker capture pass](performance.md#native-picker-parent-pipe-admission-and-shutdown-2026-10-23)
admits parent stdout/stderr, selection JSON and retained failure bytes. Boundary,
competing-owner, read/parse/failure and independent-lifetime controls pass, with
exact lossy/error text and real two-pipe helper processes. Denial/cancellation
stop and reap the direct helper, including cancellation after both pipes reach
EOF; owner closing prevents later spawn. A real Linux
server with an incomplete picker body exits successfully on SIGINT after ready/
busy preconditions. Default/combined Windows/Linux checks and retained-server
comparisons pass. Actual dialogs, descendants/helper-process heaps, command/WSL
construction and runtime remain separate; hosted assets are unchanged.

The [Column scalar pass](performance.md#column-scalar-deserialization-without-successful-trial-errors-2026-10-23)
removes successful name/index trial errors and preserves exact scalar values and
legacy errors through strict invalid-container traversal. Thirty-six reference
JSON cases run natively and in WASI, with owned-name pointer/capacity checks and
explicit usize limits. The earlier long-control-name heap exception now fits the
unchanged Job-data envelope; both native platforms pass all 41 allocation cases.
Native/core-target/default/combined checks, production browser and interruption
acceptance, base/candidate desktop reactors, clean packaging and retained CLI/
server parity cover this local build. Other error/runtime ownership, deployment,
macOS and broader device/scale coverage remain open.

The [native typed Job pass](performance.md#native-typed-job-construction-admission-2026-10-23)
admits serde conversion/default buffers before allocation, then retains actual
immutable Job capacity through workers and independent PreparedJob handoff.
Three new controls add local/shared conversion/default edges, competing-owner
retry and 27 schema/error comparisons. Fourteen request contracts and native
default/combined Windows/Linux checks pass. Isolated requested-heap probes pass
40 cases on each platform: successful conversion peaks fit admitted envelopes,
retained payload matches the exhaustive capacity audit and every case releases
all observed allocations. Error-object internals remain outside the payload
bound. A separate successful-column control observes excluded trial-error
formatting beyond the data envelope while retaining exact typed capacity and
final release. Retained-server CSV/manifest and visible behavior match; hosted assets
are unchanged. Caller/CLI construction, picker/state/error/runtime scope remains open.

The [decoded native request pass](performance.md#native-http-decoded-request-ownership-2026-10-23)
reuses admitted JSON scratch/preflight/tree decoding and carries source grants
through moved strings, worker lifetimes and independent PreparedJob handoff.
Five new controls cover local/shared construction and scratch denials, competing
owners, serialization/worker cleanup, typed-conversion errors and preparation
handoff/cancellation/failure. Thirty-eight JSON/error cases match the prior
parser. Default/combined Windows/Linux checks and eleven request contracts pass;
retained-server checks preserve request behavior and strict-cap CSV/manifest
publication. Additional typed conversion/default/serde buffering and native
runtime allocations remain open. Stored hosted assets remain unchanged.

The [native request-byte pass](performance.md#native-http-request-byte-admission-2026-10-23)
admits raw payload Vec growth/replacement overlap and retains bytes through JSON
parsing. Six focused controls cover local/shared edges, size/malformed-input
limits, read/failure/drop lifetimes and release before a bounded denial drain.
Fixed/chunked loopback and zero-pool chunked rejection pass; the initial unread
upload socket reset remains recorded before the drain fix. Default/combined
Windows/Linux checks pass. A regression restores oversized Expect rejection before
100 Continue; its initial passing suite and subsequent red failure remain separate.
Real-server parity covers oversized Expect and malformed JSON/UTF-8 without
state changes plus profile, prepare/cancel/retry and exact strict-cap publication.
Parsed/source trees and runtime remain open; local hosted assets are unchanged.

The [native HTTP response pass](performance.md#native-http-json-response-admission-2026-10-23)
admits canonical response trees, formatted error text and wire buffers through
reader destruction. Windows/Linux default and combined checks and five focused
contracts cover capacity edges, failure/abandonment, EOF/concurrent lifetimes,
cache preservation, an inline fallback and static acknowledgements. A real-server
before/after fixture preserves compared JSON fields, exact CSV hashes and manifest
output records across profile, prepare/cancel/retry, publication and failure.
The native module is excluded from WASI; all seven preceding local hosted assets
remain unchanged. Incoming request/picker parsing, state/progress/error source
storage, HTTP/runtime internals and native stacks remain open. macOS is deferred.

The [diagnostic snapshot pass](performance.md#diagnostic-snapshot-preflight-and-shared-ownership-2026-10-23)
admits JSON before construction from stable borrowed context/process/audit views,
shares retained trees/grants and patches self-inclusive numeric slots without
allocating. Final Windows/Linux default and combined checks pass, including nine
read-only doctests; all seven optional snapshot tests pass on both platforms.
A new native snapshot regression requires diagnostic admission before manifest
commit. Shared native/WASI controls cover construction/controller edges, denial
cleanup/retry, changed-source re-preflight, legacy fields, bounded audit copies,
serialization, prepared cancellation and independent final release. Native
pressure-lock and concurrent-drop controls pass. Chromium passes base WASI;
Chromium, Chrome and Edge pass the combined resource reactor. Production's 25
Chromium contracts and seven-asset test-free packaging pass. A runner print-encoding
failure after 18 successful commands is completed by an unchanged-source eight-command
follow-up; earlier fixture/lifetime/commit failures remain separate. Nine prior-binary
CLI fixtures preserve CSV, logical metadata and non-memory/non-timing diagnostic
counters. All heap-backed Analysis fields now have admitted shared owners. Carrier,
source discovery, response/error/progress and native runtime coverage remain open;
the package is local and macOS stays deferred.

The [warning/timing pass](performance.md#analysis-warning-and-timing-admission-2026-10-23)
admits warning vector/String capacity and bounded timing-map storage, sharing
immutable payloads through Analysis and independent clones. Final Windows/Linux
default and combined checks pass, including eight read-only doctests; Windows
also compiles all optional features. Shared native/WASI controls cover exact
capacity edges, partial-copy denial/cleanup/retry, bounded construction, unchanged
warning text/order, serialization, independent last-owner release and cancellation
of a prepared snapshot. Native concurrent final drops pass. Chromium, Chrome and
Edge pass resource contracts; production's 25 Chromium contracts and seven-asset
test-free packaging pass. Nine prior-binary CLI fixtures preserve warnings,
timing keys, CSV and other logical metadata. Timing observations are not A/B
performance evidence. This local package adds no wider platform/scale/RSS claim;
diagnostics, other Analysis/runtime accounting and broader release work stay open.

The [Analysis text pass](performance.md#analysis-text-admission-and-sharing-2026-10-23)
admits seed/digest/accuracy String capacity and shares it through cloned and
returned Analysis. Final Windows/Linux default and combined checks pass,
including six read-only doctests; Windows also compiles all optional features.
Shared native/WASI controls cover capacity edges, competing owners, pre-read seed
denial, empty text, serialization, clone lifetime and malformed/cancelled scan
cleanup. Native concurrent final drops pass. Chromium, Chrome and Edge pass
resource contracts; production's 25 Chromium contracts and seven-asset test-free
packaging pass. Seven prior-binary CLI fixtures compare all three text fields,
CSV and other metadata exactly. Initial comparison compile failures are retained
separately. The package stays local; warning/timing/diagnostic and runtime
allocation coverage and broader release acceptance remain open.

The [stage-statistics pass](performance.md#analysis-stage-statistics-admission-and-sharing-2026-10-23)
admits fixed capacity before CSV record reads and shares counters/grants across
Analysis clones and execution results. Windows/Linux default and combined
checks pass, including five read-only doctests. Shared native/WASI contracts
cover six capacity edges, competing owners, pre-read typed denial, mutation
rejection while shared, retry, serialization and malformed/cancelled scan cleanup;
native concurrent final drops also pass. Chromium, Chrome and Edge pass resource
contracts; production's 25 Chromium contracts and seven-asset test-free packaging
pass. Seven prior-binary CLI fixtures retain exact CSV/configuration/metadata/
stage parity. The package stays local; other Analysis/runtime accounting and
broader release coverage remain open, with macOS deferred.

The [selected-column summary pass](performance.md#selected-column-summary-admission-and-sharing-2026-10-23)
bounds selection scratch and admits retained descriptors, String capacity and a
conservative tree envelope. Shared immutable summaries preserve the original
64-column/100-value/256 KiB display rules and late selection errors. Windows/
Linux pass default/combined native checks and four read-only doctests. Shared
native/WASI controls cover capacity edges, partial-growth denial/retry, independent
owners, serialization, clone/execute lifetime and populated-scan failure cleanup.
Chromium, Chrome and Edge pass resource contracts; production's 25 Chromium
contracts and seven-asset test-free packaging pass. Seven prior-binary CLI
fixtures retain exact CSV/configuration/header/preview/summary/digest/stage parity.
The package is local and adds no RSS, throughput, physical-I/O, scale or device
claim. Other Analysis/runtime allocation coverage remains open.

The [Analysis header pass](performance.md#analysis-header-sharing-and-final-owner-admission-2026-10-23)
keeps header fields and admission together through returned/cloned Analysis,
using one private shared-payload helper with previews. Final Windows/Linux runs
pass default and combined checks plus three read-only doctests. Shared native/
WASI controls cover retained-capacity edges, concurrent owners, serialization,
Prepared drop/execute lifetimes, header presence, exact complex header bytes and
malformed-header cleanup. One initial parallel-test assertion omitted its live
header; the corrected exact equation and after-drop check both pass. Chromium,
Chrome and Edge pass resource contracts, production's 25 Chromium contracts pass,
and seven-asset packaging excludes test exports. Seven prior-binary CLI fixtures
preserve header/CSV/configuration/preview/selected-value/digest/stage parity.
Other Analysis/runtime ownership remains open. The local package is not published;
no RSS, physical-I/O, scale or additional-device claim is added.

The [Analysis preview owner](performance.md#analysis-preview-capacity-and-shared-lifetime-2026-10-23)
pre-admits row/String capacity, including empty-field descriptors, and shares
immutable rows/grants across Analysis clones. Focused native/WASI controls cover
local/shared edges, partial-copy rollback, competitor retry, serialization,
public execute parity, malformed input and populated-scan cancellation. Native
parallel last-clone drops have separate coverage. After the user-confirmed
restart, unchanged-source recovery passes 255/312 Windows and 258/315 Linux/WSL
default/combined tests, with two additional compile-fail doctests in each suite.
UI tests/build and release packaging pass. Chromium/Chrome/Edge pass resource
acceptance; a single Chrome launch failure is preserved before unchanged probes
and the original contract pass, with no proven cause or code workaround.
Production's 25 Chromium contracts and seven-asset test-free packaging pass.
Seven prior-binary CLI fixtures preserve CSV/configuration/preview/selected-value/
digest/stage parity. Other Analysis/runtime ownership remains open; this local
package is not published and adds no RSS, physical-I/O, scale or device claim.

The [prepared configuration pass](performance.md#prepared-configuration-capacity-ownership-2026-10-23)
adds retained nested String/Vec capacity admission before input processing and a
read-only prepared owner, with pre-admitted generated seeds and unchanged Job
serialization. Windows and Linux pass default/combined native checks, including
a mutation-rejecting compile-fail doctest. Shared native/WASI controls cover
spare capacities, exact local/shared edges, competing-owner retry, serialization
failure and public prepare/execute cleanup. Chromium, Chrome and Edge pass the
combined resource contract. The browser equation follow-up passes all 25 standard
Chromium contracts and clean production packaging. Seven retained-binary CLI
fixtures preserve exact CSV/configuration/output-record/stage parity under
compatible caps; the invalid-cap verifier attempt is retained separately.
Caller construction/validation scratch and source
Analysis trees/clones remain outside this slice; it adds no RSS, scale or
physical-I/O claim. macOS stays deferred.

The [modern/legacy Zstandard input pass](performance.md#zstandard-modern-and-legacy-input-allocation-ownership-2026-10-23)
adds per-allocation ownership through the pinned streaming C bridge, including
legacy inner/outer contexts, buffers, layout headers and version-switch failure
cleanup. Shared native/WASI controls cover eighteen legacy and two modern
allocation faults, thirty-six local/shared edges, matched-pattern retries,
format/window behavior, truncation and profile cancellation. The first native
snapshot passes 253 default Windows workspace and 310 combined-feature Chopper
tests; the browser receiver's missing report fields are retained as a failed run.
The JSON-only report correction passes focused native checks and three desktop
WASI browser runs, production's 25 Chromium contracts and clean packaging.
Linux native checks, a scoped C AddressSanitizer run and retained unpatched CLI
controls provide separate evidence. Eight valid CLI fixtures retain exact bytes,
records and caps; five truncated inputs fail without publication in both builds.
These records do not establish complete RSS, arbitrary-input, scale or device
coverage. Other allocation/runtime work remains open; macOS stays deferred and
this local package is not published.

The [Zstandard output pass](performance.md#zstandard-output-context-admission-2026-10-23)
admits pinned C context/workspace and Rust writer storage before construction,
retaining it through finalization, failure and abandonment. Shared native/WASI
contracts check local/shared edges, concurrent owners, exact legacy-recipe bytes,
destination failures and sampled C context sizes within the bound. Twenty Windows
and six Linux/WSL commands pass with unchanged compilation sources: Windows has
252 default workspace tests, 309 combined-feature Chopper tests, UI checks,
three desktop browser resource runs and 25 standard production Chromium checks.
A retained prior-binary comparison separately verifies exact compressed hashes,
output records, caps and decoded fields/order for two CLI fixtures. Seven-file
test-free packaging and binary/asset hashes are recorded. Input allocation
coverage remains open because legacy decoder contexts are outside the modern
stream estimate; macOS stays deferred and this local package is not published.

The [ZIP member/output deflate pass](performance.md#zip-member-and-output-deflate-codec-admission-2026-10-22)
adds separate ownership for buffered ZIP lookup/member containers and inflater
storage, and gzip/raw-deflate output heaps through explicit or implicit
finalization and destination failure. Stored/Deflated/selection controls include
shared/local edges, release/retry, malformed/consumer cleanup and public-profile
cancellation. Output fixtures check exact compressed bytes and live grants in
destination callbacks. The 20-command Windows and six-command Linux/WSL passes
retain unchanged compilation sources: 251 default Windows workspace tests,
308 combined-feature Chopper tests, UI checks, new WASI contracts in Chromium,
Chrome and Edge, 25 standard production Chromium contracts and seven-file clean
hosted packaging. The parser-peak test correction and initial Clippy failure
remain separately recorded. Zstandard contexts and runtime/stack ownership
remain open; no device, scale or RSS-cap claim follows.

The [gzip input codec pass](performance.md#gzip-input-codec-admission-2026-10-22)
adds a preconstruction allowance for the pinned inflater, codec buffer, boxed
reader and bounded header/growth storage. Shared native/WASI controls cover
maximum metadata with CRC across concatenated members, local/shared edges,
denial before header reads, EOF/drop ownership and malformed/consumer cleanup.
The corrected 20-command Windows and six-command Linux/WSL records retain
unchanged compilation sources; Windows passes 249 default workspace tests,
306 combined-feature Chopper tests, UI checks, three browser resource runs and
25 standard production Chromium contracts. Final hosted packaging contains only
seven production assets. The initial native pass's WASI test-probe failure is
preserved separately. Other codec/runtime allocation paths remain open; these
local builds have not replaced the published Pages artifact.

The [controlled temporary construction/reopen pass](performance.md#controlled-temporary-construction-and-identity-preserving-reopen-2026-10-22)
pre-admits owned name/path storage for files and job/staging directories, and
removes tempfile's error-path copy from reopen. Shared native/WASI controls cover
capacity edges, collision ownership, random/OS failure, path-join behavior,
independent offsets and cleanup. Native Windows/Linux also check adversarial
replacement identity; WASI checks raw missing-name errors, not replacement.
The 20-command Windows and six-command Linux/WSL passes retain unchanged source
identities, including 248 default Windows workspace tests, 305 combined-feature
Chopper tests, UI checks, three browser resource runs and test-free packaging.
Parent discovery/normalization, OS/runtime/codec storage and stacks remain outside
this controlled boundary; macOS validation remains deferred.
The additional 19-command production-browser lifecycle pass checks bridge,
peer cleanup, temporary/persistent interruption and process-kill recovery in
Chromium, Chrome and Edge. Final test-free assets match the pinned production
package. This uses disposable profiles and same-origin OPFS, not external pickers
or real device/quota/power-loss faults.

The [forced browser-process termination pass](performance.md#abrupt-browser-process-termination-and-recovery-2026-10-22)
uses five simultaneous production jobs across preparation and CSV/marker write
and close boundaries. The test sends an OS process kill to its CDP-identified
browser, observes process exit/disconnection, and relaunches the same disposable
profile with a different browser PID. Five retained workspaces release their
locks and are removed; committed exports/marker validity survive, and a fresh
complete job has exact CSV parity without changing earlier folders. Known pending
CSV/marker transaction files remain visible in raw snapshots and do not count as
completed exports. The [thirteen-command validation](evidence-originals.md#sha256-4cc2f8b14dfbde35ef361139d1df8855051f53338b946d28f93712d6b183ec3d "Original: docs/benchmarks/browser-process-kill-validation-2026-10-21.json")
passes UI tests/build, production WASI/hosted builds, standard Chromium/bridge/peer
cleanup, all three termination modes and final test-free packaging with unchanged
source identities and removed test profile. This is Windows Chromium checkpoint
coverage, not arbitrary crash timing, power loss, quota/device faults, external
destinations, global memory admission or a new full native Rust validation pass.

The [nested-balanced follow-up](performance.md#nested-balanced-lineage-growth-and-leaf-ownership-2026-10-22)
admits traversal growth before mutation and independent shared/emitted leaf
clones. Its final-source pass adds native/WASI capacity edges, competing-owner
retry, original serial range/row/metadata/statistics parity and first/last-row
cancellation cleanup. All 19 commands pass with unchanged source identities,
including 245 default workspace tests, 302 combined-feature Chopper tests and the
combined resource reactor in bundled Chromium, Chrome and Edge. Final production
WASI/hosted packaging excludes test assets. General child construction and other
lineage mutation remain open.

The later [default child-lineage ownership slice](performance.md#default-child-lineage-construction-and-borrowed-domains-2026-10-22)
admits ordinary balanced/partition/assignment/interleaved child trees before
construction and retains their grants through catalog consumption. Borrowed
partition/assignment shuffle domains preserve canonical serialized bytes and
seeded domains. Native/WASI contracts cover three entry shapes, capacity edges,
competing-owner retry and five operation types with row/catalog rejection and
first/last-row cancellation cleanup. Legacy experimental construction and other
mutation/clones remain open; this later local build has not replaced the Pages
deployment described below.

The [experimental child/traversal extension](performance.md#experimental-child-lineage-and-mutable-partition-traversal-2026-10-22)
adds ownership for constant/consecutive partitions, partition-balanced fusion,
streaming chains and flexible allocation ranges. Shared native/WASI controls
compare exact staged output for four rewrite scenarios, exact retries for two
flexible shuffle strategies, real first/last-row cancellation and sink errors.
Mutable prefix growth has separate local/shared boundary and leaf-lifetime
checks. These remain gated experiments with small-fixture coverage; this local
build is separate from the published deployment. All 24 Windows and six
Linux/WSL validation commands pass with unchanged source identities; the Windows
pass also covers each changed feature independently under Clippy and all six
resource scenarios in three browser channels. Final packaging excludes test assets.
The [weighted root-fixture follow-up](evidence-originals.md#sha256-53399771a2486563fcabab3ec5cec5b93cf93eb9ddac0eaf56c9225ce1953fe2 "Original: docs/benchmarks/weighted-lineage-root-validation-2026-10-22.json")
verifies that ingestion consumed no leading operation before either comparison
graph, uses 40/0/60 allocations and directly checks borrowed all-values/reference
domains. Earlier six-case reports used already transformed retained scopes for
some leading operations; the later report supplies the corrected root coverage.
Only two Rust resource-test files and browser assertions differ from the full
partition-boundary source inventory; production code is unchanged.

The subsequent [partition-boundary key owner](performance.md#retained-partition-boundary-key-admission-2026-10-22)
admits the ordinary emitter's retained key and replacement overlap before
copying. Shared native/WASI checks preserve empty-tuple initialization, escaped
key bytes, old-key/sibling ownership on denial, shorter-key capacity retention
and release/retry. This adds an accounting boundary; runtime/codec/constructor
coverage and broader scale/platform acceptance remain open.

The [Linux revalidation](performance.md#linux-revalidation-of-the-published-lineage-build-2026-10-22)
passes formatting, default/combined-feature Clippy and both native test suites in
WSL Ubuntu for the nested-lineage/published source snapshot. Recorded source
identities remain unchanged. It adds Linux temporary/output correctness coverage;
macOS remains deferred and later edits require their own validation.

The [approved current-build Pages publication](performance.md#validated-current-build-published-to-pages-2026-10-22)
pins deployment/package identities and verifies exact served hashes in live
Windows Chrome/Edge. Both browsers check input profiling without confirmation,
preparation without publication, exact CSV/manifest/marker export with active
row/byte caps and abandoned-workspace cleanup preserving exports. Synthetic
File/OPFS picker results, a five-row fixture and disposable profiles bound this
acceptance; native picker dialogs, external filesystem destinations, larger
hosted jobs and other devices/OSes remain unverified.

The [existing deployed-site pass](performance.md#existing-cloudflare-deployment-acceptance-2026-10-22)
checks the user-supplied Cloudflare Pages URL in Windows Chrome: HTTPS/isolation,
real deployed UI/workers, exact five-row/three-CSV export, valid completion marker
and abandoned-workspace cleanup preserving completed exports. Only picker results
are replaced with a test File and same-origin OPFS handles. The fixture is removed
and captured requests contain no uploads. Asset hashes remain unchanged, but the
deployed WASM differs from the current checkout; this is a smoke check of that
deployed artifact, not current-build deployment parity or external-file access.

The [Windows browser-channel pass](performance.md#windows-chrome-and-edge-release-acceptance-2026-10-22)
passes the same production correctness, bridge, peer cleanup, temporary/persistent
interruption and forced-process termination/recovery suites in bundled Chromium,
installed Chrome and installed Edge. All three also pass base, retained-parent
and flexible WASI resource contracts. The 47-command record pins unchanged dirty
sources, native default/combined-feature tests and Clippy, UI checks/build and
native/WASI releases; final packaging contains no test assets. The new shuffle
lineage owner retains admission through ordinary/flexible/parallel output
consumption, with real first/last-row cancellation checks. This extends Windows
desktop acceptance, not external destinations, real device/quota faults, remote
hosting or another OS. macOS validation is deferred at the user's request.

The [publication-path ownership pass](performance.md#retained-publication-path-capacity-ownership-2026-10-21)
adds independent retained grants for manifest/archive/CSV path buffers. Shared
controls check Unicode/separator parity, local/shared edges, competing owners,
file errors and four-codec typed publication denial, staging removal,
cancellation and exact decoded CSV retry. Native Windows also checks drive, UNC
and verbatim prefixes. The [native record](evidence-originals.md#sha256-f39db1061ed03b0e00de50e685b68744ebba4e83289e685affae4409e4e565fe "Original: docs/benchmarks/publication-path-validation-2026-10-21.json")
retains formatting and the printed contract; a terminal Unicode printing failure
occurs after that output was saved. The
[follow-up](evidence-originals.md#sha256-9118e8cd1edd003d8e2a64274b7dc458f25557a1a2a511faec15b02b9e671351 "Original: docs/benchmarks/publication-path-cross-runtime-2026-10-21.json")
records full workspace tests, 163 candidate library tests, both Clippy variants,
28 UI tests/build, native embedded rebuild, production WASI/hosted builds,
25 standard Chromium contracts, bridge/peer cleanup, temporary/persistent
production interruption/restart and both WASI resource variants. All 21 follow-up
commands pass with unchanged source identities; final hosted output contains no
test assets. This covers retained path capacity; absolute destination discovery, opaque standard-library/OS path scratch
and other constructor/runtime overhead remain open. Reservations are not an RSS cap.

The [persistent-browser restart follow-up](performance.md#persistent-browser-interruption-and-restart-recovery-2026-10-21)
runs the ten-case production interruption suite in both temporary and disposable
persistent Chromium contexts, then restarts the persistent browser with three
actual jobs paused. Different browser process IDs, released locks, retained
workspace entries, exact closed export hashes, marker validity and peer cleanup
of all three abandoned workspaces pass. The profile and test-owned entries are
removed. The [twelve-command validation](evidence-originals.md#sha256-8eaac7eee9fe2b8105d9afd783af1c94fba40e3ce5e38ce2ce49bbfe34e02ace "Original: docs/benchmarks/browser-persistent-restart-validation-2026-10-21.json")
also passes UI tests/build, production WASI/hosted builds, 25 standard Chromium
contracts, bridge/peer cleanup and test-free packaging, with source identities
unchanged. [Development evidence](evidence-originals.md#sha256-eece9eabbff9ab5921e1c47ab42095a318d6dd915fdc0fa9bb5b088403452238 "Original: docs/benchmarks/browser-persistent-restart-development-2026-10-21.json")
retains the rejected assumption that a pending Chromium marker transaction file
must survive restart; the final test records its known payload separately while
strictly preserving committed files. This establishes normal shutdown/relaunch
for this Windows Chromium build, not quota eviction, real crashes/power loss,
external destinations, device performance or global memory admission. Production
code is unchanged; no fresh full native Rust test/Clippy claim is added.

The [marker-finalization termination follow-up](performance.md#browser-completion-marker-termination-and-committed-export-preservation-2026-10-21)
passes ten production-worker cancellation/tab-close cases including marker write
before close and committed close before reply, plus five same-client retries.
Before close, an empty marker entry is invalid; after close, the completed folder
survives interruption with all CSV/manifest/marker hashes unchanged. UI guidance
now requires a valid completion record and standard contracts parse its schema
and result count. The [twelve-command validation](evidence-originals.md#sha256-12b60964811675c23e394fc28be121e8b9fba40006121864ce1e6d1cb0ee05d1 "Original: docs/benchmarks/browser-marker-termination-validation-2026-10-21.json")
passes UI tests/build, native embedded rebuild, production WASI/hosted builds,
25 standard Chromium contracts, bridge/peer cleanup and test-free packaging.
The native generated bundle changes during that pass; the
[final source check](evidence-originals.md#sha256-32b0ddc2e517d5863f7ec7131efd58cd29a54d866d122444b54f030ffca095d9 "Original: docs/benchmarks/browser-marker-termination-final-source-2026-10-21.json")
pins that expected change and confirms stable inputs through repeated UI/native
builds. The [pilot](evidence-originals.md#sha256-81b0de62d5cd6ed927b6927781b8381cd49e520af1044d79a166a05697b4bd79 "Original: docs/benchmarks/browser-marker-termination-development-2026-10-21.json")
is retained separately. Coverage is Windows Chromium in fresh temporary OPFS;
persistent/external destinations, actual quota/device/process-crash faults and
cross-instance memory admission remain unproven. No fresh full Rust test/Clippy
or throughput claim is added.

The [production engine termination follow-up](performance.md#production-browser-engine-termination-and-partial-export-2026-10-21)
passes public-client cancellation and forced tab close during real WASI
preparation, after a CSV write before close, and after one CSV closes. Active peer
cleanup skips the owner; cancellation cleans its workspace and permits a fresh
same-client job, while tab-close abandonment is removed by peer cleanup. Partial
CSV/manifest exports survive cleanup without a completion marker; unrelated
entries are preserved. A fresh success control and three retries verify exact
CSV bytes and marker completion. The
[validation record](evidence-originals.md#sha256-e97308116d5487e7d9c25294ed647b1fd75cb8a034a86ddfb1b9d9d4918acd91 "Original: docs/benchmarks/browser-engine-termination-validation-2026-10-21.json")
pins production artifacts and passes eleven commands, including UI tests/build,
production WASI/hosted builds, 25 standard Chromium contracts, bridge/peer cleanup
and test-free final packaging. [Development records](evidence-originals.md#sha256-72713497f0da979eb71201c74afb4aee9a7e15b360df840f74a4bda98ef12e37 "Original: docs/benchmarks/browser-engine-termination-development-2026-10-21.json")
retain the invalid-fixture failures and superseded manifest-only pilot. This
covers this Windows Chromium build in fresh temporary same-origin OPFS, not
persistent/external destinations, marker-finalization termination, real quota/
device/crash faults or cross-instance memory admission. No fresh full native Rust
test/Clippy or throughput claim is made for this test-harness-only change.

The [job-manifest construction follow-up](performance.md#job-manifest-tree-construction-admission-2026-10-21)
pre-admits the current canonical job/analysis JSON tree and retains its grant
through construction, serializer failure and destruction. Shared contracts cover
exact byte parity across current schema forms, local/shared edges, competing
owners/retry, independent trees, partial-construction cleanup and fail-before-build
controls for unsupported serialization or overflow. A real prepared job checks
publication denial, staging cleanup, cancellation and exact-byte retry. The
[validation record](evidence-originals.md#sha256-e3d78504813184da185a39770574bb417e8d817f7b57843e3f2094924e400766 "Original: docs/benchmarks/job-manifest-validation-2026-10-21.json") owns actual
command/build/runtime outcomes: all 21 commands pass, including the Windows
workspace (147 chopper library tests), candidate library (162), both Clippy modes,
28 UI tests/build, native rebuild, 25 standard Chromium contracts, bridge/peer
cleanup and both WASI resource variants. The
[cross-runtime comparison](evidence-originals.md#sha256-71c2a05e8d594a114d217b9401e261f2dec18e8662fc80fdef1a7bd0d13992fe "Original: docs/benchmarks/job-manifest-cross-runtime-2026-10-21.json")
matches static fixture hashes and control outcomes. Dynamic prepared timing/path
metadata is compared only to its own run's prior manifest form. Source identities
stay unchanged and final production packaging removes test assets. This adds no
Linux/macOS or device-fault coverage. Source metadata and serializer/runtime allocation
are separate gaps; this preflight is specific to the current immutable schema.

The [output-planning lineage follow-up](performance.md#output-planning-lineage-clone-ownership-2026-10-21)
admits active chunk and materialized output-group lineage clones before copying,
retaining independent grants through serialization and final drop. Shared
contracts check local/shared edges, competing-owner release/retry, source drop,
serializer failure, row-cap rollover, temporary-space catalog failure,
cancellation and named empty output. Dataset planning checks exact CSV/catalog
parity. The [validation record](evidence-originals.md#sha256-c66a32cab4a35ec810b4b47e8bf7e66b046ee53e2a4c4a39196b53b9a540b5f9 "Original: docs/benchmarks/planned-lineage-validation-2026-10-21.json")
passes the Windows workspace (146 chopper library tests), candidate library (161),
both Clippy configurations, 28 UI tests/build, native rebuild, 25 standard Chromium
contracts, bridge/peer cleanup and both WASI resource variants. The
[cross-runtime comparison](evidence-originals.md#sha256-6e37f88580aaaf1d40d9a98ca33b6613f489094b8f7d38a3cecbc2efc025a035 "Original: docs/benchmarks/planned-lineage-cross-runtime-2026-10-21.json")
matches metadata identities and contract outcomes across native and WASI builds;
capacity envelopes differ by representation. Final production packaging removes
test assets and source inputs remain unchanged. This pass adds no Linux/macOS or
device-fault coverage. Other lineage creation/clones,
mutation growth and remaining metadata/runtime boundaries stay open.

The [publication metadata follow-up](performance.md#publication-batch-descriptors-and-output-name-ownership-2026-10-21)
pre-admits batch/result descriptor slots and bounded output-name construction,
then retains their grants through native worker/WASI serial execution and ordered
collection. Shared contracts cover local/shared edges, concurrent owners,
competing-owner release/retry, naming controls, worker/consumer failure and
cancellation with final cleanup. The
[per-command validation record](evidence-originals.md#sha256-f1fb41cb2abc9ea92e316ff39d260206a327a9fa0ff291b77556a77b4e4561cf "Original: docs/benchmarks/publication-metadata-validation-2026-10-21.json")
passes the Windows workspace (145 chopper library tests), candidate library (160),
both Clippy configurations, 28 UI tests/build, native rebuild, 25 standard Chromium
contracts, bridge/peer cleanup and both WASI resource variants. The
[cross-runtime comparison](evidence-originals.md#sha256-b265423682a007b86712ae1506c6678a288a275b053a8b0a18c578963be193ee "Original: docs/benchmarks/publication-metadata-cross-runtime-2026-10-21.json")
matches names, task outcomes and final cleanup across Windows and both WASI
variants; descriptor sizes differ by representation. Final packaging removes test
assets, with source inputs unchanged. No Linux/macOS or device-fault coverage is
added by this pass. Temporary joined paths, job-manifest JSON,
other clones and codec/error/runtime/thread overhead remain outside this slice.

The [native inspection payload follow-up](performance.md#native-inspection-http-payload-admission-2026-10-21)
adds preallocation local/shared admission for column/sniff success HTTP bodies,
retained by the response reader after the inspection tree drops. Native contracts
cover exact capacity edges, typed denial/retry, concurrent readers, EOF ownership,
chunked JSON parity and injected early/partial broken-pipe cleanup. A real HTTP
test checks both endpoint schemas and missing-input errors. The
[validation record](evidence-originals.md#sha256-93e823af6de332274097757527cf01b4e6d657ad016f852f97c6d678814c6a52 "Original: docs/benchmarks/native-inspection-wire-validation-2026-10-21.json")
records this Windows build's checks and source identities. Other native responses,
HTTP framing/socket/runtime allocation and other platforms remain outside this
follow-up; it establishes neither a speedup nor an RSS cap.

The [returned inspection follow-up](performance.md#returned-inspection-json-admission-and-serialization-lifetime-2026-10-21)
now admits column/sniff result trees before construction and retains their grants
through serialization and final drop. The immutable Rust `Inspection` return type
preserves HTTP/worker JSON schemas. Ordinary and 4,096-column Unicode headers and
sniff results cover local/shared edges, competing-owner release/retry, concurrent
returned owners and serializer failure. The
[final targeted pass](evidence-originals.md#sha256-5b1f6f4ae30abc4872e9d11cf0558c40a7046123aac4fa20a9f28036cb77b0b3 "Original: docs/benchmarks/inspection-result-owner-final-targeted-2026-10-21.json")
pins unchanged source inputs and passes Windows/Linux contracts with the corrected
Unicode fixture. Earlier development and Linux ASCII-fixture results are retained
and superseded for that fixture claim. The
[broader pass](evidence-originals.md#sha256-7f1b4825f956909ac3663054e0e26c42f0a626b200c81428ca7f38c6598de16f "Original: docs/benchmarks/inspection-result-owner-validation-2026-10-21.json")
and [17-feature compatibility](evidence-originals.md#sha256-c52d1d29c87b1b65b06ff52eb24c01e1de209fab754fb0a24558336ef3c5865d "Original: docs/benchmarks/inspection-result-owner-feature-validation-2026-10-21.json")
record separate configurations; native library counts are 141 default, 156
candidate and 222 combined. Caller-created clones, native response buffers,
codec/runtime allocations and RSS remain outside this coverage.

The [inspection cross-runtime comparison](evidence-originals.md#sha256-14f1cdd2f4fbbced77f20157680e675114f25972a568806a133fc02758197b14 "Original: docs/benchmarks/inspection-result-owner-cross-runtime-2026-10-21.json")
confirms matching corrected fixture identities across Windows, Linux/WSL and both
WASI variants, with zero final reservations. Its full pass includes 28 UI tests,
25 standard Chromium contracts, bridge/peer cleanup, both resource variants and
clean production packaging. Native reports match; WASI envelope sizes differ by
representation. This validates local filesystem/OPFS controlled failures, not
broader platform/device or deployment behavior.

The [ZIP metadata ownership follow-up](performance.md#zip-metadata-parser-admission-and-owner-lifetimes-2026-10-21)
adds preallocation admission at the pinned parser's actual metadata sites, with
terminal resource denial and retained archive/member owners. Twelve native/WASI
archive forms cover fallback, failed-candidate release, text expansion, extra
fields, ZIP64 and comments. Ninety callback-denial checkpoints, local/shared
capacity edges, competing-owner release/retry, EOF retention, CRC/consumer errors
and public-profile cancellation check cleanup. The earlier
[diagnostic probes](performance.md#zip-metadata-selection-and-allocation-probes-2026-10-21)
remain evidence of the uncharged build, not additional ownership observations.
These are conservative working-allocation envelopes; codec/runtime heaps, RSS
bounds, broader archive-library configurations and throughput remain outside the
claim. The [patch contract](../vendor/zip-2.4.2/CHOPPER.md) pins representation
assumptions and re-audit requirements.

The ZIP [final validation](evidence-originals.md#sha256-bda8a71b010c29db43df6d26e165e0bcf57ac34d9f4a86fc0f383a2d548f0e05 "Original: docs/benchmarks/zip-metadata-owner-final-validation-2026-10-21.json")
passes the Windows default workspace (140 library tests), candidate library (155),
formatting, both Clippy modes, 28 UI tests/build, native embedded rebuild,
25 standard Chromium contracts, bridge/peer cleanup and base/candidate WASI
resource contracts. The [17-feature pass](evidence-originals.md#sha256-b2e8f8f67960e9dd196338574928f054e0eaedcea58d87327b14caf6ec25118b "Original: docs/benchmarks/zip-metadata-owner-feature-validation-2026-10-21.json")
passes 221 library tests and Clippy. The
[cross-runtime report](evidence-originals.md#sha256-c0bad41b7e6be9d99b8954c9a0b90a2b0df836b339790bfde9854988220914b1 "Original: docs/benchmarks/zip-metadata-owner-cross-runtime-2026-10-21.json")
compares matching fixture hashes on Windows, Linux/WSL and both WASI variants;
Linux coverage in this pass is the focused ZIP contract. Final production
packaging excludes the test export/assets. Counts describe separate builds.

The [public preparation follow-up](performance.md#public-preparation-retained-parent-retry-acceptance-2026-10-21)
now covers caller-owned-pool public API ingestion/dispatch, late-parent shared
denial, earlier-parent preservation, exact UTF-16 cap/publication parity,
cancellation and persistent-pressure cleanup on Windows, Linux/WSL and WASI.
The [cross-runtime report](evidence-originals.md#sha256-c8b7fa1de7e8bc7a4dd9ec434b9163091670fb82e6ea8a8de5b99a9409ed8390 "Original: docs/benchmarks/public-preparation-cross-runtime-2026-10-21.json")
matches the declared fixture, encoded and metadata identities. Its
[full validation](evidence-originals.md#sha256-628a511a2c1b1cc671d9922ab589cb5ea3dd93b1590cd27ea8c481c590c6d268 "Original: docs/benchmarks/public-preparation-full-validation-2026-10-21.json")
and [17-feature compatibility](evidence-originals.md#sha256-e950608c6fa2bfc0ab1a9b36852d4821b9fd2209fb6d5e161adc06c84e0c31d2 "Original: docs/benchmarks/public-preparation-feature-compatibility-2026-10-21.json")
retain per-command results rather than replacing earlier passes. The pinned
[outside-checkout shape calibration](performance.md#retained-parent-shape-calibration-outside-the-checkout-2026-10-21)
completes the interrupted skew/rare-wide cells on the same SSD; checkout-local
publication error 5 remains unexplained. No selector/default, physical-device
effect, process-pool discovery, production request injection or broader
destination/termination acceptance is established by these additions.

The [current TODO follow-up validation](evidence-originals.md#sha256-8235925254aeb5c8178902e8179b4b1db6b026041c069dd8be287650ad55bf35 "Original: docs/benchmarks/current-todo-validation-2026-10-21.json")
records 15 focused benchmark/provenance tests, four catalog tests, 28 UI tests,
TypeScript/native UI and native debug builds, 25 standard Chromium contracts,
bridge, peer tab/worker cleanup, and base/candidate WASI resource contracts.
Clean hosted packaging passes the production export guard with no test assets.
The production WASM remains
`c18a5139ebb5c0b960ad84cd5f62794f055cca66fbb23922bfc2615dfaa18ea3`.
This pass changes UI cleanup/export and benchmark harnesses; it does not claim
a new full Rust workspace/Clippy, macOS, deployment or scale validation pass.
The [peer cleanup](performance.md#peer-tab-and-worker-abandoned-workspace-cleanup-2026-10-21)
and [marker finalization](performance.md#browser-export-finalization-failure-ownership-2026-10-21)
contracts have separate lifecycle scopes. Current-build
[SSD job calibration](performance.md#current-retained-parent-ssd-calibration-and-publication-failures-2026-10-21)
and [Windows profiles](performance.md#native-windows-bounded-parallel-profile-calibration-2026-10-21)
retain their own pinned builds, complete cells, partial/failing runs and resource
tradeoffs; no default, physical-I/O or RSS-cap promotion follows.

| Area | Recorded evidence | Detail |
| --- | --- | --- |
| Retained directory paths, 2026-10-21 | Context/staging boxed paths acquire local/shared admission before creation and retain it through final ownership. Unicode/relative/trailing parents, exact edges, sibling denial/retry, early failure/cancellation, last-Arc lifetime, staging removal and publication disarm pass on native/WASI. File/directory/header/audit owner equations remain exact. Windows/Linux full workspaces pass (139/141 library tests); 17-feature library passes 219 and focused feature integration suites pass 4/6/12. Both Clippy modes, formatting, 25-browser suite, bridge, base/candidate resource/export contracts, 11 verifier tests, one complete CLI control and clean production packaging pass. Opaque constructor/runtime allocations remain outside the slice | [Evidence and boundaries](performance.md#retained-job-and-staging-directory-path-ownership-2026-10-21) |
| Bounded CSV sniff ownership, 2026-10-21 | Raw/decoded samples and candidate parser capacities now retain admission through actual ownership and growth overlap. Shared native/WASI tests cover typed local/shared denial, release/fresh retry, BOM/truncated tails, scoring/error parity, fragmented/interrupted reads, partial-read-error cleanup and the decompressed sample cap. Public plain/gzip/zstd/ZIP inspection checks pass. Full Windows/Linux default workspaces pass (138/140 library tests); 17-feature library passes 218. Both all-target Clippy modes, formatting, 25-browser suite, bridge, base/candidate resource/export contracts and clean production packaging pass. Counts describe separate passes; no throughput/RSS claim | [Ownership and scope](performance.md#bounded-csv-sniff-sample-and-parser-ownership-2026-10-21) |
| Restored Windows checks and column inspection, 2026-10-21 | After the user disabled Smart App Control, the full Windows default workspace passes (137 library tests plus integration/doc suites), the exact candidate-only case passes, and joint/17-feature library passes contain 151/217 tests respectively. Linux full workspace passes (139 library tests). Ordinary-stack fixture repair, charged column source/parser ownership and native/WASI denial/lifetime/cleanup contracts pass. Both Clippy modes, formatting, 28 UI tests/build, standard 25-browser suite, bridge, base/candidate resource/export contracts and cleaned production packaging pass. One lost temporary USN probe cannot be replayed; the maintained held-writer cache regression passes instead, without a USN claim | [Revalidation and limits](performance.md#restored-windows-checks-and-column-inspection-ownership-2026-10-21) |
| Unblocked retained-parent Windows replay, 2026-10-21 | All 12 complete jobs pass exact output/audit/cleanup checks using the initial attempt's unchanged pinned pre-inspection binaries. Three pairs per cell: 17,000-row median change −1.5% with overlapping ranges; 300,000-row change −26.9%. Warm/uncontrolled NTFS/NVMe, logical traffic and separate CPU/working-set/reservation observations; no physical I/O, tail, selector or default claim | [Replay and provenance](performance.md#windows-retained-parent-replay-after-smart-app-control-was-disabled-2026-10-21) |
| Current Windows retained-parent calibration attempt, 2026-10-21 | Fresh matched default/candidate release builds preserve an unchanged 102-file source inventory and pinned binaries. Ten portable harness tests pass; retained mode rejects missing/invalid audits and preserves exact owner equality. Windows Application Control rejects the first baseline process (WinError4551); zero complete CLI jobs/timings are recorded, so current-build performance and CLI acceptance are unverified. Failed launch, generated fixture, build transcripts and exact harness snapshots are retained; no workaround or matrix expansion | [Stopped pass and provenance](performance.md#current-retained-parent-windows-calibration-attempt-2026-10-21) |
| Browser export after retry, 2026-10-21 | Standard 25-browser suite, base/candidate resource reactors and bridge pass. Shared production exporter copies the verified retry result exactly to a separate OPFS destination; marker opens after all six writers close. Injected second-write rejection aborts once and leaves a partial folder without marker; source/destination/workspace cleanup passes. Windows passes 215 combined-feature and 135 default library tests; full default workspace is incomplete because Application Control rejects the flexible integration binary (OS4551) on sandbox/ordinary attempts. Linux full default workspace passes. Both Clippy modes, formatting, 28 UI tests/build and final production asset/export guards pass. No real quota, user-selected destination, cross-tab, deployment or speedup claim | [Pinned variants, failures and scope](performance.md#browser-export-after-retained-parent-retry-2026-10-21) |
| Encoded publication after retry, 2026-10-21 | Windows default workspace passes (135 library); recorded 17-feature library passes 215 tests; both Clippy modes, formatting and 28 UI tests/build pass. Shared publication test passes Linux and three modes run in candidate Chromium/WASI: active strict UTF-16/BOM byte splitting with exact CSV/output-record parity, one-byte-too-small cap rejection, and cancellation during writing. Final reservations, staging and workspaces release. Native atomic publication and WASI internal directory finalization are distinguished; no public preparation-dispatch injection, JavaScript export/marker, speedup or broader platform claim | [Pinned contract pass and scope](performance.md#encoded-csv-caps-and-publication-after-retained-parent-retry-2026-10-21) |
| Bounded retained-parent audit, 2026-10-21 | Windows default workspace passes (135 library); 17-feature library passes 214 tests; both Clippy modes, formatting and 28 UI tests/build pass. Linux passes ten focused candidate and three audit tests. Candidate Chromium/WASI resource reactor verifies typed denial phases, outcomes, partial observations and final release. Native tests cover 16-record truncation, late-wide exact parity, capacity boundaries, optional collection denial and last-context ownership. Retained capacity is 3,328 bytes Windows/Linux and 3,200 WASI; telemetry consumes working headroom. Test-export guard and production asset removal pass. No cost selector, speedup, injected-retry CSV-cap/export or broader platform claim | [Pinned source, transcripts and bounded scope](performance.md#bounded-retained-parent-decision-audit-2026-10-21) |
| WASI retained-parent retry, 2026-10-21 | Windows default workspace passes (135 library); recorded 17-feature library passes 209 tests; default/combined Clippy and formatting pass. Eight focused candidate tests pass Windows and WSL. Base and candidate resource reactors pass Chromium, including late-parent typed denial/release replay, earlier-parent preservation, cancellation, persistent pressure, actual pathname cleanup failure at retry boundary and terminal emission without replay. Windows/Linux/WASI logical snapshot/stat hashes match; all owners/workspaces release. Default WASI passes 25 contracts plus bridge check; test-export guard/asset removal pass. This retained-dataset fixture adds no injected-retry CSV-cap/export, scale or macOS acceptance | [Pinned variants, native launch rejection and raw evidence](performance.md#wasi-retained-parent-retry-acceptance-2026-10-21) |
| WASI group denial / unlink publication rejection, 2026-10-21 | Windows default workspace passes (135 library); default/17-feature Clippy and formatting pass. New helpers and combined resource entry pass on WSL. Normal group iterator typed Shared denial, explicit fresh-reader retry, owner surviving reader/dataset/context, and terminal malformed/cancel errors run in Chromium/WASI. Real WASI pathname/type unlink error retains orphan/path charges and prevents engine publication; final context/OPFS cleanup passes. Rebuilt default WASI passes 25 contracts plus bridge check. Actual test-export guard and asset removal pass. Fusion retry-boundary, OPFS delete/export and macOS acceptance remain open | [Raw contract pass, failed attempt and precise scope](performance.md#wasi-group-denial-and-cleanup-publication-contracts-2026-10-21) |
| Decoded groups / test-only WASI admission, 2026-10-21 | Default Windows workspace passes (133 library); recorded 17-feature library configuration passes 207 tests. JSON/parallel/nested focused tests pass Windows and WSL (12/9/2); decoder owners, partial-record rewind, serial prefetch fallback, sink failure and terminal errors are covered. Default/combined Clippy and formatting pass. Default WASI passes 25 Chromium contracts plus bridge check; a separate WASI contract checks compressed-adapter typed shared denial, release/retry and real OPFS cleanup using the native helper. Actual-module packaging guard and final test-asset removal pass. Late-parent/group denial and actual unlink-error injection in WASI remain open | [Source/build identities, failures and limits](performance.md#decoded-group-owners-and-wasi-resource-contracts-2026-10-21) |
| Input-adapter capacity / Windows profile invalidation, 2026-10-20 | Windows default workspace passes (129 library); combined shuffle-partition/spill-block/parallel-profile library passes 146 tests. Fixed input buffers and ZIP preflight share admission; returned profiles release correctly under denial. Windows rescans avoid stale same-size cache hits; Unix reuse remains covered by nine WSL profile unit and eight integration tests. Windows/Linux concurrent unlink and retry-boundary regressions pass. Formatting, default/combined Clippy, portable-core WASM and experimental snapshot compilation pass; default WASI passes 25 Chromium contracts plus bridge check. WASI typed denial and actual unlink-error injection remain open | [Boundaries, failed attempts and raw validation](performance.md#input-adapter-capacity-and-windows-profile-invalidation-2026-10-20) |
| Windows whole-device counter diagnostic, 2026-10-20 | Twelve pinned-build jobs preserve exact bytes/order/metadata, independent ID/field/membership checks, caps and success cleanup. Volume mapping and raw counters work; noise, warm cache and collection cadence exclude physical-effect inference for the entire pass. Measured scripts are preserved; corrected cadence passes 14 deterministic tests plus three provenance tests. No replacement device run or default promotion | [Raw pass, method exclusion and maintained harness](performance.md#windows-whole-device-io-diagnostic-follow-up-2026-10-20) |
| Publication I/O / cleanup-failure admission, 2026-10-20 | Default Windows and WSL workspace suites pass (126/127 library). Thirteen focused output tests cover allocation edges, concurrent/final owners and staging denial/cancellation/retry across plain/gzip/Zstandard/ZIP. Actual Linux unlink-error regression retains orphan charges and prevents successful retry; five compact-spill tests pass. Default and combined-feature Clippy/formatting pass; rebuilt default WASI passes 25 Chromium contracts plus bridge check. This is not physical-disk failure, broad browser denial, scale, throughput or RSS acceptance | [Current boundary and validation record](performance.md#publication-io-capacity-and-cleanup-failure-admission-2026-10-20) |
| Retained-parent retry / decoded output catalogs, 2026-10-20 | Default Windows workspace tests pass (121 library); eight focused exact-shuffle/partition tests pass. Typed denial/rollback, prior-parent preservation, persistent pressure, cancellation and terminal sink failure are covered. JSON/output tests cover predecode bounds, concurrent owners and staged-publication cleanup. Default/feature Clippy, formatting and portable-core WASM check pass. Default and experimental WASI each pass 25 Chromium contracts plus bridge check; no browser denial/physical-I/O/RSS/deployment claim. Focused host portability tests pass Windows and WSL Linux | [Implementation, raw browser evidence and exclusions](performance.md#retained-parent-retry-and-decoded-output-catalog-ownership-2026-10-20) |
| Native Windows spill transition, 2026-10-20 | 18 repeated complete jobs at 15,000/17,000/20,000 rows preserve exact bytes/order/metadata, independent IDs/fields/membership, cap checks and success cleanup. A separate six-job single-repeat probe locates plan changes but is excluded from timing estimates. Fusion spills while baseline remains resident at 17,000 rows, with overlapping elapsed ranges and higher temp traffic. Same pinned builds/host as the larger calibration; no new failure, browser or release acceptance | [Transition evidence and limits](performance.md#windows-shufflepartition-spill-transition-calibration-2026-10-20) |
| Native Windows shuffle/partition, 2026-10-20 | 30 alternating complete jobs on NTFS/NVMe, 3,000–1,400,000 rows, resident/external/hierarchical/skew/rare-wide shapes; exact bytes/order/metadata, independent ID/field/membership and successful cleanup checks pass. 20 CLI cap/failure/snapshot controls and six focused collision/reservation/cancellation/disk-budget Rust tests pass. Windows CPU, working set and process I/O are recorded; warm cache, one device, no physical I/O or new browser/release acceptance | [Windows calibration and limits](performance.md#native-windows-ssd-shufflepartition-calibration-2026-10-20) |
| Flexible partition-first plan, 2026-10-18 | 255 all-feature workspace tests (162 library), 24 Chromium/WASI contracts, formatting and Clippy pass at the planner checkpoint. All 210 native timings, 70 paired censuses, 36 native/WASI plan comparisons and 38 CLI controls preserve exact parity within pinned plans or independent text/ID/scope/cap invariants across distributions. Finite permutations, barriers, explicit strategy exclusion and physical/logical indices are tested. Native exact fusion remains faster; mixed browser controls retain opt-in status | [Full-job comparison and scope](performance.md#flexible-partition-first-shuffle-experiment-2026-10-18) |
| Flexible full-shuffle policy, 2026-10-18 | 201 default / 252 all-feature workspace tests (159 library), 24 Chromium/WASI contracts, UI/TypeScript, formatting and Clippy pass. Mixed resident/external parent selection, explicit v1 parity, original indices, audit hashing, retained snapshots/caps, shared-denial replay and cancellation/limit cleanup are covered. The policy stays opt-in; distribution rewrites and new RNG/bucket acceptance remain open | [Policy and measurements](performance.md#explicit-flexible-full-shuffle-policy-2026-10-18) |
| Exact streaming membership/partition chains, 2026-10-18 | 199 default / 244 all-feature workspace tests, 158 all-feature library tests, 24 Chromium/WASI contracts, formatting and both Clippy modes pass. Eight added tests cover all four endpoint combinations, counters/domains/stats, resident/hierarchical execution, capacity/growth/shared denial, partial-output rollback, CSV/dataset retry, empty scopes, cancellation and composite-key allowance fallback. All 492 final native timings (48 default controls), 148 censuses, 240 native/WASI jobs, 46 CLI controls and 48 configured-admission jobs preserve parity or clean rejection; four invalid settings also reject. Six real constrained runs retry successfully. Primary gains coexist with higher live memory and a 14% large external-browser regression. Feature stays opt-in; default builds restored | [Revisions, raw data and limits](performance.md#streaming-membership-partition-chains-2026-10-18) |
| Exact partition/shuffle/balanced fusion, 2026-10-18 | 199 default / 236 all-feature workspace tests, 150 all-feature library tests, 24 Chromium/WASI contracts, formatting and both Clippy modes pass. Seven added tests cover bounded counter capacity/fanout, exact rounding/stats/domains, forced collisions through hierarchical merges, partial-output fallback, injected CSV/dataset admission retry and cancellation after emission. All 322 final native timings, 102 censuses, 156 native/WASI jobs, 32 CLI controls and 48 configured-admission jobs preserve parity or clean rejection; four invalid settings also reject. Primary terminal and browser gains coexist with mixed native controls. Feature stays opt-in; default builds restored | [Measurements, raw data and limits](performance.md#partition-shuffle-balanced-fusion-2026-10-18) |
| Exact shuffle/partition fusion, 2026-10-16/17 | 199 default / 219 all-feature workspace tests, 133 all-feature library tests, both Clippy modes and formatting pass. Six added tests exercise eligibility, collisions, resident/hierarchical merges, multiple parents/downstream steps, reservations and failure cleanup. All 210 native timed jobs, 70 censuses, 20 input/failure/snapshot controls and 120 final persistent-profile native/WASI jobs preserve exact output/metadata and independently checked conservation. Browser gains remain warm-profile evidence; wide-key/resource controls are mixed; feature stays opt-in | [Measurements and limits](performance.md#exact-shufflepartition-prototype-evaluation-2026-10-16) |
| Browser storage boundary, 2026-10-17 | A storage-only reproducer captures an invalid temporary-context OPFS write count; both persistent-profile probes complete 1.5 GiB. Regression tests fail before fixes and pass afterward for delayed notifications and invalid read/write counts. All four UI test files, TypeScript and 24 candidate Chromium/WASI contracts pass. The original large global workload and four-variant hierarchical replay complete with persistent profiles. Earlier temporary-context timings retain their narrower scope | [Context correction and evidence](performance.md#exact-shufflepartition-prototype-evaluation-2026-10-16) |
| Bounded native profiling/hash batches, 2026-10-16 | 199 default / 208 all-feature workspace tests, 122 all-feature library tests, 24 candidate browser contracts, both Clippy modes and paired native/WASI release builds pass. Four tests cover quoted/wide/header/empty profile parity, bounded storage, serial fallback, late local/shared denial and full-scan retry, cache lifetime, corruption/cancellation cleanup. Final native evidence: 60 repeated large profiles, 20 tiny points, 12 first-wide profiles, 30 previous/current serial controls and 44 allocation censuses preserve exact profile JSON. Twelve native/WASI fresh profiles, six browser cache copies and twelve complete jobs preserve profile/output/metadata parity with four native and one browser worker. Large hash-heavy scans improve 46–49%; extra resources and regressions keep the feature opt-in. WASI remains serial | [Revisions, parity, costs and scope](performance.md#bounded-parallel-profiling-evaluation-2026-10-16) |
| Compact external-spill block experiment, 2026-10-16 | 199 default / 204 all-feature workspace tests, 118 all-feature library tests, 24 candidate browser contracts, both Clippy modes and paired native/WASI release builds pass. Five codec tests cover streaming, schema reuse/change, corruption, capacity/fallback, wide rows, lifetime, cancellation and quota edges. All 168 native timed jobs, 56 allocation censuses and 112 native/WASI jobs preserve exact output/metadata and independently checked conservation, including native 77-run hierarchy and 1.4-million-row two-shuffle native/WASI pipelines. Native costs prevent default promotion; browser gains remain warm OPFS evidence | [Format, costs, savings and limits](performance.md#compact-external-spill-block-evaluation-2026-10-16) |
| Dynamic Linux pressure rechecks, 2026-10-16 | 199 workspace tests, 113 combined-feature tests and 24 browser contracts pass; native/WASI releases, formatting and Clippy pass. Six tests cover throttling/unknown/recovery, rollback, concurrency, retained owners, publication denial, quoted/late-wide input and ID/field conservation. 96 final native timed jobs, 32 allocation censuses and 27 native/browser jobs preserve parity, including 1.4-million-row hierarchical merging with real rechecks. Eight injected candidate attempts complete exactly or fail cleanly; configured boundaries add 32 constrained successes, eight clean failures, eight references and four invalid settings. Injected/configured admission is not OS pressure or an RSS cap | [Policy, costs and evidence](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16) |
| Catalog input/streamed lineage JSON, 2026-10-16 | 193 workspace tests, 107 combined-feature tests and 24 browser contracts pass. 96 final native timed jobs, 32 allocation censuses and 27 native/browser jobs preserve exact output/metadata. Line buffers are reusable/bounded/reserved; size checks and v1 JSON domains stream without encoded scratch. Decoded JSON trees remain uncharged | [Evidence and limits](performance.md#catalog-input-buffers-and-streamed-lineage-json-2026-10-16) |
| Shared process admission/Linux discovery, 2026-10-16 | 187 workspace tests, 102 combined-feature tests and 24 browser contracts pass; native/WASI releases build. Seven new tests cover concurrent capacity, rollback, cgroup parsing/ancestor pressure, retained profile/prepared owners and retry/cleanup. All 180 timed native jobs, 60 allocation censuses, 64 fresh profiles, 32 browser cache replays and 64 native/browser output jobs preserve parity. Additional boundaries: 32 constrained successes, eight clean failures, eight references and four invalid settings. Startup discovery and one-instance sharing do not close dynamic pressure or browser cross-tab coordination | [Evidence and tradeoffs](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16) |
| Operation-key capacity/inline indices, 2026-10-16 | 180 workspace tests, 95 combined-feature tests, 24 Chromium/WASI contracts, formatting and all-target Clippy pass; native/WASI releases build. All 168 timed native jobs, 56 allocation censuses and 63 native/browser jobs preserve exact output/metadata. Capacity/boxing/handoff denial, retry, lifetime and spill conservation covered; 42 additional interleaved native/browser recheck jobs pass; initial +12.8% browser increase is not reproduced | [Evidence and limits](performance.md#operation-key-capacity-and-inline-group-indices-2026-10-16) |
| Serializer/prefix/digest accounting, 2026-10-16 | 175 workspace tests, 90 combined-feature tests, 24 Chromium/WASI contracts, formatting and all-target Clippy pass; native/WASI releases build. All 156 timed native jobs, 52 allocation censuses and 63 native/browser jobs preserve output/metadata across UTF-8, UTF-16/BOM and legacy encodings. Exact/shared limits, encoding errors, reuse, hard caps and lifetime covered | [Initial/final evidence](performance.md#serializer-prefix-and-logical-digest-accounting-2026-10-16) |
| Billion-row native full shuffle, 2026-10-16 | 1,000,000,000 presorted unique IDs shuffled into four exact balanced files; bitset/field checks and an independent lexical-ID recheck agree with every output hash. 256 MiB/four workers, 2,892 runs/46 merges, 1,131 s processing/publication, 56 MiB observed engine RSS and 102.2 GiB engine temporary peak. One copied build predating serializer/digest accounting; no broader runtime/shape claim | [Evidence and limits](performance.md#billion-row-native-full-shuffle-acceptance-point-2026-10-16) |
| Text-format prototypes, 2026-10-16 | 162 ordinary and 54 allocation-instrumented complete jobs preserve decoded text, output and metadata across u64/compact blocks, IPC/Feather V2 and text-only Parquet; 21 standalone block controls reject malformed/truncated frames. All measured CSV adapter paths regress; no production format/cache change | [Experiment and constraints](performance.md#text-snapshot-and-compact-block-prototype-evaluation-2026-10-16) |
| Output writer buffers, 2026-10-16 | 169 workspace tests, 87 combined-feature tests and 24 Chromium/WASI contracts pass; 72 timed native jobs, 24 allocation censuses and 36 native/browser jobs preserve exact output/metadata. Exact/shared boundaries, retained snapshots and constructor cleanup covered | [Evidence](performance.md#output-snapshot-writer-buffer-accounting-2026-10-16) |
| Streaming group state, 2026-10-16 | 166 workspace tests, 84 combined-feature tests and 24 Chromium/WASI contracts pass; 84 timed matched-source native jobs, 28 allocation censuses and 36 native/browser jobs preserve exact output/metadata. Capacity/validation/shared-pressure cleanup covered; initial stale-baseline pass superseded | [Evidence](performance.md#streaming-group-state-accounting-2026-10-16) |
| Merge/routed header keys, 2026-10-16 | 141 workspace tests, 59 combined-feature library tests and 24 Chromium/WASI contracts pass; formatting, Clippy and native/WASI release builds pass. Shared capacity edges, winning/replacement key overlap across copy/owned/compact consumers, routed decode lifetime, truncation and cancellation cleanup are covered. 132 timed complete native/native-WASI jobs and 36 allocation censuses preserve exact output/metadata, including native 67-run hierarchical merging; decoded row allowances remain conservative and full live-memory/RSS accounting remains open | [Evidence and scope](performance.md#merge-and-routed-header-key-accounting-2026-10-16) |
| Compact dataset decode accounting, 2026-10-16 | 133 workspace tests, 51 combined-feature library tests and 24 Chromium/WASI contracts pass. Shared growth edges, retained row lifetime, wide-buffer reuse, shrink denial, corruption/truncation and transfer to retained sort storage are covered. Complete-job timing/allocation and native/WASI parity evidence is recorded separately; owned decoding, keys, conversion/cache/runtime overhead remain open | [Evidence and limits](performance.md#compact-dataset-decode-accounting-2026-10-16) |
| Profiling parser accounting, 2026-10-15 | 129 workspace tests, 47 combined-feature library tests and 24 Chromium/WASI contracts pass; formatting, Clippy, TypeScript and native/WASI release builds pass. Exact/shared capacity edges, header lifetime, malformed/oversized records and cancellation release are covered. 48 fresh profiles, 24 browser cache replays and 48 complete-job controls preserve profile content and exact output/metadata. Fresh profiling has a measured timing cost; retained profile/cache metadata and full RSS accounting remain open | [Evidence and limits](performance.md#profiling-parser-buffer-accounting-2026-10-15) |
| Compact parser buffer accounting, 2026-10-15 | 122 workspace tests, 43 combined-feature library tests and 24 Chromium/WASI contracts pass; formatting, all-feature Clippy and native/WASI release builds pass. Capacity/growth edges, shared-pressure spill/retry, malformed CSV, cancellation and late-wide budget/worker parity are covered. Final native A/B timings/censuses and native/WASI replays preserve exact output and metadata; timings have a small cost. The ledger still excludes remaining owned parsing/intermediate decoding and runtime allocations | [Evidence, measurements and limits](performance.md#compact-parser-buffer-accounting-2026-10-15) |
| Resident native/WASI follow-up, 2026-10-15 | 48 alternating complete jobs pass: 128/100,000 rows, global/four groups, random-key/Fisher–Yates, one native worker and WASI. Native unique-ID conservation/group isolation and exact output/metadata parity within each algorithm/version pass; every job is resident with zero spills/merges. Wall/loop times, reservations and temporary/OPFS I/O are recorded; no consistent whole-job Fisher–Yates advantage or automatic-policy change | [Measurements, variability and scope](performance.md#resident-full-shuffle-native-and-wasi-comparison-2026-10-15) |
| Borrowed UTF-8 spill fields, 2026-10-15 | 117 workspace tests, 40 combined-feature library tests, 24 Chromium/WASI contracts, formatting, all-feature Clippy, TypeScript and native/WASI release builds pass. Exhaustive one/two-byte UTF-8, Unicode boundary/prefix, corruption/truncation, output-error and real wide UTF-8/cap tests pass. Initial/final comparisons each contain 128 native timed/allocation jobs; six large native/WASI replays preserve exact output/metadata. Wide-job allocation traffic falls by 1.8 MB; whole-process allocation peaks are unchanged and timings remain mixed, including a slower resident control | [Implementation, initial/final results and limits](performance.md#borrowed-utf-8-spill-validation-and-copying-2026-10-15) |
| Full-shuffle worker/WASI matrix, 2026-10-15 | 18 smoke jobs and 72 repeated 1.3-million-row complete jobs pass, preserving exact output/order, conservation and logical metadata across one/four native workers and WASI, many-column/rare-wide rows, grouped/two-shuffle pipelines and multi-level merges. Before/after resource counters match within each runtime; native/WASI intermediate traffic can differ. Native CPU/RSS and browser OPFS operations are recorded; controlled physical SSD I/O and browser CPU/allocation/RSS remain unmeasured | [Matrix and raw evidence](performance.md#full-shuffle-native-and-wasi-worker-matrix-2026-10-15) |
| Retained temporary paths, 2026-10-15 | 115 workspace tests, 38 combined-feature library tests and 23 Chromium/WASI contracts pass; formatting, all-feature Clippy, TypeScript and native/WASI release builds pass. Shared-capacity boundaries, UTF-8 paths, final-owner lifetime, creation errors, cancellation, dataset/merge overlaps and prepared-snapshot release are covered. 128 native timed/allocation jobs preserve exact output/metadata, including 1.3-million-row/65-run merging. Parser/decoded-input capacity, transient creation scratch, OS handles and full RSS remain outside these charges | [Accounting and measurements](performance.md#retained-temporary-path-accounting-2026-10-15) |
| Compact CSV ingestion/frame metadata, 2026-10-15 | 113 workspace tests, 36 combined-feature library tests and 23 Chromium/WASI contracts pass; formatting, all-feature Clippy, TypeScript and native/WASI release builds pass. Differential CSV/errors/working limits, encoding and buffer reuse, v1 digest framing, seeded order, strict caps and cleanup pass. Native complete-job comparisons preserve exact output/metadata; the first candidate regressed and was revised. Rare-wide parser scratch peaks increase; full allocation/RSS accounting remains open | [Implementation and separate experiment records](performance.md#compact-csv-ingestion-and-frame-metadata-2026-10-15) |
| Sort-run catalog accounting, 2026-10-15 | 111 workspace tests, 36 combined-feature library tests and 23 Chromium/WASI contracts pass. 128 native timed/allocation jobs plus 27 native/browser replays preserve exact output/metadata, including 1.3-million-row/65-run merging. Descriptor capacity/growth overlap, denied reservations and exhausted merge-iterator lifetimes are charged; remaining file/path metadata and full RSS are not | [Accounting and measurements](performance.md#sort-run-catalog-accounting-2026-10-15) |
| Dataset I/O buffer accounting, 2026-10-15 | 108 workspace tests, 33 combined-feature library tests and 23 Chromium/WASI contracts pass; formatting, Clippy, TypeScript/UI build and native/WASI release builds pass. 128 native A/B/allocation jobs match exact output/metadata, including 1.3-million-row/65-run multi-level shuffle and balanced jobs. Capacity edges, live/exhausted concurrent readers, denied reservations and corruption/cancellation cleanup are covered. Parser/decoded payloads and full RSS accounting remain open | [Accounting and measurements](performance.md#intermediate-dataset-buffer-accounting-2026-10-15) |
| Parser storage/compact streaming ingestion, 2026-10-15 | 106 workspace tests, 31 combined-feature library tests, 23 Chromium contracts, all four UI test files, TypeScript, formatting and all-feature Clippy pass. Native/WASI release builds pass. 160 native A/B/allocation jobs preserve exact output and metadata; tests cover categorical v1 framing, owned/compact routing and 70-way fallback, wide-buffer reuse and ownership transfer | [Ingestion measurements](performance.md#parser-storage-and-compact-streaming-ingestion-2026-10-15) |
| Fixed-seed statistical diagnostic pilot, 2026-10-15 | 480 verified complete native resident jobs, 32 fixed seeds, five fixtures, independent permutation-corpus calibration; a further 480 native/480 Chromium-WASI replays match exact CSV bytes/order and metadata. No primary full-shuffle flags at the predeclared Bonferroni threshold; all 30 buffer negative-control comparisons flag. Finite diagnostics do not prove uniformity; external-scale statistics remain open | [Design](shuffling-research.md), [results](performance.md#fixed-seed-shuffle-diagnostics-2026-10-15) |
| Per-group reservations, 2026-10-15 | 94 workspace tests, 26 experimental-feature library tests and 22 Chromium contracts pass; native/WASI release builds, formatting, TypeScript and Clippy pass. 64 native A/B/allocation jobs preserve exact output and metadata. Capacity/growth edges, concurrent pressure and mixed resident/external groups are covered; full allocation/RSS accounting remains open | [Accounting and measurements](performance.md#per-group-reservation-accounting-2026-10-15) |
| External native/browser comparison, 2026-10-15 | 144 alternating complete jobs across three shapes/four pipelines match exact CSV bytes/order, conservation, names, lineage, stage metadata and digests. Four additional 1.3-million-row native/browser jobs match across hierarchical merges and the distribution pass-cap fallback. All-feature workspace suite passes 89 tests; TypeScript and UI tests pass. Native and WASI release variants build; merge remains the default after native/browser regression | [Native/browser results](performance.md#external-shuffle-nativebrowser-follow-up-2026-10-15) |
| External prefix distribution, 2026-10-15 | 89 workspace tests passed in default and experimental builds; final 22 library tests, all-feature Clippy and WASI compile check passed. 144 warm native A/B/allocation jobs match v1 output and metadata. Depth/pass limits, equal keys/prefixes, multi-level fallback and failure cleanup are covered. Candidate remains opt-in after regression; controlled storage and browser runtime remain open | [External shuffle results](performance.md#external-prefix-distribution-experiment-2026-10-15) |
| Grouped decode reuse, 2026-10-14 | 84-test workspace suite plus a new routed-buffer/cancellation regression passed; formatting, Clippy and native/WASI release builds passed. 152 A/B/allocation jobs match output and metadata, including a 71-run/two-merge pipeline. No new browser runtime evidence | [Grouped decode results](performance.md#grouped-decode-storage-reuse-2026-10-14) |
| Compact stage ingestion, 2026-10-14 | 83 workspace tests, formatting, Clippy and release WASI build passed. 128 native A/B/allocation jobs match output and metadata; compact dataset/key/sort differential checks pass. Browser startup blocked by missing `libnspr4.so` | [Ingestion results](performance.md#compact-stage-ingestion-2026-10-14) |
| Compact external consumers, 2026-10-14 | 80 workspace tests passed; final decoder refinement passed 15 library tests, formatting, Clippy and release WASI build. 104 native A/B/allocation jobs match output and metadata, including multi-level merges; external decoder corruption and cleanup checks pass. Chromium startup blocked by missing `libnspr4.so` | [External consumer results](performance.md#compact-external-consumers-2026-10-14) |
| Compact resident consumers, 2026-10-13 | 81 workspace tests, formatting, Clippy and release WASI build passed; compact views preserve serialized bytes and spool framing, and iterators retain memory reservations. 104 native A/B/allocation jobs matched across resident, pipeline, spill and multi-level cases; six native/Chromium parity jobs matched | [Compact consumer results](performance.md#compact-resident-consumers-2026-10-13) |
| Balanced boundary scanning, 2026-10-13 | 80 workspace tests, formatting, Clippy and release WASI build passed; decoder/scanner differential tests cover every truncation, invalid UTF-8, oversized counts/lengths and small read buffers. 32 native A/B/allocation jobs and six native/Chromium parity jobs matched | [Boundary scanner results](performance.md#balanced-split-boundary-scanning-2026-10-13) |
| Whole-job profiling, 2026-10-13 | 77 native tests, formatting, Clippy and WASI library check passed; 56 benchmark jobs matched outputs across instrumentation/builds, including a 1.3-million-row multi-level merge fixture. Browser runtime tests were not rerun | [CPU/allocation/sort-time baseline](performance.md#whole-job-profiling-2026-10-13) |
| Radix experiment, 2026-10-13 | 79 native tests in both default and experimental builds, 21 Chromium contracts, formatting and all-feature Clippy passed; 64 native and 18 native/browser benchmark jobs matched, including multi-level merges. Forced collisions, equal keys, common prefixes and scratch exhaustion have differential coverage. Comparison sorting remains the default | [Radix results and decision](performance.md#radix-sort-experiment-2026-10-13) |
| Native, 2026-10-13 | 77 tests and workspace Clippy with warnings denied passed; coverage includes explicit options, fallback, nested pipelines, caps, malformed CSV, cancellation and reservations | [Options validation](performance.md#validation) |
| Existing-operation compatibility | 15 cases × three alternating A/B repetitions, 90 complete jobs; output bytes/order, names, counts, lineage, stages and digests matched | [Raw compatibility results](evidence-originals.md#sha256-cc264f3d7a664571f57f9b753cf85c1c3da7a6e3234733b608def418ddd5ea7d "Original: docs/benchmarks/options-compatibility-2026-10-13.jsonl") |
| Browser, 2026-10-13 | 21 real Chromium contracts passed, including native golden hashes for new options; native/hosted builds, TypeScript and UI unit tests passed | [Browser record and WASM hash](benchmarks/options-browser-2026-10-13.jsonl) |
| Parser/merge, 2026-10-12 | 1,176,480 differential parser cases matched; corrupt frames, buffer reuse, wide rows and merge reservations covered | [Method and scope](performance.md#validation-and-measurement-scope) |
| Inline keys | Byte-identical spool framing and forced-collision resident/external tests; 68 native and 17 browser tests passed at that milestone | [Inline-key verification](performance.md#validation-and-remaining-opportunities) |
| Profiling/cache | Full scans, sorted late keys, corrupt trailers, source replacement, cancellation and mandatory preparation | [Profiling record](performance.md#full-file-input-profiling-2026-10-12) |
| UI plan descriptions | Recorded matrix of 9,372 configuration-only plans and 44 representative scenarios; does not establish data-dependent output counts or coverage of later options | [Generated examples](output-plan-examples.md) |

## Scale and platform gaps

- **Performed:** a billion-row plain-output run of repeated one-column `x` records (about 2 GB), with complete output SHA-256 matching the input. [Scale record](performance.md#billion-row-validation). This was an observational count stress test, with a brief build overlap.
- **Performed:** one billion-row native uniform-v1 shuffle into four balanced outputs, with exact unique-ID/field conservation and a separate lexical-ID/hash recheck. [Full-shuffle point and build scope](performance.md#billion-row-native-full-shuffle-acceptance-point-2026-10-16).
- **Not established:** billion-row parity across final builds/budgets/runtimes, wide-record/high-cardinality and terabyte-scale acceptance, controlled SSD cache-state throughput, storage saturation, or universal memory bounds. The WSL host had less than 1 TB free before source/spill overhead. Smaller repeated native/browser benchmarks cover narrower fixtures.
- **Platform scope:** early Windows GNU and Linux/WSL checks and cross-platform seeded parity are recorded below. macOS is configured in CI but no executed macOS result is recorded here. The latest expanded test counts should not be read as fresh validation on every OS.
- **Browser scope:** real Chromium workers/OPFS, external shuffling, codec roundtrips, cancellation and native parity were exercised. Browser peak process memory, billion-row operation, arbitrary destination devices and broad browser/OS coverage remain unverified. The [existing Cloudflare deployment smoke check](performance.md#existing-cloudflare-deployment-acceptance-2026-10-22) covers one pinned deployed artifact in Windows Chrome with test File/OPFS picker results; the [approved current-build publication](performance.md#validated-current-build-published-to-pages-2026-10-22) additionally verifies served hashes and the same small profile/preparation/export flow in Windows Chrome/Edge.
- **Failure scope:** tests exercise budget exhaustion, cancellation and safe publication. Physical device failure and power-loss durability have not been simulated. Browser export has a completion-marker contract, not atomic directory publication; see [browser limits](browser.md#processing-and-limits).

## Historical validation records

The following milestones preserve original environments, reproduction instructions and limitations. Later evidence above supersedes their test counts and scale status.

## Native correctness

The test suite covers strict CSV grammar and encodings, quoted multiline fields, exact byte boundaries, tuple equality/order, rounding, operation composition, stratification, stable assignment order, seeded shuffle reproducibility, forced random-key collisions, buffer conservation, ZIP64 packaging/selection, compression round trips, checksum failures, cancellation, temp-budget exhaustion, overwrite refusal, and retained input snapshots. CLI tests check unattended confirmation handling; local-server tests check token and origin restrictions and embedded assets.

All 27 tests passed on Windows GNU and on Linux through Ubuntu in WSL. Windows release compilation, formatting, Clippy, and TypeScript checking/building were exercised locally. macOS is covered by the CI configuration but has not been executed on this machine. The portable `chopper-core` crate compiles for `wasm32-unknown-unknown`; the separate browser engine now compiles the shared processing code for wasm32-wasip1 (see browser validation below).

A separate assignment-plus-uniform-shuffle fixture produced byte-identical CSV outputs on Windows with four workers and Linux with one worker (both files' SHA-256 hashes matched). Linux publication was verified on its native filesystem. WSL's Windows mount rejected the required no-replacement rename flag; that path fails safely and is documented as unsupported for Linux publication.

The local web UI was exercised in the shared browser: path selection, country partitioning, exact analysis, confirmation, and ZIP execution completed. Independent 7-Zip validation reported a valid ZIP64 archive containing the three expected CSVs and manifest. Tokenless API requests and requests with an untrusted Origin returned 403.

## Million-row smoke benchmark

Measured on Windows with an AMD Ryzen AI 9 HX 370 (12 cores, 24 logical processors), release build, local storage. This is one warm-machine run, not a portable performance guarantee. Input/output and temporary data shared local storage; storage hardware and OS caching were not controlled.

| Measurement | Result |
| --- | --- |
| Input | 1,000,000 rows; four columns; 128-byte generated payload per row |
| File size | 140,888,917 bytes |
| Pipeline | Uniform seeded shuffle → 10 balanced CSVs |
| Configured working memory | 32 MiB |
| Sort workers | 1 |
| End-to-end elapsed | 9.006 seconds, including analysis and output |
| Analysis elapsed | 6.541 seconds |
| Observed peak Windows working set | 20,000,768 bytes (about 19.1 MiB) |
| Tracked peak temporary data during analysis | 634,666,725 bytes (about 605.3 MiB) |
| Output | 10 CSVs, exactly 100,000 rows each |

Working-set monitoring sampled the process's reported peak counter every 100 ms. This is not a proof of an allocation bound for every workload. Temporary accounting excludes filesystem overhead and final output staging.

An independent streaming Node check verified that each input ID occurred exactly once in the output and its first 128 bits of SHA-256 over the complete fixture record matched the source. The validator is intentionally for the generated single-line fixtures, not arbitrary CSV.

Reproduce with fresh paths:

```sh
cargo run --release --example generate -- scratch/million.csv 1000000 128
chopper split scratch/million.csv --output scratch/benchmark-uniform --files 10 --shuffle uniform --seed benchmark-1 --memory-mb 32 --workers 1 --yes
node scripts/verify-generated.mjs scratch/million.csv scratch/benchmark-uniform 1000000
```

The generator creates a new file and refuses to overwrite. Create `scratch` first. On Windows, executables under `target/release` have the `.exe` suffix. Benchmark generated files are ignored by Git.

## Scale status after the initial smoke benchmark

At this milestone, no billion-row run had been performed. A later [narrow billion-row plain-output test](performance.md#billion-row-validation) closed the count gap; the subsequent [native full-shuffle point](performance.md#billion-row-native-full-shuffle-acceptance-point-2026-10-16) adds one checked permutation workload. Broader scale acceptance and physical-failure testing remain open as summarized above.
## Browser engine validation (2026-10-10)

The browser contract harness passed 11 tests in the shared Chromium preview using real WebAssembly workers and OPFS. It covers order/row caps, impossible balanced counts, malformed records, combined partition/shuffle/allocation/balanced operations, native/browser seeded-output parity, gzip/Zstandard/ZIP input and output roundtrips, UTF-16 output byte caps, temporary budget failure, external shuffle, and cancellation cleanup.

The external shuffle fixture contained 300,000 records (approximately 41.6 MB), exceeding its 32 MiB working budget. It was split into three files and every ID was checked for uniqueness and conservation. The full test (including fixture generation, analysis, shuffle, export, and verification) completed in approximately 6–8 seconds on this development machine. This does not measure peak browser process memory or certify billion-row browser operation.

All 29 native contract/interface/pipeline tests also passed after the WASI integration. TypeScript checking, native Clippy with warnings denied, Rust formatting, and both UI builds passed. The hosted production bundle excludes the test harness. Cloudflare deployment and browser operation on macOS/Linux have not been exercised in this session.

## Pipeline optimization verification (2026-10-11)

The optimized engine passed all 38 native tests and all 12 browser contracts in Chromium on WSL Linux. Native and WASI release builds, Clippy with warnings denied, Rust formatting, and TypeScript checking passed. The browser parity helper was corrected to read descriptive filenames in numeric output order; its original native-generated seeded-output hash still matches.

Sixteen captured pre-optimization pipeline fixtures match every CSV, filename, lineage entry, and stage statistic. Tests also force multiple merge levels and random-key collisions, verify that balanced ranges share their row snapshot, exercise in-memory sorting without spill space, and compare compressed outputs across worker counts. Another 120 randomized comparisons against the previous executable matched successful output or rejection behavior.

Three alternating million-row runs per build and pipeline measured 1.47–2.28× faster end-to-end execution. The 32 MiB shuffle-and-balanced job decreased from 5.39 to 2.37 seconds; its analysis temporary peak decreased from 635 to 358 MB. See [the full measurements, reproduction command, and resource tradeoffs](performance.md). These warm-machine local results do not certify billion-row scale or cold-storage throughput.

## Independent-parent batching removal (2026-10-25)

Astra rejected E2 before the separate bounded removal round; final acceptance
remains with the parent reviewer. The batching/materialization/replay adapter,
exclusive helpers/diagnostics/test hook and native/browser feature wiring are
removed. Ordinary comparison sort/compression workers, shared storage/resources,
serial parent stages and comparison/merge fallback survive. Archived source and
harness bytes are under [history](history/rejected-parallel-groups-2026-10-25/README.md),
with the complete dirty pre-removal tree and generated hosted assets retained
under `.tools/e2-removal-20261025-r8/`.

Fresh Windows checks pass: default workspace Clippy with warnings denied and
locked tests, surviving all-feature workspace Clippy/tests, formatting and
isolated flexible-policy tests. Exact compiled-experiment count is ten and the
removed entry is absent. Existing generic tests retain field/ID conservation,
membership, order/metadata, strict CSV caps, shared admission, cancellation and
native staging/publication rollback coverage. Dedicated E2 replay tests are
archived with the implementation they exercised.

Bundled Chromium 156.0.8078.4 passes the standard hosted contracts, error bridge,
peer cleanup, temporary/persistent interruption and forced-process recovery.
WASI resource reactors pass in base, shuffle-partition and combined surviving
feature configurations; both reactors enabling shuffle-partition use the required
`--shuffle-partition` export mode. This includes shared diagnostic ownership,
last-clone cleanup, exact caps and browser marker/export fault controls. The
[ownership audit](resource-policy-research.md#independent-parent-batching-removal-ownership-audit-2026-10-25)
records the schema/layout effects without weakening resource equations.

Removed-feature Cargo requests and Node/shell wrapper requests fail clearly;
there is no substitution. Failed attempts are retained: fixed feature-array and
integration-count expectations were corrected from eleven to ten, and the shell
wrapper was normalized to LF after a CRLF execution failure. Native UI TypeScript
is unchanged, so `ui/public/app.js` is preserved without regeneration. The final
default production engine and test-free hosted package are rebuilt and checked;
raw commands/results and hashes are in the r8 `round-report.md`.

No performance measurements, deployment or other strategy work were performed.
CLI and retained-owner E2 populations remain separate, including the balanced
gain; see the [decision and limits](performance.md#independent-parent-batching-removal-2026-10-25).
This pass covers this Windows build and bundled Chromium, not new Linux/macOS,
desktop Chrome/Edge, device/scale or physical-I/O claims. E1 remains unresolved;
E3 is next unstarted. Original raw/numerical evidence and E1 snapshots remain.


## Shared exact-plan retained-parent seam (2026-10-28)

`engine::exact_plan::Proposal` shares retained-parent preparation and denial
classification between exact shuffle/partition and streaming-chain fusions. Each
plan retains its original operation indices and borrowed parent identity. The
proposal grants no capacity; operation-specific admitted owners retain existing
ledger and growth limits. Failed preparation drops tentative owners before the
shared cancellation/cleanup check permits typed retry. Emission stays outside that
retry interface, including final sorting in streaming-chain emission: every error
from that call is terminal. No selector, default, schema or feature promotion is
included. Raw ingestion and direct Run keep their separate dispatch contracts.

Streaming-chain fallback replays only the current un-emitted parent through the
original three stages, then copies admitted groups to the caller's sink. Earlier
parents remain once. A late high-fanout regression compares fields, IDs, order,
lineage and stage statistics against original execution across two retained
parents. Existing shared shuffle/partition controls exercise local/shared denial,
competing-owner release/retry, late shape, cancellation, actual temporary unlink
failure and encoded publication. Shared experimental child-lineage controls now
also inject typed local/shared denial at the first and last emitted rows, verify
that no rows replay, and retain failure/cancellation grant-release checks.
Private writer-setup denial before a parent attempt keeps its original fallback.

Executed on Windows x86-64 with Rust/Cargo 1.99.1, Node 22.12.0, WASI SDK 33 and
bundled Chromium 156.0.8078.4:

- Formatting, default and all-feature workspace Clippy with warnings denied,
  and default/all-feature locked workspace tests pass.
- Default WASI build, hosted build, browser functional and bridge checks, peer
  cleanup, temporary/persistent termination, persistent process-kill and direct
  process-kill checks pass.
- Base resource reactor and a reactor enabling both
  `experimental-shuffle-partition` and `experimental-streaming-chain` pass with
  real WASI/OPFS storage. The default engine and test-free hosted UI are restored.
- Code-only Graphify extraction was refreshed after the five Rust source changes.

Durable local runner evidence is under `scratch/exact-plan-2026-10-28/`:
`batch/status.json` and `hosted/status.json` retain declared source/vendor/SDK
identities, numbered full logs, timings and attempt results; their original plans
are `manifest.json`. `toolchain-details.json` records compiler and installed target
versions. The native batch estimated 20 minutes/3 GiB with a 30-minute deadline;
the hosted batch estimated 20 minutes/2 GiB with a 40-minute deadline. Builds ran
serially. Earlier inference/cfg compilation failures and the writer-setup retry
regression remain in failed attempts; corrected final attempts pass. The initial
exploratory compile failure is summarized in `development-failure.txt`.

These checks establish this bounded seam on Windows native and bundled Chromium,
not new Linux/macOS, desktop-browser, external-destination, quota/device-fault,
performance or RSS claims. Other exact fusions still use their existing lifecycles;
broader pipeline coverage and calibrated policy/default changes remain TODO work.

## Native retained state error ownership (2026-10-28)

The native owner tests cover local/shared source capacity edges, zero-capacity
inline fallback, exact 224-byte and split Unicode boundaries, control-character
escaping, independent competing owners and retry, source replacement and
independent response readers through EOF/drop. Existing canonical-state controls
now use the admitted error owner alongside cached Analysis/Profile/Prepared
owners and verify denial preservation and unlocking before send.

Real loopback requests exercise all four worker failure branches, repeated state
reads, replacement clearing, ready cancellation and successful retry. A separate
deterministic profile-cache gate exercises cancellation before a worker error
with the shared pool exhausted, preserving the literal acknowledgement and
inline retained source. The approved fallback is recorded in the
[specification](specification.md) and
[ownership contract](resource-policy-research.md#native-retained-state-error-ownership-2026-10-28).

Run provenance and full logs are retained locally in
`scratch/state-error-implementation-2026-10-28/`; `final-report.json` records exact
source/docs hashes and checks actually completed. Formatting, default workspace Clippy, 30 focused server unit tests, the new
real-server request test and all 328 default workspace tests passed. This
establishes the recorded Windows native build/workloads only. The server module is compiled out on WASI;
no hosted/core/UI source changes require hosted acceptance for this slice.
Progress producers and retained Progress text remain separate open ownership
work, as do source discovery, carriers and OS/thread/runtime allocation coverage.

## Release candidate preparation (2026-10-28)

The 0.1.0 candidate's [public receipt](releases/0.1.0-candidate.json) records the
Windows executable, native/hosted ZIPs, all seven hosted asset identities and
canonical source-input digests. The source remains an explicitly dirty snapshot
based on the recorded original commit. Version alone is not an artifact identity.

The final batch passed 29 declared steps: UI tests/build, Rust formatting,
default/all-feature workspace Clippy/tests, portable-core WASM checking, native
release build, bundled-Chromium standard/bridge/cleanup/interruption checks,
temporary/persistent process-kill and direct-Run process-kill controls, base and
shuffle-partition resource reactors, default engine/package restoration,
TypeScript packaging and production-export/test-asset guards. The restored
package contains no test assets. Durable full inputs, logs and failed attempts
are retained in the private release-preparation archive.

One status replacement failed with Windows error 5 after a package command
completed. That attempt was retained as incomplete; resumption reused only
matching recorded passes and reran the incomplete steps. No validation contract
or atomic-write behavior was weakened. Concurrent status reads are a plausible
holder, not an established cause.

The packaged Windows executable reports `chopper 0.1.0`. A five-row CSV export
preserves exact fields/order with a two-row and 64-byte CSV cap, and malformed
input fails without publishing its destination. This automated CLI smoke is
separate from the required real-user system-picker/external-destination test.

The previous hosted deployment's six served assets and reconstructed `_headers`
match all seven pinned hashes. Isolated read-only restoration verifies served
bytes, COOP/COEP and production WASM exports. Its private archive passed separate
scoped-reader download, outer/member hashes and nested restoration checks. The
owner confirmed there is no previous native release. See
[rollback readiness](maintainer/release-rollback.md) for known limits and restoration steps.

Installed Chrome 156.0.8078.48 and Edge 156.0.4314.50 each pass the 19 declared
hosted standard/bridge/cleanup/interruption/resource/package checks against the
same product source. Their final default packages match the candidate's seven
asset identities. These are disposable automated contexts, not actual system
picker/external-destination acceptance.

This establishes the recorded Windows/native and three Chromium browser workloads. It does not
add macOS/Linux build, actual system-picker, external-device/quota/power-loss,
larger-scale, performance-selector or complete-RSS claims. Release review and
actual-user acceptance remain open.

## Explicit memory spill regression (2026-10-28)

Human acceptance exposed a partition → exact 80/20 allocation → automatic shuffle
failure at explicit 512 MiB on a 676 MB CSV, in both native and hosted builds.
The same job succeeded at Auto/default/256 MiB. A synthetic grouped input
reproduced the shared 128 MiB admission denial: retained sort rows consumed the
capacity needed to construct the spill writer. The original candidate executable
`c87a724d4b9d39ec5911e5f8470dae4397cda65546a5d266beac5b374511cc45`
must not be released.

The sorter now bounds its retained-row target by both one quarter of the exact
job budget and half the observed shared admission ceiling. Reservations still
enforce local/shared limits; the target grants no capacity and promises no RSS
bound. Numeric job settings and reported budgets remain exact. See the current
[execution decisions](execution-decisions.md) and
[resource ownership contract](resource-policy-research.md).

The native/WASI regression runs 60,000 rows through partitioning, exact 80/20
allocation and automatic shuffle at 32 and 512 MiB with a 16 MiB shared pool.
It checks exact quotas, field/ID conservation, identical seeded CSV names/bytes,
the unchanged requested/reported budget, bounded peak reservations and final
release to zero. The base hosted reactor reports a 9,125,703-byte reservation
peak. A separate owned-row sorter control covers explicit Sort and Auto with a
4 MiB pool. The new browser fixture initially used an unsupported WASI default
temporary-directory lookup; its failed attempt is retained. Giving it an explicit
workspace path, as existing fixtures do, allowed the actual regression to run.

A complete native replay uses a 694,388,909-byte synthetic CSV with 6,500,000 rows
(SHA-256 `c51566367f1155f4a4b23cf60099d474d442de89cb265b9194b5cabc1a057632`).
At 512 MiB, all 16 output CSV names and SHA-256 values match the retained successful
256 MiB baseline. The final executable is
`771a33f8cc34e6bf871bdbe1349669251adc30d48c4fa51d4a585cf75a12409b`.
This is a synthetic correctness replay, not a test of the owner's original file
or a performance measurement.

The corrected source passed the same 29-step native/bundled-Chromium batch,
including default/all-feature Clippy/tests, portable-core WASM, hosted correctness,
cleanup/termination, both resource reactors and production restoration/export
guards. Source drift and a Clippy failure in a concurrently edited example were
retained and affected checks rerun. Installed Chrome 156.0.8078.48 and Edge 156.0.4314.50 each passed the same 19
hosted checks on the corrected source, including the regression. Both restored
the exact seven production asset identities in the revised package receipt.
The replacement ZIPs passed member readback and packaged CLI export/cap/failure
cleanup checks. Real system-picker acceptance and release review remain required.

## Owner release acceptance (2026-10-28)

The owner confirmed the original approximately 676 MB partition/allocation/shuffle
job succeeds at 512 MiB in both corrected builds, then reported completion of
the requested real-picker/external-destination export, cancellation and malformed
CSV smoke tests with no issues. The owner approved the release and Git cutover
as is. This is owner-reported acceptance of candidate revision 2, including
native executable `771a33f8cc34e6bf871bdbe1349669251adc30d48c4fa51d4a585cf75a12409b`.
The reported terminal establishes Windows; the hosted browser version was not
reported. It adds no other-platform, device-fault or scale guarantee.

## Release CI worker-control portability (2026-10-29)

The first post-cutover CI run passed evidence retrieval/audits, portable core,
hosted acceptance and macOS native checks. Linux default/all-feature tests failed
before the complete-Run denial fixture executed: its unconditional four-CPU
benchmark-host precondition rejected two-CPU runners. Windows was cancelled by
the native matrix failure policy. The failed run and full logs are retained.

Restricting the local Linux test process to two CPUs reproduced the exact
`E5 W0 host ineligible: need four available CPUs` failure. The ordinary regression
fixture now checks the actual host's automatic worker count, capped at four for
its 256 MiB job. All local/shared denial, cancellation, injection-boundary,
publication and cleanup assertions remain. Two-CPU controls resolve to 1/2/1/2
workers and pass; four-CPU controls resolve to 1/4/1/4 and pass. The unchanged
benchmark parser rejects the two-CPU output and accepts the four-CPU output,
preserving the frozen benchmark's separate eligibility requirement.

Only the native `cfg(test)` fixture changes; the production engine, WASI engine,
UI and packaged artifacts are unchanged. This correction supplies no new
performance result or default-policy claim. Configured CI is rerun on the
corrected source before publishing the approved artifact bytes.

## Verified 0.1.0 publication (2026-10-29)

The owner-approved cutover updated only the two prepared owned refs using atomic
expected-old-SHA leases. A fresh remote clone passed integrity checks. None of
the 655 private-original registry paths is present in that clone or reachable
exported history; original local bytes and verified private backups are retained.
This does not promise remote object erasure or immediate storage reduction.

All seven configured CI jobs passed on release source
`7d78706c432f34742bbc29c17be9261002a6816a`: native Windows/Linux/macOS, combined surviving features,
portable-core WASM, hosted acceptance and authenticated evidence retrieval/audits.
The preceding failed run is retained with the test-only CPU portability proof.
No production code changed after owner acceptance or artifact packaging.

The published Windows and hosted ZIPs, artifact receipt and checksum file were
downloaded from GitHub and matched all four hashes. The downloaded native
executable reports `chopper 0.1.0`. Chrome 156.0.8078.48 and Edge 156.0.4314.50
verify all six served hosted bodies against the frozen seven-file package,
effective COOP/COEP headers, absence of the WASM resource-test entry point,
exact CSV/manifest/completion-marker export, seed retention and preparation.
The live fixtures inject picker results into disposable OPFS contexts; actual
picker acceptance is the separate owner-reported pass. The prior hosted package
and all verified recovery archives remain retained without automatic deletion.
See the [publication identities](releases/0.1.0-publication.json). Repository
visibility remains private. Later documentation-only publication recording does
not change the tagged, CI-validated product source or artifact bytes.
