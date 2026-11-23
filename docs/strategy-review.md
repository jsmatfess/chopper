# Strategy retention and maintainability review

E2 status (2026-10-25): Astra rejected independent-parent batching/replay; its
bounded removal is accepted by Astra after actual-diff and raw verification review. E1 remains unresolved;
E3 compact and IPC retention are separately rejected by Astra; Astra accepted the R25 implementation
and raw verification and the R26 final documentation diff. E3 is complete, as recorded in the
[E3 decision](performance.md#direct-input-snapshot-rejection-and-removal-2026-10-26).
The [E2 decision and limits](performance.md#independent-parent-batching-removal-2026-10-25) remain unchanged.

Implementation status (2026-10-24): independent buckets and buffered XOF are removed.
Partition-first and dormant Parquet feature/dependency wiring are also removed.
Counter-v1, the flexible ordered baseline, allocation ranges, exact shuffle/partition
remain; direct compact/IPC APIs were subsequently removed after the separate E3
rejections. Contributor/check routing is complete.
Validation and ownership are recorded in the corresponding current documents.

Buffer-shuffle removal and the radix/prefix-distribution follow-up are implemented;
the inventory and removal recommendations below record the pre-removal review.
Current acceptance and remaining limitations are recorded in [validation](validation.md).

Phase one, 2026-10-23. This is a decision report, not an implementation change or
another checklist. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns
the active backlog and dependencies. The [agreed brief](maintainer/auto-mode-and-maintainability.md) fixes the
product direction; [specification](specification.md) and
[rewrite eligibility](pipeline-rewrites.md) still describe current behavior.

## Decisions and confidence

Retain canonical random-key sorting, external merge and original-stage execution
as the reproducible baseline and bounded fallback. Preserve compact ingestion,
streaming consumers and exact existing fusions. Prioritize exact pass elimination
over adding permutation machinery. Keep explicitly requested Fisher–Yates,
interleaving, exact allocation and probabilistic allocation as distinct useful
capabilities. These decisions do not depend on a universal speed advantage.

Remove buffer shuffle as already agreed. Recommend subsequently pruning radix,
prefix distribution, independent buckets, XOF and flexible partition-first: their
current implementations add complexity without a demonstrated necessary advantage
over simpler available paths. These are retention recommendations, not claims
that the underlying algorithm can never win. Do not remove dependencies shared
with survivors. Compact spill storage remains unresolved under E1. Direct parsed snapshots were
separately rejected for compact and IPC after the bounded E3 experiment below. Keep promising exact
fusions conditional on runtime/shape selection and transactional fallback.

The future Auto policy is not the existing `Shuffle::Auto` alias or the existing
`flexible_v1` planner. Auto may choose different uniform permutations and downstream
membership, but may not approximate exact allocation or move positional splits
without preserving the requested semantics. Reproducible execution must retain
one versioned logical result across supported platforms/budgets/workers. Existing
flexible audit/snapshot machinery is a reusable seam, not a ready Auto selector.
No numeric selector, automatic memory budget or speed/count-deviation threshold
is established here. Native and hosted choices must earn retention separately.

## Corpus coverage and traceability

The [machine-readable coverage audit](benchmarks/strategy-corpus-review-2026-10-23.json)
accounts for all **139 pre-review evidence sections, 638 pre-review artifacts,
35 artifacts without a performance-section link and 32 review families**. It
retains every source's SHA-256, fields, record kinds, context locations, evidence
links and first/last physical record locations by kind. JSON documents remain
whole documents; nested observations require explicit JSON pointers. A family
assignment is a reviewed navigation association, not inferred build or fixture
metadata. Exact duplicate contents stay listed and count only once as evidence.

The audit reuses `benchmark-catalog.py`'s parser/record reader. It reads every
JSON/JSONL document, inventories logs and script snapshots, and rejects unknown
sections/orphans on refresh. It does not pretend that reading a schema admits
every duration as a measurement. Reproduce without executing engine jobs:

```sh
python scripts/audit-strategy-evidence.py
python scripts/audit-strategy-evidence.py --check
python scripts/benchmark-catalog.py
python scripts/benchmark-catalog.py --check
```

The [existing 38 contrasts](performance-decisions.md#numerical-audit) and their
[derived numerical audit](benchmarks/performance-decisions-2026-10-20.json) remain
the source of selected medians, sample counts, observed min/max, raw labels,
filters and physical lines. References to cell IDs below resolve there. The
later Windows summaries retain their own hashes/physical lines and are separate
populations. This review expands family coverage and retention decisions; it
does not replace the numerical audit with a pooled score. Older before/after
bundles establish the bundle's effect, not isolated attribution to each component.

The evidence ledger below gives admission rules for **all families**, including
families with no comparative timings. Use the audit's `sections[].family` and
`sources[].families` to enumerate their exact members. Missing build, fixture,
cache or browser-context metadata remains unknown. Derived summaries, replayed
quality samples and contracts are not additional independent observations.

| Families in coverage audit | Eligible use and exclusions | Consequence |
| --- | --- | --- |
| `original-pipeline-and-scale` | 2026-10-10 complete native jobs and 10-11 engine comparisons establish their own scopes. Early billion-row split and later billion-row shuffle are single acceptance points. Sequential browser suites are observational; diagnostic single runs and resource simulations are separate. | Keep direct plain serialization, retained encoded outputs, shared ranges, streaming final merges, bounded browser read-ahead/handle reuse. No current-build scale certification or device claim. |
| `adaptive-routing` | Exploration is design evidence; final 66-job native pass has 3 repetitions per side/cell. Late-key and wide controls lose; later fallback pass is separate. | Retain resident/routing/sort alternatives; charge failed routing to total cost. |
| `compact-parser-and-consumers`, `balanced-boundaries` | Matched compact resident/group/external, parser reuse, key/digest/serialization and boundary passes support their own full jobs. Worker/browser follow-ups stay separate. Allocation censuses and parser controls cannot enter timing samples. | Keep compact/borrowed fast paths and owned adapters needed by codecs; avoid reopening a CSV-to-owned-row conversion. |
| `buffer-shuffle` | Historical compact/buffer/ingestion-fusion comparisons explain past behavior only. | Removal fixed regardless of past gains; preserve evidence. |
| `explicit-options`, `external-and-resident-shuffle` | Same-workload explicit algorithms may be compared for cost, not seeded equality. Resident n=3 cells overlap; loops omit costs. External and worker matrices do not calibrate a crossover. | Keep explicit capabilities and external fallback; do not select Fisher–Yates from its loop complexity. |
| `profiling` | Full scans and instrumented attribution identify hashing/parsing costs. GPU discussion is feasibility research. Profile commands are not completed output jobs. | Retain optional serial profiling/cache; no GPU backend or mandatory profiling justified. |
| `radix`, `prefix-distribution` | Separate native/browser full-job cells; source-loop and allocation measurements are attribution only. | Recommend removal of current prototypes, retaining comparison/merge fallback. |
| `snapshot-adapters` | 162 ordinary complete adapter jobs and 54 traced jobs are distinct. First job includes conversion; replay includes source validation. Every measured CSV-adapter path loses. Python blocks omit engine framing and strict admission. | Remove CSV-bridge optimization work; this family cannot reject unmeasured direct Rust consumers. E3 decides those; dormant Parquet wiring has no live consumer to retain. |
| `spill-blocks` | Native losses and private-context browser gains remain separate; stored spill savings are not physical traffic savings. | E1 must establish a persistent-browser benefit over v1 before retention. |
| `parallel-profile`, `windows-profile` | Historical final matched scan cells and newer Windows 24 timed scans/eight censuses are separate; initial/revised sizing failures remain design evidence. | Conditional native retention; no WASI parallel implementation or full output-job gain established. |
| `parallel-groups` | Final matched-source jobs supersede stale baseline comparisons. Keep skew/tiny regressions and separate ordered-replay space censuses. | E2 rejected this adapter; removal is accepted by Astra after actual-diff and raw verification review. Historical gains and regressions remain evidence. |
| `shuffle-partition`, `windows-ingestion-fusion` | Complete exact jobs, persistent-browser follow-up and later native Windows spill/transition cells support specific shapes. Incomplete browser/trap/write probes and smoke runs cannot extend the final timed population. | Conditional retention; external transition needs shape-aware cost selection. |
| `windows-retained-parent` | Original blocked attempt has zero jobs. Unblocked old binary, current accounting build, no-sampler controls and outside-checkout shape completion have different scopes. Preserve error-5 publication failures. | Current-build external/hierarchical and corrected skew/wide evidence supports this retained-parent path, not universal Windows behavior. |
| `device-diagnostic` | Whole-disk counters have background/delayed writes and invalid collection cadence for effect inference, even when original noise gates passed. | Exclude entire pass from physical-effect claims; no subtraction or cherry-picking directions. |
| `nested-balanced`, `constant-partition` | Final exact native/persistent-browser cells support deep/repeated-key cases. Interrupted nested revision, small-parent and near-flat cases remain visible. | Conditional retention with proof from actual ranges/lineage, never samples. |
| `consecutive-partitions`, `partition-balanced`, `streaming-chain` | Final matched complete jobs support useful shapes; preserve large-browser merging and later-parent losses. Initial eager chain/counter revisions and five-repeat sensitivity rechecks do not replace primary results. | Runtime/plan guards and original-stage retry required. |
| `flexible-policy`, `partition-first`, `allocation-ranges` | Different algorithms may have distribution equivalence but no exact seeded equivalence. Final isolated/borrowed-audit passes stay separate from initial overlapped runs, eviction requests, post-publication counters and private browser timings. | Reuse policy seam, prune partition-first, conditionally retain allocation ranges for Auto after joint-distribution/plan acceptance. |
| `xof-source`, `random-buckets`, `random-quality` | Source-only loops are not jobs. Quality/replay/follow-up families keep original flags and declared thresholds; invalid skew configs and fallback controls are not quality populations. | Prune XOF/buckets; retain v1 quality controls. Finite success does not prove uniformity. |
| `ownership-and-lifecycle` | 2026-10-15–23 capacity/census/codec/JSON/lineage/request/picker/temporary/publication controls, desktop parity, termination, deployment and packaging evidence support only their pinned builds and assertions. Some accounting changes have separate timed costs elsewhere. | Keep proven ownership and lifecycle contracts. Do not infer speedups from `tests[].seconds`, command durations, heap probes, deployment or release validation. |
| `design-and-derived` | Policy design, synthesis and this review summarize underlying evidence. | No new observations, performance population or implemented selector. |

The 35 unlinked artifacts are explicitly associated in the audit rather than
silently omitted: compact-parser engine/multilevel files, early profile source
inventories, initial partition-balanced and streaming-chain cells/controls,
shuffle-partition smoke/trap/bridge diagnostics, XOF browser controls, bucket
quality/skew-invalid/smoke/window reproduction, shuffle null calibration,
duplicate allocation controls, historical follow-up and superseded request/picker
validation reports. Unlinked initial timing populations are retained as revision
and negative-control evidence, not pooled into final cells. Script snapshots and
logs are provenance/failure evidence, never independent jobs.

## Later Windows cells, kept separate

These existing summaries provide the later effects used in the inventory. Each
row is three observations per side: median (observed minimum?maximum) seconds,
not confidence intervals. A?C are complete retained-parent jobs; D is a complete
profile command, not an output job. All are warm/uncontrolled NTFS/NVMe. This is
an audit rendering of existing summaries, not additional observations. Negative
change means `100 * (candidate median / baseline median - 1)` is lower/faster.
The summaries retain source SHA-256 and `measurement_lines`; the coverage audit
also hashes each summary itself. JSON pointers below locate exact cells.

A: [retained-current-calibration-2026-10-21-summary.json](evidence-originals.md#sha256-2a099109d0cac9237481875cfee5534a97da194726d906750d150839336a7377 "Original: docs/benchmarks/retained-current-calibration-2026-10-21-summary.json").

B: [retained-targetssd-outside-checkout-2026-10-21-summary.json](evidence-originals.md#sha256-fb079666bb9a2760105c192ffcccc001aaa293984da56d86d0a3894960144190 "Original: docs/benchmarks/retained-targetssd-outside-checkout-2026-10-21-summary.json").

C: [retained-current-calibration-transition-2026-10-21-summary.json](evidence-originals.md#sha256-d390e2fd8b8922b351bce4ff4c4c5e2e6ae57f445610bae232060cbac8d5e77e "Original: docs/benchmarks/retained-current-calibration-transition-2026-10-21-summary.json").

D: [parallel-profile-windows-current-2026-10-21-summary.json](evidence-originals.md#sha256-eadc07cd8993749aaa52ec7079e6f6613b882823eaf18d11483709b3022e5a8b "Original: docs/benchmarks/parallel-profile-windows-current-2026-10-21-summary.json").

| Summary / pointer / cell | Baseline seconds | Candidate seconds | Change |
| --- | ---: | ---: | ---: |
| A `/cells/0` resident | 0.0780 (0.0752?0.2551) | 0.0631 (0.0621?0.2240) | -19.1% |
| A `/cells/1` external | 1.6544 (1.5879?1.7010) | 1.2809 (1.2255?1.3138) | -22.6% |
| A `/cells/2` hierarchical | 8.3505 (8.0411?9.5324) | 6.3748 (6.2001?6.6081) | -23.7% |
| B `/cells/0` skew | 1.6355 (1.6342?1.6846) | 1.2745 (1.2604?1.2856) | -22.1% |
| B `/cells/1` rare_wide | 1.7457 (1.7409?1.7678) | 1.2921 (1.2840?1.2983) | -26.0% |
| C `/cells/0` transition_17000 | 0.1348 (0.1319?0.1671) | 0.1361 (0.1314?0.1719) | +1.0% |
| D `/cells/0` many/1 | 0.6244 (0.6243?0.7799) | 0.6380 (0.6146?0.7828) | +2.2% |
| D `/cells/1` many/4 | 0.6270 (0.6178?0.6276) | 0.2907 (0.2869?0.2973) | -53.6% |
| D `/cells/2` rare_wide/1 | 0.0683 (0.0670?0.0719) | 0.0686 (0.0679?0.0705) | +0.5% |
| D `/cells/3` rare_wide/4 | 0.0682 (0.0672?0.0688) | 0.0705 (0.0685?0.0783) | +3.4% |

A resident timings overlap widely. C preserves a near-flat/slower transition
control where fusion spills while original execution remains resident; its
no-sampler storage scope is final size, not a live peak. B completes corrected
skew/rare-wide shapes outside the checkout on the same volume; it does not erase
checkout-local publication failures or identify their cause. D's one-worker
controls stay serial and its rare-wide/four-worker case loses despite the
many-column win. Original blocked runs, earlier build replays, failed cells and
whole-device diagnostics remain distinct in the family ledger.

## Live strategy inventory

This inventory records the pre-removal review, including its original feature
count and controls. The implementation status above and current manifests own
present availability; removed names below are historical decision evidence.

Paths below are relative to `crates/chopper/src/` unless linked otherwise.
**N/W** means executable native and single-threaded WASI paths; it does not assert
fresh validation of every OS/device. Features are in
[native](../crates/chopper/Cargo.toml) and
[browser](../crates/chopper-browser/Cargo.toml) manifests. There are 18 native
experimental feature declarations, including the dormant Parquet gate; the
test-only `resource-contract-tests` is an acceptance mechanism, not a strategy.
JSON names are defined in [portable config](../crates/chopper-core/src/config.rs).
`--features` selects a build; most rewrites have no runtime public switch. They
activate only on their selector's eligible pipeline in that build. No experimental
feature is enabled in the ordinary production build.

Unless noted, baseline and exact rewrite paths preserve `seeded_v1` order and
membership across budgets/workers/platforms for the recorded version. Their
fallback is original-stage execution and canonical comparison/external sorting;
fallback is allowed only before emission, and cancellation, cleanup failure and
emission failure remain terminal. Distribution rewrites below instead use the
explicit flexible snapshot contract. All paths remain subject to CSV caps,
group/file/temp limits, local/shared admission and publication cleanup.

| Strategy / implementation | Controls, runtime and semantics/dependencies | Disposition and evidence/resource limits |
| --- | --- | --- |
| Direct compact ingestion, owned decode adapters, parser/decode reuse; `engine.rs`, `engine/records.rs`, core `csv.rs`, `storage/adaptive.rs` | Default N/W, selected by source/consumer; packed fields avoid repeated per-field allocation. Owned codecs/readers remain necessary. | **Keep**; compact families support complete-job improvements. Retained wide capacities and conversion overlap need grants; zero-copy is not a universal claim. |
| No-op/limits-only serialization to retained encoded plan; `engine.rs`, `output.rs` | Default N/W for eligible terminal paths; serialize once, enforce actual encoded caps. Current execution still copies/compresses the prepared snapshot. | **Keep** as exact-preview path and direct-execution building block. Early pipeline bundle gains cannot isolate snapshot cost. Direct-to-destination execution is future work. |
| Balanced frame-boundary scans/shared dataset ranges; `engine.rs`, `storage.rs` | `balanced`, `--files`; N/W. Consecutive membership and per-parent remainder rounding. Terminal paths consume rows; intermediate ranges share storage. | **Keep**, distinct exact capability and reduced scanning/materialization. Retain insufficient-row errors and lineage charges. |
| Interleaving; `engine/streaming.rs` | `interleaved`, `--interleaved`, app option; N/W. Round-robin exact balance, different membership from consecutive split. | **Keep** for capability; options pass is slower than consecutive, not a speed substitute. Per-destination state/temp files still bounded. |
| Value grouping: resident, bounded routing, forced sorting and routing-to-run reuse; `storage/adaptive.rs`, `storage.rs` | `resources.grouping: auto|sort`, `--grouping`, UI; N/W. Encounter order preserved; late keys/reordering can force one-way fallback without rereading source. | **Keep all four paths**. Adaptive late-key regression and high-cardinality need forced sort; routing is useful for low cardinality. Writers multiply buffers/files; already-ordered runs must not be sorted again. |
| Exact assignment, stratified or unstratified; `engine/assignment.rs`, `engine.rs` | `assign`, `--groups`, strata/app; N/W. Decimal largest-remainder quotas and original-order output; sort/counter/scratch admission. | **Keep**, required exact semantics. Never silently replace with probabilistic allocation; exact counters/sorts are required fallback for ineligible chains/ranges. |
| Probabilistic assignment; `engine/streaming.rs`, core random/allocation contracts | `assign_probabilistic`, `--probabilistic`, app; N/W. Seeded independent draws, approximate counts, including empty/small strata. | **Keep**, agreed distinct capability. Historic options medians 0.180→0.154 s and stratified 0.466→0.152 s establish potential, not reliable advice. E4 resolves recommendation evidence; no universal deviation bound. |
| Canonical resident comparison sort, bounded external runs/hierarchical merge and streamed final merge; `storage.rs` | Default N/W uniform/auto under seeded policy; native workers parallelize resident sorting. Random-key collision refinement remains canonical. | **Keep every level**; reproducible algorithm and fallback for oversized groups, routing and experimental denial. Resident kernels alone do not determine whole-job fit; multiple merge readers/heads and run catalogs have concurrent costs. |
| Explicit Fisher–Yates v1; `storage/adaptive.rs::ResidentShuffle`, core random | `strategy: fisher_yates`, CLI/app; N/W. Own deterministic permutation, retained rows capped at quarter-job budget; explicit request fails rather than switching algorithms. | **Keep** as explicit algorithm and possible Auto resident choice. Cells `resident-native/browser` +4.5%/+3.7% global; grouped native sometimes wins. No calibrated crossover or universal win; seed equality only within algorithm. |
| Repeated-uniform elimination, partition→uniform, assign→uniform, uniform→balanced; selectors in `engine.rs`, keys/domain/assignment modules | Default N/W seeded exact fusions, no standalone flag. Preserve original indices, assignment draws, parent domains, split order and logical stages. | **Keep each fusion**; original-stage path remains necessary for barriers, explicit Fisher–Yates and other policies. Early bundle/compact evidence supports pass elimination without attributing all gains individually. |
| Approximate buffer shuffle, ingestion and direct terminal fusion; `storage/adaptive.rs::BufferShuffle`, `engine.rs` | `buffer`, `buffer_rows`, `--buffer-rows`, app; N/W. Buffer size forms part of seeded mixing contract; not a uniform permutation. | **Remove (fixed)**. Historical buffer gains do not reopen decision. Detailed removal surface below. |
| Optional serial full-file profile and advisory cache; `profile.rs`, `profile/records.rs`, server/browser session | `profile`, API/UI Analyze input; N/W. Full scan, bounded exact sets/HLL; no output snapshot. Unix/Windows cache eligibility differs; browser cache limited to session. | **Keep**; capability independent of output execution. Avoid compulsory profile+prepare double work in future Run. Cache does not validate prepared outputs. |
| Native sort/compression workers, serial parse/merge/assembly; `storage.rs`, `output.rs`, resources | `workers`/`--workers`, app; N plus W serial. Sort and independent chunk compression parallelize; ordered output and ZIP assembly remain serial. | **Keep serial and bounded parallel**; codecs, chunk descriptors/temp batches multiply live owners. Existing worker matrix/early compression results are workload-specific, not an automatic sizing rule. |
| Plain/gzip/Zstandard/ZIP publication and signature-selected input adapters; `output/`, `engine/input_*`, pinned vendor | Compression/member/CSV options; N/W. Distinct user formats, uncompressed strict caps, ZIP directory streaming; native atomic publish versus browser marker/export. | **Keep every supported format and serial fallback**. Codec admission evidence is correctness, not speed comparison. Snapshot compression/GPU backends are absent proposals, not removable live strategies. |
| Shared admission and Linux pressure checks; `resources/`, `storage/adaptive.rs` | Job resources and native `CHOPPER_MEMORY_LIMIT_MB`; N/W ledger per engine, Linux discovery/rechecks, conservative other-platform fallback. | **Keep** for correctness. `shared-admission` +0.4%, `pressure-recheck` +3.9% examples are costs. Reservations are not RSS; no cross-worker/tab memory coordination claim. |
| Radix index sorter; `storage/radix.rs` | `experimental-radix`; N/W; eligible random-key buffers, comparison fallback on unsupported/admission path; exact comparator. | **Remove recommendation**. Resident native +28%/+44%; spill gains small, browser gains limited/overlapping. Index passes/scratch/indirection add complexity; no distinct capability. Keep comparison implementation. |
| Prefix external distribution; `storage/distribution.rs` | `experimental-distribution`; N/W implementation, primary measured native. Random groups only, four-bit prefixes, bounded recursion/passes, merge fallback; same seeded order. | **Remove recommendation**. Native 18–67% slower across 18 cells; repeated decoding/materialization, more files/traffic. Cannot remove underlying merge/collision machinery. |
| Compact spill transcoding adapter; `storage/spill_blocks.rs` | `experimental-spill-blocks`; N/W changes physical spill framing, exact logical output; v1 remains baseline. | **Resolve E1**. `spill-native` +23.3%, multilevel losses up to 46%; private-browser `spill-browser` −19.6%; stored spills −21–39%. CPU/transcoding and actual persistent storage benefit decide. |
| Bounded hash batches for profiles; `profile.rs`, `profile/parallel_tests.rs` | `experimental-parallel-profile` plus workers>1; native only; WASI stays serial despite feature forwarding. First-wide/tiny/admission cases use serial. | **Conditionally keep** native hash-heavy scans; `profile-columns` −46%, rare-wide +1.9%; Windows many-column −53.6%, more CPU/reservations. No need to benchmark merely to retain; cost rule must reject known controls. |
| Independent parent batching/ordered temporary replay (removed) | `experimental-parallel-groups` is invalid in native/browser Cargo. Ordinary sort/compression workers and serial parent stages survive. | **E2 rejected by Astra; removal accepted after actual-diff and raw verification review.** Current CLI balanced −12.68%, skew +36.86%, small +354.45%; separate retained-owner population +24.78%, n=3 per side/cell. No pooling or feasible validated headroom/width guard. [Decision](performance.md#independent-parent-batching-removal-2026-10-25). |
| Exact shuffle→partition, ingestion/retained variants; `engine/shuffle_partition.rs` and contracts | `experimental-shuffle-partition`; N/W seeded auto/uniform adjacency only. Original shuffle domain, typed retained-parent preparation denial can retry before emission; raw ingestion lacks retained replay boundary. | **Conditionally keep**; `shuffle-native/browser` −32%/−28%, current Windows retained external/hierarchical −22.6%/−23.7%, outside corrected skew/wide −22.1%/−26.0%. Near-flat transition and higher downstream temp peaks prevent blanket selection. Audit itself consumes capacity. |
| Nested balanced ranges; `engine/nested_balanced.rs` | `experimental-nested-balanced`; N/W, shared frame/decode traversal preserving each nested remainder, no flattening. | **Conditionally keep** deep chains; `nested-native/browser` −28.5%/−27.9%; tiny/parent cases mixed. Logical reads 420.5→104.9 MB, temp roughly unchanged. |
| Proven constant partition reduction; `engine/constant_partition.rs` | `experimental-constant-partition`; N/W, prior actual lineage proves columns constant; share data/copy or group only varying keys. | **Conditionally keep**; `constant-native/browser` −25.8%/−22.9%, small repeat +5.7%, some browser controls flat. Allocation traffic falls greatly, charged peak unchanged; optional sampling cannot prove constants. |
| Adjacent value partitions; `engine/consecutive_partitions.rs` | `experimental-consecutive-partitions`; N/W exact nested tuple order, stages and domains; bounded tentative attempt/original graph fallback. | **Conditionally keep** native, browser only behind plan guard. `consecutive-native` −30.2%; large browser +62.6% when fused sort replaces routed baseline with 71 runs/two merges. |
| Partition→uniform→balanced; `engine/partition_balanced.rs` | `experimental-partition-balanced`; N/W bounded tuple counter; counter/typed tentative denial falls back, preserve quotas and domains. | **Conditionally keep** terminal paths; native/browser multilevel −14.5%/−19.3%, later-parent/downstream losses up to 20.3%. Smaller writes do not imply smaller live allocation peak. |
| Membership→partition→membership; `engine/streaming_chain.rs` | `experimental-streaming-chain`; N/W endpoints probabilistic or interleaved only; original per-scope encounter draws/counters and empty groups. Catalog/composite-key denial replays original graph. | **Conditionally keep** routed chains. Native probability/interleaved −48.1%/−33.7%; browser probability −55.9%, interleaved +14.1% at merge transition. Live peaks rise despite fewer writes. |
| Flexible planner with resident attempt/random-key fallback, audit/snapshot; `engine/flexible.rs` | `experimental-flexible`, JSON `full_shuffle_policy: flexible_v1`; N/W. Ordered logical stages, per-parent actual algorithms; prepared-snapshot replay, seed alone insufficient. | **Conditionally keep seam, replace selector design**. `flexible-policy` +28.6% vs seeded resident. Future Auto must avoid redundant stages/audit/snapshot costs, while preserving explicit prepared execution. Do not promote this implementation by renaming it. |
| Flexible partition-first independent child shuffle; `engine/flexible/partition_first.rs` | `experimental-flexible-partition` requires flexible and auto shuffle; N/W. Joint partition subsequence distribution under ideal independent permutations; different domains/seed order. Child uses resident/merge fallback. | **Remove recommendation**. `partition-first-sequential` −17.3%, but `partition-first-exact` +16.4%; skew/high-fanout/wide regressions, larger external temp. Exact shuffle/partition already provides useful capability. Browser private gains lack exact-fusion comparison; no established unique workload benefit justifies retention. |
| Buffered BLAKE3 XOF source; core `fast_random.rs`, `engine/flexible/source.rs` | `experimental-fast-rng` implies flexible/core feature; `full_shuffle_rng: blake3_xof_v1`, `shuffle_rng_buffer_bytes: 64|256|1024`; N/W versioned distinct source. | **Remove recommendation**. Seven-repeat `xof-flexible` −14.1% vs flexible counter but `xof-seeded` +6.1%; sparse grouped regression, live peak unchanged. Source-only gains do not justify new replay/cache machinery. Retain counter v1 and its domains. |
| Flexible exact-allocation ranges; `engine/flexible/allocation_ranges.rs` | `experimental-flexible-allocation`, flexible adjacent full shuffle→unstratified exact allocation; N/W. Joint quota membership/within-child permutation, named zeros; original sequential fallback for ineligible requests. | **Conditionally keep** for Auto capability; `ranges-uniform/external` −26.5%/−15.7%, many parents +2.4%, +1.2% vs existing assign→shuffle on rare-wide (different requested order). Temp may exceed original seeded plan; private-browser gain is not against seeded baseline. Keep proof/constraints; never claim exact-v1 equivalence. |
| Independent random buckets/resident leaf permutation; `engine/flexible/buckets.rs` | `experimental-random-buckets`, flexible `full_shuffle_algorithm: independent_buckets_v1`; N/W, bounded skew/depth/pass fallback to random keys, distinct plan/domain. | **Remove recommendation**. `buckets-native` +34.8% vs seeded, +3.5% vs flexible merge; persistent browser 20.343 vs 19.395 s seeded control with noninterleaved original control. More seeded traffic; original quality flags remain. |
| Direct compact rows and Arrow IPC snapshots; `engine/snapshots.rs`, `snapshots/rows.rs`, `snapshots/ipc.rs` | `experimental-input-snapshots`; explicit Rust library API, source/artifact/settings hashes and bounded manifest/batches; no CLI/UI auto cache. N/W code, direct end-to-end timing not established by CSV-adapter family. | **Removed after separate E3 rejections (2026-10-26)**. Historical scope: separate compact and IPC decisions; source validation/conversion, upstream metadata, overlap and retained disk cost must count. No benefit may be inferred from smaller Python snapshots. |
| Dormant Parquet feature/dependency; native/browser manifests | `experimental-parquet-input` forwards snapshots/Arrow and an optional Parquet dependency. Source search finds no Rust Parquet consumer, public request or executable decoder. Python adapter experiment is separate. | **Remove recommendation** for unused feature/dependency wiring; preserve research. A new direct input capability would require a product use case and bounded schema/ownership design, not promotion of existing code. |

## Decision-changing experiments, not a new matrix

These are designs only. Execution belongs to the bounded calibration tasks in
TODO, after the first removal slice. Each pass pins source/features/binary/WASM,
harness and fixtures, alternates complete baseline/candidate jobs, retains
failures and reports n/median/min/max. Start with three pairs per selected cell;
overlap means unresolved, never a tail claim. A follow-up needs a named decision.
Stop immediately on correctness, cap, admission, cleanup or replay failure. Do
not run the historical matrix as a prerequisite.

| ID / decision | Smallest useful comparison and controls | Stop/outcome rule |
| --- | --- | --- |
| E1: keep compact spills for hosted storage? | Feature-off v1 vs blocks in a persistent Chromium profile: one many-column external winning shape and one multilevel/rare-wide negative control, fixed WASM/resources/export. Time through export; record stored bytes, logical traffic, simultaneous sampled space and available reservations/CPU separately. | Keep only as runtime-specific path if repeated complete jobs benefit without unsafe growth and controls support a feasible guard. Otherwise remove adapter and feature in both manifests. Native losses already rule out unconditional native use. Do not require physical-I/O attribution to choose elapsed-time behavior. |
| E2 resolved: parent batching/replay removal accepted by Astra | Matched current native sources, one balanced many-column independent-parent shape plus 90:9:1 skew and small-parent controls. Feature-off already uses normal sort/compression workers; same budgets/workers. Include CPU, concurrent reservations/RSS, replay writes/space and denial-to-serial cost. | Retain narrowly only if useful total-job benefit survives realistic shared admission and its resource cost, with a feasible guard separating controls. If the marginal gain disappears or guard cost consumes it, remove parent batching, keep normal workers/serial original stages. No WASI parallel study. |
| E3 resolved: compact and IPC separately rejected by Astra | One native many-column repeated-input job, plus a rare-wide/one-job negative control. Direct CSV vs actual direct Rust compact/IPC consumers; separate first conversion and validated replay totals for a declared repeat count. Use existing snapshot APIs/harness building blocks; no CSV bridge. | Close ownership/metadata/corruption/source-change/denial/cancellation bounds before timing admission. Retain each integration only for a demonstrated complete-workload gain or an explicitly requested interoperability capability. If none wins, remove live integrations/optional Arrow dependencies, preserve research/harness needed to explain evidence. Do not expand typed support or invent users to save an experiment. |
| E4: advice for explicit probabilistic allocation | Existing exact vs probabilistic complete-job harness, unstratified and stratified; small strata, 50/50 and rare-percentage groups, skew and a larger case. Record every count/deviation/empty destination across a small fixed seed panel; seed repetitions remain nested under shape, not independent workloads. Separate optional profile cost and actual prepare/publication cost. | Retain option regardless (agreed). Allow app advice only where savings and count variation can be assessed and explained; otherwise advanced option only. No auto substitution and no invented universal acceptable deviation/time threshold. |
| E5: safe selector boundaries for retained exact fusions | Start from current Windows retained-parent cells/negative transition and persistent-browser regressions; add only a missing plan/pressure boundary for the specific rule. Compare proposed total Auto cost including observations/failed attempts against simple original stages. Reserve separate held-out shape/late-wide/no-benefit/admission-denial controls. | Accept rule only if it avoids the known routing-to-merge losses and pays its observation cost. Otherwise leave that runtime/shape on original execution. Universal row-count thresholds and device learning remain unsupported. This resolves selection, not whether to keep already-useful exact capability. |

E1's [persistent hosted round](performance.md#persistent-hosted-spill-block-e1-comparison-2026-10-24)
now records the two selected 100000-row cells and twelve timed jobs. The rare-wide
cell is a risk control, not a historical browser loser. Columns regressed and
rare-wide ranges overlap. Astra reviewed the round as **unresolved**: overlapping
or inconclusive results remain unresolved under the agreed decision rule. The
earlier private-context many-column win did not survive this persistent comparison;
rare-wide loses two of three matched pairs despite its slightly lower median.
Stored blocks and sampled logical space shrink, with small reservation deltas,
but no useful elapsed-time win or feasible runtime/shape guard is established.
This bounded run earns neither retention nor removal; keep the feature opt-in
unchanged and E1 unchecked as the next unfinished retention item. No numeric
selector, final product selection implementation or automatic expansion follows.
The remaining decision-changing question is whether rare-wide complete-job benefit
is repeatable and materially exceeds observed run variation and measurement
overhead enough to justify a feasible runtime/shape guard. Answering requires a
separately bounded approved follow-up; no more runs are authorized now.

E2 is rejected by Astra: cheap row/group/worker checks cannot bound decoded width
or reserve shared headroom through sibling materialization. No feasible validated
guard is established. The CLI balanced gain remains a fact; rejection does not
claim parallel groups never win. The separate retained-owner population cannot
be pooled with CLI observations. See the [removal decision](performance.md#independent-parent-batching-removal-2026-10-25).
E1 remains unresolved and opt-in. E3 separately rejects compact and IPC; see the
[decision and removal](performance.md#direct-input-snapshot-rejection-and-removal-2026-10-26).

E3 tested actual direct consumers, separately rejecting compact and IPC after
first-job and complete-workload losses; this is independent of old CSV-bridge
losses. Repeated isolated ranges overlap or are mixed; no break-even extrapolation
or universal format claim follows. No interoperability requirement was requested. There is no analogous concrete missing bottleneck justifying
another radix/XOF/bucket/prefix matrix. New evidence can reopen a pruned algorithm
under the existing [reopening criteria](performance-opportunities.md#removed-from-the-active-queue),
but its current executable implementation need not remain to preserve that option.

## Buffer-shuffle removal surface and first slice

The first recommended implementation slice is complete buffer-shuffle removal,
including public rejection and focused native/hosted acceptance. It should not
also change Auto defaults, mandatory preparation, memory sizing or other RNGs.
The decision is independent of E1–E5.

* Schema: remove `Shuffle::Buffer`, `Operation::Shuffle.buffer_rows` and its
  default/validation in core config; remove construction arguments everywhere,
  including synthetic shuffle operations in exact rewrites. Audit typed Job
  default/capacity and Column/schema assumptions; old `strategy: buffer` and
  `buffer_rows` must fail clearly under strict decoding, including native CLI
  and WASI requests. Preserve `uniform`, `auto` and `fisher_yates` requests.
* Execution: remove `BufferShuffle` from `storage/adaptive.rs` and its re-export;
  remove initial-buffer detection, push/drain, `emit_buffer_row` and direct/fused
  buffer branches in `engine.rs`, ordinary group dispatch and flexible handling.
  Preserve shared packed rows, reservations, row sinks and cancellation checks.
* Controls and generated output: remove CLI `buffer` and `--buffer-rows`; remove
  UI selector/fields, planner descriptions and TypeScript model/request fields.
  Search `ui/src`, `ui/tests`, examples and core/integration tests. Regenerate
  the hosted production distribution; native CLI builds do not embed UI assets.
* Diagnostics/acceptance: remove buffer-specific counters and text in storage,
  engine diagnostics, app rendering and normalizers. Remove dedicated tests but
  retain generic shuffle lineage/admission/cancellation controls for surviving
  algorithms. Flexible eligibility/proof tests currently list buffer exclusions;
  adapt them to rejected public requests or other surviving barriers.
* Harness/docs: `benchmark-compact.py` buffer scenarios and buffer cases in
  adaptive/engine/streaming/group/flexible/partition harnesses need review. Keep
  scripts/snapshots required to interpret historical results, explicitly marked
  historical where necessary. Update README operations/resources, specification,
  active rewrite guidance and examples. Historical dated notes and raw artifacts
  keep their original buffer descriptions/hashes.

Acceptance: old buffer configurations/flags fail with a useful unsupported-option
or schema error; surviving CLI/native app/hosted requests retain fields, membership,
seed order, caps, analysis and cleanup. No executable buffer branch or active
support claim remains. Review searches for `BufferShuffle`, `Shuffle::Buffer`,
`buffer_rows`, `buffer-rows`, `fused_buffer_shuffle` and buffer-shuffle text,
explicitly allowlisting historical evidence rather than deleting ordinary I/O
buffers. Run the Rust/core WASM and UI checks required by AGENTS, plus hosted
production/bridge/resource-contract and relevant interruption acceptance from
browser.md; verify test-free packaging and regenerated bundle. Regenerate/check
catalog only after relevant evidence links change. Preserve uncommitted files.

## Maintainability findings and bounded cleanup

The [architecture entry point](architecture.md) added in this phase lets a reader
follow a job without traversing dated research. Remaining findings are concrete
cleanup targets, ordered in TODO; they do not justify a broad refactor now.

| Problem and inspected surface | Recommended boundary / acceptance |
| --- | --- |
| Navigation: docs/README ends with a dense chronological validation paragraph; `performance.md` is over 11,000 lines mixing strategy evidence, request ownership, release acceptance and history. AGENTS also repeats many per-owner instructions. | Keep current entry points short and link owning contracts/report/catalog. Later separate current guidance from dated research with stable redirect/anchor mapping and raw hashes; do not casually move evidence or rewrite history. Current README claims stay until behavior changes. |
| Missing contribution and license entry points: no root CONTRIBUTING or project LICENSE, while workspace packages declare MIT. Vendor licenses are present but do not license the project. | Add contribution guide routing to existing commands/architecture, with native/hosted/generated-output distinctions. Ask owner to confirm copyright/license text before adding a project license; record mismatch without inventing policy. This does not block strategy cleanup. |
| Engine dispatch couples ingestion fusion, later dataset planning and operation application; `engine.rs` repeats eligibility/key/domain decisions across these paths. `storage.rs` couples context/accounting, temp ownership, sorter and merge implementation. | Prune rejected branches first. Then extract a shared exact-plan proposal carrying original logical indices/domains and explicit before-emission ownership/fallback boundary. Keep sinks/execution separate from selection; test parity and denial, not file-size targets. Avoid merging native publication with browser marker/export. |
| Survivor ownership modules (`header`, `preview`, `stages`, text, warnings, timings, diagnostics) encode similar shared-payload patterns with different admission bounds/release obligations. JSON preflight also spans storage, native requests and responses. | Keep per-schema bounds local. Consolidate only identical ownership/lifetime mechanics during touched survivor work; preserve last-clone release, private unique construction, lock-release-before-reserve and strict error behavior. Similar names alone do not justify a generic allocator abstraction. |
| Strategy/feature declarations repeated in core enums, native/browser manifests, WASI build forwarding, flexible audit features and acceptance matrices. Removal can leave accepted options with no executor. | Add focused consistency checks after pruning: declared feature forwarding and rejected obsolete requests. Keep production/test reactor separation explicit. Inventory all feature combinations actually supported; do not promise all-feature execution merely because compilation passes. |
| Benchmark harnesses repeat fixture generation, normalization and verification; Windows already shares helpers with profile/device harnesses, while scripts preserve historical schemas and pinned snapshots. | Reuse catalog/export and existing Windows helpers. Extract another common fixture/verifier only when two surviving harnesses need the same contract. Keep historical harness identities immutable; census and timing APIs must remain separate. |
| Workflow: root CI checks default native/core/UI and browser plus shuffle/partition reactor, but optional feature validation and catalog/synthesis audits are mostly separate manual commands. WASI SDK/Chromium and production rebuild requirements are scattered. | Add a concise check-routing entry point/CONTRIBUTING and one documented evidence-only check command group. Later add bounded CI checks for surviving optional feature combinations and generated audits. Do not add an expensive matrix or call dirty-checkout commit identity sufficient provenance. |
| Release paths: committed native bundle and hosted output differ; resource-test builds can contaminate deployable assets without the final hosted rebuild. Toolchain wrappers and platform-specific validation failures are easy to misread. | Keep authoritative build commands in manifests/browser guide, link them from contribution docs; retain packaging guard and explicit blocked-vs-passed reporting. Do not turn the one-off outside-checkout publication workaround or Application Control history into a universal convention. |
| Evidence volume: 638 artifacts and source/probe snapshots create navigation friction, but no measured clone/development cost supports moving them out of repo. | Keep research/raw evidence here. Use generated navigation and family audit; measure repository-size friction only if it becomes a real development problem. No archive relocation/history rewrite in this phase. |

Supported conclusions are the matched effects and distinct capabilities cited
above, documented regressions and existing executable ownership/replay controls.
Hypotheses are prospective shape/cost guards, cheaper direct execution, automatic
resource sizing, direct snapshot gains and probabilistic recommendation quality.
The existing stage/parent design must be reconciled with the new brief before
implementation: optional observations, admission feasibility, total cost, safe
fallback, direct-vs-prepared execution and reproducibility are separate decisions.
No unresolved product choice blocks the first slice. License wording is a later
owner decision; numerical policy thresholds require evidence, not another interview.
