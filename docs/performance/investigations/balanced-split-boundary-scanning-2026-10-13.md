## Balanced-split boundary scanning, 2026-10-13

Intermediate balanced splitting now scans validated frame lengths instead of
allocating a `Row` and a string for every field just to compute its disk length.
Contiguous fields borrow the 64 KiB reader buffer. Fields crossing that buffer
reuse one scratch allocation, grown exactly as needed up to `max_record_bytes`;
keys are consumed without allocation. Key limits, field counts, cumulative
payload limits, truncation and UTF-8 checks remain enforced. Child offsets use
checked addition. Cancellation checks remain per row, and children still share
the original data snapshot. Terminal splitting and the spool format are unchanged.
The scratch bound is not a complete process-memory reservation guarantee; full
allocation accounting remains on the adaptive-execution roadmap.

### Native A/B evidence

AMD Ryzen AI 9 HX 370, WSL Linux, warm uncontrolled local storage. The baseline
was built from the existing working tree immediately before this change, with
comparison sorting defaults. Both builds use identical release settings.
300,000 rows and 33 columns, balanced into four children and then partitioned
by `c0`, at 32 MiB with one/four configured workers. The rare-wide fixture replaces
one field with 1.8 MB. Three alternating ordinary runs per build/case/worker
count, followed by separate allocator-instrumented runs. Builds and correctness
tests finished before the recorded native timing pass.

| Fixture / workers | Median job seconds, before → after | Wall reduction | Median CPU seconds, before → after | Peak RSS range KiB, before → after |
| --- | --- | --- | --- | --- |
| columns / 1 | 1.609 → 1.357 | 15.7% | 1.36 → 1.15 | 13,920–13,980 → 13,608–13,752 |
| columns / 4 | 1.635 → 1.402 | 14.2% | 1.39 → 1.19 | 13,836–14,016 → 13,680–13,888 |
| rare_wide / 1 | 1.680 → 1.451 | 13.6% | 1.42 → 1.21 | 17,480–17,680 → 17,156–17,364 |
| rare_wide / 4 | 1.660 → 1.420 | 14.5% | 1.42 → 1.19 | 17,136–17,584 → 17,132–17,408 |

Whole-job allocation counts drop by about 10.2 million in each case (32.6%);
requested allocation bytes drop by about 248.9 MB. These are cumulative requests,
not live memory or RSS. The reduction matches removal of 33 field strings and
one vector per row, offset by reusable scanner scratch. Counters cover the
complete preparation/publication path; allocation stacks and new sampled CPU
stacks were not captured. The raw data includes size buckets, CPU time, wall-time
ranges, peak RSS, reservations, temporary traffic and sort diagnostics.
Peak algorithm reservations and temporary traffic are unchanged between builds
for each fixture; these jobs use four routed groupings and no sort/merge runs.
This is not evidence for multi-level merge or controlled cold/slow-storage gains.

All 32 native jobs (24 ordinary and eight allocation profiles) match output
bytes/order, file names, row counts, lineage, stage metadata and logical digests.
[Raw native results](../../evidence-originals.md#sha256-8b467555aef06d5fe97c9cef40c81b4d59c3f121c8538884698950fd7c8e0458 "Original: docs/benchmarks/boundaries-native-2026-10-13.jsonl").

### Validation and browser scope

All 80 workspace tests, formatting, workspace/all-target Clippy with warnings
denied, and the release WASI build pass. Differential scanner/decoder tests use
reader capacities of 1, 7, 64 and 65,536 bytes, every truncation of a valid frame,
non-UTF-8 binary keys, invalid field UTF-8, oversized counts/lengths, cumulative
payload overflow and consecutive frames. Existing tests cover snapshot sharing,
cancellation, caps, publication and pipeline compatibility.

Three repetitions each in native and Chromium/WASI match output hashes, names,
row counts, CSV byte counts and logical digests for a 100,000-row, four-column,
128-byte-payload balanced-then-partition job, including OPFS export. This is
candidate platform parity, not a browser A/B speedup or a rerun of the browser
contract suite. [Raw browser/native results](../../evidence-originals.md#sha256-b31dd5c8ce716d408f2f06c082f964f530fc5dfcfdd62713f9c6311d870159ab "Original: docs/benchmarks/boundaries-browser-2026-10-13.jsonl").

Reproduce after retaining baseline binaries outside the build directory:

```sh
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
python3 scripts/benchmark-boundaries.py \
  --before /tmp/chopper-boundaries-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-boundaries-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile
bash scripts/build-browser.sh
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 balanced_partition 128
```

Compact field views through final serialization, tuple keys and digest consumers
are the next unchecked experiment; this change only eliminates decoding for
intermediate balanced boundaries.
