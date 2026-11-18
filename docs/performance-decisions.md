# Workload and runtime performance decisions

## Full strategy retention review (2026-10-23)

The [phase-one decision report](strategy-review.md) extends this selected
historical synthesis to every live default/experimental strategy and every
cataloged evidence family. Its [coverage audit](benchmarks/strategy-corpus-review-2026-10-23.json)
retains hashes, record locations, explicit family assignments and exclusions for
all pre-review artifacts, including unlinked files. No benchmarks were run.

Keep canonical comparison/external merge execution and original stages as the
reproducible baseline/fallback; keep distinct explicit allocation/splitting and
resident-shuffle capabilities. Conditionally retain useful exact fusions and
allocation ranges, with runtime/shape guards. Remove buffer shuffle as agreed;
recommend pruning radix, prefix distribution, partition-first, XOF, independent
buckets and unused Parquet wiring. E2 parent batching/replay is rejected and removed,
accepted by Astra after actual-diff and raw verification review; preserve its narrow balanced gain and separate
regressions in the dated evidence. E3 compact and IPC are separately rejected by
Astra and their live integrations removed; see the
[bounded decision](performance.md#direct-input-snapshot-rejection-and-removal-2026-10-26).
E1 compact spills remain unresolved and opt-in; do not add
an experiment merely to preserve a redundant prototype. Reuse the flexible policy
seam in the future Auto design without promoting its current selector.

These recommendations supersede blanket retention of opt-in candidates in the
historical introduction below. The existing numerical audit remains unchanged,
with its original populations and limitations. Recent Windows calibrations and
resource/release validation are reviewed separately, never pooled into those
38 contrasts. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns implementation
status and acceptance criteria. Current engine behavior/defaults remain unchanged.

## Selected historical synthesis (2026-10-20)

Evidence synthesis, 2026-10-20. **Prioritize exact pass elimination; keep every opt-in candidate experimental.** The strongest calibration candidates are shuffle/partition, deep nested balanced ranges, proven constant keys, terminal partition/shuffle/balanced, and routed membership chains. Native consecutive partitions and hash-heavy parallel profiles deserve narrower evaluation. Large browser merge transitions, skew, many parents and higher live-memory costs prevent a universal selector or default promotion.

This resolves the first [historical TODO](../TODO.md) decision using existing measurements. It adds no engine changes or new benchmark runs. [Performance notes](performance.md) own the dated experiment interpretations; [benchmark rules](benchmarks/README.md), [rewrite eligibility](pipeline-rewrites.md) and [validation limits](validation.md) remain authoritative. Next experiments belong to the existing SSD-calibration TODO, not a separate checklist.

## Population and interpretation

The numerical table below deliberately selects 38 informative contrasts, including losses and alternate baselines. It is not an exhaustive corpus analysis or a ranking across experiments. Each contrast uses one artifact's matched workload/runtime/worker cell. Different fixture sizes, binaries, pipelines, algorithms and browser contexts stay separate. Two rows may share candidate observations; they are alternate comparisons, not independent studies. All ordinary comparisons have three observations per side; the focused XOF comparisons have seven. Medians and observed min/max ranges describe these samples, not confidence intervals or tail behavior.

The [derived cells](benchmarks/performance-decisions-2026-10-20.json) retain artifact SHA-256, physical JSONL lines, repetitions, explicit baseline/candidate labels and filters, raw environment/fixture records, selected resource counters, and nulls for missing fields. A cell's `id` below identifies its `/cells` entry. The artifact's `sources` map supplies context for those same records only. Original records remain authoritative for algorithms, diagnostics, fingerprints and allocation censuses. A historical commit or a current harness does not identify an old dirty-build binary; use the recorded binary/WASM and source hashes in each dated section and linked summary. Unrecorded fixture hashes, feature identities, browser contexts or harness hashes stay unknown. Missing details cannot be recovered from an adjacent file or its filename.

Native operation clocks include CLI startup, preparation, serialization and publication. Browser clocks include analyze/WASM restart, execution and export, with benchmark-owned setup/verification/removal excluded as recorded by the particular harness. Older environment notes have coarser cleanup wording; do not infer identical teardown boundaries across harness versions. The two `profile-*` contrasts measure fresh full-file profile commands, including CLI startup, **not executed output jobs**. They support a profiling decision only. Browser parity/contract durations and allocation-census elapsed values never enter speed estimates.

All selected storage is warm and uncontrolled WSL or Chromium OPFS. Persistent-profile evidence is preferred for the exact fusions when present. Resident, spill-block and allocation-range browser samples retain their historical temporary/private context; they cannot substitute for persistent device calibration. Browser startup is outside the clock. No table entry establishes physical SSD throughput, a cross-platform gain, hosted-release acceptance or an RSS cap.

## Decision table

Numerical cell IDs below resolve to the following within-experiment examples. Broader ranges cited in the dated narratives remain separate cells; effects here are not pooled.

| Candidate / workload | Native decision and evidence | Chromium/WASI decision and evidence | Resource and contract conditions |
| --- | --- | --- | --- |
| Exact shuffle → partition (`experimental-shuffle-partition`) | High calibration priority: `shuffle-native`, 300,000 many-column rows, four workers, −32.0%. Rare-wide payload-key controls remain mixed. | High priority: `shuffle-browser`, 100,000 many-column rows, persistent profile, −28.0%. Large persistent replay is a single acceptance point. | Leading many-column census cuts requested allocations 525.3→185.9 MB and logical writes 346.4→146.2 MB; some downstream temp peaks rise. Exact original-parent domains/order required. [Dated evidence](performance.md#exact-shufflepartition-prototype-evaluation-2026-10-16). |
| Nested balanced ranges (`experimental-nested-balanced`) | Prioritize deep chains: `nested-native`, 300,001 many-column rows, four workers, −28.5%; tiny controls are mixed. | `nested-browser`, 100,001 rows, persistent profile, −27.9%; smaller partition-parent native controls are mixed. | Deep native chain cuts logical reads 420.5→104.9 MB; temp peak stays about 130.9 MB. Preserve nested remainder rounding, not a product split. [Evidence](performance.md#nested-balanced-range-fusion-2026-10-17). |
| Proven constant keys (`experimental-constant-partition`) | Prioritize repeated/mixed-key partitions: `constant-native`, 300,001 rows/four workers, −25.8%. Small repeat-only groups cost 5.7%. | `constant-browser`, mixed keys/100,001 rows/persistent profile, −22.9%. Primary many-column browser controls are near flat (−1.6% to +2.0%). | Repeated native partition requested traffic 401.4→16.0 MB; charged peak stays about 8.6 MB. Only prior logical partition lineage proves constants. [Evidence](performance.md#proven-constant-partition-keys-2026-10-17). |
| Consecutive partitions (`experimental-consecutive-partitions`) | Native-only calibration candidate: `consecutive-native`, 300,001 independent-key rows/four workers, −30.2%. | Require a selector before expansion: 100,001 independent rows −11.3%, but 1,400,001 rows **+62.6%** (`consecutive-browser-large`). | Large original routes without merge; fused browser uses 71 runs/two merges. Smaller allocation traffic does not compensate for that plan change. Bounded complete-attempt fallback remains mandatory. [Evidence](performance.md#consecutive-value-partition-fusion-2026-10-17). |
| Partition → uniform → balanced (`experimental-partition-balanced`) | Prioritize terminal single-parent paths: `partition-balanced-native`, 1,400,001 rows/four workers, −14.5%. Later parents/downstream primary cells include losses up to 20.3%; five-repeat rechecks do not erase them. | `partition-balanced-browser`, repeated large persistent jobs, −19.3%; both plans use 86 runs/two merges. | Example one-worker terminal logical writes 83.5→48.6 MB; allocator live peak remains about 7.85 MB. Count catalog is bounded; high fanout/admission denial replays original execution. [Evidence](performance.md#partition-shuffle-balanced-fusion-2026-10-18). |
| Membership → partition → membership (`experimental-streaming-chain`) | Prioritize routed chains: 1,400,001-row probability chain −48.1%; interleaved −33.7%. | Routed probability chain −55.9%; large interleaved chain **+14.1%**, switching from routing to 71 runs/two merges. Do not enable all chains from small-browser gains. | Example 100,000-row native writes 185.0→45.4 MB, but live allocator peak 8.34→11.20 MB and ledger peak 8.60→11.27 MB. Preserve per-scope encounter counters and named empty groups. [Evidence](performance.md#streaming-membership-partition-chains-2026-10-18). |
| Parallel profiles (`experimental-parallel-profile`) | Narrow profiling candidate: 300,000-row/33-column/four-worker fresh scan −46.0%; rare-wide +1.9%. Tiny/first-wide inputs need serial guards. | No browser parallel implementation; replay proves parity only. | Many-column CPU 1.18→1.53 s, RSS 5,476→8,132 KiB, scan reservations 0.25→2.34 MB. Rare-wide reservation peak rises 0.51→6.41 MB. No output-job speed claim. [Evidence](performance.md#bounded-parallel-profiling-evaluation-2026-10-16). |
| Independent parent batching/replay (removed; `experimental-parallel-groups` invalid) | Astra rejected E2: current CLI balanced −12.68%, skew **+36.86%**, small **+354.45%**, n=3 per side/cell. Historical −8.7% balanced gain remains valid for its old build. | WASI remains serial; no browser performance claim. | Separate retained-owner population **+24.78%**, n=3 per side; no pooling with CLI. Cheap row/group/worker checks cannot reserve shared headroom or bound decoded width; no feasible validated guard yet. Ordinary sort/compression workers remain. [Decision and evidence limits](performance.md#independent-parent-batching-removal-2026-10-25). Removal accepted by Astra after actual-diff and raw verification review. |
| Compact spill adapter (`experimental-spill-blocks`) | Keep v1 default: many-column/global/four-worker job **+23.3%**; multi-level native losses reach 46%. | Conditional storage candidate: many-column/global/100,000-row browser −19.6%, but historical temporary context needs persistent SSD confirmation. | Many-column stored spills shrink 38.8%; adapter transcodes v1 and adds CPU. Stored bytes, whole-job traffic and simultaneous file space are separate. Exact bytes/metadata match; no compression promotion. [Evidence](performance.md#compact-external-spill-block-evaluation-2026-10-16). |
| Flexible policy (`experimental-flexible`) | Contract seam, not a throughput candidate: resident auto **+28.6%** against the same build's seeded path. | Auto versus flexible uniform changes are small/mixed; no default switch. | Extra stages/audit materialization and failed resident attempts matter. Auto's admission can select different pinned permutations; guarantee is prepared-snapshot replay. [Evidence](performance.md#explicit-flexible-full-shuffle-policy-2026-10-18). |
| Flexible partition-first (`experimental-flexible-partition`) | Retain experimental: balanced −17.3% versus sequential flexible, but **+16.4% versus exact-output fusion**. Skew/high fanout/wide cases also regress. | Small private-context auto examples improve about 20–25%, but unchanged explicit-uniform control costs about 9%; no matched exact-fusion browser comparison in that pass. | External peak temp grows 261→354 MB versus sequential flexible. Distribution equivalence does not require the same seeded order. Prefer exact fusion calibration first. [Evidence](performance.md#flexible-partition-first-shuffle-experiment-2026-10-18). |
| Buffered XOF (`experimental-fast-rng`) | Do not reopen RNG tuning: seven-repeat Fisher–Yates −14.1% versus flexible counter, but **+6.1% versus original seeded**. Sparse grouped four-worker case regresses. | Small counter→XOF differences are mixed; source-only loop gains do not predict full jobs. | Resident live allocator peak remains 34.6 MB; read-ahead hurts sparse IDs at larger caches. Versioned source/cache parity and original diagnostic limitations remain. [Evidence](performance.md#versioned-buffered-blake3-shuffle-source-2026-10-18). |
| Exact-allocation ranges (`experimental-flexible-allocation`) | Promising **only for explicitly flexible jobs**: resident explicit-uniform −26.5%, external −15.7% versus original shuffle→assign; 257 parents **+2.4%**. Rare-wide +1.2% against existing assign→shuffle fusion, a different requested order. | Private-context auto −38.2% versus sequential flexible; this pass does not establish gain against original seeded browser execution. | External publication-inclusive logical writes 726.3→516.2 MB versus sequential flexible; charged temp peak 315.7 MB exceeds original shuffle→assign 261.4 MB. Joint membership/order proof, quotas/zeros and prepared-snapshot contract required. [Evidence](performance.md#flexible-shuffle-and-exact-allocation-ranges-2026-10-19). |
| Independent buckets (`experimental-random-buckets`) | Stop prototype expansion without a new bottleneck: 1.5-million-row counter buckets **+34.8%** versus seeded, +3.5% versus flexible keys. | Large persistent counter buckets 20.343 s versus seeded control 19.395 s; original control was later, not interleaved with candidate. A flexible-key win does not justify replacing seeded execution. | Fewer allocations/space than flexible keys, but more logical traffic than seeded. Retain both original diagnostic window flags; follow-up success does not erase them or prove uniformity. [Evidence](performance.md#independent-random-bucket-full-shuffle-experiment-2026-10-19). |
| Resident Fisher–Yates v1 | Keep explicit versioned option: 100,000 rows/256 MiB/global +4.5% versus resident random keys; grouped native is slightly faster. | Global +3.7%; grouped browser also slower. Three overlapping global ranges do not establish a stable algorithm preference. | All jobs are actually resident. Compare exact bytes only within the same algorithm. No calibrated resident/external crossover follows. [Evidence](performance.md#resident-full-shuffle-native-and-wasi-comparison-2026-10-15). |
| Shared admission and dynamic pressure rechecks | Retain as correctness: representative spill accounting +0.4%; recheck hooks +3.9%. These examples are costs, not claimed throughput gains. | One WASI instance shares a ledger; no cross-worker/tab capacity coordination is established. Browser hook/parity results do not establish pressure response or RSS bounds. | Boundary/concurrent lifetime, allocation coverage and runtime headroom remain open. Configured ceilings are not OS-pressure experiments. [Admission](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16), [rechecks](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16). |

## Numerical audit

Each entry is **median (minimum–maximum) seconds**, baseline → candidate. Change is `100 × (candidate median / baseline median − 1)`, so negative means lower complete elapsed time. Raw variant labels and sample locations are in the derived JSON; repeated use of one candidate under another baseline does not add observations. Profile rows have their narrower scope stated above.

| Cell ID | Baseline seconds | Candidate seconds | Change | Samples per side |
| --- | ---: | ---: | ---: | ---: |
| `shuffle-native` | 1.2338 (1.2227–1.3394) | 0.8390 (0.8388–0.8701) | -32.0% | 3 / 3 |
| `shuffle-browser` | 1.5842 (1.5809–1.6257) | 1.1412 (1.0446–1.1760) | -28.0% | 3 / 3 |
| `nested-native` | 1.0490 (1.0119–1.0843) | 0.7502 (0.7475–0.7560) | -28.5% | 3 / 3 |
| `nested-browser` | 1.7761 (1.7213–1.8411) | 1.2814 (1.2355–1.3318) | -27.9% | 3 / 3 |
| `constant-native` | 1.1736 (1.1632–1.2799) | 0.8709 (0.8663–0.9313) | -25.8% | 3 / 3 |
| `constant-browser` | 2.9003 (2.8567–2.9003) | 2.2353 (2.2241–2.2952) | -22.9% | 3 / 3 |
| `consecutive-native` | 1.6065 (1.5235–1.6113) | 1.1213 (1.1151–1.1382) | -30.2% | 3 / 3 |
| `consecutive-browser-small` | 2.7401 (2.7017–2.7923) | 2.4299 (2.4280–2.4946) | -11.3% | 3 / 3 |
| `consecutive-browser-large` | 22.0541 (21.3800–22.0588) | 35.8640 (35.5137–36.2580) | +62.6% | 3 / 3 |
| `partition-balanced-native` | 5.6392 (5.6176–5.6753) | 4.8228 (4.7706–4.8272) | -14.5% | 3 / 3 |
| `partition-balanced-browser` | 20.7694 (20.0625–20.9013) | 16.7687 (16.7037–17.1071) | -19.3% | 3 / 3 |
| `chain_probability-native` | 7.1582 (7.1372–7.1811) | 3.7126 (3.6575–3.7527) | -48.1% | 3 / 3 |
| `chain_probability-browser` | 23.5272 (23.5002–23.7661) | 10.3798 (10.3406–10.4251) | -55.9% | 3 / 3 |
| `chain_interleaved-native` | 6.8385 (6.7898–6.8431) | 4.5338 (4.5292–4.5875) | -33.7% | 3 / 3 |
| `chain_interleaved-browser` | 24.1755 (24.1710–24.5124) | 27.5842 (27.3261–27.8530) | +14.1% | 3 / 3 |
| `profile-columns` | 1.2497 (1.2395–1.2529) | 0.6752 (0.6704–0.6903) | -46.0% | 3 / 3 |
| `profile-rare-wide` | 0.1176 (0.1153–0.1176) | 0.1199 (0.1191–0.1221) | +1.9% | 3 / 3 |
| `groups-columns` | 1.0488 (1.0084–1.0532) | 0.9571 (0.9128–1.0306) | -8.7% | 3 / 3 |
| `groups-skew` | 1.3001 (1.2589–1.3164) | 1.6293 (1.5512–1.6434) | +25.3% | 3 / 3 |
| `spill-native` | 0.7825 (0.7774–0.7836) | 0.9650 (0.9206–0.9655) | +23.3% | 3 / 3 |
| `spill-browser` | 2.0213 (1.9940–2.0620) | 1.6258 (1.6008–1.6848) | -19.6% | 3 / 3 |
| `flexible-policy` | 0.0801 (0.0800–0.0853) | 0.1030 (0.1010–0.1045) | +28.6% | 3 / 3 |
| `partition-first-sequential` | 0.2755 (0.2749–0.2759) | 0.2279 (0.2226–0.2285) | -17.3% | 3 / 3 |
| `partition-first-exact` | 0.1958 (0.1946–0.2040) | 0.2279 (0.2226–0.2285) | +16.4% | 3 / 3 |
| `xof-flexible` | 0.2166 (0.2134–0.2339) | 0.1860 (0.1837–0.2357) | -14.1% | 7 / 7 |
| `xof-seeded` | 0.1753 (0.1704–0.2274) | 0.1860 (0.1837–0.2357) | +6.1% | 7 / 7 |
| `ranges-uniform` | 0.2077 (0.2031–0.2124) | 0.1525 (0.1492–0.1542) | -26.5% | 3 / 3 |
| `ranges-external` | 0.8777 (0.8569–1.0396) | 0.7398 (0.7307–0.7681) | -15.7% | 3 / 3 |
| `ranges-many` | 2.4370 (2.4173–2.4566) | 2.4963 (2.4178–2.5283) | +2.4% | 3 / 3 |
| `ranges-rare_wide` | 0.1580 (0.1353–0.1646) | 0.1292 (0.1278–0.1332) | -18.2% | 3 / 3 |
| `ranges-existing-fusion` | 0.1276 (0.1229–0.1375) | 0.1292 (0.1278–0.1332) | +1.2% | 3 / 3 |
| `ranges-browser` | 4.1176 (3.8857–4.9977) | 2.5436 (2.3996–2.7984) | -38.2% | 3 / 3 |
| `buckets-native` | 4.2030 (4.1934–4.2522) | 5.6644 (5.6515–5.6846) | +34.8% | 3 / 3 |
| `buckets-flexible` | 5.4747 (5.3436–5.6914) | 5.6644 (5.6515–5.6846) | +3.5% | 3 / 3 |
| `shared-admission` | 0.2273 (0.2209–0.2299) | 0.2283 (0.2222–0.2311) | +0.4% | 3 / 3 |
| `pressure-recheck` | 0.2233 (0.2229–0.2234) | 0.2321 (0.2278–0.2358) | +3.9% | 3 / 3 |
| `resident-native` | 0.1601 (0.1589–0.1696) | 0.1674 (0.1651–0.1869) | +4.5% | 3 / 3 |
| `resident-browser` | 1.1605 (1.1416–1.3256) | 1.2034 (1.1517–1.2844) | +3.7% | 3 / 3 |

## Eligibility, controls and gaps

The derived artifact's `excluded_from_timing` table hashes each named rejected/superseded source and records why it is excluded. Allocations, summaries, contract checks, diagnostic runs, partial attempts and configured-boundary records are never ordinary timing samples. Selection is deliberately diagnostic rather than statistically representative: wins and counterexamples identify decisions to test, not expected production effects.

| Evidence stratum | Treatment and reason |
| --- | --- |
| Final exact-fusion native matrices; persistent shuffle/partition and later-fusion browser comparisons | Include the selected matching cells. Retain original primary regressions even where a later sensitivity pass is favorable. Match within runtime; native/WASM descriptor widths can change run counts. |
| Initial parallel-profile, parallel-group, nested-balanced and streaming-chain prototypes | Keep as revision/failure context; do not count as final candidate repetitions. Preliminary parallel-groups baseline predates final sources. First-wide profiling failure motivates the serial guard. |
| Preliminary flexible-policy runs overlapping builds/tests | Exclude from timing conclusions; use final isolated matrix. |
| Incomplete large shuffle/partition browser attempt | Failure/storage diagnostic only. Later persistent complete and repeated passes do not erase the failed attempt or make historical private contexts persistent. |
| Allocation-range prototype, input-only eviction and final replay | Use final borrowed-audit native build for timing. Input eviction cannot establish cold host/spill caches. One-repeat final native/WASI replay verifies the audited build, not an additional repeated speed estimate for the earlier private-context matrix. |
| Existing assign→shuffle fusion and exact shuffle→partition | Relevant alternate baselines, explicitly labeled. They do not authorize changing a requested sequence or claiming equality of distribution-equivalent plans. |
| Bucket quality corpus, replay and independent follow-up | Keep primary flags and original family thresholds. Replay is the same observations under parity checking, not a second family; follow-up is separate. Adversarial skew controls exercise bounded fallback and are excluded from quality inference. |
| Boundary/concurrent-lifetime/cap/cancellation checks and allocation/storage censuses | Correctness/resource evidence only. Diagnostics through READY exclude later publication; allocation-range/bucket post-publication observers have different scope. Never combine these counters as though identical or add independent peaks. |
| Radix, prefix distribution, snapshot adapters, compression/GPU and billion-row point | No new timing population here. [Existing pruning criteria](performance-opportunities.md#removed-from-the-active-queue) retain regressions/absent bottlenecks; the single [billion-row point](performance.md#billion-row-native-full-shuffle-acceptance-point-2026-10-16) supports its narrow build/workload acceptance only. |

Exact rewrites have recorded conservation, tuple/parent membership, stage/lineage/digest, strict-cap and failure/cancellation cleanup controls in their dated sections. Matching pinned exact algorithms/plans require original bytes/order. Distribution rewrites instead need their joint-distribution argument, versioned plan/domain identities, quota/membership checks, quality diagnostics and exact matching-plan replay. Finite diagnostics do not prove uniformity. Native publication remains atomic directory publication; browser export uses its completion-marker semantics. This synthesis adds no correctness coverage and does not combine historical test counts.

CPU, requested allocation traffic, live reservations, RSS, logical engine traffic, stored spill bytes and sampled file space are separate outcomes. Reduced allocation traffic can leave live peaks unchanged or higher. Engine temp peaks exclude destination staging in older harnesses; sampled combined file peaks are lower bounds. WSL block counters, even zero after eviction requests, cannot establish physical I/O. Browser CPU/allocator/RSS and complete lineage/catalog/publication/runtime accounting remain gaps.

## Consequence for the next TODO

The existing target-SSD calibration item should start with an exact pass-elimination candidate, preferably shuffle/partition or a terminal partition/shuffle/balanced path, and a matching feature-off build. Retain a known losing/near-flat shape or parent case as a falsification control. Deep nested ranges and proven constant keys offer other strong exact candidates. Separate runtime decisions; do not use a native gain to select browser merging.

Before selecting a browser chain or consecutive-partition plan, require evidence around the routing→external transition that distinguishes the recorded large regression. Before selecting parallel profiles/groups, include shared admission, CPU and live-memory/storage costs; group skew is a mandatory negative control. Flexible allocation ranges merit calibration only for a user requirement that accepts their replay contract, including many-parent and rare-wide controls. Compact spill blocks need persistent browser/device evidence before any runtime-specific selection; native transcoding costs remain a reason to retain v1.

No numeric size/cardinality threshold is calibrated by this synthesis. Stop a targeted follow-up if complete-job benefits disappear, its negative control is not separated, resource growth is unbounded, or required correctness/replay evidence fails. The [experiment criteria](performance-opportunities.md#acceptance-for-experiments) require pinning builds/harness/fixtures, recording cache/device/context, alternating complete jobs, retaining failures, and closing the candidate's specific acceptance gaps before promotion. No new large matrix is warranted from this table alone.

Reproduce the derived audit without running jobs:

```sh
python3 scripts/summarize-performance-decisions.py
python3 scripts/summarize-performance-decisions.py --check
python3 scripts/benchmark-catalog.py
python3 scripts/benchmark-catalog.py --check
```

The numerical audit is a rounded rendering of those cells, in selection order. Source hash changes require a fresh eligibility review; successful regeneration alone is not an approval of new measurements.


## Current E1 disposition (Astra review, 2026-10-24)

The historical compact-spill contrasts and numerical synthesis above remain
unchanged. The [persistent hosted E1 comparison](performance.md#persistent-hosted-spill-block-e1-comparison-2026-10-24)
is Astra-reviewed **unresolved**: the earlier private many-column win did not
survive, and rare-wide ranges overlap with two of three matched pairs losing.
Stored-byte savings do not establish a useful elapsed-time win or a feasible
runtime/shape guard. The run earns neither retention nor removal; keep the feature
opt-in unchanged and E1 unchecked. A repeatable rare-wide complete-job benefit
exceeding observed variation and measurement overhead could change the decision,
but requires a separately bounded approved follow-up. No automatic expansion or
numeric selection threshold follows.
