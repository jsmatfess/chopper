## Compact dataset key accounting (2026-10-16)

Compact intermediate dataset readers now reserve decoded sort-key capacity
before allocating it. The header holds its charge while the previous reusable
row is still live, so a handoff must fit both keys. The charge then joins the
existing compact payload reservation without changing the row descriptor size.
Variable keys retain their charge through row lifetime and payload trimming;
16-byte random keys release their heap charge when moved inline. Boxing a
variable key with spare capacity reserves old/new allocation overlap. Retained
sort/shuffle storage takes over only after its reservation succeeds, as for
compact dataset payloads. No spill framing or seeded algorithm identity changes.

This closes the **compact intermediate dataset key** slice. Owned intermediate
rows, merge/routed key decoding, packed-to-owned conversion, retained
profiling/cache metadata, file/runtime metadata and sorting overhead remain
outside complete accounting. Aggregate merge allowances still cover those merge
paths; this does not turn the ledger into a live-memory/RSS cap. Intermediate
decode pressure can return a clean budget error; no new spill/retry policy is
introduced. Target-SSD cache/device calibration is skipped in this WSL pass.

Four added tests exercise below/at/above shared key allocation and boxing-overlap
limits, simultaneous old/new keys during reuse, empty/inline/variable/wide keys,
charge lifetime after reader destruction, payload trimming, truncated headers,
truncated payloads and invalid UTF-8. The existing dataset-to-sort transfer test
now includes a variable key. All 137 workspace tests, 55 combined experimental
feature library tests, and 24 Chromium/WASI contracts pass. Formatting, Clippy
with warnings denied, and native/WASI release builds pass. HTTP and Chromium
checks use loopback access and the staged Chromium libraries under
`/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

Complete native jobs use the existing alternating benchmark harness with
100,000 presorted many-column rows, one/four workers and three repetitions.
All 72 timed jobs and 24 separate allocation censuses preserve exact output
bytes/order, names, lineage, stages and logical digests. Warm, uncontrolled WSL
storage is used; physical device throughput is unmeasured. This is accounting
work, with no throughput improvement claim.

| Pipeline | One-worker median seconds, before → after | Change, one / four workers |
| --- | --- | --- |
| `streaming_pipeline` | 0.4689 → 0.4889 | +4.3% / +0.3% |
| `streaming_pipeline_sort` | 0.4985 → 0.5001 | +0.3% / -1.6% |
| `uniform_pipeline` | 0.2923 → 0.3101 | +6.1% / -6.2% |
| `uniform_pipeline_spill` | 0.3187 → 0.3227 | +1.3% / -1.9% |
| `balanced_terminal` | 0.3037 → 0.3098 | +2.0% / +1.0% |
| `fisher_pipeline` | 0.2649 → 0.2741 | +3.5% / -1.0% |

Timing is mixed across workers. The one-worker resident uniform pipeline has
identical requested allocation traffic (135.06 MB), allocation/reallocation
counts and instrumented process peak (21.45 MB) before/after. Reservations reuse
the existing row descriptor. These counts are requested allocator bytes, not RSS.
See timing ranges, CPU, peak RSS, reservation peaks and temporary traffic in the
raw records. Baseline binary hashes match the preceding compact dataset payload
accounting artifacts; builds/contracts and timing suites run separately.

All 36 further engine jobs (native, baseline WASI and candidate WASI) preserve
exact bytes/order and metadata. Browser whole-job medians, three repetitions:

| Pipeline | Before → after, seconds | Change |
| --- | --- | --- |
| `grouped_fisher256` | 1.7207 → 1.6462 | -4.3% |
| `balanced_partition` | 1.8712 → 1.8299 | -2.2% |
| `balanced_probabilistic_shuffle` | 3.9615 → 3.9911 | +0.7% |
| `balanced_probabilistic_sort` | 4.0292 → 3.9924 | -0.9% |

Browser times include OPFS/export work; browser CPU, allocations and RSS remain
unmeasured. This narrow pass does not close the external multi-level, rare-wide,
physical-device or scale matrix. The native timing suite and engine suite ran
sequentially after builds/contracts completed.

Artifacts: [native timing/allocation records](../../evidence-originals.md#sha256-b5d5c0e47078ad97d98d75adaff15a0f2702c180fd5d3bd798abd52591861f8b "Original: docs/benchmarks/dataset-key-native-2026-10-16.jsonl"),
[native/WASI jobs](../../evidence-originals.md#sha256-66426583389276f4c7292d019311fba2222d39246bcabb1aadbbe425cebfe3d9 "Original: docs/benchmarks/dataset-key-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-0902a4f68fbe68468176e33da94ba863486a7af6c27a93fcef29e56dbbc226f4 "Original: docs/benchmarks/dataset-key-browser-2026-10-16.json"),
[summary](../../evidence-originals.md#sha256-3604aca0b3467f9b86c5b76aec11e20e404f9469aa0e537c282b367a020c11c2 "Original: docs/benchmarks/dataset-key-summary-2026-10-16.json").

Reproduce after preserving baseline native/allocator/WASM binaries and building
the candidate native release/allocator and browser release:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases streaming_pipeline streaming_pipeline_sort uniform_pipeline uniform_pipeline_spill balanced_terminal fisher_pipeline
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  balanced_partition,balanced_probabilistic_shuffle,balanced_probabilistic_sort,grouped_fisher256 \
  128 BEFORE.wasm
```
