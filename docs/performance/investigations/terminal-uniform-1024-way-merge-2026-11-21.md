## Terminal Uniform 1024-way merge (2026-11-21)

The prototype expanded the eligible Linux terminal Uniform ceiling from
256 to 1,024 when the soft descriptor limit reached 8,192. The existing
memory calculation still bounded the actual reader count. At 40 GiB the
984-run job eliminated all three intermediate merges, but the first
measured pair was 14.61% slower with the higher ceiling. That exceeded
the 8% maximum slowdown for any resource-rule pair and also ruled out
the all-favorable elapsed rule. The runner stopped after the verified
pair before launching either remaining timed pair. The prototype was
removed. [Completed pair, excluded warmup, and exact build identities](../../benchmarks/terminal-uniform-1024-way-merge-summary-2026-11-21.json)

| Complete 40 GiB job | 256-run ceiling | 1,024-run ceiling |
| --- | ---: | ---: |
| Elapsed | 532.709 s | 610.531 s |
| Process CPU | 331.29 s | 365.35 s |
| Initial runs | 984 | 984 |
| Merges including final traversal | 4 | 1 |
| Managed temporary writes | 99.193 GB | 55.700 GB |
| Managed temporary reads | 99.193 GB | 55.700 GB |
| File-cache refault events | 41.57 million | 106.94 million |
| Voluntary process context switches | 112,714 | 435,571 |

The completed run at each ceiling used one worker, a 256 MiB engine
setting, the same 40 GiB plain fixture and a 1 GiB WSL2/ext4 cgroup
without swap. The entire 167,772,160-row output passed independent
field, ID, exact quota, actual serialized cap, manifest and cleanup
checks. The control and candidate were built from the same source
with one compile-time flag difference. The excluded warmup pair had
552.864 and 602.890 seconds, respectively. There is one eligible pair,
with two unattempted pairs. No 40 GiB timing median or variability
claim follows from this stopped cohort.

The narrower hierarchy wrote 1.78083 framed passes in the independent
structural qualification. The candidate dropped 43.85% of managed
spill bytes in each direction without materially changing engine
working peak. Cache refaults rose 157.22%, the GNU time filesystem
input counter rose 75.93%, and system CPU rose 33.53%. Counters for
managed spill, charged working allocations, kernel events and physical
device I/O have distinct meanings. A separate excluded descriptor
sample near final merge start showed 1,977 total open descriptors,
including 1,971 for 987 distinct temporary paths. This is one process
snapshot. It excludes descriptors opened and closed outside that sample.

The results motivate separating the pending run catalog limit from the
number of runs merged at once. GNU sort sometimes processes only the
extra runs needed to fit the following merge window. PostgreSQL chooses
fan-in with per-reader prefetch space and caps merge order partly for
cache locality. Both design ideas justify independent experiments
with Chopper’s existing framed rows and storage accounting.
[GNU sort tail merge](https://github.com/coreutils/coreutils/blob/v9.8/src/sort.c#L3682-L3740) ·
[PostgreSQL merge and buffer sizing](https://github.com/postgres/postgres/blob/REL_18_1/src/backend/utils/sort/tuplesort.c#L1664-L1744)
