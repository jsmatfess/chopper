## Output planning lineage clone ownership (2026-10-21)

The next resource-correctness gap was lineage cloned by output preparation,
after the decoded source catalog already had its own owner. Both the active
`PlanWriter` chunk and the materialized dataset's temporary output group now use
[`PlannedMetadata`](../../../crates/chopper/src/output/planned_metadata.rs). The
decision is to admit each additional live tree before cloning and retain that
grant through its actual lifetime. This is ownership work, not a benchmark or
selector/default promotion.

Admission uses the source group's checked `JsonCapacity` envelope before calling
`Group::clone`. Known-length `Vec` and `String` clones fit their source capacities;
map cloning uses the existing conservative full-node allowance per entry. After
construction the actual cloned-capacity envelope is checked and retained. Cloned
grants are independent, including two clones surviving drop of their input
fixture. Dataset planning retains the decoded source's existing separate grant.
Only scalar offsets/row counts are mutated after construction. The cloned value
drops before its grant, which also covers catalog serialization errors and
named empty outputs. A materialized group's grant stays live through `end()`.
The preparation path still produces the same CSV bytes, lineage, scalar catalog
metadata and chunk boundaries. Denial before opening a chunk now leaves its
file count/index and prefix emission unchanged, permitting a same-writer retry
after pressure is released. Cancellation and post-emission errors remain terminal.

The [shared native/WASI contract](../../../crates/chopper/src/output/planned_metadata/resource_contracts.rs)
checks local/shared source-envelope minus-one/exact/plus-one edges, a builder
that is not called after denial, typed competing-owner denial/release/retry,
independent cloned owners, and success/failure serialization while the grants
remain live. The nested Unicode/escaped metadata fixture retains 4,402 bytes
from a 4,594-byte source envelope on this native build. These are conservative
working charges, not RSS. The real `PlanWriter` controls cover row-cap rollover,
cancellation with a still-owned active chunk, temporary-space exhaustion during
unbuffered catalog serialization, denial/retry before prefix emission, and
empty allocation output. All restore the idle directory baseline after writer
drop. Materialized dataset planning additionally verifies exact CSV and catalog
lineage/counters, active row splitting and the named empty chunk.

The [validation transcript](../../evidence-originals.md#sha256-c66a32cab4a35ec810b4b47e8bf7e66b046ee53e2a4c4a39196b53b9a540b5f9 "Original: docs/benchmarks/planned-lineage-validation-2026-10-21.json")
records tracked/untracked dirty compilation-source identities including vendor
inputs, harness/toolchain identities, per-command outcomes and the initial test
compile failure. WASI build commands retain individual binary hashes. Contract
durations are validation measurements, not performance comparisons. The browser
resource page requires the same helper's report through real OPFS, separately
from production packaging.

All 21 validation commands pass: formatting, the default Windows workspace (146
chopper library tests), candidate library (161), both all-target Clippy modes,
28 UI tests/build, native embedded rebuild, production WASI/hosted builds,
25 standard Chromium contracts, bridge/peer cleanup and both WASI resource
variants. Compilation-source inputs remain unchanged. Final hosted packaging
passes the production export guard and removes test assets. The existing
vendored ZIP WASI unused-variable warning is retained in build output.

The [cross-runtime comparison](../../evidence-originals.md#sha256-6e37f88580aaaf1d40d9a98ca33b6613f489094b8f7d38a3cecbc2efc025a035 "Original: docs/benchmarks/planned-lineage-cross-runtime-2026-10-21.json")
matches the metadata digest, admission/lifetime outcomes, writer controls and
materialized parity across Windows and both WASI builds, with source artifact
hashes and exact output pointers. Capacity envelopes differ by representation;
they are not cross-runtime RSS measurements. This pass adds no Linux/macOS,
device-fault, persistent-browser or throughput claim.

This closes these two output-planning clone lifetimes. Source lineage creation,
other clones/mutation growth, job-manifest JSON, joined paths, codec/runtime/error
allocations and the broader TODO acceptance/platform work remain open. A source
with large spare capacity can conservatively require more construction headroom
than its final clone retains; admission remains working-allocation accounting.
