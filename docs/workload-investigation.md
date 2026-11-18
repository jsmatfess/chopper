# Workload-led investigation handoff

Planning completed 2026-10-31. [Product direction](product-direction.md) owns
future intent; [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active implementation backlog.
The [specification](specification.md), [rewrite rules](pipeline-rewrites.md) and
[validation](validation.md) still own current behavior and supported claims.
No engine implementation, dataset acquisition or experiments were performed
by this planning phase.

## Decision sources

- [Workload corpus map](history/prior-issues.md#issue-1):
  [coverage](history/prior-issues.md#issue-2),
  [scale/browser](history/prior-issues.md#issue-3),
  [simulation](history/prior-issues.md#issue-5),
  [identity/correctness](history/prior-issues.md#issue-6),
  [panel selection](history/prior-issues.md#issue-7) and
  [concrete recipes](history/prior-issues.md#issue-20).
- [Execution candidates map](history/prior-issues.md#issue-8):
  [eligibility](history/prior-issues.md#issue-12),
  [shortlist](history/prior-issues.md#issue-13) and
  [sorting/batching](history/prior-issues.md#issue-21).
- [First comparison map](history/prior-issues.md#issue-9):
  [measurement](history/prior-issues.md#issue-14),
  [budgets](history/prior-issues.md#issue-15),
  [holdouts](history/prior-issues.md#issue-16),
  [decision/stop criteria](history/prior-issues.md#issue-17) and
  [staged comparisons](history/prior-issues.md#issue-18).

Resolution comments contain the decisions, including later clarifications;
original question bodies and dated research may reflect earlier assumptions.
All three maps are closed. Implementation prerequisites are still pending.
Use the [coded experiment cycle](experiment-cycle.md) for reasoning routing,
deterministic execution and compact evidence handoffs.

## Retained research

These pushed reference branches intentionally remain separate from production
history. Their notes are cited at immutable commits; merging them is unnecessary.

- [Public dataset candidates](https://github.com/jsmatfess/chopper-private-archive/blob/b680866/docs/workload-corpus-public-candidates-research.md)
  (`research/workload-corpus-public-candidates`).
- [Execution candidate inventory](https://github.com/jsmatfess/chopper-private-archive/blob/d910ae4/docs/execution-candidate-inventory-research.md)
  (`research/execution-candidate-inventory`).
- [Workload-led external-memory prior art](https://github.com/jsmatfess/chopper-private-archive/blob/10fa742/docs/workload-led-external-memory-prior-art-research.md)
  (`research/workload-led-external-memory-prior-art`).

They are planning evidence, not measured Chopper speedups. Later decisions take
precedence over their preserved-order/replay assumptions. No identified recipe
or evidence supports the original Gemini two-pass superiority assertion.

## First implementation slice

Begin with a versioned deterministic entity-list generator, complete ordered
export and partition/allocation/shuffle Job recipes, and independent tiny-case
verification. Entity fields are record ID, region, locality, segment, name,
address and notes. Record generator identity/seed/parameters separately from
pipeline randomization controls. Generated defaults are UTF-8, headers, LF and
plain CSV. Width, cardinality, skew, order and scale are explicit parameters
selected for a hypothesis, not a matrix to enumerate.

The first jobs are ordered export with a 10,000,000 serialized-byte cap, and
region partition followed by independent 80/20 treatment/control allocation and
shuffle within each child. Start with available eligible paths and record what
is actually fused or materialized. Prepare native Windows and persistent-browser
manifests before execution, reusing supported harnesses where suitable.

Check current Job schema, capabilities, provenance and measurement boundaries
against source. Future opt-in reproducibility, relaxed allocation ordering,
field sorting and intermediate batching are not silently implemented by a
benchmark recipe. New-contract comparisons require deliberate implementation,
specification and applicable validation first. Independent checks cover field
and row-multiplicity conservation, membership, requested distributions/counts,
order requirements, caps and relevant failure/publication behavior.

## Experiment discipline

Use research and algorithm reasoning to test named whole-plan boundaries,
tradeoffs or fallback questions. Credit only genuinely shareable passes and
observations, including their acquisition cost. Many small tests with scaled
resource bounds do the groundwork; fewer full-scale checks establish transfer.
Browser is a first-class heuristic and measurement runtime, not just native parity.

Initial exploratory guardrails aim for runs under two minutes, require
investigation before a run beyond fifteen minutes, and bound an unattended batch
to two hours and 20 GiB of experiment-owned simultaneous storage. These are
adjustable planning limits, not measured cost estimates or resource-fit claims.
Concrete manifests must pin inputs/builds/toolchains, starting knowledge,
resource bounds, verification/timing scope, owned artifacts and locations,
estimates and deadlines. Recheck current capacity and prerequisites before runs;
use the [validation runner](validation-runner.md) for unattended sequential batches.

Measure Run-to-usable-output, including planning, retries, decoding, processing
and publication/export. Report separate verification overhead, actual reuse,
uncertainty and distinct resource measures. Prefer known, simple, safe approaches
unless benefit and resolved risk justify complexity. Retain regime-specific
outcomes and rejected ideas with their assumptions and evidence pointers, using
the [separate archive policy](evidence-storage.md); do not keep unused strategy
code as an archive.

Reserve these combinations from performance tuning initially: dominant groups
correlated with unusually wide records; late new keys with high fanout; nearly
sorted score data with ties crossing batch boundaries. Ordinary correctness
checks may cover them earlier. Freeze strategy rules, predictions, algorithm
versions and concrete evaluation cases before held-out performance evaluation.
A case used to tune rules becomes development evidence and needs a fresh
independent evaluation replacement.

Public Bank/DfT/GHCN anchors and later generator families remain selected as
specified in the recipe decision, subject to acquisition gates. Sorting/batching,
count-first allocation and external-shuffle alternatives are later staged
questions, not prerequisites for the first two baseline jobs. No live strategy
thresholds or unconditional full-scale run list were settled by planning.
