## Sort-run catalog accounting, 2026-10-15

This WSL-compatible accounting follow-up reserves the actual descriptor-array
capacity of sort levels, retained logical runs, each run's file list, compaction
batches and final merge batches. Growth reserves both old/new arrays before
allocation/movement. The charge follows the allocation into routed fallback,
merge readers and iterators, including exhausted iterators until drop. Denial
leaves existing catalog contents/capacity unchanged; unwinding releases files and
reservations. Seeded algorithms, comparison order and defaults are unchanged.
This covers catalog arrays, not all metadata: tempfile pathname allocations,
parser/decoded-input capacity, conversion overlap, final-output/codec allocations,
allocator and runtime sorting overhead still prevent a complete live-memory/RSS
cap. The opt-in distribution candidate uses charged final merge catalogs too;
its separate recursive pending-bucket metadata is not fully accounted.

New tests exercise descriptor growth and old/new overlap one byte below/at/above
capacity, drained catalogs and exhausted iterator lifetimes, merge reader/catalog
allocation overlap at exact boundaries, shared pressure and cancellation cleanup.
Validation: **111 workspace tests**, **36 combined experimental-feature library
tests**, all-feature Clippy, formatting, native/WASI release builds and all
**23 Chromium/WASI contracts** pass. [Browser contract record](../../evidence-originals.md#sha256-c41b665b911ab2b943ab7ab8df6371d572379d768474d71a4d5f06ba1b8a0e99 "Original: docs/benchmarks/run-catalog-browser-2026-10-15.json").

The [native comparison](../../evidence-originals.md#sha256-9bb700ecbae7247e67597af25bd6f6acbd80ad5a9e25f7b37df6590177e259ea "Original: docs/benchmarks/run-catalog-native-2026-10-15.jsonl") records
72 alternating timed jobs and 24 allocation censuses against the preceding
fixed-dataset-buffer pass: 300,000 rows, 33 fields, three repetitions and one/four
workers. All CSV bytes/order, filenames/lineage, stages and logical digests match.
Logical temporary traffic, sort runs, merge counts and temporary-space peaks are
unchanged. One-worker resident allocation profiles are identical. External
one-worker jobs add 4–28 allocations and 1,008–3,248 requested bytes for the
charged arrays and explicit growth. The larger reservation peak records existing
metadata; this is not a throughput or RSS reduction claim. CPU/RSS, ranges and
full diagnostics remain in the raw records. These are warm, uncontrolled WSL
filesystem measurements, with builds/tests finished before timing; they do not
measure physical SSD I/O.

| Complete job | Workers | Median seconds before → after |
| --- | ---: | ---: |
| resident random-key | 1 / 4 | 0.572 → 0.583 / 0.566 → 0.561 |
| resident Fisher–Yates | 1 / 4 | 0.574 → 0.589 / 0.587 → 0.579 |
| uniform spill pipeline | 1 / 4 | 0.954 → 0.966 / 0.969 → 0.971 |
| partition, spill | 1 / 4 | 0.620 → 0.634 / 0.615 → 0.626 |
| streaming, forced sorting | 1 / 4 | 1.598 → 1.623 / 1.647 → 1.574 |
| streaming, rare wide | 1 / 4 | 1.523 → 1.536 / 1.505 → 1.494 |

The [multi-level comparison](../../evidence-originals.md#sha256-637c7a6e2a7dcf25c521f6ef1be909be777a41d9560b0380ca68ffd20ba20729 "Original: docs/benchmarks/run-catalog-multilevel-2026-10-15.jsonl")
adds 24 alternating timed jobs and eight allocation censuses: 1.3 million rows,
33 fields, 32 MiB, global shuffle and shuffle followed by four balanced outputs,
one/four workers, three repetitions. Every job uses **65 initial runs, two merge
operations and 66 merge inputs**, preserving exact output/metadata and temporary
I/O/space. One-worker profiles add eight allocations and 4,104 requested bytes.
Global median seconds before → after: **3.883 → 3.766** (one worker), **3.883 →
4.023** (four); shuffle-plus-balanced: **3.869 → 3.894**, **3.859 → 3.976**.
This is additional native multi-level evidence, not target-device calibration.

The [native/browser A/B replay](../../evidence-originals.md#sha256-b31c615e7a129552b2a974e521119a2bfe468f72753721956ae5f7ad561e2dad "Original: docs/benchmarks/run-catalog-engines-2026-10-15.jsonl")
adds 27 timed jobs: 100,000 rows with 256-byte payloads, three alternating
repetitions, global external shuffle, partition and balanced/probabilistic routing
forced through sorting. All exact bytes/order, names/lineage, stage metadata and
logical digests match the saved previous WASM and native candidate. Browser median
seconds before → after are **2.364 → 2.314**, **1.242 → 1.175** and **6.048 →
6.074**, respectively. Browser OPFS operations are recorded, not physical I/O;
there is no general browser speedup claim.

Reproduce using the saved before/after builds:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-run-catalog-before/chopper \
  --after /tmp/chopper-run-catalog-after/chopper \
  --before-allocator /tmp/chopper-run-catalog-before/allocation-profile \
  --after-allocator /tmp/chopper-run-catalog-after/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases resident fisher uniform_pipeline_spill partition_spill \
    streaming_pipeline_sort streaming_pipeline_wide
# Same arguments with --rows 1300000 --cases spill fused_balanced_spill
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-run-catalog-after/chopper \
  100000 3 uniform32,partition,balanced_probabilistic_sort 256 \
  /tmp/chopper-run-catalog-before/engine.wasm
```
