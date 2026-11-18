## Shuffle output lineage admission and cancellation (2026-10-22)

The ordinary retained-dataset shuffle copied its parent lineage into an output
group without an independent capacity owner. The new
[`ClonedGroup`](../../../crates/chopper/src/engine/group_metadata.rs) admits that
clone before calling the sink's `begin`, using the source's JSON capacity as a
conservative construction allowance. It reconciles the copied tree's retained
capacity and holds the grant through sorting, emission and the consuming
catalog `end` call, including failure. The cloned group drops before its grant.
The source's decoded owner remains independent. This applies to the ordinary
uniform, Fisher–Yates and buffer shuffle paths, the flexible shuffle executor and
the native parallel-group shuffle evaluator. It does not cover child-lineage
construction or mutation.
New admission may deny a tight job that previously left the clone uncharged.

The shared native/WASI contract checks six local/shared capacity edges, denial
before sink entry, independent clones surviving their source and final-owner
release. Real `apply_parent` execution checks all three strategies, ID/field and
lineage/exactness conservation, row and catalog sink rejection, shared-pool
exhaustion before emission and exact seeded-order retry after release. A sink
sets the actual cancellation flag after its first or last successful row write;
the executor must stop before another row or catalog completion and restore its
pre-attempt capacity baseline. Explicit cancellation checks now cover those
emission boundaries. These are deterministic acceptance fixtures, not timing
comparisons or proofs about arbitrary interruption timing.

The [validation record](../../evidence-originals.md#sha256-3995551e1dde8891edf8d4dedc31a8ec5e066809f6bce7c856791261ddcbd378 "Original: docs/benchmarks/shuffle-lineage-validation-2026-10-22.json")
pins the dirty source inventory, including untracked compilation inputs and the
patched ZIP dependency, and retains command results and native/WASI reports.
That first pass covers the ordinary executor. The
[experimental and browser follow-up](../../evidence-originals.md#sha256-087f66139475e1e1e0b559c3140fd77bb161d2661bcd6da1d1895945b44e860d "Original: docs/benchmarks/shuffle-lineage-and-browser-channels-2026-10-22.json")
additionally checks the flexible executor's uniform, Fisher–Yates, buffer and auto
paths with the same lifetime, failure and first/last-row cancellation contract.
Flexible replay still records actual choices; extra charged capacity can change
an admitted physical plan. The native combined-feature suite covers parallel
evaluation/retry and ordered replay. The flexible recorder and the cloned group
each retain their own grants, and both disappear on a terminal failure.
This closes the shuffle-clone metadata lifetime slice. Original child JSON,
other clones/mutation, codecs, temporary construction and runtime overhead remain
outside it; no selector/default, device-throughput or complete RSS-cap claim is
made. [TODO](../../../TODO.md#resource-correctness) retains the broader work.
