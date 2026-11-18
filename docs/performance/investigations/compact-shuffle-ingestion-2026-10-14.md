## Compact shuffle ingestion, 2026-10-14

Intermediate uniform and Fisher–Yates shuffles now ingest checked compact spool
rows directly, without rebuilding one string per field and packing them again.
Terminal balanced splitting also passes compact rows to the output sink. Uniform
shuffle retains the existing inline random keys, collision refinement and decoded
merge allowances. Fisher–Yates retains its seeded sequence and resident budget
failure behavior. Retained storage is charged at its actual capacity; rare wide
rows use the contiguous decoder representation. Spill framing, defaults and public
owned-row adapters are unchanged.

### Complete-job measurements

100,000 rows, 33 columns, AMD Ryzen AI 9 HX 370 on WSL2, warm uncontrolled storage.
Baseline binaries were rebuilt and saved from the existing workspace before this
pass; raw records include binary hashes. Three alternating repetitions at one and
four workers, followed by separate allocator runs. Tests and compilation completed
before timing. The pipeline cases are balanced(2) → uniform or Fisher–Yates;
`balanced_terminal` is partition → balanced(2). Spill and wide cases use 32 MiB,
others 1,024 MiB. The wide case includes one 1.8 MB field.

| Case / workers | Median job seconds, before → after |
| --- | --- |
| resident / 1 | 0.271 → 0.279 |
| resident / 4 | 0.276 → 0.277 |
| balanced_terminal / 1 | 0.458 → 0.402 |
| balanced_terminal / 4 | 0.433 → 0.388 |
| uniform_pipeline / 1 | 0.356 → 0.293 |
| uniform_pipeline / 4 | 0.358 → 0.282 |
| uniform_pipeline_spill / 1 | 0.400 → 0.338 |
| uniform_pipeline_spill / 4 | 0.395 → 0.345 |
| uniform_pipeline_wide / 1 | 0.415 → 0.350 |
| uniform_pipeline_wide / 4 | 0.407 → 0.340 |
| fisher_pipeline / 1 | 0.346 → 0.275 |
| fisher_pipeline / 4 | 0.350 → 0.285 |

Affected medians improve approximately 10–21% on this fixture. The resident
control has identical allocations and no established timing improvement. All
96 jobs (72 timed, 24 instrumented) verify identical output bytes/order, names,
lineage, stage metadata and logical digests. Temporary traffic, run counts and
merge counts match. Peak workspace reservations match except in the wide case,
where compact retained storage changes the peak from 8,388,260 to 8,388,201 bytes.
[Raw results, including all timing ranges](../../evidence-originals.md#sha256-f57f918257a0f329c33d3425d4b5abc67347d23f9d8e8669e9321b24f13ef6f8 "Original: docs/benchmarks/compact-shuffle-ingestion-native-2026-10-14.jsonl").

At one worker, resident intermediate uniform allocations fall from 3,501,019 to
101,019; reallocations rise from 76 to 100,076 because retained decode buffers are
trimmed. Requested bytes fall from 133.8 MB to 130.9 MB, median CPU time from
0.32 s to 0.26 s, and RSS ranges from 24,336–24,652 to 24,092–24,388 KiB.
Spilled intermediate uniform similarly removes 3.4 million allocations, with
requested bytes 220.9 → 218.0 MB and median CPU 0.36 → 0.31 s. Fisher–Yates
removes 3.4 million allocations, with median CPU 0.32 → 0.24 s.

Terminal balanced output removes 3.3 million allocations (7,002,447 → 3,702,447)
but adds 100,000 reallocations and increases requested bytes from 462.0 MB to
490.0 MB. The shared retained-row decoder trims storage even though this consumer
serializes immediately. Its median CPU still falls from 0.38 s to 0.32 s; peak
live requested bytes are unchanged. Borrowing reusable decode storage is a useful
next experiment, especially here; allocation counts alone are not a memory or
speed guarantee.

### Validation and remaining scope

All 83 workspace tests passed, including server tests with loopback access.
Expanded differential coverage compares compact/owned intermediate uniform and
Fisher–Yates output, deliberately colliding keys, empty/NUL/Unicode/wide fields,
and uniform decoded merge allowances. Existing strict-cap, corruption,
cancellation, multi-level merge and publication contracts pass. Formatting,
workspace/all-target Clippy with warnings denied and the release WASI build pass.
No browser runtime benchmark, new sampled CPU stacks, controlled-storage run or
multi-level performance measurement was collected in this pass.

External decode-buffer reuse, source parser/digest integration, buffer-shuffle
and streaming-router ingestion remain open. The initial source parser still
constructs owned fields; digesting currently borrows those fields without adding
a conversion. This pass does not claim those paths are compact end to end.

Reproduce after preserving baseline binaries:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-shuffle-ingestion-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-shuffle-ingestion-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --repeats 3 \
  --cases resident balanced_terminal uniform_pipeline uniform_pipeline_spill \
    uniform_pipeline_wide fisher_pipeline
```
