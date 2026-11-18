## Decode storage reuse, 2026-10-14

Uniform-shuffle output without a fused balanced split now lends checked compact
rows to synchronous output sinks and reuses one decoded payload buffer across
external merge winners. Terminal balanced splitting also reuses a buffer across
rows and split boundaries within each parent. Resident rows retain their existing
storage. Existing owned iterators and sink adapters remain available; retained
sort ingestion, grouped output and fused shuffle → balanced output still use
owned compact rows. Spill framing and seeded behavior are unchanged.

Reuse consumes the previous row before decoding the next payload. Fields are
exposed only after all length, cumulative-payload, UTF-8 and truncation checks
succeed. Exact growth preserves the decoder's descriptor-plus-payload bound;
a rare wide row's capacity may remain live until this traversal ends. External
merges retain the existing single-largest-row reservation, not one buffer per run.
Dataset decoding remains part of the pre-existing non-sorter memory allowance;
this change does not claim full job allocation accounting or an RSS cap.

### Complete-job measurements

100,000 rows, 33 columns, AMD Ryzen AI 9 HX 370 on WSL2, warm uncontrolled storage.
Baseline is the immediately preceding compact-shuffle-ingestion workspace, rebuilt
before that pass ended and copied before these edits. Raw records include binary
hashes. Three alternating repetitions per case at one and four workers, then
separate allocator runs. Tests and native/WASI builds completed before timing.
`balanced_terminal` is partition → balanced(2); its wide variant puts a 1.8 MB
value in a non-key column so every group remains splittable. `uniform_pipeline_spill`
is balanced(2) → uniform. Spill and wide cases use 32 MiB; controls and ordinary
balanced output use 1,024 MiB.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| resident / 1 | 0.257 → 0.249 |
| resident / 4 | 0.256 → 0.255 |
| balanced_terminal / 1 | 0.387 → 0.385 |
| balanced_terminal / 4 | 0.383 → 0.373 |
| balanced_terminal_wide / 1 | 0.414 → 0.409 |
| balanced_terminal_wide / 4 | 0.420 → 0.415 |
| spill / 1 | 0.298 → 0.296 |
| spill / 4 | 0.298 → 0.298 |
| rare_wide / 1 | 0.312 → 0.317 |
| rare_wide / 4 | 0.324 → 0.343 |
| uniform_pipeline_spill / 1 | 0.341 → 0.337 |
| uniform_pipeline_spill / 4 | 0.343 → 0.335 |

These timings do not establish a consistent complete-job speedup: changes are
small, ranges mostly overlap, and rare-wide medians regress about 2%/6% at one/four
workers. The resident control's allocations are identical. The concrete result
is reduced allocation traffic, not a demonstrated universal throughput gain.

At one worker, terminal balanced allocations fall from 3,702,447 to 3,602,457 and
reallocations from 600,165 to 500,165. Requested bytes fall from 490.0 MB to
379.1 MB; peak live requested bytes remain 41,106,282. Its wide variant falls
from 543.2 MB to 430.5 MB requested, also with unchanged peak live requested bytes.
Spilled uniform removes 99,999 allocations (3,700,909 → 3,600,910) and reduces
requested bytes from 462.5 MB to 382.5 MB, while median CPU stays at 0.26 s and
RSS ranges overlap (12,644–13,004 → 12,708–12,764 KiB). Intermediate spilled
uniform requested bytes fall from 218.0 MB to 138.0 MB. These are cumulative
allocator requests, not equivalent reductions in resident memory.

All 96 jobs (72 timed, 24 instrumented) verify identical output bytes/order,
names, lineage, stage metadata and logical digests. Temporary traffic, peak
workspace reservations, sort runs and merge counts match. Full timing ranges,
CPU, RSS and allocation distributions are retained in the
[raw 100,000-row results](../../evidence-originals.md#sha256-e630274f4f110caf0dddd18de650b4da14fdf63b7e410db86dc35bab3db67429 "Original: docs/benchmarks/decode-reuse-native-2026-10-14.jsonl").

A 1.3-million-row rare-wide follow-up at one worker uses 71 initial sort runs and
two merge operations. Three alternating repetitions give median job times of
4.824 → 4.840 s, with ranges 4.799–4.864 → 4.767–4.923 s. Median CPU is
4.62 → 4.66 s; RSS ranges are 15,688–15,980 → 15,672–15,988 KiB. Allocations fall
from 49,279,201 to 47,979,202 and requested bytes from 6.048 GB to 5.008 GB.
Reallocations and peak live requested bytes are unchanged. Temporary traffic,
run/merge counts and the 8,388,558-byte peak workspace reservation match.
All eight timed/instrumented jobs match outputs and metadata, bringing this pass
to 104 verified jobs. This larger case likewise establishes allocation reduction
without a throughput improvement.
[Raw multi-level results](../../evidence-originals.md#sha256-a6d1abef0e8521a7dc67734f41c72e2bc25ea43d13e6583dbeebdc98126e57cc "Original: docs/benchmarks/decode-reuse-multilevel-2026-10-14.jsonl").

### Validation and remaining scope

All 84 workspace tests passed, including loopback server tests. New coverage
checks that a wide buffer keeps the same allocation across subsequent small and
wide records. Extended differential coverage compares fresh/reused/owned decoding
across every truncation of a Unicode fixture, corrupt counts and lengths,
cumulative overflow, invalid UTF-8 and tiny read buffers. Composite-run merge
coverage exercises reused output and injected sink failure after a wide row,
checking file and workspace cleanup. Dataset reuse preserves spool bytes and EOF
behavior. Existing seeded-order, strict-cap, cancellation and publication tests
pass. Formatting, workspace/all-target Clippy with warnings denied and release
WASI compilation pass. No new browser runtime or sampled CPU-stack evidence was
collected; storage remains warm and uncontrolled.

Grouped/routed output and fused-balanced consumers still need integration with
reusable decoding. Parser/digest, buffer-shuffle and streaming-router ingestion
remain separate conversion follow-ups in TODO. Broad source-width/cardinality
calibration and controlled-storage evidence remain open.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-decode-reuse-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-decode-reuse-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases resident balanced_terminal balanced_terminal_wide spill rare_wide uniform_pipeline_spill
```

For the multi-level comparison, replace the last two lines with
`--rows 1300000 --repeats 3 --workers 1 --cases rare_wide`.
