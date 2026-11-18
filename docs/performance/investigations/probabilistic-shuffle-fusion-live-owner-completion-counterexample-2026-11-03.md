## Probabilistic shuffle fusion: live-owner completion counterexample (2026-11-03)

**Decision: block promotion of the unchanged fusion.** The
[counterexample](../../benchmarks/probabilistic-shuffle-live-owner-2026-11-03.json) and
[appended control](../../benchmarks/probabilistic-shuffle-live-owner-2026-11-03.patch)
show the prepared baseline completing where the candidate returns typed shared
memory admission denial. Native Windows reproduces the Linux result. Earlier
fitting, fixed-capacity and browser transfer successes remain valid within their
recorded scope; they do not establish completion under a late competing owner.

The predeclared case keeps the 20,000-row probe-v1 payload generator, one R0
partition parent, seeded uniform child shuffle, one worker and strict
1,024-row/65,536-byte caps. Probabilistic groups are 50/50/0 so original child
sorts are smaller than the fused parent sort. Job memory and aggregate pool are
32 MiB. At the public `Preparing operation 2 of 3` notification, after root
materialization, an independent workspace acquires exactly 28 MiB (29,360,128
bytes), leaving 4 MiB for the job and other grants. The same competitor remains
live through each outcome. No capacity sweep, shape tuning or elapsed panel runs.

| Runtime | Prepared baseline | Unchanged fusion | Cleanup and competitor lifetime |
| --- | --- | --- | --- |
| Linux/WSL | Completes; independent fields/IDs/caps pass | Typed shared admission denial | Pass |
| Native Windows/MSVC | Completes; independent fields/IDs/caps pass | Typed shared admission denial | Pass |

The candidate produces no completed output, so this is not a successful paired
CSV-parity comparison. Every case checks one input-start visit, owned temporary
and private-staging cleanup, only the competing grant surviving job destruction,
and zero final pool usage after that grant releases. The baseline's fields,
unique IDs, three groups and output caps are verified independently. The
candidate's error remains full and typed; detailed Context diagnostics are
unavailable after failure and are not inferred from the successful cell.

A separately reviewed, candidate-only Linux diagnostic enables a backtrace and
reproduces the same denial without changing the core, capacity or owner. The
[diagnostic patch](../../benchmarks/probabilistic-shuffle-live-owner-diagnostic-2026-11-03.patch)
retains that run. Its stack locates `MemoryPool::acquire` through
`Reservation::resize` at `Sorter::flush`'s `io.resize(65536)`, reached from
`Sorter::push_packed` during fused row accumulation. This precedes `sorter.finish`
and the child/output emission loop, so no fused sink row has been emitted in this
single-parent case. Windows reproduces the completion loss but is not separately
backtraced. The original control binary remains retained before rebuilding.

`Workspace::sort_buffer_limit` uses the configured aggregate admission limit,
rather than free capacity after existing grants. `Sorter::reserve_input` can
flush on growth denial, but the flush itself needs that 65,536-byte I/O grant
while retained rows are still live. This is a concrete storage admission boundary;
no physical OOM or complete RSS claim follows. A storage-only buffer remedy may
be evaluated independently, while graph/retry integration remains with the owner.

This differs from the earlier fixed 4-MiB pool: a smaller configured limit can
reduce buffering targets up front, while a late live owner leaves the configured
target unchanged. A prior reservation peak is not a minimum required capacity,
and fixed-capacity success does not prove dynamic-owner completion. The injected
owner is ledger competition, not an actual 28-MiB allocation or an RSS ceiling.

Both focused native pairs, new Linux formatting/all-target Clippy and exact source
checks pass. Candidate/core, vendors and embedded UI match the prior workspace
validated source; only appended test helpers differ. No failed harness attempt,
performance repetition or corrective candidate revision occurs in this phase;
the one extra diagnostic job is charged separately from the two matched pairs.
Full source, plans, identities and logs remain in private Linux/Windows
`scratch/prob-shuffle-live-owner-20261103T1854/`. No archive upload is claimed.

Production stays unchanged. Further promotion requires resolving the recorded
completion loss and measuring any remedy's full retry cost. The owner reserved
execution-graph work for another thread, so this change supplies the finding and
replay material without modifying graph code, decision diagrams, glossary, ADRs
or the graph prototype.
