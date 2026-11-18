## Analysis preview capacity and shared lifetime (2026-10-23)

The [`Preview` owner](../../../crates/chopper/src/engine/preview.rs) closes a retained
Analysis allocation boundary: payload limits alone did not count String slots
for empty CSV fields. The builder now admits the root vector, each row vector
and String capacity before copying, then admits a shared controller allowance.
Failed row construction drops its temporary storage and grant without adding a
partial row. Existing eight-row/32 KiB decoded-payload selection remains intact.

`Analysis.preview` now has a read-only owner type rather than a mutable Vec.
Analysis/Preview clones share the same rows and capacity grant; explicit row
copies and caller-constructed/deserialized previews remain caller allocations.
Serialization retains the same arrays. The final clone deallocates the shared
block before dropping the moved-out row tree and its grant, using the audited
`Arc::into_inner` ordering. Empty previews allocate no controller. The
[ownership contract](../../resource-policy-research.md#analysis-preview-ownership-2026-10-23)
keeps other Analysis trees/clones and runtime/RSS coverage open.

The [first Windows pass](../../evidence-originals.md#sha256-d921f727af14563634ecb4a4837de017a767b1879f959b833699fe55969d7775 "Original: docs/benchmarks/analysis-preview-owner-validation-2026-10-23.json")
and [first Linux pass](../../evidence-originals.md#sha256-d6fd3a0bc904d0bef1856eea5e87077c48da27197d64f37e34bdffbe5c397b58 "Original: docs/benchmarks/analysis-preview-owner-linux-validation-2026-10-23.json")
are preserved. Both pass formatting/default Clippy and reach the same pressure
regression's old zero-reservation expectation while its returned Analysis is
still alive. The corrected test requires exactly that preview's charge, then
drops the Analysis and requires zero, retaining all existing output/field/ID and
metadata checks. Other exact owner equations explicitly include the preview
while it is live, including Analysis clones retained after Prepared destruction.

The [interrupted Windows pass](../../evidence-originals.md#sha256-9f2303cdb317d9352a7cc2dd297360ec0af208be42d0a266e412803845cdb022 "Original: docs/benchmarks/analysis-preview-owner-final-validation-2026-10-23.json")
and [interrupted Linux pass](../../evidence-originals.md#sha256-eecca6c6b3edaf32829382929ff7031d4631f5351f78d07a40dad0d3755b5e3c "Original: docs/benchmarks/analysis-preview-owner-linux-final-validation-2026-10-23.json")
record passing formatting/Clippy commands but no completed workspace-test result.
The user confirmed a computer restart. Subsequent process checks found neither
the runners nor their test processes, and every recorded source hash still
matched. Raw records remain untouched. The
[Windows recovery](../../evidence-originals.md#sha256-1513979a215537e9cfa6b5ed57d1de4177cba93d9d2e9d63ab5012038d3debb4 "Original: docs/benchmarks/analysis-preview-owner-restart-validation-2026-10-23.json")
and [Linux recovery](../../evidence-originals.md#sha256-f6066f491eb1ace45f1377734a2653a7776fe8d41a0a0fed282338e0510edead "Original: docs/benchmarks/analysis-preview-owner-linux-restart-validation-2026-10-23.json")
reference the interrupted records and their hashes, carry forward only recorded
passes, and rerun all checks that lacked a result. Recovery runners checkpoint
partial command output so another interruption cannot hide completed test output;
a partial command still does not establish a passing result.

The recovered native runs pass 255 default Windows workspace tests and 312
combined-feature Chopper tests, plus both compile-fail doctests in each suite.
Linux/WSL passes 258 and 315 respectively, again with both doctests. Default and
combined Clippy/format checks are supported by the unchanged-source records
before/after the restart. UI's 28 tests/build and the native release build pass.

The focused preview fixture retains 442 bytes on native Windows and 250 in WASI,
including the explicit shared-controller allowance. Six local/shared edges,
competitor release/retry, partial-copy rollback and a zero-payload row with
100,001 String descriptors verify pre-copy admission. Selection controls preserve
the exact 32 KiB boundary, skipped oversized rows, later empty fields and the
eight-row ceiling. Clones share the same row pointer and grant. Native concurrent
last-clone drops release once; WASI checks single-reactor sharing without a
native-thread claim. Public preparation retains the preview through serialization
failure, execution and sibling Analysis destruction, then releases it after the
last clone. Malformed input and cancellation after 65,536 decoded rows leave no
destination/workspace or grant.

Bundled Chromium passes the combined resource contract in the recovery record.
Installed Chrome initially exits before creating a page with `Target page,
context or browser has been closed`; that failed launch is retained. A minimal
isolated launch opens the expected page, then the
[nine-command browser follow-up](../../evidence-originals.md#sha256-d4f11777fa14baaf16432a69f54be8cd0d25b5b144f55c72201b711b4fe0cf73 "Original: docs/benchmarks/analysis-preview-owner-browser-followup-2026-10-23.json")
records two more successful probes, the unchanged original Chrome resource
contract, Edge's resource contract, production WASI, all 25 standard Chromium
contracts and final clean packaging. Chrome reports 155.0.8059.86 and Edge
155.0.4283.62. No application source changed, no workaround was applied, and the
initial launch's cause is unproven. The same small repro/full harness already
exercise that launch seam; this is not a claim that intermittent launch failure
has been eliminated.

The [package identities](../../evidence-originals.md#sha256-face7a4aec299db710e60722545c9cbea67b3cd8513671b360bc12a7d08254bb "Original: docs/benchmarks/analysis-preview-owner-package-identities-2026-10-23.json")
pin 25 native test executables, the rebuilt release binary and seven hosted
assets. The production resource-test export is absent. The
[retained native comparison](../../evidence-originals.md#sha256-c6eeb637cbeca86179bce0a374434d9ff01fd58fc379c4031eb0f385cf9084d2 "Original: docs/benchmarks/analysis-preview-owner-native-parity-2026-10-23.json")
passes seven operation fixtures/fourteen CLI commands against the prior prepared
configuration build, matching CSV hashes, output records, normalized canonical
configuration, preview/selected-value arrays, logical digests and stage statistics
under compatible row/byte caps. Its test directory is removed.

The new package is local and has not been published. These correctness controls
add no throughput, RSS, physical-I/O, large-job or additional-device claim. Other
Analysis/runtime allocation and release work remains in [TODO](../../../TODO.md);
macOS stays deferred.
