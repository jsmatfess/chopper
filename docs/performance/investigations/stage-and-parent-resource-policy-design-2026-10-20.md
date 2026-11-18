## Stage and parent resource-policy design (2026-10-20)

The [policy design](../../adaptive-execution.md#evidence-based-stage-and-parent-policy-design-2026-10-20)
turns the [historical synthesis](../../performance-decisions.md) and the separate
Windows calibration below into an implementation contract. This is analysis
only: no new jobs, timing observations, threshold calibration or default changes.
The design cites raw Windows measurement locations and source hash; pilot,
control and derived summary records are not timing observations. Historical
runtime cells are not pooled with Windows results.

Prioritize exact shuffle/partition behind its experiment gate, separating legal
rewrites, current live-capacity admission and complete-job cost. More sort runs
can coexist with lower elapsed time, while rare-wide capacity can increase; no
row-count or run-count rule follows from these cells. Other fusion candidates
retain their small-parent, downstream and browser-routing counterexamples.
Per-parent grants must include live conversion/replay overlap, retain existing
ceilings and fall back only at executor-supported replay boundaries. The design
specifies ownership, cancellation/error cleanup, replay identities and acceptance
at the planner/executor boundary. Implementation, threshold/device calibration
and incomplete allocation coverage remain in [TODO](../../../TODO.md).
