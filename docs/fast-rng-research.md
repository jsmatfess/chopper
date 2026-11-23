# Fast random-source experiment

Current status (2026-10-24): buffered XOF implementation and build features are removed.
The dated design, measurements and request examples below are historical and
require matching pre-removal artifacts; they are not current usage guidance.

Researched 2026-10-18 against primary sources. The keyed XOF experiment is now implemented behind `experimental-fast-rng`;
[complete-job results](performance.md#versioned-buffered-blake3-shuffle-source-2026-10-18)
keep it opt-in. This report records its primary-source design and limits. It extends the RNG discussion in
[randomization planning](maintainer/research/randomization-planning-research.md); it does not repeat
the completed shuffle diagnostics or establish statistical uniformity.

## Recommendation

Benchmark a versioned, buffered **keyed BLAKE3 XOF** first. It uses the existing
dependency, keeps cryptographic pseudorandomness, supports source-ID addressing
and amortizes hash setup/output compression across draws. Keep the current
per-draw BLAKE3 stream as the unchanged v1 control. An entropy-seeded flexible
job should use the same generator after obtaining its recorded seed once;
fresh entropy changes replay policy, not generator throughput.

Repository facts: [random.rs](../crates/chopper-core/src/random.rs) currently
constructs a keyed hasher for each `(row, index)` block, emits 32 bytes, and
uses only eight bytes for each bounded draw or sixteen for each primary sort
key. Domain derivation already includes seed, original logical operation index
and exact serialized parent lineage. `Cargo.lock` currently pins BLAKE3 1.8.7;
the core requests its pure Rust implementation. Preserve those existing v1
functions and assign the candidate a separate identity.

The official `OutputReader` documentation explicitly warns that short repeated
`fill` calls recompute compression: output is not internally buffered. It
recommends multiples of 64 bytes. Reading eight bytes directly per Fisher–Yates
draw therefore misses the principal batching opportunity. `set_position`
provides random access; its documented maximum is **2^64 − 1 output bytes**,
with unspecified behavior beyond that bound. This is an API/output-length
limit, not a claimed PRNG period. [BLAKE3 1.8.7 OutputReader](https://docs.rs/blake3/1.8.7/blake3/struct.OutputReader.html).

## Concrete portable candidate contract

Implemented identity: `chopper-fast-rng-blake3-xof-1`. Pin this byte-level contract
and known-answer vectors independently of crate type layout or buffer capacity:

1. Compute existing `D = json_domain(effective_seed, original_operation,
   parent_lineage)`. Compute `K = algorithm_domain(D,
   "chopper-fast-rng-blake3-xof-1")`. Do not derive group streams by consuming a
   worker-global generator.
2. Define page stream `X(purpose, page)` as BLAKE3 keyed hashing with key `K`,
   message `purpose_byte || page_u64_le`, finalized with `finalize_xof`.
   Purpose `0x01` is primary random keys; `0x02` is bounded-draw words.
   Each page exposes exactly the first **65,536 bytes**. A page's reader may be
   constructed or cloned on demand; no 64 KiB allocation is required.
3. For every source ID `r: u64`, primary key bytes are
   `X(0x01, r >> 12)[16 * (r & 4095) .. 16 * (r & 4095) + 16]`.
   All arithmetic after masking fits comfortably in `u64`, including at
   `r = u64::MAX`; no `16 * r` calculation exists. Even the final page access
   ends at byte 65,536, far below the reader limit. Compare the sixteen bytes
   lexicographically, matching the existing packed-key convention.
4. For zero-based raw draw index `i: u64`, read eight bytes at
   `X(0x02, i >> 13)[8 * (i & 8191) .. 8 * (i & 8191) + 8]` and decode
   `u64::from_le_bytes`. Consume raw draws in index order, including rejected
   bounded draws. Track exhaustion explicitly after the last `u64` index;
   never wrap to an old stream.
5. For key collisions derive `T = algorithm_domain(K,
   "random-key-ties-1")` and reuse existing `compare_ties(T, source_a,
   source_b)`. Refinement must remain independent of comparator call order,
   spill layout and worker scheduling. Preserve the existing same-ID equality
   rule and checked source-ID uniqueness; never resolve distinct-row ties by
   source ID or encounter order.

This paging/framing is a **new proposed application construction**, rather than
a BLAKE3 API promise. Its use of keyed mode, XOF and byte output is supported by
the [official Hasher API](https://docs.rs/blake3/1.8.7/blake3/struct.Hasher.html).
Validate the underlying implementation against the project's published
[1.8.7 reference vectors](https://github.com/BLAKE3-team/BLAKE3/blob/1.8.7/test_vectors/test_vectors.json),
then add independent fixed vectors for this framing, endian conversion, page
boundaries, final IDs and collision domain. Rust native and WASI must agree
byte for byte; buffer capacity must not enter the algorithm identity.

Use a charged 64-byte cache first. Primary keys can cache the aligned output
block containing four source IDs, seeking when a group has gaps; raw draws
consume eight words per cached block sequentially. Compare charged 256/1,024
byte read-ahead only where useful and retain unused bytes across calls. Never
discard the rest of a refill between bounded draws. Sparse group IDs can lose
most key-batching gains: skipping unavailable IDs is valid, assigning a new
sequential key to each encounter is a different contract. Replays after denied
resident admission must reconstruct the same group stream from its domain.

## Bounded draws and collisions

Keep current modulo-and-reject mapping for the first experiment: for positive
bound `b`, reject values below `2^64 mod b`, then return `value mod b`. The
accepted interval has a length divisible by `b`, so each residue has equal
preimage count under ideal uniform raw words. `b = 1`, powers of two,
`2^63 + 1`, `u64::MAX`, zero rejection and stream exhaustion need explicit
boundary tests. A new random source already changes results; keeping mapping
fixed isolates its cost. Lemire's multiply-and-reject method is a useful
separate comparison, but requires exact wide arithmetic and a distinct bounded
mapping identity; portable `u128` multiplication can have different WASI cost.
[Lemire's original paper](https://arxiv.org/abs/1805.10941).

Do not conflate buffering stream bytes with producing multiple bounded
integers from one word. The latter has its own rejection/consumption contract;
defer it until the simpler source change has whole-job evidence.
[Brackett-Rozinsky and Lemire's batched method](https://arxiv.org/abs/2408.06213).

Under ideal independent 128-bit primary keys the union bound for any collision
is `N(N−1)/2^129`; this is an analytical ideal-model bound, not a guarantee for
every seed. Rare collisions still require refinement and forced-collision
tests through external merge passes. Compare identities and fields, including
duplicate payloads. Key truncation offers less collision resistance than the
full hash, as the [BLAKE3 security notes](https://docs.rs/blake3/1.8.7/blake3/struct.OutputReader.html#security-notes)
explain. Public recorded seeds also mean the shuffle is not secret.

## Other candidates and limitations

| Candidate | Useful comparison | Constraint |
| --- | --- | --- |
| Pinned xoshiro256++ 1.0 | Small scalar state; potential non-cryptographic speed control | Different quality/security contract; source-ID random access needs jump machinery or retained keys |
| Named ChaCha12 with a pinned stream layout | Buffered cryptographic alternative if XOF misses whole-job targets | Adds dependency/scope; fixed 12-round, counter/stream layout and byte consumption must be specified |
| `SmallRng`, `StdRng`, worker-local ambient RNG | Convenient APIs | Do not use an unspecified or platform-selected algorithm as a pinned output contract; [Rand explicitly distinguishes these from named portable generators](https://docs.rs/rand/0.10.3/rand/rngs/index.html) |

The xoshiro authors' [reference C source](https://prng.di.unimi.it/xoshiro256plusplus.c)
identifies **xoshiro256++ 1.0** and gives the exact transition: output
`rotl(s0+s3,23)+s0`, temporary `s1<<17`, the stated XOR sequence, then
`s3=rotl(s3,45)`; all additions wrap at 64 bits. Its zero state is forbidden.
A portable control could initialize four little-endian words from a separately
domain-separated BLAKE3 digest and map the all-zero digest to a fixed nonzero
state. Pin that exceptional mapping, emit full 64-bit outputs and use the same
bounded mapping. Consecutive output pairs could supply 128-bit keys only in a
separately identified sequential-input experiment; they do not provide cheap
arbitrary source-ID lookup.

The authors report period `2^256−1` and no systematic BigCrush/Hamming-weight
failures for xoshiro256++, while explicitly classifying it as
non-cryptographic. Similar seeds require care; hashed per-group seeds avoid
the obvious closely related initial states but do **not** prove independent or
nonoverlapping streams. Jump-spaced subsequences provide a different explicit
contract. Even the authors recommend a stream cipher first and warn that
isolated generator timings can misrepresent application cost.
[Authors' design, quality and measurement discussion](https://prng.di.unimi.it/).

The named [ChaCha12 implementation documentation](https://docs.rs/rand_chacha/0.10.0/rand_chacha/struct.ChaCha12Rng.html)
specifies a 256-bit seed, 64-bit block counter, 64-bit stream ID and 64-byte
blocks, giving `2^70` bytes before cycling per stream. This differs from RFC
8439's IETF ChaCha20 layout and round count; that RFC alone cannot specify a
ChaCha12 RNG. Reproducible parallelism requires associating streams with
logical work, not whichever worker obtains a task first.
[Rand parallel RNG guide](https://rust-random.github.io/book/guide-parallel.html).

No finite-state deterministic generator proves a literally uniform
distribution over every permutation for arbitrary dataset sizes: the set of
seeds and reachable states is finite. “Full shuffle” here means an unbiased
permutation construction under ideal random draws, instantiated with a named
PRNG, rather than approximate bounded-buffer mixing. Statistical tests can
detect defects but cannot establish independence or uniformity.

## Experiment acceptance

Measure identical complete native/WASI jobs with old per-draw source versus
pinned XOF, then fixed versus once-entropy-seeded XOF. Alternate execution order;
include global contiguous IDs and sparse partition IDs, tiny/many groups,
Fisher–Yates, random-key resident/external, skew and wide payloads. Measure raw
source and shuffle-loop cost separately from whole-job wall/CPU time,
allocations, admitted peak memory/RSS, temporary I/O and cancellation cleanup.
Charge cache and generator state before admission. Keep stream scheduling
deterministic first. Retain the flexible prepared snapshot and record generator,
key framing, bounded mapping and collision identities. Run existing predeclared
[shuffle diagnostics](shuffling-research.md) with a separately declared candidate
family; use exhaustive small ideal-draw tests and native/WASI vectors for the
construction. Keep defaults until complete-job evidence supports promotion.
