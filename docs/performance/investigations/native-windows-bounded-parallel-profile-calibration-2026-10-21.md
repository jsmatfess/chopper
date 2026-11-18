## Native Windows bounded parallel profile calibration (2026-10-21)

The [fresh matched build record](../../evidence-originals.md#sha256-b808813ddd67adb5d5af2484ec15efb4bb96b399b37ac679dee6b5a7fad655f9 "Original: docs/benchmarks/profile-current-calibration-builds-2026-10-21.json")
and [raw experiment](../../evidence-originals.md#sha256-d3370d408cc770e3fedfaba74ba507555217656383293bfa0fcf5bdee6ce3c2a "Original: docs/benchmarks/parallel-profile-windows-current-2026-10-21.jsonl")
evaluate the many-column winner and rare-wide control from the historical profile
experiment on native Windows/NTFS/NVMe. The decision is whether bounded hash
batching benefits complete profiles without hiding shape/one-worker costs.
Baseline has no experiment features; candidate enables only
`experimental-parallel-profile`. Both CLI and allocation example have pinned
hashes and a common unchanged dirty-source inventory. The baseline/candidate CLI
hashes are `e7bc190cbee377189604a95bbf881ed893f48567d1646fb997cd65e0cf976cfe`
and `afcc916142a9bf6dbd8f7064eede64af806e85c80c2d6f3476501224cdaaae61`.

[benchmark-windows-profile.py](../../../scripts/benchmark-windows-profile.py) reuses
the historical fixtures and full stable-profile normalization and the Windows
Win32 process collector. It retains source/harness/fixture identities, hardware,
settings, every timed scan and separate allocation censuses. Two 150,000-row
shapes, one/four workers, 32 MiB job budgets and three alternating pairs per cell
yield 24 timed fresh-process profiles and eight separately instrumented censuses.
Every profile matches exactly except elapsed time/cache-hit state. Every scan
leaves no temporary data or output directory. No build, test or other benchmark
runs concurrently with these timing samples. Fixture generation/verification
touches cache; cache/background conditions remain warm/uncontrolled. Timings
cover complete CLI profiling, not preparation, output publication or export.
The run stops on any failure/parity/cleanup mismatch; none occurs.

The [derived summary](../../evidence-originals.md#sha256-eadc07cd8993749aaa52ec7079e6f6613b882823eaf18d11483709b3022e5a8b "Original: docs/benchmarks/parallel-profile-windows-current-2026-10-21-summary.json")
retains the source hash and physical measurement/census lines. At four workers,
33 high-cardinality columns have baseline median 0.627 seconds (0.618–0.628)
and candidate 0.291 (0.287–0.297), a 53.6% reduction relative to baseline median.
Median CPU rises from 0.609 to 0.688 seconds, process peak working set from
9.65 to 11.76 MB, and the separate successful-scan reservation census from
247,898 to 2,342,402 bytes. Requested allocation traffic rises from 410,053
to 3,509,498 bytes. These metrics have different scopes and are not added.

The rare-wide four-worker control instead increases from median 0.0682 seconds
(0.0672–0.0688) to 0.0705 (0.0685–0.0783), 3.4% higher with overlapping ranges.
Median CPU rises from 0.0625 to 0.1094 seconds and peak working set from 9.40
to 13.55 MB. Successful-scan peak reservations rise from 505,758 to 4,249,317
bytes; requested traffic rises from 740,158 to 4,624,243 bytes. Both candidate
four-worker censuses hash all 150,000 rows without serial retry. One-worker
controls remain serial and have overlapping elapsed ranges: many-column
baseline/candidate medians 0.624/0.638 seconds, rare-wide 0.0683/0.0686 seconds.
Full-profile parity includes column/tuple estimates, exact values and preview
metadata; this is not a claim of exact high-cardinality counts.

Decision: keep opt-in status. The many-column gain supports evaluating a bounded
shape-aware selector, while rare-wide CPU/live-capacity costs exclude unconditional
enablement. No numeric selector threshold, output-job speedup, physical SSD effect
or RSS cap is established. Win32 transfer counters include cached I/O; physical
I/O is unknown. Allocation instrumentation is excluded from timing; a census's
successful-scan peak is distinct from process working set and would exclude any
discarded failed scan (none is observed here). Native thread/runtime memory
remains outside the incomplete reservation ledger.

Reproduce from the root with fresh matched CLI/allocation builds and their JSON
build record, then `python scripts/benchmark-windows-profile.py --build-record
BUILD.json --work-dir SSD_DIRECTORY --hardware HARDWARE.json --output NEW.jsonl`.
The build record must bind both CLI and census artifacts to the matching source
inventory and expected feature sets. The script refuses existing output artifacts.
Additional shapes, pressure/concurrent owners and browser/device acceptance remain
in [TODO](../../../TODO.md), rather than creating another timing matrix by default.
