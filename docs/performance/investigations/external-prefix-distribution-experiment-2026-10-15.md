## External prefix-distribution experiment, 2026-10-15

The `experimental-distribution` Cargo feature evaluates a bounded, order-preserving
alternative to external random-key merge sorting. Merge sorting remains the
default. Resident random-key sorting and Fisher–Yates are unchanged.

### Candidate and bounds

After a random-key group exceeds its resident buffer, distribute rows by successive
four-bit key prefixes in lexical order, with at most 16 lazily created bucket
writers per pass. Track the sum of packed-row memory estimates in each bucket;
buckets exceeding one eighth of the job memory budget are eligible for another
pass. This is a conservative experiment threshold, not the future per-group
allocation/reservation policy. Each shuffle group has at most four distribution
levels and 64 distribution passes. Process the tree depth first and release
parent buffers before descending. Oversized buckets, including equal-prefix and
equal-key cases at these limits, fall back to the existing bounded multiway sorter.
Leaves retain the v1 comparator and collision refinement; there is no independent
bucket shuffle or new seeded algorithm identity.

Distribution buffers and recursive decode storage have workspace reservations;
leaf sorting retains its existing reservations and row-size checks. Existing disk
budgets and cancellation checks cover bucket and output writes. Pending bucket
files remain bounded by fan-out and depth; total distribution-created bucket files
are bounded by 16 × 64 per group. Fallback merge files retain the existing bounded
merge machinery. Sorted leaves are materialized into one ordered temporary stream,
then consumed through the existing checked merge cursor. This deliberately simple
candidate pays an additional output materialization pass and decodes/re-packs
rows at leaves; results apply to this implementation, not all external distribution
algorithms. The memory hint sums current packed capacities, including reusable
decode capacity after a rare wide row; it can therefore overestimate a child
bucket's eventual retained memory and trigger unnecessary redistribution. A
future candidate should separate transient decode capacity from retained leaf
capacity before interpreting this threshold as a fit policy. `SortOrder::GroupRandom` fused grouping/assignment paths retain merge
sorting; the experiment covers individual `SortOrder::Random` groups.

### Method

AMD Ryzen AI 9 HX 370, WSL2 x86-64, 32 MiB job budget, 300,000 rows,
one/four native workers, warm uncontrolled local storage.

`benchmark-external-shuffle.py` alternates baseline/candidate complete jobs, with
three timing repetitions and one separate whole-job allocation census per build,
shape, pipeline and worker count. Inputs have ascending unique IDs, two fields
(narrow), 33 fields (columns), or 33 fields with one 1.8 MB field (rare wide).
Pipelines are global shuffle, balanced(4) → per-group shuffle, and shuffle →
balanced(4). Every run checks exact unique-ID conservation, original field text,
group isolation for grouped shuffles, CSV byte counts, byte/order replay,
filenames, lineage, stages and logical digests. Source creation and verification
are outside timing; process startup, ingestion, serialization and publication are
included.

New engine diagnostics count temporary read bytes (including buffered read-ahead),
written bytes, files created and peak live temporary files, plus distribution
passes, row visits, deepest level and fallback buckets. These are logical file
operations, not physical disk traffic. `merge_operations` includes single-run
output cursors. GNU time filesystem block counts are retained separately, along
with CPU and peak RSS. Peak temporary bytes come from the existing job budget tracker. Analysis
counters/timings and temporary peaks are captured at preparation completion,
before output snapshot copying/publication; they exclude source and destination
staging space. Complete-process time, CPU, RSS, allocation census and GNU time
filesystem blocks include publication.
Reservations are algorithm workspaces, not an RSS cap or complete process-memory
accounting.

### Results and decision

All 144 complete timing/allocation jobs passed output and metadata verification.
Across the 18 shape/pipeline/worker combinations, candidate median time was
18–67% higher than merge sorting. Retain merge sorting by default;
there is no warm-native complete-job gain to promote. Times below are seconds;
the [raw artifact](../../evidence-originals.md#sha256-2d1e21d864120bd8ce2d012f17f7dd341fe8b30b206db08ac38d626b22ebfa6a "Original: docs/benchmarks/external-shuffle-native-2026-10-15.jsonl") retains
all samples/ranges, CPU, RSS, reservations, allocations and fingerprints.

| Shape | Pipeline | Merge, 1 worker | Prefix, 1 worker | Merge, 4 workers | Prefix, 4 workers |
| --- | --- | ---: | ---: | ---: | ---: |
| narrow | global | 0.214 | 0.264 | 0.210 | 0.262 |
| narrow | grouped | 0.249 | 0.307 | 0.237 | 0.301 |
| narrow | balanced | 0.224 | 0.263 | 0.214 | 0.263 |
| columns | global | 0.895 | 1.434 | 0.883 | 1.376 |
| columns | grouped | 1.026 | 1.296 | 0.999 | 1.383 |
| columns | balanced | 0.987 | 1.538 | 1.016 | 1.599 |
| rare wide | global | 0.906 | 1.474 | 0.950 | 1.584 |
| rare wide | grouped | 1.051 | 1.306 | 1.009 | 1.356 |
| rare wide | balanced | 1.000 | 1.583 | 0.993 | 1.577 |

Preparation-only temporary traffic below uses global jobs with one worker. Each
cell is merge → prefix; MiB are binary. Extra passes increase cumulative traffic
without a comparable peak temporary-space increase.

| Shape | Read MiB | Written MiB | Peak temporary MiB | Files created | Peak live files | Prefix passes / depth / fallbacks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| narrow | 24.8 → 49.6 | 31.8 → 56.6 | 31.8 → 31.8 | 11 → 21 | 11 → 19 | 1 / 1 / 0 |
| columns | 104.6 → 313.8 | 129.4 → 338.6 | 129.3 → 129.3 | 21 → 277 | 21 → 35 | 17 / 2 / 0 |
| rare wide | 106.3 → 329.3 | 132.8 → 355.8 | 132.7 → 132.8 | 22 → 787 | 22 → 48 | 49 / 4 / 14 |

Whole-job allocation requests (allocation + reallocation calls) for the same
one-worker/global fixtures:

| Shape | Merge requests | Prefix requests | Merge peak live requested MiB | Prefix peak live requested MiB |
| --- | ---: | ---: | ---: | ---: |
| narrow | 1,501,145 | 2,101,344 | 6.7 | 6.7 |
| columns | 12,001,923 | 12,906,099 | 8.0 | 8.1 |
| rare wide | 12,001,972 | 12,931,250 | 8.0 | 7.4 |

The many-column global candidate performs two distribution levels and materializes
256 sorted leaves. Rare-wide capacity inflation increases this to four levels,
49 passes and 787 created temporary files, including 14 fallback buckets. These
fallbacks are threshold/depth events; the recorded warm fixtures do not force
multi-level leaf merges. Deterministic tests cover those merge cases separately.
All GNU time filesystem input/output block counters were zero in this environment;
they provide no usable physical-I/O evidence. Complete-process RSS and allocation
peaks are not interchangeable with reservations, and small timing differences
remain subject to uncontrolled-storage/run variability.

### Validation and remaining coverage

Deterministic tests compare the candidate with v1 merge sorting under forced equal
keys, equal prefixes and multi-level spilling, check the four-level and total
64-pass limits, conserve stable unique IDs with duplicate payloads, and cover
truncated/invalid frames, cancellation, disk exhaustion and reservation/file cleanup.
The global-pass-limit test uses a tiny leaf threshold with a normal I/O workspace
to exercise the cap without a scale-sized fixture.

At this native-only milestone, controlled storage, browser runtime measurements,
broader scale and physical-device behavior remained unmeasured. The
[native/browser follow-up](../../performance.md#external-shuffle-nativebrowser-follow-up-2026-10-15)
below adds runtime coverage; slow-storage optimization is no longer a priority. The harness accepts `--work-dir`, a
recorded storage label and an optional executable `--prepare-command` before each
job for future storage-controlled runs. Warm results do not authorize promotion.
The separate per-group selection, comprehensive deterministic shuffle tests and
statistical diagnostics TODO items remain open. Both default and experimental
workspace suites passed 89 tests, including localhost interfaces. All-feature
Clippy with warnings denied passed, and the candidate passed a WASI compile check;
this is not browser runtime evidence. The final library and all-feature Clippy rerun also passed.

Reproduce with identical-source release builds, saving each executable and
`allocation-profile` example before changing the feature:

```sh
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
# Save baseline executable and example, then:
cargo build --release --locked -p chopper --bin chopper --example allocation-profile --features experimental-distribution
python3 scripts/benchmark-external-shuffle.py --baseline /path/to/baseline --candidate /path/to/candidate --baseline-allocator /path/to/baseline-allocator --candidate-allocator /path/to/candidate-allocator --rows 300000 --memory-mb 32 --workers 1 4 --repeats 3
```
