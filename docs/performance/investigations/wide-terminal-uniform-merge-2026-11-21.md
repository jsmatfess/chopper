## Wide terminal Uniform merge (2026-11-21)

Retain the opt-in Linux experiment for unobserved terminal Uniform sorts.
The original 64-run ceiling materialized intermediate merges when the 8 GiB
fixture generated 197 runs. The experiment permits up to 256 runs when the
soft descriptor limit is at least 4,096 and the existing memory calculation
admits the readers. [Reviewed samples and build identities](../../benchmarks/wide-terminal-uniform-merge-summary-2026-11-21.json)

| Complete job | Control median [range] | Candidate median [range] |
| --- | ---: | ---: |
| 8 GiB Uniform Shuffle to eight Balanced parts | 104.929 [97.161–107.545] s | 83.323 [80.771–86.435] s |

Every measured pair favored the candidate. Median elapsed fell 20.59% and
CLI CPU fell 11.46%. Run sorting stayed near 2.62 seconds, and both builds
created 197 runs. Merges fell from four to one. Managed temporary writes fell
from 22,013,141,992 to 11,140,072,936 bytes, about 49.39%. Reads showed the
same reduction. The managed counters cover spill traffic and exclude raw
input reads, final CSV output and physical device I/O.

Peak CLI RSS rose from 73,368 to 87,552 KiB. Accounted working reservations
rose from 67,395,360 to 67,432,012 bytes. Both cgroups reached the 1 GiB
cap including file cache. Peak engine-managed temporary files rose from
69 to 200. Each active run can own its original file and independently
reopened reader. The temporary file counter does not measure open process
handles, and the descriptor threshold provides selection headroom without
reserving descriptors across concurrent jobs.

The three alternating pairs used one worker, a 256 MiB engine setting,
WSL2/ext4, a 1 GiB cgroup with swap disabled, and the same source with one
different feature flag. The timer ran through validation and final
publication. The independent output verifier ran outside the clock.
It checked all fields and unique source IDs, exact Balanced quotas, strict
serialized caps, metadata and cleanup on every run. These checks establish
conservation and pipeline correctness for the measured runs. Independent
random executions do not establish a shared permutation or statistical
uniformity. The implementation retains the existing key, comparator and
collision refinement.

The small preflight, the 512 MiB run under a 256-descriptor limit, and the
single 8 GiB diagnostic were separate from the paired cohort. The
low-descriptor run fell back to the existing hierarchy and passed output
verification. The full candidate diagnostic showed one merge before the
paired experiment launched. The warmup is excluded. Both predeclared
retention rules passed. This evidence covers one input shape and platform
and leaves default activation for a separate decision.
