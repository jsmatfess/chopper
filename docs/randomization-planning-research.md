# Randomization and pipeline planning research

Historical design/research: buffer-shuffle descriptions and negative controls below
refer to pre-removal builds. The current engine rejects that strategy and its
configuration fields; see [current specification](specification.md#shuffling-and-seeds).

Researched 2026-10-16. These are proposed experiments, not implemented features or
measured speedups. The user permits optional execution that changes reproducible
random order and logically equivalent pipeline reorderings. Existing seeded
contracts remain useful defaults. See [shuffle diagnostics](shuffling-research.md),
[remaining opportunities](performance-opportunities.md) and [GitHub Issues](https://github.com/jsmatfess/chopper/issues).

## Existing behavior and the opportunity

Repository facts: `engine::generated_seed` already obtains operating-system
entropy when no seed is supplied, and preparation records that seed before doing
work. Merely omitting a seed therefore already gives a fresh order, but retains
reproducibility; it does not select a faster algorithm. `chopper-core::random`
currently derives BLAKE3 domains from the seed, original operation index and parent
lineage. Random-key v1 hashes each source row ID; resident Fisher–Yates v1 hashes
a counter for each bounded draw. Collision refinement extends the random key
rather than breaking ties by source ID. See
[random.rs](../crates/chopper-core/src/random.rs),
[engine.rs](../crates/chopper/src/engine.rs) and
[the specification](specification.md#shuffling-and-seeds).

Partition followed by random-key shuffle is already fused, including during
initial ingestion: partition tuple, per-child random key and collision domain
form a composite sort key. Consecutive random-key shuffles are already elided
using the last shuffle's original domain. Shuffle followed by balanced splitting
also has a fused path. Research items should target the reverse direction and
algorithm selection, rather than repeat these delivered optimizations.

The [existing resident comparisons](performance.md#resident-full-shuffle-native-and-wasi-comparison-2026-10-15)
show no consistent whole-job Fisher–Yates advantage. The
[external prefix experiment](performance.md#external-shuffle-nativebrowser-follow-up-2026-10-15)
regresses and adds leaf materialization/decode/repack work. Neither result rules
out a different RNG, direct distribution ingestion, smaller-group execution or
avoiding a whole intermediate stage.

## Shuffle before partition can move after partition

**Derived equivalence, under an ideal uniform-permutation model:** for a fixed
column-based partition with group sizes `n_1, ..., n_k`, filtering a uniform
permutation of `N` distinct row identities into groups produces independent
uniform permutations inside those groups. Every specified tuple of within-group
orders has `N! / product(n_i!)` global interleavings, so its probability is
`1 / product(n_i!)`. Partitioning first and independently shuffling each group
therefore has the same joint distribution of final row sequences. Row identities
must distinguish duplicate payloads for this argument and conservation checks.
The unused interleaving among groups carries no final-output information.

This equivalence requires stable value-based membership and an output group
ordering independent of first encounter. It preserves distribution, not the
permutation obtained from an existing seed. The repo's child domains include
lineage and operation indices; naively swapping configured operations changes
those domains. Fisher–Yates also starts from encounter order. Preserve original
logical operation numbers separately from physical execution order.

**Proposed exact-output optimization:** retain the original global random-key
shuffle domain and source IDs, and sort or route by `(partition tuple, original
global random key)` with the original collision refinement. Within each tuple,
this gives exactly the subsequence of the original globally shuffled rows. This
can remove global shuffle materialization while keeping seeded final rows.
It differs from today's partition-then-shuffle fusion, which deliberately derives
a new child-specific domain. Preserve final tuple order, names and lineage, and
reconstruct both original logical stage summaries, rather than presenting the
physical rewrite as a different user pipeline. Benchmark composite sorting and
bounded routing plus per-group random-key execution; a new comparator may be
needed, but the existing `GroupRandom` form is a useful starting point.

**Proposed distribution-preserving optimization:** partition first, then select
an exact resident algorithm for admitted small groups and an exact external
algorithm for oversized groups. This can avoid a large global external shuffle
when most groups fit. Sorting by tuples itself may still spill, and skew, high
cardinality, file-handle limits and payload width may erase the benefit. Choose
by complete retained working set and actual shared reservations, not row count
or average group size alone. Run groups within admitted concurrency.

Do not apply this argument to balanced/contiguous or interleaved positional
splits: shuffling before those operations changes membership; shuffling their
children afterward cannot repair it. Likewise, do not commute shuffles through
exact/probabilistic assignment without proving the particular source-ID,
stratum, encounter-order and domain semantics. Do not commute approximate buffer
mixing through partition: global and group-local buffers induce different
nonuniform distributions. Include later balanced splits and strict byte caps in
rewrite tests: an exact-output rewrite should preserve their success/failure,
while a different valid random order may legitimately change byte-cap outcomes.

## Faster random draws can remain seedable

Primary-source facts: the Rand project distinguishes fast non-cryptographic
`SmallRng` from cryptographic generators and named portable generators. Its
standard generators can change algorithm between versions or platforms; named
generators support reproducibility. The docs describe thread-local reseeding
and explain why OS entropy is normally used to seed a PRNG, rather than for every
draw. See [Rand RNG documentation](https://docs.rs/rand/latest/rand/rngs/index.html).
These are candidate semantics, not a proposed dependency upgrade.

**Inference and experiment:** benchmark a named fast PRNG against the current
per-draw BLAKE3 counter stream in Fisher–Yates and independent bucket labels.
Compare a buffered cryptographic stream as another candidate. Seed once per
logical group/task, never invoke OS entropy once per row, and avoid a single
locked generator shared by workers. A named/versioned seedable implementation
may deliver the same gain as a non-replayable one; nondeterminism itself is not
a speed optimization. Fast non-cryptographic generators change the randomness
and threat-model contract, so describe that property explicitly.

Lemire presents an unbiased multiply-and-reject bounded-integer method that
usually avoids division; his benchmark includes shuffling. The newer batched
method generates multiple independent bounded integers from one random word.
See [Lemire's paper](https://arxiv.org/abs/1805.10941) and
[Brackett-Rozinsky and Lemire's batched method](https://arxiv.org/abs/2408.06213).
These are useful experimental leads, not whole-job performance predictions.
Replacing today's modulo/rejection mapping changes seeded draws even with an
unchanged RNG. Retain rejection, boundary/overflow tests and small-permutation
enumeration; reserve a new algorithm identity for any changed draw stream.

## Independent random buckets are an exact-shuffle candidate

Penschuck describes ScatterShuffle: independently assign each row a uniform
bucket, recurse within buckets and use Fisher–Yates for small leaves. The paper
also supplies in-place sequential/parallel variants and a Rust implementation,
`rip_shuffle`; its shared-memory parallel algorithm supports seeded execution.
These results motivate both an external distribution candidate and a later large
resident comparison. They are not measurements of Chopper's packed rows, budget
accounting, WASI or whole CSV jobs. See
[the original paper, sections 2–4](https://arxiv.org/pdf/2302.03317).

**Derived proof for the proposed external variant:** choose one of `k` buckets
independently and uniformly per row; shuffle each bucket exactly; concatenate
buckets in fixed label order. For any target permutation and bucket counts
`m_1 + ... + m_k = N`, exactly one assignment places its contiguous segments
in the required buckets. Its contribution is `k^-N / product(m_i!)`.
Summing over counts gives `k^-N * k^N / N! = 1/N!` by the multinomial theorem.
Random bucket order is unnecessary. Counts must follow the independent-label
model: shuffling fixed contiguous chunks then concatenating them is biased;
arbitrary fixed-size input buckets with shuffled bucket order are also biased.

Prototype bounded fan-out, sequential buffered bucket writes, byte-based leaf
admission and exact resident leaf shuffle. Recurse oversized buckets with fresh
independent draws, including the case of repeated wide records. Account for all
open buffers and intermediate storage; define a bounded-depth exact fallback.
Route leaves directly into the downstream consumer when possible so the prior
prefix experiment's extra assembled leaf-output file is not repeated.
Scheduling-dependent RNG assignment or an adaptive traversal may make replay
unavailable. A domain-separated seedable design can instead support replay,
possibly only for its recorded plan. Both need a new algorithm identity; neither
may silently claim random-key v1 order across budgets.

## Approximation remains separate

TensorFlow documents that bounded-buffer shuffle selects from a sliding buffer;
perfect whole-dataset shuffling requires a dataset-sized buffer. See
[Dataset.shuffle](https://www.tensorflow.org/api_docs/python/tf/data/Dataset#shuffle).
Chopper already offers approximate bounded-buffer mixing and has a diagnostic
negative control showing why it differs from full shuffle. Dedicated buffer
optimization is currently deprioritized. Retain it as an explicit separate
choice; permission to relax reproducibility does not imply permission to relax
uniformity. No new buffer-shuffle implementation is proposed here.

## Suggested roadmap and acceptance

1. Implement and benchmark exact-output `uniform shuffle -> column partition`
   planning first. Keep the existing public operation list and metadata; verify
   equality against execution without the rewrite, including forced key ties,
   multiple parents, duplicate fields, rare-wide records and downstream splits.
2. Define an explicit optional distribution-equivalent execution policy. Record
   selected algorithm/version, RNG identity, physical plan and replay guarantee
   in serialized analysis/manifests, including runtime/platform or worker
   constraints needed for replay. Keep fresh recorded seeds, replay of a recorded plan
   and fully non-replayable execution as distinct choices. Select exact
   algorithms per admitted group; do not silently introduce approximation.
   Retain the realized prepared output snapshot through confirmation and export;
   export must not rerandomize a nondeterministic job. Exact byte-cap validation,
   row-cap chunk membership and any cap-derived file counts describe that
   prepared realization and may vary when a new order is prepared.
3. Benchmark fast PRNG and bounded-integer candidates in a separate versioned
   exact resident shuffle, then independently randomized external buckets with
   direct downstream leaf consumption. Consider in-place parallel scatter only
   after profiling shows resident shuffle cost warrants it.
4. Run alternating baseline/candidate complete jobs on native one/multiple
   workers and browser/WASI: presorted/blocked/periodic input, narrow/many-column/
   rare-wide rows, balanced/skewed/high-cardinality partitions, global-fit versus
   group-fit crossover and multi-level spill. Measure wall/CPU time, RNG/shuffle
   loop share, allocations, admitted peak memory/RSS, temporary bytes/files,
   read/write passes and storage/cache conditions. Preserve cancellation,
   cleanup, validation, digest/conservation and publication guarantees.

For unchanged seeded algorithms require exact row order, filenames, lineage and
metadata parity. For a new exact algorithm require conservation/group isolation,
structural uniformity arguments, small exhaustive tests and predeclared
statistical diagnostics, without asserting equality of different random orders.
Keep performance and statistical datasets separate; finite tests cannot prove
uniformity. Promote only after whole-job gains on the relevant workload and
resource limits are demonstrated.
