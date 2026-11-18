## Per-group reservation accounting, 2026-10-15

The next WSL-compatible shuffle step tightens the existing per-group sorter;
physical SSD/cache calibration remains deferred. Random-key v1 and explicit
Fisher–Yates v1 retain their algorithms, domains, RNG draws and output order.
There is no automatic algorithm substitution or new resource setting.

Retained sort/Fisher–Yates rows now charge their actual packed/owned payload
capacities, variable-key allocations, actual descriptor vector capacity, and
resident state (including Fisher–Yates RNG). Descriptor growth reserves both old
and new arrays before allocation, then releases the old-array allowance. Growth
is capped near the ceiling rather than reallocating for every additional row.
These reservations replace the former two-descriptors-per-row estimate on these
paths; buffer shuffling and routing retain their existing conservative estimates.
The retained storage/growth ceiling stays at one quarter of `memory_mb`.
Comparison sorting remains in place; its in-place unstable implementation has no
row-proportional heap scratch. The opt-in radix implementation keeps its separate
scratch reservation and comparison fallback.

A denied row reservation causes the random-key sorter to spill and retry with an
empty buffer. If there is insufficient workspace even for fallback, preparation
fails cleanly. Explicit Fisher–Yates still fails rather than switching algorithms.
Spill writers and intermediate merge output writers now reserve their 64 KiB
buffers while retained rows or merge readers are live, releasing the reservation
before later merges. Existing merge reader/head/winning-row reservations remain.
The half-budget shared ledger is still an algorithm-workspace ledger: parser and
dataset input buffers, transient conversions, retained run catalogs, Rayon/runtime
stacks, allocator overhead and simultaneous prepared jobs are not fully charged.
This is a delivered accounting step, not completed host-aware resource planning
or a guarantee that the complete group working set stays below an RSS limit.

Correctness coverage:

- Exact retained capacity at one byte below, at, and above the ceiling; owned
  string/vector spare capacity and RNG/state accounting; descriptor growth peak.
- Forced equal random keys through resident/external group selection, preserving
  v1 collision refinement and exact stable row IDs.
- Shared reservation pressure that forces spilling, and insufficient workspace
  that fails without leaked reservations or temporary files.
- One 18,000-row group plus eight three-row groups, duplicate 600-byte payloads,
  retained grouping followed by shuffle and balanced output. Native 32/128 MiB
  and one/four workers compare exact CSV order, stage metadata and logical digest,
  with unique-ID conservation and group isolation. Small groups stay resident;
  only the large group spills at 32 MiB. The browser repeats the budget comparison.
- Existing oversized-row/group, malformed-spill, strict-cap, cancellation,
  publication, seeded-fixture and multi-level collision tests remain passing.

The browser routing-fallback fixture now introduces new keys after 32,000 of
40,000 rows so it crosses the first spill under capacity-based WASI accounting.
Its assertions for bucket reuse, single fallback and exact output parity remain.

Validation: 94 default workspace tests and 26 combined experimental-feature
library tests passed; formatting, workspace Clippy with warnings denied,
TypeScript checking and release native/WASI builds passed. All 22 Chromium
contracts passed with staged `LD_LIBRARY_PATH` dependencies and the installed
Playwright browser. [Browser record](../../evidence-originals.md#sha256-1dcc66c7da1f901710c236662360bf4057c4ffd31970e2cb70b665d12403a9f7 "Original: docs/benchmarks/group-budget-browser-2026-10-15.json").

The [native A/B record](../../evidence-originals.md#sha256-1f9d17538e150123fac198341086e1d10cf2847861f56f5fac871d8be98242fa "Original: docs/benchmarks/group-budget-native-2026-10-15.jsonl") contains
48 alternating timed complete jobs and 16 allocation-census jobs: 300,000 rows,
33 columns, three repetitions, one/four workers, resident random-key shuffle,
resident Fisher–Yates, grouped spill shuffle and adaptive partition routing.
Fingerprints compare exact output bytes/order, names, lineage, stages and logical
digests. The baseline binaries were copied before this accounting change from
the existing working tree; SHA-256 identities are in the record. The final timing
pass ran after test/build processes finished, on warm uncontrolled WSL storage.
Physical SSD I/O and controlled cache conditions are not established.

| Complete job | Workers | Median seconds before → after | Observed seconds before / after | Median CPU seconds before → after | Median RSS MiB before → after |
| --- | ---: | ---: | --- | ---: | ---: |
| resident | 1 | 0.744 → 0.749 | 0.740–0.749 / 0.738–0.780 | 0.68 → 0.68 | 117.1 → 116.7 |
| resident | 4 | 0.729 → 0.732 | 0.728–0.742 / 0.731–0.736 | 0.68 → 0.68 | 117.0 → 116.7 |
| fisher | 1 | 0.757 → 0.760 | 0.745–0.761 / 0.750–0.796 | 0.68 → 0.68 | 117.3 → 116.8 |
| fisher | 4 | 0.754 → 0.762 | 0.752–0.765 / 0.760–0.763 | 0.69 → 0.69 | 117.1 → 116.8 |
| uniform_pipeline_spill | 1 | 0.957 → 0.948 | 0.938–0.983 / 0.943–0.978 | 0.87 → 0.86 | 12.5 → 13.0 |
| uniform_pipeline_spill | 4 | 0.956 → 0.938 | 0.951–0.966 / 0.932–0.949 | 0.90 → 0.88 | 12.5 → 12.9 |
| partition_spill | 1 | 0.833 → 0.858 | 0.830–0.867 / 0.828–0.868 | 0.73 → 0.76 | 12.9 → 13.3 |
| partition_spill | 4 | 0.826 → 0.836 | 0.824–0.834 / 0.821–0.872 | 0.73 → 0.74 | 12.8 → 13.4 |

These results do not establish a consistent complete-job speedup. Resident
allocation counts and peak live requested bytes are unchanged (about 124.8 MiB
for one worker); the improved ledger records descriptor reallocation overlap,
raising peak reservations from about 129.8 to 131.4 MiB. The grouped spill case
uses 16 initial runs instead of 18 and 22 temporary files instead of 24, with the
same two final merges, logical temporary traffic and 165.7 MiB temporary-space
peak. One-worker peak live requested bytes increase from about 8.00 to 8.28 MiB
because the changed threshold retains a larger batch. Adaptive partition timing
and allocation counts also move slightly as its initial routing decision occurs
at a different retained-row threshold. Retain existing algorithms/defaults;
accept this as more explicit accounting and tested fallback, not an RSS reduction
or a throughput claim.

Reproduce with the repository's staged Rust environment, saving baseline CLI
and allocation-profile binaries before applying the change:

```sh
cargo test --offline --locked --workspace
cargo test --offline --locked -p chopper --lib --features experimental-radix,experimental-distribution
cargo clippy --offline --locked --workspace --all-targets --all-features -- -D warnings
cargo build --offline --locked --release -p chopper --bin chopper --example allocation-profile
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-group-budget-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-group-budget-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases resident fisher uniform_pipeline_spill partition_spill
bash scripts/build-browser.sh --offline
node scripts/build-browser-tests.mjs
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu node scripts/test-browser.mjs
```
