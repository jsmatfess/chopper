## Hosted data movement follow-ups (2026-11-26)

This investigation compares three independent hosted changes against
`51e706c3c6fb9c4e2e3bd07b352799a4a8b15329`. Timings start at the Run request
and end after verified marker publication and worker retirement. Fixture import,
independent output readback, and removal of successful exports are outside the
clock. Each pair reverses arm order from the previous pair. Warmups are excluded.
The persistent bundled Chromium 156 and installed Chrome 149 profiles ran on a
single WSL2 ext4 host with uncontrolled caches. The File holdout supplies a
local disk File through Chromium's file input and retains OPFS for workspace
and destination. The other cohorts use file-backed OPFS input.

### Source prefetch

Reuse one existing 256 KiB lookahead window for a single explicit Uniform
shuffle when hosted Run receives a selected `.csv` file of at least 128 MiB
and plain output. Both arms use identical WASM. The engine sort runs, effective
working plan, and measured peak reservations match. The browser bridge reports
2.5 MiB plus 24 control bytes for its combined streaming capacity. A rejected
lookahead uses the synchronous read. An unresolved speculative read owns only
its Blob and reply slot during retirement. See the
[browser contract](../../browser.md#processing-and-limits).

### Shuffle then Balanced publication

Check the existing hosted writer guard after a terminal Uniform or Auto
sorter prepares its final traversal. Plain UTF-8 output, Auto grouping,
no calculated columns, and a validated CSV lower bound of 96 MiB select
the existing buffer when working headroom covers the smaller of 512 KiB
or the CSV byte cap, twice the configured record ceiling, and 1 MiB.
The same producer supplies exact original Balanced quotas and order.
Size and headroom declines use the encoded snapshot before opening output.
[Direct execution](../../direct-execution.md) ·
[Issue #100](https://github.com/jsmatfess/chopper/issues/100)

### Consecutive Balanced traversal

The initial screen uses the opt-in three-step prototype. The production
candidate covers exactly two root terminal Balanced operations after validating
at least 256 MiB of retained packed input. Auto grouping, plain UTF-8 output,
no formulas, valid row and file counts, and working headroom for four configured
records plus 8 MiB qualify the shared traversal. It emits both original nested
rounding boundaries, leaf order, and per-stage statistics. The physical graph
records both operations on one traversal with its source, rows and emitted
leaf counts. The ordinary snapshot is still used for publication.
[Nested lineage ownership](nested-balanced-lineage-growth-and-leaf-ownership-2026-10-22.md) ·
[Rewrite rules](../../pipeline-rewrites.md)

### Verified paired Runs

Readback checks every field and unique source ID, hierarchy, names, stage
counts, CSV caps, marker count and retired workspace. Nested Runs compare
ordered CSV digests and exact boundaries as well. Randomized Runs use real
Run entropy and independently check the requested quotas and row conservation.
The ranges are observed minima and maxima.

| Workload | Input MB | Pairs | Baseline s | Candidate s | Paired s saved and range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Small prefetch decline | 1.0 | 3 | 0.146 | 0.146 | -0.000 [-0.014 to +0.000] |
| Uniform prefetch, bundled Chromium | 450.0 | 3 | 12.032 | 10.734 | +1.195 [+1.183 to +1.567] |
| Below file-size floor, Chrome | 131.2 | 2 | 4.013 | 3.922 | +0.091 [+0.019 to +0.162] |
| Above file-size floor, Chrome | 145.5 | 2 | 4.420 | 3.820 | +0.599 [+0.582 to +0.617] |
| Large Uniform prefetch, Chrome | 1,264.9 | 3 | 32.342 | 29.199 | +3.119 [+3.085 to +3.262] |
| Disk File Uniform prefetch, Chrome | 690.8 | 3 | 17.691 | 15.795 | +1.896 [+1.862 to +2.026] |
| Small Shuffle → Balanced decline | 1.0 | 3 | 0.165 | 0.157 | +0.001 [-0.002 to +0.009] |
| Uniform → Balanced, bundled Chromium | 450.0 | 3 | 11.873 | 10.613 | +1.243 [+1.238 to +1.401] |
| Below validated output floor | 97.7 | 2 | 3.017 | 2.991 | +0.027 [+0.009 to +0.044] |
| Above validated output floor | 108.2 | 2 | 3.316 | 2.944 | +0.372 [+0.355 to +0.390] |
| Large Auto → Balanced, bundled Chromium | 1,264.9 | 3 | 32.026 | 28.301 | +3.764 [+3.531 to +4.017] |
| Three-step Balanced prototype, bundled Chromium | 414.2 | 3 | 11.543 | 10.014 | +1.529 [+1.433 to +2.009] |
| Two-step below packed spool floor, Chrome | 241.2 | 2 | 6.534 | 6.402 | +0.132 [+0.119 to +0.144] |
| Two-step above packed spool floor, Chrome | 248.0 | 3 | 6.612 | 6.192 | +0.420 [+0.385 to +0.442] |
| Large two-step Balanced, Chrome | 1,228.2 | 3 | 31.579 | 29.532 | +2.049 [+1.993 to +2.078] |
| Independent packed-floor decline, Chrome | 244.1 | 5 | 6.405 | 6.382 | +0.091 [-0.021 to +0.130] |
| Independent smaller decline, Chrome | 37.3 | 3 | 1.186 | 1.197 | -0.011 [-0.041 to +0.018] |

[Uniform prefetch screen](../../benchmarks/hosted-data-movement-prefetch-screen-2026-11-26.jsonl) ·
[Uniform prefetch on OPFS](../../benchmarks/hosted-data-movement-prefetch-holdout-2026-11-26.jsonl) ·
[Uniform prefetch on a disk File](../../benchmarks/hosted-data-movement-prefetch-disk-holdout-2026-11-26.jsonl) ·
[Shuffle → Balanced screen](../../benchmarks/hosted-data-movement-shuffle-balanced-screen-2026-11-26.jsonl) ·
[Shuffle → Balanced cutoff and Auto](../../benchmarks/hosted-data-movement-shuffle-balanced-holdout-2026-11-26.jsonl) ·
[Three-step Balanced prototype](../../benchmarks/hosted-data-movement-nested-screen-2026-11-26.jsonl) ·
[Observed two-step Balanced holdout](../../benchmarks/hosted-data-movement-nested-selector-holdout-2026-11-26.jsonl) ·
[Independent below-floor Balanced controls](../../benchmarks/hosted-data-movement-nested-selector-decline-2026-11-26.jsonl)

### Publication, admission, and controls

The Uniform source-prefetch pairs held the sort plan and measured working
peak fixed. The source rejected one scheduled read and completed through
synchronous fallback. An injected read left unresolved allowed cancellation
to retire the workspace and destination. A malformed final record failed
without a completed export.

The largest Shuffle → Balanced case avoided about 1.265 GB each of tracked
temporary reads and writes, and retained the same measured peak working
reservation. Both arms retired the workspace and removed incomplete output
after a write fault, marker write fault, cancellation, byte-cap rejection,
file-count rejection or malformed tail. Marker injection happened after
all eight CSVs closed. A 190 MiB managed temporary cap rejected the snapshot;
the buffered writer verified all 420,003 rows within that cap.

The first Shuffle → Balanced timing launch ended after all sixteen
measurement receipts were written and before verification. A separate
verification attempt checked the original frozen inputs and complete receipts.
The first publication fault harness could inspect results before worker
retirement. A synchronous retirement check resolved the harness race and
captured the actual cleanup state for each arm.

The 1.228 GB two-step Balanced case avoided 1,313,314,474 tracked
temporary read bytes with the same measured peak working reservation.
Its output CSV digests, stage statistics, and nested boundaries match
exactly. The two-step guard records one observed traversal of both
operations, with the original dataset as its source and the exact number of
leaves as its group count. The authoring scope keeps deeper chains opt-in.

The first below-floor Balanced control followed the ordinary route in both
builds. Its median apparent gain of 0.132 seconds exceeded the symmetric
0.12-second timing band. Fresh below-floor fixtures with different widths
and row counts passed the original limits, using five and three pairs. The
original attempts remain separate. The branch declines for insufficient
live headroom, undersized inputs and unavailable row or file counts. Both
writers reject cap violations, and cancellation after output began retired
the workspace and removed incomplete output.

Adopt all three guarded hosted paths. The measurements support the checked
regimes and runtime. Temporary traffic is tracked logical storage. Actual
device I/O, browser RSS, cold-cached timing and native performance were
outside this experiment.

[Prefetch rejection, unresolved cancellation and malformed input](../../benchmarks/hosted-data-movement-prefetch-faults-retired-2026-11-26.jsonl) ·
[Shuffle → Balanced faults and quota](../../benchmarks/hosted-data-movement-shuffle-balanced-faults-retired-2026-11-26.jsonl) ·
[Two-step Balanced failure and cancellation](../../benchmarks/hosted-data-movement-nested-selector-faults-retired-2026-11-26.jsonl)

### Replay

Build separate WASM engines with `node scripts/build-browser.mjs` from the
recorded base, optionally applying only the relevant source patch with
`patch -p1`. For the three-step nested screen, enable
`--features chopper/experimental-nested-balanced` on the second arm.
The comparisons used Rust 1.99.1, Node 22.23.4 and locked UI dependencies.
The source-prefetch comparisons use the same WASM for each arm and separately
compile the baseline and candidate worker. The first environment receipt
pins each binary, browser, compiled worker, driver, case config and harness.

Copy the [base harness](../../benchmarks/guarded-hosted-partition-shuffle-harness-2026-11-26.mjs)
to `scratch/replay/harness.mjs`. Apply the follow-up timing diff with
`patch -d scratch/replay -p1 -i ABSOLUTE_PATCH`. Run
`node scratch/replay/harness.mjs CONFIG NEW_OUTPUT_ROOT` from the repo root.
Set `browser` to the recorded executable, `engines` to the baseline and
candidate WASM paths in recorded order, and `runTimeout` to 120 seconds for
the timing cohorts or 75 seconds for fault checks. Source-prefetch configs also
map both names in `engineWorkers` to their TypeScript sources. Use each fixture
receipt as a `cases` item after removing `kind`, `bytes`, `sha256` and
`job`. For the File, two-step observed, or fault cohorts, apply their
individual harness diffs after the follow-up timing diff. Verifiers accept
CONFIG, the new `runs.jsonl`, and a new summary JSON path. The nested
verifier looks for the pair verifier beside it as `verify-results.py`.

[Timing harness diff](../../benchmarks/hosted-data-movement-harness-2026-11-26.patch) ·
[Disk File harness diff](../../benchmarks/hosted-data-movement-disk-harness-2026-11-26.patch) ·
[Observed nested harness diff](../../benchmarks/hosted-data-movement-nested-harness-2026-11-26.patch) ·
[Fault harness diff](../../benchmarks/hosted-data-movement-fault-harness-2026-11-26.patch) ·
[Pair verifier](../../benchmarks/hosted-data-movement-pair-verifier-2026-11-26.py) ·
[Nested observation verifier](../../benchmarks/hosted-data-movement-nested-observation-verifier-2026-11-26.py) ·
[Fault verifier](../../benchmarks/hosted-data-movement-fault-verifier-2026-11-26.py) ·
[Source-prefetch worker patch](../../benchmarks/hosted-data-movement-prefetch-worker-2026-11-26.patch) ·
[Shuffle → Balanced engine patch](../../benchmarks/hosted-data-movement-shuffle-balanced-engine-2026-11-26.patch) ·
[Two-step Balanced engine patch](../../benchmarks/hosted-data-movement-nested-selector-engine-2026-11-26.patch)
