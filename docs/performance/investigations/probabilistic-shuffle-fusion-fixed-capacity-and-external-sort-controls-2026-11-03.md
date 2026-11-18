## Probabilistic shuffle fusion: fixed capacity and external-sort controls (2026-11-03)

**Decision: retain the unchanged isolated candidate after exact-output controls at
one fixed lower shared capacity; broader admission and runtime transfer remain
open.** The [record](../../benchmarks/probabilistic-shuffle-fixed-capacity-2026-11-03.json)
and [appended controls](../../benchmarks/probabilistic-shuffle-fixed-capacity-2026-11-03.patch)
reuse the [original fusion and placement patches](../../performance.md#probabilistic-allocation-and-uniform-shuffle-fusion-control-2026-11-03).
Production sources, dispatch, defaults and deployment stay unchanged. There are
four untimed diagnostic jobs and no new elapsed observations.

The first baseline/candidate pair keeps the original 20,000-row fixture, four
uniform regions, payloads, seed, 80/20/0 allocations, shuffle and strict CSV caps.
Only the shared pool changes from 32 MiB to a predeclared 4 MiB, plus fresh paths;
job memory stays 32 MiB and workers stay one. Both complete exactly, adapting
through routing rather than external sorting. Prior observed peaks were not
minimum capacity requirements. Their counters report zero external runs/merges.

That result leaves external sorting untested. A separately reviewed second pair
keeps the same capacity, row count, payload generation and configuration, changing
only partition values to one R0 parent. This is a fixed larger-parent correctness
witness, not a capacity sweep or a reserved width/skew correlation. Both jobs must
complete and report actual nonzero external runs. They preserve exact output.

| Post-publication logical counter | Four-parent baseline | Four-parent candidate | Single-parent baseline | Single-parent candidate |
| --- | ---: | ---: | ---: | ---: |
| Temporary bytes written | 13,674,458 | 7,718,805 | 16,237,647 | 11,734,456 |
| Temporary bytes read | 14,479,750 | 8,323,721 | 16,329,576 | 11,777,131 |
| External sort runs | 0 | 0 | 2 | 3 |
| Merge operations | 0 | 0 | 1 | 1 |
| Merge inputs | 0 | 0 | 2 | 3 |
| Routed groupings | 5 | 1 | 2 | 1 |
| Peak tracked workspace reservations, bytes | 2,203,886 | 2,203,886 | 2,002,418 | 2,373,788 |

The single-parent candidate therefore adds an external run and has a higher
tracked reservation peak while removing logical traffic. This is a resource
tradeoff, not proof that larger composite keys are universally preferable. These
are job counters, not stage-local instrumentation or device I/O. Fixed aggregate
capacity does not simulate a dynamic competitor, live host pressure or RSS.
No timing, universal completion-domain or platform generalization follows.

All four jobs match exact CSV names, bytes and order, output records and 17 logical
Analysis fields. Independent checks cover every unique ID and field, strict
1,024-row/65,536-byte caps and named empty allocation output. Temporary/private
staging cleanup and zero final grants pass. The four-parent control also asserts
one input-start visit. The isolated candidate/core, both vendors and embedded UI
match the previously validated source byte-for-byte; only appended test helpers
differ. New formatting and workspace/all-target Clippy with warnings denied pass.
Prior workspace validation remains separate matching-core coverage.

Frozen source copies, manifests, verification, source comparison and full logs
remain in ignored `scratch/prob-shuffle-pressure-20261103T1444/`; the control binary
is retained. There were no failed attempts in this phase and no archive upload.
Strata/repeated-shuffle/collision behavior, denial and cancellation during merging,
dynamic shared-pressure feasibility, native Windows and browser transfer still
need their own acceptance before any promotion.
