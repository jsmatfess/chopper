## External shuffle native/browser follow-up, 2026-10-15

SSDs are the target storage; slow-storage optimization is not a priority. This
follow-up runs the existing merge and opt-in prefix candidates from identical
sources on native Linux/WSL and Chromium/WASI with OPFS. The browser crate now
forwards `experimental-distribution`; default browser builds still use merge
sorting. No shuffle algorithm, seeded identity or default changed.

### Method and parity

`scripts/benchmark-external-browser.mjs` uses ascending unique IDs with duplicate
payloads, narrow/two-field and 33-field fixtures, and a rare-wide variant with
one 1.8 MB field. The working budget is 32 MiB with one worker and seed
`external-comparison-v1`. Each 100,000-row shape runs global shuffle,
balanced(4) → per-group shuffle, shuffle → balanced(4), and
shuffle → balanced(4) → per-group shuffle → balanced(3). Three repetitions
alternate the order of the four native/browser merge/prefix variants.

Native outputs are independently checked for exact unique-ID conservation,
original field text, grouped source-range isolation, header/row/CSV-byte counts,
and expected output counts. Every variant must then match complete CSV SHA-256
hashes, filenames, lineage, stage statistics and logical digests. Object keys are
canonicalized before comparing native and WASI JSON. Every completed job must
release its algorithm workspace reservations. The generated fields contain no
CSV metacharacters; the fixture-specific native validator is not a general CSV
parser. Existing Rust tests retain general CSV/corruption coverage.

Times include complete ingestion, preparation, serialization and publication/export.
Browser startup, initial defaults and fixture loading are excluded, while per-job
WASM restart is included. Verification and output cleanup are outside timing.
Native time includes CLI process startup. Browser time includes asynchronous API
polling and OPFS export. These runtime differences limit native/browser speed
comparisons; candidate/baseline ratios within each runtime are the relevant
experiment. Storage is warm and uncontrolled on the local WSL virtual filesystem
and browser OPFS. Physical host-device topology and cache state are not established.
Logical temporary traffic, reservations and peak disk bytes come from engine
counters. Native GNU time also records CPU seconds, peak RSS and filesystem block
counts; those block counts do not establish physical SSD throughput. Browser
CPU/allocation/RSS and physical-device I/O measurements are unavailable. Browser
storage-call profiling is enabled equally for both variants.

### Complete-job results

All **144 measured jobs** (three shapes × four pipelines × four variants × three
repetitions) match exact v1 output and metadata. Chromium is 156.0.8078.4 on the
AMD Ryzen AI 9 HX 370 host. Median complete-job seconds:

| Shape | Pipeline | Native merge | Native prefix | Browser merge | Browser prefix |
| --- | --- | ---: | ---: | ---: | ---: |
| narrow | global | 0.091 | 0.101 | 0.573 | 2.232 |
| narrow | grouped | 0.085 | 0.087 | 0.609 | 0.615 |
| narrow | balanced | 0.093 | 0.109 | 0.586 | 2.133 |
| narrow | multistage | 0.153 | 0.168 | 0.952 | 2.553 |
| columns | global | 0.331 | 0.430 | 2.033 | 8.933 |
| columns | grouped | 0.370 | 0.454 | 3.649 | 10.431 |
| columns | balanced | 0.330 | 0.429 | 2.076 | 8.688 |
| columns | multistage | 0.543 | 0.718 | 4.676 | 18.048 |
| rare wide | global | 0.343 | 0.468 | 2.225 | 11.754 |
| rare wide | grouped | 0.371 | 0.463 | 3.712 | 10.539 |
| rare wide | balanced | 0.336 | 0.475 | 2.168 | 11.514 |
| rare wide | multistage | 0.557 | 0.765 | 4.849 | 21.251 |

[Raw repeated measurements](../../evidence-originals.md#sha256-c905f00e9ac611b2452671b8e3bc6f39d38279b9843ebc8054c11c67c37ea986 "Original: docs/benchmarks/external-browser-2026-10-15.jsonl") include
every sample/range, build hashes, CPU/RSS for native, engine timings, peak
reservations, temporary traffic/file counts and disk-space peaks. The narrow
grouped jobs stay resident on both runtimes; their small difference does not
measure the external candidate. On the remaining cases prefix/merge median
ratios are **1.10–1.41 native** and **2.68–5.31 browser**. These measurements
support retaining merge sorting as the native/browser default. They do not show
that every external distribution implementation must regress.

The native/browser descriptor sizes differ: the narrow global baseline produces
three runs on native and two on WASI at the same stated budget. Output parity
therefore also crosses those spill boundaries. Rare-wide prefix jobs reach the
four-level bound. Logical I/O and file-operation counts, especially across the
synchronous WASI/OPFS bridge, remain relevant even when target storage is SSD.
In the first rare-wide global repetition, analyze-phase bridge create calls rise
from 10 to 506 and write calls from 601 to 6,067. Logical bytes written rise from
48.7 MB to 97.0 MB; measured write-call wall time rises from 0.916 s to 8.278 s.
This attributes much of that sample's regression to storage-call work without
claiming physical-device throughput or CPU attribution.

No controlled cache-state or physical-device throughput claim is made. One fixed
seed is used; these performance/parity fixtures are not statistical evidence of
uniformity.

### Larger multi-level validation

A separate **1,300,000-row rare-wide global shuffle** runs all four variants once
with the same budget and seed. All conserve unique IDs and match exact v1 CSV
bytes/order, stages, lineage and logical digests. These are single observations,
not repeated timing estimates:

| Variant | Whole-job seconds | Sort runs | Merge operations | Distribution passes / depth / fallbacks | Peak temporary MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Native merge | 4.973 | 74 | 2 | 0 / 0 / 0 | 797.7 |
| Native prefix | 6.518 | 120 | 13 | 64 / 3 / 17 | 565.4 |
| Browser merge | 43.219 | 69 | 2 | 0 / 0 / 0 | 855.7 |
| Browser prefix | 178.763 | 109 | 13 | 64 / 3 / 17 | 565.2 |

The baseline exceeds its merge fan-in and compacts runs hierarchically. Both
prefix variants reach the global 64-pass cap and use bounded merge fallback.
This provides browser runtime evidence for that bound and parity across
multi-level external execution. Prefix reduces peak temporary space on this
fixture while regressing complete-job time. Peak space is not cumulative I/O.
The [large-fixture artifact](../../evidence-originals.md#sha256-0d314bfd4e679389c3ebcc7f5689cb8609405019ca8658a300cc3f4e10c14489 "Original: docs/benchmarks/external-browser-multilevel-2026-10-15.jsonl")
contains resource counters and the exact shared fingerprint. Broader multi-level
grouped/downstream jobs, controlled SSD cache conditions, native worker scaling
on these browser-comparison fixtures, and physical I/O remain open. Per-group
allocation accounting/selection and statistical diagnostics are separate TODOs.

Validation for this follow-up: 89 all-feature workspace tests (including localhost
interfaces), TypeScript source and benchmark-harness checks, UI tests, JavaScript
syntax/changed-file whitespace checks, and native/WASI release builds passed.
There were also 16 small smoke jobs across the four pipelines/variants. The
full 21-contract browser suite was not rerun; this pass records the complete-job
browser comparisons above.

### Reproduction

Save identical-source native release binaries with and without
`--features experimental-distribution`. Build the corresponding browser variants:

```sh
bash scripts/build-browser.sh
cp ui/dist/engine.wasm /tmp/merge.wasm
bash scripts/build-browser.sh --features experimental-distribution
cp ui/dist/engine.wasm /tmp/prefix.wasm
cp /tmp/merge.wasm ui/dist/engine.wasm
node scripts/build-hosted.mjs
node scripts/benchmark-external-browser.mjs /path/to/native-merge /path/to/native-prefix /tmp/merge.wasm /tmp/prefix.wasm 100000 3
node scripts/benchmark-external-browser.mjs /path/to/native-merge /path/to/native-prefix /tmp/merge.wasm /tmp/prefix.wasm 1300000 1 rare_wide global
```

The harness restores the original WASM and any existing benchmark artifacts on
normal completion or failure, closes Chromium and removes its local fixture tree.
It uses a temporary localhost-only test page, which must not ship in production.
This host required staging `libnspr4`, `libnss3` and `libasound2t64` packages under
`/tmp/chopper-browser-libs`, setting
`LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`, and
running the local browser/server outside the restricted loopback sandbox.
