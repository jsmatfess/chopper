## Compact external consumers, 2026-10-14

Final external merges and routed grouping output now decode directly into one
checked compact field buffer per row. Their final CSV and intermediate dataset
consumers avoid constructing a vector and one string per field. Owned iterator
clients retain the original decoder; intermediate encoded merges are unchanged.
The decoder checks field counts, individual/cumulative lengths, UTF-8 and
truncation before exposing views. Keys retain their existing validation and
collision ordering. Spill bytes, defaults and memory reservations are unchanged.

The initial buffer uses the old decoder's field-descriptor allowance; exact
growth adds the current payload and space for remaining descriptors. This avoids
geometric over-allocation and repeated growth for short fields after a rare wide
field. It does not reuse buffers between rows. Multiple wide fields can still
require repeated growth; broad wide-record calibration remains open. Dataset
stage ingestion, tuple keys and digesting retain their existing owned paths.

### Complete-job measurements

100,000 rows, 33 columns, AMD Ryzen AI 9 HX 370 on WSL2, warm uncontrolled storage.
Three alternating repetitions per build/case with one and four workers, followed
by separate whole-job allocator runs. Baseline binaries were rebuilt and saved
from the existing dirty workspace before editing; raw records include hashes.
Compilation and tests completed before timing. Spill/routed cases use 32 MiB;
resident controls use 1,024 MiB. Wide cases include one 1.8 MB field.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| resident / 1 | 0.263 → 0.255 |
| resident / 4 | 0.261 → 0.253 |
| spill / 1 | 0.347 → 0.295 |
| spill / 4 | 0.349 → 0.294 |
| rare_wide / 1 | 0.358 → 0.302 |
| rare_wide / 4 | 0.352 → 0.303 |
| partition_spill / 1 | 0.364 → 0.307 |
| partition_spill / 4 | 0.359 → 0.306 |
| partition_wide / 1 | 0.380 → 0.328 |
| partition_wide / 4 | 0.376 → 0.325 |
| pipeline / 1 | 0.548 → 0.555 |
| pipeline / 4 | 0.540 → 0.550 |

The affected spill/routed cases improve approximately 13–16% on this fixture.
Whole-job allocations fall by 3.3 million per case: spilled shuffle goes from
7,000,909 to 3,700,909 (one worker), while requested bytes fall only from 465.4 MB
to 462.5 MB. This primarily removes allocation churn. Spilled shuffle median CPU
time falls from 0.32 s to 0.28 s; RSS ranges are 12,880–13,068 KiB before and
12,696–12,792 KiB after. Its peak reservation remains 8,388,416 bytes. The rare-wide
shuffle adds one reallocation relative to baseline, with requested bytes falling
from 475.6 MB to 472.7 MB. Resident controls have identical allocation counts;
their small timing shifts (resident faster, composed pipeline slower) do not
establish an improvement on those paths.

Temporary traffic, peak reservations, sort runs and merge counts match each
baseline/candidate pair. All 96 native runs (72 timed and 24 instrumented) verify
identical output bytes/order, names, lineage, stage metadata and logical digests.
[Raw 100,000-row results](../../evidence-originals.md#sha256-46ad1312820edfef5a7562c353e69b559f0b58af66aa51ba1327ca34a926df0e "Original: docs/benchmarks/compact-external-native-2026-10-14.jsonl").

A 1.3-million-row rare-wide follow-up (one worker, three alternating repetitions)
uses 71 initial runs and two merge operations. Median complete-job time falls
from 5.319 s to 4.610 s (13.3%); ranges are 5.267–5.440 s and 4.570–4.629 s.
Whole-job allocations fall from 92,179,201 to 49,279,201; requested bytes fall
from 6.087 GB to 6.048 GB. Median CPU time is 5.23 → 4.54 s and peak reservation
remains 8,388,558 bytes. All eight timed/instrumented jobs match outputs and
metadata, bringing this pass to 104 verified native jobs.
[Raw multi-level results](../../evidence-originals.md#sha256-d8bedb532f8a920caf8bb35f04722605ab6439c8f01bfcbf04acd1aff5f5158a "Original: docs/benchmarks/compact-external-multilevel-2026-10-14.jsonl").

### Validation and limits

All 80 workspace tests passed with loopback access for server tests. The final
decoder growth refinement and expanded tests passed all 15 library tests;
formatting, workspace/all-target Clippy with warnings denied and the release WASI
build also passed. Decoder differential coverage includes every truncation of a
multiline Unicode fixture, corrupt counts/lengths, cumulative overflow, invalid
UTF-8 and tiny read buffers. Merge tests exercise compact, owned and encoded
consumers across composite runs, rare wide fields, corruption and cleanup.

Chromium startup failed because `libnspr4.so` is unavailable, so there is no new
browser runtime/parity evidence. No new sampled CPU stacks, browser allocation
profiles or controlled cold/slow-storage measurements were collected.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-external-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-external-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases resident spill rare_wide partition_spill partition_wide pipeline
# Multi-level follow-up: --rows 1300000 --repeats 3 --workers 1 --cases rare_wide
```
