# Adaptive execution: delivered foundation and remaining roadmap

The [agreed auto-mode and maintainability direction](maintainer/auto-mode-and-maintainability.md)
now governs future product policy, including direct execution, default auto with
no reproducibility guarantee, an explicit reproducible mode and automatic resource
sizing. Reconcile the designs below with that brief before implementation; existing
behavior and historical evidence are not changed by the planning decision.

Status: initial implementation and streaming follow-up delivered, 2026-10-12; broader roadmap below. Existing measurements are in [performance.md](performance.md). The objective is fast execution across diverse inputs and machines, with automatic choices for ordinary users and reproducible overrides for advanced users.

Implemented: shape-dependent buffered row storage, shared algorithm-workspace reservations, automatic bounded routing for eligible stable grouping, one-way sorting fallback, the `resources.grouping` / `--grouping` override, and execution diagnostics in JSON and the UI. Native and browser engines share these paths. The working memory default remains 256 MiB. Full-file input profiling and session-local profile caching are now implemented; see [performance.md](performance.md#full-file-input-profiling-2026-10-12). Host-aware total-memory sizing, a predictive per-stage resource planner, and accounting for all engine allocations remain future work. Sections below describe the broader target design unless explicitly marked as implemented.

The 2026-10-16 [shared-admission follow-up](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16) adds a process ledger across profiling/cache/returned copies and prepared/active jobs, transactional denial/rollback, Linux startup headroom discovery and a native aggregate-ceiling override. Per-job numeric budgets retain their meaning. The [boundary-pressure follow-up](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16) adds throttled Linux rechecks and conservative net-growth admission. Accounting remains incomplete, and separate browser workers/tabs are not coordinated.

Grouping fallback reuses ordered grouping files as one logical merge run, read sequentially with one active reader. The former buffer-shuffle implementation has been removed; its dated measurements remain historical.

## Choose strategies per operation

Avoid a single small-file/large-file switch. A pipeline can stream ingestion, partition with bounded writers, sort one small group in memory, spill a large group, and compress several outputs concurrently. The decision concerns the **live working set of each stage**, not whether the source file fits in RAM.

Memory feasibility and speed are separate decisions. More memory can remove merge levels, but larger sorts can also cost more CPU and suffer worse cache behavior. An input can fit in memory while streaming remains its fastest processing strategy. Likewise, many individually small groups need not reside in memory simultaneously.

Preserve existing logical behavior: operation order, exact allocation quotas, partition/group ordering, row order where required, seeded membership and shuffle order, filenames, strict encoded byte limits, and retained-snapshot execution. Automatic resource tuning must not silently select approximate mixing or substitute another seeded shuffle algorithm.

## What the implementation already does

- [`engine.rs`](../crates/chopper/src/engine.rs) fuses several operation combinations. With no operations, ingestion writes directly to the encoded output snapshot. Balanced intermediate splits can share existing row ranges. Partitioning and allocation use the adaptive grouping/sorting module; knowing counts is necessary for exact allocation.
- [`storage.rs`](../crates/chopper/src/storage.rs) already selects in-memory sorting when no runs spill. Retained row payload capacity, actual descriptor capacity, descriptor reallocation overlap and sorter state must fit one quarter of the configured working budget. Shared-workspace pressure can also trigger spilling. Spill/merge output buffers have separate reservations, and external merging uses bounded fan-in and hierarchical run compaction. Explicit Fisher–Yates charges its retained capacity and RNG/state against the same quarter-budget ceiling and fails rather than switching algorithms. [Budget-edge and mixed-group evidence](performance.md#per-group-reservation-accounting-2026-10-15). Fixed dataset readers/writers now reserve their I/O buffers before allocation. Sort-run descriptor arrays now reserve capacity and growth overlap through compaction and merge iteration ([evidence](performance.md#sort-run-catalog-accounting-2026-10-15)). Intermediate boundary scans and encoded merges now validate fields in borrowed chunks with constant UTF-8 carry instead of a field-sized scratch allocation ([evidence](performance.md#borrowed-utf-8-spill-validation-and-copying-2026-10-15)). Retained temporary-file paths also reserve before creation and retain charges through prepared output snapshots ([evidence](performance.md#retained-temporary-path-accounting-2026-10-15)). Compact and owned CSV job-ingestion buffers now reserve capacity and growth overlap; retained input headers remain charged through prepared snapshots ([evidence](performance.md#owned-csv-parser-and-header-accounting-2026-10-15)). Decoded intermediate-input capacity, profiling parsers, remaining conversion overlap, file/runtime metadata and sorting overhead remain incomplete, so `memory_mb` is neither the size of the CSV that fits nor an RSS cap.
- The owned decoded-row adapter has a vector of strings and a key. Its accounting is `96 + key.capacity() + 24 * fields.capacity() + sum(field.capacity())`. Many short columns can therefore cost much more memory than one field containing the same number of CSV bytes. Operation ingestion now parses directly into a compact payload and hashes that v1 framing; plain-output jobs retain owned parsing. Owned adapters still pack short fields and can retain wide strings. Direct compact parsing copies wide field scratch into the row, increasing rare-wide conversion peaks in the measured fixture ([evidence](performance.md#compact-csv-ingestion-and-frame-metadata-2026-10-15)). Allocator overhead and other live allocations also matter.
- Native workers help sorting and independent compression by default. The opt-in [independent uniform-v1 group experiment](performance.md#bounded-independent-group-processing-evaluation-2026-10-16) divides sorter sizing among bounded tasks and replays their temporary results in parent order, with serial retry after admission denial. Selected many-column jobs improve, but skew/small-group regressions and CPU/temp costs keep default group execution serial. Parsing and merge traversal within a group remain sequential. Browser execution is single-threaded and has different storage-call costs.
- Exact analysis performs most processing and retains final CSV bytes before confirmation. A faster preview and a faster processing engine are separate improvements.
- Output chunk catalogs now reserve predecode JSON scratch/tree allowance and retain decoded lineage capacity through peek/batch/thread lifetimes; manifest records borrow that lineage. Dataset group decoding and lineage construction/other clones remain open. [Ownership and validation boundary](performance.md#retained-parent-retry-and-decoded-output-catalog-ownership-2026-10-20).
- Publication writers/readers and the WASI heap copy buffer now retain capacity charges through codec finalization and actual I/O lifetimes. Failed temporary unlink retains orphan charges and stops subsequent execution rather than permitting silent retry. Codec internals, stack/thread overhead and remaining allocation boundaries stay open. [Publication and cleanup evidence](performance.md#publication-io-capacity-and-cleanup-failure-admission-2026-10-20).
- The existing [simulator](../scripts/simulate-resources.py) is exploratory. In particular, its `width + 160` row model and 40% run budget are not the actual variable-column accounting and 25% sorter threshold. Do not use it directly as the production planner.

## Inputs to planning

| Dimension | Observe or estimate | Why it changes the strategy |
| --- | --- | --- |
| Available resources | Usable memory under host/process limits, CPU availability, active jobs, runtime type | Sets a shared job budget and feasible concurrency; installed RAM alone is insufficient |
| Storage | Source/temp/output locations, free space or browser quota, measured sequential throughput and call latency | Several paths can contend for one device; external passes and tiny writes have different costs |
| Input size | Physical bytes, decoded bytes observed, row count estimate and confidence | Compressed bytes do not describe the working set; billion narrow rows differ from millions of wide rows |
| Row shape | Field count, decoded payload, allocation bytes, key bytes, p50/p95/p99/max observed record size | Allocation overhead, outliers, sort-head memory, and encoding expansion can dominate |
| Parsing | Encoding, quoting, multiline fields, compressed container | Determines decoding cost and whether independent parsing is possible |
| Group shape | Distinct keys, key length, count distribution, largest groups, estimate uncertainty | Small fanout favors routing; high cardinality needs bounded metadata; skew defeats equal-sized buckets |
| Pipeline | Count requirements, order dependencies, compatible adjacent operations, required shuffle quality | Determines which passes and intermediate representations can be eliminated |
| Output | Expected files, byte caps, encoding, selected codec and chunk sizes | Controls writer buffers, codec concurrency, metadata, and destination costs |

Gather bounded observations during normal parsing and reuse those rows, rather than adding an unconditional sampling pass. Sampling must use the real CSV parser: newline offsets are not record boundaries in general. A prefix can be unrepresentative, especially for sorted or clustered files. Mark estimates as provisional, update them during execution, and retain bounded fallbacks. Do not extrapolate a prefix's compressed-byte ratio or cardinality as an exact result.

Native resource discovery and browser capability discovery belong in separate adapters. Unknown usable memory should select a conservative fallback. Browser hints are not a reliable heap budget; browser limits, worker overhead, and storage quota require their own constraints. Linux now rechecks pressure at safe stage/run/profile/export boundaries with a one-second throttle ([policy and evidence](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16)). It limits future charged growth while retaining existing owners; browser cross-worker coordination and predictive grants remain open.

## Candidate strategies

These include implemented strategies and further alternatives to benchmark, not claims that every alternative is faster.

| Operation | Small working set / low fanout | Large working set / high fanout | Critical constraints |
| --- | --- | --- | --- |
| Parse, validate, row/byte limits | Reusable record buffers; stream serialization | Same streaming path, bounded read-ahead | Loading the whole input adds no inherent value; retain exact CSV validation and encoded limits |
| Balanced split | Count/index a compact retained dataset; emit ranges | Count while spooling, then use ranges; consume preceding sorted output where possible | Exact boundaries require counts; avoid reparsing the original source after analysis |
| Partition | Stable hash routing into bounded group buffers/writers | Bounded bucket distribution with recursive subdivision or current external sort fallback | Preserve exact keys, existing group ordering and within-group order; bound open files, buffers, and key metadata |
| Exact allocation | After counts are known, route quota draws directly to allocation writers | Sequential traversal plus bounded allocation spools; external grouping for large strata | Preserve quota rounding, RNG draw sequence, stratum traversal, and original order; do not replace with independent percentage draws |
| Uniform shuffle | Compact rows/arena plus sortable key/index array | External random-key sort with compact runs, bounded merge heads and streamed final merge | Keep canonical random keys and collision refinement. The explicit versioned Fisher–Yates option is implemented; it changes seeded outputs and cannot be silently selected |
| Retain intermediates | Compact immutable memory representation when useful across stages | Disk representation with bounded transfer; shared ranges | Spill without restarting or changing logical order; budget conversion overlap and retained references |
| Retain final plan | Consider a memory snapshot for genuinely small outputs | Existing encoded disk snapshot | Both must remain immutable across confirmation; account for idle prepared jobs and migration to disk |
| Compression/export | Several independent chunks if CPU and buffers permit | Bounded batches selected against CPU, destination bandwidth, codec memory, and temp space | Preserve output order and packaging; do not silently change requested compression |

For hash routing, the hash only locates a bucket: actual decoded keys establish equality. A bounded group catalog must reproduce the current encoded-key ordering and preserve encounter order within each group. One writer per distinct key is not a general solution. When fanout grows, flush into bounded buckets or fall back to external sorting; maintain row ordinals so regrouping remains stable. A hot key should not be repeatedly repartitioned forever.

For wide rows, sorting key/offset pairs could avoid repeatedly copying payloads. However, gathering randomly ordered payloads from disk can be much worse than sequential merges. Compare resident payload arenas, block-based gathers, and full-row runs on target SSDs and browser OPFS before choosing this representation. Memory mapping alone does not solve allocation overhead or random I/O.

For many narrow columns, compact representation and fewer allocations may matter more than extra workers. For very wide records, buffer and merge-head reservations dominate. For high-cardinality partitions, catalogs and output-file overhead may dominate even when payload is small. For compressed sources, extra passes may repeat expensive decompression unless a decoded snapshot is retained.

## Planner module and resource accounting

Introduce one deep execution-planning module with a small interface conceptually equivalent to:

```text
plan(job, observations, capabilities, resource_policy) -> execution_plan
```

The plan explains physical choices for each logical stage, reservations, fallback rules, and uncertainty. CLI, server, and browser should consume that same interface. Keep strategy mechanics inside the engine; avoid teaching each caller its own thresholds. Add internal seams where implementations actually vary, beginning with stable grouping by external sort versus bounded routing.

The implemented shared reservation ledger is a prerequisite for aggressive adaptation, with coverage still to extend. Charge concurrently live row arenas, sort/index buffers, parser/decoder storage, merge readers and heads, key catalogs, writer buffers, compression tasks, and memory snapshots. Reserve conversion peaks when changing representation, and allow margin for allocator/runtime overhead. This improves budget enforcement without pretending to impose an OS RSS limit. The server also needs an aggregate policy for simultaneous and retained prepared jobs.

Planning sequence:

1. Validate logical configuration and honor explicit resource ceilings. Resolve a conservative initial budget from usable resources and runtime limits, with an allowance for other applications.
2. Begin bounded ingestion and collect shape/cost observations. Identify count dependencies and legal fusion opportunities.
3. Eliminate strategies that violate semantics or memory/temp/file/handle limits. Estimate peak live memory, passes, bytes moved, and CPU work for remaining candidates.
4. Prefer the simplest candidate within a measured tolerance of the best expected time. Use confidence ranges: small predicted differences do not justify complexity or much larger reservations.
5. Adapt at safe boundaries when observations change materially. Spill before allocation exceeds a reservation; shrink future batches under pressure. Never wait for allocation failure as the normal transition mechanism.
6. Record effective choices and fallback reasons alongside actual stage metrics. Use measurements to calibrate later planning, with runtime/version/storage context so a result from one machine is not treated as universal.

Initially select conservative rules proven by benchmarks. A full learned cost model is unnecessary for the first release. Useful rules include streaming no-operation jobs, bounded routing for demonstrated low fanout, spilling uncertain working sets, and granting memory only when it reduces observed passes or enables a proven faster representation. Avoid live strategy oscillation by requiring a material advantage and switching only at explicit boundaries.

## Evidence-based stage and parent policy design (2026-10-20)

This is a proposed implementation contract, not an enabled selector. The
[workload/runtime synthesis](performance-decisions.md) and subsequent
[Windows calibration](performance.md#native-windows-ssd-shufflepartition-calibration-2026-10-20)
support prioritizing exact pass elimination. They do not calibrate a universal
row-count, cardinality or memory threshold. Existing feature gates, numeric
resource limits and shuffle policies remain authoritative.

The first execution slice now separates retained-parent proposal/admission,
tentative fused sorting and emission for experimental exact shuffle/partition.
Typed admission denial before emission can drop the attempt and replay original
stages; emission errors never retry. Leading raw ingestion is unchanged. This
implements the retained-boundary ownership/fallback seam, not the cost selector,
full observation model or complete accounting described below.

### Decision boundary and observations

Make one physical choice for a logical stage span and an existing parent, rather
than choosing once for the whole input. The engine owns selection; CLI, server
and WASI adapters provide capabilities and consume its diagnostics. Keep the
existing rewrite modules as the authority for semantic eligibility and storage
as the authority for actual capacity admission. A planner must not duplicate
their key/domain recipes or introduce an alternative reservation ledger.

Refine the conceptual interface above into an internal decision followed by an
atomic reservation attempt:

```text
choose(stage_span, parent_facts, capabilities, policy, evidence) -> proposal
try_admit(proposal, current_ledger) -> admitted_attempt | denied
run(admitted_attempt) -> committed_parent | retry_original | error
```

These are proposed interfaces, not current Rust APIs. A proposal carries original
operation indices and parent lineage, eligible alternatives, working-capacity and
temp/file requirements, evidence identity, uncertainty, and a fallback recipe.
It grants no memory. The admitted attempt owns reservations and tentative files;
their ownership must survive iteration and end only after the last consumer.

| Input | Required interpretation |
| --- | --- |
| Parent rows/bytes/counts | Use exact retained metadata where available; input-profile counts are not counts after arbitrary operations. Unknown stays unknown. |
| Working set | Observe payload/key and descriptor capacities, growth/conversion overlap, parser storage, catalogs, readers/heads and writers. Record maxima as well as averages; CSV bytes and row count alone cannot predict fit. |
| Group shape | Track bounded cardinality, largest observed groups, skew and ordering. A prefix cannot prove low fanout; only logical lineage can prove a constant key. |
| Live resources | Read current job/process reservations, pressure status, retained prepared owners, worker and temp/file ceilings. A prior free-capacity observation is not a grant. |
| Runtime/storage | Keep native platform/device/cache and browser storage context distinct. Unknown physical throughput or browser capacity must not be filled from native timings. |
| Contract | Retain explicit strategy, seeded/flexible policy, algorithm/RNG/domain versions, original stage indices and prepared-snapshot guarantee. |

Gather bounded facts during existing ingestion/traversal; require no extra input
scan for selection. Optional cached profiling can inform estimates but cannot
authorize final output counts or bypass required validation. The
[direct-execution design](direct-execution.md) separates Run dispatch from this
stage/parent selector; explicit exact preparation still retains its snapshot.
Release observation catalogs with their stage/parent,
charge retained capacity, and stop collecting keys when their grant is exhausted.

### Feasibility before speed

For each candidate, construct a lifetime envelope for simultaneously live owners,
including retained input, tentative output and representation-conversion overlap.
Do not sum separately measured peaks to manufacture that envelope. Estimates
filter candidates; reservation-before-allocation still enforces capacity at every
growth boundary. Unknown untracked costs retain runtime headroom rather than
being assigned zero. The current quarter-job sorter limit and half-job shared
workspace ceiling remain in force; this design does not enlarge either.

Admit a candidate only if its next bounded step fits local and shared ledgers and
its temp/file requirements. Recheck at existing safe boundaries; pressure can
reduce future growth without revoking already live owners. Account for a replay
source and tentative files together when retry is possible. If no legal plan can
fit one record or required merge heads, return the existing clear resource error.

Only then compare complete-job cost, including preparation, extra audit or
materialization passes, final serialization and publication/export. Predict
traffic and merge hierarchy for both alternatives; fewer runs alone is not a
speed criterion. Prefer the existing path when context is unmatched, observations
are too uncertain or the expected difference is within measured variability.
No numeric tolerance or crossover is selected by the present evidence. The
[Windows transition follow-up](performance.md#windows-shufflepartition-spill-transition-calibration-2026-10-20)
reinforces this separation: at 17,000 rows fusion spills while baseline stays
resident, its elapsed ranges overlap and temporary traffic increases. Larger
external gains cannot erase that control or turn this fixture's observed row
brackets into a selector for another parent or memory-pressure state.

### Candidate decisions

| Candidate | Proposed choice and evidence boundary | Conservative alternative |
| --- | --- | --- |
| Exact uniform/auto shuffle then partition | First selector to evaluate behind the existing experiment gate. Preserve original parent random keys/collision domains and child tuple order. Windows external and hierarchical complete jobs improve despite more runs; include resident, skew and rare-wide controls. This supports evaluation, not automatic enablement. | Existing separate logical stages, or the candidate's existing bounded external sorting when only resident capacity is exhausted. |
| Nested balanced ranges / proven constant keys | Use existing eligibility proofs, per-parent counts and original rounding/lineage. Prioritize deep chains and mixed varying/constant keys; small repeat-only cases can regress. | Original stage sequence when proofs or bounded metadata are unavailable. |
| Partition/uniform/balanced | Evaluate terminal single-parent cases first, retaining the charged tuple counter. Later parents/downstream cases have recorded losses; insufficient rows must keep the original failure. | Discard denied tentative work and replay original materialization. |
| Consecutive partitions / membership chains | Require runtime-specific evidence that separates routed winners from plans that introduce external merging. The large browser regressions exclude an unconditional fusion rule. | Current routing/sorting and original stage sequence. |
| Parallel profile | Keep serial as the baseline. The surviving native profiling experiment requires admitted hash batches and complete-job evidence including the extra scan when profiling is optional. Browser remains single-threaded. Independent-parent batching/replay was removed after E2 and is not a candidate. | Serial profile, or skip an optional profile and perform required execution work. |
| Compact spills / flexible allocation ranges | Keep separate opt-in decisions. Compact spills need persistent-browser/device calibration; native transcoding regresses. Allocation ranges require explicit flexible replay consent and many-parent/rare-wide controls. | Existing spill format and requested policy's original plan. Never switch seeded jobs to flexible algorithms. |

For the first row, Windows raw measurements at lines 3-8, 11-16, 19-24, 27-32
and 35-40 of
[the native artifact](evidence-originals.md#sha256-b484ffd6976ed1b34e49d82c62b3f9b4fc3a79a432682cb5169ebd62f7b96f62 "Original: docs/benchmarks/windows-shuffle-partition-native-2026-10-20.jsonl")
each contain three baseline and three candidate complete jobs. Environment line 1
pins binaries, sources, features, harness, 32 MiB/four workers and warm/uncontrolled
NTFS/NVMe context; fixture lines 2, 10, 18, 26 and 34 pin shapes/hashes. The source
SHA-256 is `b484ffd6976ed1b34e49d82c62b3f9b4fc3a79a432682cb5169ebd62f7b96f62`.
Summary lines are derived, not additional observations. The pilot and CLI control
artifacts are excluded from timing estimates. The dated performance section
retains medians, ranges, correctness and resource tradeoffs; historical synthesis
cells remain separate strata. In particular, rare-wide reservation growth and
unmeasured physical I/O prevent treating pass elimination as universal capacity
or device-throughput improvement.

### Fallback, replay and diagnostics

Use one-way transitions within a parent: resident to spill/merge, or bounded
routing to existing ordered-run fallback. Do not oscillate strategies as estimates
change. A fusion that cannot continue in place may retry the original graph only
from a retained replayable boundary. Before retry, drop tentative writers/readers,
join sibling tasks, remove job-owned files and release reservations; retain the
source and original domains. Do not restart a partially consumed raw input unless
the existing executor supplies a valid replay boundary. A cleanup failure is
reported, never hidden by a successful retry.

Retry only typed admission/eligibility failures for which the executor provides
that fallback. Propagate cancellation, corrupt input, cap violations and storage
errors through ordinary cleanup. Commit parent results and logical diagnostics
only once; retain physical attempt/fallback counters separately. Never publish
tentative output. Native atomic directory publication and browser completion
markers keep their separate contracts.

Proposed diagnostics record stage span/parent, observed versus estimated facts,
candidate rejection/denial reasons, granted and actual peak capacity, routing or
spill transitions, merge operations, and selected algorithm/plan versions. Record
calibration artifact hash/cell and planner version when a measured rule is used;
do not add timing/hardware details to the logical seeded-output fingerprint.
Exact plans must preserve seeded-v1 bytes/order across budgets and workers.
Flexible plans retain their versioned actual-algorithm audit and prepared-snapshot
replay limit; changing a grant cannot silently promise seed-only replay.

The implementation acceptance boundary is the planner/executor interface: test
late wide rows/new keys, concurrent and retained-owner denial, collision/hierarchy,
typed rollback, cancellation during retry and cleanup failure, alongside exact
bytes, membership, lineage, caps and snapshot publication. Threshold calibration
should then bracket an observed capacity transition with matched complete jobs,
retaining a losing/near-flat control. Stop selection work if benefits disappear,
resources are unbounded or replay/cleanup fails. Implementation and calibration
remain in [GitHub Issues](https://github.com/jsmatfess/chopper/issues); this design adds no runtime validation or new timing
samples.

### Implemented bounded retained-parent observations (2026-10-21)

The gated exact shuffle/partition retained-parent path now records a charged,
lazy prefix of at most 16 completed attempts. Records retain original stage and
parent identity, decoded/keyed shape completeness, actual row/key capacity
maxima, typed denial phase, commit/terminal outcome and context counter deltas.
Collection denial and omitted attempts are explicit. Optional collection failure
does not fail execution; successful collection consumes headroom and may shift
spill boundaries. This does not implement cost selection or calibrated estimates:
policy remains the experiment gate and selector/calibration are absent.
See the [implementation evidence and limits](performance.md#bounded-retained-parent-decision-audit-2026-10-21).

## Auto policy reconciliation (2026-10-28)

This completes the design reconciliation with the [Auto brief](maintainer/auto-mode-and-maintainability.md).
It specifies future selection; it does not enable a selector, change omission
defaults, or promote a Cargo experiment. The [specification](specification.md)
continues to own delivered behavior. The retained-parent design above supplies
the execution seam; [direct execution](direct-execution.md) owns Run dispatch.

### Selection order and authority

Resolve configuration and explicit resource overrides first. The current
`seeded_v1` omission, numeric 256 MiB memory omission, opt-in `memory_mb: "auto"`
resolution and worker rules stay authoritative until separately validated code
changes them. Future Auto is a distinct execution policy; neither a shuffle
named `auto` nor automatic memory sizing opts a job into different seeded output.
Explicit algorithms, exact allocation and reproducible execution constrain every
proposal. Reproducible jobs admit only plans preserving the recorded algorithm's
logical results across budgets/workers. Flexible experiments retain their own
consent, feature gates and prepared-snapshot replay contract; they do not become
the future Auto default implicitly.

Choose in this order: prove semantic eligibility using the existing rewrite
module; filter by runtime capabilities and resource feasibility; compare total
cost only among the remaining candidates; then attempt actual admission. Keep
unknown facts explicit. A proposal grants no capacity, and a free-memory estimate
cannot override either the shared pool or local growth limits. Explicit
Fisher-Yates remains a clear error when infeasible, rather than an implicit
algorithm substitution. Exact allocation never becomes probabilistic allocation.

The engine owns this policy once for CLI, native server and WASI. Adapters supply
runtime capabilities and user configuration; they do not reproduce selectors.
Storage owns grants, spill transitions and temporary lifetimes. Rewrite modules
own operation indices, lineage, key recipes and eligibility proofs. Publication
owns final commit. This keeps selection behind a small interface without adding
a second ledger or a general registry of strategy implementations.

### Facts, observations and required work

Configuration-only facts include ordered operations, selected columns, explicit
algorithms, parser/encoding settings, output caps, runtime capabilities and
requested limits. File length is encoded source size, not decoded working-set
size. A prior partition can prove a constant column through supported subsequent
operations; a sample containing one value cannot. Exact retained-parent counts
can support quota/range decisions only for that parent and operation span.

Optional observations include a compatible cached profile and admitted bounded
statistics gathered during required traversal. Treat cardinality/skew/width
estimates as incomplete unless their source proves completeness. Cache validity
does not make a profile an execution snapshot. Stop collecting when admission
fails and use conservative selection; observation denial must not require a new
scan or fail otherwise feasible execution. Retained observations and diagnostics
must have owners/grants, including construction overlap and final-clone lifetime.

Required work includes full parsing/validation, exact counts where an operation
requires them, sorting/grouping, serialization and publication/export. It cannot
be skipped because an optional sample looks favorable. Collect observations while
doing that work when possible. A new optional full profile is skipped by default:
there is currently no calibrated rule showing that its selection savings repay
its complete cost. A future rule must name the competing plans, runtime/workload
coverage, observation ceiling and measured uncertainty; stop observation when it
cannot change the choice. With no justified rule, execute the existing plan.
An explicit user request to analyze input remains available independently.

### Conservative choices on surviving paths

The production baseline uses current exact rewrites and ordered stages, bounded
external sorting where supported, and existing serial parent execution. A compiled
experimental feature remains opt-in; compilation alone is not evidence for a
cost-based Auto rule. Retain nested-balanced, constant/consecutive partition,
partition-balanced, streaming-chain and exact shuffle/partition eligibility in
their owning modules. Flexible allocation ranges remain separately gated.
Compact spills remain unresolved and opt-in after E1. E2 parent batching and E3
input snapshots are removed and cannot appear as fallback choices.

Native decisions use current shared admission headroom and native capabilities;
WASI retains its browser budget bounds and single worker. Prepared execution
reuses its Context and encoded snapshot. Do not transplant native timing rules to
OPFS, infer physical device throughput from cached process I/O, or increase worker
counts from an uncalibrated CPU heuristic. Existing worker selection is the
fallback. Uncertain width, skew, capacity or cost keeps the existing legal plan;
if that plan cannot admit required work, return its resource error.

The bounded E5 memory panel supports keeping automatic memory opt-in and numeric
memory omission unchanged. It does not establish a strategy/worker selector or a
browser crossover. Compare future candidates against simple existing plans on
held-out, no-benefit, late-wide/skew and concurrent-denial cases. Include optional
observation, unsuccessful attempts, preparation, serialization and export in
complete-job cost. No new numerical threshold, device learning or benchmark
matrix is selected by this design.

### Next implementation and acceptance

The next bounded implementation is the shared exact-plan proposal/fallback seam
for retained parents. Start by replacing the existing exact shuffle/partition
proposal machinery, keeping its gate and behavior, with an interface usable by
another surviving exact fusion. Do not route raw ingestion through retained-parent
retry or add cost selection in that refactor. A proposal borrows original spans
and parent identity; an admitted attempt owns tentative resources; successful
preparation yields a result whose emission is terminal on error.

Before-emission typed denial may retry original stages only after tentative
owners are dropped and cleanup succeeds, retaining the replay source and original
domains. After emission starts, no replay is permitted even when the sink is
private. Cancellation, malformed input, cap/storage failures and cleanup errors
remain terminal. Logical stage/parent results commit once; physical attempt
diagnostics remain separate and admitted. Native atomic publication and browser
export markers retain their distinct lifetimes.

Acceptance exercises this interface with exact field/ID/order/membership and
lineage parity, original indices, local/shared denial and competing-owner retry,
late-wide/skew growth, first/last emission failure, cancellation and cleanup
failure. Preserve explicit prepared execution and direct Run's unsupported-plan
fallback before raw input consumption. Apply contributor checks to changed
surfaces. The reconciliation itself changes no execution policy. The subsequent
[shared exact-plan seam](validation.md#shared-exact-plan-retained-parent-seam-2026-10-28)
now serves retained shuffle/partition and streaming-chain parents under their
existing gates. Broader pipeline coverage, E5 calibration, selection and default
promotion remain separate items in [GitHub Issues](https://github.com/jsmatfess/chopper/issues).

### Available predecision observables and cost hypothesis (2026-10-28)

**Decision: current evidence does not justify a nontrivial cost selector.** Keep
the existing gates and defaults. For a future selector, unknown cost chooses the
original stages; this is not an instruction to change today's explicitly gated
fusion behavior. The completed native worker panel compares worker settings on
the default engine, not retained fusion against original stages. It cannot supply
the missing strategy comparison or a browser rule. No row-count bracket, CPU
count, device label or observed free capacity becomes a crossover threshold.

The decision point is inside retained `Plan::apply`, after reading one admitted
catalog parent and before `Admitted::new`/any parent row traversal. It is distinct
from raw-ingestion dispatch and from a decision made after sorting. The following
inventory is verified against current source; proposed additions are marked.

| Class | Available fact and limit |
| --- | --- |
| Exact metadata before the attempt | [`Group`](../crates/chopper/src/storage.rs#L1138) contains offset, row count, lineage and exactness. [`Dataset`](../crates/chopper/src/storage.rs#L1149) contains the data/catalog owners and total group count. The parent's offset is not its byte length; neither type stores its ending offset, decoded payload totals, tuple cardinality/skew or row/key heap maxima. `Group.exact` is metadata, not a capacity certificate. |
| Exact configuration/proof before the attempt | [`Plan::at`, `random`, `resolve`](../crates/chopper/src/engine/shuffle_partition.rs#L745) provide adjacency, original indices, selected columns and original parent shuffle domain. Header/column count and effective Context budget/workers are already available. Resolving selected columns into a Vec still requires admission; a known column count does not grant its allocation. Supported lineage proofs can establish constant keys, but an observed prefix cannot. |
| Exact existing capacity, with a live owner | Existing configuration/header/parent metadata capacity and reservations describe allocations already retained. [`Workspace`](../crates/chopper/src/storage/adaptive.rs#L15) tracks used/peak capacity and optional process accounting. Limits, usage and pressure are observations at a moment; reading them neither reserves the difference nor predicts another owner's release. There is no existing general planner headroom snapshot interface. Do not construct/serialize diagnostics just to obtain one. |
| Estimates or unknowns before the attempt | Source file size, cached input-profile widths/cardinalities, any earlier-parent observations and configured maximum record size do not establish this parent's keyed working set. No current stored summary proves future Vec capacities, allocator growth overlap, tuple-key expansion, routing success, sort runs/merge hierarchy, comparator CPU cost or storage latency. Maximum record size is a validation ceiling, not a measured maximum or predicted row allocation. |
| Observations obtained only by doing work | [`Admitted::prepare`](../crates/chopper/src/engine/shuffle_partition.rs#L46) decodes rows, constructs tuple/random keys and pushes them into the sorter. [`ShapeObservation`](../crates/chopper/src/storage/decision_audit.rs#L7) obtains payload totals and actual keyed heap/key maxima there. [`DecisionRecord::finish`](../crates/chopper/src/storage/decision_audit.rs#L160) establishes completeness and context-counter deltas after the attempt. Partial/denied records and the first-16 prefix are not a census. These cannot select that same attempt before it starts; even a complete earlier record is not a certificate for the next parent. |
| Grants | [`Reservation`](../crates/chopper/src/storage/adaptive.rs#L81) admission, including vector growth/replacement overlap, authorizes actual allocation. Resolved-column, decoder, key, sorter, merge, metadata and output grants remain separate owners. Successful observation collection consumes headroom; a proposal, cost estimate or apparent fit is never a grant. |

The concrete hypothesis remains exact retained-parent shuffle/partition versus
its [`original`](../crates/chopper/src/engine/shuffle_partition.rs#L895) two-stage
execution. Original execution sorts by the original parent random domain, writes
a shuffled Dataset, rereads it, then partitions using the existing grouping
implementation. Fusion sorts tuple plus original random key/domain and emits
partition children, removing that intermediate shuffled materialization and its
traversal. **Hypothesis:** on a parent whose baseline already requires external
sorting, avoided materialization/traversal and separate grouping cost can exceed
fusion's larger composite-key construction/comparison, additional spill/merge
work, observation overhead and any unsuccessful attempt/cleanup/retry cost,
reducing complete-job latency with identical logical output and bounded owners.
This is a causal hypothesis, not an implication that external sorting is a
sufficient selection predicate or that baseline partitioning always sorts.

Express the comparison as `T_original - T_fused > 0`, where each T includes
startup, all parents and downstream stages, preparation, serialization,
publication/export and exit. For fusion, include observation construction and
retention, failed preparation, cleanup and original-stage retry when incurred.
Keep a separate resource envelope for simultaneous owners; do not turn bytes
saved into seconds with an assumed device bandwidth. A proposed rule is falsified
for its declared eligible cell if matched complete jobs fail to separate a gain
from run variability, regress, violate that envelope, or lose parity/cleanup.
Do not average a losing control away using larger winning cells.

The existing Windows external/hierarchical gains motivate this hypothesis, while
the resident-baseline/fused-spill transition is its concrete counterexample to
unconditional pass-elimination advice. The evidence discussion under
[feasibility before speed](#feasibility-before-speed) and the linked native cells
above retains their provenance and exclusions. Historical brackets describe
those fixtures/builds, not a predecision observable identifying a new parent's
resident/external transition. Native cached process transfers establish no
physical throughput coefficient; WASI needs its own comparison. The worker
panel's mixed differences cannot repair this gap.

#### Small internal interface and conservative branch

When sufficient facts and a supported rule exist, add one private,
allocation-free decision function at the seam immediately before
the existing [`exact_plan::Proposal`](../crates/chopper/src/engine/exact_plan.rs#L6).
It borrows the existing eligible plan and admitted parent; it neither reads rows,
resolves columns into a new vector, opens files, constructs domains/diagnostic
JSON nor calls a sink. A sketch, not a new public configuration format:

```text
consider(eligible_plan, parent_facts, resource_view, cost_evidence)
    -> Original(reason) | ProposeExact(eligible_plan, evidence_id)
```

`parent_facts` initially borrows Group/Analysis and contains only existing exact
metadata. `resource_view` is a scalar advisory view obtained after the existing
pressure boundary, without holding process/audit locks through admission.
`cost_evidence` is `Unknown` until a versioned, runtime-scoped rule can evaluate
its required facts; do not invent a numeric score or embed historical fixture
names. Unknown/missing/incomplete/overflowed/mismatched facts return
`Original(UnknownCost)` in the future selector. Eligibility stays in the rewrite
module; admission/preparation/retry stays in exact_plan and storage. Keep today's
experiment-gate dispatch outside this initial decision function so introducing
the interface preserves existing behavior. Do not build a registry of strategies
or a generic profiling module for this one comparison.

The minimum missing observable is a complete parent-specific representation
summary available before the attempt, sufficient to distinguish baseline and
composite-key capacity/traffic envelopes. A small first extension could accumulate
checked spool byte totals and payload/field maxima during already required Dataset
writing and retain completeness/provenance with that parent. It must support
shared balanced ranges: a whole Dataset aggregate is not a child-range summary.
Such totals alone still do not prove keyed heap capacities or predict runs under
concurrent admission. A later bounded tuple-key envelope must follow the actual
encoding and pinned allocator/growth rules, include descriptor and replacement
overlap, and explicitly remain unknown when not derivable without extra work.
Do not build keys twice, add a new scan, retain a cardinality map, or introduce
learned device rules merely to make a selector possible. An envelope census is
implementation evidence, not timing evidence; calibrated complete-job benefit
would still be missing after this extension.

Borrowed facts add no retained heap allocation. Any later parent summary must be
pre-admitted during construction, charged through catalog/range ownership and
released after its final consumer, including copied/shared ranges. Observation
denial discards optional facts and selects the conservative branch, without
failing otherwise feasible execution. Retain the replay Dataset and original
domains while tentative columns, decoded rows, keys, sorter runs and paths live;
do not sum independent recorded peaks as their simultaneous envelope. Tentative
owners drop and cleanup/cancellation checks succeed before typed pre-emission
retry. Once emission is called, every error is terminal, including sorting or
metadata work deferred into emission. No replay is authorized after emission,
even into private output. Publication lifetimes remain owned by direct-execution
and the existing native/browser adapters.

#### Next coding slice and acceptance

First assess whether a bounded writer-summary extension can supply a useful
envelope for both ordinary parents and shared ranges. Do not add a disconnected
decision function whose only result is `UnknownCost`: until it can inform a real
caller, the existing gated dispatch already expresses the conservative behavior.
Implement summaries only if they can supply a named rule's missing facts during
required writes, with bounded admitted ownership and no additional scan.
Introduce the private borrowed-facts interface together with its first supported
consumer. Test original indices/parent identity, missing facts,
overflow/incompleteness and runtime mismatch; assert no extra row traversal or
sink calls during selection. Reuse the shared seam's existing
denial/cancellation/emission contracts rather than duplicating its executor.
If it cannot separate the recorded spill counterexample without key construction
or another scan, stop cost-selection work and retain the existing legal plan.
Broader E5, default promotion, observation-summary implementation and calibration
remain open; this design alone closes only the observable/hypothesis prerequisite.

#### Writer-summary feasibility outcome (2026-10-28)

Source inspection of `DatasetWriter`, `GroupFrameLengths`, ordinary/nested
balanced ranges and key construction supports deferring both summaries and the
selector. Materialized writes and existing shared-range frame scans could collect
checked scalar totals/maxima without another traversal. Strict subranges would
need fresh facts from their own consumed frames; they cannot inherit parent
totals. Identical full intervals could retain facts only with the same data owner
and framing. These are feasible logical-size observations, not future allocation
capacities or a cost rule.

Whole-row sizes cannot establish selected-field/NUL expansion, key equality and
baseline routing success. Totals/maxima also omit the ordered decode/key/vector
replacement overlap and future competing grants that can change spill behavior.
A packed-size lower bound can exclude some resident cases, but it cannot show
that fusion repays its composite-key and merge costs. It therefore does not
resolve the resident-baseline/fused-spill counterexample.

Do not add unused Group fields: their internal JSONL schema, clone grants,
descriptor layout and catalog/decode admission would create maintenance and
ownership obligations without a supported consumer. The detailed local reasoning
is retained in `scratch/parent-summary-feasibility-2026-10-28/report.md`; this
section preserves the decision independently of that local file. No benchmark
or implementation was performed. Reopen only for a named runtime-scoped rule
with facts obtainable during required work, an explicit conservative uncertainty
branch and a decision-changing complete-job comparison. Continue independent
ownership/release work rather than automatically extending calibration.

## User-facing controls

Default experience: **Automatic resources** with an explanation such as “Streaming input; grouping into bounded temporary buckets; processing groups individually.” Show estimated resource ranges early, actual counters as work progresses, and an expandable account of why each strategy was selected.

Keep two concepts distinct in the interface: **execution policy** chooses physical implementations; **shuffle strategy** chooses a supported uniform permutation algorithm. The existing shuffle `auto` currently means uniform and should retain that semantic guarantee through future execution-policy changes.

Advanced controls should expose a small set of stable constraints first:

- Maximum working memory, workers, temporary directory/space, record size, and file count (existing controls).
- Automatic versus forced in-memory/external strategy where applicable. Forced in-memory fails clearly if infeasible; auto can spill. A forced strategy must not weaken exactness or memory checks.
- Optional per-operation strategy overrides for diagnosis and repeatable benchmarking.
- Explicit uniform random-key or resident Fisher-Yates shuffle.
- Export of the resolved execution plan and effective configuration, including algorithm version, seed, and all output-affecting settings.

Keep merge fan-in, run size, and individual I/O buffers internal initially; expose diagnostic overrides only if measurements demonstrate a power-user need. An automatically selected memory budget is a ceiling, not a target allocation. Explicit numeric settings in existing v1 jobs must retain their meaning; new policy fields need coordinated Rust/UI schema support and documented precedence. Example names here are proposals, not accepted JSON fields.

## Full-file profiling versus exact preparation

Implemented product choice, 2026-10-12: **Analyze input** scans and validates every record without executing operations or preparing final CSV bytes. A sorted prefix can omit entire groups, so this is a full-file scan rather than a sampled preview. Total records are exact. Column and requested input-key cardinalities cover the entire file; estimates are labeled when bounded metadata cannot retain an exact set. These are input statistics, not final counts after arbitrary composed operations.

One profile is cached per native server or browser worker session. Parser/source changes invalidate it. Seed, output, cap, and compatible operation changes reuse observations; newly requested column combinations require another scan. A cache hit never authorizes publication or makes output validation unnecessary. Full-file profiling is optional: going directly to preparation still avoids an extra source pass when exploration is unnecessary.

**Prepare exact outputs** reads the full source again, applies all operations, checks exact encoded limits, and retains immutable output bytes for confirmation. This makes the expensive phase explicit. The profile carries descriptive stage strategies, not a calibrated physical plan with reservations; estimates currently do not drive the execution strategy. Host-aware planning remains separate work.

Progress distinguishes input profiling, grouping, sorting/merging, preparing output bytes, and publishing. A future bounded preview, if added, must be explicitly approximate and must not replace the full-file profile for sorted or clustered inputs.

## Evidence and benchmark design

Treat “optimal” as the fastest validated candidate under the user's constraints, with uncertainty, rather than one universal threshold. Optimize complete-job latency and resource peaks; also report time to preview and preparation separately. Do not reward an apparent analysis speedup that just moves work to execution.

Use a staged matrix instead of an exhaustive Cartesian product:

| Axis | Required coverage |
| --- | --- |
| Scale relative to usable budget | Tiny, comfortably resident, near spill threshold, several times larger, many merge levels |
| Shape | One narrow field; many narrow fields; medium rows; wide payloads; rare maximum-sized rows; long keys |
| CSV/container | Quoted delimiters/newlines, escaping, Unicode, expanding output encoding, plain/gzip/Zstandard/ZIP |
| Group distribution | One key, small fixed fanout, growing/high cardinality, mostly unique keys, heavy skew, late new keys |
| Pipeline | Plain limits, balanced, partition, assignment/strata, exact shuffle, approximate shuffle, important ordered combinations |
| Machine/runtime | Constrained memory, several CPU counts, native and browser, SSD cache conditions and browser OPFS call latency |
| Placement/output | Shared versus separate source/temp/output devices, plain/compressed outputs, few large versus many small files |

Start with small cases that cross strategy thresholds, then selected larger tests that expose multiple merge levels and storage saturation. Simulated budgets exercise spill decisions; they do not reproduce a genuinely memory-constrained machine's paging. Use real constrained environments and target SSD runs before validating defaults. Record cache state; warm-cache and cold-cache SSD results answer different questions. Slow-storage optimization is not a priority.

For every case collect stage wall/CPU time, peak RSS where meaningful, peak reservations, rows/decoded bytes, source and temp read/write totals, spill runs, merge levels, fan-in, group skew, output count, and compression/export cost. Alternate baseline/candidate order, repeat runs, retain raw observations, and compare medians plus variability. Sparse prefix benchmarks are not scale predictions.

Correctness gates must cross the real planner/executor interface: compare output bytes, membership/order, filenames, stage stats, caps, and metadata across strategies, budgets, workers, and seeded repetitions. Exercise late wide rows, underestimated cardinality, spill transitions, random-key collisions, temp exhaustion, cancellation, and source replacement. For compression compare decompressed logical output where codec bytes are not guaranteed stable.

## Implementation order

Current status against the original sequence below: stages 1–3 are partially delivered (diagnostics, shared algorithm reservations, compact buffers, parser reuse, routing and streaming consumers). Full allocation coverage, predictive plans, host-aware sizing and broader calibration remain open. Inline keys and explicit Fisher–Yates/probabilistic/interleaved options are also delivered; they do not authorize automatic changes in semantics. See [GitHub Issues](https://github.com/jsmatfess/chopper/issues), [remaining experiments](performance-opportunities.md), and [measured implementations](performance.md).

1. **Explain and measure:** distinguish preview/preparation/publication; report resolved strategy, reservations, physical I/O, and useful stage timings. Extend the benchmark matrix and calibrate the simulator against actual accounting before relying on predictions.
2. **Budget and representation:** shared reservations, reusable parsing storage, compact row/key representation, and bounded spill conversion. Measure allocation/CPU costs rather than assuming all long runs are memory-bound.
3. **Operation alternatives:** bounded stable partition routing and direct allocation routing once counts exist; ingestion-fused approximate shuffle; benchmark against existing sorting/fusion paths. Keep current external sort as the conservative fallback.
4. **Automatic policy:** select among validated alternatives using live shape observations and host/runtime adapters. Expose explicit constraints and an inspectable plan before adding many tuning knobs.
5. **Broader optimization:** memory-backed retained datasets/output, indirect wide-row sorting, storage-aware merge scheduling, and parallel parsing only where evidence warrants it and CSV boundaries/ordering can be preserved.

The first production milestone should improve a broad set of jobs without changing their logical results. A new shuffle algorithm, approximate statistics in place of exact output validation, and automatic changes to compression are separate product decisions.
