## Balanced scaling at 40 GiB (2026-11-21)

Three independent full qualifications reproduced the 8 GiB ranking on a
40 GiB synthetic CSV. With one worker and a 1 GiB Linux cgroup, qsvlite
remained about 1.91 times as fast as the opt-in Chopper build. Chopper used
39.4% less elapsed time than the ordered DuckDB adapter. Each 40 GiB
elapsed time was 5.02–5.05 times its respective 8 GiB median for five
times the input bytes. The 8 GiB median and 40 GiB single observation
remain separate. [Three-repetition 8 GiB comparison](current-balanced-cross-tool-at-8-gib-2026-11-21.md)

| Tool | 8 GiB elapsed median, three runs | 40 GiB qualification, one run | 40 GiB process CPU | 40 GiB peak process RSS |
| --- | ---: | ---: | ---: | ---: |
| Chopper, current opt-in profile | 37.76 s | 190.55 s | 122.63 s | 5.47 MiB |
| qsvlite 29.0.0 | 19.76 s | 99.53 s | 64.37 s | 15.57 MiB |
| DuckDB 2.0.0, materialized adapter | 62.63 s | 314.36 s | 261.43 s | 711.09 MiB |

The file is 167,772,160 fixed-width plain UTF-8 data rows plus the header.
The fixture generator writes sequential IDs and eight cycling keys. Each
job uses the existing tool config and adapter from the 8 GiB comparison,
with a 256 MiB engine setting for Chopper and DuckDB. qsvlite has no separate
engine memory setting. The input exceeds the cgroup capacity and fits in host
RAM. The cgroups reached 1 GiB including file cache, with swap disabled.
Their kernel counters are separate from the individual process RSS.

Each tool passed a separate small preflight and one full qualification.
The full oracle compared every output byte against ordered source blocks,
accounting for the tools' empty-field serialization. Each tool produced
eight consecutive 20,971,520-row parts and an actual CSV size within the
5600 MiB cap. Chopper independently enforces that cap during publication.
The timer includes tool startup and completed output and ends before the
verification. The verifier also checks Chopper's manifest and private-output
cleanup. [Qualification samples, fixture and run identities](../../benchmarks/balanced-40gib-qualification-summary-2026-11-21.json)

The empty-field spelling adds 335,544,320 bytes to Chopper and DuckDB
output relative to qsvlite on this fixture, about 0.78% of input size.
Chopper recorded 1,520 managed bytes written and zero managed bytes read
apart from raw input and final output. DuckDB's materialize-and-slice
results apply to that adapter and scope. Its storage behavior differs
from computing an exact quota and assigning each input record directly
to its final file.

The repeated 8 GiB cohort and the 40 GiB qualification both confirm the
qsvlite lead for this plain CSV workload. The 40 GiB run provides scale
evidence for the selected build and fixture. Device throughput, other CSV
shapes, other DuckDB query plans and run-to-run variability at this size
remain outside this comparison.
