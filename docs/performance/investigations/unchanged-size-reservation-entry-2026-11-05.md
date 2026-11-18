## Unchanged-size reservation entry (2026-11-05)

Decision: Frozen primary and whole-Run transfer conditions pass; retain the inline entry with every original call/grant/drop and changed-size body preserved. Measured outcome is favorable, disposition
is adopt, and delivery is included in default builds by this change.
The exact final commit/current main base still requires the authorized local gate;
actual landing SHA/results are recorded separately after delivery. No tuning,
repeated measurements or source variant follows this decision.

[Report and original raw identities](../../evidence-originals.md#sha256-1d560523bf3055be05821b0af73c73f47ddefe10e0abde1b57abb3b6e1ae68b7),
[exact patch](../../benchmarks/reservation-entry-2026-11-05.patch),
[native panel](../../benchmarks/reservation-entry-2026-11-05-native.py),
[independent verifier](../../benchmarks/reservation-entry-2026-11-05-verify.py),
[preflight](../../evidence-originals.md#sha256-5e2a118e47d9df0b0405642aecd0e9ab3a0fdde068ae2ad3098ff2cfe8a5e014),
[matched build attestation](../../evidence-originals.md#sha256-b7856e561e7e6afd43be1402d45ad2e083bec79846f57aba80e9e4aa03d46f4d),
[frozen plan](../../evidence-originals.md#sha256-6771990183361f8e67cd26bf9b126a2c003472a6bbda96068b05ddc76fa70e41),
[native host-lock wrapper](../../benchmarks/reservation-entry-2026-11-05-native-lock.py) and
[Linux host-lock wrapper](../../evidence-originals.md#sha256-b098c1f8d4688cedc10cdbf1ddc89eefb6d1ab9e0f24779406b484de66948bbd) preserve reviewed
commands/provenance. These are retained private-host-layout review copies, not a
standalone portable command. The
[CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py) reuses its
original exact control/interpreter identities. All old source, binaries, plans,
raw data, failed setup and superseded attempts remain intact.

The named cost came from current-production WSL sampling and static code review:
resize self periods were 4.47% pipeline and 1.82% ordered, while its pinned old
Linux ELF set up six registers/40 stack bytes before checking unchanged size.
Neither observation predicts a Windows gain or isolates the share of equal calls.
Candidate `1d100fbea6015306d99244c947bd1a24952a3d8d` on base `5de660799b42c5e4129bb05843fd5127a808bc52` adds a tiny inline wrapper retaining the
original usize-to-u64 cast and equality return, then calls a private non-inlined
changed-size helper. That helper's entire original acquisition, local rollback,
shared pressure, peak, release and final assignment body is byte-identical.
All reservation objects, zero/nonzero calls, grants and drops remain. No layout,
heap, cancellation, policy, seeded/replay, allocation or graph behavior changes.
This differs from the rejected empty-grant/object/drop removal, which stays closed.

The existing resource/pressure/transaction/cleanup suites cover the unchanged
contracts; no implementation-mirroring test was added. Fresh exact-head/current-base
Linux native/features/browser and native Windows workflow passes precede the
experiment. Earlier c93d754/8107 passes remain historical after main advanced.
The wrong-root commit/check attempt found nothing staged and no local-ci.py;
Python exited2 before any build/test. The initially mistaken dirty-guard
interpretation and its explicit correction are both retained, with raw logs.
Parent-owned config/CLI and host-lock changes are imported without authored overlap.
They invalidate the old baseline binary, so one separately reviewed fresh current
baseline build is necessary. All committed compilation/vendor/embedded inputs,
recorded compiler/environment/dependency features and both binaries are pinned.
Unrecorded backend details remain unknown; no old binary is relabeled current.

Native and Linux accepted host locks exclude concurrent check/land while the
existing experiment cycle runs. The Linux wrapper verifies actual remote main,
clean matching head and lock-module identity before dispatch. The native wrapper
acquires its own tested OS lock before the cycle. Both fail closed; no raw act,
lock deletion or check bypass occurs. The documented persistent-shell delivery
flock also protects native handoff/validation/delivery. Parent CI-container
interference remains tooling evidence, not an inferred source or OOM failure.

The fixed panel reuses the plain million-row probe fixture (94,776,853 bytes,
SHA-256 `37bb8e696a4aa01df8452adcc1b4fb14c11bec1f8064b4575152a62be738e1ae`)
and plain four-million-row fixture (385,777,325 bytes, SHA-256
`876a1e8eef46cfd53f4b5667841327fae3f6a6d0e3b2c19b505c9b593edd2b74`).
Pipeline is region partition -> probabilistic80/20/0 allocation -> uniform child
shuffle, orderedABBA4 primary. Ordered4M export is a separate transfer pair; both
recipes call resize, so it is not a completely bypassed negative control.
Seed is `strict-csv-serial-v1`, four workers, 32-MiB job/shared limits, 1-MiB record
cap, 1-GiB temporary ceiling and 4096 files. Pipeline row/byte caps are1M/128MiB;
transfer caps4M/512MiB. No new fixture/holdout/shape/seed or matrix is introduced.

Timing covers native CLI startup through complete Run/publication/Analysis JSON
and process exit. Fixture/hash/independent verification and post-exit Win32 CPU
queries are outside the wall clock. CPU sums all child threads, with total/user/
kernel separate. Fresh hardware/NTFS context is retained, caches/background are
uncontrolled and no own competing builds overlap timing. Analysis diagnostics
precede final publication; they are not full-Run physicalI/O, RSS or capacity peaks.

| Pipeline ABBA index | Variant | Wall seconds | Total CPU seconds | User CPU seconds |
| --- | --- | ---: | ---: | ---: |
| 0 | baseline | 2.666550 | 2.328125 | 1.828125 |
| 1 | candidate | 2.576795 | 2.250000 | 1.656250 |
| 2 | candidate | 2.444072 | 2.156250 | 1.453125 |
| 3 | baseline | 2.470135 | 2.390625 | 1.828125 |

Primary n=2 per variant: baseline wall median 2.568343s, range
2.470135..2.666550; candidate 2.510433s, range
2.444072..2.576795. `(baseline - candidate) / baseline` yields median
reductions 2.25% wall, 6.62%
total CPU and 14.96% user CPU. The predeclared
primary requires both opposite-order wall/total/user pairs favorable and>=2%
median wall reduction. Actual primary result: pass.

Ordered transfer baseline/candidate is 1.427370/1.269619s
wall, 1.234375/1.156250s total CPU,
0.875000/0.921875s user CPU and
0.359375/0.234375s kernel CPU.
Its candidate-minus-baseline wall/total changes are -11.05% and
-6.33%; the frozen ceiling is no more than2% regression
on either. Actual transfer result: pass. User/kernel
components are diagnostics, not this cell's falsifiers; no component
nonregression is implied. This metric choice was explicit before data for this
distinct generic codegen/whole-Run transfer question. It does not relax or rerun
previous frozen user-control rejections. No cells are pooled or subtracted.

All seven runner steps and six complete jobs pass independent field/unique-ID/
group/order/cap/inventory/byte/17-logical-Analysis/cleanup verification. Exact seeded
CSV/output records/logical metadata match within each recipe across variants and
repetitions; ordered CSV equals its full input. Small cells, uncontrolled cache/
background and finite CPU accounting do not establish general or tail performance.
Source attempts1/2, necessary fresh baseline builds1, experimental candidate
builds1/1 and measured native Runs6/6 are spent; component scans and repeats are0.
Unused source capacity cannot reopen this decision.

Final source retains the reviewed seven-line codegen split.
Actual final-head/current-base local validation and landed SHA are recorded after
required delivery. No wizard runtime, Auto/default-policy, release/deployment or
manual hosted-CI dispatch follows from this performance result. Correctness and
performance coverage remain the recorded runtimes/builds; browser throughput and
matching-head macOS execution are not inferred.

Reviewed normalized bindings select `/native/complete_jobs/0,3` baseline and
`/native/complete_jobs/1,2` candidate, with `clock_pointer: /seconds`. Transfer4/5
has its own binding. Tested complete-job adapters keep wall/process/user/kernel
metrics separate; extraction does not establish broader eligibility. Summaries,
contract durations and diagnostic profiles are not extra speed samples.
