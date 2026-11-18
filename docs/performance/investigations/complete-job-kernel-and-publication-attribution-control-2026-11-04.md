## Complete-job kernel and publication attribution control (2026-11-04)

**Decision: investigate prepared publication before adding parser/hash workers
for this narrow probe.** The
[six diagnostic jobs](../../benchmarks/whole-job-cost-attribution-2026-11-04.json) and
[isolated instrumentation](../../benchmarks/whole-job-cost-attribution-2026-11-04.patch)
locate selected costs after the external-working-set comparison. This is partial
wall attribution, not a CPU profile, speed comparison or general rejection of
concurrency. Production and execution graph work remain unchanged.

The fixed 200,000-row ASCII probe runs ordered export and the storage-revised
partition/allocation/shuffle recipe with the same 32-MiB job/shared budget, one
worker, seed and 1,024-row/65,536-byte caps. Each recipe first runs with clocks
disabled, then enabled. Exact CSV/output-record/17-field Analysis parity within
recipe and independent fields/IDs/groups/caps/cleanup pass. Disabled counters
stay zero. These are explicit Prepare plus Execute jobs; direct Run, browser
export, compression and other record shapes are separate questions.

Selected enabled aggregate wall milliseconds, one observation per recipe:

| Scope | Ordered export | Revised fusion |
| --- | ---: | ---: |
| Parser, including reads/validation/admission | 38.641 | 49.748 |
| Decoder, nested in parser | 10.502 | 13.160 |
| Logical digest updates/finalization | 20.174 | 19.646 |
| Random block, potentially nested in categorical | 0 | 41.245 |
| Categorical membership, including draws | 0 | 47.081 |
| Reserved CSV serialization | 20.416 | 26.128 |

Do not add nested scopes. Each parser makes 200,002 calls, digest 200,001,
decoder 2,295 and serializer 200,001; fusion also makes 400,000 random-block and
200,000 categorical calls. These include wall waits and some admission work,
and omit other key encoding, allocation, storage and OS costs. Empty-span
calibration executes 100,000 guards in 0.0057884 seconds, with 0.0026278 seconds
inside the spans. It contextualizes overhead rather than providing a rigorous
bound or a correction to subtract. Per-call clocks and atomics perturb work;
off/on elapsed differences are not performance samples.

Analysis labels ingestion as `ingest_and_fused_operations`, so it cannot identify
parser CPU. The first controls also left the prepare/execute boundary unmeasured.
A separately reviewed two-job follow-up preserves identical core instrumentation
and adds explicit boundary clocks. Each job repeats independent correctness and
cleanup; it is not another speed comparison:

| Instrumented recipe | Preparation seconds | Execute/publication seconds |
| --- | ---: | ---: |
| Ordered export | 0.098245 | 0.749118 |
| Revised fusion | 0.614628 | 0.820955 |

This establishes a substantial prepared-publication interval, without attributing
its CPU versus filesystem costs. Serialization spans cover only one small part
of output work. The next useful question concerns snapshot reads, staging writes,
file lifecycle and final publication; these observations do not justify more
parser workers or compression overlap by themselves. Other shapes may differ.

Native Windows/MSVC Rust 1.99.1 runs on Windows 11 build 26200, Ryzen 7 5800X,
16 logical CPUs, with warm/uncontrolled cache and background programs retained.
No per-job CPU/RSS or physical I/O claim follows. Both fresh native snapshots have
complete Linux/Windows source/vendor/embedded-asset identity checks. New Linux
formatting, all-target Clippy and locked workspace tests pass on the original
instrumented source; the follow-up changes only its test helper. Follow-up
formatting and portable-core WASM checks pass. Exact patch replay passes.
All six jobs release their pools and clean owned temporary/private staging files.
Full plans, reviews, binaries, identities and logs remain under private
`scratch/performance-attribution-20261104T0003/` in both checkouts. No archive
upload, default change, browser acceptance or production promotion is claimed.
