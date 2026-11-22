## Uniform Balanced cross-tool at 40 GiB (2026-11-21)

Chopper completed the 40 GiB shuffle and eight-part split in 9m 12s.
The qsvlite workflow finished in 13m 27s. Chopper used 31.6% less
elapsed time and 31.8% less process CPU in this full qualification.
DuckDB's materialize-and-slice adapter failed to finish at both
internal memory settings. [Complete qualifications and failed attempts](../../benchmarks/uniform-balanced-40gib-cross-tool-summary-2026-11-21.json)

| Workflow | Complete elapsed | Process CPU | Peak process RSS |
| --- | ---: | ---: | ---: |
| Chopper, opt-in terminal Uniform and 256-way ceiling | 551.724 s | 333.91 s | 71.78 MiB |
| qsvlite 29.0.0, UUID and external line sort | 806.991 s | 489.33 s | 889.73 MiB |
| DuckDB 2.0.0, ordered materialization | Engine allocation denied | — | — |

Each workflow ran within a hard 1 GiB WSL2/ext4 cgroup with swap
disabled. Chopper had one worker, a 256 MiB engine setting and a
5600 MiB enforced output cap. The qsvlite workflow requested one
worker per command. UUID generation and column reorder overlapped
through a pipe. Independent verification checked every field, unique
source ID conservation, eight exact 20,971,520-row quotas, nonidentity
output order and actual per-file size. Chopper's manifest and
transactional cleanup were also checked. Those checks and fixture
hashing were outside the complete-job clocks. Each completed workflow
has one full sample with uncontrolled backing caches.

qsvlite used 188.58 seconds to generate UUIDs and reorder fields,
426.66 seconds inside its external line sort, 83.62 seconds to remove
the keys, and 108.00 seconds to split. Its line sorter is suitable here
because the fixture has no embedded newlines. The staged pipeline
written around that sorter accounts for about 380 seconds of its
clock. The external sort opens all runs for a single heap merge and
allocates a 1,000,000-byte buffer per run. One live sample showed 836
total descriptors and 818.5 MiB process RSS. The measurement is
a process sample during the merge. Chopper's job formed 984 runs and
performed four merges, with about 92.38 GiB of managed temporary
writes and the same amount read. These are logical traffic figures.
[qsv's pinned external sort implementation](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/extsort.rs#L82-L117)

DuckDB used one thread and preserved insertion order. Its all-VARCHAR
`CREATE TABLE AS SELECT … ORDER BY random()` failed during materialization.
At 256 MiB it refused a 30.5 MiB block with 226.7 MiB accounted.
At 512 MiB it could not pin another 256 KiB block with 511.9 MiB
accounted. The cgroup recorded zero OOM kills in both cases. Both
settings passed their small preflight. These observations bound the
specific materialized adapter and leave its full-scale elapsed time
unknown. An alternative adapter that streams ordered output to quota
writers would need an independent comparison. [DuckDB's parallel streaming merge design](https://duckdb.org/2025/09/24/sorting-again#merging)
