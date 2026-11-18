# Chopper product direction

Agreed with the owner, 2026-10-29. This is the authoritative future product
brief. It supersedes conflicting priorities and product assumptions in the
[earlier Auto brief](auto-mode-and-maintainability.md) and older delivery plans.
It does not describe delivered behavior: the [specification](specification.md),
[rewrite rules](pipeline-rewrites.md) and [validation record](validation.md)
continue to own current contracts and supported claims. [GitHub Issues](https://github.com/jsmatfess/chopper/issues)
owns the active backlog and specs.

## Purpose and scope

Let people describe how they want a CSV divided, then produce correct outputs
quickly with minimal configuration, including beyond available memory, and
explain the execution choices.

First-class jobs include splitting oversized exports into uploadable files,
creating randomized treatment/control groups, partitioning by column values,
and combinations of these operations. Keep partitioning, randomization, exact
or explicitly approximate allocation, stratification, file size/count limits,
and necessary CSV parsing and output packaging. General filtering, joins,
calculated columns and data cleaning are outside the initial product.

Field sorting is also in scope: one or more fields, each with explicit text or
numeric mode and ascending or descending direction. Text ordering is initially
deterministic and case-sensitive, without locale collation or Unicode
normalization. Numeric ordering compares signed integers and decimals exactly,
allows surrounding whitespace and preserves original field text. Empty or invalid
numeric values, NaN, infinity, currency symbols and thousands separators fail at
the first encountered invalid value. Scientific notation is optional if its
support would significantly hamper performance; assess that tradeoff before
promising support. Equal sort keys retain input encounter order within the
current logical group, including when ties cross a later batch boundary.

Support consecutive chunks of at most X records, N balanced consecutive groups,
and balanced consecutive groups of at most X records. Balanced sizes differ by
at most one; the maximum-size balanced mode chooses the fewest required groups
and balances their consecutive ranges. For 120,000 rows and X=50,000, ordinary
chunks contain 50,000/50,000/20,000 rows; balanced capped groups contain
40,000/40,000/40,000. These can be intermediate operations, not only final output
caps. For example: partition by state, sort support score descending, form
batches of at most 50,000, then shuffle independently within each batch. Sorting
determines batch membership; the final shuffle does not exchange rows between
batches. This is future scope, not a claim that all these operations are delivered.

The ordered pipeline expresses the requested semantics. Physical execution may
reorder or fuse work only where equivalence is established under the selected
randomization contract. Requested exact counts, group rules, fields and strict
serialized CSV byte limits remain binding. Randomization is not permission to
approximate another operation. Existing rewrite proofs must be checked rather
than assuming that all shuffle/partition reorderings are valid.

Pursue fusion and physical reorganization aggressively where the requested joint
semantics can be justified. Whole-pipeline transformations are a priority for
investigation, not merely independent operation kernels.

Evaluate algorithm costs in the complete execution plan, accounting for work
already required by other operations. A counting or observation pass may also
serve allocation, planning or another consumer when its information and timing
are compatible. Distinguish total job cost from a candidate's additional work:
two reads are not an extra penalty if the job already needs both and can reuse
them. Conversely, do not assume reads or observations are shareable without
checking dependencies, source identity, decoding, retained state and resource
lifetimes. Local algorithm results alone do not determine strategy selection.

For future behavior, pipelines requesting any randomization, including random
allocation, do not guarantee preservation of input row order. Random membership
does not itself require uniformly shuffled output order; an explicit shuffle
still requests that distribution. Subsequent positional operations and exact
counts, group rules and byte caps retain their semantics. Reproducibility still
requires the same versioned logical output, including its chosen row order,
across supported resource variations. Pipelines without randomization retain
their order guarantees. The current engine's allocation-order contract remains
in force until implementation, specifications and checks change together.

## Product surfaces and scale

Focus on a native CLI and hosted browser app. Retire the local web UI and native
server as product surfaces in a later implementation change; they still exist
and retain their checks until removed. Preserve the native engine and CLI.

The CLI supports scripts and a guided interactive workflow: select input,
compose operations, choose output, run, and inspect progress and strategy
explanations. Start with column selection and a small preview. Offer explicit
column-value exploration with bounded displays, distinguishing complete sets,
estimates and samples. Explain when another scan is needed. Let users save a
configuration and rerun it noninteractively. This is not a general data explorer.

Consumer hardware is the primary target. Evaluate everyday files, files near
available memory, and files far beyond memory separately. Tens of gigabytes is
the initial native large-job target, not an already established support claim.
The browser shares functional semantics; reaching that scale is a goal pursued
through demonstrated milestones, not assumed parity. Native leads large-job
acceptance. Memory limits alone do not emulate different storage or hardware.

## Auto and reproducibility

Auto owns execution strategy and resource choices. A valid larger-than-memory
job should normally finish using temporary disk without algorithm selection or
manual memory tuning. Respect explicit limits, use conservative availability
estimates, and report when resources genuinely cannot support the job.

Minimize total elapsed time from Run to completed output, including observation,
planning, retries, processing and publication/export. Prefer simpler strategies
and lower resource use in close comparisons. Numeric thresholds and the meaning
of a close comparison require evidence; none are established by this brief.

Weigh implementation complexity, algorithm maturity and failure risk alongside
elapsed time and resource use. Prefer simple, known, safe approaches over
experimental ones with unknown or tricky failure modes unless demonstrated
benefit and resolved risks justify the added complexity.

Start with cheap facts such as file size, configuration and runtime resources.
Take an obvious conservative path for small jobs rather than paying for elaborate
planning. File size alone does not prove resident feasibility, especially for
compressed input or expanded grouping structures. Gather observations during
required work, and perform extra analysis only when its expected absolute
benefit justifies its cost. Auto may adapt at safe execution boundaries, accounting
for switching costs and preserving semantics, admission and failure cleanup.

Seeded-output policy has been removed. Randomized results may change with the
physical plan, resource budget, runtime or build even with the same seed. Auto
optimizes correct completion while preserving requested distributions, exact
allocation, caps and cleanup. Prepared confirmation executes its fixed snapshot.

## Knowledge reuse

Initially reuse bounded observations within the current session, gathered from
completed reads or execution: shape, row widths, cardinalities, skew and measured
partition sizes where available. Associate knowledge with input identity, parser
settings, measured columns/combinations, completeness and accuracy. Individual
column cardinalities do not establish joint partition sizes. Source changes or
uncertain identity require invalidation or conservative treatment.

Knowledge guides performance choices and never substitutes for required input
validation or correctness checks. An incorrect estimate must permit safe fallback
rather than incorrect output. Persistent reuse across restarts is deferred until
its benefit justifies storage and identity/invalidation complexity; verifying a
whole-file hash can itself erase the benefit.

## Workload-led investigation

Organize the investigation around diverse publicly available and simulated
datasets paired with realistic complete pipeline configurations. Public data
supplies unanticipated combinations; simulation isolates causes, crossover
points and difficult cases. Dataset selection must consider lawful availability,
retrieval/reproduction and practical storage costs.

Use workload properties to propose competing algorithms, including simple
baselines and credible approaches absent from the codebase. Examine width,
quoting, cardinality, skew, order, compression, output count and size relative
to memory. The owner's report of a promising two-pass chunked partition shuffle
is motivation to broaden candidate discovery, not a verified general speed claim.

Measure complete jobs on recorded consumer hardware/storage and resource budgets.
Derive rules from cheaply observable properties rather than dataset names, and
challenge them on held-out workloads. Include no-benefit cases, misleading
observations, late wide rows, extreme skew and resource denial. Preserve failed
attempts and provenance; keep wall time, accounting, RSS and I/O measures distinct.
Existing evidence remains useful within its recorded coverage.

Do not retain unused or rejected strategy implementations merely as an archive.
Keep concise public rationale, provenance and evidence pointers; preserve private
tests, results and necessary replay material through the existing
[separate repository and archive policy](evidence-storage.md). Remove unused
strategy code after required preservation and reference checks, without rewriting
historical evidence. Conditional candidates need not be implemented unless a
workload-specific question justifies testing them.

For each rejected approach, retain at least a concise description, whether it
was researched or actually tested, the rejection rationale, workload/runtime and
whole-plan assumptions, evidence limitations and archive pointers. Rejection is
conditional on that context, not a permanent judgment on an algorithm family.
Reconsider when new findings, workloads, runtime capabilities or overall strategy
changes undermine the original rationale; state the changed assumption and the
new question before investing in another test.

Begin with a bounded, diverse comparison panel that can expose missing approaches
and useful distinctions before tuning thresholds or expanding matrices. Every
experiment should resolve eligibility, a selection boundary or fallback confidence.
Use available machines initially; rented infrastructure requires a specific
unanswered question. No new datasets, experiments or speed claims are produced
by this planning reset.

## Consequences for existing work

There are no users requiring compatibility with existing interfaces or strategy
choices. Existing machinery, defaults and abstractions may be replaced or removed
when a simpler approach better serves these goals. Reproducible randomization
remains required when explicitly requested. Change documented contracts and
applicable checks alongside implementation; this latitude does not authorize
accidental correctness loss or rewriting historical evidence.

The previous finish-the-release sequence no longer determines what happens next.
Do not automatically promote existing selectors, finish E5 as previously framed,
or prune candidates solely because earlier comparisons omitted stronger options.
Completed validation remains valid for its recorded identities. Old pending work
is reference material until reconciled with the new investigation, except checks
needed to preserve correctness when changing code.

Wayfinder planning is complete in the
[workload corpus](history/prior-issues.md#issue-1),
[execution candidates](history/prior-issues.md#issue-8) and
[first comparison panel](history/prior-issues.md#issue-9) maps.
Their resolution tickets hold the detailed decisions, staged comparisons,
held-out policy and execution prerequisites; no experiments or implementation
were performed by this planning phase. Prepare concrete run manifests and cost
estimates against actual data and implementations before executing comparisons.
Defer interactive CLI implementation and local-server/UI removal until the
execution direction is established. Keep implementation status in the owning GitHub issue rather
than creating a second checklist here.
