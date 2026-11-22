## Auto Chromium thresholds and resource calibration (2026-11-21)

This calibration addresses actual resource settings and strategy selection.
It supports keeping the existing resource envelope for the measured jobs
and reviewing narrow strategy gates for Chromium. Neither experiment changes
the deployed engine, and no input needs a separate Analyze pass.
[Per-job observations and source identities](../../benchmarks/auto-chromium-thresholds-and-resource-calibration-2026-11-21-summary.json)

### Resource defaults and limits

1. **Memory.** Keep the current Auto headroom rule for the first implementation.
   It takes the smaller of 256 MiB and twice the free tracked workspace.
   It must still pass the record-size allowance and actual admission. The
   default 8 MiB record allowance requires at least 128 MiB. Lowering the
   nominal budget from input size alone would regress both tested shapes.
2. **Workers.** Hosted WASI uses one processing worker. Keep the existing native
   ceiling based on available processors, 64 MiB per worker and at most four.
   The native panel tests 1, 2 and 4 at 128 MiB. It compares one pipeline and two
   sizes, so it does not establish a generic replacement worker rule.
3. **Writers and temporary storage.** Keep the existing hosted writer path. The
   OPFS bridge's 64-handle cache is distinct from writer concurrency. Model
   concurrent writers from expected live fanout, buffer headroom and descriptor
   headroom only for routes that already support them. Use actual admission
   and runtime storage quota to enforce capacity. This study does not calibrate
   concurrent writer or storage reservation thresholds. Preserve explicit
   resource settings at every step.

| Chromium fixture | Request | Resolved MiB | Median seconds | Peak workspace MiB | Managed reads MiB | Managed writes MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| default-record-guard | 128 | 128 | 2.992 | 32.46 | 259.75 | 259.33 |
| default-record-guard | 256 | 256 | 2.453 | 60.83 | 177.66 | 177.26 |
| default-record-guard | auto | 256 | 2.517 | 60.83 | 177.63 | 177.26 |
| late-wide-resource | 32 | 32 | 2.131 | 7.60 | 157.34 | 156.23 |
| late-wide-resource | 64 | 64 | 2.140 | 14.57 | 157.44 | 156.19 |
| late-wide-resource | 128 | 128 | 1.997 | 28.54 | 135.50 | 134.24 |
| late-wide-resource | 256 | 256 | 1.766 | 46.09 | 106.74 | 105.55 |

A lower memory target had to reduce peak working reservations by at least 25%
while staying within 5% elapsed and 10% managed temporary traffic in each of
three matched rounds. Neither fixture met that rule. On the larger default-record
fixture, numeric 256 MiB and Auto use the same resource limit. The browser's
tracked 1 GiB ledger is per engine instance. These results supply neither RSS
nor multi-tab admission guarantees.

| Native Linux fixture, 128 MiB requested | Workers | Median seconds [range] | CPU seconds | Peak RSS MiB |
| --- | ---: | ---: | ---: | ---: |
| native-small | 1 | 0.137 [0.135, 0.141] | 0.02 | 6.70 |
| native-small | 2 | 0.137 [0.136, 0.137] | 0.02 | 6.70 |
| native-small | 4 | 0.137 [0.136, 0.137] | 0.03 | 6.65 |
| native-large | 1 | 2.105 [2.075, 2.143] | 1.55 | 37.75 |
| native-large | 2 | 2.073 [2.052, 2.102] | 1.54 | 37.77 |
| native-large | 4 | 2.074 [2.053, 2.077] | 1.56 | 37.78 |

### Strategy decisions after mandatory validation

- **Shuffle fusion.** A conservative first Chromium gate for implementation
  review is `rows >= 40000`, `decoded_field_bytes >= 4 MiB` and 2–8 actual root
  groups for plain-output Partition → Probabilistic Assign → Uniform with Auto
  grouping. Use the validated input total and the first Partition's actual group
  count just before retained execution. All four fresh positive cells clear
  the practical margin at the tested 32 and 256 MiB points. The small control
  benefited by less than 100 ms per pair. This is a guarded operating region.
  It does not establish a lower crossover or cover new devices, browser runtimes,
  storage types, grouping shapes or resource limits.
- **Indexed quota lookup.** Keep quota lookup out of hosted Auto. The fresh large job failed the frozen practical margin in at least one pair.
  Use the actual quota vector immediately after rounding and before the
  cursor transforms it. `sum(quota[i] * (i + 1))` counts linear cursor tests
  including the successful test, regardless of draw order. The 180,000-row
  screen at 64, 256 and 1,000 groups did not meet the practical margin. Claims
  for other weights, scopes and group counts need evidence.

| Fixture | Cohort | Existing median s | Candidate median s | Paired elapsed savings | Paired milliseconds saved | Gate |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| fusion-fit | Screen | 0.540 | 0.420 | +19.0% to +25.6% | +101 to +144 | Pass |
| fusion-balanced | Screen | 2.805 | 2.594 | +6.5% to +8.3% | +182 to +234 | Pass |
| fusion-skew | Screen | 3.232 | 2.634 | +17.6% to +19.0% | +567 to +618 | Pass |
| fusion-spill | Screen | 4.632 | 3.800 | +17.6% to +18.6% | +809 to +866 | Pass |
| quota-64 | Screen | 1.443 | 1.441 | -4.7% to +2.0% | -67 to +30 | Below margin |
| quota-256 | Screen | 3.990 | 3.950 | +0.7% to +3.2% | +29 to +131 | Below margin |
| quota-1000 | Screen | 13.880 | 13.709 | +0.5% to +1.7% | +69 to +235 | Below margin |
| below-floor | Fresh fusion | 0.318 | 0.267 | +15.8% to +19.4% | +50 to +62 | Below margin |
| near-floor-32 | Fresh fusion | 0.620 | 0.490 | +19.7% to +22.4% | +122 to +141 | Pass |
| near-floor-256 | Fresh fusion | 0.581 | 0.448 | +21.0% to +24.6% | +122 to +147 | Pass |
| balanced-default | Fresh fusion | 1.390 | 1.035 | +25.5% to +26.2% | +354 to +368 | Pass |
| late-wide-default | Fresh fusion | 1.137 | 0.906 | +17.3% to +24.7% | +190 to +300 | Pass |
| quota-high-256 | Larger quota screen | 17.519 | 16.346 | +5.4% to +7.3% | +931 to +1289 | Pass |
| quota-confirm-256 | Fresh quota | 17.855 | 16.677 | +4.4% to +7.3% | +783 to +1301 | Below margin |

Positive savings are relative to each paired existing Run. The predeclared
strategy margin is at least 5% and 100 ms faster in all three pairs. The
development data selected the tentative rule. Fresh labels indicate fixtures
frozen before measuring their arm timings. Browser comparisons used persistent
bundled Chromium under WSL2 and a disposable OPFS destination. Timed Run
includes worker setup, engine publication, export, marker readback and workspace
cleanup. It excludes fixture loading, verification and destination removal.
Arms alternate across rounds with uncontrolled caches. The browser profiling
adapter was active in both arms. CPU and RSS were measured only in the native
panel. Managed reads and writes and working reservations have separate scopes.

All 123 jobs verified output fields and IDs, applicable partition or quota
rules, strict encoded caps and workspace cleanup. Indexed tests checked exact
quotas and encounter order. Native seeded proof and prepared-spill typed retry
evidence remain scoped to the existing runtime contracts. Before activation,
qualify the WASI candidate under admission denial and cancellation and test
the integrated decision path without benchmark instrumentation. Existing
runtime and publication behavior continues to govern fallback.

### Replay

Use the Auto worktree at the recorded base and build from its recorded diff.
In a disposable source copy extend only the two strategy feature target guards
to WASI, then build the candidate with
`node scripts/build-browser.mjs --features chopper/experimental-probabilistic-shuffle-fusion,chopper/experimental-exact-quota-index`.
Both WASMs use the same hosted worker assets. Run the preserved screen, frozen
confirmation and resource drivers in the disposable directory. The compact
artifact pins the exact harnesses, resources, fixtures, builds and raw line
locations. Raw JSONL and replay sources are retained in local scratch.
