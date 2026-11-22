## Integrated Balanced cross-tool at 8 GiB (2026-11-21)

The final opt-in build with the approved singleton fingerprint change
completed the 8 GiB exact split in a median of 38.87 seconds. It took
1.73 times as long as qsvlite and 41.9% less time than the chosen
DuckDB adapter. [Verified samples and provenance](../../benchmarks/balanced-integrated-8gib-cross-tool-summary-2026-11-21.json)

| Tool | Median elapsed [observed range] | Median process CPU | Median peak process RSS |
| --- | ---: | ---: | ---: |
| Chopper, integrated opt-in | 38.865 [37.165–39.517] s | 20.71 s | 5.56 MiB |
| qsvlite 29.0.0 | 22.530 [21.019–22.577] s | 12.62 s | 15.35 MiB |
| DuckDB 2.0.0, ordered materialized adapter | 66.843 [66.834–71.248] s | 52.37 s | 464.94 MiB |

Each tool used one worker inside a 1 GiB hard WSL2/ext4 cgroup with
swap disabled. Chopper and DuckDB used a 256 MiB engine setting.
The input had 33,554,432 rows. Three measured rounds rotated the order
after an excluded warmup per tool. The clock included launch through
process exit. An independent full output check verified each ordered
row and each 4,194,304-row quota after timing. It also checked the
1200 MiB bound for all serialized files and Chopper's manifest and
cleanup. Selecting eight groups on this divisible fixture gives
qsvlite's ceiling-based split the same quotas. [Earlier quota control](cross-tool-csv-split-and-shuffle-comparison-2026-11-18.md)

qsvlite sequentially splits without a CSV index. The DuckDB adapter
materializes all fields as VARCHAR and uses ordered COPY ranges.
Chopper and DuckDB emitted 8,657,043,624 CSV bytes. qsvlite emitted
67,108,864 fewer bytes because it writes empty fields without quotes,
a difference of 0.78% relative to input size. Each cgroup reached its
cap including file cache. Process RSS measures the CLI or adapter
rather than the whole cgroup.

The separate matched Chopper ablation isolates about 4.6 seconds of
process CPU per 8 GiB for the removed first-pass digest work on this
fixture. Chopper retains strict CSV and UTF-8 validation on both
passes and the second-pass digest, and checks the count and the
decoded header. Native atomic publication and strict byte caps also
remain part of its timed job. These competitor jobs do not implement
the same combination of contracts. The remaining gap does not
quantify the cost of any single retained feature. [Paired Chopper ablation](counted-balanced-first-pass-fingerprint-2026-11-21.md)
