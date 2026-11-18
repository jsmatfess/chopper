## Hosted execution graph: 126 retained jobs accepted (2026-11-05)

**Decision: accept the recorded hosted graph workload/build/browser scope.**
The [final summary](../../evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830)
retains all 72 original jobs plus the 36-job and final 18-job precision studies.
Every one of the 126 jobs passed independent literal-field/ID/membership/order/
strict-cap/manifest/marker checks, with exact ordered artifacts across modes and
cohorts. All eight median/upper95 gates pass. The original unmet 72/108-job
reports below and every original slow observation remain available.

| Workload | Mode | Blocks | Median slowdown | Conditional upper95 | Gate |
| --- | --- | ---: | ---: | ---: | --- |
| Direct | Collapsed | 6 | -1.06% | +0.96% | Pass |
| Direct | Expanded | 6 | -1.26% | +0.75% | Pass |
| Resident/fused | Collapsed | 6 | -0.36% | +4.73% | Pass |
| Resident/fused | Expanded | 6 | -0.39% | +1.18% | Pass |
| External merge | Collapsed | 18 | +0.23% | +2.20% | Pass |
| External merge | Expanded | 18 | -0.05% | +1.30% | Pass |
| High cardinality | Collapsed | 12 | +0.23% | +3.47% | Pass |
| High cardinality | Expanded | 12 | -0.58% | +1.74% | Pass |

Slowdown is median(enabled)/median(disabled)-1; both separate gates require at
most 5%. Six/twelve-block uncertainty is exact paired resampling. Eighteen-block
results conservatively inflate the conditional Monte Carlo quantile, with the
fixed seed, one million resamples, Python/PRNG identities and numerical-error
bound retained. [Methodology](../../execution-graph-acceptance.md) distinguishes that
simulation bound from sampling error. Both precision studies were selected after
unmet gates; no population/tail or optional-stopping-adjusted confidence claim is
made. Data were retained rather than replaced or pooled across workloads.

The actual selected Chromium Headless Shell 156.0.8078.4 executable is attested
per block on Linux/WSL. Production WASM/worker/app hashes, fixtures, configuration,
seed, budgets, persistent OPFS context type, order, raw hashes/line anchors,
spread and failed attempts are recorded. The primary timer includes destination
export and marker completion; UI cleanup/poll completion is separate. This does
not establish native Windows/macOS performance, exhaustive compositions, RSS
caps or physical device throughput. Calibration/controls/diagnostic probes are
excluded from eligible performance samples and remain retained locally.

The [validation receipt](../../benchmarks/execution-graph-validation-summary-2026-11-05.json)
connects the same production assets to native/UI, hosted strategy/lifecycle,
resource-denial and test-free packaging checks. No algorithm, randomization,
working-budget, CSV cap or publication policy changed to obtain this result.
Deployment and origin pushes remain outside this local delivery.
