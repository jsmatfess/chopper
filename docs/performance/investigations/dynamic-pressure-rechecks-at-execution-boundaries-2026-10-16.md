## Dynamic pressure rechecks at execution boundaries (2026-10-16)

The default Linux process ledger now refreshes bounded proc/cgroup observations
at preparation, profiling/cache, progress, sort-run, merge and export boundaries.
Checks are throttled to one start per second across the process. There is no
background timer: a slow operation reaches its next safe boundary before another
check. Ordinary explicit per-job budgets, worker rules and seeded algorithms keep
their meaning. Caller-created `MemoryPool::new` pools retain their fixed policy;
WASI and unsupported host adapters retain static fallback admission.

The startup/environment ceiling remains immutable. A fresh observation supplies
**additional** headroom. With grants serialized across observation, the policy
records the charged baseline after the read and admits net new charged capacity
up to half that headroom, under the startup ceiling:

```text
current admission limit = min(startup ceiling, charged baseline + additional headroom / 2)
```

Releases may proceed during observation and reduce the recorded baseline.
Existing owners keep their reservations; releasing capacity permits reuse within
the current allowance. Failed growth preserves transactional local/aggregate
rollback and existing spill/retry paths. Complete observations can restore the
allowance up to the startup ceiling. Incomplete/unknown discovery can lower it,
but cannot restore a previously reduced limit. Known finite headroom remains
conservative through the host adapter's existing partial-discovery rules.

This is a charged-capacity admission rule, not an RSS calculation or a physical
memory grant. A held capacity can include uncommitted pages, and allocator
retention is not available RAM. Neither charged baseline nor fresh free headroom
is a complete live-memory measure. Uncharged metadata, publication/codecs/input
adapters, temporary-file scratch, discovery allocations and runtime/allocator
memory still need separate headroom. Existing grants are not evicted; mandatory
allocations can fail cleanly under pressure. There is no automatic per-job budget
field, predictive stage grant or cross-worker/tab browser coordination.

Diagnostics distinguish immutable `limit_bytes`, current `admission_limit_bytes`,
`pressure_baseline_reserved_bytes`, the latest timestamped `pressure_observation`
and `pressure_rechecks`, while retaining the startup observation and current/peak
charged bytes. Observation `complete` describes discovery, not an atomic kernel
snapshot or memory guarantee. A historical peak can exceed a later smaller
admission limit; the current live charge is checked against the applicable grant
limit.

Six new tests cover throttling, exact capacity edges, zero/unknown headroom,
recovery, overflow, releases during observation, local rollback and eight-thread
concurrent admission/rechecking. Lifecycle tests retain cached/returned profile
owners across denied copies, deny publication after exact preparation, verify no
staging/destination/temp leakage, and retry after recovery. A 100,000-row/33-field
complete-job fixture drops headroom after row 65,536 and then encounters a
1.8 MB Unicode field; quoted multiline records exercise real CSV boundaries.
Both one/four-worker runs independently verify every unique ID and field, output
bytes/order, filenames, lineage, stages and logical digest. **199 workspace tests,
113 combined-feature library tests, 24 Chromium/WASI contracts, formatting and
all-target workspace Clippy with warnings denied pass.** Native/WASI releases
build. The combined-feature boundary fixture was rerun after finalizing its
success/clean-denial cases.

The injected fixture tries 8 and 16 MiB **additional observed headroom** with an
unchanged 128 MiB startup charged ceiling and 256 MiB per-job setting. The default
merge algorithm succeeds at both, spilling two runs instead of retaining the
whole permutation. At both worker counts, peak charged capacity falls from
47,096,248 to 26,536,228 bytes. These are ledger values, not RSS. The experimental
prefix implementation completes with exact parity at 16 MiB; at 8 MiB a later
recheck can leave insufficient mandatory decode/conversion overlap, producing a
verified clean denial. Both outcomes are recorded. These injected policy tests
are not measurements of real OS pressure, paging or physical-device behavior.

The final native comparison contains **96 timed complete jobs and 32 separate
allocation censuses**, alternating copied baseline and candidate for three
repetitions, one/four workers. The 100,000-row/33-field matrix covers plain output,
resident/external shuffle, a rare-wide record, probabilistic downstream grouping
and a balanced/exact-assignment/shuffle pipeline. The 1.4-million-row follow-up
covers global and per-group external shuffles, 67/86 total runs and hierarchical
merging. Every complete job preserves exact CSV bytes/order, filenames, output
lineage, stage counts and logical digest.

| Final native comparison | Median wall-time change | Median GNU CPU-time change |
| --- | ---: | ---: |
| 100,000-row cases, one/four workers | −4.2% to +6.0% | Raw samples retained; short-job timer resolution limits precision |
| 1.4-million-row external cases, one/four workers | +0.1% to +3.1% | +0.5% to +3.0% |

The extended candidate preparations record **three to four real Linux pressure
rechecks**, while the short ordinary preparations finish before the first timed
recheck. No external memory load was imposed: these measure admission/sampling
cost on a warm unconstrained WSL host, not paging or an OOM boundary. CPU time,
observed peak RSS, requested allocation traffic, charged peaks and logical
intermediate I/O/space remain in raw data. These results establish no general
throughput gain. Analysis diagnostics are preparation snapshots; later export
rechecks and peaks do not retroactively update the returned analysis. Direct
`MemoryPool::usage()` queries report the current ledger state.

The complete-job/profile boundary harness additionally runs 48 controls across
many-column/late-wide shapes, one/four workers and 1/4/8/16/64 MiB aggregate
ceilings. It records eight unconstrained references, **32 constrained successes**
with exact profile/output/metadata parity and **eight clean bounded failures**,
plus four invalid-setting checks. Reference jobs independently verify each ID
and field. No constrained failure publishes a destination or leaves job temp
files. These are configured admission tests, not OS/cgroup pressure. Boundary
controls overlapped Chromium contracts and their elapsed values are excluded
from performance conclusions; normal native/engine timing matrices ran after
other tests/builds completed.

Initial timing artifacts precede finalization of the larger boundary fixture and
its test-only success/denial cases. Although production policy is unchanged,
the rebuild changes binary identity; the final matrices use the final binary
and are reported above. The [initial ordinary](../../evidence-originals.md#sha256-e726d84c003d54adb9c1fcf4e8a987e29c5b97a2e452ff2e1c6f6ed6f842c784 "Original: docs/benchmarks/dynamic-pressure-initial-native-2026-10-16.jsonl")
and [initial multi-level](../../evidence-originals.md#sha256-a01b795aa6bd6f27659cd448c6e73fa811b2bca0e3f66f6681721a94ec2d32e9 "Original: docs/benchmarks/dynamic-pressure-initial-multilevel-2026-10-16.jsonl")
passes remain available but are excluded from final timing ranges.

The final native/Chromium-WASI matrix adds **27 complete jobs**, alternating
native, browser baseline and browser candidate at 100,000 four-field rows with
128-byte payloads. Global uniform shuffle, downstream probabilistic grouping /
shuffle and gzip output preserve exact CSV bytes/order and logical output
metadata. Browser medians change by +0.1%, +2.0% and +0.9%, respectively, with
overlapping ranges in every case. WASI has no Linux pressure adapter; these
validate the shared hooks, static fallback and serialization compatibility,
not cross-tab admission or browser RSS. No browser throughput gain is claimed.

Artifacts: [native timings/censuses](../../evidence-originals.md#sha256-2e4bb15435b37b2ebaabe9b2203d757931a19e306fe1230651564cd75e6b8d19 "Original: docs/benchmarks/dynamic-pressure-native-2026-10-16.jsonl"),
[multi-level native](../../evidence-originals.md#sha256-c795388cb04c18b4ebbdc162e5609c2db6819dc2b53c2fe53d66891f0c4515da "Original: docs/benchmarks/dynamic-pressure-multilevel-2026-10-16.jsonl"),
[configured job/profile boundaries](../../evidence-originals.md#sha256-6dbf3c5767b2590809e98d6c183b874bbd3cbcdc2b991715fd24357b23bc0679 "Original: docs/benchmarks/dynamic-pressure-boundaries-2026-10-16.jsonl"),
[injected default pressure](../../evidence-originals.md#sha256-4183c925cd9d57fcd975eeee069d6f2b96d6b2d0623a95270dd0fecff676c7c1 "Original: docs/benchmarks/dynamic-pressure-injected-2026-10-16.jsonl"),
[injected prefix pressure/denials](../../evidence-originals.md#sha256-33454e2d6efff15ac900fb68da778bc006087dc75c1fbf45aed6e671645eff4e "Original: docs/benchmarks/dynamic-pressure-injected-prefix-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-06f2475961905ff3943d24ab7c4780cd5ba7e5b7a26eb3afb5e531354e4e13cc "Original: docs/benchmarks/dynamic-pressure-browser-2026-10-16.json"),
[native/browser comparisons](../../evidence-originals.md#sha256-27685d37dd7051bc2e2598e5c8d6f0c7c39c7caaeea3a5706f8ea85527959dcd "Original: docs/benchmarks/dynamic-pressure-engines-2026-10-16.jsonl"),
[summary, ranges and hashes](../../evidence-originals.md#sha256-e9cc3534e11f63c65f5d8f34b76a12287f5ca7e74dddd90260292956120d1256 "Original: docs/benchmarks/dynamic-pressure-summary-2026-10-16.json").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain resident spill rare_wide streaming_pipeline assign_pipeline_spill
# Multi-level follow-up: --rows 1400000 --cases spill assign_pipeline_spill
python3 scripts/benchmark-shared-memory.py --before BEFORE --after .tools/linux/target/release/chopper --rows 100000
cargo test --release --locked -p chopper --lib resources::lifecycle_tests::mid_ingestion_pressure -- --nocapture --test-threads=1
cargo test --locked -p chopper --lib --features experimental-radix,experimental-distribution \
  resources::lifecycle_tests::mid_ingestion_pressure -- --nocapture --test-threads=1
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  uniform32,balanced_probabilistic_shuffle,gzip 128 BEFORE.wasm
```
