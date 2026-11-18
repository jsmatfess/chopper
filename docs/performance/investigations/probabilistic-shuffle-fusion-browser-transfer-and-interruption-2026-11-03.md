## Probabilistic shuffle fusion: browser transfer and interruption (2026-11-03)

**Decision: retain the isolated candidate after scoped native/browser output
transfer and browser interruption acceptance; no promotion or speed conclusion.**
The [transfer record](../../benchmarks/probabilistic-shuffle-browser-transfer-2026-11-03.json),
[matched traffic instrumentation](../../benchmarks/probabilistic-shuffle-browser-trace-2026-11-03.patch)
and [replay harness](../../benchmarks/probabilistic-shuffle-browser-harness-2026-11-03.patch)
keep the actual code, checks and limits separate from earlier native timings.

Both default WASI packages are freshly built from frozen baseline/candidate
source with the same post-publication atomic-counter instrumentation. Each has
exactly seven production assets and no resource-test entry point; only engine.wasm
differs. Rust 1.99.1, existing WASI SDK 33, vendors, UI/workers/dependencies and
artifacts are captured by the build records. A fresh Windows/MSVC native baseline
build supplies the reference rather than relying on an older executable.

One native CLI reference and one fresh persistent installed-Chrome pair use the
20,000-row events-transfer-v1 fixture: four event types, Unicode and quoted
multiline fields, partition -> probabilistic 80/20 allocation -> uniform shuffle,
64-MiB job memory, one worker and strict 1,024-row/65,536-byte CSV caps. The browser
is Chrome 156.0.8078.48 on Windows, with a separate disposable persistent profile
per cell. Export targets an OPFS-backed picker, not an external native filesystem.

Every field and unique ID, partition/allocation lineage, serialized cap, file size
and inventory passes independent verification. Both browser outputs exactly match
the native reference's CSV names, bytes, order and output lineage. Fourteen logical
Analysis fields match, with only the established browser non-atomic-export warning
added. Both completion markers validate and post-success cancellation removes the
workspace. The old preserved-child-order verifier assertion is deliberately removed
for this shuffle recipe; repeated capped chunks may share a logical group. Seeded
order and membership are checked by exact reference parity, not an independent RNG
oracle. The deterministic fixture generator/version/seed remain pinned.

| Complete browser Run/export temporary counter | Baseline | Composite candidate |
| --- | ---: | ---: |
| Logical bytes read | 9,482,079 | 3,975,297 |
| Logical bytes written | 9,107,470 | 3,750,929 |

The traffic reduction transfers. These Context counters include metadata/read-ahead
through native engine publication, not final normal-file writes, JS export traffic,
RSS or device I/O. Existing harness clocks remain raw diagnostic fields; a single
pair is excluded from performance comparison and supplies no percentage speed claim.

A separate candidate contracts copy leaves both seven-file packages untouched.
The 35 standard browser contracts, UTF-8 error bridge and peer workspace/lock cleanup
pass. One adapted persistent process-kill harness uses a 100,000-row
partition -> probabilistic allocation -> uniform Run for its preparation case and
pauses specifically at `Serializing output`, row 65,536. Cancellation and owner-tab
closure at that live fused-emission point remove owned workspaces. Other export and
marker phases retain their original small limits-only explicit-preparation flow;
they are not additional fusion-specific cases. The generic raw harness flag
`direct_run=false` describes that original mode, while the adapted preparation
branch explicitly calls Run. The retained patch records this distinction.

The same harness restarts the same-origin persistent profile after force-killing
only its test-owned Chrome PID. Five live workspaces remain until cleanup, then
are removed after locks release. Closed result files, completed exports, earlier
success and unrelated entries remain byte-identical; invalid markers stay invalid,
complete markers stay complete, and a fresh recovered job succeeds. Production
worker artifact hashes remain unchanged and the disposable profile is removed.
This is browser-process interruption/recovery coverage, not a power-loss/device-fault
claim. It does not replace the unrun resource-reactor/optional-feature matrix.

All five paired-build steps, the fresh native build, ten transfer/verification
steps and five candidate acceptance steps pass without a failed attempt. Full
source/SDK/toolchain/asset identities, raw records, profiles and logs remain private
under native Windows `scratch/prob-shuffle-browser-20261103T1510/`; Linux retains
plans and compact copies of records/status for interpretation. No archive upload,
production deployment, default change or execution-graph change occurs.

Internal admission, retry cost and arbitrary dynamic shared-pressure feasibility
remain open. This evidence establishes scoped runtime transfer and lifecycle
acceptance rather than a complete completion-domain proof or promotion decision.
