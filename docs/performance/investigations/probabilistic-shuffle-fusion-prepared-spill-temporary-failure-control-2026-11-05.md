## Probabilistic shuffle fusion: prepared spill temporary failure control (2026-11-05)

**Decision: retain scoped spill-write failure cleanup and fixed temporary-budget
acceptance; no promotion or timing inference.** The [six-job/four-denial record](../../evidence-originals.md#sha256-a8cc0819aea3ce7d2758fe52275d0f24bf5cf99d3e8017614399bac97e36a1ee)
and [appended test controls](../../benchmarks/probabilistic-shuffle-spill-temp-failure-2026-11-05.patch)
check the changed [real prepared owner](../../performance.md#probabilistic-shuffle-fusion-prepared-spill-owner-control-2026-11-05)
after the [browser lifetime acceptance](../../performance.md#probabilistic-shuffle-fusion-prepared-spill-browser-acceptance-2026-11-05).
No production, execution graph/retry, default or Auto changes follow.

Two focused storage cases per runtime construct the actual alternate Sorter and
its prepared file/buffer owner, retain a 128-KiB row and force the first spill.
A one-byte temporary budget denies before writing any file bytes; a 65,536-byte
budget writes the frame prefix before denying the larger packed payload. Both
return the existing `temporary-space budget exhausted` error with one recorded
spill run. The failed writer removes its file and charged bytes; dropping the
Sorter returns memory grants to the still-live Context baseline, then dropping
the Context removes its job directory and releases the shared pool to zero.
The prefix counter records cumulative actual file bytes written before cleanup,
not bytes still live after the error. These are real owner/write-error primitives,
not whole-job failure injection or an OS device-fault simulation.

Each runtime then runs the fixed 200,000-record probe-v1 pipeline: four regions,
probabilistic 80/20/0 allocation followed by uniform shuffle, the original seed,
32-MiB job/shared memory, one worker, Auto grouping and 1,024-row/65,536-byte caps.
Exactly one baseline with a 256-MiB temporary budget supplies a fresh exact
reference, followed by baseline and candidate at a fixed 64-MiB budget. All six
jobs succeed, independently conserve fields/IDs/group counts/caps, and match raw
CSV bytes, output records and 17 logical Analysis fields within runtime. One
canonical BLAKE3 fingerprint also matches across Linux and native Windows.
Input is visited once, owned temporary/private staging data is removed and every
pool returns to zero. The candidate constructs the real prepared owner for all
four parents; no whole-job denial or wider completion domain is established.

At the constrained point, complete Context temporary-byte peaks match across
runtimes: 65,018,227 bytes for baseline and 58,299,366 for candidate. This is a
6,718,861-byte reduction in charged temporary ownership, not a total filesystem
peak: private/public output overlap, RSS and physical I/O remain separate.
There are no elapsed comparisons and no added budget points or repetitions.

Both source changes append only test code to the accepted private snapshot;
every prior source byte remains an exact prefix. Fresh Linux formatting,
all-target Clippy, write-error primitives, three jobs and verifier pass 5/5 gates.
Native MSVC release primitives/jobs/verifier pass 4/4 gates with all frozen source
hashes matching and exact appended-patch replay. Earlier full workspace coverage
applies only to the unchanged runtime; no new general workspace, browser, codec
feature or arbitrary shared-pressure claim is made. All finite job/build caps are
consumed without a failed attempt. Full sources, native binary, frozen plans,
references and logs remain under private
`scratch/prob-spill-temp-failure-20261105T0610/` in both checkouts; no upload or
deployment is claimed. Fixture/verifier heaps sit outside the working ledger.
