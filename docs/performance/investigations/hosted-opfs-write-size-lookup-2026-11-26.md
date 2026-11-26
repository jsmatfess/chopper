## Hosted OPFS write size lookup (2026-11-26)

Keep the existing storage-worker size query after a successful OPFS write.
The candidate derives the new quota-ledger size from the previous tracked
size and the end of a positive write that returns its entire requested count.
It still queries the handle after partial writes, zero-byte writes and
truncation. The File System Standard describes complete writes and returned
counts. Chromium's regular-file delegate holds the backing file and uses
the host file length for its size query.
[File System Standard](https://fs.spec.whatwg.org/#api-filesystemsyncaccesshandle-write) ·
[Chromium regular-file implementation](https://chromium.googlesource.com/chromium/src/+/cf64617c1cc509f1dc88adb068ef64e61457bc0f/third_party/blink/renderer/modules/file_system_access/file_system_access_regular_file_delegate.cc)

### Complete Runs

Both arms use the feature-free WASM from
`feb6721e1a5b600100d27b2209bfc1764f578943`. Only the storage worker differs.
Use persistent bundled Chromium 156.0.8078.4 on WSL2 ext4, with uncontrolled
warm caches, a single worker, and exactly Uniform Shuffle then Partition
with snapshot publication. One warmup per arm and cell is excluded.
The clock includes verified marker readback and workspace retirement.
An independent readback checks every field and ID, ordered stage metadata,
partition membership, file inventory and caps, and the committed marker.

| Workload | Pairs | Existing, s | Candidate, s | Paired seconds saved |
| --- | ---: | ---: | ---: | ---: |
| 0.96 MB resident control, 32 MiB | 2 | 0.262 [0.257, 0.267] | 0.263 [0.257, 0.269] | -0.001 [-0.012, 0.010] |
| 1.265 GB spill, 128 MiB and 49 sort runs | 3 | 33.426 [33.366, 33.527] | 33.440 [33.419, 33.515] | 0.007 [-0.149, 0.086] |

The large pairs had between 27,254 and 27,261 OPFS write calls. Both arms
wrote 2,719,928,718 bytes to the workspace and kept the same merge and
working memory peak. The initial verifier limited same-route storage
peak differences to one 64 KiB buffer. Randomized final merge and snapshot
boundaries shifted when a spill file retired. The revised verifier bounds
that instantaneous peak variation by one 1 MiB bridge slot while requiring
equal cumulative writes, exact CSV data and the original timing gates.
The initial verifier failure and original timing records are retained.

The large workload needed every pair to save time and a paired median
saving of at least 0.20 seconds. It missed that gate. This tests the
complete job effect of eliminating eligible calls on one persistent
Chromium backend. The bridge reports writes and their payload, with
individual host size-query latency and other OPFS backends outside the
measurement scope.
[Raw observations](../../benchmarks/hosted-opfs-write-size-screen-2026-11-26.jsonl)

### Replay

Apply the [storage worker change](../../benchmarks/hosted-opfs-write-size-worker-2026-11-26.patch)
to a separate copy of the baseline worker source. Apply the
[worker-variant harness diff](../../benchmarks/hosted-opfs-write-size-harness-2026-11-26.patch)
after the [reverse pipeline timing diff](../../benchmarks/hosted-shuffle-then-partition-harness-2026-11-26.patch)
on the [base harness](../../benchmarks/guarded-hosted-partition-shuffle-harness-2026-11-26.mjs).
Build the baseline WASM with the locked Cargo build and use it in both
`engines` entries, ordered `baseline` then `size-from-write`. Pass original
and candidate storage-worker paths using the same keys under
`storageWorkers`. Use the exact recipes and time gates in the raw fixture
records as `cases`, the matching browser executable as `browser`, and a
`runTimeout` of 120 seconds. Use the
[paired verifier](../../benchmarks/hosted-opfs-write-size-verify-2026-11-26.py)
to check the receipts against the frozen limits.
