## Explicit Sort and Zstandard input Balanced (2026-11-21)

Two independent native experiments cover explicit Partition Sort and Balanced
split of Zstandard input. Both ran on WSL2/ext4 with a 256 MiB engine setting, one
worker, a 1 GiB cgroup and swap disabled. The complete-job clock includes
validation and publication. The independent output oracle is outside the clock.
Each comparison contains three alternating pairs with a separate preflight and
excluded warmup. Input cache eviction was requested before each run. Host backing
cache was uncontrolled. [Reviewed samples and build identities](../../benchmarks/pipeline-sorting-source-codec-summary-2026-11-21.json)

| Workload | Control median [range] | Candidate median [range] | Decision |
| --- | ---: | ---: | --- |
| Explicit Partition Sort, 2 GiB and 8 keys | 21.418 [21.168–23.072] s | 22.369 [21.368–22.470] s | Remove serial-sort experiment |
| Balanced, 2 GiB decoded varied Zstandard input | 15.201 [14.099–16.054] s | 11.492 [11.142–12.394] s | Retain two-pass input path as opt-in |

### Explicit Partition Sort

The explicit Sort diagnostic completed in 21.870 seconds. It made 50 spill runs
and streamed one final merge. Managed temporary writes and reads were each
about 2.71 GB. Sorting spill buffers took 1.853 seconds. The separate CPU
profile identified Rayon sort stacks, which motivated a one-worker experiment
with the existing serial sorter. Heap comparison, pop and push contributed
about 5% of identifiable user CPU samples. The profile has no attribution
for time blocked in storage or the kernel.

The two builds used the same comparator, framing and merge. The candidate
changed only key sorting on a native one-worker pool. Complete median elapsed
increased 4.44%, with mixed pair directions. Sort-phase time increased from
1.917 to 2.090 seconds. CPU changed from 12.45 to 12.42 seconds, RSS was roughly
flat and managed traffic matched. The change missed both retention criteria
and was removed. The initial preflight failed because the fixture copy skipped
the CSV header. A corrected preflight and all large jobs verified every field,
ID, group, encounter order, lineage, stage statistics, CSV cap and cleanup.

### Counted Balanced with Zstandard input

The varied fixture contains 8,388,608 records and 2,147,483,669 decoded bytes.
Its level-3 checksummed Zstandard stream occupies 1,525,888,995 bytes. The
control decodes once and uses a retained Dataset. The experimental native
selector uses two independent, sequential checked decoder lifetimes and the
existing counted Balanced path. Both passes check decoded UTF-8 CSV, and the
header, row count, logical digest and source metadata are checked before
publication. Every measured job verified eight exact consecutive quotas, all
field values and serialized caps.

Every pair improved. Median elapsed fell 24.40%, which met the speed rule.
CLI CPU increased 19.88%, so the run missed the separate resource-only rule.
CLI RSS changed from 8,672 to 8,640 KiB and peak working reservations stayed
near 2.92 MB. Chopper recorded a reduction from 2,650,801,679 to 1,496 managed
temporary bytes written and from 2,650,800,183 to zero managed bytes read.
The final CSV bytes still have to be emitted. Compressed source reads and
physical device traffic are outside these managed-spool counters.

A focused native test compares the decoded output with prepared execution
and checks truncation and checksum failure cleanup. An initial fixture
generation attempt failed before writing data because of an incorrect Python
keyword. The fresh attempt verified decompression against the original
input SHA-256. The retained path is native-only and experimental. Timing
evidence covers this one input shape and Linux memory scope.
