## Probabilistic allocation and uniform shuffle fusion control (2026-11-03)

**Decision: retain an isolated exact-order challenger for targeted transfer and
admission checks; no production promotion.** The [comparison record](../../benchmarks/probabilistic-shuffle-fusion-2026-11-03.json),
[measurement-source patch](../../benchmarks/probabilistic-shuffle-fusion-2026-11-03.patch)
and [lint-only placement patch](../../benchmarks/probabilistic-shuffle-lint-placement-2026-11-03.patch)
answer a different cost question from terminal snapshot removal.

Current `following_shuffles` fuses partition or exact assignment with uniform
shuffle, but excludes probabilistic assignment. That path routes allocation rows,
emits an intermediate Dataset and then reads/sorts each child for its shuffle.
The challenger keeps `Membership::index` and its v1 domain/ID/strata draws, derives
admitted original child shuffle domains, and uses the existing 56-byte
`OperationKey::allocation` plus `SortOrder::GroupRandom`. Allocation index remains
the leading key; child random key and collision domain preserve shuffled order.
It emits the original child metadata and logical stage statistics, including
named zero-percent groups. No allocation/shuffle operation is exchanged.

A 2,000-row debug correctness gate precedes a 20,000-row development panel.
Records have unique IDs, four `id % 4` regions and deterministic 24..120-byte
repeated ASCII `x` bytes plus a note/ID prefix; the job partitions regions, allocates 80/20/0, then uniformly
shuffles each child. Job/shared memory are 32 MiB, one worker, with strict
1,024-row/65,536-byte CSV caps. The independent plain-field verifier checks every
ID and field; all successful comparisons match exact CSV names/bytes/order,
output records and 17 logical Analysis fields. Final cancellation controls
preserve cleanup and zero residual grants. A test-local flag selects baseline
or candidate in the same binary; ordinary tests default to baseline. Production
repository sources, selectors and defaults remain unchanged.

Optimized native Linux/WSL executes Auto in opposite-order pairs A/B then B/A,
n=2 per cell. The clock is complete engine API Prepare through Execute and native
publication return; fixture/config construction, diagnostic copies and verification
are excluded, as is CLI startup. Baseline median is 0.0458361615 s
[0.045088867, 0.046583456], candidate 0.037334739 s
[0.036792738, 0.037876740]. The median reduction is 18.55%, calculated as
`(1 - candidate / baseline) * 100`; paired candidate-minus-baseline differences
are -0.008296129 and -0.008706716 s. These short, same-process jobs with retained
verification reference data, uncontrolled cache/load and one fixture do not
establish general CLI, Windows, browser, device or tail performance.

| Post-publication logical counter | Auto baseline | Composite candidate | Explicit-sort baseline |
| --- | ---: | ---: | ---: |
| Temporary bytes written | 10,697,389 | 4,741,736 | 7,640,320 |
| Temporary bytes read | 11,502,681 | 5,346,652 | 8,445,612 |
| Temporary files created | 14 | 4 | 6 |
| Resident sorts | 13 | 5 | 17 |
| Routed groupings | 4 | 0 | 0 |

The one explicit-sort diagnostic pair retains exact output and the candidate's
same traffic counters, demonstrating a saving beyond immediate-router overhead.
Its clocks remain raw diagnostic fields and are not pooled with Auto or treated
as another timing panel. All these jobs report zero external sort runs; no spill
benefit is inferred. The shared peak tracked reservations are 6,571,576 bytes in
all six optimized jobs, dominated by earlier work. This does not bound the
candidate's incremental ownership or RSS. Counters are Context temporary traffic
after publication, including metadata/read-ahead, not physical I/O or final normal
File writes. Debug durations are excluded from the optimized comparison.

The initial baseline gate checked temporary-directory emptiness while an
intentionally retained Context still owned the job directory for counter capture.
It failed before candidate/main jobs; the fresh verifier checks after final
Context destruction. The original failure remains. First standard Clippy validation
also rejects two appended functions below inline test modules; the placement-only
revision moves identical functions, keeping numerical evidence pinned to the
original optimized binary/source. That placement revision passes formatting,
workspace/all-target Clippy with warnings denied and locked workspace tests; the
research test module is skipped to avoid repeating measured panels. These checks
are separate from the original debug gates and optimized observations. Local plans, source inventories including both
vendors and embedded UI, full logs and the retained optimized binary remain under
`scratch/prob-shuffle-fusion-20261103T1430/`. No private archive upload is claimed.

The larger composite keys and per-parent sort can worsen spills or admission;
retained domain construction needs pressure tests. Strata, repeated shuffle
indices, forced collisions, real spill/merge and failure boundaries, native
Windows and browser transfer remain unproved for this prototype. Resolve those
named questions before any promotion; do not tune a threshold from this cell.
