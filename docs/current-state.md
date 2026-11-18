# Current state

Chopper 0.2.0 scope is the native CLI on 64-bit Windows and Linux, plus a separate
hosted browser UI. Start with the [0.2.0 release notes](releases/0.2.0.md) for
behavior and limits. The release page and final receipts own package, source and
validation identities; this router is not an acceptance receipt.
macOS is source-only; current release acceptance does not cover it.

[GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active
backlog, specs, dependencies and acceptance criteria. The
[product direction](product-direction.md) owns future goals; the
[specification](specification.md) and [rewrite rules](pipeline-rewrites.md) own
current behavior. Historical plans do not add tasks or authorize experiments.

## Current behavior

- The current product interfaces are the Windows/Linux CLI and the hosted
  browser UI. There is no native server or native UI in the 0.2 scope. Ordered
  `run --step` flags and JSON Run share the engine; `split` keeps its fixed order.
- Randomization has no public seed or replay setting. Prepared confirmation
  executes the retained encoded snapshot; a new Run can produce a different order.
- Omitted working memory is 256 MiB; `auto` is explicit. Reservations account for
  working allocations and do not cap total process/RSS memory.
- Native publication is atomic without replacement. Hosted export uses a final
  completion marker and can leave partial output when interrupted.
- Experimental features remain opt-in. Source availability and a local pass do
  not establish release, hosted deployment or broader platform acceptance.

## Evidence and delivery

[Validation](validation.md) owns supported claims, each limited to its exact
source, artifacts, workload and host. The [prior focused 0.2 review](releases/0.2.0-review.md)
records a selected candidate that excludes later main changes; its acceptance
must not be transferred to the final release without a documented identity and
coverage assessment. The [packaging guide](release-packaging.md) describes local
assembly, and [rollback](release-rollback.md) describes restoration records.
The final release must identify its own source, packages, checksums, acceptance
and publication records.

The [hosted app](https://chopper-1rx.pages.dev/) is a separate deployed snapshot.
This page does not assert its current asset identity or that it contains the
latest source. Use a deployment receipt and served-asset verification for that claim.
The former native server/UI and separate evidence-site are retired from current
product scope; references to their validation belong to historical records.

The [earlier handoff](history/current-state-through-2026-10-28.md) preserves dated
ownership work, test counts and operational context. It is historical reference.
