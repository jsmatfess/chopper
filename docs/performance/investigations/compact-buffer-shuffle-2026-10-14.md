## Compact buffer shuffle, 2026-10-14

Buffer shuffling now retains `PackedRow` values through random replacement,
final serialization and intermediate dataset writes. Intermediate input uses the
checked compact decoder. Fused CSV ingestion returns narrow field storage to the
parser after packing; wide fields retain the existing direct ownership transfer.
Random draws, replacement/drain order, row IDs, output ordinals and spill framing
are unchanged. Workspace reservations now account for compact rows and vector
slack under the same quarter-budget ceiling. This is not full allocation accounting
or an RSS cap; parser and output buffers remain outside that reservation.

### Complete-job measurements

100,000 rows, 33 columns, buffer capacity 1,000, 32 MiB, AMD Ryzen AI 9 HX 370,
WSL2, warm uncontrolled storage. `buffer_pipeline` is balanced(2) → buffer shuffle;
wide variants contain one 1.8 MB field. The uniform resident control uses 1,024 MiB.
The baseline was built and saved from the existing workspace before these edits;
raw records include executable hashes. Three alternating repetitions per case at
one and four workers, then separate allocation runs. All builds and tests finished
before measurement.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| buffer / 1 | 0.213 → 0.163 |
| buffer / 4 | 0.217 → 0.167 |
| buffer_pipeline / 1 | 0.303 → 0.248 |
| buffer_pipeline / 4 | 0.302 → 0.250 |
| buffer_wide / 1 | 0.217 → 0.164 |
| buffer_wide / 4 | 0.212 → 0.154 |
| buffer_pipeline_wide / 1 | 0.305 → 0.245 |
| buffer_pipeline_wide / 4 | 0.295 → 0.248 |
| resident control / 1 | 0.260 → 0.260 |
| resident control / 4 | 0.252 → 0.259 |

Buffer-job medians improve about 16–27% on this fixture, with nonoverlapping
before/after ranges. The resident control has overlapping ranges and unchanged
allocation profiles. This is a warm-storage observation, not a general throughput
promise or evidence for parallel execution.

At one worker, fused narrow buffer allocations fall from 3,400,870 to 100,905;
reallocations from 400,042 to 46; requested bytes from 324.6 MB to 31.5 MB;
and peak live requested bytes from 2,117,574 to 634,891. Peak workspace reservation
falls from 1,896,000 to 453,000 bytes. Its wide variant requests 334.1 → 41.0 MB
and has peak live requested bytes of 7,783,088 → 6,300,764.

Intermediate narrow buffer allocations fall from 3,401,023 to 101,023 and peak
live requested bytes from 1,123,997 to 611,950. However, reallocations rise from
64 to 100,064 and cumulative requests from 84.3 MB to 112.3 MB. Checked compact
decoding grows a framed buffer per retained row; fewer allocations do not mean
fewer requested bytes. The intermediate wide variant similarly requests
97.4 → 127.2 MB, while peak live requested bytes fall 6,522,630 → 6,010,110.
Recycling displaced rows into decode storage remains a separate follow-up.

All 80 jobs (60 timed, 20 instrumented) verify identical bytes/order, names,
lineage, stage metadata and logical digests. Temporary traffic and sort/merge
counts are unchanged. Full timing ranges, CPU, RSS, reservations and allocation
size distributions are in the [raw results](../../evidence-originals.md#sha256-93d9ab144dfd445606c781634cee79fe667fea93a00984f356fe7c32746c3d09 "Original: docs/benchmarks/compact-buffer-native-2026-10-14.jsonl").

### Validation and remaining scope

All 86 workspace tests pass, including existing v1 buffer-fusion fixtures, strict
caps, malformed CSV, cancellation and publication checks. A new differential test
compares compact replacement and drain order against the owned algorithm at
capacities 1, 3 and 64, with Unicode, quoting, NUL, empty and wide fields and
workspace cleanup. The existing buffer cancellation/budget failure test now
exercises compact rows. Formatting, workspace/all-target Clippy with warnings
denied, and native/WASI release builds pass. Server tests required localhost
access. No browser runtime, sampled CPU stacks, cold storage or multi-level merge
benchmark was collected in this pass; buffer shuffling itself does not merge runs.
Parser/digest and streaming-router compact ingestion remain open.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-buffer-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-buffer-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases buffer buffer_pipeline buffer_wide buffer_pipeline_wide resident
```
