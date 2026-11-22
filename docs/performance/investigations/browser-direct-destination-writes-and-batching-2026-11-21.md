## Browser direct destination writes and batching (2026-11-21)

Writing final result files directly saved a full OPFS output copy in these runs.
A separate candidate coalesced adjacent writes into a single 1 MiB buffer.
The candidate improved streaming more than partitioning. Its evidence supports
more testing on user-selected folders before a product change.

[Individual runs and build identities](../../benchmarks/browser-direct-destination-writes-2026-11-21.json)  
[Replay harness](../../../scripts/benchmark-browser-destination.mjs)

| Job | Destination path | Runs | Median complete seconds [range] | Median peak OPFS workspace MiB |
| --- | --- | ---: | ---: | ---: |
| Streaming | Staged | 5 | 0.712 [0.710, 0.743] | 16.001 |
| Streaming | Direct | 5 | 0.504 [0.503, 0.513] | 0.002 |
| Streaming | Batched | 5 | 0.377 [0.377, 0.378] | 0.002 |
| Partition | Staged | 5 | 0.794 [0.782, 0.832] | 31.992 |
| Partition | Direct | 5 | 0.626 [0.624, 0.637] | 15.992 |
| Partition | Batched | 5 | 0.614 [0.610, 0.621] | 15.992 |

Each complete Run includes worker startup, engine processing, closing result
streams, writing and verifying the completion marker, and workspace cleanup.
Input selection and independent output verification are outside that clock.
Chromium 156.0.8078.4 ran headlessly under WSL with disposable contexts and
a same-origin OPFS destination. The same WASM ran all three variants.
The fixture has 32,768 rows and 16,766,121 source
bytes. Both jobs use uncompressed, 1 MiB-capped CSV output. The partition job
uses eight keys. Both use Auto memory and the single hosted processing worker.

The staged control writes final results to OPFS and exports them to the
destination using the retained copy path. The direct variant uses the production
storage bridge. The batched variant reuses one 1 MiB buffer, flushes on writer
changes or discontinuities and flushes before control operations such as close.
It tests coalescing browser writes with serialized backpressure. It does not
test concurrent writers or overlap with engine computation.

Runs rotate variant order and use independent browser contexts. Every run
preserved records and matched the per-file CSV hashes for its job. Each output
manifest respected the byte cap. Workspace peaks are logical OPFS file sizes.
The runs do not measure OS disk throughput, CPU or process RSS. An initial
harness attempt lacked worker isolation headers in its substituted responses.
That attempt was stopped and excluded before collecting this panel.

Replay from a disposable checkout or isolated build of the current sources:

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
node scripts/benchmark-browser-destination.mjs
npm --prefix ui run build:hosted
```

The final build removes the benchmark-only assets. The batching variant is
compiled only by the harness.
