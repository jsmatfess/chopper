## Bounded I/O overlap adoption (2026-11-22)

These matched comparisons time Run through publication and cleanup. Independent
output verification is outside the clock. The gate requires at least 0.25
seconds and 5% lower median elapsed, favorable results in both reversed
pairs, and at most 15% more CPU. Analyze is disabled in both arms. The browser
arms use the same WASI engine and each native pair uses the same source,
configuration and ordered output verifier.

### Hosted plain CSV

[Integrated streaming pairs](../../benchmarks/io-overlap-adoption-2026-11-22-browser.jsonl) ·
[Integrated Partition pairs](../../benchmarks/io-overlap-adoption-2026-11-22-browser-partition.jsonl)

| Disk-backed CSV size | Synchronous direct | Source prefetch and batched writes | Time saved |
| --- | ---: | ---: | ---: |
| 391 MiB | 11.47 s | 4.44 s | 7.02 s |
| 977 MiB | 27.00 s | 10.91 s | 16.10 s |

All four pairs pass with fresh persistent Chromium profiles and an OPFS
destination. Browser process CPU changes from 15.95 to 8.67 seconds at
391 MiB and from 39.27 to 21.45 seconds at 977 MiB. Sampled sums of process
RSS change from 456 to 449 MiB and 530 to 519 MiB respectively. Engine
working reservations peak at 212,036 bytes in both arms. Managed workspace
traffic is 7,252 bytes in each direction at 391 MiB and 18,201 bytes per
direction at 977 MiB in both arms.

Plain streaming enables one 256 KiB source window ahead and one asynchronous
destination write. The storage worker coalesces adjacent writes to the same
file into a reusable 1 MiB block. Two shared slots and the worker's ordinary
buffers have 2.5 MiB plus 24 control bytes of live capacity outside the WASI
reservations. Rejected source speculation falls back to a normal read.
Destination work drains before control operations, and pending bytes flush
before file close and completion. Cancellation waits for in-flight work,
discards buffered bytes and removes the incomplete directory. A folder
with a valid committed completion marker survives cancellation.

A single plain Partition also uses prefetch. Destination writes follow
the ordinary synchronous path. The balanced eight-key 391 MiB case
improves from 10.82 to 9.76 seconds. A skewed eight-key 977 MiB case
improves from 27.00 to 22.89 seconds. All four pairs favor prefetch and
the median process CPU changes by less than 1% for each size.

All sixteen browser runs verify record contents, encounter order within
each output group, exact serialized byte caps, the marker and workspace
cleanup. Thirteen focused
browser cases exercise successful output, a late malformed record, boundary
crossings in both buffers, rejection of the first prefetched window, an
in-flight source cancellation, a failed coalesced write, cancellation during
that write, the destination write and close errors, marker faults, and
cancellation after marker close. A broader browser check initially read the
destination before asynchronous cleanup had retired the failed worker.
The corrected check tests for absence of a completion marker and waits for
folder cleanup. The storage error bridge, peer-tab cleanup and persistent
process-kill direct-Run checks also passed.

The earlier [desktop picker experiment](desktop-picker-write-overlap-2026-11-22.md)
qualifies the separate writer prototype with a picker-selected ext4 folder.
The integrated timing above covers same-origin OPFS on one WSL host.
Compressed inputs and outputs and multi-step pipelines retain ordinary
browser I/O.

### Native snapshot publication

[Linux competing opt-in](../../benchmarks/io-overlap-adoption-2026-11-22-linux-opt-in.jsonl) ·
[Linux competing Auto](../../benchmarks/io-overlap-adoption-2026-11-22-linux-auto.jsonl) ·
[Linux 192-file control](../../benchmarks/io-overlap-adoption-2026-11-22-linux-coarse.jsonl) ·
[Windows competing opt-in](../../benchmarks/io-overlap-adoption-2026-11-22-windows-opt-in.jsonl) ·
[Windows competing Auto](../../benchmarks/io-overlap-adoption-2026-11-22-windows-auto.jsonl)

Two simultaneous 2 GiB Partition jobs each produce 1,152 files with 2 MiB
caps, four configured workers and a 256 MiB memory budget. The Linux
production candidate takes 19.14 seconds median makespan versus 34.20
seconds for serial publication. Both reversed pairs improve and all eight
runs verify. Median per-process CPU changes from 12.27 to 12.13 seconds,
peak RSS from 74.2 to 74.9 MiB and peak working reservations stay near
64.39 MiB. Managed temporary writes and reads stay at 4,548,795,093 and
4,550,051,684 bytes per job. The existing four-writer experiment also
improved both reversed rounds under competition. The live-headroom policy reaches
three writer slots on the measured configuration.

On native Windows NTFS, the narrowed Auto candidate reduces the median
makespan from 22.45 to 18.41 seconds and improves both reversed rounds.
Median per-process CPU moves from 14.48 to 15.31 seconds and peak working
set from 72.3 to 72.4 MiB. Peak working reservations again stay near 64.39
MiB, and logical temporary traffic is unchanged. All eight runs verify.
The separate four-writer opt-in also passes the elapsed and CPU gate.

The 192-file control has one tie at the recording precision and misses
the all-pairs gate. Auto uses the high-fanout rule for plain, single-Partition
Linux and Windows Runs that reach snapshot publication with at least 2 GiB of validated
serialized output, at least 1,152 files and four or more resolved workers.
The verified output plan supplies size and file count. Each batch is
limited to four slots, current local and shared memory headroom, descriptor
capacity and remaining files. A focused native test adds a competing
workspace owner and verifies that the same rule reduces to one slot and
recovers after release. Existing failure tests verify admission errors,
cancellation and removal of private staging after a written prefix.

The competing jobs used separate processes. Linux under WSL, native
Windows and browser measurements share one physical machine, and some
qualification runs overlapped. Shared in-process pressure is tested
independently. The candidate keeps the
existing ordered chunk collection, manifest and atomic publication
contract. The 192-file control exercised the broader candidate before the
file-count rule was narrowed.

### Rejected CPU overlap

The [counted Balanced digest investigation](input-prefetch-native-publication-and-digest-overlap-2026-11-22.md#counted-balanced-second-pass-digest)
found an isolated 512-byte-row gain against a same-buffer serial control.
The 256-byte, 4 KiB and 512 KiB rows missed the delivery gate. The prototype
remains archived for a separately calibrated selector and an ownership model
that preserves the existing large-record behavior.

### Reproduction

Use the pinned baseline and candidate workers with byte-identical WASI
engines for the browser comparison. Screens and historical substitutions
remain available separately. For the native Auto comparison, use release
builds with `experimental-counted-balanced` in both arms and no plain
publication opt-in. Use the revision-checked Windows dispatcher for native
NTFS measurements. The opt-in control also enables
`experimental-plain-publication` in the challenger.

```sh
node scripts/benchmark-auto-multigib.mjs streaming-io-production CANDIDATE_ASSETS EMPTY_SCRATCH BASELINE_ASSETS
node scripts/benchmark-auto-multigib.mjs partition-io-production CANDIDATE_ASSETS EMPTY_SCRATCH BASELINE_ASSETS
python3 scripts/benchmark-auto-contention.py publication-competing EMPTY_SCRATCH SERIAL --writers-binary CANDIDATE
python3 scripts/benchmark-auto-contention.py publication-coarse EMPTY_SCRATCH SERIAL --writers-binary CANDIDATE
node scripts/test-browser-direct-destination.mjs
```
