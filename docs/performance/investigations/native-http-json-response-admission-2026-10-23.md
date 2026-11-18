## Native HTTP JSON response admission (2026-10-23)

The native server now pre-admits temporary canonical JSON trees, encoded response
buffers and formatted error text through its existing shared process pool.
[`server/json_body.rs`](../../../crates/chopper/src/server/json_body.rs) keeps the wire
grant with its Read owner through successful sends, early disconnects,
abandonment and delayed destruction after EOF. State serialization borrows the
cached Analysis/Profile under the mutex, then releases the lock before HTTP I/O.
Admission denial leaves prepared/cached owners intact. Static assets and fixed
responses borrow bytes; job-transition acknowledgements require no new payload
allocation after changing state. A bounded inline JSON fallback preserves the
original error prefix when even an error response cannot be admitted. See the
[ownership contract](../../resource-policy-research.md#native-http-json-response-ownership-2026-10-23).

Five focused native contracts cover six local/shared construction edges for
ordinary JSON and six for formatted errors, competing-reader denial/release/retry,
canonical JSON bytes/escaping, early-header and partial-body disconnects,
concurrent EOF readers, abandonment, cache preservation and source-drop versus
wire lifetime. Real loopback requests cover state/defaults, a zero-pool JSON
error and a zero-pool cancellation acknowledgement. The representative ordinary
fixture retains 17,460 wire bytes after a 31,907-byte construction peak; its
canonical tree accounts for 14,447 bytes. The error fixture retains 30,748 wire
bytes after a 60,479-byte construction peak. These are requested working capacities
on these native fixtures, not allocator usable size or RSS.

[Windows validation](../../evidence-originals.md#sha256-55e3b17fd10d4272b8956e3d6734cf416d5a4ef5b3e9342ce37236e530c21e6a "Original: docs/benchmarks/native-http-json-validation-2026-10-23.json")
records formatting, default/combined Clippy and tests, the focused contracts,
all-feature compilation, 28 UI tests/build and the native release build. All ten
commands pass; default/combined Rust suites pass 267/324 tests plus nine doctests
each. All seven Linux commands pass, with 270/327 tests plus nine doctests each.
[Linux/WSL validation](../../evidence-originals.md#sha256-33d3f38a05bc9a97b15d8757900fa457b730059bb513a7a92fa8ee326fb346be "Original: docs/benchmarks/native-http-json-linux-validation-2026-10-23.json")
records the corresponding native default/combined checks and focused contracts.
The [real-server before/after check](../../evidence-originals.md#sha256-0a681d4ef2de89616cf267d82dcce1e59b0c2bee24d61b7d787528e88157e1f7 "Original: docs/benchmarks/native-http-server-parity-2026-10-23.json")
uses the retained preceding diagnostic-owner executable and the new release:
authentication, static assets, defaults, idle state, columns/sniff, full profile,
prepare-without-publication, ready cancellation, reanalysis, confirmed publication
under strict row/byte caps and missing-input failure. Compared visible fields,
CSV hashes and manifest output records remain exact on the 60-row partition fixture.
The initial [request-method recorder failure](../../evidence-originals.md#sha256-dfca04df5087a273f6c68e4eb43d95488555a89225d02ca1a81ec79081281d1f "Original: docs/benchmarks/native-http-server-parity-development-2026-10-23.json")
and [invalid exact-file/cap fixture](../../evidence-originals.md#sha256-9c347f4b6a60aafc78f264f9078a0a4f546eb4377ce356d735e8614a1f900ee2 "Original: docs/benchmarks/native-http-server-parity-fixture-development-2026-10-23.json")
remain preserved separately. The latter was rejected by the retained baseline;
correcting the fixture did not change the exact-file or cap contract.
[Package identities and harness sources](../../evidence-originals.md#sha256-26b03d85df9538f7e3a67e7110b2be9a4cd63ffddaf360f10cff2c2fefc52b8e "Original: docs/benchmarks/native-http-json-package-identities-2026-10-23.json")
pin native binaries and verify all seven local hosted assets remain unchanged.

This is native-server response ownership and small-fixture compatibility evidence,
not a performance comparison. The module is excluded from WASI; the preceding
hosted engine/package validation remains its own evidence. No new hosted build,
deployment, browser/device, macOS, scale or physical-I/O claim follows. Incoming
request parsing, picker source buffers/trees, state/progress/error source storage,
source discovery/parent normalization, carriers, HTTP/runtime internals and native
thread stacks remain open. Working-allocation admission is not a complete RSS cap.
