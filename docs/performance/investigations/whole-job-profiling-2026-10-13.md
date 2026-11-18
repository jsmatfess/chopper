## Whole-job profiling, 2026-10-13

Added `sort_calls`, `sort_rows` and `sort_seconds` to job diagnostics. Time covers
only `Sorter::sort_buffer`, including Rayon dispatch/join, summed across buffers;
it excludes packing, spill writes and merges. It is elapsed time, not summed
worker CPU. Routed groups and Fisher–Yates do not use this comparison-sort timer.
Existing stage timings overlap it and must not be added to it.

The standalone `allocation-profile` example uses a counting system allocator
only in that executable. It measures successful Rust allocation/reallocation
requests by count, requested bytes and size bucket, separately for preparation
and publication. The whole-job census spans both engine calls, excluding config
loading and report serialization. Reallocation bytes count the new requested
size, not just growth; peak live requested bytes spans the process lifetime and
excludes allocator overhead, C allocations, mapped pages and thread stacks.
These counters are neither RSS nor resource reservations. They give phase/size
attribution, not allocation call stacks. Atomic counting perturbs timing, so the
allocation runs are not speed measurements.

Recorded on AMD Ryzen AI 9 HX 370, Linux/WSL2, warm uncontrolled local storage,
300,000 rows, deterministic uniform shuffle. Resident input has one column and
a 256 MiB budget; spill inputs have 33 columns and a 32 MiB budget. Rare-wide adds
one 1.8 MB field. Three alternating old/new ordinary runs per case/worker count
are separate from one allocation run and one 499 Hz user-CPU sampling run.
The baseline is the existing release executable saved before adding timers;
the candidate adds timers and release debug information. This measures a baseline
and correctness, not an algorithmic speedup or a controlled timer-overhead claim.

| Fixture | Workers | Whole-job median seconds (range) | Sort median seconds | Rust allocation calls | Peak RSS KiB (ordinary runs) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Resident | 1 | 0.184 (0.182–0.202) | 0.0164 | 1,800,296 | 35,352 |
| Resident | 4 | 0.161 (0.161–0.165) | 0.0060 | 1,800,340 | 35,328 |
| 33 columns | 1 | 1.085 (1.054–1.137) | 0.0169 | 21,000,984 | 12,644 |
| 33 columns | 4 | 1.158 (1.152–1.318) | 0.0198 | 21,001,026 | 12,868 |
| Rare-wide | 1 | 1.156 (1.100–1.174) | 0.0184 | 21,000,983 | 16,664 |
| Rare-wide | 4 | 1.168 (1.144–1.528) | 0.0194 | 21,001,027 | 16,300 |

Allocation calls exclude reallocations: the spill cases additionally make about
1.2 million reallocations. Nearly all allocation traffic occurs in preparation.
Each spill case generates 17 sorted runs and one merge; temporary writes are
126,078,012 bytes for columns and 129,678,010 for rare-wide. Resident jobs write
1,989,003 bytes. Peak workspace reservations are 49,688,890 bytes resident and
8,388,558 bytes spilling, released completely in all runs. Full CPU/RSS, phase
timings, traffic, reservations, allocation distributions and symbol-attributed
samples are in [raw JSONL](../../evidence-originals.md#sha256-3df201d7df31ebbea4fbfaf7f7310f03cbd226fb41c96c0d97eed825fdc53f3c "Original: docs/benchmarks/job-profiles-2026-10-13.jsonl").

A [1.3-million-row rare-wide follow-up](../../evidence-originals.md#sha256-74e4f969769192a9da1a798e8b17a50aa3d9f70c8b80e424e395700cd4b95036 "Original: docs/benchmarks/job-profiles-multilevel-2026-10-13.jsonl")
with one worker exercises multiple merge levels: 71 sorted runs, two merges,
72 merge inputs and 965,381,720 temporary bytes written. Three ordinary runs
take 5.928–5.984 seconds (median 5.951), with median sort time 0.0817 seconds
and peak RSS 16,108 KiB. The allocation run counts 92,179,201 allocations plus
5,201,188 reallocations; the CPU profile contains 2,400 samples. All eight runs
(three baseline, three candidate, allocation and CPU sampling) match outputs.
Reproduce with the command below plus `--rows 1300000 --workers 1 --cases rare_wide`.

The resident one-worker profile has only 69 samples: 19 in BLAKE3 compression,
10 in `PackedRow::unpack`, and 19 unattributed in libc. The 33-column one-worker
profile has 478 samples, including 234 unattributed in libc, with remaining
samples spread across hashing, parsing, serialization, allocation helpers and
merge decoding. Do not equate all libc samples with allocation. This host's perf
lacks libelf and runtime stack unwinding. `symbolize-perf-offsets.py` translates
raw executable file offsets through ELF LOAD segments before using addr2line to
recover outermost inline functions. These are self samples, not caller stacks;
system-library symbols remain unattributed. Raw perf data/reports stay in the
ignored scratch artifact directory; portable summaries are committed as JSONL.

Sorting is about 9% of the one-worker resident job and 1–2% of the spill jobs.
Even eliminating it would have limited whole-job impact on these fixtures.
The allocation volume and unpack samples support measuring compact consumers,
but do not prove a future speedup. Browser CPU/allocation profiling, allocation
call stacks and controlled cold/slow storage remain follow-up work.

Reproduce (use a new artifact directory for each run):

```sh
source .tools/linux/cargo/env
cp "$CARGO_TARGET_DIR/release/chopper" /tmp/chopper-before-profiling
CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release --locked -p chopper \
  --bin chopper --example allocation-profile
python3 scripts/capture-job-profiles.py \
  --before /tmp/chopper-before-profiling \
  --binary "$CARGO_TARGET_DIR/release/chopper" \
  --allocator "$CARGO_TARGET_DIR/release/examples/allocation-profile" \
  --artifacts scratch/job-profiles-new > /tmp/job-profiles.jsonl
```

Requires Linux perf, GNU time and binutils addr2line on minimal perf builds.
All output fingerprints matched across builds, workers and instrumentation:
CSV bytes/order, manifest names/counts/lineage, stage metadata and logical digest.
Validation: 77 native tests, formatting and workspace/all-target Clippy passed;
the shared library also passed the WASI target check with the repository SDK.
The collision-order test now checks sorted-row/call accounting across resident
and spilling budgets. Browser runtime tests were not rerun for this pass.
