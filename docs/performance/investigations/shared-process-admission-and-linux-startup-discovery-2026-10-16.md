## Shared process admission and Linux startup discovery (2026-10-16)

Charged reservations now acquire against **both** the existing per-job workspace
and one aggregate ledger. The default ledger is shared by native preparation,
profiling, cached observations, independently returned profile copies, retained
prepared snapshots and execution. Local acquisition rolls back if aggregate
admission fails; shrinking/dropping releases both counters. Moving reservation
ownership does not reacquire or briefly release capacity. Local and aggregate
denials have distinct errors. Sort/parser/key pressure keeps existing spill/retry
behavior; mandatory failure leaves publication unstarted.

The module accepts an explicit `MemoryPool` for embedded callers/tests through
`prepare_with_memory_pool`, `Context::with_memory_pool` and
`ProfileCache::with_memory_pool`. Ordinary CLI/server/browser callers use the
same default ledger automatically. Browser sharing covers one WASI engine
instance, including its retained profile cache; **different workers/tabs/processes
do not share this in-process ledger**.

Linux startup discovery reads bounded `/proc/meminfo`, membership and mount
records, resolves the cgroup2 mount/root, and visits accessible ancestors. For
each finite `memory.max` or `memory.high`, it subtracts that ancestor's own
`memory.current`, including sibling use, and takes the minimum with
`MemAvailable`. It handles root-exempt files, mount escaping, mounted subtrees,
malformed/unreadable limits, overflow and membership changes conservatively.
Known finite headroom survives an incomplete later observation. The non-root
scope of the memory interface files is specified by the
[Linux kernel documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files).

The initial tracked-capacity ceiling is **half observed additional headroom**.
Incomplete/unsupported discovery caps that choice at **128 MiB**, or less when
a smaller known boundary exists. Native `CHOPPER_MEMORY_LIMIT_MB` can lower the
ceiling; it is a positive binary-MiB integer read once per process. It cannot
increase the observed/fallback ceiling. Invalid/zero/overflow values fail before
preparation creates temporary state. Diagnostics include the chosen limit,
current/peak aggregate reservations and a timestamped startup observation.

This is an engineering admission margin, **not a calibrated RSS bound**. Existing
numeric `resources.memory_mb` remains the per-job ceiling with unchanged units,
worker rules and algorithm thresholds. No automatic working-budget field or
algorithm switch is introduced. Discovery is a startup snapshot; pressure
rechecks and predictive per-stage grants remain open. Existing reservations are
not subtracted again from observed available RAM or revoked. Runtime/allocator,
codec/publication and other uncharged memory still use separate headroom.

Seven new tests exercise exact/shared capacity edges, transactional rollback,
8-thread simultaneous acquisition/release/retry, cgroup ancestor/sibling/high
pressure, parser/mount/fallback cases, and real profiling/preparation lifetimes.
Two cached/returned profile owners and two prepared jobs share one ledger through
publication/drop; denied preparation and cancelled profiling preserve other
owners and permit retry. **187 workspace tests, 102 combined-feature library
tests, formatting, workspace/all-target Clippy with warnings denied, and native
and WASI release builds pass.**

At 100,000 rows/33 fields, one/four native workers and three alternating
repetitions, the ordinary matrix has **96 timed complete jobs and 32 separate
allocation censuses**. All output bytes/order, names, lineage, stage counts and
digests match the saved pre-admission build. Native medians range from −2.3% to
+9.2%; affected operation paths range from +0.4% to +9.2%. This is measured
accounting cost, with warm uncontrolled storage and no throughput-gain claim.

A second matrix applies a **16 MiB aggregate ceiling** to the candidate while
leaving per-job numeric settings unchanged: **84 timed jobs and 28 allocator
censuses**, all with exact parity. Paths already spilling at a 32 MiB per-job
budget cost +0.3% to +3.2%. Previously resident shuffle/partition/assignment
paths now spill and cost +14.0% to +27.1%. The extra storage work is the measured
tradeoff for enforcing a smaller shared ceiling.

| One-worker candidate, 100,000 rows | Ordinary / constrained aggregate peak bytes | Ordinary / constrained observed RSS KiB | Ordinary / constrained sort runs |
| --- | ---: | ---: | ---: |
| Uniform shuffle | 42,624,477 / 13,276,096 | 44,748 / 18,272 | 0 / 4 |
| Partition + fused shuffle | 48,026,692 / 15,047,783 | 50,892 / 20,748 | 0 / 4 |
| Exact assignment + fused shuffle | 48,231,512 / 15,117,760 | 51,152 / 20,504 | 0 / 4 |

RSS entries are individual normal measurement samples, not configured limits or
allocator censuses. All constrained candidate peaks remain below 16,777,216
charged bytes. RSS can exceed that value because the ledger is incomplete and
allocator/runtime mappings remain outside it.

A separate complete-job/profile boundary harness runs many-column and late-wide
Unicode fixtures at 1/4/8/16/64 MiB process ceilings, one/four workers. Its
**48 runs** include eight unconstrained copied-build references, **32 successful
constrained runs** with exact profile/output/metadata parity, and **eight clean
bounded failures**. The references independently check every unique ID and field
value. Failures leave no job temporary files or published destination; the
successful runs also clean up. Four invalid environment controls fail before
preparation. These are configured ledger-pressure tests, not OS/cgroup pressure,
paging, power-loss or physical SSD tests.

Chromium/WASI adds **24 passing contracts** and a three-shape alternating
comparison: **36 fresh profiles, 18 browser cache replays and 36 complete output
jobs**, all preserving exact profiles and output/metadata. Native fresh-profile
medians cost +1.3% to +3.6%; native job medians cost +1.0% to +4.1%. Browser
profile medians vary from −17.3% to −0.5%, cache medians from −0.2% to +1.1%,
and complete jobs from −11.1% to +13.7%. These noisy browser results do not
establish a throughput improvement. A seven-repetition narrow-fixture recheck
adds **28 fresh profiles, 14 cache replays and 28 complete jobs**, all exact.
It measures +5.4% native/+0.04% browser fresh profiling, +0.1% browser cache,
and +4.9% native/+5.9% browser complete jobs. Browser job ranges overlap; the
initial +13.7% median increase is not reproduced at that magnitude. Both passes
are retained without changing the candidate between them.

Artifacts: [ordinary native](../../evidence-originals.md#sha256-4dd78f5730256e1f36c3ea6e9d2dc0f8af811b0f5a5319824e48fe254e09d174 "Original: docs/benchmarks/shared-memory-native-2026-10-16.jsonl"),
[16 MiB native](../../evidence-originals.md#sha256-bddcf0334e122e6a5560072845b4381650de6a549634c46d6d7a38c24913c205 "Original: docs/benchmarks/shared-memory-constrained-native-2026-10-16.jsonl"),
[complete-job/profile boundaries](../../evidence-originals.md#sha256-c5eabfea95484ad53ceb30d194754cae073e52db803eb331b496f230739a96dd "Original: docs/benchmarks/shared-memory-boundaries-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-efbc4249fb48c488c6fd8d2edc4d2811f6978b43817d20a3b38cb64d199ac6ea "Original: docs/benchmarks/shared-memory-browser-2026-10-16.json"),
[profiling/cache/native-WASI comparisons](../../evidence-originals.md#sha256-6c355651c1d4ae53b80b60eaa0f125717171c93766271181e1f4542fb22af301 "Original: docs/benchmarks/shared-memory-profiling-2026-10-16.jsonl"),
[seven-repetition profiling/job recheck](../../evidence-originals.md#sha256-9dadb6ad006df139cab97c6777213bff98ba72bf81bdb5ddea40afa5620c82be "Original: docs/benchmarks/shared-memory-recheck-profiling-2026-10-16.jsonl"),
[summary and hashes](../../evidence-originals.md#sha256-a1dd2e8d18a887dbd850d92c8bc276f4d59f8a9ba90c75dafa0487e398354267 "Original: docs/benchmarks/shared-memory-summary-2026-10-16.json").

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases plain resident spill rare_wide partition_shuffle assign_shuffle stratified_assign_pipeline_spill streaming_pipeline
# Constrained follow-up: prefix CHOPPER_MEMORY_LIMIT_MB=16; omit the plain case.
python3 scripts/benchmark-shared-memory.py --before BEFORE --after .tools/linux/target/release/chopper --rows 100000
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-profiling-budget.mjs BEFORE BEFORE.wasm 100000 3
```
