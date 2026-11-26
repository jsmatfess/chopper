## Observed hosted calculated columns followed by Partition (2026-11-26)

[Issue #104](https://github.com/jsmatfess/chopper/issues/104) ·
[Projected Run samples](../../benchmarks/observed-calculated-partition-2026-11-26.jsonl) ·
[Fault controls](../../benchmarks/observed-calculated-partition-faults-2026-11-26.json) ·
[Measured patch](../../benchmarks/observed-calculated-partition-2026-11-26.patch)

The observed hosted route can feed evaluated rows into a terminal Partition
on a calculated column. It keeps the staged plan's capped CSV snapshot writer
and admits that writer before walking the source. The source snapshot is
validated first. One plain-output Partition on a calculated field, a single
root group, a source of at least 128 MiB, and ordinary Partition eligibility
use the fused path. The native Linux optimization has its existing scope.

### Complete hosted Runs

Both arms use `UPPER(key)`, eight 32-byte input key values, one worker, 256 MiB,
Auto grouping, plain output and a 4 MiB CSV cap. Persistent bundled Chromium
on WSL2 times the same public Run through successful marker and workspace
retirement. Three alternating pairs follow one excluded warmup per arm and
cell. The existing snapshot materializer publishes in both arms. The
candidate's grouping operator receives the observed Calculation edge and
the staged arm observes the intervening Dataset materialization.

| Fixture | Baseline median [min–max], s | Candidate median [min–max], s | Paired seconds saved [min–max] |
| --- | ---: | ---: | ---: |
| 650,003 rows, 232-byte payload | 7.723 [7.673–7.835] | 6.351 [6.221–6.482] | 1.353 [1.322–1.502] |
| 90,003 rows, 96-byte payload, below eligibility | 0.771 [0.766–0.777] | 0.769 [0.754–0.776] | 0.008 [−0.006–0.012] |

The larger job saves 243,640,069 bytes each of tracked temporary reads and
writes. Peak temporary files' stored bytes drop from 534,003,118 to 502,152,971.
Peak simultaneous working reservations, including evaluator/sorter/writer
overlap, were 60,736,351 and 60,672,074 bytes respectively. The placement of
these owners and retained output determines the peak. The smaller control
retains the same tracked traffic and working peak.

### Failure and replay

Each export independently checks exact fields and ordered CSV hashes, grouping
lineage and membership, cap adherence, and successful cleanup. When a wide
first-row key fails before a last-row numeric formula error, the challenger
reports the same row-258 formula error as the staged arm. Its observations
show a failed speculative attempt at one evaluated row and a staged replay.
Without that later formula error both report the original sort memory error.
Cancellation during an observed Calculation cleans the workspace and leaves
no destination output. The candidate keeps the original cleanup check before
replay.

Build the feature-free `ab8e1519afd15d6c22d42ee2b2ec4a5e4deca393` source with
the measured #103 and #102 patches as in
[the Balanced measurement](terminal-partition-after-a-shared-balanced-range-2026-11-26.md).
Add the measured calculation/Partition patch for the challenger. The
projections pin the fixture and WASM hashes. An initial harness verification
incorrectly treated the Analysis input header as the augmented output header,
and the fault harness needed to account for the empty OPFS namespace and
cancelled status. The excluded attempts remain in local custody.
