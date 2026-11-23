# Maintainer guide

For installation and operator workflows, see the [user guide](../user/README.md).

## Develop and review changes

- [Contributing](../../CONTRIBUTING.md) routes checks. [Architecture](../architecture.md)
  follows a Job through the code.
- [Behavior specification](../specification.md), [pipeline rewrites](../pipeline-rewrites.md),
  [direct execution](../direct-execution.md), and [execution decisions](../execution-decisions.md)
  define the engine contracts. [Browser development](../browser.md#local-development) covers
  the hosted build. [Execution observation](../execution-observation.md) covers its reporting.
- Use the [Windows and WSL workflow](../windows-wsl-workflow.md) for paired native checks.
  [Graphify](../graphify.md) and [Context Mode](context-mode.md) cover local navigation tools.
- Use [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for active work.
  Read [issue operations](../agents/issue-tracker.md) before changing the tracker.

## Qualify and ship releases

- [CI policy](../ci.md) explains the delivery gate. [Validation runner](../validation-runner.md)
  covers reproducible batches. [Validation](../validation.md) records supported scope.
- [Packaging](../release-packaging.md), [hosted qualification](hosted-tiny-qualification.md),
  and [rollback](release-rollback.md) cover release operations.
- [Operator docs release](operator-docs-release.md) covers candidate checks and
  publishing the versioned site.
- [Current state](current-state.md) routes current behavior, evidence, and delivery records.
  [Release records](../releases/) hold version notes and acceptance receipts.

## Find performance evidence

- Start with the [performance overview](../performance-overview.md) and
  [decision registry](../performance/README.md) for current decisions.
- Find results in the [benchmark catalog](../benchmarks/INDEX.md) or
  [validation index](../validation-index.md). Use the [evidence storage contract](../evidence-storage.md)
  to retrieve [archived originals](../evidence-originals.md).
- Use the [benchmark guide](../benchmarks/README.md), [experiment cycle](experiment-cycle.md),
  and [controller](../experiment-controller.md) when planning a run. See
  [opportunities and stop criteria](../performance-opportunities.md) for experiment selection.

## Design and history

- [Product direction](product-direction.md) and [workload investigation](workload-investigation.md)
  describe future goals. [Adaptive execution](../adaptive-execution.md) and
  [resource ownership](../resource-policy-research.md) distinguish implemented controls from proposals.
- [Guided CLI contract](guided-cli-specification.md),
  [guided CLI validation](guided-cli-validation.md), and [output plan examples](../output-plan-examples.md)
  cover specific surfaces.
- See [research notes](research/), [dated investigations](../performance/investigations/),
  and [project history](../history/) for earlier work.
