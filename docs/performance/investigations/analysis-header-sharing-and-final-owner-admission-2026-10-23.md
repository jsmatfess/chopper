## Analysis header sharing and final-owner admission (2026-10-23)

[`Header`](../../../crates/chopper/src/engine/header.rs) now keeps the CSV header fields
and their grant in one immutable shared owner. The separate Prepared reservation
ended when Prepared was dropped or executed even if the returned Analysis or
server's Analysis clone still retained header strings. Analysis/Header clones
now share the same vector/strings and grant until the last owner is destroyed.
`Analysis.header` has an owner type; borrowing, read-only capacity inspection and
array/null serialization retain their behavior. Explicit field copies and caller
construction/deserialization stay outside engine admission.

The existing parser construction and header-payload transfer overlap are
preserved. A [common shared-payload helper](../../../crates/chopper/src/engine/shared_analysis.rs)
now centralizes controller admission and final Arc/payload/grant release for both
headers and previews. It admits controller storage before allocation and drops
payload storage before releasing grants on success and admission failure.
Preview's retained-capacity allowance is unchanged. The
[ownership contract](../../resource-policy-research.md#analysis-header-and-shared-payload-ownership-2026-10-23)
keeps other Analysis/runtime allocations and RSS coverage open.

The [initial Windows](../../evidence-originals.md#sha256-c0da53eacf304acbd692dd3078b5d41905edca2f4d400218f493cff9441b8a86 "Original: docs/benchmarks/analysis-header-owner-validation-2026-10-23.json")
and [initial Linux](../../evidence-originals.md#sha256-596167f874f5690500ab45762a202782543fb96199fde4e60d22d9948e46b43c "Original: docs/benchmarks/analysis-header-owner-linux-validation-2026-10-23.json")
passes preserve one combined-feature assertion failure: the parallel-group
cleanup fixture extracts an Analysis containing a live header, then expects
only directory ownership. The follow-up assertion includes that retained header
and explicitly drops Analysis before requiring the directory-only baseline.
Corruption/cancellation, optional-row denial and serial-output checks remain.

The [20-command Windows pass](../../evidence-originals.md#sha256-22b3d8b8d740ff29c0ea01d3b5966144e7ae3f3bbfe714076d8e59388201612f "Original: docs/benchmarks/analysis-header-owner-final-validation-2026-10-23.json")
and [six-command Linux/WSL pass](../../evidence-originals.md#sha256-3b38f34d41c260b8cb55086b596928d932e04833458672d43263ebb3749d3532 "Original: docs/benchmarks/analysis-header-owner-linux-final-validation-2026-10-23.json")
retain unchanged source inventories. Windows passes 256 default workspace and
313 combined-feature Chopper tests; Linux passes 259 and 316 respectively. Each
suite additionally passes three read-only compile-fail doctests. Formatting,
default/combined Clippy, UI's 28 tests/build and the native release build pass.

The retained-capacity fixture includes spare vector and String capacity: 576
bytes on native Windows, 444 in WASI, including the shared-controller allowance.
Six local/shared edges, independent competing owners and release/retry preserve
typed denial and final zero grants. Analysis clones share the same header pointer;
serialization failure retains ownership. Public controls cover Prepared drop and
execute return, sibling destruction, final clone release, no-header/headerless/
header-only inputs and exact duplicate/empty/multiline/Unicode header bytes.
Malformed-header rejection leaves no destination, temporary files or grants.
Native concurrent last-clone drops have separate coverage. The preview controls
continue to pass with unchanged 442-byte native/250-byte WASI fixture allowances;
existing populated-scan cancellation and malformed-data controls retain both
header and preview owners through cleanup.

Bundled Chromium, installed Chrome and Edge pass the combined WASI resource
contract. A production rebuild passes all 25 standard Chromium contracts, then
final hosted packaging removes all test assets. The
[package identities](../../evidence-originals.md#sha256-520d8e4de4fda1d5e88958893a754c876ead54eb032955b6ce7fcce5547751dc "Original: docs/benchmarks/analysis-header-owner-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven hosted assets, with
no production resource-test export. The
[retained CLI comparison](../../evidence-originals.md#sha256-1c3a12ae4b03544939a507c29d089a5a9edd15096747cc546e19b6984e001ff7 "Original: docs/benchmarks/analysis-header-owner-native-parity-2026-10-23.json")
passes seven fixtures/fourteen commands against the preceding preview-owner
build. CSV hashes, output records, normalized configuration, header/preview/
selected-value arrays, logical digests and stage statistics match under the
configured row/byte caps. Its fixture directory is removed.

These controls do not establish throughput, RSS, physical-I/O, larger-job or
additional-device acceptance. This package remains local; macOS stays deferred.
Selected-value/stage/warning/diagnostic and other Analysis/runtime work remains
in [TODO](../../../TODO.md).
