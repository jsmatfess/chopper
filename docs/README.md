# Documentation guide

Start with the [project README](../README.md) to build and use Chopper.
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active
backlog and specs; [issue guidance](agents/issue-tracker.md) covers tracker
operations. Historical checklists and research do not create additional work.

## Use and contribute

| Question | Start here |
| --- | --- |
| How do I download and use Chopper? | [Native quickstart](../README.md#native-quickstart), [operator support](operator-support.md), [ordered Run CLI](run-cli.md) |
| How do I write a saved Job? | [Job JSON field reference and editor schema](job-json.md) |
| How do I check a saved Job before running it? | [Validate CLI](validate-cli.md) |
| How do I verify a completed native Job? | [Native manifest](native-manifest.md) |
| Will my scripts and saved Jobs work after an upgrade? | [Compatibility and migration](compatibility.md) |
| What behavior and limits are supported? | [Specification](specification.md), [pipeline rewrites](pipeline-rewrites.md), [validation](validation.md) |
| How do native and hosted execution differ? | [Direct execution](direct-execution.md), [browser setup and export limits](browser.md) |
| Where should I make a change and which checks apply? | [Architecture](architecture.md), [contributing](../CONTRIBUTING.md), [script guide](../scripts/README.md) |
| How do I develop in WSL and validate native Windows? | [Two-checkout workflow](windows-wsl-workflow.md) |
| How do checks gate delivery? | [CI policy](ci.md), [local validation runner](validation-runner.md) |
| How do I navigate source and large tool output? | [Graphify](graphify.md), [Context Mode](context-mode.md) |

## Release and product direction

| Question | Start here |
| --- | --- |
| Where are current releases and scope? | [0.5.0 notes](releases/0.5.0.md), [GitHub Releases](https://github.com/jsmatfess/chopper/releases), [current state](current-state.md) |
| How do I package and restore exact release bytes? | [Local packaging](release-packaging.md), [rollback](release-rollback.md) |
| Which previous release and candidate records exist? | [0.4.0](releases/0.4.0.md), [0.3.0](releases/0.3.0.md), [0.2.0](releases/0.2.0.md), [0.1.0](releases/0.1.0.md), [prior focused 0.2 candidate](releases/0.2.0-review.md) and [its acceptance plan](release-acceptance-plan.md) |
| Which goals describe future work? | [Product direction](product-direction.md), [workload investigation](workload-investigation.md); these supersede conflicting priorities in the [earlier Auto brief](auto-mode-and-maintainability.md) |
| What does guided CLI support? | [Guided contract](guided-cli-specification.md), [scoped validation](guided-cli-validation.md) |
| How do execution choices and observations work? | [Decision diagrams](execution-decisions.md), [hosted observations](execution-observation.md), [configuration-only output plan](output-plan-examples.md) |

## Performance and evidence

Use the [performance overview](performance-overview.md) and
[decision registry queries](performance/README.md) before individual narratives.
Decision coverage is selective; extraction coverage lists unsupported schemas.
The [benchmark guide](benchmarks/README.md), [artifact index](benchmarks/INDEX.md)
and [validation index](validation-index.md) locate source records and attempts.
The [evidence storage contract](evidence-storage.md) and
[archived-original index](evidence-originals.md) distinguish public evidence from
restricted originals. The separate public evidence website is retired; preserved
reader URLs describe historical access, not a current download service.

For experiments, use [opportunities and stop criteria](performance-opportunities.md),
the [coded cycle](experiment-cycle.md) and [bounded controller](experiment-controller.md).
The [adaptive roadmap](adaptive-execution.md) and
[resource ownership research](resource-policy-research.md) distinguish implemented
controls from proposals. Measurements apply only to recorded builds, fixtures
and runtimes. Test counts are snapshots; working reservations, RSS, logical
traffic and physical I/O are different measures.

Historical material includes the [completed checklist](history/completed-work-2026-10-20.md),
[original implementation plan](implementation-plan.md), [performance research](performance-research.md),
[shuffle research](shuffling-research.md), [randomization research](randomization-planning-research.md)
and [input-format research](input-format-research.md). Use the
[investigation index](performance.md) for dated decisions and preserved rejected
experiments. Historical proposals and estimates do not describe current behavior.
