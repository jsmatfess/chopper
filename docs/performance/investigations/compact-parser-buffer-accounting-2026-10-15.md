## Compact parser buffer accounting (2026-10-15)

The next locally actionable accounting step now reserves compact CSV ingestion's
scratch and framed-record capacity before allocation, including old/new growth
overlap. Growth uses a separate allocation, charges its actual capacity, and rolls
back the provisional charge on failure. The fixed 64 KiB UTF-8 reader and inline
transcoder footprint are charged before construction. Parser charges remain live
through consumer handoff, conservatively overlapping the consumer's retained-row
charge, then retain only scratch and returned reusable storage. Ingestion drops
these buffers before final sorting/merging. Unchanged reservation sizes avoid an
atomic update.

If parser growth cannot reserve space, a leading sorter spills retained rows and
retries without changing their keys or the incoming CSV state. An explicit
resident Fisher–Yates choice still fails cleanly if its live working set cannot
fit. No default or seeded algorithm changes.

Exact growth-capacity edges (below/at/above), shared pressure, successful spill and
retry, malformed CSV, cancellation and release are covered. A complete late-wide
fixture with a 2,050,000-byte field preserves exact output across 32/128 MiB budgets
and one/four workers. Final validation: **122 workspace tests, 43 combined-feature
library tests and 24 Chromium/WASI contracts pass**, as do formatting, all-feature
Clippy and native/WASI release builds.

The final native comparison alternates baseline/candidate complete jobs across
six 100,000-row, 33-column fixtures, one/four workers and three repetitions:
**72 timed jobs and 24 separate allocation censuses**, all with exact output bytes,
order, names, lineage, stage statistics and logical-digest parity. Timed processes
record CPU, RSS, reservations and logical temporary I/O. Complete-job median
seconds below are **baseline → candidate**:

| Job | One worker | Four workers |
| --- | ---: | ---: |
| resident | 0.194 → 0.200 | 0.187 → 0.193 |
| fisher | 0.191 → 0.195 | 0.187 → 0.198 |
| spill | 0.231 → 0.236 | 0.231 → 0.236 |
| rare_wide | 0.239 → 0.246 | 0.240 → 0.253 |
| partition_shuffle | 0.273 → 0.282 | 0.264 → 0.270 |
| uniform_pipeline_spill | 0.327 → 0.329 | 0.330 → 0.339 |

The measured cost is roughly **0.4–5.8%** on these fixtures. This is a memory
accounting improvement with a small timing cost; it is not a throughput gain.
Requested allocation traffic is effectively unchanged (−31 to +63 bytes per
preparation on these censuses); explicit growth moves a few reallocations into
allocations. The one-worker rare-wide peak reservation rises from 8,528,475 to
10,701,048 bytes as previously uncharged parser storage becomes visible, while
its allocator census peak is unchanged at 10,698,016 requested live bytes. Ledger
and allocator peaks measure different scopes and need not coincide.

A separate native/Chromium-WASI replay contains **16 verified complete jobs**:
100,000 rows, four fields, 256-byte payloads, global external random-key,
resident Fisher–Yates, four-group random-key and partition/shuffle workloads,
two alternating engine repetitions. Output and metadata parity pass. These
replays compare runtimes on the final build; they establish no browser A/B
speedup. The separate 1.3-million-row native check records multi-level external
jobs and parity across one/four workers: 65/66 sort runs, two merge operations
and 66 total merge inputs per job. It has one sample per variant and is a correctness/scale
check, not a variability estimate.

Raw artifacts:

- [Final native timings and allocation censuses](../../evidence-originals.md#sha256-d0c0c8f58f1d32fa6f8cb7129f5e5038865890e31603702e08c5443d9284b422 "Original: docs/benchmarks/parser-budget-native-2026-10-15.jsonl").
- [Native/WASI complete-job replays](../../evidence-originals.md#sha256-d259833b43e6eb6994d325c5c4c8491ee60f6e5ad264e3e168c099df385ce448 "Original: docs/benchmarks/parser-budget-engines-2026-10-15.jsonl").
- [Native multi-level checks](../../evidence-originals.md#sha256-2064a9287ccffc0623b9dea5f7e9beef9284b4b589d88f71df6236627c16c575 "Original: docs/benchmarks/parser-budget-multilevel-2026-10-15.jsonl").
- [Initial exploratory native pass](../../evidence-originals.md#sha256-832cd926a3b4827a5edf72e53741ca520cd70cebbcfeee1d4dcc378305af73e4 "Original: docs/benchmarks/parser-budget-initial-native-2026-10-15.jsonl"). Its early samples overlapped build/test activity; use the final pass for timing comparisons.
- [Derived summary, checks and artifact hashes](../../evidence-originals.md#sha256-74f686f9f0415f745f431b06a60b757c433de30fb4c485dc9e7cd75a00208f7b "Original: docs/benchmarks/parser-budget-summary-2026-10-15.json").

This remains warm, uncontrolled WSL filesystem/OPFS evidence on the recorded
Ryzen host. Logical temporary traffic does not establish physical SSD I/O.
Owned plain parsing, retained headers/statistics, decoded intermediate-input
capacity, remaining conversion/shrink overlap, codecs, file/runtime metadata,
thread stacks and sorting overhead still prevent treating the ledger as a
complete live-memory or RSS cap. Fixed input buffers are charged for plain jobs,
but their owned fields/scratch growth are not fully accounted. Intermediate
decoders retain their existing allowances; this step does not expand them.
Controlled SSD/cache, other-device and broader external-scale acceptance remain
open, as requested for this WSL pass.

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-parser-budget/before --after /tmp/chopper-parser-budget/after \
  --before-allocator /tmp/chopper-parser-budget/before-allocator \
  --after-allocator /tmp/chopper-parser-budget/after-allocator \
  --workers 1 4 --repeats 3 --rows 100000 \
  --cases resident fisher spill rare_wide partition_shuffle uniform_pipeline_spill
# Multi-level check: omit allocator arguments; use --rows 1300000 --repeats 1
# and --cases spill uniform_pipeline_spill.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-parser-budget/after \
  100000 2 uniform32,fisher256,grouped_uniform256,partition_shuffle 256
```
