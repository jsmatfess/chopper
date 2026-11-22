## Streaming shuffle adapters at 40 GiB (2026-11-21)

The qsvlite pipe completed the 40 GiB shuffle and exact eight-part split
in 11m 51s. That is 11.95% less elapsed than the file-staged qsvlite
workflow. Chopper's earlier same-scope qualification took 9m 12s,
22.35% less elapsed than the faster qsvlite workflow. The native DuckDB
COPY piped to qsvlite split hit the DuckDB engine limit before output.
[Verified full runs and failed attempt](../../benchmarks/streaming-shuffle-adapters-40gib-summary-2026-11-21.json)

| Workflow | Complete elapsed | Process CPU | Peak process RSS |
| --- | ---: | ---: | ---: |
| Chopper, opt-in terminal Uniform and 256-way merge ceiling | 551.724 s | 333.91 s | 71.78 MiB |
| qsvlite, file-staged external sort | 806.991 s | 489.33 s | 889.73 MiB |
| qsvlite, piped external sort and split | 710.569 s | 594.03 s | 893.64 MiB |
| DuckDB native COPY piped to qsvlite split | Engine allocation denied | — | — |

Each completed workflow has one full sample. All ran inside the same
hard 1 GiB WSL2/ext4 scope without swap. Chopper and DuckDB used a
256 MiB engine setting. qsvlite's sort used 64 MB per chunk. Each command
requested one worker and subprocesses could overlap. Independent
verification checked all 167,772,160 rows, unique IDs, nonidentity
order, exactly 20,971,520 rows per part and serialized caps outside
the timing window. The two qsvlite workflows produced identical
total output byte counts and the same exact quotas.

The piped qsvlite job first counted the input in 25.57 seconds. The
remaining pipeline took 684.87 seconds. Explicit input to split
avoided qsvlite's implicit stdin spool. The pipe eliminated three
explicit CSV intermediates, about 131.56 GiB of staged data writes.
GNU time filesystem input and output counters fell 42.82% and
60.44%. Cgroup file-cache refaults fell from 47.1 million to
22.6 million. Process CPU rose 21.40%. Output bytes, managed
intermediate bytes, scope refaults and filesystem counters have
different measurement boundaries.
[2 GiB adapter controls and implicit stdin failure](streaming-shuffle-adapters-at-2-gib-2026-11-21.md)

The DuckDB composition completed both verified 2 GiB pairs before
the larger qualification. At 40 GiB, the single native ordered COPY
still rejected a 30.5 MiB allocation with 226.7 MiB accounted under
its 256 MiB setting. The kernel recorded no cgroup OOM kill. The
failure matches the 256 MiB materialized adapter's reported
allocation size and available engine budget. The original adapter
also failed at 512 MiB. The engine admission failure persists after
removing the output table. The complete DuckDB elapsed at 40 GiB
remains unknown for this job scope.
[Original full-size comparison](uniform-balanced-cross-tool-at-40-gib-2026-11-21.md)
