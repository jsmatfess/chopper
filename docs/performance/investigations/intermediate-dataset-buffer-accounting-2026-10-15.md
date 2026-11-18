## Intermediate dataset buffer accounting, 2026-10-15

This WSL-compatible follow-up charges fixed intermediate dataset I/O buffers to
the same half-budget workspace ledger as sorting/routing. Each dataset data,
catalog or frame-scanning reader reserves **64 KiB** before opening/allocating
its buffered reader. The reservation remains live until the iterator is dropped,
including after EOF or a decode error. Each dataset writer reserves its **64 KiB
data plus 8 KiB catalog** buffers before either allocation and releases them
after finishing or dropping. The dataset keeps the ledger identity so later
readers share the same ceiling; idle datasets do not reserve read buffers.
Merge readers retain their existing separate accounting, with no duplicate
dataset charge. Output values/order, seed domains and sorting defaults are
unchanged. The UI and README now describe the expanded ledger accurately.

The ledger remains incomplete: parser/decoded-input capacities, conversion
overlap, retained run/catalog metadata, final-output/codec allocations, runtime
stacks and allocator overhead are not fully charged. This neither completes
per-group working-set selection nor makes `memory_mb` a whole-process RSS cap.
It also does not coordinate simultaneous prepared jobs or add host-aware sizing.

New tests cover writer capacity one byte below/at/above its buffer sum, overlapping
reader capacity one byte below/at/above two full buffers, exhausted-but-retained
catalog readers, denial without extra files/reservations, frame-scanner reuse and
release after corrupted input or cancellation. Existing shared-pressure spill,
wide-row, routing fallback, seeded fixtures, strict caps and publication cleanup
tests remain passing. Final validation: **108 workspace tests**, **33 combined
experimental-feature library tests**, formatting, all-feature Clippy, TypeScript/
UI build, native/WASI release builds and all **23 Chromium/WASI contracts** pass.
[Browser record](../../evidence-originals.md#sha256-643e72586d14c5642856ac2a0168cb1c252aa04d3187c2eb7f5a165e00997d2f "Original: docs/benchmarks/dataset-budget-browser-2026-10-15.json").

The [standard native comparison](../../evidence-originals.md#sha256-aee49d7e242d506a305fed2ecb81fe8e74e0421c367f80ad0f1a276e90bbcf8d "Original: docs/benchmarks/dataset-budget-native-2026-10-15.jsonl")
contains 72 alternating timed jobs and 24 allocation censuses, 300,000 rows/33
fields, three repetitions and one/four workers, against the preceding decode-reuse
pass. All exact output/metadata fingerprints match. One-worker allocation profiles
are identical on all six cases; four-worker censuses differ by up to three
allocations/6,216 requested bytes, with unchanged peak live requested bytes.
Run/merge counts, logical temporary traffic and space peaks are unchanged. The larger
reservation peak records existing buffers rather than newly allocated memory.
RSS, CPU and detailed variability remain in the raw records. Timings vary in
both directions; there is no throughput or RSS reduction claim for accounting.
Builds, tests and browser work finished before timing; these are warm,
uncontrolled WSL filesystem measurements, not physical SSD I/O calibration.

| Complete job | Workers | Median seconds before → after | Observed seconds before / after | Peak reservation MiB before → after |
| --- | ---: | ---: | --- | ---: |
| resident random-key | 1 | 0.569 → 0.581 | 0.563–0.587 / 0.550–0.607 | 131.395 → 131.465 |
| resident random-key | 4 | 0.551 → 0.551 | 0.550–0.659 / 0.545–0.552 | 131.395 → 131.465 |
| resident Fisher–Yates | 1 | 0.585 → 0.592 | 0.577–0.610 / 0.579–0.598 | 131.394 → 131.465 |
| resident Fisher–Yates | 4 | 0.575 → 0.592 | 0.572–0.577 / 0.591–0.612 | 131.394 → 131.465 |
| uniform spill pipeline | 1 | 0.978 → 1.001 | 0.974–0.981 / 0.973–1.009 | 8.062 → 8.125 |
| uniform spill pipeline | 4 | 0.967 → 0.965 | 0.959–1.001 / 0.956–0.978 | 8.062 → 8.125 |
| partition, spill | 1 | 0.646 → 0.625 | 0.632–0.652 / 0.620–0.626 | 8.635 → 8.705 |
| partition, spill | 4 | 0.634 → 0.632 | 0.622–0.635 / 0.630–0.634 | 8.635 → 8.705 |
| streaming, forced sorting | 1 | 1.614 → 1.576 | 1.568–1.629 / 1.573–1.590 | 8.062 → 8.258 |
| streaming, forced sorting | 4 | 1.592 → 1.631 | 1.578–1.593 / 1.614–1.654 | 8.062 → 8.258 |
| streaming, rare wide | 1 | 1.484 → 1.486 | 1.463–1.499 / 1.479–1.492 | 8.062 → 8.125 |
| streaming, rare wide | 4 | 1.488 → 1.536 | 1.480–1.503 / 1.512–1.537 | 8.062 → 8.125 |

The [larger complete-job comparison](../../evidence-originals.md#sha256-0233533269eea203098577b56bf07e148668ada5e7802d8ec0c82cb696291d06 "Original: docs/benchmarks/dataset-budget-multilevel-2026-10-15.jsonl")
adds 24 alternating timed jobs and eight allocation censuses with 1.3 million
33-field rows at 32 MiB, global random-key shuffle and global shuffle followed
by four balanced outputs, one/four workers and three repetitions. Every job uses
**65 initial runs, two merge operations and 66 merge inputs**, crossing the
64-reader fan-in boundary. Exact bytes/order, output names/lineage, stages and
logical digests match before/after. Temporary I/O/space and run counts are unchanged.
Three allocation profiles are identical; the four-worker global census records
three fewer allocations/6,216 fewer requested bytes out of 3.89 million allocations,
with unchanged peak live requested bytes. The ledger records the additional live dataset buffers.
This is native multi-level acceptance on warm WSL storage, not device calibration
or a browser multi-level rerun.

| Larger job | Workers | Median seconds before → after | Observed seconds before / after |
| --- | ---: | ---: | --- |
| global shuffle | 1 | 3.587 → 3.609 | 3.561–3.710 / 3.598–3.713 |
| global shuffle | 4 | 3.700 → 3.800 | 3.692–3.801 / 3.774–3.840 |
| shuffle + balanced | 1 | 3.773 → 3.697 | 3.768–3.776 / 3.654–3.739 |
| shuffle + balanced | 4 | 3.759 → 3.734 | 3.721–3.762 / 3.655–3.749 |

Reproduce with baseline binaries saved before adding dataset reservations:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-dataset-budget-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-dataset-budget-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases resident fisher uniform_pipeline_spill partition_spill \
    streaming_pipeline_sort streaming_pipeline_wide
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-dataset-budget-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-dataset-budget-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 1300000 --repeats 3 --workers 1 4 --cases spill fused_balanced_spill
```
