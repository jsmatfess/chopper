## Compact external-spill block evaluation (2026-10-16)

**Keep v1 row framing as the default.** The opt-in
`experimental-spill-blocks` candidate reduces stored spill bytes and improves the
active Chromium/OPFS cases, but costs substantial CPU and complete-job time on
warm native WSL storage. No default-format or compression change is made.

The [format and interface](../../spill-block-experiment.md) store bounded blocks with
shared field-count metadata and u32 key/field lengths. A forward-only footer
checks row counts without header patches/seeks. Individual lengths must fit u32
in this prototype. The adapter reconstructs the exact v1 byte stream for existing
consumers; input text, IDs, ordinals, keys, comparator/collision refinement and
seeded operation versions remain unchanged. It covers external sort runs,
routed buckets and experimental prefix files. Intermediate datasets and encoded
CSV snapshots retain their existing formats.

Writer buffering moves inside the block adapter and spends the caller's existing
I/O grant, rather than adding a second payload buffer. Readers divide the same
64 KiB grant between encoded input, reconstructed v1 input and decoder-box
capacity. Wide payloads stream; no block/field-sized allocation is retained per
merge head. Encoder metadata has an independent reservation through file drop;
optional constructor denial falls back to raw v1 for that file. Stream failures
are terminal and discard job state. Five new tests cover changing/zero field
counts, arbitrary source chunks, multiple blocks, wide Unicode, unsupported
versions/tags/counts/lengths, truncation/UTF-8, cancellation, capacity edges,
fallback/retry, append, reader lifetime and exact disk-quota edges. The existing
write-once test now normalizes stored bytes to logical v1 traffic, and external
selection recognizes either merge runs or prefix distribution.

**199 default workspace tests, 204 all-feature workspace tests, 118 all-feature
library tests, 24 candidate Chromium/WASI contracts, formatting and default /
all-feature all-target workspace Clippy with warnings denied pass.** Paired
native and WASI release builds use identical sources, differing only in
`experimental-spill-blocks`. Default native/WASI development artifacts are
restored after comparisons.

### Complete-job native measurements

The final native-only comparison contains **168 timed complete jobs and 56
separate allocation censuses**, with one/four workers and three alternating
repetitions. Every run preserves exact CSV bytes/order, filenames, lineage,
stage statistics and logical digest. The primary 300,000-row comparison
independently verifies each ID, every field and balanced-group range isolation
for narrow (two fields), many-column (33 fields) and rare-wide (1.8 MB plus 33
fields) inputs. Global, four-group and downstream-balanced shuffles all actually
use block files; no constructor fallback occurs in the measured matrices.

| Native fixture matrix | Timed jobs / censuses | Complete-job median change |
| --- | ---: | ---: |
| Three shapes, global/grouped/downstream-balanced, 300,000 rows | 108 / 36 | +10.1% to +25.7% |
| Many-column global shuffle, 1.4 million rows, 77 runs / hierarchical merge | 12 / 4 | +45.7% to +46.2% |
| Partition/spill/wide keys, exact-assignment and streaming fallback, 100,000 rows | 48 / 16 | +14.8% to +23.5% |

These are measured regressions for this adapter, not evidence that every compact
format must regress. Sorting and row memory still use the existing v1
representation. Transcoding the existing stream is additional work; the
experiment does not measure direct compact consumers or smaller resident field
frames. GNU CPU time, sort-loop/stage timing, peak RSS, allocator traffic,
reservations and temporary I/O/space remain in the raw data.

| Primary shape | Stored block bytes versus the corresponding v1 spill bytes |
| --- | ---: |
| Narrow | −20.7% |
| Many-column | −38.8% |
| Rare-wide | −38.2% |

Complete-job engine write traffic falls by 9.9–31.4% in the primary matrix,
including unchanged intermediate datasets and CSV snapshots. One-worker peak
engine temporary bytes fall by 3.8–31.4%; grouped intermediates limit savings.
The 1.4-million-row point reduces write traffic by 34.3% and peak engine temporary
bytes by 38.8%. Stored file bytes and engine counters are not physical SSD
traffic, filesystem extent allocation or power-loss evidence. GNU filesystem
block counters are also retained without treating WSL guest values as device
byte measurements.

At one worker, the primary census adds 21–60 allocations and 1,400–4,000 requested
bytes per complete job, with no additional reallocations. Reader allocations
change shape but their combined requested capacity stays within the same fixed
grant. Encoder-box/file-count overhead persists through file lifetime. The
larger census includes additional discovery and catalog work; use its exact
profile rather than extrapolating the small-job allocation delta. These censuses
are separate from ordinary timings and do not measure allocator internals/RSS.

### Chromium/WASI and hierarchical pipeline validation

The repeated runtime comparison adds **108 verified complete jobs** at 100,000
rows: three shapes, global/grouped/downstream-balanced, three alternating
repetitions across native v1/block and Chromium-WASI v1/block builds. It
independently checks IDs, field text and group isolation, and compares output
bytes/order and logical metadata across both formats and runtimes. All eight
active external browser cases improve by **2.4–23.0%** in median complete-job
time; the narrow grouped resident control has zero block rows and changes by
+0.2%. Counter evidence distinguishes actual block use from that control.

| Shape | Browser global / grouped / balanced median change |
| --- | ---: |
| Narrow | −8.7% / +0.2% (resident) / −2.4% |
| Many-column | −19.6% / −8.0% / −23.0% |
| Rare-wide | −19.9% / −7.7% / −5.6% |

A separate **four-job single-point validation** runs 1.4-million many-column rows
through shuffle → four balanced groups → shuffle → three balanced groups. It
verifies exact fields/IDs/CSV/metadata across paired native and WASI builds,
including 157 native / 142 WASI total runs and hierarchical merging. Run counts
match within each runtime; target descriptor widths can change counts between
runtimes. Recorded wall times are 6.84/9.10 seconds native and 77.48/65.44 seconds
browser (v1/blocks). This single point is structural/runtime evidence, not a
variability or general throughput claim.

All normal timing matrices run after builds/tests finish. Cache state is warm
and uncontrolled. These OPFS results do not calibrate physical SSDs or other
browser/device configurations, and browser CPU/allocation/RSS profiling remains
open. The browser gains justify retaining the opt-in experiment; native costs,
prototype bounds and remaining resource/platform coverage prevent a default
promotion. Compression remains separate pending controlled storage evidence.

Artifacts: [native shapes](../../evidence-originals.md#sha256-6cbf477d844d8f504bd66f89b9964f4bec9978c7b5cb314df841d896a523a6e2 "Original: docs/benchmarks/spill-blocks-native-2026-10-16.jsonl"),
[native hierarchy](../../evidence-originals.md#sha256-4d0fd45719cde5c74cb5199349a91869a86eb9a74acc8416fe4dae8ea6fa16e1 "Original: docs/benchmarks/spill-blocks-multilevel-2026-10-16.jsonl"),
[operation paths](../../evidence-originals.md#sha256-bc9bc99a79a226d921535db34111f076c23fe19fb8f6678f7b9977b6b9c56113 "Original: docs/benchmarks/spill-blocks-operations-2026-10-16.jsonl"),
[candidate browser contracts](../../evidence-originals.md#sha256-f116b4b43f84a70b46121739b34d1775b3194afa19601b7fbfe4eb5a3c8fcfba "Original: docs/benchmarks/spill-blocks-browser-2026-10-16.json"),
[repeated native/WASI comparison](../../evidence-originals.md#sha256-6931e432d24dfb5b0a60ba843db79e9b793a6f51934909f34ca714b3f2906d10 "Original: docs/benchmarks/spill-blocks-engines-2026-10-16.jsonl"),
[large two-shuffle point](../../evidence-originals.md#sha256-d5705468d2b26962bd43e229432a77d0edf6a1d035e601e2671b2a159c3988b2 "Original: docs/benchmarks/spill-blocks-multilevel-engines-2026-10-16.jsonl"),
[summary, ranges and hashes](../../evidence-originals.md#sha256-7f0043c1c843391ae467fb9664c6df78491b6a68d45f6d995184d0acd3e114d2 "Original: docs/benchmarks/spill-blocks-summary-2026-10-16.json").

```sh
# Build/copy native and WASI v1 first; repeat with --features experimental-spill-blocks.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
bash scripts/build-browser.sh
python3 scripts/benchmark-external-shuffle.py --baseline V1 --candidate BLOCKS \
  --baseline-allocator V1_ALLOCATOR --candidate-allocator BLOCKS_ALLOCATOR \
  --rows 300000 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide --cases global grouped balanced
# Native hierarchy: --rows 1400000 --shapes columns --cases global
python3 scripts/benchmark-compact.py --before V1 --after BLOCKS \
  --before-allocator V1_ALLOCATOR --after-allocator BLOCKS_ALLOCATOR \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases partition_spill partition_wide assign_pipeline_spill streaming_pipeline_sort
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs V1 BLOCKS V1.wasm BLOCKS.wasm \
  100000 3 narrow,columns,rare_wide global,grouped,balanced v1,blocks
# Large runtime point: 1400000 1 columns multistage v1,blocks
```
