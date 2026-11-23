# Performance research archive (2026-10-12)

Historical design/research: buffer-shuffle descriptions and negative controls below
refer to pre-removal builds. The current engine rejects that strategy and its
configuration fields; see [current specification](../../specification.md#shuffling-and-seeds).

Historical assessment before the parser/merge, inline-key and explicit-option implementations. Recommendations and numerical estimates below are preserved as hypotheses from that review, not current TODOs or measured gains. In particular, later measurements found no clear Fisher–Yates speedup and slower interleaved splitting on the tested fixture.

Use [current opportunities](../../performance-opportunities.md), [measured results](../../performance.md), and the [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for current status. Primary-source links below are the original research references; this documentation reorganization did not reverify them.

## Recommendation

Prioritize reducing per-record allocation, decoding and hashing overhead. Then
specialize the exact shuffle sorter. Broader automatic planning and concurrency
remain useful, but they cannot remove this repeated work.

| Priority | Opportunity | Status relative to existing notes | Expected beneficiaries | Effort |
| --- | --- | --- | --- | --- |
| 1 | Reusable compact records from parsing through output | Allocation/compact representation already identified; end-to-end implementation remains incomplete | Nearly all jobs, especially many short columns | Medium–large, incrementally deliverable |
| 2 | Encoded merge payloads and small merge heads | Concrete extension beyond existing packed sort buffers and routing-run reuse | External shuffle/grouping, multiple merge levels, rare wide rows | Medium–large |
| 3 | Batch the existing logical digest byte stream | Hashing named as an investigation area; this specific sequential optimization is unexplored in the notes | Narrow rows and many columns | Small |
| 4 | Inline fixed-width shuffle keys, then radix sorting | No implementation or experiment found | Large uniform shuffles | Medium |
| 5 | Compact, optionally compressed spill blocks | Compact runs mentioned broadly; no block-format experiment found | Narrow records, repetitive data, slow temporary storage | Medium–large |

## 1. Reusable compact records and chunk scanning

The [parser](../../../crates/chopper-core/src/csv.rs) calls `fill_buf`/`consume` for each
byte, grows a fresh field allocation, transfers it to a String, and returns a
new `Vec<String>`. The [adaptive row representation](../../../crates/chopper/src/storage/adaptive.rs)
then packs short fields into another allocation and later unpacks them into
individual strings again. Packing reduces retained memory but does not eliminate
the initial allocations. [Output serialization](../../../crates/chopper/src/output.rs)
also requests a fresh serialized vector for each record.

Start with reusable parser and output scratch buffers for profiling and plain
streaming. For retained rows, use owned compact records or bounded arenas with
field offsets, allowing field access without one allocation per field. Account
for arena retention and conversion peaks; borrowed views cannot outlive reused
parser storage. Resolve fixed output encoding/dialect state once per writer.

A later parser experiment can scan contiguous ordinary bytes and bulk-copy them,
using scalar state transitions at quotes, escapes, delimiters and newlines.
The rust-csv author's [allocation-reuse discussion](https://burntsushi.net/csv/#amortizing-allocations)
provides primary-source precedent. [memchr](https://docs.rs/memchr/latest/memchr/)
documents vectorized byte search, including supported native/WASM targets; actual
WASM acceleration depends on build features. Neither source establishes a Chopper
speedup. Preserve strict UTF-8/encoding validation, bare-CR rejection, malformed
quote rejection, record limits and multiline semantics. A different CSV library
is not automatically a semantics-compatible replacement.

## 2. Merge encoded payloads without reconstructing fields

In [storage.rs](../../../crates/chopper/src/storage.rs), `read_row` allocates every field
and validates each as UTF-8. `MergeRows` holds these fully decoded rows. Every
intermediate `Sorter::merge` writes them back through `write_row`, although
`SortOrder::compare_parts` needs only the key, ID and ordinal.

Introduce an encoded frame interface: compare compact headers, carry opaque
payload bytes, and decode field views only when an operation actually requires
them. Initial work can preserve the current disk format; a payload length in a
new frame format would make bounded streaming copies simpler. Keep frame bounds
and corruption checks. This follows directly from the local comparator's inputs;
it is an architectural hypothesis, not a benchmark result.

The larger opportunity is retaining only a key/header per input stream. A winning
run's payload can be copied sequentially before its next header is loaded. This
avoids arbitrary gathers from a separate payload file. Final consumers requiring
owned rows still need a bounded decode allocation.

`Sorter::fan_in` currently uses the largest decoded row observed anywhere:
`(memory / 4 / (largest_row + 65536 + 128)).clamp(2, 64)`. Thus one wide row can
reduce fan-in for every run and increase merge passes. Compact heads address the
cause. A smaller interim experiment is per-run maximum metadata rather than one
global maximum, retaining conservative reservations. Never replace a maximum
with a percentile without a safe oversized-row path.

## 3. Batch logical digest updates

[Ingestion](../../../crates/chopper/src/engine.rs) currently calls BLAKE3 `update` for
the field count, each field length and each field's bytes. With C columns this is
1 + 2C calls per record. Accumulate exactly that byte stream in a bounded reusable
buffer and feed larger slices to the same hasher, flushing the final partial
buffer. Large fields can bypass the buffer after preceding bytes are flushed.

[BLAKE3's API documentation](https://docs.rs/blake3/latest/blake3/struct.Hasher.html)
states that input-buffer size limits SIMD parallelism. Benchmark a few sizes,
such as 16 and 64 KiB: the extra copy may outweigh reduced call overhead. This
preserves the digest because the concatenated input bytes are unchanged. It does
not permit concatenating independent random-key hashes or replacing the seeded
RNG. This is a small sequential experiment, distinct from proposed parallel hash
batches.

## 4. Specialize exact shuffle keys and sorting

Initial uniform shuffle creates a 16-byte key in a `Vec<u8>` for every row;
`sort_buffer` comparison-sorts complete `PackedRow` descriptors. Start by storing
the fixed key inline and comparing it without a heap indirection. Then benchmark
sorting compact key/index entries with radix sorting for sufficiently large runs.
Reserve auxiliary arrays and account for payload access locality.

[DuckDB's 2025 sort redesign](https://duckdb.org/2025/09/24/sorting-again)
describes fixed integer keys with optional payload references and adaptive radix
sorting; its [earlier external-sort design](https://duckdb.org/2021/08/27/external-sorting)
explains order-preserving binary keys. These are precedents, not transferable
speedup estimates.

Retain the exact current key byte ordering. Equal 128-bit keys must still invoke
Chopper's `compare_ties`; row-ID tie breaking would change the algorithm. Start
with `SortOrder::Random`, leaving variable-width group keys on the current path.

## 5. Reduce spill-format overhead

The current [row format](../../../crates/chopper/src/storage.rs) costs
`32 + key_bytes + 8 * field_count + payload_bytes`. A one-field, one-byte row with
a 16-byte shuffle key therefore takes 57 bytes before filesystem overhead, versus
2 source CSV bytes without a header. Not all temporary/output bytes use this
format, so this ratio is not a whole-job I/O multiplier.

Test block framing with bounded offsets/lengths and shared schema metadata before
adding compression. Optionally benchmark compressed blocks on repetitive input
and slow storage using the existing codec stack. Compression adds CPU and codec
memory per active reader; high-entropy payloads and warm local storage may regress.
Retain sequential reading, bounded decompression and cancellation cleanup. This
is inferred from the local representation; no codec benchmark establishes a win.

## Already explored or planned

Do not count ingestion-fused buffer shuffle, retained-route reuse, encoded output
snapshots, browser source read-ahead/handle caching, or parallel compression as new
opportunities: they already exist. Older sections of performance.md describe
historical gaps subsequently closed by its newest sections.

Higher-cardinality bounded routing, direct exact-allocation routing, memory-backed
snapshots, host-aware budgets and independent group parallelism are already in
[adaptive-execution.md](../../adaptive-execution.md). They remain worthwhile follow-ups,
but are not discoveries from this review. GPU acceleration and indiscriminate
read-ahead already have assessments; current evidence does not raise their priority.

## Experiment order and acceptance

Capture CPU/allocation profiles first, then test digest batching and reusable
serialization independently. Next test compact parsing/records and encoded
merges; benchmark inline keys separately from radix sorting. Only pursue spill
compression when physical I/O measurements justify it.

Measure complete-job time, allocations, CPU time, peak reservations/RSS, temporary
reads/writes and merge passes. Include native and browser, many short columns,
wide payloads, a rare maximum-sized row, several merge levels, and cold/slow
storage. Alternate baseline/candidate runs and report variability. Verify output
bytes/order, logical digests, names, stage metadata, forced random-key collisions,
malformed CSV, exact byte limits and cancellation. No numerical speedup estimate
is justified for these candidates yet.

## Product tradeoffs and rough estimates

Follow-up assessment, 2026-10-12. The ranges below are engineering estimates for
complete affected jobs after implementing the alternative, not benchmark results
or confidence intervals. A 2x speedup means half the elapsed time. Gains overlap
and must not be multiplied. Unaffected or already-streaming pipelines may gain
nothing; added routing overhead can also regress some cases.

| Requirement to relax | Alternative | Rough speedup on favorable affected jobs | Evidence strength |
| --- | --- | --- | --- |
| Globally uniform shuffle | Explicit bounded-buffer mixing | 1.3–3x for shuffle-dominated external jobs | Historical direct comparison measured 1.31x native; upper range is speculative |
| Exact randomized allocation counts, especially per stratum | Independent seeded categorical assignment with probabilities equal to requested percentages | 1.5–3x when counting/grouping/restoring order dominates | Architectural estimate; no implementation benchmark |
| Balanced files must be consecutive input ranges | Cyclic assignment to X outputs, retaining exact balance | 1.1–1.5x for standalone balanced splits with modest X | Estimate anchored by older balanced/plain timing ratio of 1.23x |
| Full CSV validation, normalized serialization and logical digest for every split | Explicit trusted, byte-preserving record/line splitting under a restricted input contract | 2–5x on CPU-bound simple splitting | Low-confidence hypothesis; requires removing substantial ingestion work |
| Exact counts/bytes displayed before approval | Confirm configuration first, stream to staged outputs, report exact results afterward | About 1–1.2x on current CPU-heavy native examples; up to roughly 2x on a shared I/O-bound device | Phase timing and byte-traffic model; not a requirement-imposed lower bound |

### Shuffle quality

The historical million-row comparison measured uniform/buffer times of
2.92/2.23 seconds natively (1.31x), before later optimizations. This is not a
current-build A/B measurement. Current profiling benchmarks put plain streaming
at 0.626 seconds and uniform shuffle at 1.733 seconds on the same fixture: 2.77x
is the comparison against eliminating shuffle work entirely, not an achievable
buffer-shuffle forecast. Buffer mixing still needs RNG, buffering and output work.
More merge levels can increase the opportunity, but other pipeline stages can
hide it. Buffer mixing retains source-locality bias, especially on sorted input.

Changing the v1 seeded permutation is a different decision from abandoning
uniformity. A versioned resident Fisher–Yates path could retain uniformity while
avoiding random-key sorting. Alternative uniform algorithms also exist; see the
primary [MergeShuffle research](https://arxiv.org/abs/1508.03167). There is no local
timing basis for a numerical promise. The current contract already scopes seeded
compatibility to algorithm version. An automatic resident/external algorithm
switch would need care to preserve resource-independent output, or an explicit
strategy recorded in the job. Dropping collision refinement alone is unlikely
to help normal jobs because 128-bit key collisions are extraordinarily rare.

### Allocation and balance

Independent assignment eliminates the need to know N or each stratum size before
making a decision. Every row selects exactly one destination; no rows are dropped.
The binary case uses the same independent-trial idea documented for
[PostgreSQL BERNOULLI sampling](https://www.postgresql.org/docs/current/sql-select.html),
but allocation routes excluded rows to the other destination. A seeded per-row
decision can remain reproducible and preserve encounter order. It cannot promise
the exact quotas in `engine::assign`, and requires a bounded writer/spool strategy.

For N=1,000,000 and p=0.8, the treatment count has standard deviation
sqrt(N*p*(1-p))=400. About 95% of ideal independent assignments fall within roughly
800 rows of 800,000 (0.08 percentage points). Small strata have much larger
relative deviations and may receive zero rows in a category. This tradeoff needs
explicit product wording; it does not preserve exact stratification.

Cyclic balanced splitting does not need approximate counts: assign row i to
output i mod X. Counts differ by at most one, and each output preserves its
input subsequence, but output membership is interleaved rather than contiguous.
Concatenating files no longer reconstructs input order, and downstream pipeline
membership changes. Enforce N>=X at completion before publication. Large X still
needs bounded buffering/handles. If a preceding stage already supplies N, little
counting work may be saved.

### Trusted raw splitting

The 158.19-second billion-row run spent 153.85 seconds in ingestion and 4.34 in
execution/publication. This identifies potential scope, not the fraction
removable by weaker validation. The 2–5x range assumes a specialized raw splitter
removes 50–80% of total CPU time; that assumption must be measured.

The fastest restricted mode could require one physical line per record, preserve
source bytes, omit full field/encoding validation and replace or omit the logical
record digest. It would not support transcoding or field-based operations.
Multiline CSV would require boundary-aware scanning and reduce the simplification.
Removing validation alone is not expected to deliver this range. Full support
for other dialects can remain available through the existing engine.

### Confirmation and publication are separable

For equally sized uncompressed source/output on one I/O-bound device, the current
source-read + snapshot-write + snapshot-read + output-write traffic is about 4D.
Direct staged output needs about 2D, giving an idealized 2x I/O-bound estimate.
Different devices, caching, compression and sorting invalidate that simple ratio.
The billion-row case's final phase was only 2.7% of elapsed time; deleting that
phase alone could yield at most about 1.03x there.

Safe atomic publication can remain. Moreover, plain final files could themselves
be the immutable prepared snapshot, preserving exact pre-confirmation reporting
while avoiding the copy. That requires output-filesystem staging during
preparation and different accounting/lifecycle handling. Therefore abandoning
exact confirmation is not necessary to obtain all of this potential saving.

Keep exact field equality, no lost/duplicated rows, overwrite protection, bounded
resources and strict byte caps. Streaming enforcement can retain byte caps.
Stable order already permits linear routing in eligible cases; dropping it alone
does not remove exact-allocation count dependencies. Broader encoding support has
no inherent requirement to slow a specialized UTF-8 path. The existing full-file
profile is optional, so avoiding profile-plus-preparation is already possible.

Recommended product additions: explicit probabilistic allocation, explicit mixing
quality, and an interleaved balanced split option. Consider trusted raw splitting
as a separate narrow feature. Preserve reproducibility with versioned algorithms
and explicit settings rather than removing it wholesale.

