## Merge and routed header key accounting (2026-10-16)

External merge heads and routed output headers now reserve key length before
allocation and reconcile actual `Vec` capacity before filling it. Merge heads
retain separate charges until consumed. Both encoded copying and decoded output
keep the winning key charged while loading its replacement, including old/new
key overlap. The fixed merge reservation no longer estimates every head from
`largest_key`; fan-in planning still uses that conservative size estimate.
Routed output retains its header key charge through decoding.

Decoded winners continue using the existing conservative merge/routed row
allowances after the call returns. This pass does not transfer a header charge
into compact payload accounting, which would double-charge payloads against
those allowances. Owned intermediate decoding, actual decoded/conversion
overlap, retained profiling/cache metadata, file/runtime metadata and sorting
overhead still need complete accounting. The ledger is not a complete
live-memory or RSS cap. Algorithms, v1 seeded order and spill framing are
unchanged. Target-SSD/cache calibration and other-platform validation are
outside this WSL pass.

Four new tests exercise shared just-below/at/above header capacity limits,
heterogeneous keys with an underestimated planner hint, simultaneous winning
and replacement keys on encoded-copy/owned/compact consumers, routed decode
lifetime, truncated keys and cancellation cleanup. All 141 workspace tests,
59 combined experimental-feature library tests and 24 Chromium/WASI contracts
pass. Formatting, Clippy with warnings denied and native/WASI release builds
pass. The HTTP integration tests and Chromium checks require loopback access;
Chromium uses the staged libraries under
`/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

Complete native comparisons use presorted 33-field input, 100,000 rows,
one/four workers and three alternating repetitions. All 72 timed jobs and 24
separate allocation censuses preserve exact output bytes/order, names, lineage,
stages and logical digests. Warm, uncontrolled WSL storage is used; physical
SSD throughput and cache state are unmeasured. This is accounting work with
no throughput improvement claim.

| Pipeline | One-worker median seconds, before → after | Change, one / four workers |
| --- | --- | --- |
| `streaming_pipeline` | 0.4724 → 0.4791 | +1.4% / +0.4% |
| `streaming_pipeline_sort` | 0.5021 → 0.5106 | +1.7% / +1.4% |
| `spill` | 0.2341 → 0.2354 | +0.6% / +4.5% |
| `rare_wide` | 0.2399 → 0.2410 | +0.4% / -0.2% |
| `partition` | 0.2301 → 0.2289 | -0.5% / -0.1% |
| `balanced_terminal` | 0.3032 → 0.3059 | +0.9% / +1.4% |

The 1.3-million-row controls add 16 timed jobs and eight allocation censuses
with one/four workers and two alternating repetitions. Those fixtures produce
62–63 runs and one final merge, so they are scale controls rather than
hierarchical-merge evidence. Their medians change by -3.7% to -0.7%.
A further 1.4-million-row rare-wide fixture produces 67 runs and two merge
operations on both builds and workers. All eight timed jobs and four allocation
censuses preserve exact output/metadata; one/four-worker medians change by
+1.1% / -0.9%. All native suites, builds/contracts and browser measurements run
sequentially to avoid overlapping timing workloads.

Requested allocator traffic and instrumented process peaks remain nearly
unchanged. For the 1.4-million-row one-worker job, both builds request 822.37 MB
and peak at 10.71 MB of live requested allocations. These allocator measurements
are not RSS. CPU, peak RSS, reservation peaks, sort/merge counts and logical
temporary I/O/file/space diagnostics are recorded in the raw jobs. Baseline
native/allocator hashes match the preceding compact dataset key pass.

All 36 further native/baseline-WASI/candidate-WASI complete jobs preserve
exact output bytes/order and metadata. Chromium whole-job medians on
100,000 four-field rows with 128-byte payloads, three alternating repetitions:

| Pipeline | Browser seconds, before → after | Change |
| --- | --- | --- |
| `uniform32` | 1.5348 → 1.4743 | -3.9% |
| `balanced_partition` | 1.8457 → 1.9221 | +4.1% |
| `balanced_probabilistic_shuffle` | 3.9758 → 3.9257 | -1.3% |
| `balanced_probabilistic_sort` | 3.8634 → 4.0137 | +3.9% |

Browser timings include OPFS/export work and remain mixed; browser CPU,
allocations and RSS are unmeasured. The engine fixtures cover external random-key
shuffle, routed partitioning and auto/forced-sort probabilistic grouping. The
1.4-million-row hierarchical merge is native-only in this pass. This evidence
does not close the broader device/storage/scale matrix.

Artifacts: [native timing/allocation records](../../evidence-originals.md#sha256-115dba0bae008b83462e70dfc9344f4c3b384de81ebe65317705db3aa0d58c1a "Original: docs/benchmarks/merge-key-native-2026-10-16.jsonl"),
[1.3-million-row controls](../../evidence-originals.md#sha256-03d646335e545e0bc6da902aa1c31660436b6cdd00ad8fdf02254e7d0d1f7ab8 "Original: docs/benchmarks/merge-key-scale-2026-10-16.jsonl"),
[multi-level timing/allocation records](../../evidence-originals.md#sha256-27efb74ebf2f92b9dc16d9f33d32818365d37d2c6ce6147b749def9ad99557a3 "Original: docs/benchmarks/merge-key-multilevel-2026-10-16.jsonl"),
[native/WASI jobs](../../evidence-originals.md#sha256-c6135730cb6722e07ddab6b958f4f593787c0ccc52c425d5ff87475a20ddc978 "Original: docs/benchmarks/merge-key-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-74e1fbc95c45eecf80974acfd7bb85dd15ce4e9b552a87176c0e5766654444d6 "Original: docs/benchmarks/merge-key-browser-2026-10-16.json"),
[summary](../../evidence-originals.md#sha256-1c429cfd78b1d2352a39663a60940bbeaa37c8050cf948c719c36c678065a93f "Original: docs/benchmarks/merge-key-summary-2026-10-16.json").

Reproduce after preserving baseline native/allocator/WASM binaries and building
the candidate native release/allocator and browser release:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases streaming_pipeline streaming_pipeline_sort spill rare_wide partition balanced_terminal
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 1300000 --workers 1 4 --repeats 2 --cases spill rare_wide
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 1400000 --workers 1 4 --repeats 2 --cases rare_wide
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  uniform32,balanced_partition,balanced_probabilistic_shuffle,balanced_probabilistic_sort \
  128 BEFORE.wasm
```
