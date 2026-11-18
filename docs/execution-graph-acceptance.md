# Hosted execution graph acceptance

[Issue #48](history/prior-issues.md#issue-48) defines the behavior;
[#58](history/prior-issues.md#issue-58) owns integrated acceptance.
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active backlog and specs. The representative matched
performance gate now **passes within the recorded workload/build/browser scope**.
The [126-job result](evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830)
retains every eligible observation and the earlier unmet reports. Calibration,
harness controls and diagnostic probes are not acceptance timing samples.

## Default production path inventory

All graph fixtures use the public hosted Run action, production WASI, real workers
and OPFS. Enabled/disabled pairs independently inspect CSVs, manifests, membership,
seeded ordering, strict caps and valid completion markers. Names below identify
fixture families in `node scripts/test-browser-graph.mjs`.

| Production work | Acceptance families |
| --- | --- |
| Direct reading/CSV publication, final output mapping | `direct` |
| Internal preparation, routed/sorted grouping, resident uniform/Fisher–Yates | `partition`, `uniform`, `fisher-yates`, `partition children` |
| Original fused mappings and overwritten shuffle annotations | `fusion`, `elision`, `later elision` |
| External spill, merge, hierarchical merge, final traversal | `external spill`, `hierarchical merge` |
| Grouping handoff and actual ordered-file provenance/reuse | `grouping fallback reuse` |
| Exact/probabilistic allocation, exact strata and intermediate artifacts | allocation families, including parent/strata/downstream-shuffle cases |
| Balanced shared ranges, terminal and fused traversal, interleaved membership | split families, including nested/parent cases and cap/insufficient-row failures |
| Gzip/Zstandard/selected ZIP input and gzip/Zstandard/ZIP output | codec families, including UTF-16 input/output and corrupt/ambiguous archive failures |
| Saved-and-closed destination files versus marker readback confirmation | graph parity plus lifecycle/termination cases |

The 42 graph families establish these concrete paths. Experimental algorithms
are not enabled to obtain coverage. This inventory does not claim exhaustive
profiling, every combination, native presentation or standalone Analyze/Prepare
graphs. [Inspection acceptance](execution-observation.md#advanced-inspection-and-significant-events)
adds actual fused/repeated work, shared views, frozen configuration, event
navigation, focus/viewport retention and targeted 1280px/390px visual review.

## Composed lifecycle and bounded resources

`node scripts/test-browser-graph-lifecycle.mjs --composed` combines signature-detected
gzip input, partition/uniform work and gzip export with the sixteen interruption
and degradation cases. Processing cancellation pauses after an actually observed
completed spill; confirmed work remains available. Export close, marker
write/close/read, old-generation confirmations, observer loss/rendering/transport
and cleanup failures retain their independent artifact checks. Gzip exports are
decoded using Node's independent reader before checking strict CSV-byte/row caps.

`node scripts/test-browser-termination.mjs --persistent --process-kill --composed`
combines gzip input/output, partition and child Fisher–Yates with actual persistent
browser restart and process-kill boundaries. Independent decoded fields,
partition membership, manifest rows and seeded CSV hashes check committed results;
missing markers retain incomplete-export semantics. Test-only routes/controls
are absent from the production package.

`node scripts/test-browser-graph-bounds.mjs` first completes and independently
verifies a real Run. A focused observation-boundary adapter then saturates all
1152 physical identities plus four direct categories, memberships, safe numeric
fields, 128 significant events and one-message delivery credit. Overflow stays
bounded and explicit. A second real Run at the smallest manual 32 MiB budget
receives saturated focused-state updates while its real observation acknowledgement
is deliberately withheld. Cancellation does not wait for that acknowledgement;
its processing interruption publishes no destination output/marker.

The logical census counts five cumulative/queued/page copies of numeric values
(8 bytes), booleans (1) and UTF-16 value text, plus DOM/configuration text, fixed
serialization/grant/mask envelopes and 2048 bytes of additional fixed-category/
source/inspector allowance per retained step. It checks the existing 32 MiB
logical envelope separately from the 4 MiB serialized message-content envelope.
Fixed schema/code strings, JS container/allocator overhead and browser backend
buffers are outside that logical-value census; it is not a JS heap or RSS cap.
The producer's 65536-record cap, callback/serialization admission and last-owner
release remain covered by native and both WASI resource-contract reactors.

## Overhead methodology and retained intermediate results

`scripts/benchmark-execution-graph.mjs` generates bounded synthetic CSV fixtures,
uses OPFS-backed input files and drives the real hosted Run action. Its disabled
mode removes observation credit only at an internal worker-request boundary;
there is no public Job option. Collapsed and expanded modes use the same build
and capture. Each matched block has a fresh persistent Chromium profile; all
three modes share its input/configuration/seed, storage context and resource
ceilings. Expanded mode explicitly opens and centers the graph viewport once;
each completed sample verifies that viewport is fully visible. It does not follow
new cards automatically. Six repetitions use all six mode permutations per workload, not a
Cartesian strategy matrix. Actual quota estimates and order are retained. The benchmark currently runs on
Linux/WSL so it can attest the selected test-owned browser executable using a
CDP browser PID and `/proc/PID/exe`. Every matched block records and checks its
executable hash/version. Playwright's launcher-reported Chromium path is kept
separately because its default headless launch selects Chromium Headless Shell;
that reported path alone does not identify the running binary.

The primary monotonic page timer runs from the public Run action through the
actual successful request reply after destination export and marker completion.
Public UI completion after cleanup is recorded separately because status polling
is quantized at one second. Fixture generation/copying, hashing and independent
verification are outside the timer. Post-timer streamed checks establish literal
fields/IDs, partition/balanced membership, strict 8 MiB CSV caps, manifests and
markers; ordered CSV/lineage/digest identities must match across modes/blocks.

The four declared long workloads are direct output; routed partition/shared
balanced ranges followed by resident fused partition/uniform work; external
spill/merge at 32 MiB; and 2048 parents with child Fisher–Yates summaries. Their
single collapsed calibration jobs took approximately 47, 85, 46 and 168 seconds.
Those four jobs verify shapes and intended paths, and are excluded from the
matched comparison. Requested working budgets are 32, 512, 32 and 64 MiB; these
are working-accounting limits, with the browser's existing aggregate admission
policy, not browser memory/RSS claims.

The matched population fixes a 6 GiB temporary ceiling. An initial tiny control
using 16 GiB failed normal admission against Chromium's roughly 10 GiB quota,
despite ample host free space; its raw failure/profile remain retained. A revised
6 GiB control passed twelve complete jobs. Calibration used automatic temporary
headroom; it is not an eligible paired timing baseline. No algorithm or resource
policy changed to accommodate these controls.

The predeclared gate is at most 5% slowdown for each enabled mode of each workload,
using the ratio of separate medians. The exact distribution of all 6^6 paired-block
resamples must also have a one-sided 95th-percentile slowdown at most 5%. This is
conditional measurement uncertainty, not a population or tail guarantee. Report
raw samples/order, min/max/MAD and paired ratios. No pooling, failed/incomplete
attempt omission or inconclusive-as-pass is permitted.
`scripts/analyze-execution-graph.py` checks order, configuration identities,
complete independent verifications, exact artifact parity and balanced mode order;
a separate command requires all eight gates. Its regression controls use literal
2%/4% effects and a single 10% regression that cannot be hidden by other cells.

Local task-owned plans, full logs, fixture/provenance hashes, retained failures and
profiles are under `.tools/execution-graph/58-*` in the issue worktree. They have
not been uploaded or deleted. Earlier calibration/control metadata recorded the launcher-reported executable
path. Those records remain unchanged and are not accepted overhead samples; the
replacement cohort records the actual running executable. Cohort 002 completed all
72 jobs in about 165 minutes, with independent artifact parity in every workload.
Its [compact result and raw line anchors](evidence-originals.md#sha256-fd637745e75a20bb67867b422948b7b834dd3d3a1ce74d9089c55b3d70cbd30e)
retain the actual build/browser identities, samples, spread, uncertainty and local
raw SHA-256. Both direct and resident/fused cells passed. External merge failed
(collapsed median +2.61%, upper 95% +22.39%; expanded median +8.05%, upper +21.82%).
High-cardinality medians were +1.80%/+2.60%, but uncertainty upper bounds were
+5.33%/+6.19%; those cells remain unmet. No sample was omitted or pooled to obtain
a pass. These measurements do not identify the cause of the variation.

Cohort 001 was interrupted after a correctness audit reproduced loss of
last-observed physical metrics at page shutdown. Its six timed/five verified
samples remain retained and excluded. The renderer now preserves unfinished
row/byte measurements, separately labels prior confirmed completed totals and
honors actual terminal measurements. Cohort 002 used this corrected renderer.

The matched plan declares a 300-second job limit and a sampled 24 GiB owned-tree
stop threshold with a 48 GiB host-free reserve. A separate six-job external-merge
diagnostic adds page CPU profiles/process metrics to distinguish runtime variation,
collection and rendering. Its instrumentation changes the timing context, so it
cannot establish acceptance. Original raw evidence and profiles remain local;
[Evidence storage](evidence-storage.md) owns archival classification. Git retains
small summaries/manifests/hashes; no upload has been performed.

The first precision extension completed all 36 added jobs and retained every
original observation, for 108 verified jobs. Its [combined report](evidence-originals.md#sha256-d59c9c71f4f2c9df68b38a55c9bf35f02e2ff8fcc1ebd9f2a2ccfed6f9682c47)
uses twelve blocks for external/high-cardinality and six for direct/resident.
At that checkpoint seven cells passed. Expanded external merge had median
slowdown -0.0693%, but exact conditional upper95 +7.6153%; acceptance remained unmet. Its six
added expanded samples are stable around 45 seconds, while three original slow
samples remain in the calculation. No original sample was discarded.

After reviewing that remaining precision gap, a final bounded study adds six
external-merge blocks only: 18 new jobs, retaining all prior 108, for 126 total.
This is a second disclosed post-gate sampling decision, not an automatic retry
or a fresh-only report. It is the final data-only augmentation; an unmet result
will remain unmet. No production optimization or algorithm change is justified
by the completed diagnostic probes.

`scripts/extend-execution-graph-analysis.py` validates the first two cohorts and
computes exact count-vector-weighted paired bootstrap results at twelve blocks.
`scripts/final-execution-graph-analysis.py` validates all three cohorts, requires
the final workload to be the single still-unmet workload, rejects overlapping
admitted jobs, and retains all source hashes/physical JSONL anchors. It compares
build/harness/browser/runtime/storage/fixture/configuration and exact artifacts.

At eighteen blocks the final analysis uses 1,000,000 paired bootstrap resamples
with predeclared seed 735780. To bound simulation error conservatively, it uses
`epsilon = sqrt(log(2/1e-6)/(2*1000000))` and the empirical `0.95 + epsilon`
quantile, approximately the 95.2693rd percentile, as the upper95 bound. Under
independent uniform bootstrap resampling, the [DKW–Massart CDF bound](https://arxiv.org/abs/1107.5356)
limits simulation undercoverage to 1e-6 per cell, at most 2e-6 by union bound for
the two simulated cells. Python's seeded PRNG implementation is recorded for
replay. This bounds numerical simulation error, not sampling/population error or
optional stopping. Both the median and conservative upper bound must still be
at most 5%. Exact six/twelve-block references remain unchanged. Regression
controls compare the conservative calculation against exhaustive six-block
results, preserve known effects and old regressions, and reject invalid cohorts.

These conditional uncertainty reports explicitly disclose post-gate selection
and make no population/tail or optional-stopping-adjusted confidence claim.
The regression command is `python3 scripts/test-execution-graph-extension.py`.

## Final accepted result

The final study completed all 18 added jobs. The combined [126-job summary](evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830)
retains all 72 original jobs and both precision additions (36 + 18), including
all original slow observations. All independently checked ordered artifacts
match across modes/cohorts. All eight median and upper95 gates pass. Direct and
resident/fused use six blocks; high-cardinality twelve; external merge eighteen.
The largest observed median slowdown is about 0.233%; the largest conditional
upper bound is about 4.726%. These are scoped observations, not future-job/tail
or population performance guarantees.

The [validation receipt](benchmarks/execution-graph-validation-summary-2026-11-05.json)
links retained native/UI/hosted/resource/restoration logs and source-matched
production asset identities. Bounds/cancellation evidence supplements actual
Run verification with focused synthetic state; it is not a heap/RSS cap. The
final production package excludes prototype/test assets and test-only WASM entry
points. Native Windows/macOS performance, exhaustive compositions and native graph
presentation remain outside this acceptance scope. No deployment is authorized.
