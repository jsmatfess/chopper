## WASI retained-parent retry acceptance (2026-10-21)

The [retained-parent contract pass](../../evidence-originals.md#sha256-cb5985832d8517fec3ee77f22a0e68db93a2fa4daf37ceb345517452e4ce8f17 "Original: docs/benchmarks/wasi-retained-parent-contracts-2026-10-21.json")
closes the recorded WASI retry-boundary gap for exact shuffle/partition's
retained-dataset seam. The existing native fixture and terminal-emission test
now delegate to a shared helper, additionally compiled into the separate resource
reactor only with `experimental-shuffle-partition`. No production API, default
planner choice or algorithm/replay identity changes.

The fixture has two eight-row parents: ordinary keys first, then eight identical
320,000-byte keys. After the first parent completes its sink group, a synthetic
owner leaves only 128 KiB of shared ledger capacity, forcing typed admission
denial in the late parent's tentative preparation. The owner reserves accounting
capacity rather than an equivalent heap allocation. All four modes require one
fused parent/eight fused rows, one retry entry and final workspace removal with
zero reservations.

| Retry-boundary mode | Result | Completed sink groups / rows |
| --- | --- | --- |
| Release the competing owner | Original stages replay successfully; exact logical snapshot/stat hashes match baseline | 2 / 16 |
| Cancel after release | Cancellation stops before replay | 1 / 8 |
| Retain the competing owner | Typed admission remains terminal | 1 / 8 |
| Release, then cause an actual pathname unlink error | Cleanup failure stops replay; three orphan bytes/path owner remain until final context drop | 1 / 8 |

These are completed retained sink groups, not published destination folders.
The successful snapshot contains row IDs, decoded text/order, lineage and exact
flags; logical statistics are compared separately. Windows, WSL Linux and WASI
match fixture BLAKE3
`16d32f81ce2e00d88b3476ae7112a7e01dcd63273c10e1d0a7e4e09767e70799`,
snapshot BLAKE3
`63812162d082fc543c8e905c266b50fbded1f39826ee0d48313f94c1dcd03d71`
and statistics BLAKE3
`832d3502c4d915a7f1b7e909eacf498edd54d38617c4167bfae2e47460509ed4`.
Path capacities and physical offsets are not logical parity fields. A separate
denied sink receives exactly one row call, completes zero groups and observes
zero retries, proving emission admission errors cannot replay rows.

Each context requests 32 MiB temporary space and a 64 MiB shared accounting
ceiling. The browser test store is now 128 MiB, so retained baseline/actual data
fit alongside the fixture. Actual successful context and OPFS logical peaks are
16,005,200 bytes; terminal modes peak around 10.56 MB. The candidate resource pass
observes at most twelve OPFS files/handles, zero bytes before worker cleanup and
no workspace directory afterward. Peaks from separate modes are not added.
Fixture/snapshot JSON allocations are test scaffolding; these values establish
neither a memory census nor RSS/physical-I/O limits or whole-job performance.

The base resource build explicitly omits the candidate report, and its browser
runner verifies absence. The candidate build requires it through
`--resource-contracts --shuffle-partition`; CI and [browser instructions](../../browser.md#tests)
run both variants. Base test WASM SHA-256 is
`f13d077754cf339f4dd6efe8fd1ff298b783812a9638adf25b9f26de7bbd6086`;
candidate test WASM is
`cfad20d3f8b94dc55145b94ca5b38c1c538e8bbcabdc776e4a188746046e8515`.
Both are separate from the production engine. The actual candidate module fails
the production export guard, and final packaging removes every test asset while
preserving the tested production WASM.

Windows default workspace tests pass (135 library), the recorded 17-feature
library configuration passes 209 tests, and default/combined all-target Clippy
and formatting pass. Eight focused candidate tests pass on Windows and WSL.
Two sandboxed Windows test launches were blocked by Application Control before
execution; ordinary approved outside-sandbox runs pass and are recorded
separately. No policy settings or executable contents were changed to bypass
that rejection. Rebuilt default WASI passes 25 Chromium contracts plus bridge
check. Base/candidate resource suites are contract observations, not timing
samples or additional independent performance jobs.

This verifies the fixed fixture's late-parent rollback, earlier-parent preservation,
cancellation, persistent denial, cleanup-error retry boundary and terminal
emission behavior on the recorded runtimes. It adds no injected-retry CSV cap,
destination export, OPFS delete/media failure, scale or macOS acceptance. Bounded
per-parent observations/decision audit, a calibrated cost selector, remaining
allocation boundaries and broader resource/browser coordination stay open in
[TODO](../../../TODO.md). No new benchmarks or defaults are promoted.
