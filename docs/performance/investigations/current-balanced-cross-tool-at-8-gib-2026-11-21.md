## Current Balanced cross-tool at 8 GiB (2026-11-21)

The current opt-in Chopper profile took 37.76 seconds to split 8 GiB into
eight exact consecutive parts under a 1 GiB Linux cgroup. qsvlite 29.0.0
completed in 19.76 seconds and the DuckDB 2.0 materialize-and-slice adapter
in 62.63 seconds. Here Chopper used 1.91 times qsvlite's elapsed time and
39.7% less elapsed time than the DuckDB adapter. [Reviewed samples and
build identities](../../benchmarks/balanced-8gib-cross-tool-summary-2026-11-21.json)

| Tool | Complete median [observed range] | Median process CPU | Median peak process RSS |
| --- | ---: | ---: | ---: |
| Chopper, current opt-in profile | 37.762 [36.406–42.873] s | 25.19 s | 5.58 MiB |
| qsvlite 29.0.0 | 19.765 [17.961–21.777] s | 12.89 s | 16.53 MiB |
| DuckDB 2.0.0, materialized adapter | 62.626 [55.408–64.831] s | 51.94 s | 471.31 MiB |

Each tool passed a small and a full-size qualification. Those runs are
excluded. Three rotations place each tool once in each order position.
The fixture has 33,554,432 rows and exactly eight 4,194,304-row parts.
Every verification checks all fields, original row sequence, exact
quotas and the actual serialized size of each CSV. Chopper's manifest
and private-stage cleanup are also verified. The clock includes process
launch and output completion and excludes the independent oracle.

Every job used one worker and a hard 1 GiB cgroup with swap disabled.
Chopper and DuckDB used a 256 MiB engine setting. qsvlite has no separate
engine setting. All three cgroups reached the cap including file cache.
Process RSS measurements cover the individual CLI or adapter process.
The host was WSL2/ext4, and backing caches were uncontrolled. Input
eviction advice preceded each clock.

qsvlite uses a sequential split on this unindexed source, chosen here
because its count implementation can run in the hard scope. The DuckDB
adapter materializes all fields as strings, then writes ordered quota
ranges. The installed DuckDB extension and Python package sources are
bound in the runner inputs. These timings describe the chosen adapters
and fixture, including Chopper's two strict input passes. The measured
quanta are divisible by eight, which also makes qsvlite's ceiling-based
split produce the same quotas.

Chopper writes only 1,512 bytes and reads zero bytes of managed
temporary storage in all three runs. Its remaining complete-job gap
therefore persists after eliminating the row spool. Chopper and DuckDB
output 8,657,043,624 CSV bytes. qsvlite outputs 67,108,864 fewer bytes
because it writes each empty field without the two quote bytes.
This is about 0.78% of input size. Final output bytes and managed
temporary traffic have different scopes.

The roughly 18-second elapsed gap with qsvlite cannot be assigned to
any individual requirement from these timings. The chosen qsvlite
command does not supply Chopper's logical digest, source consistency
proof, strict UTF-8/CSV rejection, file cap enforcement, manifest and
native atomic publication. The earlier scoped digest measurements
and malformed-input probes quantify only parts of that difference.
The current CPU difference of 12.30 seconds per job motivates
attribution on the current build before a new optimization.
[Earlier requirement controls and pinned upstream source links](cross-tool-csv-split-and-shuffle-comparison-2026-11-18.md#requirements-avoidable-costs-and-rough-impact)
