## Compact resident consumers, 2026-10-13

Resident uniform and Fisher–Yates shuffle rows now retain packed fields through
final CSV serialization and intermediate dataset writes, including fused balanced
splits and shuffles within later pipeline stages. Borrowed field iteration avoids
reconstructing a vector and one string per short field; uniform shuffle also
avoids reconstructing its discarded random key. Wide fields retain their existing
owned storage. The public owned-row iterator and sink methods remain available;
custom sinks get an unpacking adapter unless they implement the compact method.
Reservations remain live until the compact iterator is dropped.

External merge/routing readers and partition/assignment output still use owned
rows. Tuple-key construction and logical digest ingestion still consume owned
fields. Reusable checked external decoding and those consumers are the next
step; this pass does not change spill framing, sorting, seeded order or defaults.

### Complete-job measurements

Three alternating A/B repetitions on warm, uncontrolled WSL2 storage, AMD Ryzen
AI 9 HX 370, 100,000 rows and 33 columns. Resident/pipeline/Fisher–Yates cases use
a 1,024 MiB configured budget; spill cases use 32 MiB. Both native builds include
pre-existing uncommitted work; their hashes are recorded in the raw data.

| Case / workers | Median seconds before → after | Whole-job allocations before → after |
| --- | --- | --- |
| Resident uniform / 1 | 0.359 → 0.291 | 7,000,866 → 3,500,866 |
| Resident uniform / 4 | 0.355 → 0.284 | 7,000,908 → 3,500,910 |
| Shuffle → balanced → partition / 1 | 0.779 → 0.663 | 14,003,369 → 10,503,369 |
| Shuffle → balanced → partition / 4 | 0.733 → 0.657 | 14,003,415 → 10,503,413 |
| Fisher–Yates / 1 | 0.346 → 0.288 | 6,900,870 → 3,500,870 |
| Fisher–Yates / 4 | 0.359 → 0.302 | 6,900,912 → 3,500,916 |
| Spilled uniform / 1 | 0.371 → 0.372 | 7,000,909 → 7,000,909 |
| Spilled uniform / 4 | 0.372 → 0.372 | 7,000,955 → 7,000,954 |
| Rare 1.8 MB field / 1 | 0.378 → 0.374 | 7,000,908 → 7,000,908 |
| Rare 1.8 MB field / 4 | 0.382 → 0.377 | 7,000,954 → 7,000,954 |

Resident uniform improves by 19–20% on this fixture, with approximately half the
allocations. At one worker its cumulative requested bytes fall from 458.7 MB to
374.2 MB and median CPU time from 0.31 s to 0.24 s. Wall-time ranges are
0.359–0.366 s before and 0.283–0.291 s after. Peak RSS is essentially unchanged
(43,296–43,412 KiB before, 42,824–43,092 KiB after); peak algorithm reservation is
45,288,890 bytes in both builds. Savings concern allocation churn, not retained
row storage. Pipeline jobs improve 10–15%; Fisher–Yates improves 16–17%.
Small publication allocation-count differences reflect runtime bookkeeping.

Spill cases retain the old decoder and show no material allocation improvement.
A separate 300,000-row rare-wide run likewise shows overlapping timing ranges.
The 1.3-million-row fixture exercises 71 initial runs and two merge operations;
median time is 5.545 → 5.613 s with overlapping ranges and identical allocation
counts, so it establishes compatibility rather than an improvement. Its raw record
includes complete-job timing, allocations and conservation checks.
Temporary traffic, sort/merge counts and peak workspace reservations match each
baseline/candidate pair. Allocation size buckets, sort timings, CPU time, RSS and
ranges are in the raw records. New sampled CPU/allocation stacks, controlled
storage and browser allocation profiles were not captured.

[100,000-row measurements](../../evidence-originals.md#sha256-a856991bbe5cf6d825f3ae3610a2fafa15082cf6d2b475f391e048f6d0afd9ef "Original: docs/benchmarks/compact-native-2026-10-13.jsonl"),
[300,000-row spill measurements](../../evidence-originals.md#sha256-d6d008ee12fd956bb1861c952af9fec1efaac982e132ca7bc61fcd352ffa76bb "Original: docs/benchmarks/compact-spill-2026-10-13.jsonl"),
[multi-level merge measurements](../../evidence-originals.md#sha256-4a7d1418d32aca34e8a6918c27cc2b57d86d05e4b0fbe4dd8bd1478c9c441d4a "Original: docs/benchmarks/compact-multilevel-2026-10-13.jsonl").

### Validation and reproduction

All 81 workspace tests, formatting, workspace/all-target Clippy with warnings
denied and the release WASI build pass. Added checks cover compact iterator
reservation lifetime, field views, UTF-8/UTF-16 serialization and identical spool
lengths/bytes for packed and wide-owned fields. Existing contracts cover collision
refinement, corruption, cancellation, caps, output publication and composed jobs.

All 104 native A/B and allocation runs match output bytes/order, names, lineage, stage
metadata and logical digests. Six native/Chromium 156 jobs match output hashes,
names, row counts, CSV byte counts and logical digests for resident uniform,
spilled uniform and gzip output (100,000 rows, four columns, 16-byte payload).
These include browser OPFS export and establish candidate platform parity, not a
browser A/B speedup or a rerun of the full browser contract suite.
[Browser/native parity records](../../evidence-originals.md#sha256-c01b132251be7a5bc9aec7512d63083cb6521e4e33c10598a873311064d9c53d "Original: docs/benchmarks/compact-browser-2026-10-13.jsonl").

Retain baseline binaries before building the candidate, then run:

```sh
cargo build --release -p chopper --bin chopper --example allocation-profile
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-compact-before/chopper --after target/release/chopper \
  --before-allocator /tmp/chopper-compact-before/allocation-profile \
  --after-allocator target/release/examples/allocation-profile \
  --rows 100000 --repeats 3
# Repeat with --rows 300000 --cases rare_wide, then
# --rows 1300000 --workers 1 --cases rare_wide for multiple merge levels.
bash scripts/build-browser.sh
node scripts/benchmark-engines.mjs target/release/chopper \
  100000 1 uniform32,uniform256,gzip 16
```

The local Chromium run additionally used
`LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`
for staged browser system libraries. Server tests and Chromium required loopback
permissions outside the restricted sandbox.
