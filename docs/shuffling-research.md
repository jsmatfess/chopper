# Full-shuffle diagnostic design

Historical design/research: buffer-shuffle descriptions and negative controls below
refer to pre-removal builds. The current engine rejects that strategy and its
configuration fields; see [current specification](specification.md#shuffling-and-seeds).

Specified 2026-10-15 before inspecting diagnostic results. This is a finite
regression diagnostic, not a proof of uniformity or a throughput benchmark.
Random-key v1 and Fisher–Yates v1 remain separate reproducibility contracts.
Resident execution is preferred when the complete working set fits; external
random-key merge sorting retains its existing default and collision refinement.
Independent random buckets would require a new algorithm identity.

## Fixed experiment

`scripts/diagnose-shuffle.py` runs 32 literal seeds `shuffle-diagnostic-v1-00`
through `shuffle-diagnostic-v1-31`. Each complete native job has 256 uniquely
identified rows, one worker and 64 MiB. Five fixtures cover ascending records,
descending records, four long entity/label blocks, periodic labels and skewed
groups of 192/48/16 rows. Skewed groups use partition then shuffle; other fixtures
shuffle globally. IDs identify source positions independently of record values.
Labels are categorical text, with no type inference. Blocks contain 64 rows,
sixteen times the negative control's four-row buffer.

Each output must conserve exact IDs and field text within its group, match
manifest row/byte counts, report the expected stage/group counts, retain the
input logical digest across algorithms, and release workspace reservations.
Record exact order fingerprints, binary/script hashes and individual seed metrics.

Six statistics are computed within each group and averaged with row-count
weights: 4-by-4 source/output position-bin Pearson discrepancy; mean absolute
source/output displacement divided by group size; fraction of adjacent output
records adjacent in source; longest same-label run divided by group size;
early/middle/late label-composition Pearson discrepancy; same-label adjacency
fraction. Position bins and windows use floor(position * bins / group size).
Expected contingency counts use their exact fixed margins. This handles
non-divisible group sizes and skewed labels. Constant-label groups have zero
composition discrepancy. All six corpus statistics are means across 32 seeds.

## Null calibration and decisions

Use Python's independent `random.Random` permutation implementation as a
diagnostic reference. Its seed is a SHA-256-derived integer of a literal,
versioned domain and fixture name; record the Python version. This is an
independent pseudorandom reference, not an oracle proving true randomness.
First use 1,024 independent permutations to fix each statistic's null center.
Then generate 2,047 independent corpora of 32 permutations each, retaining group
sizes, labels and membership. Compare absolute departures from the fixed pilot
center, allowing departures in either direction. Monte Carlo p-values use
`(1 + count(null deviation >= observed deviation)) / 2048`; ties count against
rejection. Report the empirical null mean and central 95% interval as context.
No asymptotic chi-square approximation is used for sparse cells or run lengths.

Predeclare family-wise alpha 0.05, Bonferroni across the 60 primary comparisons
(2 full-shuffle algorithms x 5 fixtures x 6 metrics): reject at p <= 0.05/60.
The 30 bounded-buffer comparisons form a separate negative-control family,
using 0.05/30; they do not change the primary threshold. Run all comparisons
without optional stopping, deleting seeds or selecting metrics after inspection.
The Monte Carlo resolution is 1/2048. Failure to reject indicates only that this
small corpus did not detect a departure. A flag warrants investigation and a
separately specified follow-up, never silently changing algorithm/version.

## Remaining matrix

This first diagnostic corpus exercises small resident jobs, not external-scale
statistics, worker scaling, browser/WASI or physical SSD throughput. Extend the
same harness and preregister new families before drawing conclusions about
those cases. Complete-job performance acceptance additionally needs alternating
baseline/candidate runs, CPU/allocation/resource measurements, unchanged output
and metadata for the same algorithm, multi-level external jobs and controlled
cache/device observations. See [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for the active matrix and
[recorded performance](performance.md) for existing measurements.
