## Probabilistic shuffle fusion: prepared spill browser acceptance (2026-11-05)

**Decision: retain scoped persistent-Chrome acceptance of the real spill-owner
variant; no promotion or speed inference.** The [raw acceptance record](../../evidence-originals.md#sha256-54334de75d25e17cc06f8b8c018fe99aeb476cd3c0de2d9c15eb356bcc9f8e0d)
extends the [new owner control](../../performance.md#probabilistic-shuffle-fusion-prepared-spill-owner-control-2026-11-05)
to the changed storage lifetime in WASI, rather than reusing earlier browser
coverage of the observation-only variant. Production and execution graph/retry
integration remain separate.

The frozen events-transfer-v1 input has 20,000 quoted Unicode/multiline records,
four event types, partition -> probabilistic 80/20 allocation -> uniform shuffle,
the original seed, a 64-MiB job budget, one worker, Auto grouping and
1,024-row/65,536-byte output caps. One fresh native Windows baseline and one
baseline/candidate pair in persistent installed Chrome 156.0.8078.48 pass
independent fields, unique IDs, group/lineage, CSV caps and inventory checks.
Exact per-file CSV SHA-256 signatures and 14 logical Analysis fields match all
three jobs, with the expected extra browser export warning. Membership exactness
uses the same-version baseline, not an independent randomization oracle.
Completion-marker and owned-workspace cleanup checks pass.

Complete post-publication logical temporary reads fall from 9,482,079 to
3,975,297 bytes and writes from 9,107,470 to 3,750,929 bytes in the browser pair.
These counters exclude physical I/O and RSS. Unreplicated elapsed values remain
raw and support no speed claim. The picker writes into OPFS, not an external
File System Access destination; cache is uncontrolled.

The candidate also passes the 35 default browser contracts, bridge and peer
cleanup. The existing 22-job persistent forced-process-termination lifecycle
harness passes all five preparation/CSV/marker checkpoints, same-client retries,
closed-export preservation and post-restart recovery. Its preparation pause now
occurs immediately after the real prepared spill writer is constructed, at
`Prepared spill writer`, rows zero, before packed traversal. Cancellation and tab
close observe five workspace files at that point; the active owner remains
locked, active peer cleanup skips it, and abandoned cleanup releases it. The
forced browser process exits, restart releases locks/removes five abandoned
workspaces, and a fresh exact-CSV job completes while preserving earlier exports.
This covers those checkpoints, not arbitrary interruption or device faults.

Private [shared instrumentation](../../benchmarks/probabilistic-shuffle-spill-browser-2026-11-05-shared.patch),
[activation](../../benchmarks/probabilistic-shuffle-spill-browser-2026-11-05-activation.patch)
and [lifecycle adaptation](../../benchmarks/probabilistic-shuffle-spill-browser-2026-11-05-lifecycle.patch)
replay exactly against the retained bases in the record. The accepted owner
prototype enables fusion outside tests; this study explicitly disables it in the
baseline and enables it only for WASI in the candidate. Shared infallible traffic
tracing and the WASI-only pause event change no Analysis/schema/capability fields.
Baseline/candidate UI and worker assets match; default seven-asset packages reject
the test-only resource entry. A separate contracts package borrows the exact
candidate engine with matching Rust/vendor bytes, leaving both original packages
test-free. No browser resource-test WASM, Edge, other-device or deployment claim
is added.

Fresh Linux-filesystem formatting/all-target Clippy passes for both byte-matched
private Rust/native-embedded snapshots. Native build, transfer and contracts
batches pass 8/8, 10/10 and 5/5 gates. Preserve earlier source-assembly, lint,
Linux/NTFS routing and dependency-copy failures: the interrupted Linux batch is
incomplete, and the failed hosted build is not a passing batch. Its individual
successful baseline WASI build is reused only after original/new relevant input
and artifact hash checks. Two WASI builds and one native build total consume the
frozen build caps; no engine job is repeated. Full sources, binaries, dependency/
SDK provenance, plans, failed attempts and logs remain under private
`scratch/prob-spill-browser-20261105T0502/` in both checkouts, with no archive upload.
Broader shared-pressure/temp-failure feasibility still needs separate evidence.
