## Same-origin hosted Uniform Run overlap (2026-11-25)

Keep independent dispatch for the tested same-origin workload. Both modes
completed every Job. Taking the two Runs together finished the pair
6.423 seconds sooner at the paired median. Serial dispatch
missed the frozen latency and completion gates for further coordination work.
[Issue #86](https://github.com/jsmatfess/chopper/issues/86) ·
[Samples and identities](../../benchmarks/same-origin-uniform-run-overlap-2026-11-25.json)

| Pair | Simultaneous to both outputs, seconds | Serial to both outputs, seconds | Seconds saved by overlap |
| --- | ---: | ---: | ---: |
| 1 | 7.361 | 13.784 | +6.423 |
| 2 | 7.477 | 13.793 | +6.317 |
| 3 | 7.551 | 14.045 | +6.494 |

The two distinct pages share a fresh Chromium context and origin in each
arm. Each uses the pinned 800,000-row, 199,888,905-byte Uniform fixture with
1024 MiB, one worker and a strict 4 MiB CSV cap. Both pages select their input
and output before the clock. Serial dispatch starts the next Run after the
first reports usable output and retires. Simultaneous dispatch overlaps the
two normal Runs. The monotonic clock runs from dispatch until the later
publication and retirement. A separate pass verifies both manifests,
markers, all IDs and fields, file sizes and workspace cleanup.
[Matched single-Run fixture](guarded-hosted-uniform-retention-at-1024-mib-2026-11-25.md)

Each mode has an excluded warmup and three alternating pairs. Median time
to the first usable output is 7.476 seconds with
overlap and 6.906 seconds in serial. The runtime uses
bundled Chromium 156.0.8078.4 under ordinary WSL Linux headroom
and browser quota. Per-reactor tracked working allocations and logical OPFS
traffic are reported separately. A production cross-instance memory policy
needs a workload with a measured completion or resource benefit and its own
lifetime contract.
