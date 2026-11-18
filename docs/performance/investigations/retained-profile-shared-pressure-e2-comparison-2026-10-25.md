## Retained-profile Shared-pressure E2 comparison (2026-10-25)

One untimed copied-source diagnostic observed two actual Shared denials and two
successfully materialized sibling Datasets in the evaluated four-parent batch.
After sibling discard and before serial retry, workspace/process reservations
fell from 160320/424656 to 159772/424108 bytes and directory paths from eight to
four. These are aggregate observations, not per-grant isolation. The exact serial
retry, profile invariance and owner-only then zero cleanup passed. Diagnostic
durations are excluded. The working engine was unchanged.

The conditional six ordinary uninstrumented jobs ran B,C / C,B / B,C with one
quiescent retained profile (264336 bytes) on a fixed 8 MiB ledger. Primary target
time starts immediately before preparation and ends immediately after execute
returns with publication complete; owner setup, identity handshake, serialization
and external verification are outside it. The prior sizing driver's observation
between prepare and execute was removed. Baseline median was 1.1552399 s
[1.0986065, 1.1624471], candidate 1.4415612 s [1.4386231, 1.4546266], n=3 each:
+24.78% using `(candidate median / baseline median - 1) * 100`. Paired changes
were +31.22%, +24.53%, +25.13%. Separately timed owner setup medians were
0.0037649/0.0035804 s. The setup-plus-target **sum of two intervals**, excluding
fingerprint/handshake, had medians 1.1599562/1.4451416 s (+24.59%); it is not an
uninterrupted enclosing clock.

All baselines had zero group retries; every candidate had one batch, four groups
and one retry, with 525000/450000/525000 sorted rows versus 300000. Exact prior-A
CSV bytes/order, every ID/field/header, contiguous parent membership, logical
metadata, seed/version/caps/names and no extras passed independently for every
job. The owner profile stayed identical and the pool returned to R then zero,
with empty temporary storage and no staging. Ordinary counters and extra work
support evaluated retry by inference; their binaries do not directly log typed
denials or successful-sibling counts. The diagnostic establishes its own path.

Process-scope CPU medians were 1.03125/1.515625 s and peak working-set medians
15159296/16269312 bytes, including setup and verification wait. Target logical
read/write medians were 319602756/240568097 versus 482027774/401446105 bytes.
Cumulative pool-peak medians were 7334665/8373447 bytes, including setup; they
were never reset. Sampled owned logical-space medians were 155726087/245304972
bytes. Reservations, working set, logical traffic and space are separate metrics;
20 ms samples are non-atomic lower bounds and may interfere. Independent peaks
cannot be added as simultaneous use. Physical I/O and allocator census are null.
This is static retained-response pressure with warm/uncontrolled cache, not
active CPU/I/O competition or dynamic OS pressure.

The [raw observation summary](../../evidence-originals.md#sha256-bf258dcced4693e8cc560f68c80a97dae5ff6544b541d9f4f2262288c2082c06 "Original: docs/benchmarks/parallel-groups-retained-pressure-2026-10-25.json")
pins each attempt, exact diffs, build/dependency identities and the staged
[immutable E2 bundle](../../../.tools/e2-pressure-measure-20261025-r7/evidence-bundle.zip).
The [implementation report](../../../.tools/e2-pressure-measure-20261025-r7/round-report.md)
records checks, limits and uncertainties. The bundle includes original baseline,
failed/corrected evidence, latest endpoint tests, diagnostic source and ordinary
results; caches remain untouched at their original paths. Driver fmt/Clippy,
release builds, matched dependency closures and all selected correctness/path
checks passed. Existing unchanged-engine test evidence remains separate. Hosted
default package hashes are unchanged; no browser rebuild is claimed.

These six use different artifacts/clocks from the earlier 18 CLI observations
(A -12.68%, skew +36.86%, small +354.45%); no pooling or subtraction isolates a
pure pressure cost. Known group counts, exact rows and valid preceding stage
statistics can inform a future guard, but width costs are absent and headroom
snapshots do not reserve capacity. No numeric selector, retention/removal decision,
TODO completion or strategy disposition is made; parent review remains pending.
