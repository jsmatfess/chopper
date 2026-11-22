## Counted Partition and Balanced (2026-11-21)

The native opt-in path counts each Partition key before writing its exact
consecutive Balanced parts. It preserves tuple order, one-based part order,
encounter order inside each part, lineage, caps and both logical stage counts.
The feature uses the existing counted-source proof and bounded final writers.
It selects unobserved native Run with Auto grouping, plain UTF-8 input, plain
output, exactly two operations and a configured file ceiling within the writer
capacity. Job admission remains independent of Analyze. [Reviewed samples and
build identities](../../benchmarks/counted-partition-balanced-summary-2026-11-21.json)

The control used Auto routing and retained staging in the two-operation
pipeline. A verified 2 GiB diagnostic recorded about 7.52 GB of managed
temporary writes and 5.36 GB of reads. Its physical counters reported one
routed grouping and no sort runs. This qualified a decision on whether the
existing counted-input proof could avoid those stages.

The candidate uses a sorted admitted catalog of exact tuple key bytes and
counts. The number of keys is bounded by max_files divided by the requested
part count. The second pass advances a cursor per key and gives the first
remainder parts one extra row. It finalizes writers in canonical key and
part order. Header, total count, logical digest and file metadata must match
before directory publication. The second pass still checks the actual per-key
counts. Insufficient parent size, file-cap or byte-cap denial, input changes,
and cancellation discard private output. The path shares the ordinary Run
publication and source lifetime contracts.

| Complete job | Control median [range] | Candidate median [range] |
| --- | ---: | ---: |
| 2 GiB, 8 keys, 64 exact parts | 24.224 [23.623–24.327] s | 14.301 [11.543–15.252] s |

All three paired differences favored the candidate. The elapsed median fell
40.97%, CLI CPU fell 31.58%, peak CLI RSS fell 91.03% and accounted working
reservations fell 97.16%. Managed temporary writes went from 7,524,594,899 to
14,656 bytes and reads from 5,360,322,056 to zero. Both runs still write the
same final CSV bytes. Managed counters exclude raw source reads and physical
device I/O. The experiment meets both predeclared retention rules.

The pairs used one worker, a 256 MiB engine setting and a Linux 1 GiB cgroup
with swap disabled. The scope was WSL2/ext4 with uncontrolled host backing
cache. The timer includes launch through completed publication. Every pair
verified every row, exact output order, membership, quota, logical digest,
lineage, stage, 40 MiB actual CSV cap and cleanup. Preflight, warmup and the
initial diagnostic are excluded. Focused tests cover composite Unicode keys,
unequal quotas, an empty root and failure cleanup.

The initial built pair was unused after a review found repeated live descriptor
limit probes could change how the operation shape was classified after dispatch.
The measured pair captures the mode once before counting. Two subsequent
harness attempts failed before starting a CLI because of an incorrect script
path and a stale output directory. The successful run uses fresh directories.
The paired binaries share identical source and differ by the experiment flag.
The retained verification source extends test-only failure controls after the
timing freeze. Results apply to this workload and native Linux scope.
