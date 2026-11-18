## Persistent hosted spill-block E1 comparison (2026-10-24)

Astra reviewed E1 as **unresolved**; the final disposition is appended below.
This round does not remove or promote the feature. The [raw round bundle](../../evidence-originals.md#sha256-431d629431e835f4b401b1fdc09b87177380826d8d7d10533e73db715c26ec72 "Original: docs/benchmarks/spill-blocks-persistent-e1-2026-10-24.json")
preserves the reviewed plan, commands/status/logs, initial source inventory,
build-source comparison, environment, individual attempts, per-file inventories,
manifest records, timestamps and logical-space samples. Its summary is derived
from exactly twelve timed jobs, three per variant per selected cell. The dedicated
`scripts/benchmark-e1-persistent.mjs` and `ui/tests/e1-persistent.ts` leave the
historical generic comparison harness unchanged; their executed bytes are retained
in the bundle. No native timed job, historical matrix or automatic repeat ran.

One bundled Chromium 156.0.8078.4 persistent profile on Windows ran alternating
pairs V1/C, C/V1, V1/C for columns/global and rare_wide/balanced, both N=100000.
The latter is a wide-record/downstream risk control, not a historical browser
loser. Both fixtures contain id,payload,c0..c30; row-zero rare-wide payload is
1800000 x bytes. Seed external-comparison-v1, seeded_v1, uniform, 32 MiB, one
worker, 2097152 maximum record bytes, no compression and explicit UTF-8/header/
comma/LF/no-BOM settings match between variants. Resolved defaults and fixture
hashes are recorded. Timed jobs retain the original no-cap workloads. Origin
quota was 10 GiB and persisted permission was false. Cache was warm/uncontrolled;
a saved profile does not establish persistence permission or power-loss durability.

Columns/global v1 median was **0.730890 s** (observed 0.671700–0.759030), versus
blocks **0.783200 s** (0.775195–0.789830): candidate median / v1 median minus one
is **+7.2%**, slower. Rare-wide/balanced v1 was **0.843865 s**
(0.797760–0.881920), versus blocks **0.831830 s** (0.831570–0.893835): **−1.4%**,
with overlapping ranges. These small n=3 cells do not identify a reliable
selection threshold or establish a general persistent-hosted speed benefit.
The decision-changing question is whether the modest rare-wide difference is
a repeatable workload-specific benefit sufficient to justify retention; this
bounded round adds no runs to resolve that uncertainty. Parent review owns the
disposition and whether any fresh experiment is warranted.

Elapsed starts immediately before analyze and ends after complete, which awaits
export, closed completion marker and worker/workspace cleanup. Complete with an
error is rejected. Fixture creation/loading, browser startup, defaults/pickers,
builds, post-job verification and successful destination disposal are excluded.
Both exact shapes passed untimed v1/candidate parity before timings, and each
timed output passed every-ID/every-field/header/count checks, exact per-file
hash/order, logical digest/stages/output lineage, balanced quotas/membership
against seeded v1, manifest CSV byte/count checks and valid marker file counts.
The complete current retained-owner equation includes the validated optional
decision-audit grant. Output inventories are retained before/after export and
successful disposal. All timed/parity candidates used blocks with zero fallback.

Columns used five runs/five merge inputs, rare-wide six/six; all had one merge
operation, no resident sorts, and candidate rows encoded exactly 100000 in five
or six files. Raw records conservatively mark merge depth unknown. Inspection
of the current MergeRows constructor counter, together with those actual
counters and no rewritten rows, supports a single merge level for these cells;
this does not infer historical hierarchical depth from aggregate counters.
Candidate stored blocks were 22295588 and 24095588 bytes, representing
36488890 and 38288873 v1 bytes respectively. Preparation logical read/write
traffic fell from 36488890/45078015 to 22295588/30884713 bytes for columns and
from 38288873/48678792 to 24095588/34485507 for rare-wide. These are engine
counters at ready, distinct from export reads and physical I/O.

Peak workspace reservations were 8658467/8659043 bytes (v1/blocks columns) and
10723216/10723936 (rare-wide); reservations are not RSS. Simultaneous sampled
workspace-plus-export logical sizes ranged 43827787–44613997/29896557–30420695
bytes for columns and 47643154–48167362/33974077–34236204 for rare-wide.
The test-only worker build samples its existing successful-operation size ledger
at most every 25 ms of activity, 16–21 samples per timed job. It creates no extra
sync handles and performs no profile scans during jobs. Samples are non-atomic
lower bounds, not exact live peaks or physical I/O; collection/postMessage cost
is equal instrumentation but uncalibrated. Fixture/profile files, filesystem
metadata and implementation buffers are outside this scope. No independent
peaks are added. Final export sizes include CSVs, manifest and marker and vary
slightly with diagnostic/timing JSON; individual inventories retain exact sizes.
CPU, RSS, allocator traffic and device measurements are null.

Current candidate native codec controls (five tests: roundtrip/wide, admission,
constructor fallback/retry, quota/footer, corruption/truncation and cancellation)
pass. Candidate standard hosted, resource, bridge, peer cleanup, persistent
interruption/restart and pinned forced-process termination controls pass; hosted
standard controls include UTF-16/BOM caps and temporary-budget/cancellation
cleanup. Separate selected-shape wide-row strict-cap rejections pass for both
variants with empty output/workspace and successful subsequent timed retry.
Hosted lifecycle controls use the candidate artifact and real workers, including
marker-free interruptions and committed-marker preservation, but their pause
fixtures do not establish block-specific corruption/constructor-denial injection
coverage; that narrower codec coverage is native. No correctness gate or timed
job failed. An initial forced-process control used the restored baseline and is
excluded from candidate coverage; the pinned candidate rerun passed. A relative
clang version-query invocation failed to launch and its absolute-path retry
passed. Both invocation issues remain recorded, without treating them as feature
rejections or additional timing observations.

WASM SHA-256 identities are v1
`059f6ac45a5c47583906780974d8736a8d25d6593126f91ac18fc03b3945b7a8`
and candidate `ce880a4bad6bea90ebd27229d119e2f782ee5119acf4517585b603e33493edcc`,
from identical current Rust sources differing only in experimental-spill-blocks.
Inventory includes tracked/nonignored untracked sources, complete ZIP/zstd vendor
trees and Cargo.lock; only the two new non-Rust harness sources changed across
builds. Rust/Cargo 1.99.1 and WASI SDK 33 clang 22.1.0 are recorded, as are the
native codec validation executable and worker/harness build hashes. UI tests/build
pass. Final default engine rebuild, hosted packaging and test-free export guard
pass. Original ui/dist and top-level WASM artifacts were snapshotted; all 1130
initial source/vendor entries matched before implementation. Preservation has
one limitation: builds reused Cargo caches, and the native test dependency
executable/PDB was rebuilt without a prior byte snapshot. Original ignored cache
bytes cannot be attested; this does not affect the verified source baseline.
The retained fixtures, profile, copied WASMs, native validation binary and snapshots
remain in `.tools/e1-persistent-20261024T151800Z`. No unknown/preexisting material
was deleted, no commits or deployment occurred, and TODO/E1 disposition is unchanged.


### Astra final E1 review and disposition (2026-10-24)

Astra reviewed both harness sources in full, the six existing-file changes against
orientation, all twelve timed attempts, sampled resource arrays, native codec and
hosted gate logs, default packaging and post-job metadata verification. Astra
independently recomputed n, medians and ranges and verified the paired WASM hashes.
The preceding numerical results and historical round narrative remain unchanged;
this decision supersedes their pending-review status. The raw bundle's original
decision field remains the historical experiment record.

**Unresolved.** Under the explicit rule that overlapping or inconclusive results
remain unresolved, this bounded run earns neither retention nor removal. Keep
experimental-spill-blocks opt-in unchanged and E1 unchecked. The earlier private
many-column win did not survive this persistent comparison (+7.2% median elapsed
time). Rare-wide's −1.4% median has overlapping ranges and loses two of three
matched pairs. Actual paths show 5/6 runs, one merge, 100000 block rows and zero
fallbacks; marker and cleanup checks pass. Stored blocks and sampled logical space
shrink, with small reservation deltas, but no useful elapsed-time win or feasible
runtime/shape guard is established. No physical-I/O, RSS/CPU or exact peak claim
follows. No numeric threshold or final product selection is implemented.

The possible decision-changing question is whether rare-wide complete-job benefit
is repeatable and materially exceeds observed run variation and measurement
overhead enough to justify a feasible runtime/shape guard. Answering needs a
separately bounded approved follow-up, not more runs in this round or automatic
expansion. TODO remains the sole checklist, with E1 next among unfinished retention
items. Native-only codec fault injection and the overwritten, unsnapshotted Cargo
cache executable/PDB remain explicit limitations; original cache bytes cannot be
attested. No corrective deletion or rebuild is required.

### E1 harness prerequisites and reproduction boundary

`node scripts/benchmark-e1-persistent.mjs TASK_DIRECTORY` is the experiment phase,
not a standalone build workflow. Use a new task directory: the harness refuses an
existing attempts.jsonl and creates static/ and other evidence with exclusive
writes. Before invocation, install UI dependencies (`npm --prefix ui ci`) and
bundled Playwright Chromium (`npm --prefix ui exec -- playwright install chromium`),
and meet the Rust/WASI SDK prerequisites in [browser setup](../../browser.md).
Prepare matching current-source feature-off baseline.wasm and
experimental-spill-blocks candidate.wasm copies in TASK_DIRECTORY, retaining
source/features/build hashes before later builds overwrite generated artifacts.
Prepare ui/dist through the hosted build; the harness copies it and rebuilds its
dedicated page and workers using ui/node_modules. The persistent origin must have
more than 1 GiB available quota; retain the disposable profile and failures.

The directory must also contain successful (exit_code = 0) *.result.json gate
records named candidate-build, baseline-build, candidate-standard, native-codec,
candidate-resource, candidate-bridge, candidate-cleanup,
candidate-termination-persistent and candidate-termination-kill-pinned. These are
prerequisites to produce and retain honestly, not placeholder files. Candidate
lifecycle gates must use the pinned candidate artifact, including the forced
process-kill check; native codec injection has the narrower coverage stated above.
The raw bundle retains the reviewed plan, exact build/gate command records and
logs, artifact identities and executed harness sources. The retained local plan
and logs are in .tools/e1-persistent-20261024T151800Z/reviewed-plan.md and its sibling
*.result.json/*.log files; implementation-report.md lists the actual sequence,
including the excluded unpinned control and failed version-query invocation.
Use those records with [the build and test workflow](../../browser.md), then restore
the default test-free package as documented there. This documents reproducibility
prerequisites only and authorizes no new measurements.
