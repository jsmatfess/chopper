## Default child-lineage construction and borrowed domains (2026-10-22)

The ordinary balanced, partition, exact assignment, interleaved and probabilistic
assignment emitters now use a fixed-schema
[`Entry`](../../../crates/chopper/src/engine/child_metadata.rs) that borrows source
strings until admission. Construction validates serialized metadata size first,
admits parent payload, child object/keys/strings and the new lineage vector before
cloning, reconciles actual vector capacity before filling it, then retains the
tree's grant through the consuming catalog call. Shared-range balanced output
uses the same owner. Source decoded grants remain independent. Conservative
construction allowances can deny jobs that previously left these trees uncharged.

Partition and assignment shuffle domains serialize the borrowed parent/entry
directly. They no longer allocate a temporary child JSON tree or selected-value
descriptor vector to hash it. Fixed fields preserve canonical map ordering,
selected column order/duplicates and escaping; seeded-v1 domains remain unchanged.
This is an allocation-ownership change, not a new randomization policy.

The [final validation record](../../evidence-originals.md#sha256-f7e6c0780399f4a6d9abc1c210314f443c45f93198bd1365b88d3bbb6425b8c1 "Original: docs/benchmarks/child-lineage-final-validation-2026-10-22.json")
contains native and WASI reports. Three entry shapes check canonical bytes and
seeded-domain parity with the original owned form, local/shared boundaries and
competing-owner denial/release/retry. Invalid columns and cancellation are
rejected before tree allocation. Real default operation execution checks IDs and
fields, row/catalog errors, cancellation after the first and last successful row,
restored reservation baselines and exact-order retry. These small fixtures do
not establish performance, scale, arbitrary cancellation timing or an RSS cap.
Legacy experimental child construction, other mutation/clones, partition-key
copies, codecs and runtime overhead remain in [TODO](../../../TODO.md#resource-correctness).
This later local change is separate from the already published Pages build.
All 19 final-source commands pass with unchanged source identities: formatting,
default/combined-feature Clippy, 246 default workspace tests, 303 combined-feature
Chopper tests, three printed lineage contracts, 28 UI tests/build, native/WASI
release builds, combined resource contracts in Chromium/Chrome/Edge, the 25
production browser contracts and final hosted packaging without test assets.
The [first validation attempt](../../evidence-originals.md#sha256-a6341d600372126c1f1685dc87e370176c5228cfe48012c4d3f54728bc0979e8 "Original: docs/benchmarks/child-lineage-cross-runtime-validation-2026-10-22.json")
is preserved: default checks pass, but the combined-feature test rejects an
invalid fixture operation index. The corrected fixture invokes operation zero
without inventing preceding job operations; production eligibility is unchanged.
