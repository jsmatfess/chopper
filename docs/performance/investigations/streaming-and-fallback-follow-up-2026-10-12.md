## Streaming and fallback follow-up (2026-10-12)

Two extra passes have been removed without changing the logical algorithms:

- **Initial buffer-shuffle fusion:** when an explicit buffer shuffle is the first operation, parsed rows enter its replacement buffer directly. A final buffer shuffle serializes straight to the retained output plan; a composed pipeline retains only the shuffled intermediate dataset. Replacement draws, final draining draws, row IDs/ordinals, random domains and stage statistics match the prior executable. Later buffer-shuffle stages use the same implementation.
- **Reuse on grouping fallback:** each retained group file is already sorted by key/ordinal. When new keys or reordered rows force fallback, those files become a single logical sorted run in key order, with one active reader at a time. Only new rows need sorting. This avoids re-reading/re-sorting/re-writing the retained prefix and avoids one merge reader/head per bucket. Consumed run files are released as their readers advance; cancellation releases the remaining files.

Buffer shuffling now participates in the shared algorithm-workspace ledger, including decoded row allocations and unused vector capacity. Its quarter-budget ceiling remains bounded. Fused ingestion retains parser allocations rather than reconstituted spool rows, and capacity is now explicitly counted: configurations close to the old memory limit can need fewer buffer rows or a larger budget. There is no silent reduction of `buffer_rows` and no automatic switch to approximate mixing.

Diagnostics/UI add `fused_buffer_shuffles` and `routing_reused_runs`. The latter counts reused physical group files; `merge_inputs` counts logical streams, so several reused files can contribute just one merge input. A merge still decodes rows when consuming a reused run; the saved work is the preliminary replay and sort, not all decoding.

### Measured results

The expanded `scripts/benchmark-adaptive.py` compared the executable saved before this follow-up with the final executable: 15 shape/pipeline cases, three alternating repetitions per build, **90 full-job runs** with matching output fingerprints, filenames, stage statistics, logical digests and manifest entry metadata. WSL/Linux, warm caches, 32 MiB, one worker for the cases below. Generation and output verification are excluded. No compilation, native tests or browser tests overlapped the final benchmark.

| Case | Rows | Before | After | Time reduction | Temporary bytes written before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buffer shuffle, narrow | 100,000 | 0.0638 s | 0.0495 s | 22.5% | 7.28 → 1.09 MB |
| Buffer shuffle, 32 extra short columns | 60,000 | 0.2553 s | 0.1813 s | 29.0% | 25.48 → 4.49 MB |
| Buffer shuffle, 4 KiB payloads | 10,000 | 0.3186 s | 0.2894 s | 9.2% | 82.61 → 41.04 MB |
| Buffer shuffle → allocation | 120,000 | 0.2254 s | 0.1988 s | 11.8% | 55.12 → 39.99 MB |
| Partition, late new keys | 120,000 | 0.6157 s | 0.5701 s | 7.4% | 35.99 → 24.38 MB |
| Stratified allocation | 120,000 | 0.2838 s | 0.2666 s | 6.1% | See raw diagnostics |

The buffer window is 2,048 rows except for wide rows (512). Temporary write reductions are cumulative I/O, not necessarily peak-space reductions: buffer → allocation still peaks at 38.23 MB in both builds because later work dominates. Late-key peak temp decreases from 24.35 to 17.72 MB, and final merge inputs decrease from four to two.

An intermediate implementation reused each bucket as an independent merge input. It reduced writes but made the late-key job slower; the final implementation concatenates the disjoint ordered buckets logically without copying them. [Intermediate observations](../../evidence-originals.md#sha256-541f1a35c807fd41a00cf4f349e0fcd0e3ec4a36e07a9daeb9084211692965f7 "Original: docs/benchmarks/adaptive-streaming-first-2026-10-11.jsonl") retain that experiment; use the [final observations](../../evidence-originals.md#sha256-55c9fbdb104843e643dc53a5af926500f2d88f4c728fea1bb2528675992fb036 "Original: docs/benchmarks/adaptive-streaming-2026-10-12.jsonl") for the table above.

The full matrix is not uniformly faster. Wide uniform shuffle measured 0.3143 → 0.3436 s (9.3% slower) overall, while its median analysis improved from 0.2407 → 0.2355 s. Full-job repetitions varied substantially (before 0.2915–0.3557 s; after 0.2750–0.3465 s), with most variation outside analysis. These short warm-cache measurements do not establish cold-storage, browser throughput, or billion-row performance, nor do they justify a universal memory policy.

Validation: **50 native tests**, **15 browser contracts**, all four UI test files, TypeScript, formatting, Clippy with warnings denied, and native/WASI release builds. A new 14-case fixture captures pre-fusion outputs for window sizes below/equal/above input length, composed operations, repeated shuffles, encoded byte caps and empty input. Deterministic I/O assertions verify one write per row through the tested fallback and no extra spool for a final buffer shuffle. Tests also cover reservation release, cancellation while consuming a reused run, and browser parity for both stable and late-changing cardinality. Broader host-aware budgets and quick previews remain roadmap work.
