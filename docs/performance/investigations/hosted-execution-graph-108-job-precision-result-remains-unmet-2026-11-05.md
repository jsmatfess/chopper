## Hosted execution graph: 108-job precision result remains unmet (2026-11-05)

**Decision: retain the remaining unmet uncertainty gate.** The
[combined report](../../evidence-originals.md#sha256-d59c9c71f4f2c9df68b38a55c9bf35f02e2ff8fcc1ebd9f2a2ccfed6f9682c47)
retains all 72 original and 36 added jobs, with independent exact artifact parity
across all three modes/cohorts. Direct/resident retain six blocks; external and
high-cardinality now have twelve. Seven of eight cells pass. Expanded external
merge has median slowdown -0.0693%, with exact conditional upper95 +7.6153%.
No original timing, including the three slow expanded samples, was excluded.
The first extension is terminal; its unmet gate and all original raw data remain.

The six added expanded external samples are stable near 45 seconds. Together
with the diagnostic probes, this does not identify a causal production hotspot;
changing production to chase these timings is unjustified. An explicit further
assessment selects one final, bounded external-only precision study: six more
balanced blocks/18 jobs, all prior 108 observations retained. Both original 5%
thresholds remain fixed. Eighteen-block conditional bootstrap uses a conservative
simulation-error bound; exact six/twelve-block references remain unchanged.
[Acceptance methodology](../../execution-graph-acceptance.md) records the fixed seed,
resample count, DKW inflation, source and post-gate-selection limitations. It is
not an optional-stopping-adjusted confidence claim. No further data-only
augmentation is declared. At that checkpoint the final study had not run, and feature acceptance
remained incomplete. The later accepted result above retains this report.
