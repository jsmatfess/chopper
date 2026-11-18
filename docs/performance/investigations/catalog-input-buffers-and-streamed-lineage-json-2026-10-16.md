## Catalog input buffers and streamed lineage JSON (2026-10-16)

Intermediate dataset and prepared output-plan catalog readers now reserve their
fixed I/O buffer before construction. Both use one reusable byte vector for JSON
lines, charging actual capacity and old/new growth overlap before allocation.
Catalog records are bounded by `max_record_bytes + 512`: the existing lineage
limit plus fixed group/chunk field names, punctuation and decimal counters. This
bounds encoded input scratch; it does not reserve decoded JSON trees. Disk
framing and persisted JSON remain unchanged.

Cancellation is checked even when the next record is already buffered. A failed
read, denied growth or malformed JSON terminates the iterator. EOF/failure frees
line scratch; the exhausted iterator retains its charged reader buffer until
destruction. Reader admission uses the file's original workspace and shared
process ledger, so file/dataset destruction does not release a surviving reader's
charge. A denied aggregate grant rolls back local admission and permits retry.

Lineage size checks now serialize into a bounded counter instead of constructing
a temporary JSON vector. Random-domain construction serializes directly into the
same v1 BLAKE3 framing instead of constructing a JSON string. Both paths preserve
serde's compact JSON grammar, escaping and map ordering. Six new tests cover
local/shared capacity edges, aggregate rollback, reuse, multi-buffer growth,
failure/retry, corruption/truncation/UTF-8, buffered cancellation, independent
reader lifetimes, exact serialized limits and v1 domain parity for escaped,
Unicode and large scopes. **193 workspace tests, 107 combined-feature library
tests, 24 Chromium/WASI contracts, formatting and all-target workspace Clippy
with warnings denied pass.** Native and WASI release builds pass.

Decoded/cloned lineage values, JSON deserializer scratch and JSON construction
for manifests/analysis remain outside this step. Publication/codecs/input
adapters, temporary-file construction and runtime overhead also remain open.
The ledger still does not bound complete process live memory or RSS.

The final native matrix contains **96 timed complete jobs and 32 separate
allocation censuses**, with one/four workers and three alternating repetitions.
Seven cases use 100,000 rows/33 fields: plain output, resident/external shuffle,
partition/shuffle and probabilistic/stratified downstream pipelines, including
512 logical groups. A separate 10,000-row fixture carries 512-character Unicode
partition labels through 512 groups. Every run preserves exact bytes/order,
filenames, lineage, stage statistics and logical digests.

| Native complete-job fixtures | Median time change |
| --- | ---: |
| Ordinary and 512-group pipeline, 100,000 rows | −2.4% to +3.4% |
| Wide Unicode lineage, 10,000 rows | −2.8% / −5.3% (one/four workers) |

The one-worker 512-group ordinary fixture removes 2,053 allocations and 286,225
requested bytes. The wide-lineage fixture removes 2,053 allocations and 3,082
reallocations, reducing requested traffic from 156,263,829 to 147,850,822 bytes.
These are separate allocator censuses, not RSS measurements or physical
`realloc` overlap. Ordinary complete-job timings remain mixed; wide-label ranges
also overlap. No general speedup is established. GNU CPU time, observed RSS,
prepare-time reservation peaks and logical temporary I/O/space remain in raw
measurements; analysis diagnostics do not capture later publication-time peaks.

Chromium/WASI adds **27 complete jobs** at 100,000 four-field rows with
128-byte payloads, alternating native, browser baseline and candidate across
three repetitions. Uniform shuffle, downstream probabilistic grouping/shuffle
and stratified exact assignment/shuffle preserve exact bytes/order and metadata.
Browser medians change by +7.3%, +1.0% and −1.0%, respectively, with overlapping
baseline/candidate ranges in every case. These warm WSL/OPFS measurements do not
establish a throughput gain, physical-device performance or browser RSS bounds.

The final timing matrices ran after builds/tests completed. An
[initial catalog-only candidate](../../evidence-originals.md#sha256-f6d95962b1fdc37b6a4e85a1c2fcff41a770718d3726ae06eed68b6c8232e2bd "Original: docs/benchmarks/catalog-reader-initial-native-2026-10-16.jsonl")
and [its browser contracts](../../evidence-originals.md#sha256-cf96c0a3d6614338ae1a029d88a960c7564bed3c77bc41995b6564a3edfdcae4 "Original: docs/benchmarks/catalog-reader-initial-browser-2026-10-16.json")
precede streamed lineage hashing. A second
[concurrent correctness/control pass](../../evidence-originals.md#sha256-ed632700ba759ed3c7e916520c86c77feb84f3a502975b037e474a64e0febdba "Original: docs/benchmarks/catalog-reader-concurrent-controls-2026-10-16.jsonl")
overlapped Chromium contracts and is excluded from the final timing ranges.
All are retained without treating their timing deltas as final evidence.

Artifacts: [ordinary native](../../evidence-originals.md#sha256-6a6d0b131e6e454628d8663d28ca448a431f8171ff8f2cc26cf4a136427107b4 "Original: docs/benchmarks/catalog-reader-native-2026-10-16.jsonl"),
[wide-lineage native](../../evidence-originals.md#sha256-6fd410d73cff83eebb75969c3051956917eeb59a9650fdc84aae96d45cca9928 "Original: docs/benchmarks/catalog-reader-wide-native-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-6341fdb0f6a2d28bf6e66c50dc562429076cb8359008173ca92ce43615fa6821 "Original: docs/benchmarks/catalog-reader-browser-2026-10-16.json"),
[native/browser comparison](../../evidence-originals.md#sha256-646692a7c82e13b98cb0877786c01611bde6a8ea04b7d84678c4e47001ffe6b8 "Original: docs/benchmarks/catalog-reader-engines-2026-10-16.jsonl"),
[summary and hashes](../../evidence-originals.md#sha256-1836b5601f00d22568e20b8bf0c6fe9a230a11e86db084570552f730c84ca158 "Original: docs/benchmarks/catalog-reader-summary-2026-10-16.json").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain resident spill partition_pipeline streaming_pipeline stratified_assign_pipeline_spill catalog_pipeline
# Wide-lineage follow-up: --rows 10000 --cases catalog_wide
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  balanced_probabilistic_shuffle,stratified_assign_shuffle,uniform32 128 BEFORE.wasm
```
