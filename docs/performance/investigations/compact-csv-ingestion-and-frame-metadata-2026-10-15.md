## Compact CSV ingestion and frame metadata, 2026-10-15

Operation pipelines now parse validated UTF-8 fields into one compact allocation,
using the existing CSV state machine and the same record working-limit checks.
The compact encoding is the existing v1 count/length/text stream: logical hashing
can consume it directly, and retained/spooled rows take ownership without first
constructing owned field strings. Immediate consumers return storage to the parser;
retained rows trim spare capacity. A previous-record allocation hint, capped at
64 KiB, avoids growing once per short field after transferring ownership. Column
summaries scan selected compact fields in order. Headers and the separate input
profiler retain their owned adapters. **Plain-output jobs retain the previous
owned parser/serializer path**, which already reuses storage without packing.
No seeded algorithm, format, output limit or default shuffle strategy changes.

Checked packed rows now calculate payload size, owned-adapter merge allowance and
disk frame length directly from validated count/length metadata, avoiding repeated
field iteration/UTF-8 checks just to count bytes. Constructors/decoders still validate
all field text, lengths, truncation and cumulative limits; private packed storage
cannot be supplied by unchecked external bytes. This pass adds no unsafe code and
no new on-disk format. It is a combined parser/framing change: measurements below
do not isolate direct parsing from the constant-time frame-size calculations.

The first candidate was rejected after the [initial native experiment](../../evidence-originals.md#sha256-4f345b2a6920c912ac0530e69bc52ea94b9e3c8a7bd4bf5ac1a06d261b369a83 "Original: docs/benchmarks/compact-parser-initial-native-2026-10-15.jsonl"):
96 alternating timed jobs and 32 allocation censuses, eight cases, one/four workers,
300,000 rows and three repetitions. Exact output/metadata matched, but plain-output
medians rose **0.330 → 0.380** seconds with one worker and **0.330 → 0.367** with
four. Resident random-key, partition and forced partition spilling also regressed.
It avoided field strings but still repeatedly scanned compact fields for accounting.
Its [23 browser contracts](../../evidence-originals.md#sha256-f45b71ed58f740a6d2ba9df0c682c6b1efac59228d06b966e92090278516bed2 "Original: docs/benchmarks/compact-parser-initial-browser-2026-10-15.json")
passed; correctness alone was not grounds for promotion. The final implementation
keeps the plain path and uses checked frame metadata for byte counts.

The [final native comparison](../../evidence-originals.md#sha256-202ea67a2116d9a8d79baff95dd628bdf3c76a8e71eab0cfb598d84a4937b1f6 "Original: docs/benchmarks/compact-parser-native-2026-10-15.jsonl")
contains another 96 alternating timed jobs and 32 allocation censuses against the
preceding catalog-accounting build, again with 300,000 rows, 33 fields, one/four
workers and three repetitions. All exact CSV bytes/order, output names/lineage,
stages and logical digests match. Tested operation medians improve about **2–13%**;
plain-output medians are close. CPU, RSS, full timing ranges, reservations and
logical temporary I/O/space remain in the raw records. These warm, uncontrolled
WSL filesystem results are not physical SSD calibration or a universal speedup.
All builds, tests and browser work finished before these final timed runs.

| Complete job | Workers | Median seconds before → after |
| --- | ---: | ---: |
| plain output | 1 / 4 | 0.316 → 0.316 / 0.312 → 0.317 |
| resident random-key | 1 / 4 | 0.564 → 0.547 / 0.572 → 0.513 |
| resident Fisher–Yates | 1 / 4 | 0.580 → 0.553 / 0.595 → 0.530 |
| partition, resident | 1 / 4 | 0.630 → 0.616 / 0.593 → 0.577 |
| partition, spill | 1 / 4 | 0.621 → 0.603 / 0.615 → 0.595 |
| exact assignment | 1 / 4 | 0.775 → 0.703 / 0.772 → 0.693 |
| streaming, forced sorting | 1 / 4 | 1.610 → 1.437 / 1.588 → 1.516 |
| global shuffle, rare wide | 1 / 4 | 0.694 → 0.650 / 0.744 → 0.651 |

This is primarily reduced conversion/scanning work, **not a per-row allocation
reduction** over the previous parser-storage reuse. Ordinary one-worker operation
jobs remove only 33 allocations for reusable field storage; plain-output profiles
are identical. Requested allocation traffic is mixed: resident random-key/Fisher–
Yates/partition add 2,691 bytes, assignment/streaming remove 2,224 bytes, and partition
spilling adds 1,681,595 bytes. The rare 1.8-million-byte wide row adds **7,264,414
requested bytes**, with peak live requested bytes **8,635,737 → 10,699,593** (one
worker): compact parsing copies its field scratch into the row instead of the
previous wide-field ownership transfer. Other one-worker peaks are unchanged or
slightly lower. The existing working-limit checks and shared retained-row ledger
remain; parser/scratch capacity, conversion overlap and full RSS accounting are
still open. Compact parsing does not close complete working-set selection.

New differential tests compare owned/compact fields, exact error messages, record
counters and working limits for empty/blank/trailing fields, CRLF, multiline quotes,
custom escapes, malformed quotes, bare CR and invalid UTF-8 at buffer sizes 1/2/7/
65,536 and eleven working limits. Separate reuse tests move wide fields between
columns through UTF-8, UTF-16LE and Shift_JIS decoding. Logical-digest tests cover
empty input, framing and large-field/batch boundaries. Existing seeded fixtures,
collisions, mixed-group budgets/workers, strict output caps, malformed spills,
cancellation and publication cleanup remain passing. Final validation: **113
workspace tests**, **36 combined-feature library tests**, all-feature Clippy,
formatting, TypeScript checking, native/WASI release builds and all **23 Chromium/
WASI contracts** pass. [Browser contract record](../../evidence-originals.md#sha256-c035a60b4c5b7eaa15f70a17ca14f56bcdb590dfff228bceea81a3a434eb1e65 "Original: docs/benchmarks/compact-parser-browser-2026-10-15.json").

The [larger native comparison](../../evidence-originals.md#sha256-f6b78a6bc59ce4074564b2c6e6aad6db9d63398a07b7fc1df8fcca2c25f2fe4a "Original: docs/benchmarks/compact-parser-multilevel-2026-10-15.jsonl")
adds 24 alternating timed jobs and eight allocation censuses: 1.3 million 33-field
rows, 32 MiB, global random-key shuffle and global shuffle followed by four balanced
outputs, one/four workers and three repetitions. Every job still uses **65 initial
runs, two merge operations and 66 merge inputs**. Exact output/metadata, logical
temporary traffic and temporary-space peaks are unchanged. Median seconds before
→ after: global **3.774 → 3.553** (one worker), **3.860 → 3.691** (four); balanced
**3.841 → 3.665**, **3.823 → 3.618**. Full ranges and resource profiles are recorded.
These runs extend multi-level acceptance without claiming physical-device throughput.

Reproduce the final native comparison against the preceding catalog-accounting
build, with both builds saved before later experiments:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-run-catalog-after/chopper \
  --after /tmp/chopper-compact-parser-after/chopper \
  --before-allocator /tmp/chopper-run-catalog-after/allocation-profile \
  --after-allocator /tmp/chopper-compact-parser-after/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases plain resident fisher partition partition_spill assign \
    streaming_pipeline_sort rare_wide
# Same arguments with --rows 1300000 --cases spill fused_balanced_spill
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-compact-parser-after/chopper \
  100000 3 rows,uniform32,uniform256,partition,balanced_probabilistic_sort 256 \
  /tmp/chopper-run-catalog-after/engine.wasm
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs \
  /tmp/chopper-run-catalog-after/chopper /tmp/chopper-compact-parser-after/chopper \
  /tmp/chopper-run-catalog-after/engine.wasm /tmp/chopper-compact-parser-after/engine.wasm \
  1300000 1 columns global,balanced,multistage before,after
```
