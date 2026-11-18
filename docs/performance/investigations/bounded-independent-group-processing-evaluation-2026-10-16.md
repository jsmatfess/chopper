## Bounded independent group-processing evaluation (2026-10-16)

The native `experimental-parallel-groups` candidate evaluates bounded independent
uniform-v1 shuffle groups. Default execution and WASI stay serial across groups.
This experiment does not parallelize CSV parsing, partitioning, exact assignment,
merge traversal within a group, Fisher–Yates or buffer shuffling.

At most four parent groups execute on the existing Rayon pool. Each gets its
own sorter and temporary dataset, with sorter/merge sizing divided by the actual
batch concurrency. These contexts retain the same job workspace, process ledger,
thread pool, cancellation and temporary-space/file budget. Row capacities,
sorter descriptors/growth, readers, writers and paths use their existing capacity
reservations. The batch descriptor vector is reserved before allocation; retained
parent lineage uses a conservative BTreeMap-node/string/array bound before
entering the batch. Existing transient catalog JSON decoding and native runtime
allocations remain outside this incomplete ledger.

Results replay into the next stage or encoded output in original parent order,
preserving parent lineage, random domains, row IDs, ordinal reset, v1 collision
refinement and balanced-split fusion. The extra spool write/read and replay are
included in complete-job time, logical I/O and disk-space peaks. This is not an
in-place parallel output implementation. No success is published while optional
group work remains incomplete.

All workers finish before a batch is inspected. A typed local/process admission
denial (including a row too wide for the smaller optional sort grant) drops every
successful sibling spool before retrying those same parents serially under the
original budget. Remaining parents stay serial for that stage. Corruption,
cancellation, disk-space exhaustion and other failures are terminal; non-admission
errors take precedence over concurrent admission denial. Already emitted earlier
batches are not replayed. Optional task-metadata denial selects serial processing
without losing consumed parents.

The first prototype let all sorters use the original quarter-job sort target.
On the 300,000-row/33-column/four-group case it reached the half-job shared limit,
retried serially and regressed by 13.8% in four-worker median complete-job time.
The revised candidate divides sorter/merge sizing among active tasks and stops
parallel attempts after the first failed batch. The initial artifact is retained
as failure/iteration evidence, not the final comparison.

### Matched-source complete-job measurements

**Keep serial defaults; retain the candidate opt-in.** Four-worker many-column
jobs improve, but extra CPU, spill/replay traffic, retained disk space and
regressions on narrow/skewed/small-group jobs prevent automatic promotion.

Paired release builds use the same final sources, differing only in
`experimental-parallel-groups`. The final native comparison contains **132 timed
complete jobs and 44 separate allocation censuses**, with three alternating
repetitions. Every successful job independently checks unique IDs, every field
and parent-group isolation, then compares exact CSV bytes/order, filenames,
lineage, stage statistics and logical digest. All final native timing/census
cases stay below the unchanged half-job charged-workspace ceiling and finish
with only retained header/path charges. No final ordinary run retries serially.

Warm, uncontrolled WSL storage; explicit 32 MiB job budget. The primary matrix
uses 300,000 presorted records, four initial balanced groups, one/four workers,
three shapes and three pipelines: grouped shuffle, grouped shuffle followed by
three balanced outputs per group, and two grouped shuffles separated by balanced
splitting. The last pipeline finishes with 24 outputs. The rare-wide shape adds
one 1.8 MB field to the 33-column input. One-worker controls do not dispatch groups;
their median changes range from −4.4% to +4.6%, without a consistent speedup.

Four-worker primary medians, seconds:

| Shape | Pipeline | Serial | Groups | Change |
| --- | --- | ---: | ---: | ---: |
| Narrow, two fields | Grouped shuffle | 0.3017 | 0.2977 | −1.3% |
| Narrow | Grouped shuffle → balanced | 0.3259 | 0.3242 | −0.5% |
| Narrow | Two shuffles / balanced splits | 0.4992 | 0.5580 | +11.8% |
| 33 columns | Grouped shuffle | 1.0488 | 0.9571 | −8.7% |
| 33 columns | Grouped shuffle → balanced | 1.0410 | 0.9369 | −10.0% |
| 33 columns | Two shuffles / balanced splits | 1.6044 | 1.3693 | −14.7% |
| Rare wide, 33 columns | Grouped shuffle | 1.0166 | 0.9728 | −4.3% |
| Rare wide | Grouped shuffle → balanced | 1.0467 | 1.0089 | −3.6% |
| Rare wide | Two shuffles / balanced splits | 1.5846 | 1.4555 | −8.2% |

The primary matrix has 108 timings and 36 censuses. The additional cases add
24 timings and eight censuses:

| Additional fixture | Serial median | Groups median | Change |
| --- | ---: | ---: | ---: |
| 6,400 narrow rows / 64 small groups | 0.1702 | 0.1812 | +6.5% |
| 6,400 many-column rows / 64 small groups | 0.1904 | 0.2003 | +5.2% |
| 300,000 many-column rows / 90:9:1 partition skew | 1.3001 | 1.6293 | +25.3% |
| 2.8 million many-column rows / two groups, hierarchical merging | 11.8861 | 11.1867 | −5.9% |

The skewed input contains quoted Unicode/newlines in its dominant partition key.
A one-part balanced stage separates partitioning from shuffle fusion, exercising
three independent shuffle groups with preserved partition isolation. Sixty-four
small groups exercise sixteen bounded batches. The large case has 155/310 runs
and four/six merge operations (serial/candidate), including hierarchical merges
on both paths. Its serial repetition range is 11.7864–17.1338 s and candidate
range 11.1235–11.8020 s; the first serial observation is much slower. The reported
median is not evidence of a stable device/scale-wide gain.

### CPU, memory and temporary-storage tradeoffs

Whole-job GNU CPU time increases substantially despite selected wall-time gains.
For 33-column grouped jobs it rises from 0.95 to 1.37 s, and for the two-shuffle
pipeline from 1.46 to 2.31 s. The narrow two-shuffle pipeline rises from 0.44 to
1.23 s. CPU reporting has 0.01-second resolution. Instrumented census timings
are excluded from speed comparisons.

Primary engine write traffic rises by 39–90%, with higher peak temporary space.
For the 33-column grouped case, writes rise from 240.6 to 345.5 MB and peak engine
temp bytes from 158.3 to 297.7 MB. The additional replay/framing work is material,
even where parallel execution improves latency. The large case writes 3.10/4.07
GB and peaks at 1.95/2.97 GB of engine temporary data. These counters exclude
source files and final destination staging; they measure logical engine traffic,
not physical SSD bytes or filesystem allocation. WSL filesystem block counters
do not establish device traffic or controlled cache conditions.

Separate allocation censuses retain distributions/counts, requested traffic and
peak live requested bytes. For 33-column grouped jobs, whole-job requested bytes
rise from 420.1 to 427.9 MB. The many-small-column case rises from 22.4 to 35.7 MB;
repeated spool/reader setup matters for small groups. Rare-wide and skewed cases
also add many per-row allocations. Peak reservations and GNU RSS are different
metrics: the primary cases reserve about 7.1–10.9 MB at four workers, while
median per-process RSS is about 12–21 MiB. Native runtime/allocator internals and
filesystem page cache are not fully represented by the charged ledger or Rust
allocator census. No complete RSS cap is claimed.

### Failure, parity and validation

Five new tests check ordered/remainder batches, Unicode and quoted multiline
rows, balanced fusion, shared-capacity edges/rollback, sibling-spool destruction,
injected local/shared denial with exact serial replay, precedence of terminal
errors, corruption/cancellation and a row exceeding the smaller optional sort
grant while fitting the original serial grant. **199 default / 213 all-feature
workspace tests, including 127 all-feature library tests, formatting, both
all-target Clippy configurations with warnings denied, and 24 candidate
Chromium/WASI contracts pass.** Local server/browser checks use loopback-enabled
execution; no build or test overlaps an ordinary timing matrix.

The configured admission matrix adds 32 constrained successes, eight clean
failures, eight unconstrained references and four invalid environment settings.
Fourteen constrained complete jobs and eighteen profiles exactly match their
references. Three four-worker jobs actually retry a failed group batch: many
columns at 4/8 MiB process ceilings, and a late-wide input at 8 MiB. Temporary
cleanup and absence of publication on failure are checked. These are configured
capacity ceilings, not OS/cgroup/RSS pressure experiments.

Six additional native controls check singleton batches, a retained empty named
allocation (through an intervening compatibility buffer-shuffle stage), and a
strict output byte cap. Four successful jobs conserve every field/ID and match
exact output/metadata; both strict-cap failures leave no output or temporary job
directory. Candidate counters confirm eight singleton and two empty/nonempty
parent groups actually use the worker path.

The repeated runtime replay adds **72 complete jobs** on 100,000-row inputs:
three shapes, grouped/two-shuffle pipelines, three alternating repetitions, four
native workers and one browser worker. Every output/metadata fingerprint matches
across feature flags and runtimes; native checks independently verify every
field/ID and grouped-range isolation. Counters confirm four candidate native
groups and zero browser group tasks per job. WASI remains serial; browser timings
are parity/control observations, not evidence of browser parallelism. Default
native and WASI development artifacts are restored and their hashes checked.

Artifacts: [final native matrix](../../evidence-originals.md#sha256-489442b1242872ad39c9011406f94fa3d1eade027eb5b16151580d536bf24317 "Original: docs/benchmarks/parallel-groups-native-2026-10-16.jsonl"),
[many small groups](../../evidence-originals.md#sha256-9d77e237424be90374f04e7cf65ffda2f65389273a563bcdd184dfb19a07b199 "Original: docs/benchmarks/parallel-groups-many-small-2026-10-16.jsonl"),
[skew](../../evidence-originals.md#sha256-6e386dc369e8920f3f465fd21382dde5fe49942a69a7b85fce48e2eba39bdbdb "Original: docs/benchmarks/parallel-groups-skew-2026-10-16.jsonl"),
[hierarchical merge](../../evidence-originals.md#sha256-38fa51d9f75d7db99a70a70a9f1ea485c475b2aef7d3c7064aef18ce17111b88 "Original: docs/benchmarks/parallel-groups-multilevel-2026-10-16.jsonl"),
[configured boundaries](../../evidence-originals.md#sha256-daf43f1a7c7e03160d5871ccc796a7ee9885643c9fe0f2340e741531d3762f8a "Original: docs/benchmarks/parallel-groups-boundaries-2026-10-16.jsonl"),
[singleton/empty/cap controls](../../evidence-originals.md#sha256-26f3b8a35ef53eb830e7f2caed014f0738a00f3778cd71fa0d6769e09f07925e "Original: docs/benchmarks/parallel-groups-edges-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-0fd1f2ec9a2d79b33a50436c198ef668137476e8e988c6a15fc7980139ddca80 "Original: docs/benchmarks/parallel-groups-browser-2026-10-16.json"),
[native/WASI replay](../../evidence-originals.md#sha256-5e3a6cc0c2d9dc9e1bf0a78aa5547a288069f9a90410e4d3740989540e8fea9c "Original: docs/benchmarks/parallel-groups-engines-2026-10-16.jsonl"),
[summary, ranges and source/build hashes](../../evidence-originals.md#sha256-dfda11e05395c7b9f3d9ed9e4ac47d3b3a418d40fefe0006175de64969b8b102 "Original: docs/benchmarks/parallel-groups-summary-2026-10-16.json"),
[initial prototype](../../evidence-originals.md#sha256-771a97ef1473dca1d7825ea37508a0abec658586bbe509ca0392f0a992fbea82 "Original: docs/benchmarks/parallel-groups-initial-native-2026-10-16.jsonl"),
[preliminary revised comparison](../../evidence-originals.md#sha256-ee72e477e8c74332c87a2f5c93bb5d5d4bfe178062db5fb3ee2472b4b32583bd "Original: docs/benchmarks/parallel-groups-revised-native-2026-10-16.jsonl").
The preliminary comparison uses the previous default build; the final matrix
rebuilds both variants from matching final sources.

```sh
# Build/copy SERIAL and SERIAL_ALLOCATOR; repeat with the feature for GROUPS.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-parallel-groups
python3 scripts/benchmark-external-shuffle.py --baseline SERIAL --candidate GROUPS \
  --baseline-allocator SERIAL_ALLOCATOR --candidate-allocator GROUPS_ALLOCATOR \
  --rows 300000 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide --cases grouped grouped_balanced multistage
# Small groups: --rows 6400 --groups 64 --workers 4 --shapes narrow columns --cases grouped
# Skew: --rows 300000 --workers 4 --shapes skew --cases skew
# Hierarchy: --rows 2800000 --groups 2 --workers 4 --shapes columns --cases grouped
python3 scripts/benchmark-shared-memory.py --before SERIAL --after GROUPS \
  --rows 100000 --groups 4 --memory-mb 32
python3 scripts/validate-parallel-groups.py --baseline SERIAL --candidate GROUPS
bash scripts/build-browser.sh --features experimental-parallel-groups
# Build/copy matching serial/candidate WASI files, then run parity controls:
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs SERIAL GROUPS SERIAL.wasm GROUPS.wasm \
  100000 3 narrow,columns,rare_wide grouped,multistage serial,parallel 4
```

These warm native measurements do not calibrate cold/controlled SSD conditions,
other machines, a complete resource planner, other operation-level concurrency,
browser threads or complete live-memory/RSS accounting. Remaining work stays in
[TODO.md](../../../TODO.md).
