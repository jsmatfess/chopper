## CSV marker-cache candidate not promoted (2026-11-05)

Decision: reject the unchanged marker-cache candidate and restore production
exactly. The plain primary passes the frozen wall/total-CPU/user-CPU conditions,
but the separate quote-rich negative control exceeds its 2% CPU regression limit.
The measured outcome is mixed, the disposition is rejection and delivery is
unapplied. No tuning, more repetitions or alternate source follows this result.
The small coarse control does not establish a general regression.

[Report and original raw identities](../../evidence-originals.md#sha256-f86e608f20d68a15810c224bdc02f768ac8d6b0ca1badb2237af5ee7cfac0fdd),
[retained patch](../../benchmarks/csv-marker-cache-2026-11-05.patch),
[native harness](../../benchmarks/csv-marker-cache-2026-11-05-native.py),
[independent verifier](../../benchmarks/csv-marker-cache-2026-11-05-verify.py),
[preflight](../../benchmarks/csv-marker-cache-2026-11-05-preflight.py),
[build attestation](../../evidence-originals.md#sha256-2bfc69006e35faae008d8b2596fe8e6337a2820e72f4f756d132382077755964) and
[frozen executed plan](../../evidence-originals.md#sha256-ecf219aa9489da392b9daecd9d351c78055fbd9bbafbac9f3dbf7cc6b42819f1) preserve the exact
commands, source/fixture/build identities and decision rule. These are host-layout
review copies requiring the recorded private paths and
[CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py), not a portable
standalone command. The earlier failed preflight and all original raw bytes remain
at their private locations with hashes in the report.

The named cost was repeatedly searching a buffered unread row for quote/CR/LF
at each ordinary field. Initial source
`92c4ea9af9d13c36a4b0372073b190848215c5cc` cached the first structural offset
within a record. Its existing suites passed but did not establish generic BufRead
adequacy: a reader can shrink or extend the visible unread prefix after consume.
The late finding was initially a static inference. During this continuation, the
new changing-window control independently fails that preserved source at
`structural <= data.len()`; the frozen focused test executable exits 101. The
initial Cargo wrapper's failure log is preserved separately; it did not capture
its child exit code, so a second execution of only that frozen test binary records
it explicitly. Neither execution is a benchmark or a timed engine Run.

Corrected source `be21ca7cbb1c1eb256a10d52895ab87dc1d048a5` tracks the expected
remaining extent, subtracts every direct/span/scalar consumption and invalidates
the cached offset before slicing whenever the next visible extent differs.
Quoted mode still clears the cache; CRLF's extra byte returns the record, so no
local cache survives. Coherent BufRead bytes remain the same unread prefix;
relocation alone does not change their meaning. Parser fields/layout, heap grants,
working-byte accounting, scalar CSV errors, seeds, dispatch and execution graphs
remain unchanged. The new reader controls narrow, grow and alternate windows
across owned, compact and admitted paths, dialects, invalid UTF-8/quoting,
CRLF/blank/EOF boundaries, twelve working limits and denial budgets 0..320.
Stable one-byte-reader results and literal known fields provide independent
record/error/count expectations. Retained capacities remain covered by grants.

Fresh exact-head/current-base local workflow checks pass on Linux and native
Windows before measurement. Linux includes core WASM compilation, bundled-Chromium
acceptance/resources/interruption and combined-feature checks; native Windows
executes its native profile. Earlier first-candidate passes stay historical and
do not resolve the new counterexample. No hosted Actions are dispatched and
macOS remains deferred and untested.

The concrete panel is frozen before data: 250,000 plain rows with 32 fields,
45,089,828 bytes, SHA-256
`c6ff7efd0db614d00686624f9e56a9e9b6c68f8d779555c965df1ebf3408f3d6`,
and a separate 50,000-row/32-field quote-rich fixture, 30,679,048 bytes, SHA-256
`c39bd64effb90c82d07d18f41c3532fc001b53c0691088c44bcd8e699c856b12`.
The generator fixes exact field formulas, minimal quoting, UTF-8/LF and no BOM;
rich fields contain commas, quotes, Unicode and embedded newlines. These are
development shapes, not reserved holdouts. Both use limits-only ordered complete
Run, seed `strict-csv-serial-v1`, four workers, 32-MiB job/shared limits, 1-MiB
record cap, 1-GiB temporary ceiling, 4096 files and million-row/128-MiB output caps.

The original default native baseline build from `fc235f8` is byte-for-byte
source-equivalent across all 333 compilation/vendor/embedded inputs to production
`8127c947d04cc76d97be03e8bb27379fcc87701a`. Reuse separately verifies the original
full build ledger, input hashes, executable, recorded Cargo/rustc identities and
environment; matching current dependency features are checked after the one fresh
candidate build. Historical MSVC C-compiler/linker hashes were not recorded and
remain unknown. A first preflight fails on a directory-metadata schema assumption
before any build/Run. A reviewed separate checker resolves directories from the
original root and retains exact resolved-file/hash checks; its new batch passes
all six steps. The original failed batch is unchanged.

Timing covers native CLI startup through complete Run/publication/Analysis JSON
and process exit. Hashing, independent verification and post-exit GetProcessTimes
are outside the wall clock. CPU sums all child threads; user, kernel and total
stay separate. Hardware/NTFS context is retained, caches/background are uncontrolled,
and no own builds overlap measurements. Native diagnostics do not provide a full
physical-plan trace; Analysis I/O snapshots precede final publication and are not
physical device I/O or RSS measurements.

| Primary ABBA index | Variant | Wall seconds | Total CPU seconds | User CPU seconds |
| --- | --- | ---: | ---: | ---: |
| 0 | baseline | 0.540132 | 0.375000 | 0.359375 |
| 1 | candidate | 0.492493 | 0.343750 | 0.312500 |
| 2 | candidate | 0.374520 | 0.328125 | 0.312500 |
| 3 | baseline | 0.403215 | 0.390625 | 0.343750 |

Primary n=2 per variant: baseline wall median 0.471673 s, range
0.403215..0.540132; candidate 0.433507 s, range 0.374520..0.492493.
`(baseline - candidate) / baseline` yields median reductions of 8.09% wall,
12.24% total CPU and 11.11% user CPU. Both opposite-order pairs favor the
candidate on all three metrics, and the 2% practical wall threshold passes.
Ranges overlap and the small cell does not support broad or tail claims.

The separate quote-rich pair is 0.274984/0.266495 s wall (baseline/candidate),
0.218750/0.234375 s total CPU and 0.187500/0.203125 s user CPU. Each CPU
increase is one 15.625-ms accounting tick: +7.14% total and +8.33% user, exceeding
the frozen 2% ceiling. Favorable wall time cannot override that conjunctive rule.
This unreplicated control stays separate; it is neither pooled nor subtracted.

All six complete jobs independently verify every field and unique ID, exact
order, strict row/byte caps, output inventory/bytes, seventeen logical Analysis
fields and temporary/staging cleanup. Ordered CSV exactly equals the appropriate
input fixture, and output hashes/records and logical metadata match within each
shape. The original CPU-helper self-control and interpreter hashes are rechecked.
Source attempts 2/2, experimental candidate builds 1/1 and measured native Runs
6/6 are consumed; component scans and measurement repeats are zero.

Production Rust/vendor/UI inputs are restored exactly to current main. The patch,
corrected tests, rejected source, both preflight attempts, binaries, full raw
artifacts and prior frozen studies remain intact. The final evidence-only commit
uses its applicable local gate; actual landed SHA/results are recorded in the
landing handoff after delivery, not predicted here. The original TODO objective
continues with a distinct named-cost investigation rather than reopening this one.

Reviewed comparison bindings explicitly select `/native/complete_jobs/0,3` as
primary baseline and `/native/complete_jobs/1,2` as candidate, with
`clock_pointer: /seconds`. The quote-rich `/native/complete_jobs/4,5` control has
a separate binding. Existing tested complete-job adapters retain process/user/
kernel CPU separately. Summaries, contract durations, failed preparation and
prior suite passes are not extra speed samples. Extraction does not grant
eligibility for any broader comparison.
