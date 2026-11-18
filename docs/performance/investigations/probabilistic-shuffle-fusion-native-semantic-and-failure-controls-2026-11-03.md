## Probabilistic shuffle fusion: native semantic and failure controls (2026-11-03)

**Decision: retain the isolated candidate after scoped semantic and cleanup
acceptance on Linux and native Windows; browser transfer and admission/retry
acceptance remain open.** The [control record](../../benchmarks/probabilistic-shuffle-native-semantics-2026-11-03.json)
and [diagnostic patch](../../benchmarks/probabilistic-shuffle-native-semantics-2026-11-03.patch)
extend the prior prototype and fixed-capacity controls. Production dispatch,
source and defaults remain unchanged. No timed performance panel or speed
inference accompanies these controls.

Each runtime executes ten untimed complete-engine cases. Four cases compare
baseline/candidate with stratified probabilistic allocation on columns 0 and 2
(record ID and payload), four partition parents and two consecutive uniform
shuffles. The first pair uses ordinary random keys; the second forces primary-key
collisions. They preserve exact CSV names, bytes and order, output records and
17 logical Analysis fields, including all four original logical stages. An
independent verifier checks every ID/field and strict row/serialized-byte caps.
Named zero-percent children and final temporary/private/grant cleanup stay exact.

The forced-primary diagnostic zeros only the shuffle key's first 16 bytes in
both plain-Random producers and allocation composite keys. The original
categorical membership generator, child domains and v1 `compare_ties` refinement
remain unchanged. A separate single-parent 20,000-row pair at 4-MiB shared
capacity preserves exact output through observed external runs and merging
under those forced collisions. This is deterministic tie-refinement acceptance,
not evidence about natural collision frequency or a distribution proof.

Four further cases inject failure at the public `Preparing operation 2 of 3`
notification, before allocation/output emission. One baseline/candidate pair
fills the remaining 32-MiB pool through an independent competing grant and must
report typed shared admission denial. Another sets cancellation and must report
cancellation. All preserve absent final/private output, empty temporary storage,
one input-start visit and competitor-only residual reservations; releasing that
competitor returns the pool to zero. These are public-boundary controls, not a
proof of the new domain vector's internal denial boundary, arbitrary late pressure
or cancellation during fused merging.

Linux Rust 1.99.1 passes focused controls, formatting, workspace/all-target Clippy
with warnings denied and locked workspace tests. The general suite skips the
research module rather than repeating its diagnostic panels. Native Windows/MSVC
Rust 1.99.1 passes the same ten focused cases on byte-matched source/vendor/native
UI inputs. The copied source, fixtures and target stay on NTFS. Its existing
checkout remains at the explicitly guarded revision with its dirty file preserved;
no synchronization, reset or security-policy changes occur. This is Windows
focused acceptance, not a new full Windows workspace or performance pass.

An initial source-edit guard found two plain-Random producers where the setup
expected one. It stopped before writing source, building or launching a job.
The revised guard instruments both producers consistently; the original setup
failure is retained. No scientific case failed in this phase. Full manifests,
source inventories and logs remain in Linux
`scratch/prob-shuffle-semantics-20261103T1454/` and its native Windows counterpart.
The Windows records/status are also copied locally for interpretation. No private
archive upload is claimed.

These results establish within-runtime baseline/challenger parity. They do not
record direct cross-runtime CSV hash parity, browser behavior or a general
completion-domain proof. A before-emission admission failure could still favor
original execution; safe per-parent fallback requires its own preparation/emission
boundary and cost evidence. No production promotion follows from these controls.
