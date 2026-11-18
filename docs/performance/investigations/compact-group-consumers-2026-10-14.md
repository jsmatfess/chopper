## Compact group consumers, 2026-10-14

Resident partition and exact-assignment output now retains compact fields through
final CSV serialization and intermediate dataset writes. This includes fused
partition/assignment shuffles, stratified assignment's partition output, and
resident sorting for streaming grouping fallback. Partition boundaries compare
borrowed keys and construct lineage from borrowed field views; discarded keys no
longer require unpacking. Existing owned-row sink adapters remain supported.
Ordinal resets, selected-column order, seeded behavior and workspace lifetimes
are unchanged. This is a consumer-only extension: external decoding, stage
ingestion, tuple-key construction and digest ingestion still use owned rows.

### Complete-job evidence

100,000 rows, 33 columns, AMD Ryzen AI 9 HX 370, WSL2, warm uncontrolled storage.
Three alternating repetitions per build/case at one and four workers, plus separate
whole-job allocator runs. Baseline binaries were built from the existing dirty
workspace before this change; hashes are recorded in the
[raw results](../../evidence-originals.md#sha256-acc72f95e2fc9e610118ee59df4ce3044626c175129b337e38db0886d639e849 "Original: docs/benchmarks/compact-groups-native-2026-10-14.jsonl"). Compilation and
Rust tests finished before the timing suite. Resident cases use 1,024 MiB; the two
partition spill cases use 32 MiB and select automatic disk routing. The wide case
includes one 1.8 MB field. `probabilistic_sort` forces sorting to exercise the
resident output path instead of direct routing.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| partition / 1 | 0.368 → 0.291 |
| partition / 4 | 0.347 → 0.281 |
| partition_shuffle / 1 | 0.382 → 0.326 |
| partition_shuffle / 4 | 0.383 → 0.323 |
| assign / 1 | 0.415 → 0.318 |
| assign / 4 | 0.395 → 0.312 |
| assign_shuffle / 1 | 0.431 → 0.358 |
| assign_shuffle / 4 | 0.417 → 0.348 |
| probabilistic_sort / 1 | 0.339 → 0.284 |
| probabilistic_sort / 4 | 0.336 → 0.262 |
| partition_spill / 1 | 0.354 → 0.354 |
| partition_spill / 4 | 0.356 → 0.354 |
| partition_wide / 1 | 0.382 → 0.380 |
| partition_wide / 4 | 0.370 → 0.378 |
| pipeline / 1 | 0.648 → 0.551 |
| pipeline / 4 | 0.613 → 0.543 |

The resident grouping cases improve 14–24% on this fixture. Whole-job allocation
counts fall by approximately 3.4 million (about 7.0 → 3.6 million for standalone
grouping, 10.5 → 7.1 million for the composed pipeline). At one worker, partition
requested bytes fall from 459.8 MB to 376.9 MB and median CPU time from 0.32 s to
0.25 s. RSS ranges are 46,432–46,584 KiB before and 46,096–46,340 KiB after;
algorithm reservation stays at 45,888,890 bytes. This reduces allocation churn,
not retained row memory. Routed spill cases have unchanged allocation counts
and no established timing improvement. Temporary traffic, peak reservations,
sort-run counts and merge counts match baseline/candidate pairs throughout.
Raw records retain timing ranges, allocation buckets, RSS and sort timings.
No new sampled CPU stacks, controlled-storage or multi-level-merge measurements
were collected in this pass.

All 128 native runs (96 timed and 32 allocator-instrumented) verify identical
output bytes/order, names, lineage, stage metadata, row/byte counts and logical
digests. All 81 existing workspace tests and the new compact/owned partition
parity test pass, as do formatting, all-target workspace Clippy with warnings
denied and the release WASI build. The new test covers selected-column ordering,
empty fields, NUL, Unicode, multiline fields, wide-owned payloads, key removal and
shuffled/unshuffled ordinals. Existing contracts cover grouping across budgets,
strict caps, cancellation, publication and empty allocations. Server tests needed
loopback access outside the restricted sandbox.

Browser execution was attempted but Chromium could not load `libnspr4.so` in this
environment. There is no new browser runtime/parity or browser speedup evidence.
The browser harness now includes partition, partition-shuffle and assignment-shuffle
cases for follow-up; its JavaScript syntax check passes.

Reproduce after saving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-group-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-group-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases partition partition_shuffle assign assign_shuffle probabilistic_sort partition_spill partition_wide pipeline
# Once Chromium dependencies are available:
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper \
  100000 1 partition,partition_shuffle,assign_shuffle 16
```
