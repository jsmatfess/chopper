## Cross-tool CSV split and shuffle comparison (2026-11-18)

Decision: investigate Chopper's data movement and admitted batch processing before
replacing the sorting algorithm. This is a native WSL development investigation,
not a new engine default or a qualification of native Windows/browser performance.

### Scope and comparison design

The comparison uses freshly built Chopper 0.2.0 at
`1a7742732b0a75d698bd36d917bf8dcad3488063`, official GNU qsv 29.0.0 and
DuckDB 2.0.0's Python wheel. The host is WSL2/ext4 on a Ryzen 7 5800X, 16 logical
CPUs, 62 GiB RAM. Each job requests eight workers; actual qsv counting parallelism is discussed below. Cache is warm/uncontrolled;
there is no cache eviction or durability/fsync measurement. These are not native
Windows or physical-device throughput results.

Synthetic CSVs have four text columns, fixed 256-byte data records, an exact
10-digit unique ID, leading-zero text key, empty string and a 237-byte payload.
128 MiB is 524,288 rows and 2 GiB is 8,388,608 rows, plus the header. Both divide
exactly into eight outputs. Repeated-payload and SHAKE256-derived varied-payload
cells are separate populations; they must not be pooled. No gzip/ZIP, high-column
count, Unicode, quoted multiline or arbitrary-customer-data throughput is claimed.

A complete-job clock runs from subprocess launch to exit, including startup,
counting, input reads, shuffle, intermediate materialization, all CSV output and
Chopper publication/Analysis. Builds, fixture generation, verification and removal
of successful output payloads are outside the clock. Each cell has one excluded
warmup and three measured runs. Tool order rotates across repetitions. Report
medians and min/max, not confidence intervals or tails. Failed attempts remain
failed; setup failures and the 256 MiB DuckDB OOM do not become speed observations.

The DuckDB adapter creates one all-VARCHAR table, orders it once by random() for
shuffle, counts it, then writes eight LIMIT/OFFSET ranges. It explicitly preserves
insertion order and uses a null sentinel absent from this fixture. This is a
reproducible naive equivalent for the measured fixture, not an optimal SQL plan
or a general arbitrary-text adapter. Repeated export scans/materialization and
Python startup are charged. Independent checks establish actual field/order/quota
behavior on these inputs. A different SQL plan could change rankings.

qsv has no pre-existing index or stats cache in these fresh work directories.
Balanced uses split --chunks 8. Shuffle uses sort --random to a CSV, then split
--chunks 8, with intermediate write/count/read charged. qsv has no matching
memory-budget switch on the random sort. Its full build's count path uses mmap
and Polars; qsvlite is a separately identified build control, not another repetition
of the full build. RSS includes mapped file pages; it is not heap alone.

The independent verifier parses every output CSV, checks all original field text,
unique IDs/conservation, exact eight-file quotas, concatenated encounter order for
balanced, and nonidentity for shuffle. It retains output hashes and actual byte
sizes before removing successful payloads. These checks do not prove uniformity
or equate different random permutations. Chopper Analysis counts/diagnostics and
GNU-time process CPU/RSS/page-fault/filesystem counters remain separate scopes.
Returned prepared Analysis temporary counters precede final snapshot publication;
they cannot be reported as complete-job physical I/O.

### Measured complete jobs

Seconds are median [observed min–max], n=3 per cell; each has one excluded warmup.
The source build is current Chopper 0.2.0, not proof of identity with the other
system's release artifact. qsv is unconstrained; the memory column applies only
to Chopper/DuckDB working settings.

| Input / payload / budget | Job | Chopper, s | DuckDB, s | qsv, s |
| --- | --- | ---: | ---: | ---: |
| 128 MiB / repeated / 4096 MiB | balanced | 0.512 [0.512–0.557] | 0.802 [0.770–0.802] | 0.241 [0.239–0.252] |
| 128 MiB / repeated / 4096 MiB | shuffle | 0.754 [0.752–0.770] | 0.690 [0.675–0.699] | 0.747 [0.728–0.782] |
| 2 GiB / repeated / 1024 MiB | balanced | 8.619 [8.193–9.313] | 9.437 [9.126–9.549] | 3.096 [2.932–3.134] |
| 2 GiB / repeated / 1024 MiB | shuffle | 13.931 [13.636–13.937] | 9.814 [9.675–10.734] | 14.434 [14.083–14.796] |
| 128 MiB / varied / 4096 MiB | balanced | 0.521 [0.512–0.537] | 0.742 [0.698–0.769] | 0.246 [0.243–0.282] |
| 128 MiB / varied / 4096 MiB | shuffle | 0.740 [0.718–0.767] | 0.715 [0.646–0.718] | 0.793 [0.787–0.827] |

The primary repeated-payload comparisons show qsv balanced split 2.12× faster
at 128 MiB and 2.78× faster at 2 GiB (Chopper median / qsv median). DuckDB shuffle
is 1.09× and 1.42× faster respectively. Chopper beats this naive DuckDB balanced
adapter at both scales. qsv does not win the measured 2 GiB shuffle: its median
is slightly slower than Chopper, despite its larger resident working set. The
varied small-shuffle ranges overlap; its modest DuckDB median lead is not robust
shape-independent speed advice. No comparison with the user's original timings
is pooled into these observations.

| 2 GiB primary job / tool | Median peak RSS, MiB | Median user + median system CPU, s |
| --- | ---: | ---: |
| balanced / chopper | 5.5 | 8.14 |
| balanced / duckdb | 1240.4 | 15.81 |
| balanced / qsv | 3169.7 | 9.15 |
| shuffle / chopper | 260.2 | 14.30 |
| shuffle / duckdb | 1238.3 | 22.69 |
| shuffle / qsv | 3320.8 | 20.15 |

These CPU sums are medians of the two separately reported counters, not a sum of
phase peaks. Chopper's wall/CPU relation is close to one core for these jobs;
DuckDB's shuffle uses about 2.2 cores and more total CPU. qsv requests eight split
workers, but without an index that flag does not cap Polars' own count pool.
POLARS_MAX_THREADS was unset. Treat this as actual-default tool behavior with
recorded resources, not an equal-core/equal-RSS experiment.

The qsvlite build removes the Polars count path: 2 GiB balanced median **3.385 s**
[3.370–3.419], **21.2 MiB** median peak RSS. Its separate build cohort has three
measured runs after a warmup; it is a separate build control. It remains about
2.55× faster than primary Chopper, so high mapped RSS does not explain away the
balanced throughput gap. No direct full-binary/qsvlite paired causal effect is
claimed across the separate cohorts.

### Controls that change the proposed direction

| 128 MiB repeated-payload control | Baseline median [range], s | Control median [range], s | Interpretation |
| --- | ---: | ---: | --- |
| Balanced versus direct row-limit output with N supplied | 0.490 [0.488–0.505] | 0.310 [0.309–0.314] | 36.8% lower elapsed, but count discovery and balanced lineage are absent from the control. This is a bound on recoverable combined work, not a delivered balanced optimization. |
| Uniform→Balanced versus explicit FY→Balanced | 0.713 [0.696–0.716] | 0.805 [0.805–0.863] | FY is 12.9% slower: the current path adds a Dataset instead of using Uniform's fused balanced traversal. A faster permutation kernel is insufficient. |

The FY control writes 287.0 MiB and reads 158.0 MiB of temporary data before
publication, versus Uniform's 129.0 MiB write and zero temporary read. Both still
copy the encoded snapshot during publication. These are logical counters with
explicit scope, not physical SSD bytes.

At 1 GiB configured memory the Chopper external shuffle makes 13 runs and one
merge. Its median sum of run-sort wall times is about 0.20 s, roughly 1.5% of the
13.93-s complete job. Even eliminating that measured run-sort work would not
recover the 4.12-s DuckDB gap. Merge, ingestion, encoding, ownership and publication
remain outside that counter. The 256 MiB warmup made 50 runs and one merge, and
also spent only about 0.21 s sorting runs.

A separate DuckDB CTAS-only diagnostic records actual spill at
`/system/peak_temp_dir_size`: **1,558,773,760 bytes (1.45 GiB)**, with
1,107,513,344 bytes of peak buffer memory. It is not another timed complete job.
The original receipt's legacy top-level metric lookup returned null; the retained
profile and separately normalized pointer record preserve the corrected schema
extraction without rerunning or rewriting the source profile.

The common 256 MiB/eight-worker attempt is retained: Chopper completed both
warmup jobs, DuckDB completed balanced and failed shuffle allocation at 260/256
MiB. The batch stopped there. A new 1 GiB cohort was declared rather than treating
that failure as a timing or silently discarding it. Initial harness setup failures
(missing temp directory, interpreter symlink resolution dropping the venv) and
successful one-MiB smoke runs are also retained and excluded from speed summaries.

The real N=19,K=8 quota control produces Chopper `[3,3,3,2,2,2,2,2]` and qsv
`[3,3,3,3,3,3,1]`: qsv emits seven files. It is a semantic difference, not an
error in the selected divisible timing fixture.

### Requirements, avoidable costs and rough impact

These estimates are deliberately scoped. Components are not whole-job ablations,
interacting costs are not additive, and logical byte removal is not a speedup.

| Feature or choice | Rough cost supported here | What to preserve or change |
| --- | --- | --- |
| Logical content digest, absent from these competitor jobs | Current digest component: 0.0665 s [0.0659–0.0669] per 128 MiB and 1.064 s [1.063–1.095] per 2 GiB. Equivalent to about 8–13% of the relevant Chopper wall times, as an order-of-magnitude estimate. | Retain the logical digest; investigate admitted batching/parallel hash work only with matching digest bytes. |
| BLAKE3 random-key construction versus faster PRNG draws | Current key component: 0.0380 s [0.0379–0.0381] / 0.620 s [0.611–0.631], roughly 4–5% of Chopper shuffle wall time. This is the whole component, not a measured difference versus qsv/PCG. | Full uniformity does not require cryptographic hashing, but any alternative needs a deliberate source/version contract and joint-distribution proof. Old buffered-XOF experiments are not automatically reopened. |
| Larger collision-safe random keys | 16 versus 8 key bytes means about 4 MiB extra key storage at 128 MiB input and 64 MiB at 2 GiB, before other layout differences. Collision refinement should almost never run at these sizes. | Preserve full-permutation behavior; no timing penalty for collision refinement was isolated. |
| Exact balanced sizes with unknown N | Count discovery or retained rows is unavoidable; distributing the eight quotas is O(8), negligible versus millions of records. The known-count direct control saves 0.180 s (36.8%) at 128 MiB, including removed passes/path differences. | Count-first balanced emission must charge a real count scan and source-consistency validation. qsv's less exact remainder rule does not justify a large performance tax. |
| Prepared immutable snapshot | One encoded payload write plus later read/copy: roughly 258 MiB of logical traffic at 128 MiB input, 4.03 GiB at 2 GiB. The existing post-Analysis publication tail is separately recorded but includes other finalization/startup work. | Required for explicit Prepare/confirm; ordinary Run's snapshot is an avoidable implementation choice. |
| Balanced framed Dataset plus Run snapshot | At 2 GiB, pre-publication read/write are about 2.47/4.48 GiB. Including input and publication payload scopes gives about 6.5 input-size units of logical traffic. Count-first direct output would target roughly 3 units, while snapshot-only elimination targets roughly 4.5. These are payload models, excluding metadata/read-ahead details. | Test removing a demonstrated pass, not a promised 2× wall speedup. Extra strict parsing/counting can offset saved I/O. |
| Bounded working admission, strict CSV/UTF-8, caps and cancellation | qsvlite retains a 2.55× split lead at low RSS. Individual overheads were not isolated. Direct Chopper still keeps validation/digest/private publication while being much faster than balanced. | Batch bookkeeping and reuse admitted packed buffers; do not bypass guarantees. No defensible per-feature percentage is claimed for this combined residual. |
| Atomic native publication and small manifests/previews | Same-filesystem private output plus no-replacement rename does not inherently require an extra full-payload copy. Eight-file metadata is small; isolated elapsed cost is unmeasured. | Preserve atomicity, cleanup and manifests. Blame the extra snapshot pass on the current Run implementation, not atomic publication itself. |

The digest probe includes current source directly, uses a hot repeated compact
record and substitutes a minimal admission stub outside the timed loop. It omits
parsing, real data access and output. The key probe calls the current public block
function on sequential IDs. Both have one warmup and three measured repetitions,
use rustc -O with release dependencies (without reproducing the engine’s thin-LTO link), and are diagnostic approximations rather than causal
feature-removal experiments. Their source/build command/output are retained.

### Interpretation boundaries

qsv's ceil(N/K) chunk sizing is not Chopper's balanced rule in general. These
fixtures deliberately make N divisible by K. A nondivisible quota conformance
control is recorded separately. Speed on this common subset does not establish
feature equivalence for arbitrary jobs.

The 2 GiB jobs exceed Chopper's configured working budget, and its actual run/merge
counters establish spill. They do not exceed host RAM: a 40 GiB cold-storage or
physical-RAM-exhaustion result has not been reproduced. DuckDB's memory setting
and Chopper's working admission are not complete RSS caps. Budget settings do not
by themselves prove DuckDB spilled; its separate profiling diagnostic supplies
that fact if available. qsv's resident full shuffle is not a bounded-memory
external algorithm, even when it happens to complete a larger file.

### Algorithm findings and proposed experiments

Future implementation remains under the existing execution investigation
[#20](https://github.com/jsmatfess/chopper/issues/20) and terminal-output
[#19](https://github.com/jsmatfess/chopper/issues/19). The sequence below is this
research's proposed decision order, not an additional active backlog or approval
to promote defaults.

1. Resolve avoidable payload passes first. Narrow Run-only grouped direct output
   should retain the existing serializer/caps and private atomic publication while
   removing the encoded snapshot write/read. Explicit Prepare must retain its
   immutable snapshot. Start with terminal plain Balanced and Uniform→Balanced,
   preserve original lineage/counts/digests and compare complete jobs. Separately
   evaluate count-first exact balanced emission versus the current framed dataset;
   account for the count scan, source consistency and changed-input failure.
2. Prefer admitted packed batches to a wholesale sort replacement. Profile the
   actual merge/serialization and intake work, then remove a demonstrated repeated
   decode/copy or amortize admission/callback overhead over bounded owned batches.
   Fuse useful worker computation with parsing rather than copying parsed batches
   back into the old row-at-a-time consumer. Keep late-wide-record, UTF-8, shared
   pressure and drop-before-grant-release contracts.
3. Use DuckDB's parallel run generation and rank-partitioned k-way merge as design
   references only if profiles identify a material merge bottleneck. Chopper already
   has inline random keys and parallel run sorting; a different sorter cannot
   remove serialization, source digesting, row ownership or publication costs.
4. Test a materially different resident/fusion candidate only if current controls
   show a recoverable cost. Explicit FY is resident-only and can have a different
   downstream materialization path. The Nov 15 same-buffer adaptive selector was
   already tried and rejected for lack of complete-job benefit. Do not repeat it
   unchanged or infer a new selector from qsv's Fisher–Yates implementation.

Each candidate needs a frozen baseline, intended workload, observed bottleneck and
predeclared stop rule. Use an initial three alternating complete-job pairs after
warmups; expand to five pairs and an untuned held-out shape only after a useful
signal. A reasonable proposed delivery gate is >=10% median elapsed reduction,
consistent paired signs and no unexplained control regression above 5%; overlapping
or noisy results require more evidence rather than automatic rejection/promotion.
These thresholds are proposed experiment decisions, not product policy. A feature
must also pass meaningful conservation/quota/order/cap controls, malformed/late-wide
input, admission denial, cancellation/finalization and destination-race cleanup.
Validate native Linux, applicable native Windows and WASI independently before
changing shared execution defaults; update affected decision diagrams/contracts.

The old radix, external-prefix, independent-bucket, copied parallel parser and
adaptive FY prototypes are not new candidates merely because upstream uses a
related technique. Their archived failures and reopen conditions remain binding.

### What upstream actually does

qsv's random branch loads ByteRecords into a vector and applies a slice shuffle;
its ordinary splitter counts first, then writes reusable records directly to CSV.
Without an index, the full binary can use Polars/mmap to count. Indexed parallel
splitting needs an index-building pass unless an existing index is declared;
none is silently credited here. See pinned qsv
[sort](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/sort.rs#L141),
[split](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/split.rs#L343),
[count dispatch](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/util/rows.rs#L28)
and [mmap/Polars counting](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/count.rs#L419).

DuckDB uses parallel CSV scan boundaries, column-vector execution, thread-local
sort runs, spillable layouts and rank-partitioned parallel k-way merge. Version
2.0's run sorting uses vergesort with ska-sort fallback; calling it simply a radix
sorter misses the relevant integration. These are mechanisms to investigate,
not causal attribution of this benchmark's whole-job gap. See pinned
[CSV state](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/execution/operator/csv_scanner/table_function/global_csv_state.cpp),
[run sorter](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/common/sort/sorted_run.cpp#L232),
[merge](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/common/sort/sorted_run_merger.cpp)
and the [official redesign explanation](https://duckdb.org/2025/09/24/sorting-again).

Its `ORDER BY random()` uses finite DOUBLE keys from a PCG-based source; SQL does
not provide Chopper's fresh-block collision-refinement contract. qsv Fisher–Yates
is a full permutation under unbiased ideal draws, but resident. Chopper's uniform
path uses 16-byte keyed BLAKE3 keys, refines ties and spills without changing the
requested guarantee. Uniformity does not inherently require BLAKE3, and this
study does not justify weakening collision behavior or restoring removed RNGs.
See DuckDB [random engine](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/common/random_engine.cpp),
[order contract](https://duckdb.org/docs/2.0/sql/dialect/order_preservation)
and Chopper's [random source](../../../crates/chopper-core/src/random.rs).

A general DuckDB backend would additionally need lossless schema/header/null
handling, exact quotas and serialized caps, resource ownership, interruption and
native no-clobber publication, plus a separate WASI integration. `all_varchar`
alone does not disable NULL recognition; v2.0 rejects an empty nullstr list. This
fixture's sentinel is deliberately absent, not a universal escape hatch. The
pinned [option parser](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/execution/operator/csv_scanner/util/csv_reader_options.cpp)
and [string scanner](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/execution/operator/csv_scanner/scanner/string_value_scanner.cpp#L272)
own these details. Porting useful techniques into the existing engine is the
smaller initial experiment.

Historical constraints: [radix](radix-sort-experiment-2026-10-13.md),
[independent buckets](independent-random-bucket-full-shuffle-experiment-2026-10-19.md),
[copied parallel CSV](bounded-parallel-csv-parsing-with-copied-handoff-2026-11-05.md),
[adaptive selector](../decisions/shuffle-ingestion-adaptive-2026-11-15.json) and
[balanced routing](../decisions/shuffle-balanced-parts-2026-11-15.json) were already
rejected/deferred in their recorded regimes. The proposed batching/direct-output
work must eliminate a newly identified cost and meet their reopen rules.

### Evidence and reproduction

The [complete-job summary](../../benchmarks/cross-tool-summary-2026-11-18.json)
is derived from the exact raw JSONL locations and source hashes, not new
observations. There are 69 measured complete jobs and 23 excluded warmups in the
six completed cohorts. The initial smoke and failed cohorts remain separate.
The provenance packet (local `cross-tool-provenance-2026-11-18.json`)
contains source/toolchain/binary identities, complete crate/vendor file hashes,
executed harness snapshots, install identities, research source, runner manifests,
statuses, logs and auxiliary diagnostic source. The local exact Chopper binary is
still `target/release/chopper`; the packet pins its SHA-256 without publishing it.

Raw jobs:

- 128 MiB repeated (local `cross-tool-small-2026-11-18.jsonl`),
  2 GiB 1 GiB-budget (local `cross-tool-large3-2026-11-18.jsonl`),
  128 MiB varied (local `cross-tool-varied-2026-11-18.jsonl`).
- Direct control (local `cross-tool-direct-control-2026-11-18.jsonl`),
  FY control (local `cross-tool-fisher-control-2026-11-18.jsonl`),
  qsvlite control (local `cross-tool-qsvlite-2026-11-18.jsonl`).
- 256 MiB failed batch (local `cross-tool-large2-2026-11-18.jsonl`),
  initial failed smoke (local `cross-tool-pilot-2026-11-18.jsonl`),
  successful smoke (local `cross-tool-pilot2-2026-11-18.jsonl`).
- Component probes (local `cross-tool-components-2026-11-18.jsonl`),
  DuckDB source profile (local `cross-tool-duck-profile-2026-11-18.json`),
  profile pointer extraction (local `cross-tool-duck-spill-normalized-2026-11-18.json`),
  quota control (local `cross-tool-quota-control-2026-11-18.json`).

To replay, use a fresh Python environment containing DuckDB 2.0.0 and the pinned
qsv GNU binary, then select the named cell explicitly. GNU time and POSIX process
groups are required; this is a Linux development harness, not a Windows runner.
With the repository experiment runner, this session used a copied venv interpreter
because executable symlink resolution otherwise selected system Python. The
failed receipt documents the actual behavior; it does not establish a general
change to runner policy.

```sh
# Inspect all options; substitute actual pinned paths in a fresh environment.
python scripts/benchmark-tool-comparison.py --help
python scripts/benchmark-tool-comparison.py run --work scratch/fresh-small-comparison --mib 128 --memory 4096 --repetitions 3 --qsv /absolute/path/to/qsv
python scripts/benchmark-tool-comparison.py run --work scratch/fresh-spill-comparison --mib 2048 --memory 1024 --repetitions 3 --qsv /absolute/path/to/qsv
python3 scripts/test-benchmark-tool-comparison.py
```

The work directory must not exist. The harness stops on the first failed job or
verification and enforces a 600-second job timeout; it does not impose a disk/RSS
quota. Successful output CSVs are removed after exhaustive checks and hashes;
failed artifacts remain local. Runner plans retain the declared outer deadlines
and disk estimates. Existing release/engine tests were not rerun for these
benchmark/doc-only changes; release build, actual benchmark verification, focused
verifier corruption controls and evidence navigation checks are separate records.
No engine default, new backend, merge, deployment or native Windows/browser
qualification follows from this investigation.
