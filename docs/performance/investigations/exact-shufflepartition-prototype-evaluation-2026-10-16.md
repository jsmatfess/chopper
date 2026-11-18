## Exact shuffle/partition prototype evaluation (2026-10-16)

The opt-in `experimental-shuffle-partition` feature sorts adjacent uniform-v1
shuffle/partition input by tuple followed by the **original parent's** random
key/domain. It avoids the globally shuffled intermediate while retaining source
IDs, collision refinement, logical operation indices, stage statistics, lineage,
filenames and downstream random domains. Both initial CSV ingestion and later
parents use the same eligibility/domain rules. See the
[rewrite audit](../../pipeline-rewrites.md) for exact/distribution/prohibited rules.
Defaults remain unchanged.

Six added tests cover eligibility, forced collisions through resident and
hierarchical external sorting, multiple parents and downstream operations,
repeated leading shuffles/empty input, reservation boundaries/rollback, malformed
input, cancellation and disk denial. Recorded checks pass: 199 default / 219
all-feature workspace tests, 133 all-feature library tests, default/all-feature
Clippy, formatting and 24 candidate Chromium/WASI contracts.

The final native comparisons contain **210 ordinary timed jobs and 70 separate
allocation censuses**. The principal matrix uses 300,000 rows, narrow/many-column/
rare-wide shapes, five pipelines, one/four workers and three alternating repeats.
Every output/metadata fingerprint and independent ID/field check matches. All 30
principal cell medians improve 3.3–32.4%. Four-worker leading shuffle/partition
medians improve 20.6% (narrow), 32.0% (many columns) and 32.4% (rare wide).
A 1.4-million-row many-column hierarchical merge improves 28.6%. Skewed payload
keys improve about 31%; the rare-wide payload-key control is mixed (+2.5% with
one worker, −2.7% with four), so these are workload-specific gains.

For the leading many-column/four-worker cell, median CPU falls from 1.15 to
0.79 seconds, requested allocation traffic from 525.3 to 185.9 MB, allocation
count from 1,501,747 to 901,671, temporary writes from 346.4 to 146.2 MB and peak
temporary bytes from 214.5 to 146.1 MB. This does **not** establish a universal
memory reduction: some downstream peak temporary-space values increase 1–2%,
rare-wide reservations can increase, and RSS is mixed. A separate 36-job
previous-default/final-feature-off control costs 0.7–3.3% on tested cells.

The repeated native/WASI comparison completes **108 jobs** at 100,000 rows,
three shapes and three pipelines, plus eight repeated-shuffle/assignment
controls. All match exact output/metadata; native references independently verify
conservation and partition/parent isolation. Browser medians improve 28.5–53.5%
in the repeated matrix. These warm WSL/Chromium OPFS observations do not measure
physical SSD behavior or browser CPU/allocation/RSS.

The **2026-10-17 persistent-profile replay completes all four 1.4-million-row
native/WASI jobs** with exact output/metadata parity. Native original/fused jobs
use 77/86 runs and two merges; browser jobs also perform hierarchical merging.
The single browser timing is 29.3 versus 18.8 seconds (35.8% lower), an acceptance
point rather than a repeated estimate.

A further **108 repeated complete jobs** rerun the three-shape/three-pipeline
matrix with persistent profiles and the storage fixes. All fingerprints and
independent native conservation checks match. Browser cell medians improve
14.0–34.1%; ranges and individual samples are retained separately from the
historical temporary-context results. Eight additional persistent-context jobs
cover repeated shuffles and downstream assignment.

The first large browser attempt trapped during a buffered merge write. A
storage-only reproducer removes Rust, CSV, sorting and partitioning: the installed
Chromium's temporary context returns `4294967288` for a 1 MiB OPFS write after
899,678,208–1,047,527,424 retained bytes in two runs. A persistent profile completes 1.5 GiB. That invalid
count crossed the shared signed integer and WASI boundary as a successful write,
causing Rust's buffer bookkeeping to panic. Storage workers now reject negative,
noninteger and oversized read/write counts, preserving valid short operations.
A separate deterministic test exposed a delayed-notification race; the bridge
now waits on the current completion predicate within a fixed timeout. Both bugs
have tests observed failing before their fixes, followed by passing UI tests and
TypeScript checks. Benchmark workers are built from current source and restored
afterward; persistent context and UI source hashes are recorded. The final
temporary-context replay of the original large global workload also completes;
the observed invalid-count threshold depends on context/resources. Default native
and WASI artifacts are restored and their hashes verified. Historical
measurements above use temporary browser contexts and retain that scope.

Artifacts: [native matrix](../../evidence-originals.md#sha256-fb81d3eb7bb524e0a67c14eb54197824a13ba1c24004f16e561593da818d1894 "Original: docs/benchmarks/shuffle-partition-native-2026-10-16.jsonl"),
[hierarchy](../../evidence-originals.md#sha256-d63681f9cf25e1d2dacabbdc9d06bdb10f7c72b199b3f4c25bf57e55f4d03a55 "Original: docs/benchmarks/shuffle-partition-multilevel-2026-10-16.jsonl"),
[wide keys](../../evidence-originals.md#sha256-b43aa42672596988e7854ae24adee6d7658d618a19e13289f9f3518573fb0c0b "Original: docs/benchmarks/shuffle-partition-wide-key-2026-10-16.jsonl"),
[skew](../../evidence-originals.md#sha256-431b6d2bc09f759bad3690062d115e1d759b9b133152e71f6d37b2f63f470154 "Original: docs/benchmarks/shuffle-partition-skew-2026-10-16.jsonl"),
[feature-off control](../../evidence-originals.md#sha256-8b5f0d07edf6c8e625781993ba24649304c6a760813a88ca8f5adda3f4dad51d "Original: docs/benchmarks/shuffle-partition-default-control-2026-10-16.jsonl"),
[shared-memory boundaries](../../evidence-originals.md#sha256-4fb5045b49aba12d4be91d1e4840b386ad85448f1f25f7a41abccaf6deb089cb "Original: docs/benchmarks/shuffle-partition-boundaries-2026-10-16.jsonl"),
[input/failure/snapshot controls](../../evidence-originals.md#sha256-5e4f2958373ba0d079e6fb970e34349533f2d531516d2dcac696077911b6ca01 "Original: docs/benchmarks/shuffle-partition-controls-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-2bb1dd9038126ac51b94818b94472bef75f244edb8207f9b7a6b51aa7277114d "Original: docs/benchmarks/shuffle-partition-browser-2026-10-16.json"),
[native/WASI matrix](../../evidence-originals.md#sha256-99255fb5ddadf7d0a595f813d5d389940eeda9595963c7f607546427cb268209 "Original: docs/benchmarks/shuffle-partition-engines-2026-10-16.jsonl"),
[extra engine controls](../../evidence-originals.md#sha256-aea746a55682e02dfec04e15879bd58d0f2366c7a7cd81dca3519ebc2f232478 "Original: docs/benchmarks/shuffle-partition-engine-controls-2026-10-16.jsonl"),
[incomplete large replay](../../evidence-originals.md#sha256-bdab1aa5013a46dba8270ee3fe04f92a5db09d8646f53b2958360dd305903ad4 "Original: docs/benchmarks/shuffle-partition-multilevel-engines-2026-10-16.jsonl"),
[persistent hierarchical replay](../../evidence-originals.md#sha256-e8f86645d04274021a7510a599a96be619a7be34e54bd912d5c2eca534c817f5 "Original: docs/benchmarks/shuffle-partition-multilevel-persistent-2026-10-17.jsonl"),
[repeated persistent-profile matrix](../../evidence-originals.md#sha256-d6b62c119d22ca2ea992c01dd47e7265eb0443ef308e39fcb19f8f874286db94 "Original: docs/benchmarks/shuffle-partition-persistent-engines-2026-10-17.jsonl"),
[persistent extra controls](../../evidence-originals.md#sha256-340570dbcc7d40fe633abdd35167c4e729e3b15bff232865b2c1200400ffb776 "Original: docs/benchmarks/shuffle-partition-persistent-controls-2026-10-17.jsonl"),
[storage-only context diagnostic](../../benchmarks/browser-opfs-contexts-2026-10-17.jsonl),
[final temporary-context replay](../../evidence-originals.md#sha256-bb0d4190729cb67bebeac18083edde52daf7a963ae0f4f53f6dcbab758cbcf2c "Original: docs/benchmarks/shuffle-partition-temporary-replay-2026-10-17.jsonl"),
[post-fix candidate browser contracts](../../evidence-originals.md#sha256-4379013b8457885a5f8f6d61c6abe3b687ea5cb47e52886bdfdbde0456c0b42a "Original: docs/benchmarks/shuffle-partition-browser-fixed-storage-2026-10-17.json"),
[summary and measured build/source identities](../../evidence-originals.md#sha256-10220122e39eca89c6afb51e5b42da65f05f6902c2e35b26f9638da29029375c "Original: docs/benchmarks/shuffle-partition-summary-2026-10-16.json").

Reproduction (build/copy the default and feature variants from matching sources):

```sh
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-shuffle-partition
python3 scripts/benchmark-external-shuffle.py --baseline ORIGINAL --candidate FUSED \
  --baseline-allocator ORIGINAL_ALLOCATOR --candidate-allocator FUSED_ALLOCATOR \
  --rows 300000 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide --cases shuffle_partition parent_shuffle_partition \
  shuffle_partition_balanced repeated_shuffle_partition shuffle_partition_assign
python3 scripts/validate-shuffle-partition.py --baseline ORIGINAL --candidate FUSED --snapshot
# Build/copy WASI files with and without --features experimental-shuffle-partition.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs ORIGINAL FUSED ORIGINAL.wasm FUSED.wasm \
  100000 3 narrow,columns,rare_wide \
  shuffle_partition,parent_shuffle_partition,shuffle_partition_balanced original,fused 4
# Hierarchical acceptance: 1400000 1 columns shuffle_partition original,fused 4
node scripts/validate-browser-opfs.mjs
```
