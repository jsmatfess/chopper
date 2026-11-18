## Zstandard output context admission (2026-10-23)

The [`Zstandard output owner`](../../../crates/chopper/src/output/zstandard.rs) admits
the pinned context/workspace estimate plus zstd-rs's fixed 32 KiB output Vec
before constructing the encoder. The stream keeps level 3, window log 21,
checksum enabled, unknown source size, no dictionary and no internal workers.
The grant survives explicit finish and failure-time codec destruction; abandoning
an encoder preserves the previous no-implicit-finish behavior. Publication
buffers remain independently owned and concurrency ceilings do not change.

The [source audit](../../evidence-originals.md#sha256-979b30c210a43fe9392008bc394f35619cb53727612848e5eceef9f75147855d "Original: docs/benchmarks/zstandard-output-source-audit-2026-10-23.json")
records the Rust/C version chain and estimator assumptions. A runtime version
guard precedes the static-linking-only estimate call. Its bound covers both
row-matchfinder choices; workspace resize frees before replacement. Exact
dependency pins and binding exposure add no experimental compression setting.
On native Windows, the C estimate is 3,663,377 bytes and the complete allowance
is 3,696,145. Three independent streaming `CCtx::sizeof` probes observe 26,452,
3,663,377 and 3,663,377 bytes for empty, Unicode and 3 MiB-plus incompressible
fixtures, all within the context bound. This is requested context/workspace
storage, not allocator usable-size or RSS.

Shared contracts cover six local/shared edges, concurrent owners and
denial/release/retry. Twelve destination cases check explicit finish,
abandonment, write failure and finish failure; callbacks assert live grants.
Six successful finish/abandonment cases compare exact bytes with the previous
direct encoder recipe. The existing publication-worker test now includes the
context allowance alongside its writer buffer through worker transfer/finish.
New admission can reject a tighter job that previously left this storage
uncharged. The [ownership contract](../../resource-policy-research.md#zstandard-output-context-admission-2026-10-23)
retains the broader boundary.

The [20-command Windows validation](../../evidence-originals.md#sha256-67c304f5ca3487bc90b963f72c65cb62b09e5765061a56f2de9f6512cf669920 "Original: docs/benchmarks/zstandard-output-validation-2026-10-23.json")
and [six-command Linux/WSL validation](../../evidence-originals.md#sha256-c13ec5c77601e51f7f9efe9fd20cb1e1c3a8be97a0eb495d7d6fa464abd16b92 "Original: docs/benchmarks/zstandard-output-linux-validation-2026-10-23.json")
complete with unchanged compilation-source inventories. Windows passes 252
default workspace tests, 309 combined-feature Chopper tests, formatting/default
and combined Clippy, UI's 28 tests/build, native release and shared resource
contracts in bundled Chromium, installed Chrome and Edge. WASI admits 3,692,601
bytes, with observed C context sizes of 22,908, 3,659,833 and 3,659,833. The
rebuilt production WASI engine passes 25 standard Chromium contracts, including
compression round trips, caps and cancellation, then final packaging removes
test assets. The [package record](../../evidence-originals.md#sha256-19cdfc1d04b5bfb29cf4e245d5f5553097a92d6a5c2b6db4de5232984af3d475 "Original: docs/benchmarks/zstandard-output-package-identities-2026-10-23.json")
pins 25 native test executable identities, release identity, all seven production
hosted files, absent resource-test export and the active upstream feature tree.

The [retained-binary CLI comparison](../../evidence-originals.md#sha256-170bcceaba18b178b546abe75e8bccb0fa24bb11a868a390613604d78edc4939 "Original: docs/benchmarks/zstandard-output-native-parity-2026-10-23.json")
verifies its baseline binary against the prior ZIP/deflate package hash before
running both binaries on identical sources. Two fixtures cover capped Unicode
CSV and a 36,000-row stream spanning the configured window. All compressed
output hashes and per-output manifest records match exactly; row/byte caps hold,
and rebuilt CLI decoding preserves every field and row order. Eight successful
commands and removed temporary fixtures are recorded. This is before/after
correctness evidence, not a timed performance comparison or scale claim.

The input audit found a separate requirement: the default build can dispatch
legacy frames after a modern frame through version 0.4-0.7 ZBUFF constructors.
Those contexts/buffers are outside the modern DStream estimate and do not use
the parent custom allocator. Input admission remains open rather than treating
the modern estimate as complete or disabling legacy support. Source/job trees,
parent discovery, native runtime/stacks and error/OS/allocator internals also
remain separate. No performance, physical-I/O, scale, device or full RSS-cap
claim follows; the local build remains distinct from the published Pages build
and macOS remains deferred.
