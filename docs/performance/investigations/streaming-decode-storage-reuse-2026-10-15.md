## Streaming decode-storage reuse, 2026-10-15

The preceding compact-streaming pass revealed one remaining payload allocation
and shrink per input row even when routing immediately writes and discards it.
The sorter now returns that checked row to its caller after successful direct
routing. The next spool decode reuses its field storage. If routing falls back
to sorting, the sorter trims and retains ownership; the caller gets no buffer.
The input row is written exactly once, with unchanged membership, ordinal and
categorical framing. Existing owned adapters and retained-row reservations remain.

A focused regression starts with a wide row and checks the same payload address
through all 64 direct routes, then checks that the 65th distinct route transfers
ownership on fallback. Final group frames conserve all IDs and exact field text,
and reservations/files release. The final WSL workspace suite passes **106 tests**,
the combined-feature library suite passes **31 tests**, and formatting, all-feature
Clippy, TypeScript and all four UI test files pass. Native/WASI release builds
and all **23 Chromium contracts** pass.
[Browser contract record](../../evidence-originals.md#sha256-6eb9d845740c80337f6c053455fe0eab1b3094c7da569e7e4204ddcedbe31f31 "Original: docs/benchmarks/streaming-decode-reuse-browser-2026-10-15.json").

The [separate native comparison](../../evidence-originals.md#sha256-08ec4be3291a6460e2f95cf4e7bd3fe09d51fe5c860fa56a813552b4e822f91b "Original: docs/benchmarks/streaming-decode-reuse-native-2026-10-15.jsonl")
uses the previous pass as baseline: 60 alternating timed jobs plus 20 allocation
censuses, 300,000 rows/33 columns, three repetitions and one/four workers. All
output/metadata fingerprints match. Warm uncontrolled WSL storage; builds,
tests and browser work completed before timing. Physical SSD I/O remains unknown.

| Complete job | Workers | Median seconds before → after | Observed seconds before / after | CPU seconds before → after |
| --- | ---: | ---: | --- | ---: |
| probabilistic pipeline, routing | 1 | 1.519 → 1.444 | 1.463–1.543 / 1.442–1.450 | 1.39 → 1.32 |
| probabilistic pipeline, routing | 4 | 1.480 → 1.472 | 1.478–1.502 / 1.432–1.484 | 1.38 → 1.37 |
| same, forced sorting | 1 | 1.542 → 1.543 | 1.534–1.651 / 1.539–1.583 | 1.41 → 1.42 |
| same, forced sorting | 4 | 1.571 → 1.642 | 1.564–1.576 / 1.587–1.648 | 1.49 → 1.55 |
| interleaved pipeline, routing | 1 | 1.457 → 1.389 | 1.428–1.491 / 1.381–1.401 | 1.33 → 1.26 |
| interleaved pipeline, routing | 4 | 1.435 → 1.402 | 1.424–1.457 / 1.374–1.422 | 1.33 → 1.31 |
| probabilistic pipeline, rare wide | 1 | 1.494 → 1.483 | 1.473–1.520 / 1.473–1.501 | 1.37 → 1.35 |
| probabilistic pipeline, rare wide | 4 | 1.534 → 1.469 | 1.487–1.539 / 1.460–1.483 | 1.44 → 1.38 |
| uniform spill pipeline, control | 1 | 0.964 → 0.975 | 0.958–0.966 / 0.963–0.992 | 0.88 → 0.88 |
| uniform spill pipeline, control | 4 | 0.973 → 0.963 | 0.957–0.973 / 0.947–0.966 | 0.91 → 0.90 |

One-worker routed probabilistic allocations fall from 1,501,567 to 1,201,569,
reallocations from 600,331 to 300,331, and requested bytes from 747.5 to
414.7 MB. Interleaved and rare-wide routing show the same nearly 300,000 fewer
allocations/reallocations. Peak live requested bytes, logical temporary traffic,
run/merge counts and reservations are unchanged. The forced-sort and uniform
control allocation profiles are identical before/after. Several timing ranges
overlap; the four-worker forced-sort control regresses 4.5% in this pass despite
identical allocation counts. Accept the measured routing allocation reduction,
with some routed complete-job gains, rather than a consistent throughput claim
across paths. The broader scale/device matrix remains open.

The [native/browser A/B record](../../evidence-originals.md#sha256-21c0c9562bf525559076f2e1e450295ba9ee078a56c53bb8ec23c18736062a5f "Original: docs/benchmarks/streaming-decode-reuse-engines-2026-10-15.jsonl")
adds 27 complete jobs: 100,000 four-column records with 128-byte payloads, three
alternating repetitions, one native worker, and browser export to OPFS. The
browser baseline is the preceding compact-streaming pass's saved WASM. Exact CSV
hashes, names/lineage, stage statistics and logical digests match across all three
engines. Browser median seconds before → after: routed probabilistic **3.696 →
3.626**, forced sort **3.826 → 3.755**, interleaved **3.106 → 3.191**. Native
candidate medians are 0.234/0.269/0.211 seconds, respectively. These results do
not establish a consistent browser speedup. OPFS call counters and WASM hashes
are recorded; physical-device traffic and controlled cache conditions are not.

Reproduce with the preceding pass's saved binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-stream-reuse-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-stream-reuse-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases streaming_pipeline streaming_pipeline_sort interleaved_pipeline \
    streaming_pipeline_wide uniform_pipeline_spill
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper \
  100000 3 balanced_probabilistic_shuffle,balanced_probabilistic_sort,balanced_interleaved_shuffle \
  128 /tmp/chopper-stream-reuse-before/engine.wasm
```
