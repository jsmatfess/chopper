## Retained temporary-path accounting, 2026-10-15

Every `DiskFile` now reserves its retained `TempPath` bytes against the shared
workspace ledger **before file creation**. The explicit tempfile prefix/random
length preserves the dependency's previous naming convention and makes the
required path length known in advance. A successfully created file checks that
length. Its reservation follows ownership through datasets, run catalogs,
composite-run readers, merges and prepared output snapshots; the last owner
releases the path charge. Run catalogs already charge descriptor capacity, which
now includes the per-file reservation guard. A denied reservation creates no
file, and creation errors/cancellation release the charge without leaking files
or temporary-space usage.

`temporary_path_reserved_bytes` distinguishes live file paths from algorithm
buffers in diagnostics. Preparation retains the two output-plan files, so
`workspace_reserved_bytes` is now nonzero until those snapshots are dropped.
Tests and development benchmarks check that the remaining charge equals the
live path charge, rather than treating a prepared snapshot's path as a leak.
Native execution tests additionally retain a context and verify both counters
return to zero after execution consumes the prepared snapshot.

New capacity tests cover one byte below/at/above the shared ceiling, another
reservation competing with file creation, long UTF-8 parent paths, shared `Arc`
ownership, failed file creation, cancellation and actual directory cleanup.
Existing dataset-buffer and merge-catalog boundary tests now include overlapping
path lifetimes, including EOF and cancellation. This is **retained path
accounting**, not a complete file/runtime memory census: tempfile creation
scratch, job-directory paths, OS handles, parser/decoded-input capacity,
conversion overlap, allocator bookkeeping and runtime stacks remain outside
these charges. The workspace ledger remains a partial working-set limit, not
an RSS cap.

The [native A/B comparison](../../evidence-originals.md#sha256-93f80b7936e34f5525d247fda4e5ddce422260f2bbdf08ee0d21138dc1c8dc12 "Original: docs/benchmarks/path-budget-native-2026-10-15.jsonl")
contains 72 alternating timed complete jobs and 24 allocation censuses: 300,000
rows, 33 fields, one/four workers, three repetitions, resident random-key and
Fisher–Yates, intermediate external shuffle, partition routing, forced streaming
sorting and a rare-wide streaming pipeline. Every exact output byte/order,
name/lineage, stage and logical digest matches. Logical temporary I/O and space
are unchanged. Timings are mixed; this is a resource-accounting improvement,
with no demonstrated throughput gain.

| Complete job | Workers | Median seconds before → after |
| --- | ---: | ---: |
| resident random-key | 1 / 4 | 0.542 → 0.548 / 0.515 → 0.510 |
| resident Fisher–Yates | 1 / 4 | 0.532 → 0.566 / 0.540 → 0.534 |
| intermediate external shuffle | 1 / 4 | 0.905 → 0.903 / 0.914 → 0.913 |
| partition routing | 1 / 4 | 0.619 → 0.596 / 0.607 → 0.596 |
| streaming, forced sorting | 1 / 4 | 1.515 → 1.467 / 1.464 → 1.464 |
| streaming, rare wide | 1 / 4 | 1.366 → 1.327 / 1.388 → 1.335 |

The one-worker allocation censuses add three allocations per whole job and
778–2,026 requested bytes, including the extra diagnostic entry. Peak live
requested bytes increase by 8–184 bytes on these fixtures. Full ranges, CPU,
RSS, reservations and temporary counters remain in the raw records. These are
warm, uncontrolled WSL filesystem measurements, not physical SSD calibration.

Reproduce against builds saved before subsequent experiments:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-path-budget-before/chopper \
  --after /tmp/chopper-path-budget-after/chopper \
  --before-allocator /tmp/chopper-path-budget-before/allocation-profile \
  --after-allocator /tmp/chopper-path-budget-after/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases resident fisher uniform_pipeline_spill partition_spill \
    streaming_pipeline_sort streaming_pipeline_wide
# Same arguments with --rows 1300000 --cases spill fused_balanced_spill
```

The [multi-level extension](../../evidence-originals.md#sha256-7135ecf7aa238c19b8f4721e209124223134e3c5472f274be534c29dfcad2b49 "Original: docs/benchmarks/path-budget-multilevel-2026-10-15.jsonl")
adds 24 alternating timed jobs and eight allocation censuses: 1.3 million rows,
33 fields, 32 MiB, global random-key shuffle and shuffle followed by four balanced
outputs, one/four workers and three repetitions. All jobs retain **65 initial
runs, two merge operations and 66 merge inputs**, unchanged exact output/metadata,
logical temporary I/O and temporary-space peaks. Global median seconds before →
after: **3.991 → 4.185** (one worker), **3.901 → 3.932** (four); shuffle plus balanced:
**3.738 → 3.676**, **3.730 → 3.683**. This extends memory-accounting acceptance,
not target-device calibration; it includes a slower one-worker global median.

The [native/browser replay](../../evidence-originals.md#sha256-46c7bb9178d203474e2316fbc4a16b213284a1ad40579aa60b26d4f8706f76b0 "Original: docs/benchmarks/path-budget-engines-2026-10-15.jsonl")
adds 27 timed jobs on 100,000 rows with 256-byte payloads and three alternating
repetitions, preserving exact native/WASI bytes/order and metadata. Browser
median seconds before → after: external global shuffle **2.474 → 2.570**,
partition **1.201 → 1.228**, and forced streaming sorting **6.191 → 6.197**.
These narrow browser measurements also provide no throughput improvement claim;
OPFS counters are not physical device I/O.

Validation: **115 workspace tests**, **38 combined-feature library tests**,
all-feature Clippy, formatting, TypeScript, native/WASI release builds and all
**23 Chromium/WASI contracts** pass. [Browser contract record](../../evidence-originals.md#sha256-042424c7a28defa07945c41ba170d7f8b80430b63486aa5923e4dd840536e1cb "Original: docs/benchmarks/path-budget-browser-2026-10-15.json").
The workspace test runner needs local socket access for its existing HTTP tests;
its sandboxed attempt could not start those servers, and the socket-enabled
rerun passed.

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-path-budget-after/chopper \
  100000 3 uniform32,partition,balanced_probabilistic_sort 256 \
  /tmp/chopper-path-budget-before/engine.wasm
```
