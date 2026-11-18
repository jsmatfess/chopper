## Probabilistic shuffle fusion: wide-record acceptance control (2026-11-05)

**Decision: retain the unchanged available-buffer candidate after one successful
resident wide-row acceptance point; no promotion.** The
[four-job record](../../evidence-originals.md#sha256-1649401a7fa6e7c1096e72f88f47b4f30381ca410e31cee62c0641f5d0d8c6b8) and
[appended test-only control](../../benchmarks/probabilistic-shuffle-wide-2026-11-05.patch)
address a named gap in the
[storage revision](../../performance.md#probabilistic-shuffle-fusion-available-buffer-storage-control-2026-11-03).
The prior [external working-set comparison](../../performance.md#probabilistic-shuffle-fusion-native-external-working-set-comparison-2026-11-03)
provides scoped benefit beyond existing Auto/Sort; this check adds no timing
comparison or broader performance inference.

The frozen case has 4,096 unique ASCII records, a 4,096-byte payload base plus
`id % 97` and the note/id prefix, four regions, probabilistic 80/20/0 allocation
and child uniform shuffle. It retains the original seed, one worker, 32-MiB job
and aggregate pool, 1-MiB record limit and 1,024-row/65,536-byte output caps.
There is no competing grant. Baseline and candidate each run once on Linux and
once in native Windows/MSVC release mode, after the Linux gates pass.

All four complete Prepare-plus-Execute jobs pass exact within-runtime CSV bytes,
ordered output records and 17 logical Analysis fields. Independent IDs, fields,
group count and caps pass; the exact baseline reference checks seeded membership
and order parity. Every job visits input once, removes owned temporary/private
staging data and releases its pool to zero. This is not a new cross-runtime byte
comparison. Fixture generation and the verifier retain their own heaps outside
the engine ledger; tracked reservations are not RSS.

Both variants remain resident: twelve baseline sorts become four candidate
sorts, with no spill runs or merges. Complete logical temporary reads are
87,772,216 versus 52,924,354 bytes and writes 86,219,471 versus 51,653,806 bytes,
baseline versus candidate, matching across these two runtimes. Those counters
are not physical I/O or elapsed-time evidence. Diagnostic sort clocks remain in
the raw record but are excluded from performance inference. External wide sorting,
competition after buffer observation and browser acceptance of the changed storage
variant remain open; no capacity/shape sweep or extra repetition followed success.

Only the private research helper changes. All runtime/core/storage/vendor and
embedded-asset bytes match the retained available-buffer source-v3. Fresh Linux
formatting/all-target Clippy and the new focused control pass; previous workspace
checks apply only to the byte-identical runtime whose research module was excluded.
The native snapshot matches all 326 declared inputs, its release control and
verifier pass, and exact appended-patch replay passes. No production source,
publication-feature combination, execution graph, default or Auto policy changes.
Full source, plans, binary, statuses and logs remain under private
`scratch/prob-shuffle-wide-20261105T0342/` and its native Windows counterpart;
no archive upload is claimed.
