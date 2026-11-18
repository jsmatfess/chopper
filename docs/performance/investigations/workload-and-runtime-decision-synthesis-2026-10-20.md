## Workload and runtime decision synthesis (2026-10-20)

The [decision table](../../performance-decisions.md) resolves the first performance TODO
using existing evidence, without new benchmark jobs or engine/default changes.
It prioritizes exact pass elimination for target-SSD calibration and preserves
large browser merge regressions, parallel CPU/memory/storage costs, alternate
flexible baselines and replay limits. All experimental candidates remain opt-in.

The [derived audit](../../benchmarks/performance-decisions-2026-10-20.json) contains
38 curated matched contrasts with raw source hashes/physical lines, per-side
repetitions, medians/ranges, selected resource metrics, raw context records and
explicit exclusions. These are within-experiment examples, not independent
studies or pooled gains. Fresh-profile clocks remain separate from complete
output jobs; allocation censuses and correctness/diagnostic records do not enter
timing estimates. Missing metadata stays unknown. The decision document links
each family to its original dated controls, resources and reproduction details.

Reproduce with `python3 scripts/summarize-performance-decisions.py` and check with
`python3 scripts/summarize-performance-decisions.py --check`, then refresh/check
the catalog. Warm WSL/temporary or persistent OPFS evidence does not establish
physical SSD throughput or a process RSS cap. The next open TODO is targeted
SSD calibration; no new size/fanout threshold or default selector is established.
