## Terminal Uniform merge read buffers (2026-11-21)

Widening each admitted final-run reader from 64 KiB to 256 KiB
changed median complete-job time by +4.81%
and process CPU by +4.69%. Neither predeclared retention rule passed. The candidate was removed.
[Complete pairs and resource measurements](../../benchmarks/terminal-uniform-merge-read-buffers-summary-2026-11-21.json)

| Measure, median [range] | 64 KiB | 256 KiB |
| --- | ---: | ---: |
 | Complete elapsed | 84.237 [83.630–85.783] s | 88.290 [87.942–88.292] s |
 | Process CPU | 53.52 [53.45–54.10] s | 56.03 [55.77–56.51] s |
 | Peak process RSS | 87740 [73332–87904] KiB | 87896 [73264–87944] KiB |
 | Peak working reservations | 67431811 [67431811–67431811] bytes | 67432213 [67432213–67432213] bytes |
 | File-cache refaults | 9236254 [8865740–9684653] | 10305716 [8846307–10485755] |

The 8 GiB fixture runs in a hard 1 GiB WSL2/ext4 cgroup with swap
disabled, one worker and a 256 MiB engine setting. The clock includes
native Uniform shuffle and direct Balanced publication. Three
alternating complete pairs contribute to the table. The small
preflight pair, full warmup pair and instrumented probe runs are
excluded. The exact all-field oracle verified unique IDs, actual per-part
caps, exact quotas, nonidentity order and manifest cleanup. Each
timed run formed 197 runs and one merge. Managed traffic was the
same at roughly 10.38 GiB in each direction. The measured elapsed
pair changes were +5.57%, +2.92%, +4.40%, with CPU changes of +4.20%, +4.45%, +4.83%.

Median system CPU increased 17.89%, while user CPU fell 1.73%.
File-cache refaults increased 11.58% and direct page scans increased
5.58%. These counters describe the cgroup during the complete job.

The experiment charged wider buffers before opening the temporary
readers and kept the same file ownership and fan-in. Before timing,
the 512 MiB probe with the larger job setting recorded 2,681 reads
requested at 256 KiB against spill files. The lower-budget probe
recorded 10,822 requests at 64 KiB and zero at 256 KiB. Both passed
the independent output check. These diagnostic runs verify dispatch
and admission behavior at different memory settings. Linux local
and shared admission control, native storage tests and compact-spill
compilation passed. Process RSS, working reservations, file-cache
refaults, and managed spill bytes have distinct scopes.

qsv's external sort uses a larger per-run buffer and opens all runs
for one merge. PostgreSQL sizes merge order using memory and
preread targets. The controlled Chopper comparison holds merge order
and normal OS read-ahead constant. The separate kernel advice
experiment changed another mechanism.
[qsv wrapper](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/extsort.rs#L82-L117)
[PostgreSQL merge-order calculation](https://github.com/postgres/postgres/blob/REL_18_1/src/backend/utils/sort/tuplesort.c#L1664-L1744)
[Earlier kernel advice test](terminal-uniform-kernel-read-ahead-2026-11-21.md)
