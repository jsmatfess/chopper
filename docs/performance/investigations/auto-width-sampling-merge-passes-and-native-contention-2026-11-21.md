## Auto width sampling merge passes and native contention (2026-11-21)

This follow-up to the [multi-GiB calibration](browser-auto-calibration-at-multiple-gib-2026-11-21.md)
tests four bounded width samples, the memory crossover for an extra merge
pass, and native worker and writer choices alongside another job. The
outcomes are a hosted width-sampling rule, a Linux merge-target rule based
on applicable completed Analyze, and evidence for keeping the current
native worker policy and bounded-writer feature gate.

### Hosted widths and Analyze

[Prototype](../../benchmarks/auto-followup-2026-11-21-browser-windows.jsonl) ·
[Integrated engine](../../benchmarks/auto-followup-2026-11-21-browser-integrated.jsonl) ·
[Skewed composed holdout](../../benchmarks/auto-followup-2026-11-21-browser-composed.jsonl)

The prototype took four 64 KiB ranges at 25%, 50%, 75% and 87.5% of the file.
It ignored partial boundary lines and declined quote-containing windows,
malformed UTF-8 and inconsistent field counts. It compared two complete
jobs per arm in Chromium with same-origin OPFS. The extra reads occur inside
the timing boundary. The integrated check reran those fixtures and a
narrower out-of-range control. The size-only arm cleared the preview by
reselecting the same file. On these fixtures, prior Auto reached the same
1024 MiB tier with or without the eight-row preview.

| Fixture | Starting tier Run | Integrated sampled Run | Analyze + Run | Spill runs before / after sampling |
| --- | ---: | ---: | ---: | ---: |
| Stable wide rows | 5.21 s | 5.23 s | 5.89 s | 0 / 0 |
| Wide head, narrow tail | 15.56 s | 7.01 s | 8.24 s | 2 / 0 |
| Narrow middle, wide ends | 12.58 s | 5.87 s | 6.97 s | 2 / 0 |
| Quoted multiline fields | 5.09 s | 5.10 s | 6.00 s | 0 / 0 |

Values are two-run medians. Analyze and Run both republished and verified
every result row, exact input fields, grouping where relevant, serialized
byte caps, completion and cleanup. Standalone shuffle remains uniform.
The output verifier is outside the clock. The independent prototype
recorded about 3–4 ms for sampling the narrow-tail fixture.

The held-out skewed Partition → Shuffle took 12.70 s at the starting
tier, 6.02 s with sampling, and 7.30 s with Analyze + Run. These are
two-round medians through publication and cleanup.

The planner uses matching preview facts. It applies the width refinement
only to eligible plain UTF-8 CSV shuffles targeting 1024 MiB. Estimated
footprint above 256 MiB and through 528 MiB can raise the request to 2048 MiB.
The resource ledger can retain the 1024 MiB starting tier when 2048 MiB
lacks headroom. Tests cover a lower field count and quoted window rejection,
as well as insufficient capacity and explicit settings.

A bounded offset probe can miss a narrow band or mistake text inside a
quoted field for data. It supplies a budget estimate and Run parses the
current CSV. The out-of-range control still spilled and kept its starting
tier. The successful probes had lower elapsed time than Analyze + Run.
The controls did not establish an automatic Analyze trigger. Analyze
remains user-initiated.

### Merge-pass crossover

[Linux 4 GiB tiers](../../benchmarks/auto-followup-2026-11-21-linux-merge.jsonl) ·
[Linux 2 GiB control](../../benchmarks/auto-followup-2026-11-21-linux-merge-small.jsonl) ·
[Linux denser source](../../benchmarks/auto-followup-2026-11-21-linux-merge-dense.jsonl) ·
[Linux Auto sizing](../../benchmarks/auto-followup-2026-11-21-linux-merge-planned.jsonl) ·
[Linux Auto small control](../../benchmarks/auto-followup-2026-11-21-linux-merge-small-planned.jsonl) ·
[Linux Auto dense control](../../benchmarks/auto-followup-2026-11-21-linux-merge-dense-planned.jsonl) ·
[Chromium constrained tiers](../../benchmarks/auto-followup-2026-11-21-browser-merge-pass.jsonl)

The 4.01 GiB Linux/WSL standalone shuffle had 73 runs and two merges at
256 MiB. At 384 MiB it had 50 runs and one merge. At 512 MiB it had 37 runs
and still needed one merge. The respective complete-job medians were
32.94, 26.83 and 26.41 seconds in two reversed rounds. Relative to 256 MiB,
384 MiB removed about 3.8 GiB each of logical temporary reads and writes.
Peak working reservations rose from about 64 to 96 MiB. The 2 GiB Linux
control made one merge at either tier and had mixed elapsed results.
The Chromium 2 GiB control demonstrated the same pass mechanism at a
different crossover. A fixed 128 MiB made two merges and a fixed 256 MiB
made one. Both complete pairs favored 256 MiB. This validates the existing
headroom-driven default as the starting point for that hosted shape.

The denser 3.67 GiB Linux source likewise dropped from
75 initial runs and two merges to
51 runs and one merge. Its two-round
complete-job medians were 62.30 s at 256 MiB and 41.44 s at 384 MiB.
The integrated Auto replay used 384 MiB with a matching Analyze on the
4.01 GiB input and removed the intermediate merge in both rounds. Run
started at 256 MiB without Analyze. The 2 GiB integrated control kept
256 MiB with or without Analyze. The denser integrated control also
selected 384 MiB and reduced two merges to one. One integrated series ran under more
host load than the initial fixed-tier screen. Compare arms within each
series. Fresh Analyze took roughly two seconds on the large Linux
fixture and the complete sequence was faster in those controlled arms.
Existing Analyze can drive this rule. General prediction of a profitable
fresh scan remains uncalibrated.

The Linux rule is limited to standalone uniform shuffle with uncompressed
output and automatic grouping. It requires current Analyze observations,
average decoded row widths from 384 to 2048 bytes, no decoded row over
1 MiB, and an estimated packed footprint above 4 GiB and through 5 GiB.
The shape and footprint bands limit extrapolation beyond the measured
crossover. The target is 384 MiB, subject to available capacity, and the
256 MiB baseline remains the fallback. Numeric settings take precedence.

### Worker and writer contention

[Linux workers](../../benchmarks/auto-followup-2026-11-21-linux-workers.jsonl) ·
[Linux workers, four CPUs](../../benchmarks/auto-followup-2026-11-21-linux-workers-four-cpus.jsonl) ·
[Windows workers](../../benchmarks/auto-followup-2026-11-21-windows-workers.jsonl)

[Linux 96-group writers](../../benchmarks/auto-followup-2026-11-21-linux-writers.jsonl) ·
[Linux descriptor control](../../benchmarks/auto-followup-2026-11-21-linux-descriptor-control.jsonl) ·
[Linux 12-group writers](../../benchmarks/auto-followup-2026-11-21-linux-writer-low.jsonl)

[Windows 96-group writers](../../benchmarks/auto-followup-2026-11-21-windows-writers.jsonl) ·
[Windows 12-group writers](../../benchmarks/auto-followup-2026-11-21-windows-writer-low.jsonl)

The native worker matrix used Partition → Uniform Shuffle with gzip output,
one job at a time and two identical concurrent jobs released from a
barrier. It compared Auto with one, two and four workers. On the
unrestricted host, Auto resolved four on Linux and three on Windows.
Both selections compared favorably to fixed one and two for total elapsed.
The fixed four and Auto comparisons overlapped at the observed spread.
The Linux four-CPU affinity control also favored keeping Auto's cap.
These tested settings support retaining automatic worker selection.

The default Linux 96-group plain partition pair finished in 2.02–2.12 s.
The bounded-writer opt-in took 1.52 s in both rounds and opened 96 slots
per job. On Windows the 96-group case kept the standard route and one
observed slot because the Windows planner uses a conservative 16-slot ceiling. A Linux
128-descriptor control likewise stayed on the standard route. At 12
groups, the opt-in selected bounded writers on both operating systems.
Those cases support the existing feature gate and modeled descriptor
ceiling, with actual allocation and file limits enforced independently.

### Coverage and replay

Each CLI arm includes planning, the actual Run, publication and workspace
cleanup. Fresh Analyze time is reported separately and included in makespan
where requested. Independent verification checks row conservation, field
contents, strict caps, partition membership, and per-key order when the
job preserves it. Linux GNU time reports process CPU and peak RSS. Native
Windows uses Win32 CPU, peak working set and process I/O counters.
Managed temporary traffic and working reservations are separate from
these metrics. Concurrent makespan is elapsed from first start to last
finish. We ran the Windows tools and data on NTFS in a separate checkout.
All runs shared one physical host. Some independent experiments and validation
overlapped, so the spread is part of the evidence. The initial Windows harness
smoke attempt needed its scratch parent created before the executable could run.

[Build provenance](../../benchmarks/auto-followup-2026-11-21-build-inputs.json) ·
[Browser resource harness](../../../scripts/benchmark-browser-auto-resources.mjs) ·
[Disk-backed Chromium harness](../../../scripts/benchmark-auto-multigib.mjs) ·
[Native harness](../../../scripts/benchmark-auto-contention.py)

Browser and native records pin the executable and relevant harness hashes.
The native provenance file captures build inputs separately from the running
checkout, which was being edited for the integrated passes. Pair timers
stop before the fixture verification. Sampled browser-process RSS can
include shared pages. No timings establish physical device throughput.


```sh
node scripts/benchmark-browser-auto-resources.mjs preview-windows
node scripts/benchmark-browser-auto-resources.mjs preview-windows-integrated
node scripts/benchmark-browser-auto-resources.mjs preview-windows-composed
mkdir -p scratch/merge-pass-browser
node scripts/benchmark-auto-multigib.mjs merge-pass ui/dist scratch/merge-pass-browser
python3 scripts/benchmark-auto-contention.py merge scratch/merge-control target/release/chopper
python3 scripts/benchmark-auto-contention.py merge scratch/merge-planned target/release/chopper --planned
python3 scripts/benchmark-auto-contention.py workers scratch/worker-control target/release/chopper
```

The writer panels accept a separately built
`experimental-bounded-final-partition` binary via `--writers-binary`.
Use the Windows dispatch workflow to measure the same CLI panels on NTFS.
