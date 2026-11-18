## Bounded retained-parent decision audit (2026-10-21)

The [decision-audit contract pass](../../evidence-originals.md#sha256-871b72b64daa13ccc45f6469c09d88ba1e7baa26da5cd8e9bf7594bc1590e204 "Original: docs/benchmarks/bounded-parent-decision-audit-2026-10-21.json")
and [native/WASM build identities](../../evidence-originals.md#sha256-af39c8187560b6e720e5031e275a7b26fce0ff08150a1d38c42d9e472e351ae1 "Original: docs/benchmarks/bounded-parent-decision-audit-builds-2026-10-21.json")
implements the next observation slice behind `experimental-shuffle-partition`.
On the first eligible retained parent, the context attempts to reserve a fixed
16-record vector. It retains 3,328 charged bytes on Windows x64 and WSL Linux,
and 3,200 bytes in this WASI build, through the last context owner. Contexts
without eligible retained parents allocate no audit vector. Collection denial
sets an explicit flag and omits records without becoming an execution error.
Successful collection consumes working headroom and can shift spill/retry
boundaries; its time and memory overhead have not been benchmarked.

Each record identifies the original shuffle/partition indices and retained
parent ordinal/offset/exact row count. Preparation observations separate decoded
and successfully keyed row prefixes, payload lengths, maximum field count and
actual row/key heap capacities. Heap maxima cover the keyed prefix, exclude
descriptor allowances and are not a simultaneous working-set peak. Separate
completeness flags expose partial observations. Context counter deltas include
failed tentative work and original-stage retry; they do not isolate per-parent
grants, RSS or physical I/O.

Outcomes distinguish fused commit, original-stage commit and terminal failure,
with admission/preparation/retry/emission phase and typed local/shared denials.
Cancellation and cleanup failure remain explicit. The first 16 records form a
bounded prefix, with completed/omitted counts and collection denial; they are
neither representative sampling nor a complete replay log. Policy remains
`experiment_gate_v1`; selector and calibration are null. No thresholds,
eligibility, capacity ceilings, seeded identities or defaults are promoted.

Windows default workspace tests pass (135 library tests), as does the recorded
17-feature library pass (214 tests), default/combined all-target Clippy,
formatting and 28 UI tests/build. Linux passes ten focused candidate tests and
three audit tests. The actual 18-parent native regression retains 16 records,
omits two and observes a late 100,002-byte payload while matching original-stage
logical output. Tests also cover below/exact/above vector-capacity admission,
last-context lifetime and exact execution after optional collection denial.

The candidate-only Chromium 156.0.8078.4 resource reactor passes all four shared
retry modes and terminal-emission assertions. Windows/Linux/WASI match the
recorded logical hashes, parent identities, completeness, outcomes and denial
phases. Target-dependent heap/path capacities, offsets and context counters are
excluded from cross-runtime parity. Final reservations and workspaces release.
The test reactor is rejected by production packaging; the final hosted build
contains no test assets and retains production WASM hash
`e75a886a263584f6d7aa2f9e2e24d5c222583d5f509145c1c544c86663d208d9`.
Default/base browser variants retain their preceding checkpoint coverage and
were not rerun in this pass. Cost selection, encoded CSV caps under injected
retry and destination publication/export acceptance remain in [TODO](../../../TODO.md).
