## Flexible shuffle and exact allocation ranges (2026-10-19)

Harnesses: [complete jobs](../../history/shuffle-harnesses-2026-11-16/benchmark-allocation-ranges.py), [correctness controls](../../history/shuffle-harnesses-2026-11-16/validate-allocation-ranges.py), [summary generation](../../../scripts/summarize-allocation-ranges.py). Run with `--help` for required inputs.

**Implemented, measured and opt-in** behind `experimental-flexible-allocation`.
For adjacent full shuffle → **unstratified** exact allocation under `flexible_v1`,
the candidate generates one parent permutation and emits consecutive ranges
using the existing largest-remainder quotas. It removes the shuffled intermediate
and assignment sort. Requested allocation order, named zero-quota outputs,
original logical indices/stage statistics and strict serialization/caps remain.
Explicit auto, uniform and Fisher–Yates strategies retain their own shuffle
implementation; buffer, stratified allocation and intervening operations are
excluded. No default or seeded-v1 rewrite changes.

The [joint-distribution argument](../../allocation-ranges-experiment.md) proves that
membership **and within-allocation order** agree under independent ideal
randomness. A five-ID 2/0/3 enumeration gives all 120 ordered outcomes equally:
one occurrence per range permutation versus ten among the original 1,200
permutation/assignment pairs. This is a construction proof under that model,
not a finite-PRNG uniformity claim. The candidate uses a separately derived
`independent-allocation-ranges-v1` domain at the original shuffle index and parent
lineage. It changes seeded results and records physical identity
`adjacent-full-shuffle-allocation-ranges-v1` with prepared-snapshot replay.

The range sink retains only one child and the existing charged quota scratch.
Auto admission still drops an unsuccessful resident attempt before replaying
external-capable keys; it never retries after partially emitting a child.
Logical shared-work counters appear once at the shuffle stage. Final audit
serialization borrows operations/statistics instead of building JSON copies of
potentially large allocation configurations. Native source/domain fixtures cover
counter and XOF sources with all cache sizes. A cancellation during terminal
serialization after 65,536 rows releases every shared grant and temporary file
without publishing output. Forty final CLI controls cover quoted/multiline/NUL
text, Unicode names, UTF-16/BOM, headerless data, gzip/ZIP, named empty parents,
zero quotas, downstream exact splits, strict caps and clean malformed/resource/
insufficient-row failures. Excluded plans require exact output parity.

### Complete native jobs

The final matrix alternates original shuffle→assignment, original
assignment→shuffle fusion, sequential flexible execution and the range plan:
192 timed jobs (eight fixtures × one/four workers × four plans × three
repetitions), plus 64 separate allocator/storage censuses. Resident cases use
256 MiB; other cases use 32 MiB. Inputs cover 120,003 resident rows, sixteen
sparse parents, 257 small parents, 32 extra columns, 180,003 × 512-byte external
payloads and one rare 1.8 MB row. Some fixtures add a downstream 50/50 exact
split; strict 50,000-row/20,000,000-byte caps apply throughout. Independent
verification checks every field/unique ID, original parent isolation, exact
quotas including zeros, configured group order and logical metadata. Matching
pinned plans must also retain exact bytes/metadata across repetitions/censuses.

One-worker medians in seconds:

| Case | Original shuffle→assign | Original assign→shuffle | Sequential flexible | Range candidate |
| --- | ---: | ---: | ---: | ---: |
| Resident auto | 0.2145 | 0.2040 | 0.2292 | 0.1512 |
| Resident uniform | 0.2077 | 0.2067 | 0.2354 | 0.1525 |
| Resident Fisher–Yates | 0.2084 | 0.2147 | 0.2345 | 0.1595 |
| Sixteen sparse parents | 0.3852 | 0.3485 | 0.4127 | 0.3358 |
| 257 small parents | 2.4370 | 2.5125 | 2.4878 | 2.4963 |
| Many columns/downstream split | 0.3568 | 0.3232 | 0.3974 | 0.3139 |
| External/downstream split | 0.8777 | 0.8187 | 0.9388 | 0.7398 |
| Rare-wide/downstream split | 0.1580 | 0.1276 | 0.1589 | 0.1292 |

The strongest resident improvements survive the explicit-uniform comparison,
which holds the shuffle algorithm fixed. Four-worker candidate medians are
0.1484/0.1512/0.1545 s for resident auto/uniform/Fisher–Yates and 0.7443 s for
external data. There is no universal gain: many-parent execution regresses
about 2% against original shuffle→assignment, and rare-wide cases trail the
existing assignment→shuffle fusion by roughly 1–5%. Full ranges, CPU, RSS and
reservation records remain in the raw data and summary; three warm repetitions
do not establish broader host/device gains.

Resident one-worker allocations fall from 240,714 (original) and 240,745
(sequential flexible) to 120,730. Peak live allocator requests remain about
24.6 MB and RSS about 30 MB. External allocations fall from 1,081,358 to
733,889; RSS stays near 13 MB. Faster execution does not imply a smaller
working-set or RSS bound.

### Publication-inclusive temporary traffic and space

Final allocator examples retain a counter observer through publication and
report `post_publication_diagnostics`, separate from analysis-through-READY
counters. Their allocation snapshot excludes measurement serialization and
holds the context until observation, delaying its final teardown; census wall
times are excluded from performance medians. Counters measure logical engine
file traffic, including publication reads, rather than physical disk I/O or
final destination writes. A separate 10 ms census sampler observes intermediate,
publication-staging and retained-output files, excluding original input/config/
time files and directory metadata. Sampled peaks are lower bounds, not exact
peaks or filesystem capacity guarantees.

For the external one-worker case (decimal MB):

| Plan | Temporary read | Temporary write | Charged temporary peak | Sampled combined file-byte peak |
| --- | ---: | ---: | ---: | ---: |
| Original shuffle→assign | 622.4 | 622.0 | 261.4 | 251.0 |
| Original assign→shuffle | 523.9 | 523.4 | 322.9 | 321.9 |
| Sequential flexible | 734.0 | 726.3 | 315.6 | 305.3 |
| Range candidate | 524.0 | 516.2 | 315.7 | 312.5 |

The candidate reduces temporary reads/writes about 29% against sequential
flexible execution, but its charged temporary peak exceeds original
shuffle→assignment by about 21%. Native/OPFS storage tradeoffs remain part of
the decision; these results do not justify changing defaults.

An additional 72 prototype jobs request input-only page-cache eviction using
`fsync` and `POSIX_FADV_DONTNEED` before timing resident/column/external cases,
one/four workers and three repetitions. Candidate external medians are
0.7662/0.7381 s versus original 0.8977/0.8829 s. Spill and host caches remain
uncontrolled. The reported filesystem input/output counters are zero on this
WSL environment even for these runs, so they establish neither successful
physical cache misses nor cold-device throughput. The older prototype census
and timing artifacts are retained separately from final borrowed-audit builds.

### Native/WASI replay and timing

The three-repetition browser matrix completes 84 alternating jobs over seven
cases, using both native binaries and both WASM plans. Matching pinned plans
require exact bytes/order/metadata; distribution-equivalent plans require
conservation, quotas and logical scopes instead. Median elapsed seconds:

| Case | Native sequential | Native candidate | WASI sequential | WASI candidate |
| --- | ---: | ---: | ---: | ---: |
| Auto | 0.2522 | 0.1880 | 4.1176 | 2.5436 |
| Uniform | 0.2465 | 0.1736 | 4.0264 | 2.4412 |
| Fisher–Yates | 0.2360 | 0.1597 | 2.4828 | 1.4969 |
| Partitioned parents | 0.3344 | 0.2724 | 4.0189 | 3.4952 |
| Downstream exact split | 0.3598 | 0.2941 | 7.1763 | 4.3776 |
| Excluded stratified control | 0.3464 | 0.3401 | 5.5999 | 5.6022 |
| Excluded balanced-barrier control | 0.2891 | 0.3007 | 5.1010 | 4.9451 |

Browser global cases improve about 38–40%, with a smaller 13% gain for
partitioned parents. The unchanged controls show ordinary timing variability.
Bridge profiles retain analyze/execute/export traffic separately: global auto
analysis writes fall from about 96.3 MB to 55.6 MB; destination stream writes
are outside those bridge counters. Browser clocks run from analyze/WASM restart
through complete/publication; verification and benchmark-owned output removal
are excluded. These are local Chromium/OPFS fixtures, not broader devices or
hosted-release certification.

Evidence: [final native jobs/censuses/storage samples](../../evidence-originals.md#sha256-fdbe248d77f07528b4fd038e7206c8f26440c26c8ce951f5a234410ee4b7a027 "Original: docs/benchmarks/allocation-ranges-final-native-2026-10-19.jsonl"),
[three-repetition native/WASI matrix](../../evidence-originals.md#sha256-cbabb9cc772a9736b75a6c5cd69f534933994a3d6075b4d522f504f990054eff "Original: docs/benchmarks/allocation-ranges-engines-2026-10-19.jsonl"),
[final text/failure controls](../../evidence-originals.md#sha256-315fef477aeabe40bf2997c344e4348b08af220541c669450a48d5b6a893a549 "Original: docs/benchmarks/allocation-ranges-final-controls-2026-10-19.jsonl"),
[input-eviction requests](../../evidence-originals.md#sha256-e79366d443290610c3cf35662779cbbd790ad6f34a4ce3277d0a77d8d57a8b10 "Original: docs/benchmarks/allocation-ranges-input-eviction-2026-10-19.jsonl"),
[initial prototype matrix](../../evidence-originals.md#sha256-cccb234f85a8ba996a6882ef8565c5718ffd052bdb3da4ede08d7a212050b34f "Original: docs/benchmarks/allocation-ranges-native-2026-10-18.jsonl"),
[initial publication/storage census](../../evidence-originals.md#sha256-a0fcf5b9f6a86dfc58d59ac4d7ec436331b8571c72eb965f1cf9fd28bc60df9e "Original: docs/benchmarks/allocation-ranges-resource-2026-10-19.jsonl"),
and [per-build ranges/resources/hashes](../../evidence-originals.md#sha256-8a2ad0627f0a60d66823bad50c520dd13e88161e70379058dad6f2205fabba36 "Original: docs/benchmarks/allocation-ranges-summary-2026-10-19.json").

A final 40-job replay of the borrowed-audit build additionally verifies the seven
counter-source cases and combined XOF Fisher–Yates/keys at all three cache sizes,
with exact native/WASI/cache parity for each matching plan. These one-repetition
replays are correctness controls, not additional speed estimates.
[Final replay](../../evidence-originals.md#sha256-e00ad512e51ecdb98e1cabe6d77c4c059486463661de679d4c2ae212857399d3 "Original: docs/benchmarks/allocation-ranges-final-engines-2026-10-19.jsonl").

Final validation for the allocation batch: 273 Rust workspace tests, 24 real-browser
contracts, UI tests/type checking, Clippy with warnings denied and formatting
checks pass. [Browser contracts](../../evidence-originals.md#sha256-106b8a7210a87f2101f76f40cae32fd27c62c1757fd0b4d704db74ac1bd6eb6c "Original: docs/benchmarks/allocation-ranges-browser-2026-10-19.json").
