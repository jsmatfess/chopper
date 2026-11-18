## Windows retained-parent replay after Smart App Control was disabled (2026-10-21)

The [successful replay](../../evidence-originals.md#sha256-000cad4468a82bcd2e39bc16cde2faba44507d3dfa0a5c4eeb09be4b6534e14e "Original: docs/benchmarks/windows-retained-parent-audit-unblocked-2026-10-21.jsonl")
and [derived summary with source hashes/line references](../../evidence-originals.md#sha256-e855692bc82efc4293e6c565eb00ffba5153a6fdbb973f94edc9896cfcb40997 "Original: docs/benchmarks/windows-retained-parent-audit-unblocked-summary-2026-10-21.json")
retain all 12 complete jobs from the previously stopped two-cell experiment.
They reuse the exact pinned baseline/candidate binaries and 102-file build
inventory from the initial attempt below. These binaries predate the column
inspection change; the later measurement checkout inventory is recorded
separately. The initial failed artifact remains unchanged.

Each side has three alternating complete CLI jobs, including startup,
preparation, execution and native publication. Both cells use 33 columns, ten
cycling keys, `balanced(1) -> uniform -> partition(c0)`, the pinned seed,
32 MiB/four workers and a 128 MiB shared ceiling on Windows NTFS/NVMe.
Generation, exact-output verification and cleanup are outside timing. No other
build or test ran during measurements. Cache is warm/uncontrolled.

| Rows | Baseline median (min–max), seconds | Candidate median (min–max), seconds | Median change, candidate/baseline − 1 |
| --- | --- | --- | --- |
| 17,000 | 0.132955 (0.129771–0.164669) | 0.130946 (0.126268–0.283469) | −1.5% |
| 300,000 | 1.732212 (1.703718–1.800884) | 1.266692 (1.248359–1.426102) | −26.9% |

The smaller control remains near-flat with overlapping ranges and a retained
candidate outlier. Baseline has two resident sorts and no spill runs; candidate
has two runs and one merge, with slightly more logical temporary traffic.
At 300,000 rows both plans merge; candidate has 19 runs versus 17 but reduces
logical temporary reads from 530,144,812 to 329,966,955 bytes and writes from
451,247,609 to 251,069,752 bytes. Peak temporary storage falls from 319,448,585
to 251,012,881 bytes; peak workspace reservations fall from 8,602,146 to
7,902,830 bytes. Median process CPU falls from 1.515625 to 1.109375 seconds.
Process working-set observations are recorded separately from reservations and
are not a complete RSS bound or physical-device measurement.

All jobs pass exact CSV/order, fields, group membership, metadata, cap and
successful-cleanup verification. Every candidate job has one complete charged
audit record, no retry and no selector/calibration; baselines have no audit.
This compares fusion plus its audit, not isolated telemetry overhead. Three
samples establish neither tails nor a numeric selector. Physical I/O effects,
broader shape/runtime coverage and defaults remain open; historical ingestion
fusion cells are not pooled with this retained-parent stratum.
