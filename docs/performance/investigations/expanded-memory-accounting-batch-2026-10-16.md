## Expanded memory accounting batch (2026-10-16)

This batch closes several parts of the resident/external accounting backlog
together. It preserves algorithms, random-key v1 ordering, collision refinement,
spill framing, the profile JSON schema and metadata selection policies. It does
not turn the algorithm ledger into a complete process-memory/RSS cap.

The implementation now covers:

- Profiling column-summary arrays, sorted distinct-value strings/descriptors,
  live cardinality sketches, operation-selection vectors, deduplicated composite
  key indices/counts, retained cache-key path/options capacity, stage strings and
  accuracy text. Bounded sorted vectors replace profiling trees, keeping their
  lexicographic serialized order and historical 100-value/256 KiB selection
  policy. Independently returned profiles reserve all their retained observation
  payloads, including headers/previews from the previous pass. Selection/sketch
  workspaces coexist with retained observations during the full-file scan.
- Actual merge/routed payload and key capacity, including decoder growth/reuse
  overlap and winning/replacement headers. The former largest-row merge allowance
  is removed. Returned rows retain their reservations independently of their
  iterator, and cursor reuse keeps the live wide payload charged. Routed output
  releases obsolete bucket writer/tree allowances before reserving its reader.
- Merge reader-vector and heap-head capacity before allocation, reconciled to
  allocator-provided capacity, plus a fixed sort-order metadata allowance. The
  routing eligibility probe uses a sorted 64-entry stack array, removing its
  transient heap tree without changing route limits or fallback decisions.
- Owned input packing and compact-to-owned materializing adapters while source
  and destination allocations coexist. Owned sorted, resident, merge and routed
  iterators now return `DecodedRow` wrappers, borrowing the underlying `Row`
  while retaining its reservation. Resident and buffer-shuffle emissions transfer
  heap charges out of their containers without releasing/reacquiring the budget.
  Public constructors of arbitrary caller-owned raw `Row`/`PackedRow` values are
  not a process-wide allocation interception mechanism. `PackedRow::unpack`
  remains a raw compatibility API; budgeted iterators/adapters use the
  reservation-carrying conversions.
- Experimental prefix redistribution/fallback readers and actual decode capacity
  through row reuse and sorter handoff, replacing their coarse decode allowance.

A shared vector-growth helper charges existing and replacement arrays together
before allocation, preserves unrelated payload charges and rolls back denied
requests without changing the vector. String copies reserve before filling.
Source and destination guards are independent; failures discard partial copies
while preserving the original cached/source data. Cache-key filesystem/JSON
construction scratch is outside the retained key charge.

Seven new tests exercise complete profile metadata peak boundaries and composite
selection deduplication; returned stage/key retention; aggregate vector growth
with competing reservations; source/destination adapter overlap; emitted buffer
row lifetimes; owned resident/merge/routed results after iterator destruction;
and compact merge payloads after merge destruction. Existing tests were updated
to assert reservations remain live while results are retained, and include
owned/compact payload capacity in winning/replacement-key boundaries. Existing
forced collisions, late-wide rows, shared-pressure spill/failure, malformed
input/spills, cancellation, output caps and publication tests remain in place.
All 155 workspace tests, 73 combined experimental-feature library tests and 24
Chromium/WASI contracts pass. Formatting, Clippy with warnings denied and
native/WASI release builds pass. HTTP/Chromium checks use loopback access;
Chromium uses the staged libraries under
`/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

The remaining boundary is explicit: operation-key construction and partition
key/domain/lineage caches; group-catalog JSON/lineage materialization; output
serialization, codec and input-adapter allocations; temporary-file construction
scratch; and native Rayon/thread/runtime allocations are not fully charged.
Comparison sorting still uses the existing unstable algorithms and native
worker pool; this batch covers its visible row/merge arrays, not all runtime
bookkeeping. Independent profiling/preparation workspaces and simultaneous
prepared/active jobs still need a shared host-aware policy. Allocator metadata,
thread stacks and RSS require separate accounting/measurement. Target-SSD
calibration and other-platform acceptance remain outside this WSL pass.

Native execution controls cover 100,000 presorted 33-field rows, ten pipelines,
one/four workers and three alternating repetitions: all 120 timed jobs and 40
separate allocation censuses preserve exact output bytes/order, file metadata,
stages and logical digests. These native records were captured before the final
profile-only capped-column lookup fix; execution pipeline code did not change
between those revisions. Raw hashes distinguish the builds. Median time changes
for that execution-path comparison:

| Pipeline | One worker | Four workers |
| --- | --- | --- |
| `resident` | +9.9% | +3.9% |
| `fisher` | +2.6% | +2.0% |
| `spill` | -0.9% | +2.9% |
| `rare_wide` | -2.2% | -0.9% |
| `partition` | +1.1% | +1.2% |
| `balanced_terminal` | -1.4% | -1.5% |
| `streaming_pipeline` | -0.7% | -0.1% |
| `streaming_pipeline_sort` | -0.5% | -1.5% |
| `buffer_pipeline_wide` | +8.0% | -0.4% |
| `uniform_pipeline_spill` | -0.7% | -0.3% |

The native 1.4-million-row rare-wide control produces 67 sort runs and two merge
operations on both builds/workers, exercising hierarchical merging with a live
wide decoded row. All eight timed jobs and four allocation censuses preserve
exact output/metadata. One/four-worker medians change by -2.4% / -1.1%. Allocation
traffic and requested-allocation peaks are unchanged on this fixture: 822.37 MB
requested over the job and a 10.71 MB peak of live requested allocations for one
worker. Requested allocator bytes are not RSS; the overall workspace peak is
ingestion-dominated and unchanged. Named-column selection avoids its old small
matches-vector allocation (the one-worker partition census requests 192 fewer
bytes); most execution-path allocator totals remain unchanged.

An initial profiling comparison revealed that the sorted-vector implementation
searched retained values even after a column's metadata cap was reached. The
old tree path skipped this work. The final profile-only revision restores that
skip; initial records are retained separately. Final profiling and engine
comparisons use the revised native/WASI binaries. This is accounting work with
no throughput-improvement claim. Runs use warm uncontrolled WSL/OPFS storage;
physical SSD I/O/cache conditions are not measured. Reported timing workloads run separately from builds/tests; the initial engine experiment is retained for parity
history, not used for final timing conclusions.

Final profiling controls use three alternating repetitions of 100,000-row narrow,
33-field and late-wide fixtures on native and Chromium/WASI, with 32 MiB memory
and one native worker. All 36 fresh profiles, 18 browser cache replays and 36
complete jobs preserve exact profiles (excluding timing/hit fields), output
bytes/order, stages, metadata and logical digests. Fresh-profile medians after
removing the redundant capped-column lookup:

| Fixture | Native seconds, before → after | Browser seconds, before → after |
| --- | --- | --- |
| `narrow` | 0.0269 → 0.0299 (+11.3%) | 0.0618 → 0.0622 (+0.6%) |
| `many` | 0.1238 → 0.1376 (+11.2%) | 0.2761 → 0.2564 (-7.1%) |
| `late_wide` | 0.0332 → 0.0377 (+13.9%) | 0.0733 → 0.0735 (+0.3%) |

The native profiling overhead is still measurable; accounting correctness is the
benefit here. Native profile CPU/process peak RSS, cache-replay time and full-job
resource diagnostics are recorded. Browser CPU/allocation/RSS are unmeasured.
Timings include their respective native-process/browser-adapter overheads, so
cross-runtime elapsed times do not isolate the decoder or profiling loop.

Final browser comparisons add 36 native/baseline-WASI/candidate-WASI complete
jobs across external uniform shuffle, routed partition and automatic/forced-sort
probabilistic pipelines. All preserve exact output bytes/order, metadata and
digests. Chromium whole-job medians (100,000 four-field rows, 128-byte payloads,
three alternating repetitions):

| Pipeline | Browser seconds, before → after | Change |
| --- | --- | --- |
| `uniform32` | 1.5069 → 1.4383 | -4.6% |
| `balanced_partition` | 1.8241 → 1.8532 | +1.6% |
| `balanced_probabilistic_shuffle` | 4.0431 → 4.0291 | -0.3% |
| `balanced_probabilistic_sort` | 4.0429 → 3.9859 | -1.4% |

In the reported controls, 200 timed complete jobs and 44 allocation censuses
preserve exact output/metadata, with 36 additional fresh-profile and 18 cached
profile checks. These counts exclude the separate initial profile/engine
experiments. The hierarchical merge control is native-only; browser/device,
physical storage and larger-scale acceptance remain open.

Artifacts: [native timings/allocation censuses](../../evidence-originals.md#sha256-dcb433b57654ee093a67b0dd3e727a51011f380e9c404c0268aac681f412e781 "Original: docs/benchmarks/accounting-batch-native-2026-10-16.jsonl"),
[hierarchical merge](../../evidence-originals.md#sha256-c3de488a3beb155b09187b6c00cac20b954ea393b1d6ae6d795dc694ee1ef843 "Original: docs/benchmarks/accounting-batch-multilevel-2026-10-16.jsonl"),
[final profiles/cache/jobs](../../evidence-originals.md#sha256-68c71edf61708592284a9c337cc1737143dba81bcd428072bf4bdb58cc65cc58 "Original: docs/benchmarks/accounting-batch-profiling-2026-10-16.jsonl"),
[final native/WASI jobs](../../evidence-originals.md#sha256-4a8560708f49538ca1a879b0cbdb232021ba5b00c078c76379b99bc70bff24e1 "Original: docs/benchmarks/accounting-batch-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-7d5c240c25005c66fbad060918cd93ca32127e1ff509efe4975bbae2a101825b "Original: docs/benchmarks/accounting-batch-browser-2026-10-16.json"),
[summary/build hashes](../../evidence-originals.md#sha256-a9dbb3929f5394c3d90f939a922be44a319281896b1f0e7c064079de8573eb0f "Original: docs/benchmarks/accounting-batch-summary-2026-10-16.json").
[Initial profiling](../../evidence-originals.md#sha256-8fc2482c21806768db5e303ec6b2f0c8187f180e298c8b03e39368a6211a1703 "Original: docs/benchmarks/accounting-batch-initial-profiling-2026-10-16.jsonl")
and [initial engine records](../../evidence-originals.md#sha256-b93c5d2cc9bc8acd15a69e98e982dcdcf78eb80ad888f84886035bd70db70c09 "Original: docs/benchmarks/accounting-batch-initial-engines-2026-10-16.jsonl")
retain the preceding revision. The allocator baseline was built from isolated
pre-batch source copies; native CLI and WASM baselines were saved before editing.

Reproduce after preserving baseline native, allocator-example and WASM binaries,
then building candidate native/allocator and WASI releases:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases resident fisher spill rare_wide partition balanced_terminal streaming_pipeline \
  streaming_pipeline_sort buffer_pipeline_wide uniform_pipeline_spill
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 1400000 --workers 1 4 --repeats 2 --cases rare_wide
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-profiling-budget.mjs BEFORE BEFORE.wasm 100000 3
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  uniform32,balanced_partition,balanced_probabilistic_shuffle,balanced_probabilistic_sort 128 BEFORE.wasm
```
