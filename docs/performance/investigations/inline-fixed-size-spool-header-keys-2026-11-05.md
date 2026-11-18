## Inline fixed-size spool header keys (2026-11-05)

**Decision: keep common spool keys inline during decode; deliver scoped favorable
native evidence with the unchanged framing and ownership contracts.** The
[six-job record](../../evidence-originals.md#sha256-f079c32bf3ccec894dbd1658cddaaf25f0c3812f3ead6388c16531f716256bbf), [implementation patch](../../benchmarks/inline-spool-key-2026-11-05.patch)
and [native harness](../../benchmarks/inline-spool-key-2026-11-05.py) compare against `800f6cd`, whose engine
matches the [CPU attribution source](../../performance.md#current-complete-run-user-cpu-attribution-2026-11-05).
The harness requires its recorded task layout/fixtures/binaries and the unchanged
[completed-process CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py)
beside it. No execution graph/retry, worker, schema, algorithm, default or Auto
policy changes follow.

Previously, each spool header allocated/admitted a Vec, including common 16-byte
random keys; compact decoding then moved those bytes into an existing inline
PackedKey. Private FrameKey now reads eight/sixteen-byte keys into inline arrays.
Other lengths retain their original Vec capacity and late-boxing overlap. All
comparisons and serialized spool bytes remain exact, including arbitrary binary
keys and collision refinement. This removes transient key allocation/grant work,
not strict field UTF-8 validation or any required stage.

RowHeader now declares key storage before its grant. Owned/compact decoders move
keys into locals declared after the aggregate grant before fallible field work.
Inline-to-owned Vec conversion pre-admits requested/actual capacity; returned
DecodedRow/PackedRow owners retain their grants. Merge Head metadata increases
with the enum layout, and requested/actual heap capacity remains charged using
the target's actual `size_of::<Head>()`. Variable-key boxing still includes old/new
overlap. [Owner contract](../../resource-policy-research.md#fixed-size-spool-header-keys-2026-11-05)
records the audit; no complete stack/runtime/RSS bound follows.

Four fresh native Windows complete CLI jobs use one million ordinary probe-v1
records in baseline/candidate/candidate/baseline order: partition(region) ->
probabilistic 80/20/0 allocation -> uniform child shuffle. Both variants use four
workers, 32-MiB job/shared limits, a 1-MiB record limit, 1-GiB temporary ceiling,
fixed seed `strict-csv-serial-v1`, and strict million-row/128-MiB output caps.
Fixture copying/hashing warms data; cache/background state is uncontrolled.
Wall time covers CLI startup through Run/publication, Analysis JSON and exit;
fixture hashes, independent verification and post-exit CPU queries are excluded.

| Pipeline | Observations | Median elapsed seconds | Elapsed range | Median process CPU seconds | CPU range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vec header | 2 | 2.82060 | 2.74450–2.89669 | 2.53906 | 2.46875–2.60938 |
| Inline fixed keys | 2 | 2.68005 | 2.59878–2.76131 | 2.37500 | 2.34375–2.40625 |

Candidate-minus-baseline opposite-order elapsed differences are -0.13539 and
-0.14572 seconds; process CPU differences are -0.203125 and -0.125000 seconds.
Relative to baseline medians, elapsed falls 4.98% and process CPU 6.46%. Both
pairs favor the candidate, but elapsed ranges overlap with between-pair drift.
Two observations per variant and coarse process counters establish no tails,
statistical significance, universal threshold or general shape/device benefit.
The separate unreplicated ordered control pair has elapsed 0.36664/0.35688 and
process CPU 0.328125/0.343750 seconds; it does not establish an improvement.
No historical timings or earlier percentage gains are pooled.

All six jobs independently verify fields, unique IDs, group/lineage, strict caps,
inventory and cleanup. Per-cohort CSV hash maps, output records and 17 logical
Analysis fields match exactly; ordered output equals the 94,776,853-byte input.
Pipeline snapshots retain 36 sort runs, eight merges and identical logical
traffic (861,665,334 written / 767,245,241 read bytes). Reported prepublication
workspace peaks are 7,461,141/7,461,150 bytes for the pipeline and
202,292/202,298 for ordered export; variant path/name charges differ. These
snapshots neither show a lower complete-Run peak nor measure physical I/O/RSS.

Premeasurement exact-head local workflows pass native Windows and Linux native,
combined features and browser acceptance, including WASI resource, cleanup and
termination checks. New controls cover zero-heap fixed headers, exact frame/owned
round trips, every fixed-key truncation point, owned-copy exact/adjacent admission
edges, payload truncation/invalid UTF-8 cleanup, and eight-byte packed ownership.
Existing 17/4000-byte keys, 113-byte boxing overlap, wide rows, shared pressure and
collision controls remain passing. The first semantic attempt failed Clippy on
two unnecessary conversions in ordinary Row test fixtures; a narrow new commit
fixes them. Its failed Windows and interrupted superseded Linux workflow logs
remain intact. A separate read-only baseline proof initially guessed the wrong
unused example filename; the corrected proof verifies all 329 maintained files
and the actual unused core serial-parser example. No measured job was repeated.

The native experiment batch passes 5/5 gates. The reused baseline's original
330 file hashes, 81 directory tokens, full source file-set, binary, Cargo executable,
compiler and complete build environment are rechecked. All maintained native
candidate/vendor/embedded bytes match the reviewed delivery sources, and exact
patch replay passes. The previously passed CPU helper control is reused only
with identical helper/interpreter bytes; it is not a fresh observation. Fresh
final-head/base local Windows validation and guarded `local-ci.py land` remain
the delivery gate; receipts retain their actual results. Hosted CI is not
dispatched; macOS is deferred rather than claimed tested.

Context is Windows 11 build 26200, Ryzen 7 5800X (8 cores/16 logical CPUs), NTFS
and Rust 1.99.1. Private frozen sources/binaries, outputs, plans, failed attempts
and full logs remain under `scratch/inline-spool-key-20261105T1200/` in both
checkouts. The one-experimental-candidate-build/six-Run caps are consumed, without
component scans, measurement retries, retuning or matrix expansion. Native stack
and descriptor costs, non-fixed keys, other shapes/encodings and browser speed
need their own evidence; this is no general admission-domain expansion claim.
