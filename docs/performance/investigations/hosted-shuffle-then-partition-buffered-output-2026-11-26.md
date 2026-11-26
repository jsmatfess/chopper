## Hosted Shuffle then Partition buffered output (2026-11-26)

Extend the existing hosted buffered writer to terminal Uniform or Auto
Shuffle followed by Partition. This pipeline already sorts partition tuples
with the original parent shuffle keys and streams the final traversal. The
new writer replaces the encoded snapshot at that boundary. The sorted rows,
collision refinement, canonical tuples, column selection, stage counts and
strict CSV limits use the same producers and serializer.
[Direct execution](../../direct-execution.md) ·
[Prior Partition then Shuffle decision](guarded-hosted-partition-shuffle-publication-2026-11-26.md) ·
[Issue #100](https://github.com/jsmatfess/chopper/issues/100)

Select after input validation and final cursor creation using at least 96 MiB
of validated field bytes plus one delimiter or terminator byte per field.
The route requires plain UTF-8 output, Auto grouping, and no calculated
columns. Limit the writer to the smaller of 512 KiB or the strict byte
cap, with live headroom for that buffer, two configured records and 1 MiB.
The decision uses existing intake counters and grants. Below the size floor
or live headroom requirement, Run uses the existing snapshot writer.
Explicit Prepare and Fisher–Yates preserve their separate contracts.

### Complete Runs

A pair compares feature-free WASM engines on the same fixture through
marker readback and workspace retirement. The harness uses persistent
browser profiles with real OPFS source, workspace and destination handles
on one WSL2 ext4 host. Cache state was uncontrolled. The harness independently
reads every output record, matches the full input ID, field text and
partition key, and checks stage counts, names, manifest entries, row limits,
serialized byte limits, marker counts, and cleanup. Verification, source
import and successful-result removal run outside the clock. Warmups
where declared are excluded.

| Workload | Measured pairs | Snapshot, s | Candidate, s | Paired seconds saved |
| --- | ---: | ---: | ---: | ---: |
| 0.96 MB small control, 32 MiB | 3 | 0.259 [0.257–0.262] | 0.265 [0.258–0.269] | -0.004 [-0.010–-0.001] |
| 533.34 MB Uniform, 128 MiB | 3 | 14.576 [14.569–14.583] | 13.077 [12.978–13.196] | 1.499 [1.387–1.591] |
| 97.68 MB below the floor, 32 MiB | 2 | 6.182 [6.178–6.186] | 6.148 [6.134–6.163] | 0.034 [0.024–0.044] |
| 108.25 MB above the floor, 32 MiB | 2 | 6.783 [6.753–6.814] | 6.472 [6.471–6.474] | 0.311 [0.282–0.340] |
| 1.265 GB skewed Auto, 256 MiB selected | 3 | 33.246 [33.152–33.485] | 29.595 [29.310–29.796] | 3.652 [3.356–4.175] |
| 421.15 MB and 211 keys, installed Chrome, 64 MiB | 3 | 12.255 [12.244–12.276] | 10.864 [10.843–10.997] | 1.412 [1.247–1.412] |

All eleven eligible pairs improved. The table shows medians and observed
minima and maxima for each cohort. The screen and cutoff holdout used
bundled Chromium 156.0.8078.4. The higher-fanout holdout used installed
Chrome 149.0.7827.200 with OPFS input and destination handles.
[Screen Runs](../../benchmarks/hosted-shuffle-then-partition-screen-2026-11-26.jsonl) ·
[Cutoff and Auto holdout](../../benchmarks/hosted-shuffle-then-partition-heldout-2026-11-26.jsonl) ·
[Installed Chrome holdout](../../benchmarks/hosted-shuffle-then-partition-chrome-2026-11-26.jsonl)

The Auto memory holdout selected 256 MiB in both arms and retained a single
25-way merge. Managed temporary reads and writes each fell from
2,719,928,718 to 1,455,013,751 bytes in every Auto pair. Peak workspace
reservations stayed at 67,406,629 bytes. The storage worker's logical
workspace peak fell from about 2.720 GB to 1.455 GB. Peak workspace plus
destination bytes remained near 2.720 GB because the spill files remained
live while the destination grew. These are tracked working reservations
and logical storage, with RSS and physical device I/O outside the scope.

The unchanged controls retain the same sort path, working peak and written
bytes. The independent verifier initially required exact read-ahead totals
and then exact peak storage across same-route arms. Shuffled rows can move
chunk borders for snapshot readers and change when the last merge reader
releases its file. The revised checks bound these differences while
retaining exact CSV conservation, write totals on both decline controls
and the original timing gates. The raw Runs and the failed verification
receipts remain intact.

### Publication and admission

The resource contract checks the reverse pipeline at the exact size floor,
rejects explicit Fisher–Yates, and exercises Auto with the producer and a
peer grant live through writer selection and first-row encoding. It keeps
the snapshot at a one-byte headroom shortfall. Internal preparation keeps
its snapshot.

Both browser writers retired their private destination and workspace under
a write failure, cancellation, a marker write failure, a marker readback
mismatch, strict row-fit and file-count rejection, and a malformed final
record. Marker faults occurred after all 208 CSVs closed. The late malformed
input reached no destination opening. In the 190 MiB managed cap control,
the snapshot exhausted the budget and cleaned up before opening a
destination. The buffered route verified all 420,003 rows with a
149,442,694-byte logical OPFS workspace peak.
[Fault receipts](../../benchmarks/hosted-shuffle-then-partition-faults-2026-11-26.jsonl) ·
[Quota control](../../benchmarks/hosted-shuffle-then-partition-quota-2026-11-26.jsonl)

### Replay

Use the candidate source at `8ee26c178eee222d1a521d0f33fd6822aad7b38d` and base
`feb6721e1a5b600100d27b2209bfc1764f578943`. Build separate feature-free
WASM engines with `node scripts/build-browser.mjs` using the frozen Cargo
lockfile. The experiment used Rust 1.99.1 and Node 22.23.4. Install the
locked UI dependencies with `npm --prefix ui ci`. Each raw cohort pins the
engines, compiled workers, benchmark driver, browser, and fixture bytes.

Copy the [existing timing harness](../../benchmarks/guarded-hosted-partition-shuffle-harness-2026-11-26.mjs)
to `scratch/replay/harness.mjs`, then apply the
[Shuffle then Partition timing diff](../../benchmarks/hosted-shuffle-then-partition-harness-2026-11-26.patch)
with `patch -d scratch/replay -p1 -i ABSOLUTE_PATCH`. Run
`node scratch/replay/harness.mjs CONFIG NEW_OUTPUT_ROOT` from the repository
root. Set `browser` to the observed executable, `engines` to the two engine
paths in `baseline`, `buffered` order, and `runTimeout` to 120 seconds.
The fixture records preserve each case recipe, time gate and expected
route. Use those recipes for `cases`, omitting `kind`, `bytes`, `sha256`
and `job`. [Pair checks](../../benchmarks/hosted-shuffle-then-partition-verify-2026-11-26.py)
accept CONFIG, the new `runs.jsonl` and a new summary JSON path.
The [fault harness diff](../../benchmarks/hosted-shuffle-then-partition-fault-harness-2026-11-26.patch)
applies after the [initial fault diff](../../benchmarks/hosted-partition-shuffle-direct-harness-controls-2026-11-26.patch)
and [guarded fault diff](../../benchmarks/guarded-hosted-partition-shuffle-harness-controls-2026-11-26.patch)
on the [fault harness base](../../benchmarks/hosted-partition-shuffle-direct-harness-2026-11-26.mjs).
Pass the baseline and candidate engines, a new output directory, `faults`
or `quota`, and the bundled browser executable.
