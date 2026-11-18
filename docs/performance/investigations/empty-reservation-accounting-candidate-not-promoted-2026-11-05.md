## Empty reservation accounting candidate not promoted (2026-11-05)

**Decision: restore production and retain the unchanged patch as unpromoted.**
The [six-job record](../../evidence-originals.md#sha256-5a1bc54de633945753a067164d501dabd87b057eecba7940f03d9c9ac01cd518), [prototype patch](../../benchmarks/zero-reservation-2026-11-05.patch)
and [native harness](../../benchmarks/zero-reservation-2026-11-05.py) investigate source-level accounting
work after the [SIMD rejection](../../performance.md#strict-spool-utf-8-simd-wrapper-rejected-2026-11-05).
The harness uses its recorded task layout and unchanged
[completed-process CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py).
This is a separate hypothesis; all earlier study caps remain closed.

The candidate skips zero-byte Reservation destructor releases and removes two
redundant empty fallback grants in packed Dataset decoders. Both ledger release
bodies perform only relaxed atomic subtraction, with no notifications/callbacks;
zero subtraction changes neither value. Arc field destruction remains intact.
Those decoder headers already carry independent grants, including inline keys;
packed decoding transfers the header owner or absorbs it into a reused row.
Debug assertions preserve that premise. Nonzero byte ownership and destruction
order, types/layouts, limits, dependencies, RNG, execution graph/retry and defaults
remain unchanged. This removes reference/count work, not admitted heap capacity.

The frozen rule requires both opposite-order elapsed/CPU pairs to favor the
candidate and at least 2% primary median elapsed benefit. Four fresh Windows
complete Runs use one million plain probe-v1 rows in ABBA order, partition(region)
-> probabilistic 80/20/0 -> uniform child shuffle. Both variants use four workers,
32-MiB job/shared limits, a 1-MiB record cap, 1-GiB temporary ceiling, fixed seed
`strict-csv-serial-v1` and strict million-row/128-MiB output caps. Elapsed includes
CLI startup through Run/publication, Analysis JSON and exit; hashes, independent
verification and post-exit CPU queries are excluded. Cache/background state is
uncontrolled; own builds finish before measurements.

| Pipeline | Observations | Median elapsed seconds | Elapsed range | Median process CPU seconds | CPU range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current inline-key baseline | 2 | 2.62315 | 2.54283–2.70348 | 2.34375 | 2.23438–2.45313 |
| Empty-work candidate | 2 | 2.59471 | 2.53275–2.65667 | 2.26563 | 2.26563–2.26563 |

Candidate-minus-baseline opposite-order elapsed differences are -0.04681 and
-0.01008 seconds; CPU differences are -0.18750 and +0.03125. Median elapsed falls
1.08%, below the predeclared practical threshold; median CPU falls 3.33%, but one
paired CPU observation regresses. That fails the rule. Overlapping ranges,
between-pair drift and coarse counters prohibit significance/tail/general gains.
The separate unreplicated ordered control has elapsed 0.36216/0.36426 and equal
0.328125-second CPU. No older timings, controls or percentage gains are pooled.
Neither component is isolated; the result does not establish that zero-work
removal is always harmful or useful. No retuning, extra shapes, repeated jobs or
promotion under a cleanup label follows.

All six jobs independently verify fields, unique IDs, groups/lineage, strict caps,
inventory and cleanup. CSV hashes, output records and 17 logical Analysis fields
match per cohort; ordered output equals the 94,776,853-byte input. Pipeline
snapshots retain 36 sort runs, eight merges and identical logical temporary
traffic. Prepublication workspace peaks are 7,461,141/7,461,150 bytes for pipeline
and 202,292/202,298 for ordered export, including differing path/name charges.
These snapshots are separate from full-Run I/O, physical traffic and RSS.

Exact measured-head local workflows pass native Windows and Linux native,
combined-feature and full browser/WASI resource/cleanup/termination checks.
Existing real reader-drop/returned-row transfer, local/shared capacity edges,
corruption and cancellation controls exercise the ownership paths. No mirror
test is added for subtraction by zero. Native experiment gates pass 5/5. The
baseline's original source/file-set, 330 file hashes, directory tokens, binary,
Cargo executable/compiler and full build environment are rechecked; maintained
source matches the base exactly. Dependency feature names match. Prior CPU
self-control reuse requires identical helper/interpreter bytes. Exact patch
replay matches the measured candidate. No experimental build/job failed or ran
again. Production Rust/manifests/vendor/embedded bytes are restored before
fresh final-head/base local delivery checks; `local-ci.py land` and its retained
receipts gate delivery. Hosted CI is not dispatched; macOS remains deferred.

Source follow-up also rules out a false serialization premise: `serialized_text_size`
is a lazy closure, called only by cold buffer growth. Steady-state rows do not
repeat quote classification through that planner. No quote-cache prototype or
new measurements were launched for that idea.

Context is Windows 11 build 26200, Ryzen 7 5800X, NTFS and Rust 1.99.1. Private
frozen sources/binaries, full outputs, plans and logs remain under
`scratch/zero-reservation-20261105T1255/` in both checkouts. One source attempt,
one experimental candidate build and six complete jobs consume this study's
measurement bounds; there are no component scans or matrix expansion.
