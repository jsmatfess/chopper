## Selected-column summary admission and sharing (2026-10-23)

[`ColumnSummaries`](../../../crates/chopper/src/engine/column_summaries.rs) now owns
retained selected-column descriptors, strings and a conservative BTree node
allowance. The same immutable shared-payload helper used by headers/previews
keeps these grants through Analysis cloning, serialization and execution until
the last owner drops. The public Rust field has an owner type; array/value/
truncated JSON stays unchanged. Caller construction and explicit copies remain
outside engine admission.

Selection uses a fixed 64-index stack array while resolving every configured
column, preserving late validation errors and the original lowest-index subset.
The 100-value and 256 KiB display limits retain their historical per-value cost
and sticky truncation. Display selection is separate from heap admission: the
collector now reserves each copied String and a full-node envelope before
insertion. Entry denial preserves the prior tree/display counter and propagates
typed admission. Tight budgets may deny formerly uncharged summary storage.
The [ownership contract](../../resource-policy-research.md#selected-column-summary-admission-2026-10-23)
records the insert-only standard-library bound, fixed stack scratch, compile
guard and remaining allocation/RSS limits.

The [20-command Windows record](../../evidence-originals.md#sha256-1606fcbd737ff951a714871d9d9222bdcf8d0187ccd795a235632aac6e9c904c "Original: docs/benchmarks/column-summaries-validation-2026-10-23.json")
and [six-command Linux/WSL record](../../evidence-originals.md#sha256-97cd140dfc3bc882d06b5ac9140bc2b2085e98a0f56f96a2a8ef063e8e74b93e "Original: docs/benchmarks/column-summaries-linux-validation-2026-10-23.json")
pass with unchanged compilation inputs. Windows covers 257 default workspace
and 314 combined-feature Chopper tests; Linux covers 260 and 317. Each suite
also passes four read-only compile-fail doctests. Default/combined Clippy,
formatting, UI's 28 tests/build and native release pass.

The three-column/four-key retained fixture reserves 2,373 bytes on native Windows
and 1,201 in WASI. Its per-key node allowance is 544/272 bytes respectively;
these conservative grants are not a node-allocation census or RSS measurement.
Six exact local/shared edges, competing-owner release/retry, shallow clone
identity and native concurrent final drops pass. Injected shared denial after
node allowance but before String copying leaves the tree/display counter and
existing grants unchanged; release permits exact retry. Independent legacy
controls match descending/duplicate/named selection beyond 64 columns, the
100-value cutoff, global display boundary and sticky truncation. Late missing,
ambiguous and out-of-range columns retain the original errors before summary
vector/tree construction. Empty input/unselected metadata allocate no owner.

Public prepare/execute controls retain header/preview/summary grants together,
share summaries across Analysis clones, retain them through serialization failure
and release them after final destruction. Publication independently checks rows
and fields. Malformed input and cancellation after 65,536 populated scan rows
leave no destination, temporary workspace or grant. Bundled Chromium, installed
Chrome and Edge pass the shared WASI resource contract; production's 25 Chromium
contracts and final test-free hosted packaging pass.

The [package identities](../../evidence-originals.md#sha256-9310b1f5ac9ef7ea60e536dfb6e3f6ee5c74c059671166f7def3be04d81a3049 "Original: docs/benchmarks/column-summaries-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven final hosted assets,
with no production resource-test export. The
[retained CLI comparison](../../evidence-originals.md#sha256-d8e6de8aa211e64b6605fd448166aa17a0fb32b976bd25bc01c326a09383009f "Original: docs/benchmarks/column-summaries-native-parity-2026-10-23.json")
passes seven operation fixtures/fourteen commands against the preceding header
build, preserving CSV hashes, output records, normalized configuration, header/
preview/selected-value arrays, logical digests and stage statistics under row/byte
caps. Its fixture directory is removed.

The package is local, not published. Other Analysis/runtime ownership and broader
release work remain in [TODO](../../../TODO.md); macOS stays deferred. These small
correctness fixtures establish no throughput, physical-I/O, RSS or scale claim.
