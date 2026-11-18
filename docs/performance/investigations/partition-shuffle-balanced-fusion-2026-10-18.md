## Partition shuffle balanced fusion (2026-10-18)

`experimental-partition-balanced` extends the exact-v1 partition/shuffle pair
through an immediately following balanced split. It remains opt-in on native and
WASI. The original logical job, last uniform-shuffle index, source IDs, child
random domains, collision refinement, per-parent remainder rounding, lineage,
stage summaries, names and strict final caps are preserved. Repeated adjacent
uniform shuffles still use the last original operation index. Explicit
Fisher–Yates and buffer strategies and intervening operations are excluded.

### Execution and bounded fallback

A sorted tuple/count catalog is built alongside the original partition/random
keys. Its descriptor/key capacities and growth overlap reserve before allocation;
it retains at most 256 tuples and uses at most a conservative memory/64 allowance.
The existing resident/external `GroupRandom` sorter orders rows, including
hierarchical merges and v1 collision refinement. Known tuple counts let its
single checked decode traversal emit each balanced child directly, retaining
original per-tuple ordinals and exact nonempty-group failures.

Terminal fusion avoids writing and reading the partition/shuffle dataset before
CSV serialization. With downstream operations it still writes the child dataset;
the saving is principally the separate balanced frame-boundary scan and catalog.
It does not eliminate every downstream materialization.

High fanout or optional count admission failure immediately drops the count
catalog and uses the original pipeline. Initial CSV ingestion reuses its original
sort in this case. Later execution discards all tentative results, including
previously completed parents, before replaying the immutable source dataset.
Any typed memory denial during a complete fused attempt also releases the attempt
and retries without this fusion, including CSV reopening with the existing
source-stability checks. Cancellation, malformed input, disk/record limits and
strict-cap errors remain terminal. Only completed attempts increment the fusion
and row diagnostics; typed admission retry has a separate counter.

### Native measurements

The final native matrices contain **322 timed complete jobs and 102 separate
allocation censuses**, all with exact byte/order/metadata parity and independent
ID/field conservation. The primary 100,000-row matrix alternates three
repetitions across one/four workers, narrow/many-column/rare-wide rows, leading
and later-parent fusion, repeated uniform shuffles and downstream operations.
Its terminal single-parent cases improve **5.8–21.6%**; repeated-shuffle cases
improve 4.3–16.6%. Across all primary cells the range is **−21.6% to +20.3%**:
later-parent and downstream cases include regressions.

A separate five-repeat recheck of the two noisy many-column cases improves
3.9–7.5%; it supplements rather than replaces the primary regressions. The
100,000-row skew matrix improves 3.5–17.4%. The 128-row controls remain mixed
(−4.8% to +0.9%). A 1,400,001-row many-column/four-worker job uses 86 sort runs
and two merge operations in both builds: the median improves **14.5%**, from
5.639 to 4.823 seconds, with ranges 5.618–5.675 and 4.771–4.827 seconds.

The initial exploratory native run predates complete-attempt admission rollback
and the final diagnostic fields. It is retained separately and superseded for
performance interpretation by the matched-production-source matrices above.

The 100,000-row many-column terminal case at one worker illustrates the physical
pass saving. Logical temporary writes fall from 83,476,333 to 48,586,552 bytes;
logical reads fall from 75,330,057 to 39,988,890 bytes and peak engine temporary
data from 74,828,262 to 48,569,334 bytes. Whole-job requested allocation traffic
falls from 66,666,176 to 65,853,865 bytes; peak live requested allocation stays
about 7.85 MB. This is chiefly an I/O/pass improvement, not a large allocation
reduction. GNU time records native CPU, RSS and filesystem block counters in the
raw artifacts; ledger capacity and requested allocation peaks are not RSS caps.

### Native/WASI acceptance

The persistent-profile comparison completes **156 alternating native/WASI
jobs**: 144 at 100,000 rows across all three row shapes and four pipelines, plus
12 repeated 1,400,001-row terminal jobs. Every result matches exact CSV bytes,
order, names, lineage, logical digests and stage summaries. Native jobs also
independently check every ID/field and partition membership.

Primary browser medians improve **2.7–28.2%**. The repeated large browser median
improves **19.3%**, from 20.769 to 16.769 seconds, with ranges 20.063–20.901 and
16.704–17.107 seconds. Both large browser builds use 86 runs and two merges.
The accompanying large native median improves 13.0%; its timing is a separate
comparison from the earlier native-only matrix. **24 candidate Chromium/WASI
contracts pass.** Default native/allocator/WASI development builds are restored
and their hashes recorded in the summary.

### Validation and scope

Seven new tests cover selector barriers and original indices; charged counter
fanout, local/shared denial and release; exact rounding/ordinals/lineage/stages
and downstream domains; fallback after a successfully emitted parent; forced
primary-key collisions through resident/hierarchical merges; injected CSV and
later-dataset admission retry; and cancellation after actual child emission.
**199 default / 236 all-feature workspace tests, 150 all-feature library tests,
formatting and default/all-feature all-target Clippy with warnings denied pass.**
Local-server contracts run with loopback access.

Thirty-two CLI controls independently conserve IDs/fields and match exact
CSV/order/names/stage/lineage/digest output or reject cleanly. They cover repeated
shuffles, earlier parents, downstream operations, skew, high fanout, rollback
after an earlier parent's output, oversized counter keys, empty input, named
empty allocations, UTF-16/BOM, headerless input, strict caps, max-files limits,
per-parent insufficient counts and malformed CSV. Every failed job leaves no
publication or temporary files. The initial incomplete control run used a byte
cap too small for its wide-key success fixture; the corrected final controls
are authoritative.

Configured shared-admission controls add eight unconstrained references,
30 constrained successes, ten clean failures and four invalid settings, across
one/four workers, many-column/late-wide rows, fresh profiles and complete jobs.
Every success matches its reference; each failure leaves no output or temporary
files. These are configured ledger limits, not OS/cgroup/RSS-pressure evidence.

All storage observations use warm uncontrolled WSL storage and persistent
Chromium OPFS. Logical counters include read-ahead and differ from physical
SSD/device I/O and full source/output filesystem allocation peaks. Browser
CPU/allocations/RSS are unavailable. Target SSD calibration, broader platforms,
flexible randomization, streaming-chain fusion and full allocation/resource
policy work remain open. Retain current defaults.

Artifacts: [native](../../evidence-originals.md#sha256-70e0de231535daac588c9f7997ce2f514c3455d610cdfb8ffecfd6f09692a2dc "Original: docs/benchmarks/partition-balanced-native-2026-10-18.jsonl"),
[skew](../../evidence-originals.md#sha256-935d92f732be996ac5c93b98aafdd72bb5dc171b7b6b0be54db45689656b4681 "Original: docs/benchmarks/partition-balanced-skew-2026-10-18.jsonl"),
[tiny](../../evidence-originals.md#sha256-f8b27cbd99f8e81445ee868fb9a7e8ebbb313b913cb374753e70f99dfdaa11af "Original: docs/benchmarks/partition-balanced-tiny-2026-10-18.jsonl"),
[hierarchical](../../evidence-originals.md#sha256-355a8426ce77f2ce11f4d3f4be543943916d074f26a882bcd856aae2c3a62c19 "Original: docs/benchmarks/partition-balanced-multilevel-2026-10-18.jsonl"),
[timing recheck](../../evidence-originals.md#sha256-49e3e7c3c3fc666cd8146ec84552c4b36b1a09e233f621a089e44e09209ce283 "Original: docs/benchmarks/partition-balanced-recheck-2026-10-18.jsonl"),
[native/WASI](../../evidence-originals.md#sha256-07de5929df66a4ef1e17471642698c46fe71d9b7411c6e19ef2c2f14bcaea79d "Original: docs/benchmarks/partition-balanced-engines-2026-10-18.jsonl"),
[large native/WASI](../../evidence-originals.md#sha256-d556494ae53d2fa23764d7d1149dc452b1da773a8b0a740aaddde6c4ca96a90d "Original: docs/benchmarks/partition-balanced-multilevel-engines-2026-10-18.jsonl"),
[CLI controls](../../evidence-originals.md#sha256-27d22837fb73aabfb513a19fa4cf5bc18a19b0da84734aef39ae5a027c64cafa "Original: docs/benchmarks/partition-balanced-controls-2026-10-18.jsonl"),
[shared admission](../../evidence-originals.md#sha256-c680f0b993ecfe3ab65177f5ccfd3f1c37637ec0cf1cfd38003dde2bab0bfda4 "Original: docs/benchmarks/partition-balanced-boundaries-2026-10-18.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-9e9790a8b11528f1ca2d7c1776bed1356d0b257c9507021b8a045d9129334871 "Original: docs/benchmarks/partition-balanced-browser-2026-10-18.json"),
[summary/build/source identities](../../evidence-originals.md#sha256-df39ee048af71b7f2e26857b516ca4bb205f8525d3d01f33d89d7100237218a7 "Original: docs/benchmarks/partition-balanced-summary-2026-10-18.json").

```sh
# Build/copy ORIGINAL and ORIGINAL_ALLOC, then FUSED and FUSED_ALLOC.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-partition-balanced
python3 scripts/benchmark-external-shuffle.py --baseline ORIGINAL --candidate FUSED \
  --baseline-allocator ORIGINAL_ALLOC --candidate-allocator FUSED_ALLOC \
  --rows 100000 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide \
  --cases partition_balanced partition_balanced_parents partition_balanced_downstream partition_balanced_repeat
# Skew: --shapes skew; tiny: --rows 128 --shapes narrow columns.
# Hierarchy: --rows 1400001 --workers 4 --shapes columns --cases partition_balanced.
python3 scripts/validate-partition-balanced.py --baseline ORIGINAL --candidate FUSED
python3 scripts/benchmark-shared-memory.py --before ORIGINAL --after FUSED \
  --partition-balanced --rows 100000 --memory-mb 32
# Build/copy matching WASI files using scripts/build-browser.sh.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs ORIGINAL FUSED ORIGINAL.wasm FUSED.wasm \
  100000 3 narrow,columns,rare_wide \
  partition_balanced,partition_balanced_parents,partition_balanced_downstream,partition_balanced_repeat original,fused 4
```
