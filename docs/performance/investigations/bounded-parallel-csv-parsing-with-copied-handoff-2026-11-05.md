## Bounded parallel CSV parsing with copied handoff (2026-11-05)

**Decision: reject this unchanged copied-batch prototype.** The
[raw six-job record](../../evidence-originals.md#sha256-d741d13d9b46b4db52c6a2c8e19c447c089c3157662a8d5ca0e1f8b63970ea53),
[private prototype patch](../../benchmarks/bounded-parallel-csv-2026-11-05.patch) and
[native harness](../../benchmarks/bounded-parallel-csv-2026-11-05.py) compare against the
[stronger strict serial control](../../performance.md#strict-csv-serial-admitted-span-control-2026-11-05).
The patch is retained evidence, not applied engine code. No production, execution
graph/retry, default, worker-selection or Auto policy changes follow. The separate
[source-backed techniques review](../../csv-ingestion-techniques.md) explains why Rayon,
csveee and medialab/simd-csv are integration candidates rather than equivalent
strict, admitted parser replacements; upstream throughput is not Chopper evidence.

The native-only private feature parses the header serially, then transfers the
same buffered reader to an inline owner. Quote-parity LF searches discover batch
boundaries; the existing strict Parser validates each worker chunk. At most four
existing job-pool workers process one synchronous batch of at most 1,024 records,
with a 128-KiB raw target and a 1,179,650-byte raw capacity for the 1-MiB record
limit. Completed compact records drain in source order through existing owned or
compact **copying** APIs. Raw bytes, indices, worker metadata, retained records and
parser growth compete within job/shared reservations; old rows clear before the
next batch, parsers drop before grants shrink and workers join before cleanup.
Deferred reader errors preserve earlier strict CSV errors. The extension/dialect
filter is not a proven plain-input magic detector: disguised compressed inputs
remain a production-eligibility gap, irrespective of the timing rejection.

Exactly six fresh native Windows CLI Runs use four workers and matching 32-MiB
job/process budgets. One million probe-v1 ASCII records use ordered export with
1,000,000-row/128-MiB caps; the schedule is serial/parallel/parallel/serial. Seconds
include CLI startup through complete Run/publication, Analysis JSON and process
exit, excluding fixture generation, hashes and independent output verification.

| Ordered export | Observations | Median seconds | Range seconds |
| --- | ---: | ---: | ---: |
| Stronger strict serial | 2 | 0.43630 | 0.36700–0.50561 |
| Bounded parallel, copied handoff | 2 | 0.79614 | 0.73859–0.85369 |

Candidate-minus-baseline paired differences are +0.34808 and +0.37159 seconds;
the candidate median is 82.47% higher relative to baseline. These short samples
have substantial drift, uncontrolled warm cache and background applications; no
tail, threshold or general parser claim follows. The separate 200,000-row
partition -> probabilistic 80/20/0 allocation -> uniform shuffle pair retains
1,024-row/65,536-byte caps and 296 output files. Its serial/parallel observations
are 1.40887/1.41220 seconds, an unreplicated diagnostic with no useful gain.
Framing, raw copying, strict reparsing, compact retention, receiver-copy growth
policy and dispatch costs are included together; none has isolated attribution.
This result does not reject parallel parsing fused with useful initial computation.

All six jobs independently verify actual fields, unique IDs, group/lineage,
strict caps, inventory and cleanup. Per-recipe raw CSV SHA-256 maps, ordered output
records and 17 logical Analysis fields match exactly; ordered CSV bytes equal the
input. Candidate traces report 977/196 joined batches for ordered/pipeline Runs,
four worker slots and 1,466,928 bytes as the maximum **sampled post-join** source
grants. The stderr label `peak_owned_grants` does not measure parser growth overlap
or RSS. Returned Analysis workspace peaks are 202,285 bytes serial versus
1,668,926–1,668,996 parallel for ordered export, and 7,461,130 versus 8,920,472 for
the pipeline. Both pipeline snapshots show eight sort runs, four merges and equal
logical traffic. These returned diagnostics precede final publication and do not
measure complete-Run I/O, physical device traffic or process RSS.

Preserved semantic attempts include two compile failures, a five-gate pass, and
a later full-Run test-counter failure: the first valid serial Run passed its
output checks, then the counter missed the direct path's existing progress phase.
A separately reviewed recovery changes only that test callback, keeping the
exact-one-visit assertion. Final formatting, feature all-target Clippy and focused
controls pass 3/3. Fourteen recovery Runs cover ordered/pipeline valid, late width,
late quote and post-join cancellation with exact parity, error and cleanup checks;
the earlier first Run makes 15 functional attempts total. Refill, UTF-8, working
limits, deferred reader errors, partial admission denial and last-owner release
controls also pass. Earlier default-workspace/core-WASM passes apply only where
compiled relevant bytes are unchanged; failed batches remain failed/incomplete.

The first native attestation failed before build/jobs because directory tokens
lack file hashes. Its retained replacement correctly distinguishes 328 files and
81 directory tokens. The final native batch passes 4/4 gates: exact baseline reuse,
one candidate build, six-job panel and verification. Original declared file-set
hashes match the new serial snapshot, and final native candidate sources match
the Linux prototype except an identical unused probe example. Exact patch replay
passes. No timed job was repeated, matrix expanded or own Linux build run during
native timing. Both study caps (six jobs, one candidate build) are consumed.

Windows 11 build 26200, Ryzen 7 5800X (8 cores/16 logical CPUs), NTFS, Rust 1.99.1,
full source/toolchain/binary identities and raw attempts remain under private
`scratch/parallel-csv-20261105T0702/` in both checkouts. Browser threading,
compression/other encodings, fused worker computation and broad scale acceptance
remain outside this result. No private archived benchmark logs were hydrated.
