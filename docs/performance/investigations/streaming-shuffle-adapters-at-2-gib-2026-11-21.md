## Streaming shuffle adapters at 2 GiB (2026-11-21)

A single native DuckDB `COPY` into qsvlite's splitter reduced median
complete-job elapsed from 26.359 to 14.426 seconds against the original
DuckDB materialize-and-slice adapter. A piped qsvlite workflow reduced
median elapsed from 39.339 to 36.881 seconds against its file-staged
workflow. [Matched runs and failures](../../benchmarks/streaming-shuffle-adapters-2gib-summary-2026-11-21.json)

| Workflow | Median elapsed [range] | Median process CPU |
| --- | ---: | ---: |
| qsvlite with keyed, sorted, and final intermediate CSV files | 39.339 [37.911–40.768] s | 22.78 s |
| qsvlite with explicit piped split | 36.881 [36.756–37.006] s | 27.38 s |
| DuckDB materialized and sliced | 26.359 [23.675–29.043] s | 19.69 s |
| DuckDB native COPY piped to qsvlite split | 14.426 [13.499–15.353] s | 18.77 s |

Each tool comparison uses two opposite-order 2 GiB complete-job pairs.
All runs use a hard 1 GiB WSL2/ext4 cgroup with swap disabled and one
requested worker per command. Subprocesses can overlap. DuckDB uses
a 256 MiB engine setting and qsvlite's sort uses 64 MB per chunk.
The clock includes discovering the exact count, sorting and closing
output files. The independent oracle verifies every field, unique ID
conservation, eight exact quotas, nonidentity order and actual cap
compliance outside the clock. The source is line-safe and its count
is divisible by eight. Small preflights are excluded.

qsvlite saves 6.25% elapsed, below its declared 10% time advance.
Its process CPU rises 20.19%. GNU time filesystem input and output
counters fall 48.93% and 60.44%. File-cache refaults in the cgroup
fall 56.96%. The pipe removes three explicit intermediate CSV files.
The DuckDB and qsvlite composition saves 45.27% elapsed and 4.67%
total process CPU. Its GNU time filesystem output counter falls
67.78%. The qsvlite serializer writes empty fields with two fewer
bytes per row than the DuckDB-only output, about 0.78% of input size.
Counters and output bytes describe different measurement scopes.

The initial qsvlite pipe used implicit stdin for `split --size`. That
command stages stdin to a temporary file before parsing. Here `/tmp`
was tmpfs. The kernel reported about 926 MiB of shmem at the scope OOM.
The explicit `/dev/stdin` path first failed qsvlite's extension check.
The verified variant applies qsvlite's documented extension override
only to that pipe input. qsvlite still parses the CSV in the split
stage. [Pinned split source](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/split.rs#L186-L212)

DuckDB's separate `COPY PARTITION_BY` prototype passed small tests
with quoted multiline input and uneven exact quotas. It failed a
1 MiB allocation at its 256 MiB engine limit in the 2 GiB execution.
The measured alternative uses one native ordered CSV writer, with a
count query followed by `ORDER BY random()` feeding qsvlite's split.
These results support separately qualifying the larger streaming
compositions. [DuckDB streaming merge design](https://duckdb.org/2025/09/24/sorting-again#merging)
