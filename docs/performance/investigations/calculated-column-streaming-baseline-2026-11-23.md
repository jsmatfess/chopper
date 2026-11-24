## Calculated-column streaming baseline (2026-11-23)

[Issue #54](https://github.com/jsmatfess/chopper/issues/54) establishes a full-Run
baseline for the prepared expression evaluator. Measure four deterministic
jobs on one input at 256 MiB and 32 MiB. Stop after three runs per case and
budget, verified output parity, and evidence that the low-budget sort spilled.
The experiment measures one implementation at two resource settings.

The [disk-backed rows](../../benchmarks/calculated-columns-native-2026-11-23.jsonl)
come from a default-feature x86-64 Linux build in WSL2, using its ext4 filesystem.
The first matrix used [tmpfs](../../benchmarks/calculated-columns-tmpfs-2026-11-23.jsonl),
which exercises external sort control flow with memory-backed files. Keep it
separate from the ext4 matrix. Neither matrix measures physical SSD I/O or
establishes native Windows or hosted throughput.

The [harness](../../../scripts/benchmark-calculated-columns.py) builds pinned
commit `83e638c018b0bf18727600a74e82dc9744dfbcb9` with Rust 1.99.1 using the
locked workspace and default features. Its context records the tree, executable
and harness hashes. The input contains 18,000 rows and 22,648,815 bytes. All
jobs use one worker, explicit sort grouping, a 1 MiB working record limit,
and an 8 MiB serialized CSV cap. Fitting and spilling budgets alternate order
between repetitions. The input is generated once per matrix and remains in
the operating system's normal cache. Run timing starts at CLI process launch and
ends after native publication and stdout completion.

| Formula workload | 256 MiB wall ms, median [range] | 32 MiB wall ms, median [range] | 256 / 32 MiB calculation traversal median ms |
| --- | ---: | ---: | ---: |
| Text normalization | 134.9 [134.1–140.1] | 139.2 [136.3–140.9] | 17.7 / 17.5 |
| Numeric calculation and category | 158.3 [153.1–163.2] | 158.2 [158.1–159.5] | 38.1 / 37.8 |
| Regex capture replacement | 141.3 [139.6–142.4] | 143.7 [142.9–144.0] | 25.2 / 24.8 |
| Timestamp parsing and local day | 167.7 [163.8–467.6] | 165.2 [164.7–166.9] | 42.9 / 43.1 |

Each cell has three runs. The 467.6 ms observation remains in the timestamp
range and raw data. No cause was established for it. All ext4 jobs at 32 MiB
produced four sort runs and merged. Jobs at 256 MiB retained the sort in memory.
The calculation stages read and write retained rows at both budgets. Traversal
time includes their I/O and evaluation. Formula preparation was below 0.1 ms
in every ext4 run, separately recorded in the timing map. Peak logical
temporary bytes were approximately 48–50 MB in the fitting cells and
64–65 MB in the spilling cells. Peak admitted workspace was approximately
27–28 MB and 8.7 MB respectively. These counters have their own scopes.

Each matched job conserved rows and verified identical ordered CSV hashes,
lineage, chunk names, and byte counts across budgets and repetitions. The
native execution observation test verifies one completed CSV intake scan in a
calculated pipeline. Later operations traverse retained rows; formula
preparation and strategy selection add no source scan.

This small warm-cache matrix supports keeping the prepared streaming evaluator
as the baseline. A future proposal to cache expression results or evaluate batches
needs a workload where expression evaluation, rather than stage I/O, is shown to
dominate. Any materialization or fusion proposal needs a complete-job comparison
and parity across calculation positions and error paths.

To reproduce on a clean checkout of the recorded commit, select a work directory
on the intended filesystem and use a fresh output file.

```sh
python3 scripts/benchmark-calculated-columns.py \
  --work-dir /path/to/work-directory \
  --output /path/to/new-measurements.jsonl
```
