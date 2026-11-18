## Explicit flexible full-shuffle policy (2026-10-18)

`experimental-flexible` adds an opt-in `full_shuffle_policy: "flexible_v1"`
job setting. Omission retains `seeded_v1`, including its existing algorithms,
seeded output, manifest version and omitted-default JSON representation. A build
without the feature rejects flexible execution before opening its input. The browser
crate forwards the same feature; imported job JSON preserves the setting. There
is no new default or automatic GUI opt-in.

### Execution, audit and replay contract

The first flexible physical plan is `ordered-logical-stages-v1`. It executes every
requested stage in order, materializing intermediate datasets and retaining the
already encoded final CSV snapshot. It does not commute operations, eliminate
repeated shuffles or reuse the default ingestion/fusion selectors. This makes a
measurable starting point for the subsequent distribution-preserving experiments,
not a performance promotion of the policy itself.

Within each existing parent, `shuffle: auto` attempts the existing versioned
Fisher–Yates implementation against actual charged payload/descriptor capacity.
A local or typed aggregate admission denial discards the entire attempt and
replays the immutable input group through external-capable random-key v1 sorting,
with the original source IDs and logical operation/parent random domain. All
attempt storage is gone before retry. Other errors propagate. Explicit `uniform`,
`fisher_yates` and `buffer` retain their requested implementations and failure
semantics; auto never substitutes a bounded buffer for a full shuffle. The
existing unbiased draws and random-key collision refinement are unchanged.

Selection is per parent: one job may use both full-shuffle algorithms. Resource
budgets, aggregate pressure, platform and enabled implementations can change the
realized order. A seed alone does **not** promise rerun equality across plans,
builds or platforms. The actual guarantee is `prepared_snapshot_only`:
analysis, confirmation, strict encoded byte/row caps, file counts and export refer
to the same retained realized CSV bytes. Explicit buffer requests remain bounded
mixing and are labeled `uniform_full_permutation: false` in the audit.

A charged fixed-buffer writer streams a job-owned execution JSONL file rather
than retaining a group/lineage catalog in memory. Its header records the requested
logical operations, source logical digest, effective seed/resources/workers,
physical-plan and RNG versions, engine/target and compile-time experiment flags.
Per-shuffle-group records identify original logical index and parent lineage,
requested strategy, selected algorithm/RNG/implementation version, admission
choice and actual sort/merge/distribution/temporary-I/O counter deltas. Stage
records retain requested operations, logical statistics and execution counters.
Analysis exposes a fixed-size summary and BLAKE3 hash of the exact audit bytes;
publication copies those bytes into the manifest without re-encoding them. The
flexible manifest uses `chopper-flexible-full-shuffle-v1`. Consumers should select
`type: "output"` for output entries and retain the additional `execution_plan`,
`execution_group` and `execution_stage` records. Logical indices in audit records
are zero-based; existing analysis stage numbers remain one-based.

Both the plan narrative and the ready analysis warn that methods can change with
available memory and a seed alone is insufficient for replay. This records the
reproducibility boundary before confirmation without changing the immutable
prepared snapshot mechanism.

### Validation and measured scope

The default workspace passes 201 tests and the all-feature workspace passes 252
(including 159 library tests). Formatting, all-feature Clippy with warnings denied,
UI tests, TypeScript, native/WASI release builds and 24 Chromium/WASI contracts
pass. Server tests require loopback access; their initial sandbox-only socket
failures are superseded by the full passing runs with local socket access.

New tests cover legacy JSON omission/version rejection, feature rejection before
input I/O, all three explicit strategies' byte/metadata parity through partition
and downstream balanced splitting, multiline/Unicode/quoted fields, mixed
small/oversized parents, unique-ID conservation, exact output caps and file
counts, named zero-quota groups, original logical indices, repeated-shuffle
retention, no-operation snapshots, and BLAKE3 audit integrity. Changing the source
after preparation preserves exported bytes and audit records. Injected aggregate
denial verifies that all attempt grants are released before random-key replay
and that replay matches explicit uniform at the same original domain.
Cancellation, malformed CSV, disk/record/file limits and impossible byte caps
release all grants without publication.

This is still charged algorithm admission rather than complete live-memory/RSS
accounting. Remaining lineage/JSON/publication/runtime accounting and browser
cross-tab coordination are unchanged open work. The policy supplies the explicit
contract needed for future algorithms; distribution rewrites, a fast RNG and
independent random buckets are separate uncompleted experiments.

Reproduce the native complete-job comparison after building default and
`--features experimental-flexible` release binaries (and the candidate
`allocation-profile` example):

```sh
python3 scripts/benchmark-flexible.py \
  --baseline /tmp/chopper-flexible-before \
  --candidate /tmp/chopper-flexible-after \
  --allocator /tmp/chopper-flexible-after-alloc
bash scripts/build-browser.sh --features experimental-flexible
node scripts/benchmark-engines.mjs /tmp/chopper-flexible-after 100000 3 \
  flex_uniform256,flex_auto256,flex_uniform32,flex_auto32,flex_partition_uniform,flex_partition_auto \
  128 --interleave-cases
```

The WSL Chromium runner also needs its local runtime-library path and loopback
access. All measurements are warm uncontrolled WSL filesystem/OPFS jobs, not
physical SSD or cold-cache throughput. The initial native/browser artifacts
include overlap with validation/build work and are retained only as preliminary
observations; the final measurements below run separately from those workloads.

### Final whole-job results

The final native matrix contains 120 timed jobs and 30 allocation censuses: five
fixtures, one/four workers, three alternating repetitions, prior/default controls,
flexible explicit uniform, and flexible auto. Every job checks exact fields and
unique IDs, canonical partition order/isolation, output caps/counts and logical
metadata. Default and explicit-uniform variants also require identical output
bytes/metadata; auto is checked independently and repeats within its pinned plan.

| Fixture / workers | Candidate default (s) | Flexible uniform (s) | Flexible auto (s) |
| --- | ---: | ---: | ---: |
| resident / 1 | 0.0801 | 0.1049 | 0.1030 |
| resident / 4 | 0.0786 | 0.1031 | 0.1051 |
| columns / 1 | 0.1515 | 0.1853 | 0.1966 |
| columns / 4 | 0.1555 | 0.1901 | 0.2023 |
| external / 1 | 0.1664 | 0.1804 | 0.1771 |
| external / 4 | 0.1524 | 0.1820 | 0.1807 |
| partitioned / 1 | 0.1933 | 0.2299 | 0.2234 |
| partitioned / 4 | 0.1879 | 0.2395 | 0.2196 |
| skewed / 1 | 0.2600 | 0.3535 | 0.3618 |
| skewed / 4 | 0.2635 | 0.3564 | 0.3655 |

The fixtures are 100,000 resident 16-byte-payload rows at 256 MiB; 60,000
32-extra-column rows at 32 MiB; 60,000 external 512-byte-payload rows; and
120,000 balanced/skewed partitioned rows with 64/256-byte payloads at 32 MiB.
Auto admits resident/global and all 16 balanced partition groups. It rejects
the many-column/external global groups; the skewed job selects random-key for
the large parent and Fisher–Yates for 16 small parents. Logical algorithm
admission follows actual capacity rather than a row-count guess.

Compared with the same candidate build using default execution, flexible auto
adds roughly 6–40% median elapsed time across these fixtures. Default-control
changes against the prior binary range from −7.2% to +2.4%; three short warm
repetitions do not establish a small default-path performance change. Extra
materialization dominates the resident case: peak tracked temporary bytes grow
from 2.59 MB to 10.48 MB. The skewed case grows from 74.75 MB to 111.83 MB;
its whole-job allocation count grows from 361,538 to 611,132. The fixed audit
state is small, but the policy currently bypasses default ingestion/fusions,
and denied admission adds a partial scan. Peak live allocator bytes and RSS
are observations, not a hard total-memory cap.

The separate native/WASI matrix adds 36 complete jobs, with exact output/metadata
parity for the tested matching resolved algorithms/plans. It uses 100,000 rows
with 128-byte payloads, global 256/32 MiB and seven country partitions at 32 MiB.
Each pair preserves explicit uniform or selects auto under the same job budget.

| Plan | Native median (s) | Browser/OPFS median (s) |
| --- | ---: | ---: |
| flex_auto256 | 0.1476 | 1.3127 |
| flex_auto32 | 0.1715 | 2.1257 |
| flex_partition_auto | 0.2151 | 2.7052 |
| flex_partition_uniform | 0.2329 | 2.7367 |
| flex_uniform256 | 0.1502 | 1.3502 |
| flex_uniform32 | 0.1582 | 2.0523 |

The browser auto variants change median time by about −2.8%, +3.6% and −1.2%
against matching flexible uniform at 256 MiB, 32 MiB and partitioned scope.
These are small mixed differences, not evidence for a default algorithm switch.
The snapshot/audit contract is implemented; performance gains must come from
separately measured algorithms/plans. Distribution rewrite/RNG/bucket tasks
remain open.

Raw records: [final native](../../evidence-originals.md#sha256-7a58eb44edb6389388efcf09fc342a9e30966e982d3f888b5e331a7c1f0c52c2 "Original: docs/benchmarks/flexible-policy-native-2026-10-18.jsonl"),
[final native/WASI](../../evidence-originals.md#sha256-e2f172dc03227199b981c2df00f67215e30235a05eeabb778646f1158eaf1d9b "Original: docs/benchmarks/flexible-policy-engines-2026-10-18.jsonl"),
[summary, ranges, hashes and censuses](../../evidence-originals.md#sha256-830259bd14bd03f213c32a0e86501bbeb2c0b06b168a4e7f6bbe9e0ea4f5e737 "Original: docs/benchmarks/flexible-policy-summary-2026-10-18.json"),
[24 browser contracts](../../evidence-originals.md#sha256-f2c3197db67613036266d5871deaf002c97d1924f378caed00e303b171e60459 "Original: docs/benchmarks/flexible-policy-browser-2026-10-18.json"),
[preliminary native](../../evidence-originals.md#sha256-628f8002df29f16e865165380fad8f8cb3f2f2054229093a1dd1ad8e2e028ce1 "Original: docs/benchmarks/flexible-policy-initial-native-2026-10-18.jsonl"), and
[preliminary engines](../../evidence-originals.md#sha256-b7cd096a38080d15a1cc89e4aa0bd29faf59eb3cdf9d08cdbe52e5e9cbc5a375 "Original: docs/benchmarks/flexible-policy-initial-engines-2026-10-18.jsonl").
