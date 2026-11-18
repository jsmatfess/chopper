## Probabilistic shuffle fusion: external-wide owner acceptance (2026-11-05)

**Decision: retain the unchanged prepared-spill owner after one fixed external-wide
acceptance point; no promotion or timing inference.** The
[four-job record](../../evidence-originals.md#sha256-323acadca34ea8076365a8098d2b541d5d4e4c7d2b0c5792fae290321189675d)
and [test-only extension](../../benchmarks/probabilistic-shuffle-external-wide-2026-11-05.patch)
cover a distinct path from the earlier resident-wide point and the
[narrow new-owner cost panel](../../performance.md#probabilistic-shuffle-fusion-prepared-spill-working-set-cost-2026-11-05).
Production, execution graph/retry integration, defaults and Auto stay unchanged.

The case fixes 16,384 unique ASCII records with a 4,096-byte payload base plus
`id % 97` and note/id prefix, four regions, probabilistic 80/20/0 groups and
uniform shuffle. It keeps the original seed, 32-MiB job/shared pool, one worker,
Auto grouping and 1,024-row/65,536-byte caps, with no peer. Linux runs baseline
then candidate; native Windows repeats exactly that pair after Linux gates pass.
No size/capacity/repetition expansion follows the result.

All four jobs produce 1,100 CSV files totaling 68,236,544 bytes. Independent
actual-byte fields, unique IDs, group count and cap checks pass before computing
canonical per-file BLAKE3 hashes. Those hashes, ordered output records and 17
logical Analysis fields match within each runtime and in one predeclared combined
fingerprint across all four jobs. The raw record retains that fingerprint and the
native verifier's frozen Linux reference input. This is exact CSV-hash parity,
not a retained literal Vec comparison of every CSV byte. Every job visits input
once, cleans owned temporary/private staging data and releases its pool to zero.

Both variants spill and merge. Each runtime records eight baseline versus twelve
candidate spill runs and four merges each. Complete logical temporary reads are
404,182,412 versus 280,548,002 bytes and writes 400,133,145 versus 276,680,777 bytes;
files created are 26 versus 24, baseline versus candidate. The candidate trades
more spill runs for fewer materialized passes/files. These are complete Context
logical counters after publication, not physical I/O or speed. Diagnostic sort
clocks remain raw and excluded; fixture/verifier heaps sit outside the working
ledger, which is not an RSS cap.

Only the excluded private research module changes. A caller-local wide mode
preserves ordinary payload/byte-map behavior when disabled and hashes verified
wide CSVs to avoid inflating raw byte arrays into large JSON heaps. Runtime/core/
storage/vendor/embedded bytes match the accepted owner source. Fresh Linux
formatting/all-target Clippy and the new focused pair pass; previous full default
workspace coverage applies only to that unchanged relevant runtime. Native MSVC
release pair/verifier, all 326 declared input hashes and exact appended-patch
replay pass. No new full workspace/browser or feature-combination claim follows.

Full source, native binary, frozen plans, reference, fingerprints and logs remain
under private `scratch/prob-shuffle-external-wide-20261105T0440/` in both checkouts;
no archive upload is claimed. The owner still adds live/unused files and may deny
earlier. Broader pressure/temp failures and changed-owner browser acceptance
remain separate; this single no-peer external-wide point is not universal width
or admission coverage.
