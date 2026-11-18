## Output snapshot writer buffer accounting (2026-10-16)

Final encoded-output snapshot writers now reserve both fixed I/O buffers before
constructing either writer. Native data/catalog buffers charge **73,728 bytes**;
WASI's larger storage-RPC data buffer plus catalog charges **270,336 bytes**.
Charges remain live through serialization/flush and release when the writer is
dropped or finishes. Finished snapshots retain their disk files and existing
path charges, without retaining the freed writer buffers. The former default
catalog capacity is now explicit (8,192 bytes); actual buffer sizes are unchanged.

Three new tests cover exact/shared capacity edges, competing reservations and
retry, finished-snapshot lifetime/readback, header-cap failure and invalid encoding
after partial file construction. **169 workspace tests, 87 combined-feature
library tests and 24 Chromium/WASI contracts pass.** This step does not charge
serializer text/encoding scratch, BOM/header prefixes, lineage/catalog JSON,
publication readers/writers or codec allocations; those remain follow-up work.

The native matrix contains **72 timed complete jobs and 24 allocation censuses**:
100,000 rows, 33 fields, one/four workers, three alternating repetitions. Plain
output, rare-wide plain output, resident/external shuffle, partition spilling
and a probabilistic downstream pipeline all preserve exact output bytes/order,
names, lineage, stages and logical digests. Native medians range from **−3.1% to
+0.8%**; allocation counts are unchanged. These mixed small differences do not
establish a throughput improvement.

The native/Chromium-WASI matrix adds **36 verified complete jobs**: 12 native,
12 browser baseline and 12 browser candidate, three alternating repetitions,
100,000 four-field rows, plain output, uniform shuffle, a probabilistic/shuffle
pipeline and gzip publication. All output bytes/order and metadata match. See
raw timings/ranges below; these remain warm uncontrolled WSL/OPFS results, with
no physical-device throughput or RSS-cap claim. Shared pressure can now reject
output-writer construction before allocating these mandatory buffers.

Artifacts: [native timings/allocations](../../evidence-originals.md#sha256-a696a32b90048fcd5ee03489dac99396c2e4289003563a4c548de8e9ab505e42 "Original: docs/benchmarks/output-buffers-native-2026-10-16.jsonl"),
[native/browser comparison](../../evidence-originals.md#sha256-cf36ae97f21d6390248efc3d137726ee3046d89c4218467ee1b526646c62e461 "Original: docs/benchmarks/output-buffers-engines-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-8dcb750c0ca7d5991699ad7f54c0f47f0c5d4094241e9539258eddcf4be4daec "Original: docs/benchmarks/output-buffers-browser-2026-10-16.json"),
[summary, ranges and hashes](../../evidence-originals.md#sha256-be189efd467ed56191e452e2177e34e2323d82eb3d0d019b490719a10f4fa166 "Original: docs/benchmarks/output-buffers-summary-2026-10-16.json").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain plain_wide resident spill partition_spill streaming_pipeline
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  rows,uniform32,balanced_probabilistic_shuffle,gzip 128 BEFORE.wasm
```
