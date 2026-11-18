## Analysis stage-statistics admission and sharing (2026-10-23)

[`Stages`](../../../crates/chopper/src/engine/stages.rs) replaces the raw stage vector
in Analysis with one fixed-capacity admitted owner. The engine reserves the
validated operation count before requesting a CSV record, reconciles actual
vector capacity and admits the shared controller. Private appends check the
complete incoming length against the operation count and capacity, and require
unique ownership. They cannot grow or copy a shared payload. Zero operations
allocate no stage vector/controller. The public Rust field has an owner type;
serialized stage arrays and their scalar records remain unchanged. A tight
budget can now deny formerly uncharged stage storage.

Analysis clones share counters and admission through serialization, discarded
preparations and returned execution results. Concurrent native final drops use
the existing shared-payload destruction rule. Streaming/flexible temporary
statistics already use fixed arrays; consecutive/nested traversals use bounded
stack counters. Caller construction/deserialization, explicit copies and runtime
stack costs remain outside this heap grant. The
[ownership contract](../../resource-policy-research.md#analysis-stage-statistics-ownership-2026-10-23)
records these limits and the `stage_stats_reserved_bytes` diagnostic.

The [Windows run](../../evidence-originals.md#sha256-0e403ed58e92e0badb6063a07842727b4ba9c5a0b55010b09df41ba06a5fb5de "Original: docs/benchmarks/stage-stats-validation-2026-10-23.json") passes
258 default workspace and 315 combined-feature Chopper tests; the
[Linux/WSL run](../../evidence-originals.md#sha256-8308baf5bb7fcf06349c699895da42e08beda496033178e844eab8689e88eb86 "Original: docs/benchmarks/stage-stats-linux-validation-2026-10-23.json") passes
261 and 318 respectively. Each suite also passes five read-only compile-fail
doctests. Default/combined Clippy, formatting, UI's 28 tests/build and the native
release build pass.

The 64-stage fixture retains 3,144 bytes on 64-bit native and 3,120 in WASI,
including its shared controller. Six exact local/shared edges, over-limit append
rejection, competing-owner release/retry, shallow clone identity and native
concurrent final drops pass. A clone rejects private mutation without changing
either view; dropping it permits unique construction to continue. A zero-operation
owner allocates nothing. Denial at the controller boundary after vector admission
returns the typed shared error without requesting even a header record.

Public prepare/drop/execute controls preserve two logical stages' counts and
order, share their payload, retain the grant through serializer failure and
release all grants after the final Analysis clone. Malformed input and
cancellation after 65,536 populated scan rows leave no destination, temporary
workspace or grant. Exact live-owner equations add stage bytes explicitly and
still require release after destruction. Nested rewrite contract fixtures also
release their new stage owners before checking the original baseline.
Bundled Chromium, installed Chrome and Edge pass the shared WASI resource
contract, including these stage, summary and nested traversal lifetime controls.

All 20 Windows and six Linux commands pass with unchanged compilation inputs.
Production's 25 Chromium contracts and final hosted packaging pass. The
[package identities](../../evidence-originals.md#sha256-d22cbe352821fffad20a6e615ca233b5da0e44e6a46d2b58a05be4fe18b8e6f9 "Original: docs/benchmarks/stage-stats-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven hosted assets;
production exposes no resource-test entry point. The
[retained CLI comparison](../../evidence-originals.md#sha256-cc7793f020236b5d8583c642b43c2122a2b1cfa65c0b677061619f7a610e56c2 "Original: docs/benchmarks/stage-stats-native-parity-2026-10-23.json")
passes seven operation fixtures/fourteen commands against the preceding summary
build, preserving CSV hashes, output records, normalized configuration, header/
preview/selected-value arrays, logical digests and stage statistics under row/byte
caps. Its temporary directory is removed.

This package remains local. Seed/digest strings, warnings, diagnostics, other
Analysis metadata and native thread/runtime overhead remain open in
[TODO](../../../TODO.md); macOS stays deferred. These small correctness fixtures add
no throughput, physical-I/O, RSS, scale or additional-device claim.
