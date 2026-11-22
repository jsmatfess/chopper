## Browser direct destination write overlap (2026-11-22)

The [direct destination screen](browser-direct-destination-writes-and-batching-2026-11-21.md)
found that coalescing browser writes improved plain streaming. This follow-up
compares today's direct path, coalescing into 1 MiB writes, one asynchronous
write slot, and the combination. All four variants publish directly.

### Mechanism

The prototype owns one 1 MiB shared byte slot and a separate acknowledgement
for destination writes. After copying a write to the slot, the engine can
continue parsing, serializing, or requesting temporary storage. It drains
the slot before reusing it or sending a destination operation such as close,
truncate, or finish. The existing storage worker still serializes destination
operations. Combined mode also uses the existing experiment's 1 MiB coalescer.
The extra buffers are benchmark-owned JavaScript storage outside WASI working
reservations. The production path continues to use the synchronous bridge.

On failure a deferred write error reaches the engine at the next destination
barrier. Cleanup retires the storage worker's input, waits for active storage
operations, and uses the shared incomplete-destination cleanup. Closing all
output files remains a prerequisite for creating and verifying
`CHOPPER-COMPLETE.json`.

### Complete-job screen

[Raw screen](../../benchmarks/browser-direct-destination-write-overlap-2026-11-22-screen.json)

Chromium 156 ran on WSL with same-origin OPFS destinations. Each job used
196,608 input rows, a 96.08 MiB source and strict 8 MiB CSV caps. The clock
starts at Run and ends after marker verification and workspace cleanup.
Each cell is the median of four runs, with the observed range in brackets.
Order rotates and each run has a disposable context. The same WASM ran all
variants. Every job verified field values, conservation, byte caps and
matching output CSV hashes within its workload.

| Workload | Direct | Batched | Async | Async + batched |
| --- | ---: | ---: | ---: | ---: |
| Plain streaming | 2.375 s [2.356, 2.405] | 1.558 s [1.542, 1.584] | 1.837 s [1.816, 1.844] | 1.441 s [1.431, 1.461] |
| Gzip streaming | 1.358 s [1.342, 1.370] | 1.328 s [1.328, 1.339] | 1.340 s [1.339, 1.348] | 1.323 s [1.318, 1.341] |
| Plain partition, eight keys | 6.127 s [6.114, 6.161] | 6.048 s [6.013, 6.305] | 5.859 s [5.808, 6.008] | 5.902 s [5.870, 6.004] |

Plain streaming was the clear gain. Async alone saved about half a second
and coalescing alone saved about eight tenths. The combined path removed a
further 0.12 seconds over coalescing. Gzip had little elapsed change. Partition
showed a small overlap benefit and the combined variant did not improve the
async-only median.

### Disk-backed holdout

[Raw holdout](../../benchmarks/browser-direct-destination-write-overlap-2026-11-22-holdout.jsonl)

The holdout uses a different row width, 400,000 rows and a disk-backed
390.63 MiB input `File`. It uses a fresh persistent Chromium profile per
trial and an OPFS destination, with paired orders reversed. Independent
validation checks every row and its order, field contents, the manifest,
capped files, output inventory and the completion marker. Each run samples
CPU across browser processes and sums process RSS at 500 ms intervals.
Shared pages can contribute to more than one process's RSS. WASI working
reservations and logical OPFS traffic are separate scopes. These measures
do not establish physical device throughput.

| Variant | Complete Run median [range] | Browser CPU seconds [range] | Sampled browser peak RSS MiB [range] |
| --- | ---: | ---: | ---: |
| Direct | 10.404 s [10.354, 10.454] | 15.31 [15.28, 15.33] | 457.1 [456.2, 457.9] |
| Async | 7.756 s [7.756, 7.756] | 14.60 [14.60, 14.60] | 460.3 [449.1, 471.4] |
| Batched | 6.303 s [6.253, 6.352] | 8.66 [8.63, 8.68] | 429.3 [425.8, 432.7] |
| Async + batched | 5.853 s [5.852, 5.853] | 8.44 [8.44, 8.44] | 427.6 [426.5, 428.6] |

Both rounds verified at all four modes. The combined mode saved 4.55 seconds
relative to direct, including 0.45 seconds relative to batching alone.
The async-only arm spent about 3.72 seconds draining the pending slot.
The combined arm spent about 1.40–1.42 seconds there. Engine peak working
reservations were 212,036 bytes across all eight jobs. The measured peak
OPFS workspace was 7,252 bytes in each job. Destination file traffic was
tracked independently and every job removed its workspace.

### Failures and scope

[Publication checks](../../benchmarks/browser-direct-destination-write-overlap-2026-11-22-faults.json)

Direct, async and combined modes each passed success, late invalid input,
write failure, close failure, marker write failure, marker readback failure,
cancel during an acknowledged in-flight write, and cancel after a valid
marker closed. Error and cancel controls check owned incomplete folder
removal. The marker cases check retention of already complete files.
The timed paths use real Chromium filesystem writes and the same Rust
engine and CSV limits. Fault injections take place outside timed trials.

These results support qualifying coalesced async writes on the plain
streaming route. Batching accounts for most of the gain, and the incremental
overlap benefit repeats on two streaming fixtures. The gzip and partition
cells support narrower claims. An isolated desktop-picker attempt stopped
before browser selection because its virtual display could not initialize
the keyboard. The timed evidence covers same-origin OPFS on one WSL host.
The prototype stays benchmark-only pending picker-selected destination
evidence and integration with the runtime's memory accounting.

### Replay

Use a disposable hosted build because the small harness writes bench-only
assets to `ui/dist`. Both harnesses pin the engine and worker hashes.
The user-facing hosted bundle keeps the ordinary direct path.

```sh
node scripts/benchmark-browser-destination.mjs --async
mkdir -p scratch/write-overlap-holdout
node scripts/benchmark-auto-multigib.mjs destination-overlap ui/dist scratch/write-overlap-holdout
node scripts/test-browser-direct-destination.mjs
node scripts/test-browser-direct-destination.mjs --async
node scripts/test-browser-direct-destination.mjs --async-batched
```
