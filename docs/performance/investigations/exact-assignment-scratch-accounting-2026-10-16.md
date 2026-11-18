## Exact-assignment scratch accounting (2026-10-16)

Exact assignment now reserves actual weight, count, quota, remainder-order and
optional fused-shuffle domain vector capacities before allocation, retaining the
charge through the assignment call. Quota and ordering storage is reused across
strata instead of allocated for each stratum. Shared core helpers accept
caller-owned slices; percentage parsing no longer builds split-component vectors.
Remainder ordering uses in-place unstable sorting with the original total
(remainder, index) key, so tied quotas and seeded membership remain unchanged.
The existing allocating core APIs remain available.

Four new tests cover just-below/at/above capacity, simultaneous reservations,
partial-construction failure/retry, invalid weights, quota scratch reuse and
comparison with the original stable-sort implementation. Tests include zero
weights, 100-way remainder ties and `u64::MAX` row counts. **164 workspace tests**,
**82 combined-feature library tests** and **24 Chromium/WASI contracts** pass.
The local-server integration tests require local socket access outside the
execution sandbox.

Native measurements alternate baseline/candidate complete jobs with 100,000
33-field rows, one/four workers and three repetitions. Exact assignment, fused
assignment/shuffle, balanced/assignment/shuffle spills, stratified versions and
an unaffected resident-shuffle control cover **72 timed jobs and 24 allocation
censuses**. Every job preserves output bytes/order, names, lineage, stages and
logical digests. Native medians range from **−2.4% to +4.1%** on affected paths;
these warm uncontrolled WSL results establish no throughput gain. The final
native timing pass ran separately from builds, tests and browser measurements;
an initial overlapping native pass is excluded.

| Complete native job | Workers | Before (s) | After (s) | Change |
| --- | ---: | ---: | ---: | ---: |
| `assign` | 1 | 0.2445 | 0.2397 | -1.9% |
| `assign` | 4 | 0.2311 | 0.2378 | +2.9% |
| `assign_shuffle` | 1 | 0.2796 | 0.2750 | -1.7% |
| `assign_shuffle` | 4 | 0.2658 | 0.2662 | +0.1% |
| `assign_pipeline_spill` | 1 | 0.3343 | 0.3382 | +1.1% |
| `assign_pipeline_spill` | 4 | 0.3343 | 0.3387 | +1.3% |
| `stratified_assign_shuffle` | 1 | 0.3974 | 0.3876 | -2.4% |
| `stratified_assign_shuffle` | 4 | 0.3803 | 0.3740 | -1.7% |
| `stratified_assign_pipeline_spill` | 1 | 0.4696 | 0.4747 | +1.1% |
| `stratified_assign_pipeline_spill` | 4 | 0.4698 | 0.4893 | +4.1% |
| `resident` | 1 | 0.1917 | 0.1918 | +0.1% |
| `resident` | 4 | 0.1997 | 0.1971 | -1.3% |

Allocation counts fall slightly: four allocations for direct assignment/shuffle,
22 for stratified assignment/shuffle and 42 for its balanced two-parent spill
pipeline (one worker). The resident control is unchanged. These fixtures have
two destination groups and ten strata; they do not establish broad high-cardinality
performance.

This closes exact-assignment scratch and fused-shuffle domain vectors only.
Operation-key construction, selected-column vectors, lineage/catalog JSON,
output/codecs/input adapters, temporary-path construction and native runtime
allocations remain open. Probabilistic streaming-group allocation state remains
outside this step. The workspace ledger is still not a complete live-memory or
process/RSS cap; existing runtime headroom and algorithm defaults are retained.
Target-SSD and other-platform validation were skipped for this WSL pass.

The native/Chromium-WASI matrix adds **36 verified complete jobs**: 12 native,
12 browser baseline and 12 browser candidate, using 100,000 four-field rows,
three alternating repetitions, assignment/shuffle and stratified assignment/shuffle,
plus uniform-shuffle and balanced/partition controls. Exact output bytes/order,
filenames, lineage, stages and logical digests match across engines/builds.

| Complete browser job | Before (s) | After (s) | Change |
| --- | ---: | ---: | ---: |
| `uniform32` | 1.3760 | 1.4320 | +4.1% |
| `balanced_partition` | 1.6288 | 1.7423 | +7.0% |
| `assign_shuffle` | 1.6066 | 1.3641 | -15.1% |
| `stratified_assign_shuffle` | 3.6772 | 3.7281 | +1.4% |

These are warm WSL/OPFS timings with uncontrolled caches. They do not establish
physical-device throughput or a general speedup.

Artifacts: [native timings/allocations](../../evidence-originals.md#sha256-b436e2769bb0c9b36e8a9b081907cdbaf3a4f5420f3ecfdde9617f259e50b270 "Original: docs/benchmarks/assignment-scratch-native-2026-10-16.jsonl"),
[native/browser parity and timings](../../evidence-originals.md#sha256-061edb7b722a68be49079c53b32375174ec313ebbc6ad2f4249151631b39b031 "Original: docs/benchmarks/assignment-scratch-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-5b93445838a8a5152eb3446fa92708e38e6577340f849a21adb3e22829231b49 "Original: docs/benchmarks/assignment-scratch-browser-2026-10-16.json"),
[summary, environment and binary hashes](../../evidence-originals.md#sha256-4a6f596a5cfceaf223ce41500b0228b08bac9a982bfe382fdf81bf2a08463a6b "Original: docs/benchmarks/assignment-scratch-summary-2026-10-16.json").

Reproduce after saving baseline CLI, allocator-example and WASM binaries, then
building native/allocator and WASI releases:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases assign assign_shuffle assign_pipeline_spill stratified_assign_shuffle stratified_assign_pipeline_spill resident
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  assign_shuffle,stratified_assign_shuffle,uniform32,balanced_partition 128 BEFORE.wasm
```
