---
name: chopper-unattended
description: Carry an authorized Chopper investigation through blockers, experiments, validation and merged changes, renewing the time window on continuation. Use for unattended end-to-end work or repeated requests to keep going; not for a single bounded analysis or review.
---

# Unattended Chopper investigation

Keep the user's end outcome active across experiments and delivery checkpoints.
Use this skill alongside [chopper-benchmarks](../chopper-benchmarks/SKILL.md)
for performance/resource investigations. It supplies continuation policy;
the benchmark skill supplies evidence standards.

## Establish the objective

Read the user's full authorization, current Git state, the owning GitHub issue
in `jsmatfess/chopper` and existing session/handoff records before creating work.
Read `docs/agents/issue-tracker.md` before tracker operations. State the end outcome and the
concrete evidence needed to declare it complete. Preserve scope and product
contracts; an unattended request does not authorize new defaults, deployments,
credentials, security changes, delegation or unrelated work.

When the user authorizes a persistent goal and goal tools are available, register
that outcome as the active goal. On continuation, inspect the existing goal
rather than creating a replacement. Keep it active across intermediate reports,
rejected candidates and merged PRs. Mark completion only after the end outcome
and its required delivery gates are verified. A skill is instructions, not a
scheduler: report unavailable continuation support accurately and use supported
runtime events rather than installing hooks or recurring automation.

Record the original objective start, current time-window start, duration, absolute
deadline, launch cutoff and applicable non-time limits in a task-owned session
record before execution. A continuation, including a user saying "continue" or
"keep going", a new prompt resuming or redirecting the authorized work, or a runtime
goal continuation, resets the time window from receipt of that prompt. Reuse the
previous window's duration and launch-cutoff margin unless the user supplies new
ones. Record the renewed deadline and reference the prior session; proceed without
asking for renewed time authorization merely because its deadline passed.

Count failures, retries, builds and waits within each window, and retain lifetime
elapsed time and usage for provenance. A new attempt, branch, output root or PR
alone does not reset time. Explicit user-specified fixed deadlines and non-time
caps remain binding unless the user changes them; renewal of time alone does not
reset run, storage or cost caps. Keep terminal records and controllers intact;
use a fresh reviewed session/plan when their frozen bounds are exhausted.
Operational records reference the owning GitHub issue. GitHub Issues for
`jsmatfess/chopper` is the sole active backlog and specification tracker.

## Continue from each result

1. Compare the evidence with the end outcome. Name the remaining gap.
2. Choose the smallest useful authorized action that can close that gap. Make
   routine design choices from the current contracts and available evidence.
3. Prepare and self-review concrete manifests using
   [the experiment cycle](../../../docs/maintainer/experiment-cycle.md) and
   [validation runner](../../../docs/validation-runner.md). Declare prerequisites,
   source/build/toolchain identities, commands/dependencies, verification, timing
   scopes, duration/storage estimates, deadlines, falsifiers and stop criteria.
4. Execute through the supported runner/harness. After failure, stop dependent
   work, preserve full logs/partial outputs, diagnose, then declare a revised
   attempt separately if a defensible remedy fits the remaining budget.
5. Apply the [Auto performance priorities](../../../docs/maintainer/product-direction.md#auto-and-reproducibility).
   Use absolute seconds on representative large Runs and measured resource
   headroom to choose the next experiment or resolve the candidate. For a
   situational win, complete its selector and decline-path evidence before
   promotion. Deliver supported changes through the authorized PR/merge gates.
   Then return to step 1.

A rejected hypothesis ends that experiment. Assess alternatives against the same
objective before declaring the session finished. A prepared plan, retained patch,
passed control or merged PR is a checkpoint when an authorized gap remains.
Keep independent useful work moving while another workstream waits or is blocked.

## Resolve blockers within authorization

Fix ordinary implementation, harness, path and environment defects when evidence
supports the diagnosis. Install documented development prerequisites only within
the user's authorization and appropriate task-owned locations; otherwise continue
independent work and identify the specific missing authorization or access.
Missing historical logs limit historical attribution; current controls can still
answer current questions. Evaluate whether a safe alternative can advance the
objective without the missing material.

Use fresh source snapshots, build/output roots and immutable retained artifacts.
If preserving earlier binaries is required, a reused compilation cache can
replace executables: choose a fresh target directory or retain and hash the old
artifacts before any rebuild. Reuse passing evidence only with matching relevant
identities. Experimental promotion still requires its own evidence and authority.

The [controller](../../../docs/experiment-controller.md) has stricter per-session
bounds and terminal states than this overall workflow. Preserve those boundaries:
a terminal controller stays terminal. A diagnosed issue may justify a separately
reviewed fresh plan under the remaining overall budget; it never justifies editing
old status, silently retrying, bypassing a scientific rejection or extending an
unsupported runtime. Browser work needs a supported execution plan.

## Wait and resume

Use supported event-driven continuation for CI/reviews. Link created/pushed PRs
as required by the active environment. Read [CI policy](../../../docs/ci.md) for
the active delivery gate; during the temporary local-only phase, use its gated
`local-ci.py land` command and retain the local receipts instead of waiting for
hosted checks or merging through GitHub. Before yielding, save the objective,
current time window and deadline, current head, pending event, cumulative usage
and exact next action. The continuation reads that record and checks the actual head,
its current delivery gate, conflicts and every review/comment/thread before acting. Merge explicitly
with a matching-head guard after successful checks and resolved findings, when
merging is authorized. Stop watchers for finished work; retain the overall goal
if other authorized gaps remain. A CI wait is not objective completion.

## Finish only at an objective boundary

End substantive work when one of these is established:

- **Complete:** the requested end outcome is verified and required changes are
  delivered through their final gates.
- **Budget exhausted:** the current window's deadline or another applicable limit
  prevents further work. Preserve incomplete results as incomplete; a continuation
  renews time according to the rule above.
- **Human dependency:** necessary access is unavailable or a decision exceeds
  authorized product/contract boundaries; remaining independent work is exhausted.
- **No defensible path:** recorded evidence rejects the relevant in-scope
  alternatives and explains why further work cannot resolve the objective within
  current constraints. Uncertainty alone does not establish this condition.

Apply the runtime's lifecycle rules for pausing, blocked status and completion;
never mark an incomplete goal complete to end a turn. Report evidence, failed
attempts, limitations, PR state, artifact/status paths, remaining budget and the
exact next action. Distinguish a checkpoint/event wait from a final stop.
