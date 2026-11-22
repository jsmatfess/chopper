## Terminal Uniform short tail at 40 GiB (2026-11-21)

Keep the bounded short-tail scheduler as an opt-in Linux experiment.
The three 8 GiB measured pairs passed both retention rules. In the
separate 40 GiB pair the same builds reduced complete-job elapsed
from 575.976 to 542.388 seconds and managed temporary traffic from
92.38 to 76.82 GiB in each direction. The 40 GiB qualification
provides one matched observation at the larger size.
[Matched 40 GiB receipts](../../benchmarks/terminal-uniform-short-tail-40gib-summary-2026-11-21.json)

| Complete-job measure | Original hierarchy | Short-tail scheduling |
| --- | ---: | ---: |
| Elapsed | 575.976 s | 542.388 s |
| Process CPU | 351.08 s | 347.26 s |
| Peak working reservations | 67,448,648 bytes | 67,649,752 bytes |
| Process peak RSS | 87,960 KiB | 86,740 KiB |
| Managed temporary writes | 99,192,634,864 bytes | 82,486,617,304 bytes |
| Managed temporary reads | 99,192,633,344 bytes | 82,486,615,784 bytes |
| Initial runs | 984 | 984 |
| Total merges | 4 | 2 |
| Cgroup file-cache refaults | 45,127,662 | 62,698,208 |

Both jobs used one worker, a 256 MiB engine setting and a hard 1 GiB
WSL2/ext4 cgroup without swap. The control ran first. Backing cache
state was uncontrolled. Independent verification covered all
167,772,160 rows and every field, source ID uniqueness, exact
20,971,520-row quotas, nonidentity order, serialized caps, the
manifest and cleanup outside the stopwatch. The build profiles
differ only in the short-tail feature. [8 GiB retention result and targeted controls](terminal-uniform-short-tail-2026-11-21.md)

The scheduler kept 984 initial runs and merged 473 into one, leaving
512 inputs for the last merge. Elapsed fell 5.83%, CPU fell 1.09%
and both directions of managed traffic fell 16.84%. File-cache
refaults rose 38.94% and GNU time filesystem input counters rose
19.76%, while filesystem output counters fell 11.74%. One live
intermediate-merge sample observed 1,465 descriptors, including
1,460 temporary-file handles. The descriptor sample does not
establish a peak. Managed traffic, process RSS, descriptor samples
and cgroup activity describe different scopes.

The selected raw Linux profile, default and all-feature Linux tests
and Clippy passed, along with portable-core WASM and WASI feature
compilation. Native Windows passed ordinary storage and direct-run
checks in an independently pinned MSVC/NTFS checkout. The scheduler's
active path is Linux-only. Both default release binaries were rebuilt.
[Current direct execution contract](../../direct-execution.md)
