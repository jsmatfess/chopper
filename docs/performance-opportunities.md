# Performance decisions and experiment criteria

Updated 2026-10-20. The [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns open work. This document explains priorities and stop/reopen criteria. [Benchmark guide](benchmarks/README.md) defines how to compare results; the [index](benchmarks/INDEX.md) locates experiments, scripts and raw artifacts.

## Already delivered

The [2026-10-23 agreed direction](maintainer/auto-mode-and-maintainability.md) adds a full
strategy-retention review, future default auto execution and complete buffer-shuffle
removal. It supersedes blanket retention of experimental implementations below;
historical measurements and stop/reopen criteria remain evidence inputs. Current
defaults remain unchanged until implementation and validation.

[Completed checklist entries](history/completed-work-2026-10-20.md) preserve the implemented work and evidence links. [Performance](performance.md) records individual experiments, including rejected/revised candidates. Surviving opt-in implementations remain available; buffer shuffle, radix sorting, prefix distribution, independent random buckets, buffered XOF, partition-first, dormant Parquet wiring independent-parent batching/replay and the separately rejected E3 direct compact/IPC input integrations have been removed. Evaluation is complete even when promotion is unjustified. Historical research estimates are hypotheses, not measured gains.

## Decisions worth resolving

| Decision | Evidence to start with | What could justify further work |
| --- | --- | --- |
| Which exact pipeline fusions should run on which workloads/runtimes? | [Shuffle/partition](performance.md#exact-shufflepartition-prototype-evaluation-2026-10-16), [nested balanced](performance.md#nested-balanced-range-fusion-2026-10-17), [constant keys](performance.md#proven-constant-partition-keys-2026-10-17), [consecutive partitions](performance.md#consecutive-value-partition-fusion-2026-10-17), [partition/balanced](performance.md#partition-shuffle-balanced-fusion-2026-10-18), [streaming chains](performance.md#streaming-membership-partition-chains-2026-10-18) | A selector that separates measured winning cases from browser, fanout and small-parent regressions, with transactional fallback. |
| When do parallel profiles pay for their resource costs? | [Profiling batches](performance.md#bounded-parallel-profiling-evaluation-2026-10-16) | Matched evidence around shape/skew/size thresholds and concurrent admission; retain serial fallback. Independent-parent group batching was [rejected and removed](performance.md#independent-parent-batching-removal-2026-10-25); historical group gains remain valid. |
| Which working sets fit, and when is external execution preferable? | [Resident comparison](performance.md#resident-full-shuffle-comparison-2026-10-15), [reservations](performance.md#per-group-reservation-accounting-2026-10-15), [shared admission](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16), [adaptive roadmap](adaptive-execution.md) | Complete live-capacity observations and targeted SSD/browser calibration supporting a bounded per-parent policy. Accounting itself is resource correctness, not a claimed throughput gain. |
| Where does flexible exact-allocation fusion beat its extra policy/materialization costs? | [Allocation ranges](performance.md#flexible-shuffle-and-exact-allocation-ranges-2026-10-19), [policy overhead](performance.md#explicit-flexible-full-shuffle-policy-2026-10-18) | Complete-job gains including publication and space peaks, under the explicit flexible replay contract. Many-parent and rare-wide regressions must remain visible. |
| Is compact spill storage worthwhile for a specific runtime? | [Spill blocks](performance.md#compact-external-spill-block-evaluation-2026-10-16) | Controlled storage evidence that justifies runtime-specific selection: stored spills shrink 21–39%, while tested native jobs cost 10–46% and browser medians improve 2–23%. |

The [workload/runtime synthesis](performance-decisions.md) identifies promising exact fusions, runtime-specific regressions and resource costs from matched historical cells. Use it to select the next target-SSD calibration. New benchmark cells should answer a named decision or falsify a proposed selector; do not rerun the whole historical matrix by default. SSDs are the target storage; slow-storage tuning remains outside the priority.

## Removed from the active queue

Buffer shuffle is removed from the engine; historical tuning and negative-control
results do not create a reopening criterion.

The dated decisions below remove pending work, not evidence. The subsequent strategy review also authorizes implementation pruning; see the linked validation records for completed slices.

| Item | Reason | Reopen only if |
| --- | --- | --- |
| Repeat parsed-snapshot comparisons through a CSV adapter | The [162-job prototype](performance.md#text-snapshot-and-compact-block-prototype-evaluation-2026-10-16) already compares compact blocks, IPC/Feather and Parquet, including first/repeated jobs; every measured adapter path regresses against direct CSV. | A direct bounded consumer or real repeated-input workload can avoid the measured adapter costs. See the historical [adapter design](maintainer/research/columnar-input-followup.md). |
| Parquet support as a throughput optimization | Existing-dataset interoperability is a feature decision; no complete-job gain is established for Chopper's whole-row CSV workloads. | A concrete input-support requirement or profile justifies direct decoding. Preserve exact field text; conversion cannot silently infer types. |
| More radix, Fisher–Yates permutation machinery, RNG or bucket variants without a bottleneck | [Radix](performance.md#radix-sort-experiment-2026-10-13), [resident algorithms](performance.md#resident-full-shuffle-native-and-wasi-comparison-2026-10-15), [XOF](performance.md#versioned-buffered-blake3-shuffle-source-2026-10-18) and [buckets](performance.md#independent-random-bucket-full-shuffle-experiment-2026-10-19) show regressions or inconsistent whole-job gains. The [profile](performance.md#whole-job-profiling-2026-10-13) puts sorting at only 1–2% on its many-column spill fixtures. | A target workload profile attributes material cost to the proposed change and a complete-job experiment can test it. These results do not imply no workload can benefit. |
| Spill compression or GPU | Compression adds CPU/decoder memory without controlled storage evidence; [GPU feasibility](performance.md#gpu-assessment) does not justify a backend; full permutations remain the priority over approximate mixing. | A measured bottleneck and relevant workload justify the added complexity. |
| Unconditional billion-row/terabyte sweeps | Expensive repetition across every build/runtime does not by itself resolve an architectural decision. The [billion-row shuffle point](performance.md#billion-row-native-full-shuffle-acceptance-point-2026-10-16) is preserved with its build/shape limits. | A release scale claim, capacity boundary or candidate regression requires that size and sufficient storage is available. |
| Separate overlapping acceptance/accounting checklists | One active list reduces duplicated work and conflicting status. | Add a missing acceptance criterion to the owning GitHub issue rather than creating another matrix. |

## Resource planning and concurrency

Remaining allocation lifetimes and browser worker/tab coordination are correctness work, retained in [GitHub Issues](https://github.com/jsmatfess/chopper/issues). The [adaptive execution roadmap](adaptive-execution.md) supplies design context, and [resource-policy research](resource-policy-research.md) records platform constraints. Shared Linux admission and dynamic rechecks already exist; remaining coverage and predictive grants must not be described as fully delivered or as an RSS cap.

## Deferred product decisions

Resumability, entity-coherent assignment, sampled previews, Parquet interoperability, trusted physical-line splitting and earlier destination staging remain separate product decisions. The [behavior specification](specification.md) is the baseline. Existing flexible-policy experiments do not authorize arbitrary positional/assignment rewrites; see [rewrite eligibility](pipeline-rewrites.md). Research documents retain proposed designs for reference and do not create active tasks.

## Acceptance for experiments

1. State the architectural decision, candidate, baseline, eligible workload and stop criterion before adding runs. Find existing cells in the [catalog](benchmarks/INDEX.md) first.
2. Pin native/WASI binaries, build features, harness and fixture identities. Record runtime, workers, memory budget, seed/algorithm/plan, input shape, cache conditions and browser context. Missing provenance stays unknown.
3. Alternate matched baseline/candidate complete jobs; preserve individual repetitions and report sample counts and spread. Separate microbenchmarks, allocation/storage censuses, statistical diagnostics, contracts and timing samples. Compare conversion/preparation/publication scopes explicitly.
4. Measure CPU, allocations, reservations/RSS, temporary logical traffic and sampled storage peaks where supported. Logical traffic is not physical SSD I/O; reservations are not RSS; sampled peaks are lower bounds. Avoid adding independent peak values or reusing summary rows as new samples.
5. Check conservation, membership, lineage, digests, strict caps and failure/cancellation/publication cleanup. Require exact order/bytes only for matching algorithms/plans or exact rewrites. Distribution-equivalent changes require their proof and declared diagnostics; preserve flagged results and exclusions.
6. Promote only after complete-job gains, bounded resource behavior and the replay contract are supported on the intended workload/runtime. Extend device/scale coverage when it can change that decision. Otherwise stop and retain the result with its limitations.
