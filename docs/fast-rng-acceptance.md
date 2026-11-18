# Additional full-shuffle diagnostic families

Current status (2026-10-24): XOF and independent buckets are removed. The dated
preregistration, original diagnostic flags and follow-ups below are historical;
reproduction requires matching pre-removal artifacts.

Declared 2026-10-18 before inspecting either family's results. These extend the
[original protocol](shuffling-research.md); they do not change its seeds, metrics,
null model, calibration size or negative control. Each is a separate finite
regression diagnostic, with no combined uniformity or performance claim.

1. **blake3-xof-full-shuffle-v1:** flexible policy, explicit uniform and
   Fisher–Yates using `chopper-fast-rng-blake3-xof-1`, plus unchanged buffer-v1
   with four rows as its separate negative control. Use the 64-byte cache.
   Byte parity across cache sizes means additional cache sizes are not separate
   statistical samples/families.
2. **flexible-partition-first-v1:** flexible policy and original BLAKE3-v1
   source, requesting shuffle then partition by `group`. Auto exercises the
   adjacent partition-first rewrite; explicit uniform is its full-shuffle
   exclusion comparator; buffer-v1 is the negative control and remains excluded
   from rewriting. All fixtures end partitioned, including a constant tuple for
   the four single-group fixtures. The skewed fixture yields 192/48/16 rows.

Each family runs the same 32 literal seeds, five input patterns and 256 rows
from the original protocol, one worker, 64 MiB and three requested strategies:
480 complete jobs, 60 primary comparisons and 30 negative-control comparisons.
Keep all six position/displacement/adjacency/label metrics and the existing
0.05/60 primary and 0.05/30 negative-control thresholds. Report every seed,
comparison and flag. Investigate flags with a separately declared follow-up;
do not delete seeds, select metrics or change identities to remove a result.

The ideal null remains independent uniform permutations within each final
expected group. Its deterministic pilot (1,024) and Monte Carlo corpora (2,047
sets of 32) may be computed once and reused verbatim across these families.
A cache must include every corpus vector/center, original null-domain seed,
Python version, source hash of fixture/metric/calibration functions, and shape
constants. Check those before reuse and record the cache hash with results.
This reuses an independently fixed reference; candidate observations do not
change calibration or thresholds.

Require exact unique-ID/field conservation, tuple membership/canonical order,
original partition index, stage/group counts and workspace cleanup. A separate
native/WASI replay must match every CSV hash, row order and output metadata for
the same named source and physical plan. Exact equality between the two
families or against v1 is not expected. Concurrent platform features and the
combined XOF/rewrite plan retain invariant/vector/byte-parity coverage rather
than silently creating an unregistered third statistical family.

These resident diagnostic fixtures do not certify external-scale statistics,
PRNG independence, a literal uniform distribution over all permutations, hard
RSS bounds, physical SSD throughput or other devices. Separate complete-job
native/browser timing, allocation/resource and external/collision/failure checks
are required for performance decisions.
