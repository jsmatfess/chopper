## Experimental child lineage and mutable partition traversal (2026-10-22)

The remaining experimental child-tree constructors now use the same admitted
[`ClonedGroup`](../../../crates/chopper/src/engine/group_metadata.rs) owner: constant
partition reuse/copy, partition/shuffle/balanced fusion, count-independent
streaming chains and flexible shuffle/allocation ranges. Intermediate scopes and
output children retain independent grants through hashing, row emission and
catalog consumption. Constant-partition reuse retains its grant when restarting
a sink group; flexible ranges retain it across quota boundaries and named zero
allocations. Additional admission can reject a tight job or select an existing
typed-denial fallback; no experiment is promoted and replay policies are unchanged.

Consecutive-partition traversal now owns its cloned prefix, pre-admits each
borrowed entry and vector replacement overlap before mutation, and reconciles
the tree after append. Truncation frees removed payload charges while retaining
the actual vector capacity. Output leaf clones retain independent grants through
consumption. This preserves a mutable traversal instead of accumulating a separate
full-prefix copy at every level. The old uncharged `child` helper is now compiled
only for native test expectations. Streaming-domain construction hashes selected
borrowed values while retaining the intermediate scope owner.

The [validation record](../../evidence-originals.md#sha256-352289d91a85c0295aefc7b30e80e1d8e4a1504ae268303f6995b2aa54752578 "Original: docs/benchmarks/experimental-lineage-final-validation-2026-10-22.json")
includes the extended shared native/WASI child contract. Four exact scenarios
compare IDs, fields, ordinals, metadata and exactness with original staged
execution; flexible uniform/Fisher–Yates allocation ranges check their own exact
retry and named empty groups. All six scenarios inject row/catalog rejection and
actual first/last-row cancellation, check the intended checkpoint and restore
the pre-attempt reservation baseline. The mutable-tree controls check six
local/shared edges, denial without tree mutation, replacement overlap,
truncate/regrowth accounting and a leaf surviving source mutation/destruction.
These are small correctness fixtures, not new throughput, scale or complete
RSS-cap evidence. Partition-key copies and remaining codec/runtime/construction
boundaries remain open in [TODO](../../../TODO.md#resource-correctness).

All 24 Windows final-source commands pass with unchanged source identities:
formatting, default/combined-feature Clippy, each changed experiment's individual
Clippy configuration, 246 default workspace tests, 303 combined-feature Chopper
tests, three printed lineage contracts, 28 UI tests/build, native/WASI release
builds, all six extended resource scenarios in Chromium/Chrome/Edge, the 25
production browser contracts and final test-free packaging. Native mutable-tree
construction/retention is 7,764/7,700 charged bytes for this fixture; WASI is
4,972/4,924. These are platform-specific admission equations, not measured heap
or RSS. The [package identity record](../../evidence-originals.md#sha256-0d320ec0b2641e67a6d907ca59dede74639dc23f8d58098cb0e02e6fdec242dc "Original: docs/benchmarks/experimental-lineage-package-identities-2026-10-22.json")
binds native test/release executables, the validation harnesses and seven local
hosted files, with the test resource export absent. This package is not published.
The [six-command Linux/WSL pass](../../evidence-originals.md#sha256-73087af6bdecc8934488ded4294446c1669f7e9856775eb5d61d598bccf05424 "Original: docs/benchmarks/experimental-lineage-linux-validation-2026-10-22.json")
also passes formatting, default/combined-feature Clippy and both native suites
with unchanged source identities. Its inventory matches the Windows pass and
includes vendor sources. Linux temporary/output fixtures extend correctness
coverage; macOS remains deferred and no physical-I/O conclusion follows.

The [weighted root-fixture follow-up](../../evidence-originals.md#sha256-53399771a2486563fcabab3ec5cec5b93cf93eb9ddac0eaf56c9225ce1953fe2 "Original: docs/benchmarks/weighted-lineage-root-validation-2026-10-22.json")
changes test inputs only. It verifies an unprocessed retained root before running
either comparison graph: disabling multi-stage ingestion fusion does not disable
all leading-operation ingestion. Earlier six-scenario records therefore tested
already transformed retained scopes for some leading operations; their raw
reports remain preserved. The corrected fixture uses two positive weights and
one named zero allocation (40/0/60), exercising probabilistic child domains and
positive quota rollovers. It records all final group counts and explicitly checks
3/0/5 flexible quotas for eight rows. Borrowed all-values and reference-list
entries also have direct canonical-byte/domain comparisons against owned JSON.
The follow-up's source inventory proves that only two resource-contract Rust
files and the browser assertion harness changed after the full partition-boundary
pass below; production sources remain identical.
All 18 follow-up commands pass with unchanged source identities, including
native and Linux/WSL focused contracts, Clippy, UI checks, three browser resource
runs and production rebuild/25-contract acceptance/final packaging. The
[package parity record](../../evidence-originals.md#sha256-f50323ab533e2360d16ca8fcee7d78651c1b865c45baa6164e511cb30eee7d52 "Original: docs/benchmarks/weighted-lineage-package-parity-2026-10-22.json")
confirms that all seven production hosted files remain byte-identical to the
full partition-boundary pass. The native release hash changes despite unchanged
recorded production source inputs; no cause or native binary-identity claim is
inferred. Its new hash and actual five-row Unicode CLI/cap/manifest smoke are
recorded separately. The [verifier diagnostic](../../evidence-originals.md#sha256-1921b1df0d7ad1b6e5a8fb3cb286f5bde4eef6fb536b16922a3630673a545df8 "Original: docs/benchmarks/weighted-native-cli-verifier-diagnostic-2026-10-22.json")
preserves the successful native command before correcting the smoke verifier's
`.json` assumption to `manifest.jsonl` and making fixture/subprocess UTF-8 handling
explicit. No full-suite rerun is inferred for these test-only changes.
