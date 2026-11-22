## Terminal Uniform kernel read-ahead (2026-11-21)

Keep normal kernel read-ahead for the measured wide terminal Uniform merge.
Advising the kernel to suppress speculative reads increased elapsed time by
57.29% and process CPU by 6.34%, despite a large reduction in file-cache
refaults. Every measured pair was slower with the advice. The prototype was
removed. [Exact samples and build identities](../../benchmarks/terminal-uniform-kernel-read-ahead-summary-2026-11-21.json)

| Measurement | Normal median [range] | Advice median [range] |
| --- | ---: | ---: |
| Complete elapsed | 79.621 [79.066–82.274] s | 125.235 [119.058–125.589] s |
| Process CPU | 51.59 [51.35–51.89] s | 54.86 [54.67–55.31] s |
| File-cache refault events | 9.33 [7.90–9.66] million | 0.677 [0.674–0.678] million |
| Direct page scans | 18.12 [16.68–18.37] million | 9.41 [9.41–9.42] million |
| Voluntary process context switches | 12,854 [12,472–13,814] | 175,920 [175,852–177,818] |

All jobs used the same 8 GiB repeated input, 197 sort runs, one terminal
merge, one worker, a 256 MiB engine setting and a hard 1 GiB WSL2/ext4
cgroup without swap. Pair order alternated and the warmup pair is excluded.
The independent oracle verified all fields and unique IDs, exact Balanced
quotas, actual serialized caps, metadata and private-output cleanup. The
timed boundary runs through complete publication. Managed temporary writes
remained 11,140,072,936 bytes and reads remained 11,140,071,424 bytes.
Accounted working peak increased by 402 bytes. Process RSS was about
85.6 MiB for both, and both cgroups peaked at 1 GiB including file cache.

The prototype applies `POSIX_FADV_RANDOM` to independently opened raw
spill readers in the unobserved terminal Uniform merge with more than 64
inputs. The 64 KiB application buffers remain the same. A separate tagged
2 GiB probe verified the kernel accepted all 197 calls on controlled
spill descriptors. Neither the instrumented run nor the private profile
contributes samples to the timing pairs.

GNU time's file-system input counter fell by 63.79%. The whole-scope
file-cache refault and direct-scan counters fell by 92.74% and 48.07%.
These counters cover different events and provide no independent
physical-device census. The simultaneous rise in elapsed time and
voluntary context switches is consistent with more blocking on
individual reads, but reason and duration for each context switch were
not captured. In Linux 6.18, the hint sets the file's random mode, and
the synchronous readahead path limits that mode to the requested range.
[Kernel advice](https://github.com/torvalds/linux/blob/v6.18/mm/fadvise.c) ·
[Kernel read-ahead](https://github.com/torvalds/linux/blob/v6.18/mm/readahead.c)

Neither retention path passed. A separate application-buffer experiment
can test larger admitted reads with normal kernel mode. qsv's pinned
external-sort wrapper supplies an approximately 1 MB buffer per
chunk, and its pinned ext-sort dependency uses a binary heap. The prior
art supports testing capacity independently of changing the merge heap.
[qsv buffer setup](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/extsort.rs) ·
[ext-sort 0.1.6 source archive](https://static.crates.io/crates/ext-sort/ext-sort-0.1.6.crate)
