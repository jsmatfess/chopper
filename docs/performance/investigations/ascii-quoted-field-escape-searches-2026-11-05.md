## ASCII quoted-field escape searches (2026-11-05)

Decision: Frozen primary or separate negative-control condition fails; restore production exactly and retain unchanged source without tuning. The measured outcome is mixed,
the disposition is rejection, and the implementation
is unapplied.
Delivery still requires the exact final commit/base local gate; actual landed SHA
and results are recorded only after authorized landing. No tuning, repetitions or
shape expansion follow this panel.

[Report and original raw identities](../../evidence-originals.md#sha256-4923bae1f66493417ce3abbc88c3b54634e9873e918d25292d6ebb307e34c002),
[exact patch](../../benchmarks/ascii-quoted-escapes-2026-11-05.patch),
[native harness](../../benchmarks/ascii-quoted-escapes-2026-11-05-native.py),
[independent verifier](../../benchmarks/ascii-quoted-escapes-2026-11-05-verify.py),
[preflight](../../benchmarks/ascii-quoted-escapes-2026-11-05-preflight.py),
[build attestation](../../evidence-originals.md#sha256-bbbe49ca98051efd973844742d52fad9e7e7d9c41b1656fe6bc5c50f4fcb1331),
[fixture generator](../../benchmarks/ascii-quoted-escapes-2026-11-05-fixtures.py) and
[frozen executed plan](../../evidence-originals.md#sha256-c52cf34bd6fde7551d1e9e9c22f915736141e8da5cfa5920c0556a1c019b18b3) preserve provenance and
reviewed commands. These are private-host-layout review copies, not a portable
standalone command. The
[CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py) is reused only
with its exact original control and interpreter identities. All raw bytes,
unexecuted planning versions and previous study failures remain at their private
locations; missing originals limit replay.

The named remaining serializer cost is searching quoted spans with
`match_indices([quote, escape])`. The locally pinned Rust 1.99.1 source implements
this character-array pattern using CharIndices and per-scalar matching. Its
source hash and a retained source copy identify that observation; compiler
optimization can change instructions, so it is a hypothesis, not function-level
CPU attribution. Earlier span-copy evidence motivates the question without
predicting this candidate's gain.

Candidate `2beebb2092f4a8746c378b7e1dd99011c9b7d6ad` on base `98a8462d2795092585e982e078d79f414e53b385` uses existing `memchr2_iter` only when both
quote and effective escape are ASCII. An ASCII match cannot be a UTF-8
continuation byte, so both slice endpoints are valid. Each match is emitted once,
including equal needles, through the same ordinary-span, escape-prefix and
matched-character target calls. Non-ASCII quote or escape retains the exact old
character matcher. Planned sizing, incremental growth/callback sequence, retained
capacity/overlap, UTF-16 transcoding, error placement, Parser/cache state, seeds,
dispatch, heap ownership/layout and execution graphs are unchanged.

Independent scalar reference tests cover equal/custom/ASCII/mixed-Unicode
quote/escape settings, LF/CRLF, UTF-8/UTF-16LE/BE, every short prefix alignment,
255/256 and 4096 neighbors, Unicode spans, larger-buffer reuse and denied
admission budgets 0..1024 with exact retry. Existing literal controls remain.
Fresh exact-head/current-base Linux and native Windows workflow gates pass before
measurement, including actual Linux core-WASM/browser/resource/combined-feature
checks. These checks are correctness coverage; macOS and browser throughput are
not claimed. No hosted Actions are dispatched.

The first one-million-row suggestion remained unexecuted planning intent. Before
any experimental build or timing, a reviewed concrete panel fixes four million
rows per narrow three-field shape because observed 15.625-ms CPU increments are
large relative to a 2% ceiling on shorter controls. No size sweep or postdata
selection occurs. The Python CSV generator is independent of Chopper. Each first
million-row prefix exactly reproduces its earlier fixture hash. Full plain input
is 385,777,325 bytes, SHA-256
`876a1e8eef46cfd53f4b5667841327fae3f6a6d0e3b2c19b505c9b593edd2b74`;
quoted input is 489,777,325 bytes, SHA-256
`3a3c129b61e6cdf2f5379a7ffbe83cb8bc976cbbf3c81c79c1f3d99dcd251a7f`.
IDs, four region values, variable ASCII notes, commas, Unicode, doubled quotes
and embedded CRLF are deterministic development data, not reserved holdouts.

Four quoted ordered Runs use ABBA; two plain ordered Runs are a separate negative
control. Both retain seed `strict-csv-serial-v1`, four workers, 32-MiB job/shared
limits, 1-MiB record cap, 1-GiB temporary ceiling, 4096 files and strict
four-million-row/512-MiB output caps. Original default baseline build `fc235f8`
has exactly the 333 current production compilation/vendor/embedded inputs.
Source equivalence alone does not grant reuse: original ledger/input/artifact,
recorded Cargo/rustc/environment and actual old/current resolved dependency
features are explicitly rechecked before the first Run. Historical independent
MSVC C-compiler/linker hashes remain unknown. One fresh default candidate build
and all six runner steps pass; no feature/backend/target-CPU flag changes occur.

Timing includes native CLI startup through complete Run/publication/Analysis JSON
and process exit; fixture/hash/independent verification and post-exit process CPU
queries are excluded. CPU sums all child threads, with user/kernel/total separate.
Fresh hardware/NTFS context is retained, cache/background are uncontrolled and no
own builds overlap timing. Returned Analysis diagnostics precede final publication
and are not full-Run physical I/O, RSS or simultaneous capacity peaks.

| Quoted ABBA index | Variant | Wall seconds | Total CPU seconds | User CPU seconds |
| --- | --- | ---: | ---: | ---: |
| 0 | baseline | 2.404931 | 2.125000 | 1.843750 |
| 1 | candidate | 1.977960 | 1.734375 | 1.328125 |
| 2 | candidate | 1.846451 | 1.703125 | 1.359375 |
| 3 | baseline | 2.236763 | 2.140625 | 1.734375 |

Primary n=2 per variant: baseline wall median 2.320847 s, range
2.236763..2.404931; candidate 1.912206 s, range
1.846451..1.977960. `(baseline - candidate) / baseline` yields
17.61% wall, 19.41% total CPU and
24.89% user CPU median reductions. Frozen primary rule:
both opposite-order wall/total/user pairs favorable and at least 2% median wall
reduction. Actual primary result: pass.

Separate plain baseline/candidate wall is 1.344055/1.306315 s,
total CPU 1.203125/1.203125 s and
user CPU 0.859375/0.953125 s.
Candidate-minus-baseline relative changes are seconds: -2.81%, total_seconds: +0.00%, user_seconds: +10.91%. Its frozen ceiling
is no more than 2% regression on each wall/total/user metric; actual result:
fail. Kernel CPU falls from 0.343750 to 0.250000 s, so the flat total masks a
user/kernel redistribution; these counters do not attribute the difference to
the changed function. The frozen conjunctive rule still fails.
This unreplicated control stays separate and is
never pooled, subtracted or counted as a primary sample. Small cells and warm
uncontrolled variation do not establish a general speed/regression or tail claim.

Every complete job independently verifies all fields and unique IDs, exact order,
strict row/byte caps, inventory, raw output bytes, seventeen logical Analysis
fields and temporary/staging cleanup. Ordered output exactly equals its full
fixture, and per-shape output hashes/records/logical metadata match across variants
and repetitions. Source attempts 1/2, candidate builds 1/1 and measured native Runs
6/6 are consumed; component scans and measurement repeats are zero. Unused source
capacity does not authorize retuning after this decision. Prior marker-cache and
digest studies remain closed with their own unchanged counters and artifacts.

Final source is restored exactly to the production base;
the local delivery gate must validate the exact final commit/current main base.
The landing handoff records actual SHA/results and limitations after delivery.
The original TODO objective continues within the same 20:33:04 UTC deadline and
20:13:04 UTC measurement cutoff; starting this study did not renew time.

Reviewed bindings explicitly select `/native/complete_jobs/0,3` baseline and
`/native/complete_jobs/1,2` candidate for quoted primary, with
`clock_pointer: /seconds`. Plain `/native/complete_jobs/4,5` has a separate binding.
Existing tested complete-job adapters retain user/kernel/total CPU separately;
extraction does not create eligibility for broader comparisons. Derived summaries,
contract durations and prior observations are not extra samples.
