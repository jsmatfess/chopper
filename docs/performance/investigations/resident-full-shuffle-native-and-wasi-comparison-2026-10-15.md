## Resident full-shuffle native and WASI comparison, 2026-10-15

The development engine harness now has explicit global/four-group resident
Fisher–Yates cases alongside random-key sorting. `--interleave-cases` alternates
selected algorithms/cases, reverses their order each repetition, and also reverses
engine order. Historical commands retain case-by-case ordering. The new Fisher–
Yates/grouped cases are opt-in so a large default fixture does not unexpectedly
require resident-only execution. Environment records include binary, WASM and
harness hashes and the scheduling policy.

The [128-row pilot](../../evidence-originals.md#sha256-955af59bebadae6c7457d4befa894c437d4ce313c79c95798a4c18b3b877bfbe "Original: docs/benchmarks/resident-browser-tiny-2026-10-15.jsonl") and
[100,000-row comparison](../../evidence-originals.md#sha256-ebfd6ac1531948eb008580aab0801ca967da7b92efc47aa26a68692f413a9291 "Original: docs/benchmarks/resident-browser-2026-10-15.jsonl") contain
**48 verified timed complete jobs** altogether: four fields, 256-byte generated
payloads, 256 MiB, one native worker and single-worker Chromium/WASI, global
shuffle and balanced-into-four then per-group shuffle, three repetitions. The
four-group jobs contain 32 or 25,000 rows per group. Every job is actually resident:
zero spill runs/merges, with one/four resident sort or Fisher–Yates calls as
expected. Native verification independently checks every unique ID, exact
conservation, per-file rows/bytes and balanced input-range isolation. Repetitions
and WASI exports match exact bytes/order, names/lineage, stage metadata and logical
digests **within the same algorithm/version**. Different algorithms intentionally
produce different seeded permutations and are not compared for exact output order.

| Complete job | Native median seconds | WASI median seconds |
| --- | ---: | ---: |
| 128 rows, global | 0.012 → 0.013 | 0.110 → 0.109 |
| 128 rows, four groups | 0.020 → 0.023 | 0.159 → 0.173 |
| 100,000 rows, global | 0.160 → 0.167 | 1.161 → 1.203 |
| 100,000 rows, four groups | 0.193 → 0.190 | 2.617 → 2.718 |

Arrows here mean **random-key v1 → Fisher–Yates v1**, not before/after builds.
The pilot is dominated by initialization/publication costs. These larger complete
jobs show no consistent Fisher–Yates advantage; retain existing defaults and the
explicit versioned choice. The raw records include full timing samples, stage
and loop wall times, peak reservations and logical temporary/OPFS I/O. Sort-loop
time excludes random-key generation while Fisher–Yates loop time includes RNG
draws, so the loop counters alone are not a fair complete-algorithm comparison.
The [derived summary](../../evidence-originals.md#sha256-9d9fe923e9a2f1ca3e0b8283fec500bbd3ec7a82db599c7cae0c1a639e0239a6 "Original: docs/benchmarks/resident-browser-summary-2026-10-15.json") records
all medians, ranges and loop/reservation summaries with source-file hashes. For
100,000-row WASI jobs, global ranges are **1.142–1.326 / 1.152–1.284** seconds
(random-key / Fisher–Yates); grouped ranges are **2.572–2.657 / 2.717–2.834**.
These are three-sample ranges, not confidence intervals. This follow-up does not
capture process CPU/allocation/RSS on either runtime; the broader native resident
censuses remain in the preceding native comparison. Physical-device I/O is not
established. This is one four-field shape on warm WSL/OPFS, with broader resident
device/scale calibration and automatic-policy prerequisites still open.

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-field-stream-after/chopper \
  100000 3 uniform256,fisher256,grouped_uniform256,grouped_fisher256 256 \
  --interleave-cases
# Same command with 128 rows for the tiny pilot.
```
