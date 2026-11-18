## Independent parent batching removal (2026-10-25)

Astra rejected the current native independent-parent batching, materialization
and ordered-replay adapter before this separate implementation round. Removal is
accepted by Astra after actual-diff and raw verification review. This is a maintainability/retention
decision for this layer, with no claim that parallel groups can never win.

The matched Windows CLI population retains balanced-columns **−12.68%** median
elapsed time, skew **+36.86%** and small-parent **+354.45%**, n=3 per side/cell.
The balanced gain costs more CPU, logical traffic and simultaneous sampled space.
The independently matched retained-profile population is **+24.78%**:
baseline median 1.1552399 s [1.0986065, 1.1624471], candidate 1.4415612 s
[1.4386231, 1.4546266], n=3 each. Every retained-owner pair regresses. Its clock
is preparation through execution/publication with an already retained owner;
setup is separate. These populations are not pooled or subtracted to estimate
a pure pressure effect. [Retained-owner evidence](../../evidence-originals.md#sha256-bf258dcced4693e8cc560f68c80a97dae5ff6544b541d9f4f2262288c2082c06 "Original: docs/benchmarks/parallel-groups-retained-pressure-2026-10-25.json")
and its [dated interpretation](../../performance.md#retained-profile-shared-pressure-e2-comparison-2026-10-25)
retain the exact clocks, ranges, exclusions and source/binary identities.

Separate copied-source untimed diagnostics directly observed two typed Shared
denials and two successful materialized sibling datasets; successful sibling
paths were discarded before serial retry. Ordinary binaries were uninstrumented:
their batch/retry counters and extra sorting establish retry work, rather than
direct typed-denial classification for every repetition. Cleanup returned to the
retained owner R and then zero, and exact output gates passed. Earlier failed
owner fixtures and their corrections remain evidence.

Cheap exact row/group/worker checks can exclude obvious small/skew shapes but
cannot bound decoded width or reserve shared headroom through sibling
materialization. No feasible validated guard is established; retaining the layer
would need another cost/admission design and new evidence. No threshold or Auto
selector is introduced. One Windows host, fixed small samples, warm/uncontrolled
cache and sampled-space races limit inference. Reservations are not RSS, process
counters include setup/verification wait, and physical I/O/allocator census are
unknown. There is no browser performance claim.

Removed: `engine/parallel_groups.rs`, its exclusive dispatch/retry helpers,
catalog rewind mode/tests, test hook/peak reset, three diagnostic counters,
feature forwarding and dedicated active harnesses. Ordinary parallel comparison
sort/compression workers, generic batching, shared Dataset/storage/resources,
original serial parent stages and comparison/merge fallback remain. Removed
Cargo features fail explicitly. Generic exact output/caps/admission and native
publication/browser completion coverage are retained.

Preservation/replay locations are repository-local ignored artifacts:
`.tools/e2-removal-20261025-r8/source-before/` contains every fresh tracked and
nonignored input, including vendor, removed sources and harnesses;
`hosted-before/ui/dist/` preserves generated hosted assets before rebuilding.
The original E2 baseline remains `.tools/e2-orientation-20261024-162519/`;
prior CLI evidence remains `.tools/e2-experiment-20261024-163217/` and the latest
immutable bundle remains `.tools/e2-pressure-measure-20261025-r7/evidence-bundle.zip`
(SHA256 `129370ee1adfee82cc56c6450431d77095f02d71aeb6ec7b30a3b5bdc979c0f4`).
All historical raw JSON and numerical synthesis bytes are preserved. Fresh r8
commands, diffs, hashes, failed attempts and verification limits are recorded in
`.tools/e2-removal-20261025-r8/round-report.md`. No new performance measurements.
E1 remains unresolved/unchecked; E3 is next unstarted, and E3–E5 are untouched.
