## Consecutive value-partition fusion (2026-10-17)

The opt-in `experimental-consecutive-partitions` feature recognizes adjacent
value-partition chains and groups once by their concatenated tuples. It retains
original selected-column order and duplicates, rather than replacing the logical
pipeline with one user-visible partition. A tuple-prefix boundary identifies
where each logical parent changes. The emitter reconstructs every original
lineage element, canonical child order, encounter order, stage count/minimum/
maximum and downstream operation index/random domain. Original source IDs and
row ordinals survive unchanged. No shuffle or positional/assignment barrier is
crossed. Both CSV ingestion and later datasets use the same chain emitter.

Only final leaf rows/catalogs are materialized. The implementation retains one
current lineage stack and a reserved previous-key buffer, with fixed arrays for
at most 64 logical stages. Resolved combined-column vectors and temporary
borrowed-value descriptors reserve actual capacity before allocation. Existing
sorter/routing/merge reservations, checked compact fields and encoded output
snapshots retain their normal lifetimes. JSON values/clones, analysis metadata
and runtime allocations remain within the previous incomplete accounting scope;
this is not a process/RSS cap. High-fanout combined tuples use the existing
external sort fallback instead of collecting an unbounded group catalog.

A combined key can need more capacity than separate keys. Typed admission denial
drops the complete tentative output before serial retry. Initial ingestion
reopens and revalidates CSV; a later attempt replays its immutable input dataset.
Already completed logical stages remain intact. After one such denial, remaining
chains stay serial for that job. Cancellation, invalid input/metadata, disk-space
failure and output limits are terminal. Sorter row-capacity errors now retain
`MemoryAdmission::Local` through their original explanatory context, permitting
this classification without matching error strings. Discarded physical I/O,
allocation peaks and completed parent work remain in diagnostic counters.

Every logical stage still checks max-files independently, and the final encoded
snapshot enforces original byte limits. Empty named parents yield no partition
children; stage input counts still include those parents. Empty input and
selection failures retain normal semantics. Full tuples and original hierarchical
lineage remain in output filenames/manifests. This is an exact v1 execution
rewrite; it introduces no new random algorithm or flexible replay policy.

### Complete-job comparison

Keep the candidate opt-in. Native comparisons improve, but the repeated large
browser case regresses materially. Defaults retain the original execution.

The final native matrix contains **168 timed complete jobs and 56 separate
allocation censuses**, with three alternating repetitions. Paired release builds
use matching sources and differ only in the experimental feature. Successful
jobs independently conserve unique IDs and every field, verify full partition
tuples, encounter order and original balanced-parent membership, then compare
exact bytes/order, filenames, lineage, stage statistics and logical digests.

Primary jobs use 300,001 presorted rows, one/four workers and explicit 32 MiB job
budgets. Narrow two-field fixtures repeat the payload partition as a compatibility
control. Cyclic 33-column/rare-wide fixtures partition distinct c0/c1 columns but
have ten observed joint tuples; these correlations are not used by the planner.
Independent fixtures change c1 to produce 100 country/city tuples, beyond the
64-route preflight limit, and exercise external grouping. Rare-wide fixtures add
one 1.8 MB payload.

Four-worker medians, seconds:

| Shape | Pipeline | Original | Fused | Change |
| --- | --- | ---: | ---: | ---: |
| Narrow repeated-key control | Two partitions | 0.3340 | 0.1978 | -40.8% |
| Narrow repeated-key control | balanced(4) → two partitions | 0.4526 | 0.2776 | -38.7% |
| Narrow repeated-key control | Two partitions → uniform → balanced(2) | 0.5335 | 0.4324 | -18.9% |
| Cyclic, 33 columns | Two partitions | 1.3078 | 0.7799 | -40.4% |
| Cyclic, 33 columns | balanced(4) → two partitions | 1.4869 | 1.2084 | -18.7% |
| Cyclic, 33 columns | Two partitions → uniform → balanced(2) | 1.6869 | 1.3881 | -17.7% |
| Cyclic rare wide | Two partitions | 1.2959 | 0.7383 | -43.0% |
| Cyclic rare wide | balanced(4) → two partitions | 1.4954 | 1.1895 | -20.5% |
| Cyclic rare wide | Two partitions → uniform → balanced(2) | 1.6538 | 1.3796 | -16.6% |
| Independent, 100 tuples | Two partitions | 1.6065 | 1.1213 | -30.2% |
| Independent, 100 tuples | Two partitions → uniform → balanced(2) | 2.2123 | 1.7461 | -21.1% |
| Independent rare wide | Two partitions | 1.5357 | 1.1245 | -26.8% |
| Independent rare wide | Two partitions → uniform → balanced(2) | 2.2271 | 1.7756 | -20.3% |

All 18 initial medians improve 16.6–47.1%. The eight independent-key medians
improve 19.7–30.2%. The 1,400,001-row native control improves 14.6% (6.308 to
5.389 seconds), despite switching from routing without merges to 82 runs/two
merges. The 6,400-row resident three-stage chain improves 22.3% (0.0650 to
0.0505 seconds). Its baseline/candidate resident-sort counts are retained in the
raw artifact; no external runs are needed.

The four-worker cyclic many-column two-partition census lowers whole-job
requested allocation traffic from 401.4 to 16.8 MB and allocations from
1,520,177 to 619,366. Logical engine reads fall from 317.0 to 106.7 MB, writes
from 342.5 to 132.7 MB, and peak engine temporary bytes from 141.4 to 109.2 MB.
Median GNU CPU falls from 1.16 to 0.66 seconds; median per-process RSS changes
from 14,368 to 13,564 KiB, while charged capacity peaks remain about 8.6 MB.

For independent many-column keys, requested traffic falls from 425.7 to
194.3 MB. Logical reads fall from 317.0 to 106.7 MB and writes from 342.5 to
132.7 MB; peak temporary bytes change from 139.1 to 132.4 MB. Median CPU falls
from 1.23 to 0.84 seconds and RSS is about 14 MiB for both variants. CPU has
0.01-second resolution. Requested traffic, charged peaks and RSS measure
different things; these results do not establish a universal peak-memory gain.

### Native/WASI parity and large browser regression

The repeated small/medium replay completes **168 native/WASI jobs**, with three
alternating repetitions, four native workers and one browser worker. Primary
100,001-row cases preserve exact parity and improve browser medians 13.4–29.7%.
Independent-key browser cells improve 6.6–13.3%. The 6,400-row independent
three-stage resident chain improves 6.1% in the browser and 3.8% natively.

The initial four-job large acceptance pass exposes a browser regression. A
further **12 alternating complete jobs** at 1,400,001 rows confirm it: browser
median time rises from **22.05 to 35.86 seconds (+62.6%)**, with original range
21.38–22.06 seconds and candidate range 35.51–36.26 seconds. The native replay
improves 17.2% (6.073 to 5.026 seconds). All 184 replay/acceptance jobs match exact
output and metadata; native jobs also independently check fields/IDs and tuples.

The original large browser pipeline uses routing and no external merges; the
candidate performs 71 runs and two merges (82 runs/two merges natively). This
demonstrates a material scale/storage tradeoff despite lower native allocation
traffic and selected small-browser gains. It does not establish which individual
WASI/OPFS cost dominates. The repeated observations supersede the single large
timing for performance interpretation. Keep the global fused candidate opt-in.

Browser profiles are persistent and isolated per matrix; current-source workers
and generated development artifacts are restored afterward. Default native and
WASI builds are restored and their hashes verified. Browser CPU/allocation/RSS
and physical device traffic are not measured. All storage observations are warm
and uncontrolled; engine counters include read-ahead and differ from physical
SSD I/O, filesystem allocation and full source/destination storage peaks.

### Validation and reproduction

Five new tests cover eligibility barriers, escaped NUL/Unicode/empty tuple fields,
resident and hierarchical grouping with multiple parents, duplicated/overlapping
selections, original row IDs/ordinals/fields/keys, every stage summary, downstream
seeded shuffles and terminal/empty ingestion snapshots. Injected admission denial
checks both CSV restart and later-dataset retry; denial/cancellation after actual
row emission releases partial rows, catalogs and reservations. **199 default /
229 all-feature workspace tests (143 all-feature library tests), formatting,
default/all-feature all-target Clippy with warnings denied and 24 candidate
Chromium/WASI contracts pass.** Local-server tests use loopback access.

Thirty native controls compare exact CSV bytes/order, filenames, lineage,
statistics and logical digests, independently conserving all fields/IDs. They
cover leading/later/three-stage/64-stage chains, duplicate name/index selections,
downstream shuffle/balanced splitting, UTF-16/BOM, headerless input, empty input
and named allocations, strict caps, a max-files failure after grouping starts,
malformed CSV and ambiguous headers. Failed jobs leave no output or temporary
directory.

The configured shared-admission matrix completes 48 jobs: eight unconstrained
references, 16 constrained successes and 24 clean rejections at 1/2/4/8/16 MiB
process-ledger ceilings. Every success conserves fields/IDs and matches its exact
reference. The independent narrow-payload candidate succeeds at 2/4 MiB where
the original is denied; successful candidates need no serial retry in this
matrix. Injected tests separately verify retry. These are configured capacity
limits, not OS/cgroup/RSS pressure experiments; no failed job leaves output or
temporary files.

Artifacts: [native matrix](../../evidence-originals.md#sha256-abb0f6f2d3df5f6d519937db6b6071a7fd70c0eef92ab869bf120868ce636ffd "Original: docs/benchmarks/consecutive-partitions-native-2026-10-17.jsonl"),
[independent keys](../../evidence-originals.md#sha256-a902693ccb5a4216bb71dd58525e960138e24aa9a99ee72d3cd7af97185c6322 "Original: docs/benchmarks/consecutive-partitions-independent-2026-10-17.jsonl"),
[hierarchical native control](../../evidence-originals.md#sha256-bdd7d1b94b96db4dca61220a042861c545520cc7d0524ff9ffc609f3611b8a81 "Original: docs/benchmarks/consecutive-partitions-multilevel-2026-10-17.jsonl"),
[resident chain](../../evidence-originals.md#sha256-6bf87ea2e9e2921c085a04cd72da8044696d3a3accc8dd12327319cd402325c8 "Original: docs/benchmarks/consecutive-partitions-chain-2026-10-17.jsonl"),
[native/WASI matrix](../../evidence-originals.md#sha256-5931dce0ee31f10d45a599009ea1ab727c29c7194129d0d20533cd08b130c5ba "Original: docs/benchmarks/consecutive-partitions-engines-2026-10-17.jsonl"),
[native/WASI independent keys](../../evidence-originals.md#sha256-64067496756c3ea52161866bbc9483ab34dacc28670462916e7965203f752390 "Original: docs/benchmarks/consecutive-partitions-independent-engines-2026-10-17.jsonl"),
[native/WASI resident chain](../../evidence-originals.md#sha256-ff98b61e713a26e46521637fdb4b4617e064e328bdc507176d18218d76fcb422 "Original: docs/benchmarks/consecutive-partitions-chain-engines-2026-10-17.jsonl"),
[initial large acceptance](../../evidence-originals.md#sha256-3bcdc53b270f38246e16c064fcc87ad5b0ea7ccde117619f9a32c72113dfea58 "Original: docs/benchmarks/consecutive-partitions-multilevel-engines-2026-10-17.jsonl"),
[repeated large native/WASI matrix](../../evidence-originals.md#sha256-acb51149e296fe3099c174e3c91fed6ee6f0bad419dc2f55d5746a882c08cb84 "Original: docs/benchmarks/consecutive-partitions-multilevel-repeated-engines-2026-10-17.jsonl"),
[configured admission controls](../../evidence-originals.md#sha256-64f00f38b62de4d2d0eb10bd099975094745942241b04e92d32904e1879d59d2 "Original: docs/benchmarks/consecutive-partitions-boundaries-2026-10-17.jsonl"),
[encoding/failure controls](../../evidence-originals.md#sha256-286a3ffa2c05fe15021e4813495a2acb2aebce7e06738576444c0ba0c0c08883 "Original: docs/benchmarks/consecutive-partitions-controls-2026-10-17.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-9515e0c1d605de6735a16f159336a54253c9faace68f641524290165e5d20917 "Original: docs/benchmarks/consecutive-partitions-browser-2026-10-17.json"),
[summary and source/build identities](../../evidence-originals.md#sha256-607221e2cea8c9a53e866eaf63f05639bcb83c7b8d09e6c7c1826bfeecf48177 "Original: docs/benchmarks/consecutive-partitions-summary-2026-10-17.json").

```sh
# Build/copy ORIGINAL and ORIGINAL_ALLOC, then FUSED and FUSED_ALLOC.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-consecutive-partitions
python3 scripts/benchmark-external-shuffle.py --baseline ORIGINAL --candidate FUSED \
  --baseline-allocator ORIGINAL_ALLOC --candidate-allocator FUSED_ALLOC \
  --rows 300001 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide \
  --cases consecutive consecutive_parents consecutive_downstream
# Independent keys: --shapes independent independent_wide --cases consecutive consecutive_downstream
# Hierarchy: --rows 1400001 --workers 4 --shapes independent --cases consecutive
# Resident chain: --rows 6400 --workers 4 --shapes columns --cases consecutive_chain
python3 scripts/validate-consecutive-partitions.py --baseline ORIGINAL --candidate FUSED
python3 scripts/validate-consecutive-memory.py --baseline ORIGINAL --candidate FUSED
# Build/copy matching default/candidate WASI files with scripts/build-browser.sh.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs ORIGINAL FUSED ORIGINAL.wasm FUSED.wasm \
  100001 3 narrow,columns,rare_wide \
  consecutive,consecutive_parents,consecutive_downstream original,fused 4
```
