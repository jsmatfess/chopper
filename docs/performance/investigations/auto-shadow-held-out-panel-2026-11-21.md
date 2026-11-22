## Auto shadow held-out panel (2026-11-21)

The resource report and input-bound advisory reuse are ready for review. The
two strategy rules remain in shadow. Both Linux feature opt-ins remain
available under their existing eligibility. The held-out results do not
calibrate a default crossover.
[Per-job measurements and build identities](../../benchmarks/auto-shadow-held-out-summary-2026-11-21.json)

### Complete jobs

The prior executable was built at `cf0c1e4`. Shadow and opt-in executables
use the Auto branch. All jobs use one worker and a 32 MiB working budget.
Two rounds reverse arm order on the same WSL2 Linux filesystem and host.
Timing starts before the CLI invocation and ends after publication and report
serialization. Analyze arms include the separate full scan, sidecar read and
Run. Fixture construction and independent verification are outside the clock.
Cache state and host pressure are uncontrolled. Competing jobs share the host
and storage with independently admitted process budgets.

| Workload | Prior | Shadow | Analyze + shadow | Opt-in | Analyze + opt-in |
| --- | ---: | ---: | ---: | ---: | ---: |
| Small fusion | 0.120 [0.117–0.123] | 0.121 [0.117–0.124] | 0.122 [0.121–0.123] | 0.117 [0.116–0.118] | 0.124 [0.122–0.126] |
| Larger-than-budget correlated keys | 1.004 [0.986–1.022] | 1.016 [1.007–1.024] | 1.119 [1.086–1.152] | 0.918 [0.909–0.927] | 1.001 [0.999–1.002] |
| Same records in gzip | 0.993 [0.985–1.001] | 0.996 [0.988–1.003] | 1.083 [1.069–1.097] | 0.914 [0.900–0.928] | 0.993 [0.981–1.005] |
| Late 300 KB field | 0.454 [0.452–0.457] | 0.449 [0.447–0.452] | 0.490 [0.489–0.490] | 0.420 [0.417–0.424] | 0.460 [0.459–0.461] |
| Small, 1,000 exact groups | 4.365 [4.353–4.376] | 4.390 [4.380–4.401] | 4.463 [4.404–4.521] | 4.446 [4.429–4.462] | 4.450 [4.349–4.552] |
| 1.05 million rows, 1,000 exact groups | 5.586 [5.502–5.669] | 5.490 [5.482–5.498] | 5.673 [5.672–5.675] | 5.419 [5.411–5.427] | 5.694 [5.642–5.746] |
| Competing correlated and high-fanout jobs, pair makespan | 5.651 [5.593–5.709] | 5.788 [5.625–5.952] | 5.783 [5.731–5.835] | 5.470 [5.452–5.487] | 5.648 [5.629–5.666] |

Values are median seconds with the two-run range. All 80 jobs published and
passed independent ID and field conservation, partition lineage or exact quotas
and encounter order, encoded caps and temporary cleanup. The
probabilistic run checks permitted allocations and that zero-weight outputs contain no rows.
Existing feature contract tests cover retry, typed denial, cancellation and
output equivalence under controlled entropy.

| Run arm | CPU seconds | Peak RSS MiB | Peak workspace reservations MiB | Managed temp reads MiB | Managed temp writes MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correlated, shadow | 0.71 | 14.4 | 8.72 | 386.3 | 384.5 |
| Correlated, fusion | 0.61 | 14.2 | 8.72 | 258.4 | 257.1 |
| Gzip, shadow | 0.69 | 14.6 | 9.30 | 386.3 | 384.5 |
| Gzip, fusion | 0.60 | 14.5 | 9.30 | 258.5 | 257.1 |
| High fanout, shadow | 1.44 | 12.4 | 5.89 | 295.0 | 284.6 |
| High fanout, indexed | 1.32 | 12.4 | 5.89 | 295.0 | 284.6 |

Resources are per-Run medians. The artifact records Analyze CPU and RSS and the
prepublication process-reservation figures separately. The branch's workspace
and managed temporary measurements extend through engine publication. The
prior executable's diagnostic traffic ends before publication, so its traffic
is excluded from the resource comparison. Managed traffic is logical I/O.
The opt-ins reported zero fusion retries in this panel.

### Decisions

- **Probabilistic shuffle fusion.** The plain and gzip correlated jobs are
  recommended after Analyze and after Run validation. The cheap container-size
  rule misses both. Fusion improves the measured correlated jobs and reduces
  their managed temporary traffic. Late-wide also benefits in these measurements
  while the rule declines it. Keep the opt-in and calibrate the rule using facts
  from mandatory ingestion. An extra Analyze scan consumes much of the measured
  saving. The earlier evidence covers a larger, one-worker Linux cell.
  [2 GiB fusion decision](../decisions/probabilistic-shuffle-fusion-at-2-gib-2026-11-21.json)
- **Exact quota index.** The rule recommends the 1.05 million-row jobs and
  declines the small 1,000-group case. Indexing changes lookup CPU while output
  publication and managed temporary traffic still carry substantial work.
  Neither group count nor row count supplies a calibrated elapsed-time crossover.
  Keep the opt-in and measure more group counts and row widths before choosing a
  cutoff. [2 GiB quota decision](../decisions/indexed-exact-quota-lookup-at-2-gib-2026-11-21.json)
- **Runtime coverage.** Chromium verifies the same-source Analyze-to-Run handoff,
  existing Run paths and destination completion. These measurements apply only
  to the recorded WSL2 environment. Native Windows and browser timing need
  separate calibration. Terminal direct publication and archived resident
  buckets remain outside the selector.

### Reproduction

Build the prior executable at the recorded base and build this checkout twice,
with the default feature set and with
`experimental-probabilistic-shuffle-fusion,experimental-exact-quota-index`.
Use a temporary directory on the checkout filesystem and run
`python3 scripts/benchmark-auto-shadow.py --baseline PRIOR --shadow SHADOW --opt-in OPT_IN --record LOCAL_JSON`.
The synthetic fixtures, executable hashes and raw attempt identities are
recorded in the summary. An initial verifier read allocation names from the
partition-lineage field and was excluded. The verified tmpfs passes are retained
locally as separate scopes.
