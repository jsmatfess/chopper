## Calculated columns followed by Partition (2026-11-24)

The [previous calculation investigation](calculated-column-evaluation-and-terminal-publication-2026-11-24.md)
showed larger gains from removing an output copy than from optimizing
individual formulas. This follow-up asks whether a Linux Run can feed calculated
rows into the existing Partition grouping path without an intermediate Dataset.
[Issue #54](https://github.com/jsmatfess/chopper/issues/54) identifies the original
calculated-column baseline.

### Implementation and correctness

An unobserved Linux Run can use the new path when a single Partition consumes a
calculated column, input has one root group and is at least 128 MiB on disk, and
output is plain. Auto still chooses between the existing routing and sorting
paths. The packed row, rendered tuple key, original ordinal, and capped final
snapshot preserve output order, contents, and lineage. Source intake and
schema binding finish before the attempt. Explicit preparation and observed
Runs retain their separate stage boundaries. See the [rewrite contract](../../pipeline-rewrites.md).

On a fused error, the temporary sort state and output snapshot are dropped
before replaying the staged path from the validated retained input.
Cancellation stops without replay. Replay preserves error order when an
oversized partition key on the first row would otherwise mask a formula failure
on the last row. The paired CLI failure checks covered both of those errors,
output count denial, and complete cleanup. The native test compares
an explicit snapshot with Run and cancels after sorting but before output
can be published.

### Complete-job measurements

The baseline includes the previous retained calculated-column optimizations.
Alternating pairs used one pinned CPU and one Chopper worker on the same x86-64
WSL2 ext4 host with its ordinary filesystem cache. Every Run completed publication
before its clock stopped. The large jobs used 256 MiB and an 8 MiB CSV byte cap.
The fitting pilot used 2,048 MiB. Formulas, fixture hashes, raw positions, and
pinned binaries are in the [measurements](../../benchmarks/calculated-partition-summary-2026-11-24.json).
The exact runners, binaries, source patch and private raw evidence remain
together in local experiment custody.

Positive deltas are savings. Each row reports a paired median with the observed
range. Tracked temporary reads and writes describe engine traffic, separately
from peak tracked storage, RSS, and physical disk I/O.

| Workload / build | Rows | Pairs | Wall saved, seconds [range] | Process CPU saved, seconds | Tracked GB removed from each of reads and writes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fitting timestamp, explicit Sort pilot | 350,000 | 4 | 0.172 [0.159, 0.222] | 0.18 | 0.209 |
| Spilling regex, explicit Sort pilot | 2,000,000 | 4 | 4.064 [2.398, 5.108] | 2.55 | 2.712 |
| Spilling timestamp, explicit Sort pilot | 8,000,000 | 4 | 4.446 [3.500, 5.668] | 4.37 | 3.430 |
| Routed timestamp, retained build | 2,000,000 | 4 | 3.100 [1.597, 6.619] | 2.05 | 2.796 |
| Spilling regex, retained build | 2,000,000 | 4 | 2.564 [0.954, 4.193] | 1.59 | 2.712 |
| Formula-free routed, retained build | 2,000,000 | 4 | 0.951 [0.214, 1.638] | 0.11 | 0 |
| Formula-free spilling, retained build | 2,000,000 | 4 | -0.038 [-0.387, 1.741] | -0.01 | 0 |
| Formula-free direct, retained build | 2,000,000 | 4 | -1.241 [-1.416, -0.408] | -0.035 | 0 |
| Formula-free direct, retained build repeat | 2,000,000 | 8 | 0.991 [-1.737, 1.403] | -0.005 | 0 |
| Formula-free direct, identical-binary control | 2,000,000 | 6 | -0.535 [-1.207, 1.739] | 0.025 | 0 |
| Existing terminal regex export, retained build | 2,000,000 | 4 | 0.581 [-0.658, 1.382] | -0.13 | 0 |

The retained routed job used 122 MB less peak tracked temporary storage.
The retained spilling job used 38 MB less. The 8-million-row Sort pilot
used 488 MB less. These peak reductions are smaller than per-pass traffic
reductions because the source spool and grouping state overlap during fusion.

### Retention

The first Auto-capable build improved eligible jobs, but the existing terminal
export showed a wall-time loss and formula-free Sort showed a small repeated
CPU cost. The retained revision keeps the fused attempt out of line and inlines
the shared row evaluator back into the staged calculation loop. It repeated
the data movement and elapsed-time gains. The existing terminal export used
0.13 seconds more process CPU at the paired median, with lower median elapsed
time and identical tracked traffic and output.

Formula-free jobs do no new per-row work. Their ordered output, stage counts,
spill and routing statistics, peak tracked temporary bytes, and temporary
read and write counters matched. The direct control's first elapsed loss
reversed in the eight-pair repeat, and identical-binary elapsed spread showed
similar swings. Direct process CPU rounded to effectively even. The spilling
control was within 0.04 seconds elapsed and 0.01 seconds CPU at the paired
median. The evidence supports the guarded Linux default in the tested regime.
Native Windows and browser throughput were outside the timing panel.
