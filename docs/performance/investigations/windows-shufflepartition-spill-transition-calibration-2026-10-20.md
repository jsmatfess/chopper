## Windows shuffle/partition spill-transition calibration (2026-10-20)

Decision: falsify a simple resident/external selector for exact shuffle/partition
using the retained Windows builds from the calibration below. The candidate is
still only `experimental-shuffle-partition`; baseline has no features. Stop after
three probe row counts and three repeated row counts, or the first parity/cleanup
failure. No default promotion, new algorithms or broad matrix is authorized by
this pass. No Rust builds/tests ran concurrently with these measurements.

The [six-job probe](../../evidence-originals.md#sha256-f1209026028cb764ce6af4c39c57b6954cbb68091df38cb1b0992c4c39ca5232 "Original: docs/benchmarks/windows-shuffle-partition-transition-probe-2026-10-20.jsonl")
tests 12,000/18,000/24,000 rows once per build, for plan discovery only. Both plans
are resident at 12,000; only fusion spills at 18,000; both spill at 24,000. These
single observations are excluded from the repeated timing estimates. The
[18-job repeated pass](../../evidence-originals.md#sha256-ad592bb2ae809e1729815fbdb8bb88425cff82965def6f1d6b5bf2c10082072d "Original: docs/benchmarks/windows-shuffle-partition-transition-native-2026-10-20.jsonl")
tests 15,000/17,000/20,000 rows with three matched pairs each, alternating
baseline/candidate, candidate/baseline, baseline/candidate. Complete CLI elapsed
time includes startup, preparation, execution and atomic publication; generation,
independent verification and cleanup remain outside the clock.

| Rows / raw measurement lines | Baseline median [min-max], seconds | Fusion median [min-max], seconds | Median time reduction | Runs / merges, baseline to fusion |
| --- | --- | --- | --- | --- |
| 15,000 / 3-8 | 0.0806 [0.0780-0.0878] | 0.0650 [0.0621-0.0657] | 19.4% | 0 / 0 to 0 / 0 |
| 17,000 / 11-16 | 0.0876 [0.0852-0.0916] | 0.0846 [0.0812-0.0866] | 3.4% | 0 / 0 to 2 / 1 |
| 20,000 / 19-24 | 0.1245 [0.1222-0.1292] | 0.0859 [0.0858-0.0951] | 31.0% | 2 / 1 to 2 / 1 |

Reduction is `100 * (1 - candidate median / baseline median)`. Ranges are observed
min/max, not confidence intervals. Keep the overlapping 17,000-row ranges as a
near-flat control rather than replacing them with the larger-cell gains. These
short jobs are startup/scheduling-sensitive; three repetitions establish neither
a tail estimate nor a precise optimum.

At the observed points, fusion's resident/spill boundary lies between 15,000 and
17,000 rows; baseline's lies between 18,000 (probe only) and 20,000. These are
brackets for one fixture/build/budget, not a monotonicity proof or row thresholds
for other shapes, parents, worker counts, pressure or runtimes. All use 33 columns,
ten cycling `c0` values, constant ordinary payloads and unique ordinal IDs.

| Resource median | 15,000 baseline to fusion | 17,000 baseline to fusion | 20,000 baseline to fusion |
| --- | --- | --- | --- |
| CPU seconds | 0.0781 to 0.0625 | 0.1094 to 0.0781 | 0.1094 to 0.0781 |
| Peak Windows working set, decimal MB | 16.39 to 16.69 | 18.38 to 17.35 | 18.45 to 17.35 |
| Peak charged workspace, decimal MB | 6.56 to 7.27 | 8.60 to 7.86 | 8.60 to 7.86 |
| Engine peak temporary data, decimal MB | 6.51 to 1.28 | 7.38 to 8.23 | 14.23 to 9.69 |
| Engine logical temporary reads / writes, decimal MB | 5.22 / 6.51 to 0 / 1.28 | 5.92 / 7.38 to 6.79 / 8.24 | 21.29 / 23.00 to 7.99 / 9.70 |

At 17,000 rows, fusion's extra spill increases peak temporary data about 11.6%
and logical reads/writes about 14.6%/11.8%, despite its slightly lower elapsed
median. At 15,000, fusion increases charged workspace about 10.9%. Memory
feasibility, live capacity and speed remain separate decisions. CPU counters have
15.625 ms granularity; working set is not an RSS cap. Directory sampling remains
a logical-size lower bound; raw process transfers include cached I/O, not physical
device traffic. Independent peaks must not be added as simultaneous usage.

Both passes use the same NTFS/NVMe host and retained binaries as the earlier
Windows calibration: 32 MiB, four workers, 2 MiB maximum record and seed
`external-comparison-v1`. Cache is warm/uncontrolled; physical I/O and allocation
traffic remain unknown. The harness now supports `--transition-rows` and
`--build-evidence`: it verifies binary hashes/features against environment line 1
of the explicitly supplied original artifact before starting jobs. The new
environment distinguishes reused build-source identities from current
measurement-source identities, and retains the original artifact hash/location,
revision/dirty status, current harness hashes and hardware. The source of the
original build is not inferred from the changed working tree. Fixture records
at lines 2/10/18 of the repeated pass retain hashes and byte sizes; its summaries
at 9/17/25 are derived, not observations.

Every job passes independent unique-ID/field conservation, partition membership,
row/byte metadata, exact CSV order/bytes and logical stage/digest comparisons.
The 100 MB per-CSV cap is checked but does not actively split these small outputs;
temp/staging cleanup passes. This pass adds no failure/cancellation, concurrent
admission, browser or physical-disk acceptance; retain the earlier controls and
their limits. Raw repeated SHA-256:
`ad592bb2ae809e1729815fbdb8bb88425cff82965def6f1d6b5bf2c10082072d`;
probe SHA-256:
`f1209026028cb764ce6af4c39c57b6954cbb68091df38cb1b0992c4c39ca5232`.

Decision: retain the opt-in candidate and the near-flat crossover control. A
resident/spill distinction alone cannot choose the faster whole job or predict
temporary-space savings. Stop this small calibration here; finer shape/pressure
rules require the planner observations and acceptance work already in
[TODO](../../../TODO.md), not a larger blind size sweep.

Reproduce with matching retained binaries and a new output path in PowerShell:

```powershell
$env:PYTHONUTF8 = '1'
python scripts/benchmark-windows.py --baseline scratch/windows-calibration/baseline.exe --candidate scratch/windows-calibration/candidate.exe --work-dir scratch/windows-calibration --hardware scratch/windows-calibration/hardware.json --build-evidence docs/benchmarks/windows-shuffle-partition-native-2026-10-20.jsonl --transition-rows 15000 17000 20000 --repeats 3 --output scratch/windows-calibration/new-transition-pass.jsonl
```

For plan discovery use `--transition-rows 12000 18000 24000 --repeats 1` and a
different output path. Binary/evidence mismatch rejects before creating the
artifact. The harness also verifies reuse rejects changed binary/feature
identities; these checks do not establish correctness of arbitrary build records.
