## Operation-key capacity and inline group indices (2026-10-16)

Partition tuple keys and exact-assignment/fused-shuffle keys now reserve their
complete capacity before allocation. Tuple sizing includes NUL escaping, field
terminators and any random/domain suffix. Fixed group indices use eight inline
bytes instead of a heap vector. Existing random-key v1 framing, collision
refinement, seeded membership/order and disk framing are unchanged.

A key retains its reservation through construction and row installation,
including vector-to-box replacement overlap. Decoded rows keep the charge after
reader/sorter destruction; ingestion rows acquire their row-owned charge before
parser ownership is released. Denied key growth or handoff first spills retained
sort rows and retries. Mandatory failure preserves the old row and releases the
new key; it does not publish partial results.

Five tests cover exact/shared capacity edges, NUL/Unicode/repeated-column v1
framing, failure/retry cleanup, boxing overlap, inline-index binary framing,
consumer lifetime and pressure-triggered spilling with exact row conservation.
**180 workspace tests, 95 combined-feature library tests, formatting and
workspace/all-target Clippy with warnings denied pass.** Native and WASI release
builds pass. Browser contracts and engine measurements are recorded below.

The native matrix runs 100,000 rows/33 fields, one/four workers and three
alternating repetitions: **168 timed complete jobs and 56 separate allocator
censuses**, all with exact bytes/order, filenames, lineage, stage statistics and
logical-digest parity. Cases cover probabilistic routing/sort fallback,
interleaved/probabilistic downstream shuffles, partition with/without fused
shuffle, spilling/1.8 MB partition keys, exact/stratified assignment and a resident
uniform-shuffle control. GNU CPU time, peak RSS, stage timing, ledger and temporary
space/traffic counters are retained in the raw data.

| Native complete-job cases | Median time change range |
| --- | ---: |
| Probabilistic routing/sort, streaming/interleaved pipelines | −9.1% to +4.1% |
| Partition, fused shuffle and spill/wide keys | −2.7% to +3.3% |
| Exact/stratified assignment and downstream shuffle | −5.4% to +2.7% |
| Resident uniform-shuffle control | +0.2% to +2.0% |

These mixed warm WSL results do not establish a general throughput gain.
Allocation effects are more consistent. At one worker, per 100,000 input rows:

| Census | Change in allocations / reallocations | Change in total requested bytes |
| --- | ---: | ---: |
| Streaming membership and exact assignment without fused shuffle | −100,000 allocations | −800,000 |
| Plain partition | −100,000 reallocations | −800,000 |
| Partition + fused shuffle | −200,000 reallocations | −3,000,000 |
| Exact assignment + fused shuffle | −200,000 reallocations | −3,200,000 |
| Stratified exact assignment + fused shuffle | −300,000 reallocations | −4,000,000 |

The sort-fallback pipeline also changes sort-buffer growth; see its exact census
rather than applying the first row's byte delta to every pipeline. Requested
allocator traffic is measured separately from normal timing and is not RSS or
physical `realloc` overlap. Native process peak live requested bytes for the
unstratified exact-assignment fixture fall from 43,451,818 to 42,651,826.

The Chromium/WASI matrix adds **63 complete jobs**, alternating native, browser
baseline and candidate at 100,000 four-field rows with 128-byte payloads. All
seven cases preserve bytes/order and metadata; browser median changes range
from −7.1% to +12.8%, including an unchanged uniform-shuffle control at +6.4%.
The largest increase, fused exact assignment, also varies substantially in the
unchanged ingestion stage. A separate **42-job recheck**, interleaving that case
and the control across seven alternating repetitions, measures +1.6% assignment
and −3.8% control medians with overlapping ranges. It does not reproduce the
initial +12.8% increase. Both passes are retained; no general speedup is claimed.
**All 24 Chromium/WASI contracts pass.** Browser CPU/allocation/RSS profiling is
still separate remaining work.

Lineage/catalog JSON, publication/codecs/input adapters, temporary-file
construction and native runtime overhead remain unaccounted here. Independent
profiling/preparation contexts still need a shared policy. The ledger is not a
complete process/RSS cap, and these measurements do not certify physical SSD
throughput, other platforms or billion-row execution of this build.

Artifacts: [native timings and allocation censuses](../../evidence-originals.md#sha256-ebf9519c65fa0f983495a7b093575658241c993610a53ed9187d887c34eff357 "Original: docs/benchmarks/operation-key-native-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-9f10e47f4cc40f81a2e1878c12418f80deb82708c7439c2fa67c63bafca9f575 "Original: docs/benchmarks/operation-key-browser-2026-10-16.json"),
[native/browser comparisons](../../evidence-originals.md#sha256-9885eef95cbfda6dac20d721ba6e1e70fde5ac66d3b402006ca44352e8ffa779 "Original: docs/benchmarks/operation-key-engines-2026-10-16.jsonl"),
[seven-repetition browser recheck](../../evidence-originals.md#sha256-285a6154fcd3165cbfe3390f3d526f18402158d8f089fd7a211083a8130293aa "Original: docs/benchmarks/operation-key-recheck-engines-2026-10-16.jsonl"),
[summary and hashes](../../evidence-originals.md#sha256-5444b2acda742403fa7586ad2c545a145c99a8b318a0c8500f871e3f1b6d6d05 "Original: docs/benchmarks/operation-key-summary-2026-10-16.json").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases probabilistic_route probabilistic_sort streaming_pipeline streaming_pipeline_sort \
    interleaved_pipeline partition partition_shuffle partition_spill partition_wide \
    assign assign_shuffle stratified_assign_shuffle stratified_assign_pipeline_spill resident
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  partition_shuffle,assign_shuffle,stratified_assign_shuffle,balanced_probabilistic_shuffle,balanced_probabilistic_sort,balanced_interleaved_shuffle,uniform32 \
  128 BEFORE.wasm
```
