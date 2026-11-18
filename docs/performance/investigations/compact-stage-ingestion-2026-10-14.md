## Compact stage ingestion, 2026-10-14

Intermediate partition and exact-assignment stages now decode spool rows directly
into checked compact fields and transfer them to the sorter. This includes
stratified assignment's partition and allocation passes and fused downstream
shuffles. Tuple-key construction and partition shuffle lineage accept borrowed
fields, preserving selected-column order, NUL escaping and seeded domains.
The public owned-row interfaces remain available. Spill framing and defaults are
unchanged. Source CSV parsing and logical digest ingestion still use owned fields.

Retained rows trim decoder capacity before sorting. The sorter preserves the
owned decoder's row-size limit and largest-row/key merge allowance, including the
original generated key capacity. Actual compact storage remains charged to the
existing reservation. Rare wide spool rows now retain a contiguous checked buffer
instead of rebuilding field strings. Decode buffers are not yet reused across
rows: this pass removes unpack/repack churn, not every row allocation.

### Complete-job measurements

100,000 rows, 33 columns, AMD Ryzen AI 9 HX 370 on WSL2, warm uncontrolled storage.
Baseline binaries were rebuilt and saved from the existing dirty workspace before
editing; hashes are in the raw results. Three alternating repetitions per
build/case at one and four workers, followed by separate allocator runs.
Compilation and tests finished before timing. Resident cases use 1,024 MiB;
`partition_pipeline_wide` and `assign_pipeline_spill` use 32 MiB. The wide case
includes one 1.8 MB field. The new pipeline cases run balanced(2) → partition or
assignment → uniform shuffle; `pipeline` remains shuffle → balanced(4) → partition.
Standalone exact assignment also reads an intermediate dataset and is affected.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| resident / 1 | 0.273 → 0.267 |
| resident / 4 | 0.268 → 0.268 |
| partition / 1 | 0.300 → 0.300 |
| partition / 4 | 0.308 → 0.313 |
| assign / 1 | 0.385 → 0.338 |
| assign / 4 | 0.405 → 0.344 |
| pipeline / 1 | 0.578 → 0.596 |
| pipeline / 4 | 0.607 → 0.563 |
| partition_pipeline / 1 | 0.441 → 0.399 |
| partition_pipeline / 4 | 0.446 → 0.383 |
| assign_pipeline / 1 | 0.397 → 0.338 |
| assign_pipeline / 4 | 0.383 → 0.327 |
| partition_pipeline_wide / 1 | 0.559 → 0.507 |
| partition_pipeline_wide / 4 | 0.559 → 0.520 |
| assign_pipeline_spill / 1 | 0.428 → 0.365 |
| assign_pipeline_spill / 4 | 0.440 → 0.372 |

Affected assignment and balanced-first grouping medians improve about 7–15% on
this fixture. Shuffle-first pipeline timing is mixed: one worker regresses about
3% and four workers improve about 7%, with overlapping ranges; no consistent
speedup is established for that case. Resident shuffle and first-stage partition
controls retain identical allocation counts and show no established speedup.
Raw records include all timing ranges rather than only these medians.

At one worker, exact assignment allocations fall from 3,600,989 to 200,989;
reallocations rise from 59 to 100,059 because retained decoder buffers are trimmed.
Requested bytes fall from 134.2 MB to 131.3 MB, median CPU time from 0.35 s to
0.31 s, and RSS ranges from 46,328–46,628 KiB to 46,092–46,368 KiB. Peak reservation
remains 46,088,890 bytes. Balanced → partition → shuffle likewise removes
3.4 million allocations, with requested bytes 144.7 → 141.8 MB. This is chiefly
an allocation-churn improvement. RSS does not universally fall: the one-worker
assignment spill case rises from 13,372–13,456 to 13,896–13,968 KiB.

All 128 native jobs (96 timed, 32 allocator-instrumented) verify identical output
bytes/order, names, lineage, stage metadata and logical digests. Temporary bytes,
peak reservations, sort runs and merge counts match baseline/candidate pairs.
[Raw results](../../evidence-originals.md#sha256-be96976e47edaa9c5d72ac3e6ca213a5a335e236606e86f4ecf8efff2b504ade "Original: docs/benchmarks/compact-ingestion-native-2026-10-14.jsonl").

### Validation and remaining scope

All 83 workspace tests passed, including loopback server tests outside the
restricted sandbox. New differential coverage checks dataset decoding, spool
bytes, arbitrary selected-column order/repeated columns, empty/NUL/Unicode/wide
fields, sort order, decoded merge allowances and truncated datasets. Existing
corrupt-frame, multi-level merge, seeded parity, strict cap, cancellation and
publication contracts pass. Formatting, workspace/all-target Clippy with warnings
denied and the release WASI build passed.

Chromium startup fails because `libnspr4.so` is unavailable; there is no new browser
runtime evidence. No new sampled CPU stacks, controlled-storage measurements or
large multi-level performance comparison were collected. Broad selected-column
and high-cardinality calibration remains open; compact tuple selection scans
borrowed field iterators. Reusable external decode storage, digest consumers and
remaining ingestion paths are still unchecked follow-ups in TODO.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-ingestion-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-ingestion-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases resident partition assign pipeline partition_pipeline assign_pipeline \
    partition_pipeline_wide assign_pipeline_spill
```
