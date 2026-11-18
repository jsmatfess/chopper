# Full shuffle followed by unstratified exact allocation

Implemented and measured, 2026-10-19. [Complete-job results and limits](performance.md#flexible-shuffle-and-exact-allocation-ranges-2026-10-19)
keep the candidate opt-in; defaults remain unchanged. The feature is `experimental-flexible-allocation`;
it requires the explicit flexible policy. The candidate physical identity is
`adjacent-full-shuffle-allocation-ranges-v1`.

For an existing parent of N unique source IDs, let largest-remainder quotas in
requested allocation order be q₁,…,qₖ, including named zero quotas. Original
execution first chooses a uniform permutation and then, independently, chooses
an assignment with those quotas. Exact allocation emits each allocation's
subsequence in the shuffled order. For any specified ordered list in every
allocation, exactly N!/(∏qᵢ!) interleavings of the lists produce that outcome
when combined with its membership assignment. The probability is therefore

`[N!/(∏qᵢ!)] / [N! × N!/(∏qᵢ!)] = 1/N!`.

Cutting one uniform permutation at the quota boundaries is a bijection between
its N! possible permutations and those ordered allocation lists, also giving
probability 1/N!. Thus the joint membership **and within-allocation order**
agree under ideal independent randomness. Marginal membership equality alone
would not establish this result. A five-ID 2/0/3 exhaustive test counts every
one of 120 outcomes once for cuts and ten times among the 1,200 original
permutation/assignment pairs. Zero quotas contribute `0! = 1` and still retain
their named output groups.

The finite keyed generators instantiate this construction; the argument does
not prove exact uniformity over their finite seed spaces. The candidate derives
a separately named parent stream from the original shuffle operation index and
full existing-parent lineage, rather than pretending to reproduce an old seeded
job. It uses the requested full-shuffle strategy and source: auto admission,
explicit random keys or explicit Fisher–Yates. Explicit buffer is excluded.

The selector only recognizes the immediately adjacent unstratified pair. It
never crosses another operation, moves a cap/split, or admits stratified quotas.
Stratified allocation needs a separate per-stratum quota and joint-order design.
Existing parents are processed in their original catalog order; allocation
children retain configured name order and the allocation's original logical
index. The permutation's encounter ordinals remain monotonic within each child.
Logical shuffle/allocation statistics remain two separate stages. The audit
records the changed domain recipe, one physical permutation, actual shuffle
algorithm/source/backend and shared-work counters counted once.

The range sink uses the existing charged largest-remainder scratch and retains
only one output group at a time. It emits directly to the final CSV snapshot or
the next immutable dataset, avoiding the shuffled intermediate dataset and the
assignment sort. A resident admission denial discards that attempt before the
existing external-capable key path; cancellation and storage/format failures
propagate. Named empty groups are emitted even when all parent quotas are zero.
Output serialization and strict byte/row caps retain their existing path.

The complete-job comparison alternates original shuffle→assignment,
original assignment→shuffle fusion, sequential flexible execution and this
candidate. Distribution-equivalent plans require field/ID conservation,
existing-parent isolation, exact quotas, canonical configured allocation order,
strict caps and original indices. Exact byte/order/metadata equality is required
only for repeated matching pinned plans and native/WASI replay. Include resident
strategies, external memory, sparse/many parents, many columns, rare-wide rows,
downstream exact splits, one/four native workers, allocator censuses, failures
and browser OPFS. Keep defaults until complete-job evidence supports promotion.
