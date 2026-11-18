## Hosted execution graph: first complete overhead gate unmet (2026-11-05)

**Decision: keep integrated acceptance incomplete.** All 72 matched hosted Runs
completed and passed independent CSV/ID/membership/order/cap/manifest/marker checks,
with identical ordered artifact hashes within each workload. Four of eight
performance cells remain unmet; no feature-completion or deployment claim follows.
The [compact result](../../evidence-originals.md#sha256-fd637745e75a20bb67867b422948b7b834dd3d3a1ce74d9089c55b3d70cbd30e)
retains every timing, physical raw JSONL line anchors, spread, exact conditional
bootstrap uncertainty, source/build/fixture/browser identities and local raw hashes.
The raw original and failed runner gate remain unchanged and locally retained.

Six blocks per workload use every three-mode order permutation once. The primary
clock spans public Run through the authoritative reply after destination export
and marker completion; public completion after cleanup/polling is separate.
Each block uses a fresh persistent OPFS profile, with the same production build,
input, configuration, seed, one worker, working/temporary ceilings and browser.
Selected Chromium Headless Shell 156.0.8078.4 is attested through its actual CDP
browser PID and executable SHA-256 on Linux/WSL. This is not native Windows,
physical-disk throughput or RSS evidence. The four workloads and fixed bounds
are defined in [acceptance](../../execution-graph-acceptance.md).

| Workload | Mode | Median slowdown | Exact paired-block upper 95% | Gate |
| --- | --- | ---: | ---: | --- |
| Direct | Collapsed | -1.06% | +0.96% | Pass |
| Direct | Expanded | -1.26% | +0.75% | Pass |
| Resident/fused | Collapsed | -0.36% | +4.73% | Pass |
| Resident/fused | Expanded | -0.39% | +1.18% | Pass |
| External merge | Collapsed | +2.61% | +22.39% | Unmet |
| External merge | Expanded | +8.05% | +21.82% | Unmet |
| High cardinality | Collapsed | +1.80% | +5.33% | Unmet |
| High cardinality | Expanded | +2.60% | +6.19% | Unmet |

Slowdown is median(enabled)/median(disabled)-1; the separate uncertainty gate
also requires at most 5%. The exact distribution resamples these six paired
blocks, with no population/tail guarantee. Timing variation and inconclusive
uncertainty are retained, never pooled or treated as passes. Calibration,
harness controls and the deliberately interrupted cohort 001 are excluded from
this fresh cohort, with their evidence retained and reasons recorded.

Two six-job external-merge diagnostics independently verify the same outputs.
The [page/process probe](../../benchmarks/execution-graph-diagnostic-001-summary-2026-11-05.json)
reproduces extra enabled elapsed/process CPU time, while page script/layout time
is small. The [worker-profile probe](../../benchmarks/execution-graph-diagnostic-002-summary-2026-11-05.json)
changes the timing direction in its first block and captures engine stacks from
about 0.06 seconds after Run begins. Storage bridge calls, including blocking
calls, dominate sampled stacks; stack samples are not exclusive CPU accounting.
Main/process CPU scopes include public completion/cleanup beyond the primary
export timer. Profiling and delayed engine termination change runtime conditions;
all these jobs are diagnostic and cannot establish acceptance. No production
optimization is justified by these probes alone. The [eight-job delivery-credit ablation](../../benchmarks/execution-graph-diagnostic-003-summary-2026-11-05.json)
verifies that held credit suppresses delivery after one message while preserving
the final six physical summaries. It does not reproduce a consistent delivery
penalty: held-credit runs take 45.19/44.89 seconds, normal collapsed 45.44/45.67,
expanded 45.44/45.06 and disabled 45.10/46.54. These are diagnostic timings,
not an acceptance pass. The probes do not establish a production hotspot.
The required overhead gate remains unmet.
