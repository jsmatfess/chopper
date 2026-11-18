## Public preparation retained-parent retry acceptance (2026-10-21)

The [shared native/WASI contract](../../evidence-originals.md#sha256-a47cb1f4ab96707a95dfd8e2245774a7a9afebb637c6a09b9775b22add3a6bee "Original: docs/benchmarks/public-preparation-resource-validation-2026-10-21.json")
enters through the public `prepare_with_memory_pool` API with a real immutable
CSV, rather than constructing a retained dataset directly. It exercises input
metadata validation, ingestion, original-stage dispatch, intermediate retained
shuffle/partition, downstream partitioning, encoded planning and real Rust
publication. The job requests `balanced(2) -> uniform -> partition(key) ->
partition(text)`, seeded v1, 32 MiB job memory, one worker, a separate 64 MiB
shared pool and 32 MiB temporary ceiling. No production admission branch or
injection API is added; the existing progress callback holds synthetic competing
capacity at the public stage boundary and releases it at the existing retry event.

An unpressured public preparation fuses both parents without replay. The pressure
case leaves 256 KiB of shared headroom after ingestion/balanced grouping: the
first eight-row narrow parent commits, while the second parent's 320 KB key
causes typed shared denial during tentative preparation. Releasing the competing
owner permits exactly one original-stage replay. Complete published CSV bytes
and complete output metadata compare directly with the unpressured control;
the report hashes long lineage keys only after that equality check to keep its
stored size bounded. Independent decoding verifies all 16 IDs exactly once,
original field text, balanced-parent/key/text membership, header and per-chunk
row counts. Nine UTF-16LE/BOM/CRLF CSVs obey the 1,000,000-byte strict cap and
total 5,121,016 bytes; their concatenated BLAKE3 is
`b67637e5cedb6320e301703da496dfb140bb79ef2fd3dd5f2b0dc908b83e8dac`
on both Windows and WASI. The fixture hash is
`989fa9f23fec42032f84e885e39fa48decec71b6f87a266c979a577efcce17bb`.

Two failure cases use the same public entry. Cancellation at the retry boundary
prevents replay/publication; persistent competing capacity preserves typed shared
denial. After each public result is dropped, the ledger contains exactly the
competing owner and nothing else, then reaches zero after its release. Input
bytes are unchanged, temporary workspaces are absent, successful verification
outputs are explicitly removed, and failure cases publish nothing. The real
Chromium/OPFS test reactor asserts these results alongside the existing retained
dataset, encoded-publication and JavaScript-export contracts. The test-only code
is excluded from production builds. Initial compile errors and a 128 KiB fixture
that denied dispatch before the intended attempt are recorded as development
failures, not acceptance; the final 256 KiB fixture reaches the required seam.

This closes the caller-owned-pool public preparation slice. It does not exercise
automatic process-pool discovery, CLI/server/browser production request dispatch
injection, JavaScript export after this new fixture, external destinations,
termination or complete allocation/RSS coverage. Fixture construction and
verification allocations remain outside the engine reservation claim. Existing
experiment gates, ceilings, replay identities and defaults are unchanged.

The [cross-runtime comparison](../../evidence-originals.md#sha256-c8b7fa1de7e8bc7a4dd9ec434b9163091670fb82e6ea8a8de5b99a9409ed8390 "Original: docs/benchmarks/public-preparation-cross-runtime-2026-10-21.json")
binds source hashes and explicit JSON pointers/selectors for the Windows,
[Linux/WSL targeted pass](../../evidence-originals.md#sha256-a51c21d9b9f50949c01f09e2efd3f13f5fa9fe27f654739ad3219c232c23feac "Original: docs/benchmarks/public-preparation-linux-2026-10-21.json")
and final Chromium WASI reports. Their complete expected reports match, including
encoded and metadata identities and all nine chunk descriptors. The
[full validation record](../../evidence-originals.md#sha256-628a511a2c1b1cc671d9922ab589cb5ea3dd93b1590cd27ea8c481c590c6d268 "Original: docs/benchmarks/public-preparation-full-validation-2026-10-21.json")
passes formatting, default/candidate all-target Clippy, the default Windows
workspace (139 library tests), candidate library (154 tests), 28 UI tests,
native UI/debug builds, 25 standard Chromium contracts, bridge, peer cleanup
and base/candidate resource reactors. A separate
[17-feature compatibility pass](../../evidence-originals.md#sha256-e950608c6fa2bfc0ab1a9b36852d4821b9fd2209fb6d5e161adc06c84e0c31d2 "Original: docs/benchmarks/public-preparation-feature-compatibility-2026-10-21.json")
passes 220 library tests and all-target workspace Clippy. These are separate
passes, not an added cumulative test total. Clean hosted packaging removes test
assets and passes the production export guard; production WASM retains
`c18a5139ebb5c0b960ad84cd5f62794f055cca66fbb23922bfc2615dfaa18ea3`.
This is a targeted Linux check, not a fresh full Linux/macOS workspace claim.
