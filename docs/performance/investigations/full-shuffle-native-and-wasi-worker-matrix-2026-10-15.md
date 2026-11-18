## Full-shuffle native and WASI worker matrix, 2026-10-15

The development harness now accepts an optional native worker list after the
baseline/candidate labels. Each selected count gets its own named variant; WASI
retains one worker. It asserts the resolved worker count as well as output parity.
Existing commands retain their historical variant names and single-worker scope.
An [18-job smoke run](../../evidence-originals.md#sha256-219d5a2b5740d77bb551d2f3a40e3bd87d766f3752c500e4eaaf35cd9ead0340 "Original: docs/benchmarks/worker-matrix-smoke-2026-10-15.jsonl") checks the
worker dispatch and global/grouped/two-shuffle cases on 1,000 rows; its startup-
dominated timings are not performance evidence.

The [larger matrix](../../evidence-originals.md#sha256-ee9f24c98ce3e233daa3bdaab7a0f2583e50a7fff35080250a6e1e0f53e83750 "Original: docs/benchmarks/full-shuffle-workers-wasi-2026-10-15.jsonl") contains
**72 verified timed complete jobs**, 48 native and 24 Chromium/WASI: 1.3 million
presorted unique IDs with duplicate payloads, 33 fields, an ordinary many-column
shape and a shape with one 1.8-million-byte field; three alternating repetitions,
32 MiB, and one/four native workers. The comparison uses the preceding build and
the retained-path-accounting build, both with the unchanged random-key v1 algorithm.
The grouped pipeline balances into four input groups before shuffling. The
multi-stage pipeline shuffles globally, balances into four groups, shuffles each
group, then balances into three outputs each (12 outputs).

Every variant/repetition has the same exact CSV byte/order fingerprint and logical
metadata within its cell. Native verification additionally checks every unique
ID and field, exact conservation and grouped input-range isolation; WASI exports
match those verified native bytes. Grouped jobs use **68 initial runs, four merge
operations and 68 merge inputs**; many-column two-shuffle jobs use **133 runs, six merges and 134 merge inputs**
on both runtimes. Rare-wide two-shuffle jobs use **134 runs / 135 inputs** on native
and **133 runs / 134 inputs** on WASI, with six merges on each. Before/after run,
merge, logical I/O, peak file and temporary-space counters match within each
runtime. Runtime-specific spill boundaries give different intermediate traffic
and space peaks across native/WASI; exact final output does not require identical
intermediate materialization.

| Row shape / complete job | Native, 1 worker | Native, 4 workers | Chromium/WASI |
| --- | ---: | ---: | ---: |
| many columns, grouped | 4.132 → 4.115 | 4.171 → 4.248 | 45.582 → 46.733 |
| many columns, two shuffles | 5.954 → 5.957 | 6.039 → 6.061 | 78.850 → 78.422 |
| rare wide, grouped | 4.089 → 4.046 | 4.054 → 4.069 | 45.690 → 46.080 |
| rare wide, two shuffles | 5.979 → 5.903 | 6.018 → 5.998 | 78.108 → 78.345 |

Entries are median complete-job seconds before → after, not sort-loop timings.
Full ranges, native CPU/RSS/filesystem block counters, reservations, temporary
space and browser OPFS operations are in the raw records. The accounting change
shows no general throughput improvement. This extends repeated multi-level,
multiple-worker, rare-wide and per-group acceptance on warm WSL/OPFS storage.
It does not complete the full-shuffle matrix: target SSD/cache calibration,
broader devices/storage/scale, browser CPU/allocation/RSS measurements and external
statistical diagnostics remain open. Builds, tests and other benchmarks were kept
out of these timed runs.

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs \
  /tmp/chopper-path-budget-before/chopper /tmp/chopper-path-budget-after/chopper \
  /tmp/chopper-path-budget-before/engine.wasm /tmp/chopper-path-budget-after/engine.wasm \
  1300000 3 columns,rare_wide grouped,multistage before,after 1,4
```
