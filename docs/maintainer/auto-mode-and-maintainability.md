# Auto mode, strategy selection and repository maintainability

## Product reset, 2026-10-29

The [product direction](product-direction.md) now owns future product goals and
investigation priorities. It supersedes this brief where they conflict: the
product will focus on native CLI (including guided interaction) and hosted
browser; local web UI/server retirement is now implemented. Native
leads large-job acceptance; seeded-output policy is removed; and workload-led candidate discovery precedes selector tuning and release
promotion. The old handoff sequence below is historical planning context, not
the next-work instruction. Current behavior and evidence remain as documented.

Buffer-shuffle removal, the first [direct-Run slice](../direct-execution.md), opt-in
automatic memory selection is implemented locally. The former reproducibility
controls have been removed. [Current behavior](../specification.md) keeps omitted
memory at numeric 256 MiB and provides no seeded-output policy. E5 and default promotions remain pending;
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns status and validation sequencing.

Agreed direction, 2026-10-23. This records the owner's decisions from the planning
interview. It is a future implementation brief, not a claim that these behaviors
already exist. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active backlog and specs.

## Status and precedence

The current [specification](../specification.md) and [rewrite rules](../pipeline-rewrites.md)
describe the implementation baseline. This brief explicitly authorizes future
changes to the default execution policy, preparation workflow and buffer-shuffle
support. Update those contracts alongside implementation; do not silently treat
the proposed behavior as delivered. Other correctness and ownership contracts
continue to apply. Existing experimental gates are not evidence of production
readiness, and approval of this direction does not promote candidates by itself.

This supersedes earlier planning preferences to preserve omitted-mode saved-job
behavior, retain every experimental implementation, or require exact preparation
for every job. There are no existing users requiring a compatibility period.
Historical evidence and its original contracts remain historical facts.

## Agreed product decisions

### Default execution and semantics

Auto will be the default in the CLI, native web app and hosted browser, including
configurations that omit an execution mode. Native and hosted execution have
equal standing; their physical choices may differ. Evaluate small everyday jobs,
larger-than-memory jobs and demanding grouping/shuffling pipelines separately.
Do not weight an overall score by how many historical tests happen to exist.

Auto provides best-effort efficient execution with no reproducibility guarantee.
It may select among uniform full-shuffle algorithms with different seeded orders
and consequently different downstream membership. It must still preserve the
requested pipeline order, full-shuffle distribution, exact allocation when
requested, group rules, field values and strict serialized CSV caps. Lack of a
reproducibility promise is not permission to approximate requested operations.
Useful explicit strategy overrides remain available in advanced CLI/app settings;
their existence alone does not justify maintaining a redundant strategy.

The default interaction is configure -> Run. Direct execution without a separate
full prepared-output snapshot is in scope wherever the pipeline permits it.
Optional profiling may be skipped; required parsing, validation and operation
work may not. Exact preview/preparation remains an explicit action and execution
uses that prepared result. This does not imply every pipeline can stream in one
pass. Errors may occur during direct execution; native atomic publication,
browser completion markers, cancellation and failure cleanup remain binding.

### Randomized output and prepared confirmation

Seeded-output policy and its controls have been removed. Public seed input is removed;
internal entropy identifiers are not cross-plan/resource/platform replay controls. Physical rewrites
must preserve requested distributions, exact memberships and caps. Explicit
preparation fixes the encoded snapshot used by confirmation. Historical experiment
labels below do not restore a user-selectable policy or retired runner.

### Buffer shuffle and probabilistic allocation

Remove buffer shuffling completely: executable implementation, public options,
configuration variants, UI, feature-specific tests and active usage guidance.
Remove dedicated harnesses unless needed to interpret preserved evidence. Keep
raw historical results and historical descriptions; they are not live support.
Old buffer-shuffle configurations must fail clearly rather than silently select
another algorithm. A compatibility implementation or deprecation period is not
required. Do not confuse ordinary I/O buffers with the removed shuffle strategy.

Retain explicit probabilistic allocation and run a brief targeted study of its
time savings and count deviations versus exact allocation. Size alone is not an
eligibility rule: include small strata, skew, group sizes and percentages.

There is no silent substitution anywhere. The app may offer probabilistic
allocation when it predicts meaningful savings and can explain likely count
variation, including small affected strata. Require an explicit choice between
using approximate allocation and keeping exact allocation before starting; an
overlooked warning or merely clicking Run is not acceptance. Keep the accepted
choice visible in configuration. CLI use requires an explicit option. If variation
cannot be assessed reliably, leave the advanced option available without a
recommendation. There is no agreed universal acceptable deviation or time-saving
threshold; establish the tradeoff and let the user assess suitability.

### Optimization objective and resource policy

Minimize total time to completed output, including optional profiling, planning,
failed attempts, processing, preparation where used, and publication/export.
Enforced memory and temporary-space budgets are constraints; resource use and
maintenance complexity are tie-breakers. Favor conservative decisions when
evidence is weak. Marginal speed gains do not automatically justify substantially
more memory, disk use or code complexity.

The delivered opt-in `memory_mb: "auto"` slice uses current shared admission
headroom; existing `workers: 0` selection remains unchanged. The
[resource contract](../specification.md#resources-publication-and-interfaces) owns
its resolution, validation and prepared-result behavior. Broader automatic policy
and default promotion remain future work. Explicit user limits take precedence.
Uncertain availability requires conservative fallback. Stage this around actual
admission coverage, concurrent owners and runtime headroom; working-allocation
accounting is not a complete RSS cap.

Initial selection uses versioned rules, file/configuration metadata and bounded
observations from the current job. It can skip sampling, stop early or adapt at
safe boundaries. Charge observation cost to the complete job. Account for skew,
late wide rows and misleading samples; sampling cannot prove a semantic invariant.
Defer persistent device-specific learning until its incremental benefit is shown.

## Evidence review and strategy decisions

Start from the [benchmark guide](../benchmarks/README.md), generated index/catalog,
[existing synthesis](../performance-decisions.md), dated [performance notes](../performance.md)
and [experiment criteria](../performance-opportunities.md). The existing 38 selected
contrasts are a starting point, not an exhaustive review. Inventory the full
corpus and explicitly classify evidence that cannot support speed comparisons.

Build a strategy inventory connecting implementations and feature gates to public
controls, runtime support, semantics, fallback dependencies and maintenance costs.
Include default strategies as well as experiments. Each strategy must earn its
place through credible benefit on an identifiable workload or a distinct useful
capability such as reproducibility. One important workload/runtime can justify
retention; universal wins are not required. Buffer removal is already decided.

Produce an auditable decision record for every strategy: keep, conditionally keep,
remove, or unresolved pending a named decision-changing experiment. Include
baseline, eligible workload/runtime, source hashes and record locations, sample
counts/spread, total-job effects, resource tradeoffs, correctness evidence,
exclusions, confidence limits and code dependencies. Unresolved status is
temporary: specify the experiment's stop criterion and what each outcome changes.
If no realistic experiment can justify a redundant candidate, remove it while
preserving evidence. Do not remove a required fallback or distinct capability
merely because it is not the fastest path.

Use matched within-experiment comparisons. Preserve failures, duplicate/derived
record distinctions, dirty-build identities and missing metadata. Keep incompatible
runtime, workload, storage and timing scopes separate; do not pool historical
percentage gains. Contract timings are not speedup evidence. Keep wall time, CPU,
reservations, RSS, logical traffic, stored bytes and physical I/O separate.

Run only targeted tests that could change a retention decision or selection rule.
Reserve expensive scale/device runs for a specific unresolved boundary or claim.
Evaluate rules on workloads beyond those used to formulate them, including
no-benefit and regression cases, uncertain shapes, admission denial, and cases
where sampling costs more than it saves. Compare complete auto jobs against
appropriate simple baselines, not just the chosen kernel or execution stage.
Numeric thresholds and uncertainty margins require evidence; none are agreed yet.

Put measured interpretation in performance.md and strategy dispositions in the
maintained synthesis with traceable derived data. Refresh/check the benchmark
catalog whenever artifacts or performance evidence links change. Preserve raw
artifacts byte-for-byte. Proposed selectors are hypotheses until validated on
their intended runtimes and workloads.

## Repository maintainability decisions

Optimize for the owner, coding agents and outside contributors. A new contributor
should locate the architecture, run relevant checks and make a small change
without reading research history. Agents should use the same documentation;
AGENTS.md remains concise operational guidance with links to owning documents.

Cleanup includes structural refactoring justified by concrete maintenance
problems, removal of dead strategy code, consolidation of duplicated logic,
clear module responsibilities, reliable development entry points, understandable
tests/CI and repeatable release procedures. Avoid cosmetic churn, arbitrary file
size limits and abstractions without a demonstrated benefit. Audit repository
basics such as contribution instructions and license-file/package consistency;
do not introduce a new license or policy choice implicitly.

Keep research and evidence in this repository for now. Separate current guidance
from historical research through clear navigation and an archive where useful,
preserving links, source identities and reproduction paths. A separate repository
is conditional on measured clone/development friction from artifact size; no
move or Git-history rewrite is authorized by this plan. Do not relocate raw
evidence casually to achieve a tidier tree.

Cleanup proceeds incrementally in the same program: establish documentation and
development entry points, determine which strategies survive, simplify surviving
modules during implementation, then perform a consistency pass. Preserve the
substantial existing uncommitted work; unknown files and failed validation
artifacts are not disposable clutter.

## Handoff sequence and completion criteria

This sequence records the original planning brief. Select current work from
GitHub Issues and its dependencies; use the product direction for precedence.
Reuse existing source provenance, export and synthesis tooling where suitable.

The review deliverable must account for every strategy and every evidence family,
identify unsupported conclusions, and specify only consequential missing tests.
The design deliverable must make feasibility, cost selection, observations,
resource sizing, fallback, direct execution and reproducible semantics explicit.
It must distinguish configuration-only facts, optional samples and required work.

Implementation should be reviewable in bounded changes: eliminate buffer shuffle,
prune evidence-rejected candidates, simplify survivors, deliver policy/execution
paths and controls, then change defaults after applicable validation. Order
individual changes by dependencies rather than treating this sentence as an
additional checklist. Keep current contracts documented until changed code lands.

Acceptance covers preserved fields/membership/distributions/caps, reproducibility
where promised, explicit approximation consent, direct-path failure/cancellation
cleanup, native publication and browser marker/export semantics, resource denial
and fallback, and complete-job performance including observation overhead. Apply
the repository's Rust/UI/browser checks to changed surfaces and regenerate the
hosted distribution from TypeScript and the production WASI engine. Update current docs and claims to
match tested coverage; this direction does not silently expand platform promises.

Final maintenance acceptance is a consistent architecture/development entry
point, one active backlog, no live buffer-shuffle support, justified surviving
strategies, reproducible check/build instructions and preserved evidence navigation.
The present planning change performs no engine implementation or benchmarking.
