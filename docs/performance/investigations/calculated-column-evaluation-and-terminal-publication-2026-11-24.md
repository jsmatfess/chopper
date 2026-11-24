## Calculated-column evaluation and terminal publication (2026-11-24)

[Issue #54](https://github.com/jsmatfess/chopper/issues/54) and the
[streaming baseline](calculated-column-streaming-baseline-2026-11-23.md)
established the complete-Run measurement. This investigation asks which costs
can be removed from calculated-column jobs while retaining the existing entry
points and performance of formula-free jobs. Start with text normalization,
numeric calculation, regex replacement and timestamp parsing from that baseline.
Scale the wide fixture from 18,000 to 180,000 rows and add a narrower 350,000-row
fixture to expose repeated evaluator work.

### Cost attribution

An instrumented build accumulates the wall time inside formula evaluation and
rendering. A second build samples the current thread's CPU clock on roughly one
row in 64 and subtracts separately sampled back-to-back clock overhead. Both
traversal measurements include the existing allocator admission checks.
These are diagnostic clocks with observer overhead. Neither measures a complete
optimization or physical disk throughput.

| Workload | Formula evaluation and rendering wall ms | Calculate traversal wall ms | Estimated formula and rendering thread CPU ms | Whole calculation stage thread CPU ms |
| --- | ---: | ---: | ---: | ---: |
| Wide text | 19 | 185 | 52 | 170 |
| Wide numeric | 58 | 237 | 95 | 213 |
| Wide regex | 100 | 272 | 129 | 242 |
| Wide timestamp | 92 | 273 | 140 | 262 |
| Narrow numeric | 117 | 250 | 145 | 218 |
| Narrow timestamp | 180 | 313 | 231 | 308 |

Each attribution cell is the median of two instrumented Runs with verified
output. The clock columns come from separate builds. The CPU estimate weights
observed sample costs by formula-call count. Differences between columns are
diagnostic, since the clocks, samples, instrumentation and trials differ.
Wide jobs have substantial traversal, row handling and I/O outside evaluation.
The narrow timestamp and numeric cells expose repeated scalar work. The evidence
supports testing materialization and typed reuse ahead of a vectorized evaluator.

### Candidate screens

- Single-pass number display avoids a second formatter invocation. Its narrow
  numeric paired median saved 3 ms, with mixed CPU results. The formula-free
  direct control lost 9 ms at the paired median, with six of seven pairs slower.
  The complete-job evidence did not support retaining it.
- In the first unobserved plain terminal test, writing directly to private
  publication saved 94 ms and 228 MB peak tracked temporary bytes for wide
  text. The fresh all-size Linux pass saved 92 ms on that workload but cost
  16 ms on narrow timestamp. The latter has a smaller serialized snapshot and
  more evaluator work. Limit the route to source files of at least 128 MiB and
  confirm on additional wide shapes.
- The isolated typed-dependency change stores scalars in topological order and
  saves reparsing formatted values when one formula reads another. It saved a
  paired median of 40 ms for narrow timestamp and 16 ms for narrow numeric.
  Formula-free control medians were within 2 ms of baseline. An earlier
  attempt used a common Cargo target and produced the same binary as the
  terminal trial. That attempt is ineligible. The isolated pass used its own
  target and distinct binary.
- The combined build saved a paired median of 93–117 ms on the wide terminal
  tests and 22–29 ms on the narrow dependency tests. Its 119.7 MB dependency-free
  text export, below the direct-output threshold, was 16 ms slower at the paired
  median. Confirmation put the cost at 9 ms. Specializing the dependency-free
  loop still lost 9 ms for that case, weakened the numeric gain and showed a
  possible grouped no-formula slowdown.

The byte-identical A/A control on the same 119.7 MB cell showed a 0.9 ms paired
median and a -14.0 to +13.7 ms range. On the grouped and direct no-formula cells
its ranges were -52.8 to +119.5 ms and -6.6 to +6.4 ms. These samples establish
a local comparison for noise.

The size-gated publication-only build cleared the below-threshold text cell
and saved 91–115 ms in the three wide terminal cells. Its no-formula direct
control lost 2.6 ms in 11 pairs and 0.7 ms in 20 additional pairs. Process CPU
medians rounded to zero difference. The directional elapsed result repeated,
so the no-formula gate withheld this artifact.

### Retained scope and tradeoff

Retain the combined build. Formula evaluation reuses already-computed scalars
when another calculated column references them on the same row. Strings still
borrow their rendered text. The output row keeps the existing canonical text
and type encoding. The native Linux Run selector sends unobserved plain exports
with calculated columns, no ordered operations, and at least 128 MiB of source
bytes through the existing private grouped output writer. Source intake finishes
and validates before calculation. The source-size check runs only for the
calculated terminal case and does one metadata lookup.

The hard gate applies to jobs without calculated columns. The combined artifact
cleared it in two batches. The grouping and direct controls retained their
stage statistics, spill and merge counts, peak tracked temporary bytes, output
lineage and CSV hashes. The positive wall deltas in the table are control
observations, since the implementation adds no per-row work to either route.

The below-threshold text cost is a measured tradeoff of the combined binary.
Its exact cause was not established. The repeated paired median cost was 9 ms
on a roughly 0.42-second export, compared with 93–117 ms saved per representative
wide export and 22–29 ms on the narrow grouped dependency cases. The extra
branch specialization missed the no-formula gate and was withheld. These results
support the combined build under the no-formula gate and favoring absolute time
saved. They do not establish a gain for every job with calculated columns.

### Complete-job measurements

The following deltas are the paired median and observed minimum and maximum in
milliseconds. Positive values are savings. All rows use the same baseline and
retained executable. Each primary cell has 11 pairs with opposite order in
successive pairs. The second control batch uses 15 pairs.

| Workload | Paired wall saving, ms [range] | Paired process CPU saving, ms [range] | Peak tracked temporary saving, MB |
| --- | ---: | ---: | ---: |
| Wide terminal regex | 117.0 [14.2, 196.7] | 120 [70, 180] | 232.9 |
| Wide terminal timestamp | 93.1 [-3.1, 148.4] | 100 [70, 150] | 233.1 |
| Wide terminal text | 93.0 [31.7, 136.7] | 100 [60, 160] | 228.0 |
| Narrow terminal timestamp | 30.2 [-8.9, 71.6] | 30 [10, 50] | 0 |
| Narrow grouped timestamp | 28.5 [6.7, 65.4] | 30 [10, 60] | 0 |
| Narrow grouped numeric | 21.9 [2.4, 66.4] | 20 [0, 60] | 0 |
| Wide grouped timestamp | 14.0 [-16.1, 78.5] | 10 [-50, 60] | 0 |
| Wide grouped regex | 4.3 [-18.0, 149.8] | 10 [-30, 130] | 0 |
| Small grouped numeric | 0.5 [-2.2, 24.3] | 0 [-10, 20] | 0 |
| Small terminal text | 0.0 [-8.8, 3.0] | 0 [-10, 10] | 0 |
| Below-threshold terminal text | -16.2 [-37.0, 53.0] | -10 [-30, 40] | 0 |
| Below-threshold text, confirmation | -9.2 [-31.4, 33.2] | -10 [-20, 10] | 0 |
| No-formula grouped | 42.2 [-78.6, 86.1] | 30 [-60, 80] | 0 |
| No-formula grouped, confirmation | 34.9 [-126.8, 76.1] | 20 [-70, 90] | 0 |
| No-formula direct | 5.6 [-6.9, 52.9] | 0 [-10, 20] | 0 |
| No-formula direct, confirmation | 4.5 [-6.4, 23.2] | 10 [0, 20] | 0 |

The grouped control produced 31 sort runs and one merge. The direct control
produced neither. Peak workspace and process RSS observations show no material
reduction. Peak tracked temporary bytes remove an encoded snapshot roughly
the size of the written CSV on wide terminal jobs. That is logical managed
temporary storage. GNU time filesystem counts stay in the raw records and
do not establish physical bytes written or SSD throughput.

### Verification and reproduction

The driver verifies each complete job's row count, ordered output file and
lineage, strict byte cap, and each CSV hash. The final driver also verifies
the logical stage statistics and checks spill counters and peak tracked
temporary bytes on formula-free jobs. Native coverage compares capped direct
exports with explicit snapshot preparation and exercises cleanup after a late
formula error and cancellation just before publication. Existing native
tests cover forward references, typed values, nulls and error propagation.
The Chromium formula journey exercises a typed numeric or null dependency
through preview and a complete saved-job Run.

The timed environment is one x86-64 Linux process under WSL2, AMD Ryzen 7
5800X, pinned to CPU 6, with one Chopper worker and a warm ext4 cache. The jobs
use explicit sort grouping, 32 or 256 MiB budgets, and an 8 MiB output cap.
The wide scope is 226.9–232.5 MB of input with 140,000–180,000 rows. The narrow
scope is 32.7 MB with 350,000 rows. Wall timing covers launch through native
publication and stdout collection. CPU uses the process user plus system clock
from GNU time, recorded to hundredths of a second. Native Windows and WASI
performance are outside this sample.

The [paired driver](../../../scripts/benchmark-calculated-column-optimization.py)
uses immutable CLIs and generated fixtures. The base was a dirty local source
snapshot, stored separately from the working checkout. The [evidence projection](../../benchmarks/calculated-column-optimization-summary-2026-11-24.json)
keeps pairing, resource measurements, raw hashes and line numbers, build and
patch identities, and the source tree ID. Full original records, binaries,
runner receipts and absolute build paths remain in local session custody.
The [retained implementation patch](../../benchmarks/calculated-column-opt-integrated-2026-11-24.patch)
applies to that snapshot. Use separate Cargo target directories for each
source variant. Select a fresh output file and working directory.

```sh
taskset -c 6 python3 scripts/benchmark-calculated-column-optimization.py measure \
  --baseline /path/to/chopper-baseline --candidate /path/to/chopper-integrated \
  --work-dir /path/to/work-dir --output /path/to/paired.jsonl --repeats 11 \
  --case terminal-text-wide --case terminal-pattern-wide --case terminal-timestamp-wide \
  --case timestamp-narrow --case control-grouped --case control-direct
python3 scripts/benchmark-calculated-column-optimization.py verify /path/to/paired.jsonl
```
