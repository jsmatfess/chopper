## Bounded parallel profiling evaluation (2026-10-16)

Full-file profiling now has an opt-in native `experimental-parallel-profile`
experiment. Serial profiling remains the default. It batches selected-column
and tuple hashes for the existing cardinality sketches; ingestion logical
digests and operation execution do not use this worker path. WASI remains
serial even when the feature is enabled.

The CSV parser stays on the calling thread and produces complete validated
records, including quoted multiline fields. A private record source reuses
owned field slots and preallocated hash vectors, hashes them in a dedicated
bounded Rayon pool, and returns results in input order. Summary/value/preview
updates remain serial, preserving the profile JSON and exact cache observations.
The first record estimates slot count against a 2 MiB target, capped at 4,096
slots. A first-record estimate too small for sixteen rows per worker selects
serial storage before allocating slots or starting threads. Batch fill uses
current record content rather than retained capacity, stopping after the target
or slot limit; one oversized complete record can exceed the target.

Reservations cover slot/hash arrays, parser scratch, all live field/string
capacities and growth overlap. Retained capacity can exceed the target, as the
rare-wide measurements show, but remains subject to the unchanged local/shared
admission limits. Optional metadata or thread-pool construction failure selects
serial storage. A later typed local/shared admission denial releases the entire
partial scan and reopens the unchanged source for one serial retry. Corrupt CSV
and cancellation never trigger that retry. Cache installation still requires a
matching source identity. Each pool uses the existing worker policy and 1 MiB
thread stacks; native thread/runtime allocations remain in the separate runtime
headroom, outside the incomplete charged-capacity ledger.

The scalar `InputProfile::execution()` accessor reports hash workers, batches,
hashed rows, serial retry and successful-scan peak reservations. These diagnostics
are excluded from stable profile JSON. Cache copies retain the originating
scan's diagnostics; a retry's successful-scan peak excludes the discarded failed
scan. The allocation example accepts `job.json profile` for separate census runs.

### Final whole-file measurements

Warm, uncontrolled WSL storage; 300,000 records, 32 MiB explicit job budget,
one/four requested workers, five shapes and three alternating repetitions.
The final matrix contains 60 ordinary fresh profiles and 20 separate allocation
censuses. All compare complete profile JSON, excluding only elapsed time and
cache-hit state. Candidate four-worker censuses confirm that every row passed
through the hash batches without a serial retry; one-worker cases remain serial.
No build, test or other benchmark ran concurrently with these timing matrices.

Four-worker medians, seconds except RSS:

| Shape | Serial wall | Batches wall | Wall change | Serial / batches CPU | Serial / batches RSS, KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Narrow, low-cardinality values | 0.0923 | 0.0856 | −7.2% | 0.08 / 0.17 | 5,244 / 6,984 |
| 33 high-cardinality columns | 1.2497 | 0.6752 | −46.0% | 1.18 / 1.53 | 5,476 / 8,132 |
| Eight high-cardinality columns | 0.3484 | 0.1801 | −48.3% | 0.32 / 0.39 | 5,188 / 8,096 |
| Long Unicode text | 1.2346 | 0.6261 | −49.3% | 1.17 / 1.47 | 5,328 / 10,244 |
| Rare wide values and quoted newlines | 0.1176 | 0.1199 | +1.9% | 0.11 / 0.22 | 5,368 / 11,412 |

Raw artifacts contain repetition ranges, per-process GNU-time RSS/CPU and
filesystem-block counters. CPU has 0.01-second reporting precision; the short
cases do not support fine CPU comparisons. Filesystem counters do not establish
physical SSD traffic or controlled cache behavior.

Separate four-worker census observations:

| Shape | Batches | Serial / batches scan peak, bytes | Serial / batches requested allocation bytes |
| --- | ---: | ---: | ---: |
| Narrow | 74 | 117,527 / 1,727,043 | 106,013 / 1,755,023 |
| 33 columns | 421 | 247,836 / 2,342,340 | 451,090 / 3,533,427 |
| Eight columns | 85 | 146,711 / 2,597,693 | 181,642 / 2,950,548 |
| Long text | 206 | 236,154 / 3,796,997 | 368,801 / 5,488,778 |
| Rare wide | 74 | 505,696 / 6,408,679 | 759,558 / 6,800,988 |

Requested allocator bytes include profiling and its returned copy, exclude
native allocations outside Rust's global allocator, and are distinct from peak
live requested bytes, reserved capacity and RSS. Instrumented timings are not
used for speed claims. Multiple retained wide slots explain the rare-wide peak.

### Revisions, controls and decision

The initial 256-slot/512 KiB prototype improved many-column/long-text profiles
by 25.1%/18.7%, but cost 288% on narrow input and 1,586% on rare-wide input.
Repeated pool scheduling and counting a formerly wide slot's retained capacity
against each later batch made narrow batches too small. Larger batches and
content-based fill fix that particular failure while continuing to charge the
retained memory. The first larger-batch revision still took 0.594 s versus
0.034 s serially when a 120 KB Unicode field was the first data record: its
estimate selected tiny batches for the entire otherwise narrow file. The final
early serial choice reduces this to 0.0345 versus 0.0336 s. That control uses
100,000 records, three repetitions and four allocation censuses; diagnostics
confirm zero batch workers and no retry for the final first-wide path.

Twenty 1,000-record timing controls and twenty censuses preserve parity. These
single-point controls show about 1–2 ms extra startup cost on most small cases;
they do not establish a tiny-input speedup. Thirty alternating serial controls
compare the previous direct-loop build with the final feature-off build on the
five 300,000-row shapes: median changes range from −2.5% to +0.9%, with exact
profile parity. This control measures the default abstraction cost independently
of the candidate's four-worker gains.

Keep the experiment opt-in: large hash-heavy scans benefit, but extra CPU,
allocation traffic, retained capacity, tiny-input overhead and shape-dependent
regressions preclude unconditional default promotion. First-record sizing is a
conservative experiment, not a calibrated predictive resource plan. Compressed
and legacy-encoded profiling, broader worker/budget/pressure combinations and
other hosts/storage are not calibrated by this matrix. Independently reserved
group processing remains separate work; operation parsing, merge traversal,
output publication and logical-digest hashing are not newly parallelized here.

Four new tests cover full profile/tuple parity across quoted newlines and wide
rows, header/no-header/empty cases, single-worker/optional-denial fallback,
late local/shared denial with complete-scan retry and cache lifetime, corruption,
cancellation and reservation cleanup. The suites pass 199 default and 208
all-feature workspace tests, including 122 all-feature library tests. Formatting,
both all-target Clippy modes with warnings denied, and paired native/WASI release
builds pass. The candidate's final WASI bytes match the 24-contract tested build.
The native/WASI replay passes twelve fresh-profile comparisons, six browser
cache-copy comparisons and twelve complete-job output/metadata comparisons,
with four native workers and one browser worker. These single-repetition
controls establish parity, not browser A/B speedups. An initial harness attempt
passed four workers to browser preparation and stopped at its existing worker
validation; the corrected harness uses the supported browser setting.

Artifacts: [final native matrix](../../evidence-originals.md#sha256-0928680fb050f04f2dd429f86b05cb34be97236e74cb6fe81bffb7de466d64ee "Original: docs/benchmarks/parallel-profile-native-2026-10-16.jsonl"),
[tiny controls](../../evidence-originals.md#sha256-ea392f5073ed0c9f48cd638ea665b3cadb8d472c4fa49a496b09bb91314f64e5 "Original: docs/benchmarks/parallel-profile-tiny-2026-10-16.jsonl"),
[first-wide control](../../evidence-originals.md#sha256-c542be9447ecf01e4ecee9b189d056a57413bca213947a554d397ed22895e0d2 "Original: docs/benchmarks/parallel-profile-first-wide-2026-10-16.jsonl"),
[default serial control](../../evidence-originals.md#sha256-f91eee77e10b2a786d2a493cc156735abe83cac736d106929142dff84c3673c9 "Original: docs/benchmarks/parallel-profile-serial-control-2026-10-16.jsonl"),
[initial prototype](../../evidence-originals.md#sha256-26b9615339264dd12b80b1327334342ebed8e24583ef522d919f25c96c4091e9 "Original: docs/benchmarks/parallel-profile-initial-native-2026-10-16.jsonl"),
[larger-batch revision](../../evidence-originals.md#sha256-57e70b80e7f8a24ebced2bb0e15390b8fbbfc05f73c30348d8bc1367d7870601 "Original: docs/benchmarks/parallel-profile-revised-native-2026-10-16.jsonl"),
[revision first-wide failure](../../evidence-originals.md#sha256-4ef6118ebac7ea99ec03d5c0202f006e299ebb93b5b75eb68cacf8750e2870c6 "Original: docs/benchmarks/parallel-profile-revised-first-wide-2026-10-16.jsonl"),
[revision tiny controls](../../evidence-originals.md#sha256-209a08af374bc370257348c1ac7b45e7980c1d147dec4e3bcf930c1aa9cee986 "Original: docs/benchmarks/parallel-profile-revised-tiny-2026-10-16.jsonl"),
[revision serial controls](../../evidence-originals.md#sha256-42d1ceb8bd1796ac297cc3ce5a254ca65b3d27ec47c72d153bc0fe92a9b5b041 "Original: docs/benchmarks/parallel-profile-revised-serial-control-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-5c0eba89acc59a86dfd5427832e73d67f3798193a8b01c59d400e882c837d6c2 "Original: docs/benchmarks/parallel-profile-browser-2026-10-16.json"),
[initial harness rejection](../../evidence-originals.md#sha256-0a747b255049ff911539aaffeed23002b679be25d3c863b7edb637ef05bf128e "Original: docs/benchmarks/parallel-profile-initial-harness-2026-10-16.jsonl"),
[native/WASI profile, cache and job controls](../../evidence-originals.md#sha256-1bc28d06976fadf56ab4d6ac4f11f6b4eaa93a93dbd4075cc349a1f891e08718 "Original: docs/benchmarks/parallel-profile-engines-2026-10-16.jsonl"),
[summary and hashes](../../evidence-originals.md#sha256-6b0af382c7a4f45959cd63e1fa71547b4cc8ab56c74403aa74f5aa00d227cff9 "Original: docs/benchmarks/parallel-profile-summary-2026-10-16.json").

```sh
# Build/copy SERIAL and SERIAL_ALLOCATOR, then repeat with the feature enabled.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-parallel-profile
python3 scripts/benchmark-parallel-profile.py --baseline SERIAL --candidate PARALLEL \
  --baseline-allocator SERIAL_ALLOCATOR --candidate-allocator PARALLEL_ALLOCATOR \
  --rows 300000 --memory-mb 32 --workers 1 4 --repeats 3
# Small controls: --rows 1000 --repeats 1
# First-wide: --rows 100000 --repeats 3 --shapes first_wide
# Previous default vs final default: --skip-allocations --workers 1
bash scripts/build-browser.sh --features experimental-parallel-profile
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-profiling-budget.mjs SERIAL SERIAL.wasm 100000 1 --workers=4
```
