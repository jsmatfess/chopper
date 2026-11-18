## Versioned buffered BLAKE3 shuffle source (2026-10-18)

Harness: [native source and complete-job comparison](../../history/shuffle-harnesses-2026-11-16/benchmark-fast-rng.py). Run with `--help` for required pinned binary inputs.

**Implemented and measured; opt-in.** `experimental-fast-rng` enables
`full_shuffle_policy: "flexible_v1"` with
`full_shuffle_rng: "blake3_xof_v1"`. Existing jobs retain the counter-based
BLAKE3 source and seeded-v1 plan. The flexible materialization/audit costs still
outweigh this source's gains against the original fused default on the focused
native fixtures. Changing only the seed policy is not a throughput improvement.

The named source `chopper-fast-rng-blake3-xof-1` derives a key from the existing
seed/original-operation/physical-parent domain, then hashes a purpose byte and
little-endian page index. Each independently keyed page uses only its first
65,536 XOF bytes. Keys address every `u64` source ID without multiplying it into
a wrapping `u64` byte position: page `id >> 12`, offset `16*(id & 4095)`.
Draws similarly address 8-byte words with page `i >> 13`; exhaustion after the
last word is checked. Fisher–Yates retains the rejection-based unbiased bounded
mapping. Random-key sorting retains independently derived collision refinement.
There is no claim of a finite generator period or proof of independence: this
is a fixed keyed cryptographic construction with explicitly bounded addressing.
See [primary-source design and quality limits](../../fast-rng-research.md).

`resources.shuffle_rng_buffer_bytes` accepts 64 (default), 256 or 1024 only for
the new source. Cache sizes address identical bytes, including sparse/reordered
IDs, page boundaries and the last `u64` ID; they are throughput choices rather
than new output identities. Fixed cache/hasher/generator state is charged before
admission and released before key-sort completion. A resident attempt denied
source-state admission releases rows/readers before replaying the immutable
input through external keys. Cancellation propagates rather than triggering a
retry. Explicit buffer shuffle remains buffer-v1 even when the full-shuffle
source requests XOF; audit records identify the algorithm actually used.
Entropy mode obtains one seed, records it and uses the same source. A prepared
snapshot remains the replay guarantee; a seed alone does not select a plan.

Frozen [byte vectors](../../evidence-originals.md#sha256-e458eae7864e3ace29db5da6fbc87c84b7101a9995e7ad7ca49dd53449bbefd4 "Original: docs/benchmarks/blake3-xof-v1-vectors-2026-10-18.json") and tests
cover addressing, rejection, exhaustion, source/group domains, fixed-state
admission denial, cancellation, strict caps, immutable source snapshots,
entropy replay, external budgets and unchanged v1/buffer behavior. The combined
partition-first feature has separate child-scope tests. No ambient or
worker-selected randomness was introduced.

### Complete native jobs

The initial matrix alternates seven variants over eight fixtures, one/four
workers and three repetitions: 336 timed jobs, 112 separate allocator censuses
and 16 entropy-seed replays. Fixtures include tiny/resident Fisher–Yates,
resident/external keys, sparse IDs in sixteen groups, 128 small parents,
32 extra columns and a rare 1.8 MB row. Every job verifies exact fields/unique
IDs, relevant membership, output caps and trace identities. Matching pinned
sources/cache sizes require byte/order/metadata parity. Census instrumentation
perturbs timing and is kept separate.

A focused seven-repetition run reduces noise on four cases (168 jobs). Medians
below include preparation and publication, with independent processes and warm,
uncontrolled WSL caches. CPU values are coarse process CPU seconds.

| Case | Workers | Original seeded v1 (s) | Flexible counter (s) | Flexible XOF/64 (s) | Counter → XOF CPU (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Resident Fisher–Yates | 1 | 0.1753 | 0.2166 | 0.1860 | 0.18 → 0.16 |
| Resident Fisher–Yates | 4 | 0.1769 | 0.2327 | 0.1934 | 0.19 → 0.16 |
| Resident keys | 1 | 0.1824 | 0.2315 | 0.2142 | 0.18 → 0.17 |
| Resident keys | 4 | 0.1824 | 0.2232 | 0.2023 | 0.19 → 0.18 |
| Sparse grouped keys | 1 | 0.2164 | 0.2599 | 0.2567 | 0.19 → 0.19 |
| Sparse grouped keys | 4 | 0.2283 | 0.2607 | 0.2787 | 0.21 → 0.21 |
| External keys | 1 | 0.1800 | 0.2082 | 0.1989 | 0.16 → 0.15 |
| External keys | 4 | 0.1716 | 0.2173 | 0.2055 | 0.18 → 0.16 |

An additional 84-job, seven-repetition unchanged-v1 control puts before/after
flexible medians within about −2% to +1.5%. The focused XOF gains against
flexible counter execution are real for selected fixtures, but sparse groups
show little benefit or regress. The original default is faster in every row.
One-worker resident censuses retain the same 34,586,975-byte peak live allocator
requests and about 40 MB RSS; XOF adds one whole-job allocation (200,574 →
200,575 for Fisher–Yates), rather than eliminating the existing row allocations.
Full CPU, RSS, allocation, reservation, temporary-space and logical engine
traffic records are retained. Analysis diagnostics describe preparation through
READY; they do not count subsequent publication reads as whole-job physical I/O.

### Source-only cost and browser jobs

For two million operations and three repetitions, bounded-draw median falls
from 0.2705 s (counter) to 0.0374/0.0331/0.0332 s (64/256/1024-byte XOF caches).
Contiguous keys fall from 0.212 s to about 0.036–0.039 s. Sparse stride-17 keys
cost 0.2184 s with counter, 0.1433 s with XOF/64, but 0.5793/0.6288 s with the
larger caches: unused read-ahead reverses the gain. Checksums match across XOF
cache sizes in every repetition. These raw-loop gains do not predict full jobs.

The small native/WASI matrix completes 150 jobs at 100,000 rows across old/new
v1 controls, all cache sizes, Fisher–Yates/keys, sparse groups, external memory
and entropy mode. Every matching pinned plan matches exact bytes and metadata.
Browser medians are dominated by materialization/storage: flexible counter to
XOF/64 is 1.519 → 1.500 s for Fisher–Yates, 1.529 → 1.536 s for keys,
3.096 → 3.100 s for sparse groups and 2.345 → 2.300 s for external keys.
The original seeded browser fixtures are about 0.760/0.785 s. These three
warm repetitions do not demonstrate a useful browser default improvement.

### Declared distribution diagnostics

The [predeclared acceptance families](../../fast-rng-acceptance.md) separately test
XOF full shuffle and counter-source partition-first plans. Each runs 480 native
jobs: 32 fixed seeds, five input patterns, two full-shuffle strategies and the
unchanged four-row buffer negative control. Each then replays another 480
native and 480 WASI jobs with exact pinned-plan CSV/order/metadata parity.
Neither family flags any of its 60 primary comparisons; each flags all 30
negative-control comparisons at the declared corrected thresholds. Reused ideal
null corpora are immutable and checked by function/source/shape hashes. This is
finite regression evidence, not proof of uniformity, period or independence.
External-scale statistical/device/resource acceptance remains separate.

Raw evidence: [source loops](../../evidence-originals.md#sha256-48d199533cf8129d570495ab12e24720a83a9163cfde75c36d569d123b536d37 "Original: docs/benchmarks/fast-rng-micro-2026-10-18.jsonl"),
[initial jobs and censuses](../../evidence-originals.md#sha256-35635ff8b3689a3851416b201211ea7342c7fb61b9fccceeaffd63dbf5bd091c "Original: docs/benchmarks/fast-rng-native-2026-10-18.jsonl"),
[focused jobs](../../evidence-originals.md#sha256-4c90ad0ac593ba445a4be0b03b19a1811719bb0a9a238e0a3f659ca5c65b3cb3 "Original: docs/benchmarks/fast-rng-focused-native-2026-10-18.jsonl"),
[unchanged-v1 controls](../../evidence-originals.md#sha256-bddfbff1f5f6184fc62faa2f520369c7779b746c2ada04a6280bcd5df144f874 "Original: docs/benchmarks/fast-rng-v1-controls-2026-10-18.jsonl"),
[small native/WASI jobs](../../evidence-originals.md#sha256-8c5eaa1534c2627fc956aa08417ddaa4c20086bb98b628e8e8355ce9ff68b8b1 "Original: docs/benchmarks/fast-rng-engines-2026-10-18.jsonl"),
[38 CLI controls](../../evidence-originals.md#sha256-fff48d4b4bac7592090a2d9addfa17387dc1bef254703336fd37a398ce388e0c "Original: docs/benchmarks/fast-rng-controls-2026-10-18.jsonl"),
[XOF diagnostics](../../evidence-originals.md#sha256-bb18089734b0b31e262142f16abed2b6aa2d888265f07606a93ca05f5d310ca6 "Original: docs/benchmarks/fast-rng-diagnostics-native-2026-10-18.jsonl"),
[XOF replay](../../evidence-originals.md#sha256-555b848253eed62413259a9aafc368c27c807b41edda632aeb2f640a3eb873d7 "Original: docs/benchmarks/fast-rng-diagnostics-engines-2026-10-18.jsonl"),
[partition-first diagnostics](../../evidence-originals.md#sha256-e538d3ab54b3937c17fa484425e7b0f8e0b1919d5dde8be66123f930ea4bdf57 "Original: docs/benchmarks/partition-first-diagnostics-native-2026-10-18.jsonl"),
[partition-first replay](../../evidence-originals.md#sha256-563e5c39e472e5dedf810e909ab54804e983dd4a7af9675e5629d076eb40a0e3 "Original: docs/benchmarks/partition-first-diagnostics-engines-2026-10-18.jsonl"),
and [machine-readable ranges/resources/hashes](../../evidence-originals.md#sha256-58eff2503464a5dcc927fc45181375146402862397aad769495f69d6aa7fbf3c "Original: docs/benchmarks/fast-rng-summary-2026-10-18.json").

### Multi-level native/WASI follow-up and browser failure visibility

A separate 24-job run alternates four cases and engines over three repetitions:
1.5 million rows, 32 extra columns, 32 MiB and zero payload bytes (about 119 MB
CSV). The generator's optional extra-column argument preserves its original
bytes when omitted. Native sorts create 92 initial runs; WASI creates 76 under
its different pointer/state sizes. Both perform two merge operations. Every
matching pinned source/cache/engine reproduces exact output bytes, order and
metadata; unique IDs and all fields are independently checked outside timing.

| Plan/source | Native median (range), s | WASI median (range), s |
| --- | ---: | ---: |
| Original seeded uniform | 4.505 (4.485–4.612) | 19.905 (19.434–20.583) |
| Sequential flexible counter | 5.654 (5.606–6.036) | 24.186 (23.155–24.469) |
| Sequential flexible XOF/64 | 5.928 (5.562–6.054) | 24.650 (23.691–24.774) |
| Sequential flexible XOF/1024 | 5.623 (5.390–5.873) | 23.707 (23.616–23.743) |

The largest cache's roughly 2% WASI improvement against flexible counter is
small relative to the original default's advantage. XOF/64 regresses in this
case. These are warm WSL/local-browser jobs, not physical SSD calibration.
The browser uses a temporary **persistent disk profile**, recorded in the
[raw environment](../../evidence-originals.md#sha256-2e03f193e163ffb2fb5ed8beb160199d3adf1284c8f8680eb74b8975508814e5 "Original: docs/benchmarks/fast-rng-multilevel-engines-2026-10-18.jsonl"),
which is removed after the run. Reproduce after building the matching hosted
worker/WASM with:

```sh
node scripts/benchmark-engines.mjs /path/to/fast-rng-binary \
  1500000 3 uniform32,rng_external_v1,rng_external64,rng_external1024 0 \
  --extra-columns=32 --reload-browser --persistent-browser --interleave-cases
```

The original private-session attempt hit an OPFS resource failure. An isolated
shared-buffer write reproduces an invalid unsigned count (`4294967288`) near
896 MiB although `navigator.storage.estimate()` reports over 10 GiB; changing
only to a temporary persistent profile successfully writes 2 GiB. This observed
profile difference does not establish a universal browser quota. Preserve the
[private failure](../../evidence-originals.md#sha256-f552f0126c2a35bb6b8b72dd07697dd505b78e1bf9df0c514c88b644d02860be "Original: docs/benchmarks/fast-rng-multilevel-private-failure-2026-10-18.log"),
[partial run](../../evidence-originals.md#sha256-c01a196a17862836168aa936e1c25ee868511efb461fa18c46f65796afa43bd8 "Original: docs/benchmarks/fast-rng-multilevel-private-partial-2026-10-18.jsonl"),
[private probe](../../evidence-originals.md#sha256-400e57c0309e22e8c2b27f0351a450bcdc717e98df27550827ee087348571950 "Original: docs/benchmarks/opfs-private-write-probe-2026-10-18.log") and
[persistent probe](../../evidence-originals.md#sha256-837c0dcdca09e7fb95f1652f94274a0756d1787c3aef9cc13eae591eb139ba6e "Original: docs/benchmarks/opfs-persistent-write-probe-2026-10-18.log")
separately; they are excluded from successful timing medians.

That failure also revealed a diagnostic bug: Chromium rejects `TextDecoder`
input backed by `SharedArrayBuffer`, masking the original storage message.
The bridge now copies only the error bytes to an ordinary buffer before
UTF-8 decoding. A real-Chromium regression (`node scripts/test-browser-bridge.mjs`)
fails on the original implementation and preserves the original Unicode error
after the fix; it runs in browser CI. Node-only decoding tests would not catch
this browser-specific behavior. The existing invalid byte-count guard remains
the authority that stops the failed write. No larger storage entitlement is
inferred from estimated quota, and this experiment changes no production quota.

Timing-scope clarification for the browser matrices above: `elapsed_seconds` spans
`analyze` (including its worker/WASM restart) through successful publication.
Subsequent verification and benchmark-owned deletion of retained outputs are
excluded. Some older raw environment notes incorrectly say export cleanup was
included; the timing code and stored numbers are unchanged. Native CLI timings
include process startup/exit. This does not turn bridge byte counters into
physical-device I/O measurements.
