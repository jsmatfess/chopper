## Owned CSV parser and header accounting (2026-10-15)

The next WSL-compatible accounting step adds reservations for **owned CSV job
ingestion**. Plain-output jobs retain their existing owned parsing path. String
payloads, the actual `Vec<String>` descriptor capacity, scratch capacity and
old/new allocation overlap are charged before growth. Shrinking accumulated wide
field storage also reserves the replacement while its predecessor remains live.
Malformed input or reservation denial retains charges for buffers still owned by
the parser/caller until they are dropped. The unreserved public parser adapters
remain available; this does not account the separate profiling parser.

Input headers use the same checked path. Their retained vector/string capacity
transfers to a separate reservation, conservatively overlapping the parser charge
during handoff, and remains charged through later operations and the prepared
snapshot's lifetime. `input_header_reserved_bytes` identifies that retained
charge; prepared jobs now retain headers as well as temporary-file paths. Copies
in output serializers, previews and returned analysis objects are separate scope.
Defaults, CSV framing, logical digests and seeded shuffle algorithms are unchanged.

Tests exercise exact just-below/at/above peaks with 1/7/65,536-byte reader chunks,
quoted UTF-8/CRLF fields, descriptor growth, wide fields moving between columns,
shrinking and EOF, shared reservation pressure, malformed/truncated input,
cancellation, and final-owner cleanup. Complete plain and multi-stage prepared
jobs check header reservation lifetime. **126 workspace tests, 44 combined-feature
library tests, formatting, all-feature Clippy and TypeScript checks pass.** Native
and WASI release builds pass. The final Chromium/WASI contract and benchmark
results follow below.

The initial complete-job comparison showed **21–24% slower plain output**.
Reusing a string that already fits its charged capacity now takes a fast path
without reconstructing/validating the string again or revisiting its reservation.
The initial timings are preserved separately; final measurements use this revision.

Final native measurements alternate baseline/candidate complete jobs across six
100,000-row, 33-column fixtures, one/four workers and three repetitions:
**72 timed jobs and 24 separate allocation censuses**, all with exact byte/order,
output-name, lineage, stage-statistics and logical-digest parity. Timed jobs record
CPU, peak RSS, reservations and logical temporary I/O/space. Median complete-job
seconds are **baseline → candidate**:

| Job | One worker | Four workers |
| --- | ---: | ---: |
| plain | 0.116 → 0.118 | 0.114 → 0.119 |
| plain_wide | 0.119 → 0.123 | 0.120 → 0.124 |
| resident | 0.191 → 0.188 | 0.187 → 0.186 |
| fisher | 0.190 → 0.185 | 0.189 → 0.189 |
| spill | 0.227 → 0.226 | 0.229 → 0.234 |
| partition_shuffle | 0.257 → 0.270 | 0.250 → 0.256 |

Plain-output medians cost **1.5–4.8%**; shuffle/group medians range from 2.3%
lower to 4.8% higher. These warm runs establish no throughput improvement.
One-worker plain-wide peak reservations rise from **180,548 to 3,281,044 bytes**
as owned parser storage becomes visible. Its allocator census peak is unchanged
at **5,918,994 requested live bytes**. The allocator and reservation ledger have
different scopes; output serialization and other metadata remain outside this
step. Preparation allocation traffic falls by 165 bytes on plain/plain-wide jobs
and 69 bytes on the measured operation jobs; explicit growth changes allocation
versus reallocation counts without materially changing traffic.

All **24 Chromium/WASI contracts pass**. A separate alternating native/browser
replay verifies **24 complete jobs** on 100,000-row, four-field, 256-byte-payload
fixtures: plain output, global external random-key shuffle, resident Fisher–Yates
and four-group random-key shuffle. Baseline and candidate WASM outputs also match
native bytes/order, logical digests, stages and output metadata. With two
repetitions, browser median seconds are **baseline → candidate**:

| Job | Chromium/WASI |
| --- | ---: |
| rows | 1.108 → 1.158 |
| uniform32 | 2.448 → 2.432 |
| fisher256 | 1.322 → 1.191 |
| grouped_uniform256 | 2.829 → 2.796 |

These limited browser samples are mixed and establish no general speedup. The
separate **eight 1.3-million-row complete native jobs** compare both builds and
one/four workers on spill and balanced-then-shuffle pipelines: 65/66 sort runs,
two merge operations and 66 merge inputs per job, with exact output/metadata
parity. One sample per build/worker is a multi-level correctness check, not a
variability estimate. Final evidence totals **128 verified complete-job checks**
(72 native timings, 24 allocation censuses, eight multi-level timings and
24 native/browser replays), plus the separately retained 96 initial checks.

Raw artifacts:

- [Final native timings and allocation censuses](../../evidence-originals.md#sha256-2e1b0d733194b7cf335e1cee9fe2779063e347e322de0f439f9ec4532ce059c4 "Original: docs/benchmarks/owned-parser-budget-native-2026-10-15.jsonl").
- [Native multi-level checks](../../evidence-originals.md#sha256-ded4ed7221afd0b35861af797f25a0b53f397c8233ba6fb7e449b4a5d843418f "Original: docs/benchmarks/owned-parser-budget-multilevel-2026-10-15.jsonl").
- [Alternating native/baseline-WASI/candidate-WASI replays](../../evidence-originals.md#sha256-799ec6ea263180dddf68845c8c8af9c1b6c28771a02a3b62652149ae4b155346 "Original: docs/benchmarks/owned-parser-budget-engines-2026-10-15.jsonl").
- [Chromium/WASI contracts](../../evidence-originals.md#sha256-5ffd54b63d1f9aee4354de4ddf4390130830a3b24bfbad6520a32f9cfc3ce5f3 "Original: docs/benchmarks/owned-parser-budget-browser-2026-10-15.json").
- [Initial native candidate](../../evidence-originals.md#sha256-67917210ae553a666019e31158156b3b8041bf205362338348381254540903b8 "Original: docs/benchmarks/owned-parser-budget-initial-native-2026-10-15.jsonl").
- [Derived summaries, counts and artifact hashes](../../evidence-originals.md#sha256-69198d130ec568fecb9197925ccacf343fb958fa092b91c395588bfecb0c315e "Original: docs/benchmarks/owned-parser-budget-summary-2026-10-15.json").

This is warm, uncontrolled WSL filesystem/OPFS evidence. Physical SSD/cache
calibration and other environments remain open. Decoded intermediate-input
capacity, profiling parsers, remaining conversion/shrink overlap, serializer and
header copies, previews/statistics, codecs, file/runtime metadata, thread stacks
and sorting overhead still prevent treating the ledger as a complete live-memory
or RSS cap. Returned analysis metadata outlives preparation without an aggregate
host reservation; simultaneous/prepared-job policy remains a separate open task.

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-owned-budget/before --after /tmp/chopper-owned-budget/after \
  --before-allocator /tmp/chopper-owned-budget/before-allocator \
  --after-allocator /tmp/chopper-owned-budget/after-allocator \
  --workers 1 4 --repeats 3 --rows 100000 \
  --cases plain plain_wide resident fisher spill partition_shuffle
# Multi-level check: omit allocator arguments; use --rows 1300000 --repeats 1
# and --cases spill uniform_pipeline_spill.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs /tmp/chopper-owned-budget/after \
  100000 2 rows,uniform32,fisher256,grouped_uniform256 256 \
  /tmp/chopper-owned-budget/before.wasm
```
