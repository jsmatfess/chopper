## Guarded hosted partition shuffle publication (2026-11-26)

[Issue #100](https://github.com/jsmatfess/chopper/issues/100) ·
[Initial direct-output experiments](hosted-partition-shuffle-direct-output-2026-11-26.md) ·
[Direct execution contracts](../../direct-execution.md)

### Decision and Auto rule

Use the buffered writer for the qualified hosted Partition then Uniform or
Auto shuffle route. The fused sort and the existing Auto memory targets
control data processing. The output decision runs once, after input
validation and preparation of the final traversal, while the producer's
reservations are live. It requires Auto grouping, no formulas and plain
UTF-8 output.

The lower bound for serialized CSV is the validated field payload plus one
byte per field for delimiters and record terminators. All of these facts
already exist at that boundary. Quotations, BOMs and headers can add bytes.
A lower bound of 96 MiB selects the size region. It was set before the
held-out tests and keeps the earlier 100 MiB managed-quota success in scope.
The neighbourhood controls confirm how the selector behaves. Their results
supply evidence near the chosen cutoff, with room for other workload
crossovers.

Cap the single active destination buffer at 512 KiB or the strict byte
cap. Require that buffer, two configured records and 1 MiB of additional
headroom at the start of emission. The guard is a bounded readiness check.
Live allocations still admit independently. A decline chooses the snapshot
writer before destination emission. Direct failures retire unpublished
output under the existing protocol. Internal Prepare retains its encoded
snapshot. The reported physical plan describes the writer that ran.

A switch at Run dispatch would skip the existing hosted Auto sort sizing.
The earlier route-only control resolved 256 MiB where the ordinary route
chose 1,024 MiB and introduced three spills. The delivered code keeps the
memory and producer decision in its original place, even when a matching
Analyze result advises it. The later output choice uses validated current
input, without a second scan or required Analyze.

### Complete Run time

The screening build pairs the earlier 512 KiB writer with Auto parity
against the snapshot engine. The guarded build uses the production
eligibility test, capped buffer and unchanged upstream memory plan. All
rows in the table come from matched same-tier, same-sort runs through a
verified marker and worker retirement. Columns report elapsed medians and
the median and observed range of paired seconds saved. Wakeups, file
selection and independent verification occur outside the Run timer.

| Cohort | Input and working setting | Snapshot, s | Writer, s | Paired seconds saved [min–max] |
| --- | --- | ---: | ---: | ---: |
| Buffer screen | 535.7 MB, 128 MiB, 27 spill runs | 17.174 | 15.751 | 1.468 [1.305–1.496], n=3 |
| Buffer screen | 1.251 GB skewed, 256 MiB, 22 spill runs | 30.949 | 27.238 | 3.611 [3.586–3.820], n=3 |
| Buffer screen | 279.4 MB, Auto chose 2,048 MiB, resident | 6.978 | 6.291 | 0.681 [0.613–0.711], n=3 |
| Guarded | 97.6 MB, 32 MiB, below the size floor | 3.405 | 3.421 | −0.015 [−0.031–+0.001], n=2 |
| Guarded | 103.1 MB, 32 MiB, above the size floor | 3.677 | 3.356 | 0.321 [0.272–0.370], n=2 |
| Guarded | 157.0 MB, 1,536 keys and 64 KiB cap, 128 MiB | 16.270 | 15.464 | 0.806 [0.794–0.817], n=2 |
| Guarded | 106.0 MB, 1.76 MB last row, 32 MiB | 3.654 | 3.313 | 0.341 [0.332–0.350], n=2 |
| Guarded | 7.46 MB gzip source, 260.8 MB output, 256 MiB Auto | 6.881 | 6.074 | 0.807 [0.736–0.878], n=2 |
| Guarded | 3.253 GB skewed, 384 MiB, 38 spill runs | 79.795 | 70.031 | 9.764 [9.514–11.229], n=3 |
| Guarded, desktop Chrome | 563.1 MB uncapped, 128 MiB, 22 spill runs | 18.745 | 17.091 | 1.619 [1.487–1.683], n=3 |

The lower neighbour kept the snapshot in all arms with identical sort and
storage counters. The upper neighbour switched at the same 32 MiB working
setting. The gzip input picked direct from its validated decoded record
payload despite the small archive size. Both arms kept the same Auto
memory setting and seven spills there. In the short-output case both arms
made 3,144 destination write calls. The guarded writer still saved time by
avoiding the encoded payload passes.

The desktop holdout selected a real source file and ext4 destination folder
through the GTK pickers in Linux Chrome 149.0.7827.200. The test observed the
read/write grant and verified all 787,003 rows across 32 destination files
from disk. Both arms used one 22-way merge and peaked at 33.86 MB of tracked
working reservations. Managed temporary reads and writes each fell from
1.211 GB to 0.648 GB. Destination write calls fell from 2,172 to 1,088.

### Resource and correctness boundaries

The largest job completed one 38-way merge in each arm. Managed temporary
reads and writes each fell from 6.782 GB to 3.529 GB. The peak managed
temporary footprint fell from 6.781 GB to 3.529 GB. Destination bridge
writes fell from 12,427 to 6,300 calls. The peak reservation was 101.0 MB
in both arms, and the combined logical peak stayed near 6.78 GB.

On the 1.251 GB skewed screen, managed temporary writes went from 2.614 GB
to 1.363 GB and reads from 2.617 GB to 1.363 GB. The two paths had the same
peak working reservations, about 67.48 MB. Combined logical storage
remained about 2.61 GB because the direct writer's destination files grow
while the spill files remain live. For the resident Auto screen the
combined peak fell from 558.8 MB to 279.4 MB. The buffered writer held about
0.26 MB more tracked working memory there. The storage and memory figures
come from the engine’s live logical accounting. RSS and physical device
traffic are outside the measurement scope.

For the late-admission contract, hold a producer charge and a separate
shared grant through the writer decision and first record. Exact configured
headroom admits the buffered writer. One byte less preserves the snapshot
writer. At 400 KiB of shared headroom a forced 512 KiB writer returns typed
shared denial before it can open the first file. The selector declines at
the same boundary and the snapshot encodes the exact row. Each arm drops
its private owners without changing the producer or peer grants.

Verify the full uncompressed byte and row limits, canonical names, lineage,
partition membership and unique original IDs for every completed result.
The harness independently reads output bytes and checks the final marker,
the materialization span on the snapshot route, and retirement of owned
temporary data. The selection changes the consumer of the sorted rows.
The random keys, domains, collision handling and partition traversal remain
the same. The comparison checks membership and conserved fields across
independently randomized Runs.

Seven browser fault cases ran on both writers. A late malformed row never
opened the destination. Strict byte-cap and file-count failures, an injected
write failure after a file closed, cancellation at the same boundary, and
marker write and readback mismatches all retired the owned destination and
workspaces. The marker tests observed all 208 CSVs closed before the marker
opened. Both arms withheld a completed publication on every fault.

For the separate 190 MiB managed temporary cap, use the same 420,003 rows,
32 MiB working budget and 512 KiB chunk cap. The snapshot exhausted its
managed temporary budget and cleaned up before opening a destination. The
guarded writer completed and verified all rows with a 149,442,694-byte
managed peak and one 22-way merge. Treat this as evidence that the route can
finish within that particular cap. A spilling job can still approach the
snapshot's combined storage peak when both temporary and output files share
the same volume.

### Reproduction and provenance

Build the feature-free baseline from `fc85297a41d24eb558daecf8ead9b40a816328e1`
and the guarded writer from `8af5e5b38baa5a9ac810b0373bd446d714606c3f` with
`node scripts/build-browser.mjs`, saving `ui/dist/engine.wasm` after each build.
For the screen, build the earlier 512 KiB writer with the route, buffer and
Auto sizing patches in the [initial experiment](hosted-partition-shuffle-direct-output-2026-11-26.md#reproduction-and-provenance).
The runs use Rust 1.99.1, Node 22.23.4, locked UI dependencies, production
browser workers and persistent disposable profiles. The recorded fixtures,
WASM and compiled worker identities, browser executable hash, observations,
times and post-Run counters are in the raw results. The OPFS arms used warm,
uncontrolled caches on one WSL2 ext4 host and bundled Chromium 156.0.8078.4.

| Batch | Harness | Raw records |
| --- | --- | --- |
| Larger buffer screen | [Main harness](../../benchmarks/guarded-hosted-partition-shuffle-harness-2026-11-26.mjs) | [Screen](../../benchmarks/guarded-hosted-partition-shuffle-screen-2026-11-26.jsonl) |
| Guarded cutoff, fanout, wide row and gzip | Main harness plus [held-out diff](../../benchmarks/guarded-hosted-partition-shuffle-harness-heldout-2026-11-26.patch) | [Qualifier](../../benchmarks/guarded-hosted-partition-shuffle-qualifier-2026-11-26.jsonl) |
| Guarded 3.253 GB | Held-out harness | [Scale](../../benchmarks/guarded-hosted-partition-shuffle-scale-2026-11-26.jsonl) |
| Actual picker destination | Held-out harness plus [desktop diff](../../benchmarks/guarded-hosted-partition-shuffle-harness-desktop-2026-11-26.patch) | [Desktop](../../benchmarks/guarded-hosted-partition-shuffle-desktop-2026-11-26.jsonl) |
| Failure and quota controls | Initial investigation controls plus [selector diff](../../benchmarks/guarded-hosted-partition-shuffle-harness-controls-2026-11-26.patch) | [Faults](../../benchmarks/guarded-hosted-partition-shuffle-faults-2026-11-26.jsonl) · [Quota](../../benchmarks/guarded-hosted-partition-shuffle-quota-2026-11-26.jsonl) |

From the root, install the locked UI dependencies with `npm --prefix ui ci`.
Copy the relevant base harness to a two-level directory such as
`scratch/replay/harness.mjs` and apply its diffs in order with
`patch -d scratch/replay -p1`. In `CONFIG.json`, point `browser` at the matching
executable and `engines` at the local WASM paths in baseline, candidate order,
using keys `baseline` followed by `buffered` for the screen or `selector` for
the other batches. Set `runTimeout` to 360 seconds. Copy each fixture record
into `cases`, omitting `kind`, `bytes`, `sha256`, `job` and desktop `permission`.

```sh
node scratch/replay/harness.mjs CONFIG.json scratch/rerun
python3 docs/benchmarks/guarded-hosted-partition-shuffle-verify-pairs-2026-11-26.py \
  CONFIG.json scratch/rerun/runs.jsonl
```

For the desktop batch set `xvfb` and `xdotool` to the installed program paths
and `browser` to the Linux Chrome executable. Use the same clean browser
version, local GTK chooser and 1,280 by 900 isolated X11 display as in the raw
record. Supply `xkbcomp` and the GTK image loader prerequisites. The measured
batch used a private X11 socket directory, loopback-only network namespace and
a reaping PID namespace with procfs for the nested GTK image loader sandbox.
The harness starts a new Chrome profile and approves the Chrome edit prompt
for the empty destination inside its output directory.

Reconstruct the controls base by applying the earlier controls diff to its
primary harness. Apply the new selector diff next and invoke that harness
in each mode with a fresh output directory.

```sh
node scratch/replay/harness.mjs BASELINE.wasm SELECTOR.wasm \
  scratch/controls-rerun faults CHROME_HEADLESS_SHELL
node scratch/replay/harness.mjs BASELINE.wasm SELECTOR.wasm \
  scratch/quota-rerun quota CHROME_HEADLESS_SHELL
```

The local runner retains the build retry and picker smoke failures. The
initial picker automation reached no Run while resolving a launcher, nested
GTK image loader, chooser focus and edit prompt. The desktop timing cohort
began after the grant and export smoke passed. The first full desktop batch
verified its outputs but left subprocesses at Chrome teardown. Its receipt
failed. The repeated cohort used the same frozen recipe with a reaping PID
namespace. The scale, desktop and smaller OPFS cohorts ran sequentially.
Timing comparisons use completed measured pairs from the accepted cohorts.
