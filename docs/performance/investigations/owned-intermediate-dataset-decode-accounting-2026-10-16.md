## Owned intermediate dataset decode accounting (2026-10-16)

The owned `Dataset::rows` decoder now reserves key capacity, the actual
`Vec<String>` descriptor capacity and each string's actual capacity before
filling the allocation. String construction transfers its byte vector without
copying, and the descriptor vector reserves the declared count once, so this
path has no growth or shrink replacement overlap. Reservations use the same
shared workspace as compact decoding, sorting, dataset buffers and temporary
paths. Denied allocations fail before materialization; no output is published.

`GroupRows` now yields `DecodedRow`, an immutable borrowing wrapper around
`Row` and its reservation. The charge follows each returned row through
consumer borrowing, even after the iterator and dataset are destroyed. Several
retained rows therefore compete against the same ceiling. The output-plan
consumer keeps the wrapper alive during serialization. Explicitly cloning a
borrowed `Row` creates a separate allocation outside this decode reservation;
conversion/adapter accounting remains open. Owned iteration checks cancellation
even when the next row is already buffered, and terminates after its first
budget, decode or cancellation error.

Four new tests exercise just-below/at/above shared capacity, empty and UTF-8
fields, independently retained rows, destruction order, truncated/invalid UTF-8
and oversized count/length frames, competing reservations and buffered
cancellation. The older fixed-buffer boundary test now expects owned decoding
to fail when buffers leave no room for descriptors. All 145 workspace tests,
63 combined experimental-feature library tests and 24 Chromium/WASI contracts
pass. Formatting, Clippy with warnings denied and native/WASI release builds
pass. HTTP/Chromium tests ran with loopback access; Chromium used the staged
libraries under `/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

Complete native controls use 100,000 presorted 33-field rows, one/four workers
and three alternating baseline/candidate repetitions. All 48 jobs preserve
exact output bytes/order, output metadata, stages and logical digests. Median
whole-job times change by -2.1% to +2.7%, with mixed directions. These controls
mostly use the existing direct/compact paths; they do not isolate owned decode
cost or establish a throughput gain. Raw records include ranges, CPU, process
peak RSS, workspace peaks and logical temporary I/O/space. Storage is warm,
uncontrolled WSL storage; physical SSD throughput/cache conditions are unknown.

A further 18 complete native/Chromium-WASI jobs (plain output, external
uniform shuffle and balanced/partition pipelines; three repetitions each)
preserve exact output bytes/order, metadata and digests across engines. These
are candidate parity controls, without a baseline-WASM timing comparison.

Artifacts: [native controls](../../evidence-originals.md#sha256-1a1965b52b1ce97e3b7655a63854c731f5cdaf2a5719c2378d5dcfd69f0c0617 "Original: docs/benchmarks/owned-dataset-native-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-0cfca9178cb8bfca476472a5d9f9658b4ee7962aa9836f6beb8a9d31a4485a4a "Original: docs/benchmarks/owned-dataset-browser-2026-10-16.json"),
[native/WASI parity controls](../../evidence-originals.md#sha256-88327c52e860b2c11c54935d9ca35f29b8b85017d2330d5c7633fc02a6b29e24 "Original: docs/benchmarks/owned-dataset-engines-2026-10-16.jsonl").

This is a scoped accounting step. Merge/routed decoded rows still use their
existing conservative allowances; exact capacities, retained profile/cache
metadata, conversion overlap, sorting and file/runtime metadata remain open.
The ledger remains an algorithm workspace ceiling rather than a complete
live-memory/RSS cap. Algorithms, seeded order, spill framing and defaults are
unchanged. Target-SSD calibration and other-platform validation remain outside
this WSL pass.

Reproduce the native controls after retaining the baseline binary:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain balanced_terminal balanced_terminal_wide streaming_pipeline
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper \
  100000 3 rows,uniform32,balanced_partition 128
```
