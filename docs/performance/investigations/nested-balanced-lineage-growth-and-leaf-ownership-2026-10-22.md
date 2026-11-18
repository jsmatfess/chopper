## Nested balanced lineage growth and leaf ownership (2026-10-22)

The gated nested-balanced traversal formerly pushed part metadata onto a decoded
parent and cloned each leaf without a separate growth/clone grant. Its
[`Parent`](../../../crates/chopper/src/engine/nested_balanced.rs) now owns the decoded
tree plus an independently admitted traversal allowance. Before any mutation it
reserves the maximum chain depth's two-scalar-field objects/keys and descriptor
capacity, including vector replacement overlap. Depth is checked against the
existing 64-operation limit. Popped entries do not revoke capacity while the
traversal can reuse it. The original decoded vector allowance remains held, so
the extra traversal-vector charge is deliberately conservative. It is not an
exact heap or RSS measurement.

The common [`ClonedGroup`](../../../crates/chopper/src/engine/group_metadata.rs),
extracted from the preceding shuffle owner, admits shared-range and emitted leaf
clones before construction and retains their grants through catalog consumption.
Only offsets, row counts and exactness scalars change after cloning. Parent and
leaf fields drop before their respective grants, including recursive failure.
Terminal emission also checks cancellation before finishing each leaf, covering
cancellation on the last row as well as between rows.

The [19-command final-source pass](../../evidence-originals.md#sha256-3f8eb42bf0ac62f076f315c3505567a0800334f60318698e218b4ee6b03315d1 "Original: docs/benchmarks/nested-lineage-and-final-validation-2026-10-22.json")
passes formatting, default/combined-feature Clippy, the 245-test default workspace
suite, the 302-test combined-feature Chopper suite, both printed lineage
contracts, 28 UI tests/build and native/WASI release builds. A combined
shuffle/partition, nested-balanced and flexible resource reactor passes in
bundled Chromium, Chrome and Edge; a production WASI rebuild, standard 25-contract
browser suite and final test-free hosted packaging also pass. Source identities
remain unchanged across that pass. Earlier records retain their own source
identities and test counts.

The new contract checks six local/shared edges, construction versus retained
capacity, a competing owner/release/retry, invalid depths and exact parity with
three original balanced stages. Shared offsets retain the original data file;
emitted rows, metadata and stage statistics match original materialization.
Row/catalog rejection and first/last-row cancellation restore the pre-attempt
baseline. Native construction/retained growth allowances are 16,904/16,776 bytes;
WASI uses 10,656/10,560 on this fixture. These are admission equations, not
throughput/RSS comparisons. Original general child-lineage construction and other
clones remain in [TODO](../../../TODO.md#resource-correctness).
