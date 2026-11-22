## Desktop picker write overlap (2026-11-22)

This holdout repeats the plain streaming comparison from the
[OPFS investigation](browser-direct-destination-write-overlap-2026-11-22.md)
using a real destination selected through Chromium's native folder picker.
It uses the same 96.08 MiB fixture, 196,608 input rows, and strict 8 MiB CSV
caps. The disposable headed Chromium 156 profile ran through WSLg. A user
selected the task-owned folder on the Linux ext4 filesystem and granted
write access. The harness confirmed a job-owned result folder appeared
on disk while processing and the selected parent was empty after cleanup.

[Raw desktop picker runs](../../benchmarks/browser-direct-destination-write-overlap-2026-11-22-desktop.jsonl)

| Variant | Complete Run median [range] |
| --- | ---: |
| Direct | 3.129 s [3.064, 3.133] |
| Async | 2.562 s [2.561, 2.621] |
| Batched | 2.388 s [2.357, 2.461] |
| Async + batched | 2.255 s [2.237, 2.319] |

All 12 runs published valid markers, verified records, matched output CSV
hashes, enforced the byte caps, and removed their own output folders.
Three rounds reused one selected directory handle with new workers and
alternating variant order. Selection and independent verification are
outside the complete Run clock. The combined path saved 0.87 seconds
against current direct writes and 0.13 seconds against batching alone.
Async alone saved 0.57 seconds.

The desktop holdout corroborates the OPFS result on plain streaming.
It used one filesystem and machine. Compressed and partitioned output were
only measured in the OPFS screen. The async and batching paths remain
benchmark-only until their buffers and failure controls are integrated
into the production resource and publication contracts.

For replay, build the default hosted assets in a disposable checkout, then
run the command below and choose the exact empty folder printed by the
harness. The timed desktop pilot used a manually launched server and the
same worker variants. The replay wrapper owns the server and test directory.

```sh
node scripts/benchmark-browser-desktop-destination.mjs
```
