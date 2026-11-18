# Independent random-bucket full shuffle

Current status (2026-10-24): independent random buckets implementation and build features are removed.
The dated design, measurements and request examples below are historical and
require matching pre-removal artifacts; they are not current usage guidance.

Implemented and measured opt-in prototype, 2026-10-19. The 330 native timed
jobs, 110 separate allocation/storage censuses and 150 native/WASI complete-job
comparisons/controls pass their field, unique-ID, grouping and publication checks.
The candidate often beats the previous order-preserving prefix implementation
but generally trails the original seeded default, with substantial overhead for
many small parents. No default change is justified. This is a separately
versioned flexible algorithm, not the existing order-preserving prefix experiment.
See the [complete measurements, resources and limits](performance.md#independent-random-bucket-full-shuffle-experiment-2026-10-19).

The explicit selection is `full_shuffle_policy: "flexible_v1"` and
`full_shuffle_algorithm: "independent_buckets_v1"`. It applies to requested
`auto` full shuffles only; explicit uniform, Fisher–Yates and buffer retain their
existing implementations. The omitted/default algorithm remains `adaptive_v1`.
The engine feature is `experimental-random-buckets`; unsupported builds reject
the requested algorithm before opening input. Imported jobs retain the optional
setting without adding an unsupported default UI choice.

## Fixed construction

Algorithm identity: `independent-random-buckets-v1`. For each existing logical/
physical parent, derive the existing scope domain D, then set the root node key
to `algorithm_domain(D, "independent-random-buckets-v1")`. A node's routing key
is `algorithm_domain(node_key, "routing-v1")`; route source ID i by
`random::block(routing_key, i, 0)[0] & 15`. Thus sixteen buckets are assigned
independently under the ideal keyed-source model, with no modulo bias or
encounter-counter dependence. Traverse nonempty buckets in numeric order.
A child node key is `blake3::keyed_hash(node_key, [3, bucket_index])`.

A resident leaf uses `algorithm_domain(node_key, "resident-leaf-v1")` with the
requested full-shuffle source and existing Fisher–Yates bounded mapping. Its
randomness is separate from routing and all other nodes. If a node cannot be
resident, route again only below depth two and within seventeen routing
attempts per original parent. This permits the root and all sixteen first-level
children to route at most once; no record traverses more than two routing
levels. At the depth/pass bound or typed routing-memory denial, use the existing
external-capable full random-key shuffle under
`algorithm_domain(node_key, "external-fallback-v1")`. That fresh fallback is
independent of the routing outcomes that caused the stop.

The BLAKE3 row-nibble routing source is fixed by the algorithm version. The job's
`full_shuffle_rng` selects resident-leaf draws and fallback sort keys; XOF cache
sizes preserve addressed bytes for matching leaf plans. This mixed construction
must appear in the actual algorithm/RNG audit rather than implying routing used
an XOF stream. Finite cryptographic seeds do not prove ideal independence or
uniformity; the mathematical statement below is about ideal random choices.

## Why fixed bucket order is uniform

For N unique IDs and B independent equiprobable buckets, fix any desired output
permutation. Given a count vector n₁+…+nᴮ=N, exactly one membership assignment
makes its consecutive output ranges belong to the corresponding buckets.
Its probability is B⁻ᴺ. Independent uniform leaf permutations then have
probability `1 / ∏nᵢ!`. Summing over all count vectors gives

`B⁻ᴺ × Σ[1/∏nᵢ!] = B⁻ᴺ × Bᴺ/N! = 1/N!`.

This requires fresh full leaf shuffles. Concatenating input-order buckets,
shuffled input chunks or leaves correlated with routing does not establish it.
A recursively routed leaf has the same conditional uniform-permutation law;
substituting a separately randomized full-key fallback preserves it. Admission/
stopping decisions must precede consuming that node's leaf/fallback randomness.
Errors during emission abort the job; they must never reroute already emitted
rows. The proof applies independently inside every existing parent and composes
with the separately proved exact-allocation range cut.

## Bounded storage and acceptance

Use at most sixteen charged writer states/buffers per active routing level,
existing checked compact framing and a reusable charged decoded row. Seal all
bucket writers before admitting leaves. Emit shuffled resident leaves directly
into the next immutable dataset or final CSV snapshot, avoiding the old prefix
candidate's extra shuffled-leaf materialization. Release an owned source node
before descending into its completed children. Typed denial while constructing
a route discards its tentative files before replaying that same un-emitted node;
malformed data, cancellation and disk/encoding failures propagate.

Record parent scope, algorithm/source versions, bucket path, attempted/completed
routing passes, processed routing rows, depth, resident/fallback leaf choices,
reasons and existing logical temporary counters. Keep prepared-snapshot replay
and original logical metadata/caps. Test ideal small-case multiplicities and a
negative input-order-leaf control, forced routing skew, depth/pass bounds,
oversized rows, admission denial, field/ID/group conservation and clean failure.

Measure alternating complete jobs against flexible full-key execution and the
old order-preserving prefix candidate, with directly emitted leaves. Include
resident/external sizes, sparse/many/skewed parents, wide/rare-wide records,
downstream splits, one/four native workers and browser OPFS. Separate CPU/time
from allocator/storage censuses; capture publication-inclusive logical traffic
and sampled staging/retained-output space. WSL caches and virtual-device counters
do not establish physical SSD throughput. Keep defaults until whole-job and
resource evidence supports promotion.
