## Grouped decode storage reuse, 2026-10-14

Partition, exact assignment, streaming grouping (including sorting fallback), and
fused uniform-shuffle → balanced output now borrow checked compact rows from a
lending cursor. External merge and routed readers reuse one decoded payload across
group and split boundaries. Resident rows keep their reserved storage. The existing
owned row iterator and sink adapters remain available; obsolete internal compact
wrappers were removed. Spill framing, random keys, collision refinement, allocation
membership, empty groups and ordinal conventions are unchanged.

The cursor exposes fields only after checked decoding completes. The next read
cannot begin while a consumer holds a borrowed row. The existing largest-row
reservation covers the external buffer; a rare wide row's capacity can remain live
until traversal ends. This preserves the existing allowance, not a complete job
allocation bound or an RSS cap. Parser/digest, buffer-shuffle and streaming-router
ingestion still have conversion work to measure separately.

### Complete-job measurements

100,000 rows and 33 columns, AMD Ryzen AI 9 HX 370 on WSL2, warm uncontrolled
storage. The baseline was rebuilt and saved from the preceding workspace before
these edits. Binary hashes are recorded. Three alternating repetitions per case
at one and four workers, followed by separate allocator runs; tests and native/WASI
builds finished before timing. Spill/wide cases use 32 MiB, other cases 1,024 MiB.
Wide cases include a 1.8 MB field. `assign_pipeline_spill` is balanced(2) → exact
assignment → uniform; `pipeline` is uniform → balanced(4) → partition.
`probabilistic_route` uses automatic grouping, while `probabilistic_sort` forces
comparison sorting and remains resident on this fixture.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| resident / 1 | 0.261 → 0.263 |
| resident / 4 | 0.260 → 0.263 |
| partition_spill / 1 | 0.312 → 0.306 |
| partition_spill / 4 | 0.314 → 0.318 |
| partition_wide / 1 | 0.323 → 0.328 |
| partition_wide / 4 | 0.332 → 0.327 |
| assign_pipeline_spill / 1 | 0.360 → 0.363 |
| assign_pipeline_spill / 4 | 0.367 → 0.358 |
| probabilistic_route / 1 | 0.221 → 0.219 |
| probabilistic_route / 4 | 0.216 → 0.219 |
| probabilistic_sort / 1 | 0.276 → 0.272 |
| probabilistic_sort / 4 | 0.269 → 0.270 |
| fused_balanced_spill / 1 | 0.310 → 0.308 |
| fused_balanced_spill / 4 | 0.310 → 0.315 |
| fused_balanced_wide / 1 | 0.314 → 0.312 |
| fused_balanced_wide / 4 | 0.316 → 0.315 |
| pipeline / 1 | 0.499 → 0.501 |
| pipeline / 4 | 0.502 → 0.491 |

There is no consistent complete-job throughput improvement: medians move roughly
−3% to +2%, with mostly overlapping ranges. The result is lower allocation traffic.
The resident and resident probabilistic-sort controls have identical allocation
profiles. At one worker:

- Routed partition allocations fall from 3,719,777 to 3,619,778 and requested
  bytes from 418.9 MB to 338.9 MB.
- Exact-assignment pipeline allocations fall from 401,301 to 301,303 and requested
  bytes from 236.3 MB to 156.3 MB (two parent traversals).
- Routed probabilistic allocation falls from 300,997 to 200,998 allocations and
  82.5 MB to 2.5 MB requested, retaining its 385,950-byte peak live requested allocation.
- Fused spilled balanced output falls from 3,701,053 to 3,601,054 allocations and
  462.9 MB to 382.9 MB requested. Its wide variant also removes 99,999 allocations
  and about 80 MB of requests.

Peak live requested bytes and reallocation counts match in these cases. Cumulative
requests are not reductions in resident memory. All 144 jobs (108 timed and 36
instrumented) verify identical bytes/order, names, lineage, stage metadata and
logical digests. Temporary traffic, sort runs, merge counts and peak workspace
reservations match. Full ranges, CPU, RSS and allocation distributions are retained
in the [raw results](../../evidence-originals.md#sha256-90f5cdbcdf83026776c8b8e4e103e445803e02b642b6790d87589bbec084b111 "Original: docs/benchmarks/group-decode-reuse-native-2026-10-14.jsonl").

A 1.3-million-row follow-up exercises intermediate balanced(1) → uniform →
balanced(4), with one 1.8 MB field, 32 MiB and one worker. It produces 71 initial
runs and two merges. Three alternating repetitions give medians of 5.199 → 5.114 s
and ranges of 5.179–5.218 → 5.105–5.209 s. Allocations fall from 5,080,075 to
3,780,076 and requested bytes from 2.883 GB to 1.843 GB. Reallocation counts and
peak live requested bytes (8,396,260) are unchanged. All eight jobs match output
and metadata, bringing this pass to 152 verified jobs. Temporary traffic, run/merge
counts and peak workspace reservations match. The overlapping timing ranges do
not establish a throughput improvement.
[Raw multi-level results](../../evidence-originals.md#sha256-4be20096e65f9494ace0155647b16e4e096a3d0a4f94c2ae412ac6b08002081b "Original: docs/benchmarks/group-decode-reuse-multilevel-2026-10-14.jsonl").

### Validation and remaining scope

The 84-test workspace suite and a new routed-cursor regression passed (85 tests
in total). The new regression checks allocation reuse across routed file/group
boundaries after a wide row, metadata reset, cancellation, EOF and reservation/file
cleanup. Partition output is checked against an owned-field reference including
selected-column order, Unicode, NUL, wide fields and shuffled ordinals. Existing
corrupt-frame, merge sink-failure, multi-level merge, seeded-order, empty-group,
strict-cap and publication tests pass. Formatting, workspace/all-target Clippy
with warnings denied, and native/WASI release builds pass. Server tests required
loopback access. No new browser runtime or sampled CPU-stack evidence was collected;
controlled storage and broader cardinality/width calibration remain open.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-group-reuse-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-group-reuse-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases resident partition_spill partition_wide assign_pipeline_spill \
    probabilistic_route probabilistic_sort fused_balanced_spill fused_balanced_wide pipeline
```

For the multi-level comparison, use
`--rows 1300000 --workers 1 --repeats 3 --cases fused_balanced_pipeline_wide`.
