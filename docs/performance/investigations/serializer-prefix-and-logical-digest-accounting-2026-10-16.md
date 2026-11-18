## Serializer, prefix and logical-digest accounting (2026-10-16)

Final output now reserves UTF-8 text and encoded serialization scratch before
allocation, including old/new capacity overlap. The same reservation retains
BOM/header-prefix capacity until the writer finishes or drops. Headers use the
same reserved serializer as data rows. Serializer settings now retain scalar
formatting values instead of cloning encoding/line-ending strings. Legacy
encoding writes directly into reserved destination storage without a temporary
`Encoding::encode` allocation; UTF-16 storage is reserved before conversion.
Public compatibility helpers keep their existing behavior.

The retained logical digest now reserves its **16 KiB buffer and inline
hasher/descriptor state** before construction, through finalization/drop.
Record framing, hashing batches, seeded algorithms, defaults and spill framing
are unchanged. Neither this step nor the earlier writer-buffer step completes
operation/lineage/catalog JSON, input codec/adapters, publication/codec/runtime
accounting or the aggregate profiling/preparation/cache policy. The ledger still
is not a process/RSS cap.

The first candidate sized every row before serializing it and cost up to 15.1%
on the tested native paths. The revised implementation checks append capacity
while executing the shared serialization grammar. Only an actual growth invokes
full-row sizing; it reserves the complete row and old/new overlap before copying
the current prefix into replacement storage. Normal buffer reuse avoids the
extra quote/escape scan. Initial candidate artifacts are retained below.

Six new tests cover every supported output encoding, Unicode/multibyte text,
quote/escape/newline parity, exact/shared capacity edges, denial/retry, encoding
failure, hard caps, finished snapshots and digest lifetime/v1 parity. Existing
record-reuse tests also guard against carrying prior text into a later row.
**175 workspace tests, 90 combined-feature library tests, 24 Chromium/WASI
contracts, formatting and workspace/all-target Clippy with warnings denied pass.**
Native and WASI release builds pass.

The final native matrix contains **156 timed complete jobs and 52 separate
allocation censuses**, all at 100,000 rows and 33 fields, one/four workers, three
alternating repetitions. It covers plain/wide output, resident/external shuffle,
rare-wide rows, spilling partition and a probabilistic downstream pipeline.
UTF-16LE/BOM and Windows-1252 add encoding-specific controls. Every job preserves
exact bytes/order, filenames, lineage, stage statistics and logical digest.

| Native output encoding | Tested paths | Median change range |
| --- | --- | ---: |
| UTF-8 | Seven complete-job cases, one/four workers | +1.9% to +7.6% |
| UTF-16LE + BOM | Plain/wide/spill/rare-wide, one/four workers | +0.2% to +4.3% |
| Windows-1252 | Plain/resident shuffle, one/four workers | +3.9% to +7.0% |

These are measured accounting costs, not throughput gains. Complete allocation
traffic falls on the wide fixtures because growth plans include the remaining
fields/newline and encoded destination, avoiding subsequent geometric growth.
Settings/header construction also uses fewer allocations.

| One-worker wide plain-output census | Before requested MB | After requested MB | Before / after process peak live requested MB |
| --- | ---: | ---: | ---: |
| UTF-8 | 10.01 | 6.41 | 5.92 / 4.12 |
| UTF-16LE + BOM | 18.41 | 10.01 | 10.72 / 7.72 |

MB above is decimal. These system-allocator requested-byte censuses are separate
from normal timings and do not measure RSS, allocator internals or physical
allocation overlap inside `realloc`.

The final native/Chromium-WASI comparisons contain **63 verified complete jobs**:
36 UTF-8 jobs (plain, uniform shuffle, probabilistic/shuffle pipeline and gzip)
and 27 UTF-16BE/BOM jobs (plain, uniform shuffle and gzip). Each case has three
alternating repetitions across native, browser baseline and browser candidate.
Browser median changes are −0.7% to +3.6% for UTF-8 and −0.6% to +0.5% for
UTF-16BE/BOM. All bytes/order and metadata agree. These warm uncontrolled
WSL/OPFS results do not establish physical SSD performance or a general speedup.
Six additional [tiny UTF-16BE/BOM harness controls](../../evidence-originals.md#sha256-207aa93f6595fe23e7b3c50ad6d9d103d03919164eab9f7b93d6e8b9b1da7c5e "Original: docs/benchmarks/serializer-utf16-harness-controls-2026-10-16.jsonl") check resident global/four-group ID conservation and range isolation at 128 rows, with native/WASI parity. These are runtime checks, outside the median matrix.
Timing runs began after billion-row execution and both conservation passes had
finished; the large retained outputs were removed before final measurements.

Artifacts: [UTF-8 native](../../evidence-originals.md#sha256-c77fa6fb8c8c4e505a5d609a860e5b3c145d1976fcde758569e9fd462b3c573f "Original: docs/benchmarks/serializer-native-2026-10-16.jsonl"),
[UTF-16LE native](../../evidence-originals.md#sha256-1bde2cb69cd1a61d7ed689724562bb4dcb39178aa71cc4b5e18e6d4366aeceed "Original: docs/benchmarks/serializer-utf16-native-2026-10-16.jsonl"),
[legacy native](../../evidence-originals.md#sha256-c0fc10c0772bb8abe5143580a98b0fefdd7999f5e35870ea13674913ca598478 "Original: docs/benchmarks/serializer-legacy-native-2026-10-16.jsonl"),
[UTF-8 engines](../../evidence-originals.md#sha256-44803c4ba242f8e2b27452af68c0fd04ddc11670dea69250490d3c15aeb00f5b "Original: docs/benchmarks/serializer-engines-2026-10-16.jsonl"),
[UTF-16BE engines](../../evidence-originals.md#sha256-5b18bc81e101412c4d27979c0e6e75a5601f55dae593877550ae206a6f3c7ee0 "Original: docs/benchmarks/serializer-utf16-engines-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-1c5c99f24c4a61b74e12dee312aa18fe6c4dc3cc4c4ca05f03514369d9588b99 "Original: docs/benchmarks/serializer-browser-2026-10-16.json"),
[summary, ranges and hashes](../../evidence-originals.md#sha256-2a29fde61a28f18b358a57f16f1b36ec6e34a26273df845aa11f719045b8a5d7 "Original: docs/benchmarks/serializer-summary-2026-10-16.json").
Superseded first candidate: [UTF-8](../../evidence-originals.md#sha256-d1e21535a37660a49eff6d013136a0754c46612c06ef0c8e2d156f908fce1c7e "Original: docs/benchmarks/serializer-initial-native-2026-10-16.jsonl"),
[UTF-16LE](../../evidence-originals.md#sha256-94520608100a5ed3d9f1c6dddd97e51fd8fc2a075020d6efc8fb249a12e8a0e8 "Original: docs/benchmarks/serializer-initial-utf16-native-2026-10-16.jsonl"),
[Windows-1252](../../evidence-originals.md#sha256-51f129287e74cce22b6d4a1eea8c511178bc785f83d8ef8fdee9d4bd5f40cc91 "Original: docs/benchmarks/serializer-initial-legacy-native-2026-10-16.jsonl").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain plain_wide resident spill rare_wide partition_spill streaming_pipeline
# Encoding follow-up: --cases plain plain_wide spill rare_wide --output-encoding utf-16le --output-bom
# Legacy follow-up: --cases plain resident --output-encoding windows-1252
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  rows,uniform32,balanced_probabilistic_shuffle,gzip 128 BEFORE.wasm
# UTF-16 browser follow-up: cases rows,uniform32,gzip; append --output-encoding=utf-16be --output-bom
```
