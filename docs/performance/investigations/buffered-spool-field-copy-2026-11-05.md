## Buffered spool field copy (2026-11-05)

Decision: adopt the behavior-preserving short-field copy in default packed spool
reads. The predeclared primary rule passes: both opposite-order elapsed and total
process-CPU pairs favor the candidate, and primary median elapsed reduction exceeds
2%. This closes the bounded decoder-copy study; it does not reopen the rejected
SIMD or empty-grant studies. Code disposition and actual delivery are separate:
the fast path is in this delivery branch's default build; exact final-head local
receipts and the guarded landing handoff establish delivery to origin/main.

[Report and retained raw identities](../../evidence-originals.md#sha256-82be73319e0ea955d51f0de6e9a9cd1b948b1b05ed00f1c16645dde76b127577),
[exact patch](../../benchmarks/buffered-field-copy-2026-11-05.patch),
[native harness](../../benchmarks/buffered-field-copy-2026-11-05-native.py),
[independent verifier](../../benchmarks/buffered-field-copy-2026-11-05-verify.py),
[baseline reuse attestation](../../evidence-originals.md#sha256-32f1ae23caeac8de6ebe65a2e3d0fdb0bafe637481b4c70e10486fef5626afce)
and [frozen renewed plan](../../evidence-originals.md#sha256-f30b9452b6bdf40d4ba49110a625ee202a484b861e1ee8057ef336c0380f48aa)
pin the evidence and replay requirements. The existing
[CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py) is byte-identical
to the retained self-control. Private absolute paths in the plan identify this
host's retained inputs; unavailable original bytes are a replay limitation, not
permission to substitute a nearby build or fixture.

The production baseline is `80894c6f0ba13ce1fa940e87002a97450b0dff06`; the measured
candidate is `d8243783bf723b86f5fe9483d40198e9876aa412`. The original inline-key
native binary is reused only after rechecking its complete original build-status
inputs, executable, Cargo, rustc, environment and CPU-helper control. All 330
compilation, complete vendored and embedded-asset inputs exactly match the current
baseline and candidate source trees respectively. No earlier timings are reused.
The report retains both source maps, executable hashes, MSVC/tool/runtime identities,
actual hardware/NTFS context and original source/fixture/harness/plan/runner hashes.

The one-million-row plain probe-v1 fixture and fixed `strict-csv-serial-v1` seed
are unchanged. Primary jobs perform region partition, probabilistic 80/20/0
allocation and uniform child shuffle. Each uses four workers, 32 MiB job and shared
limits, a 1 MiB record cap, 1 GiB temporary-byte cap, 4096 files, one-million-row
and 128 MiB serialized CSV output caps. Seed/algorithm/plan, fixture identity and
per-job configuration remain explicit in the report and retained raw jobs.

Native Windows complete-Run elapsed time starts at CLI launch and ends after
publication, Analysis JSON and process exit. Fixture hashing, independent
verification and the post-exit CPU query are excluded. CPU is Win32 process user
plus kernel time across all child threads. Storage is the recorded C: NTFS volume;
cache and background activity are uncontrolled. No own builds overlap timing.

| Primary ABBA index | Variant | Complete-Run seconds | Total process CPU seconds |
| --- | --- | ---: | ---: |
| 0 | baseline | 2.873713 | 2.546875 |
| 1 | candidate | 2.791501 | 2.328125 |
| 2 | candidate | 2.684940 | 2.296875 |
| 3 | baseline | 2.797557 | 2.531250 |

There are two observations per variant in this matched primary cell. Baseline
elapsed median is 2.835635 s (range 2.797557..2.873713); candidate median is
2.738220 s (2.684940..2.791501). Reduction is `(baseline - candidate) / baseline`:
3.44% elapsed and 8.92% total process CPU. Opposite-order candidate-minus-baseline
elapsed differences are -0.082212 and -0.112617 s; CPU differences are -0.218750
and -0.234375 s. Exact values remain in the report. These are development samples,
not a general device, shape, scale or tail claim, and not additive to earlier gains.

The separate unreplicated ordered control is 0.418503/0.387387 s elapsed and
0.406250/0.359375 s total CPU for baseline/candidate. It does not exercise packed
decoding and also favors the candidate, showing uncontrolled variation. Do not
pool it, subtract it from the primary cell or claim an ordered-export improvement.
The primary CPU difference is in kernel time: user time is flat in one pair and
slightly worse in the other. Total CPU does not establish function attribution or
prove that removed zero-fill caused the entire observed effect.

The implementation appends a complete nonempty field smaller than the existing
64 KiB read-buffer bound directly from `fill_buf` when already available, then
consumes precisely that field length and performs the unchanged strict UTF-8
validation. Destination capacity is already admitted. Empty, split and wide fields
retain the original resize/read_exact path. No new allocation, schema, frame,
worker, RNG, replay, retry, execution-graph or resource-policy change is introduced.
Returned rows own their copied bytes. Header/key/grant destruction ordering stays
unchanged; this remains subject to the
[packed-field constructor and ownership contract](../../resource-policy-research.md#validated-packed-field-traversal-2026-11-05).

Six jobs independently verify exact fields, unique IDs, group membership, row and
serialized-byte caps, ordered input equality, all CSV/output records and seventeen
logical Analysis fields per recipe. They also check temporary/staging cleanup.
The focused regression covers five read-buffer capacities across success, invalid
UTF-8 and truncation, including cursor position, ownership after reader drop and
failure-charge release. The recorded measured-head Linux and native Windows local
workflows pass; final changed commits/base require fresh gate receipts. Linux
browser/WASI checks establish only their recorded correctness scope. Native macOS
is deferred; hosted Actions are not dispatched.

All five native runner steps pass. The report retains every raw file's original
identity, all failed preparation attempts and logs. The first patch comparison
failed because its diff context differed from the retained zero-context patch;
using the original serialization yields the exact original patch hash. An initial
cycle-wrapper preflight rejected a missing explicit hypothesis before any runner
attempt/build/Run. A separate v2 plan states the already-recorded hypothesis and
uses fresh batch output; no source, decision rule or resource/run cap changes.
Earlier frozen sessions/manifests and interrupted/failed workflow attempts remain
untouched. One experimental build and all six measured Runs are spent; there are
no scans, retuned samples or expanded shapes.

Normalized primary eligibility explicitly selects `/native/complete_jobs/0` and
`/native/complete_jobs/3` as baseline, `/native/complete_jobs/1` and
`/native/complete_jobs/2` as candidate, with reviewed `clock_pointer: /seconds`.
The ordered pair remains outside this binding. The existing tested
`native-complete-jobs` adapter supports this report; extraction alone is not
eligibility. Summaries repeat these observations rather than adding samples.
Analysis diagnostics are pre-final-publication logical snapshots, not complete
physical I/O. Reservations, RSS, allocations and stored traffic remain separate;
this study makes no new RSS, physical-I/O or whole-Run peak-capacity claim.
