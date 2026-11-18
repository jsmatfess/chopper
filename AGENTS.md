# Working on Chopper

Chopper processes CSVs larger than memory through a Rust CLI for Windows/Linux
and a hosted TypeScript UI. The hosted build runs the engine in a WASI browser
worker; native builds contain the CLI only.

## Find the current source of truth

- Start with [README.md](README.md) for setup and [docs/README.md](docs/README.md)
  for documentation routing; [docs/architecture.md](docs/architecture.md) follows
  a job through the current modules and development entry points.
- [CONTRIBUTING.md](CONTRIBUTING.md) routes changes to applicable checks and
  explains native/generated/hosted output boundaries.
- [GitHub Issues](https://github.com/jsmatfess/chopper/issues) is the active backlog and spec tracker.
  Read [issue operations](docs/agents/issue-tracker.md) before tracker changes.
  Historical checklists and dated research do not create additional work.
- [Product direction](docs/product-direction.md) owns future goals and supersedes
  conflicting priorities in the [earlier Auto brief](docs/auto-mode-and-maintainability.md).
  Distinguish proposals from current behavior; use issue dependencies for work order.
- [docs/specification.md](docs/specification.md) defines behavior;
  [docs/pipeline-rewrites.md](docs/pipeline-rewrites.md) defines rewrite eligibility.
- [docs/browser.md](docs/browser.md) owns browser setup and export limits.
- [docs/validation.md](docs/validation.md) owns supported correctness, platform
  and scale claims. Keep claims within the recorded build/workload coverage.
- For current performance conclusions and delivery status, start with the
  [overview](docs/performance-overview.md) and [decision registry queries](docs/performance/README.md)
  before opening individual narratives. Use its topic/observation queries and the
  [validation index](docs/validation-index.md) for source records and test attempts.
  Decision coverage is selective; extraction coverage lists unsupported schemas.

## Implementation boundaries

For code navigation, query the local Graphify graph before broad source searches
when `graphify-out/graph.json` exists:
`powershell -NoProfile -File scripts/graphify.ps1 query "<question>" --budget 1200`.
On Linux/WSL, use `sh scripts/graphify.sh query "<question>" --budget 1200`.
Refresh after source changes using the code-only extraction command in
[local Graphify setup](docs/graphify.md). The graph excludes vendor sources and
historical evidence; verify findings against current source and owning docs.
The wrapper disables model backends. Do not switch to semantic extraction or
Graphify Cloud as part of ordinary graph refreshes.

- `crates/chopper-core`: portable configuration, CSV and randomization contracts.
- `crates/chopper`: native CLI, engine, storage, resources and publication.
- `crates/chopper-browser`: WASI engine adapter.
- `ui/src`: framework-free TypeScript UI and browser workers.
- `scripts`: builds, validation and experiment harnesses.
- `vendor/zip-2.4.2`: pinned ZIP reader patch for metadata and member-container admission;
  see its `CHOPPER.md`. It is excluded from the workspace. Include vendor sources
  in fresh build provenance and re-audit the ownership bounds when updating it.
- `vendor/zstd-sys-2.1.1`: pinned C streaming allocator bridge, including legacy
  decoder children; see its `CHOPPER.md`. Preserve the vendored backend and
  include the complete directory in build provenance when changing codecs.

Preserve pipeline semantics, exact allocation/group membership and strict serialized
CSV byte caps. Randomized output has no cross-plan seeded replay guarantee;
prepared confirmation still executes the retained output snapshot. Read the relevant specification and rewrite rules first.
Keep native atomic publication and browser completion-marker semantics distinct;
cover failure/cancellation cleanup when changing storage or execution lifetimes.
For Run dispatch or direct-publication changes, read the
[direct-execution contracts](docs/direct-execution.md).
For randomization, automatic memory resolution or worker
selection, read the [randomization](docs/specification.md#shuffling-and-seeds) and
[resource contracts](docs/specification.md#resources-publication-and-interfaces).
Memory reservations are working-allocation accounting, not a complete RSS cap.
Preserve [spool-key storage, owned conversion and metadata admission](docs/resource-policy-research.md#fixed-size-spool-header-keys-2026-11-05)
when changing header/row decoding; key bytes must drop before their grants.
Preserve [validated packed-field construction and immutable views](docs/resource-policy-research.md#validated-packed-field-traversal-2026-11-05)
when adding record constructors, byte mutation or decoder paths; packed traversal
relies on that UTF-8 invariant.
Keep prepared configuration read-only and audit new schema fields against its
[retained-capacity owner](docs/resource-policy-research.md#prepared-configuration-capacity-ownership-2026-10-23).
Analysis headers, previews, selected-column summaries, stage statistics, text,
warnings, timings and diagnostics share immutable admitted payloads; preserve their
[last-clone release ordering](docs/resource-policy-research.md#analysis-header-and-shared-payload-ownership-2026-10-23).
Re-audit the [summary tree envelope](docs/resource-policy-research.md#selected-column-summary-admission-2026-10-23)
when changing summary limits or standard-library node layout.
Preserve [stage-counter pre-admission and private unique construction](docs/resource-policy-research.md#analysis-stage-statistics-ownership-2026-10-23) when changing stage reporting.
Keep [Analysis text copies and their grants](docs/resource-policy-research.md#analysis-text-ownership-2026-10-23) together through returned/cloned Analysis.
Re-audit [warning/timing construction bounds and tree admission](docs/resource-policy-research.md#analysis-warning-and-timing-ownership-2026-10-23) when adding metadata.
Keep [diagnostic source visits and admission](docs/resource-policy-research.md#analysis-diagnostic-snapshot-ownership-2026-10-23) separate: release audit/pressure locks before reserving, then recheck the borrowed schema before construction. Re-audit shared JSON preflight when changing Serialize forms or serde_json features.
Preserve [Column scalar decoding and strict invalid-input validation](docs/resource-policy-research.md#column-scalar-deserialization-2026-10-23), including owned-name moves, numeric-string names and legacy error placement.
Temporary construction/reopening follows the [ownership contract](docs/resource-policy-research.md#controlled-temporary-construction-and-reopen-2026-10-22).
Preserve atomic creation, independent reader offsets and platform file-identity
checks when changing those helpers.
Codec admission depends on pinned flate2/miniz and Zstandard implementations;
re-audit the [codec ownership contracts](docs/resource-policy-research.md#zstandard-input-streaming-allocation-ownership-2026-10-23)
when changing codec versions, backend features or stream settings.
Experimental features and flexible replay policies remain opt-in unless the task
authorizes promotion and the evidence supports it.

## Windows and WSL development

For paired WSL development and native Windows validation/benchmarks, follow
[the two-checkout workflow](docs/windows-wsl-workflow.md). Keep Linux tools and
source on the Linux filesystem and native Windows builds/data on Windows drives.
Use `scripts/windows-native.py` for explicit Windows dispatch with revision checks;
never reset or synchronize a dirty checkout automatically. WSL timings do not
establish native Windows performance.

## Build and verification

For local validation, CI triggers and PR merge gates, read
[CI policy](docs/ci.md). The workflow declares PR/main and manual triggers;
hosted activation and acceptance are tracked there. Until hosted acceptance is
recorded, deliver through the local gate. Before authorized delivery to main, use
`python3 scripts/local-ci.py land`, which executes the workflow locally and gates
the tested commit's push on Linux and applicable native Windows receipts.
Preserve conservative path selection and report actual platform coverage.

Run commands from the repository root. Current command definitions live in
`Cargo.toml`, `ui/package.json`, `scripts/` and `.github/workflows/ci.yml`; check
those when these examples stop matching. Use the applicable checks for the change;
documentation-only edits need link/command review, not a full engine build.

For Rust changes:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
```

For portable-core changes, also check its WASM target (install the target if needed):

```sh
cargo check --locked -p chopper-core --target wasm32-unknown-unknown
```

For hosted UI changes, install dependencies with `npm --prefix ui ci` when needed
and typecheck with `npm --prefix ui run check`. UI tests run in the browser job.
Build the hosted distribution only after building the WASI engine:

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
```

The hosted UI is TypeScript source; build its generated output with the hosted
workflow in [browser.md](docs/browser.md). Native Rust builds do not depend on
Node or embed UI assets. Hosted build provenance includes the WASI engine and
all hosted assets; see the [runner input contract](docs/validation-runner.md).

For hosted engine/worker changes, follow `docs/browser.md` for Rust target,
WASI SDK and Chromium prerequisites. The current validation sequence is:

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
node scripts/build-browser-tests.mjs
node scripts/test-browser.mjs
node scripts/test-browser-graph.mjs
node scripts/test-browser-graph-lifecycle.mjs
node scripts/test-browser-graph-inspection.mjs
node scripts/test-browser-step-starts.mjs
node scripts/test-browser-theme.mjs
node scripts/test-browser-step-motion.mjs
node scripts/test-browser-value-shares.mjs
node scripts/test-browser-graph-bounds.mjs
python3 scripts/test-execution-graph-analysis.py
python3 scripts/test-execution-graph-extension.py
node scripts/test-browser-graph-lifecycle.mjs --composed
node scripts/test-browser-bridge.mjs
node scripts/test-browser-cleanup.mjs
node scripts/test-browser-termination.mjs
node scripts/test-browser-termination.mjs --persistent
node scripts/test-browser-termination.mjs --persistent --process-kill
node scripts/test-browser-termination.mjs --persistent --process-kill --direct
node scripts/test-browser-termination.mjs --persistent --process-kill --composed
node scripts/build-browser.mjs --resource-contracts
node scripts/build-browser-tests.mjs --resource-contracts
node scripts/test-browser.mjs --resource-contracts
node scripts/build-browser.mjs --resource-contracts --features experimental-shuffle-partition
node scripts/test-browser.mjs --resource-contracts --shuffle-partition
```

After test builds, run `node scripts/build-browser.mjs` without feature flags,
then `npm --prefix ui run build:hosted` before preparing a deployable artifact.
This restores the default production engine and removes test assets, including
both baseline and shuffle-partition resource-contract test WASMs. Hosted output is
`ui/dist`. Production packaging rejects an
engine exposing the test-only resource entry point.

Browser acceptance harnesses default to bundled Chromium. Set
`CHOPPER_BROWSER_CHANNEL=chrome` or `CHOPPER_BROWSER_CHANNEL=msedge` to check an
installed desktop browser with disposable test contexts/profiles; see
`docs/browser.md` for selection and evidence limits.

For this checkout's optional local Rust toolchain, see the root README's
`.tools/linux/cargo/env` setup. Do not assume it exists in another checkout.
Add focused regression coverage for changed contracts. Distinguish checks actually
run from checks blocked by missing platform/toolchain prerequisites.
For unattended sequential batches, use the [local validation runner](docs/validation-runner.md)
with declared inputs, artifacts, toolchains and deadlines. Reuse passes only with
matching relevant identities; retain incomplete/failed attempts and full logs.

## Performance evidence

For repeated experiments, follow the [coded experiment cycle](docs/experiment-cycle.md)
for reasoning routing, declared command pipelines and compact evidence handoffs.
For an authorized end-to-end unattended investigation, use the repository
[chopper-unattended skill](.agents/skills/chopper-unattended/SKILL.md) to retain the
overall objective across experiments and merged PRs, with time-window renewal
and limit handling defined in that skill.
For unattended sessions, decision-file resume or session stop/recovery, read the
[controller commands and limits](docs/experiment-controller.md).

Use the repository's [chopper-benchmarks skill](.agents/skills/chopper-benchmarks/SKILL.md) for benchmark analysis and
experiments. Its maintained repository rules are
[docs/benchmarks/README.md](docs/benchmarks/README.md) and
[docs/performance-opportunities.md](docs/performance-opportunities.md); follow
those directly if the skill is unavailable.

Find existing evidence through `docs/benchmarks/INDEX.md` and `catalog.json` before
adding runs. Compare matched complete jobs, preserve provenance and failed runs,
and keep timing, memory accounting, RSS, logical traffic and physical I/O separate.
Do not launch large matrices merely because a harness exists. Record interpretation
in a new dated investigation using the [narrative authoring workflow](docs/performance/README.md#investigation-narratives),
and future work in GitHub Issues for `jsmatfess/chopper`. `docs/performance.md` is generated compatibility navigation.

After adding artifacts or changing performance evidence links:

```sh
python3 scripts/performance-narratives.py
python3 scripts/audit-strategy-evidence.py
python3 scripts/benchmark-catalog.py
python3 scripts/performance-registry.py
python3 scripts/evidence-views.py --build
python3 scripts/performance-narratives.py --check
python3 scripts/benchmark-catalog.py --check
python3 scripts/performance-registry.py --check
python3 scripts/evidence-views.py --check
```

Preserve raw historical artifacts and migrated prose. Register new investigation
documents using the [narrative authoring workflow](docs/performance/README.md#investigation-narratives);
`docs/performance.md` is a generated compatibility index. Regenerate derived outputs
through their scripts; [the benchmark guide](docs/benchmarks/README.md#evidence-checks)
owns the complete read-only check list.

## Keep these instructions current

For Run dispatch, resource resolution/admission, spill/retry, rewrite eligibility
or Auto policy changes, update the affected [execution decision diagrams](docs/execution-decisions.md)
in the same change; follow their maintenance guidance and verify current/design status.

Maintain this file as part of relevant work, not as a separate recurring task:

- When a task changes a documented command, directory boundary, generated artifact
  or durable project convention, update the affected guidance in the same change.
- If an instruction or link is stale, inspect the maintained source and actual
  behavior, make the smallest supported correction, and report it with the work.
  Distinguish intended behavior from an implementation bug; a failing check alone
  does not justify weakening a contract or removing validation.
- Keep detailed rules in their owning documents and link to them here. Avoid
  copying benchmark results, test counts, dates, backlogs or machine-specific paths.
- Add guidance only for a durable, evidenced convention that will help future
  tasks. Do not turn a one-off workaround into a universal rule. Remove obsolete
  guidance when its replacement is verified.
- If sources conflict and the intended contract cannot be established, explain
  the specific conflict and ask for clarification rather than silently choosing
  a new policy. Continue independent work where possible.

This maintenance guidance does not authorize unrelated edits, historical evidence
rewrites, changes to user-installed skills, or new background automation.

@RTK.md

## RTK command output

Read [RTK.md](RTK.md) for RTK output guidance. When RTK is installed, use
`rtk git`, `rtk cargo`, and `rtk rg` for supported commands. The project Codex
hook in `.codex/hooks.json` targets Bash; PowerShell sessions must invoke RTK
explicitly. Use the original command or `rtk bypass` when full output is needed
for correctness checks or raw benchmark evidence. RTK is optional developer
tooling, not a build dependency. Check installation with `rtk --version` and
recorded savings with `rtk gain`.

## Context Mode

Context Mode is optional local MCP tooling; see [setup and verification](docs/context-mode.md).
When its `ctx_*` tools are available, use `ctx_execute` / `ctx_execute_file` to
filter or aggregate large logs and data, and `ctx_index` / `ctx_search` for
repeated queries over long documents or captured output. Return focused findings
with source paths and relevant errors. Use descriptive source labels and refresh
indexed content after its source changes; search results do not prove completeness.

Keep Graphify first for structural code navigation and RTK for supported commands.
Read source directly when preparing edits or verifying a contract. Small reads,
normal edits, native browser tools and authoritative documentation tools remain
appropriate. Preserve full test failures, exit codes and raw benchmark artifacts;
Context Mode summaries never replace validation or provenance. Run dependent or
state-changing commands sequentially. On Windows, prefer JavaScript with absolute
paths and an explicit child-process cwd; inspect the available tool schema and
host shell before using shell snippets.

After compaction, search any previously indexed task notes before repeating work,
then verify them against current files and Git state. Explicit MCP routing does
not automatically capture session history. If tools are absent or fail, continue
with scoped reads and RTK and report the limitation. Do not install blocking hooks,
bulk-index the repository, or change user-installed skills as a routine fallback.

## Agent skills

### Issue tracker

Track issues and specs in GitHub Issues for `jsmatfess/chopper`.
Read `docs/agents/issue-tracker.md` before issue operations.

### Triage labels

Use the five default triage labels.
Read `docs/agents/triage-labels.md` when triaging issues.

### Domain docs

Use a single-context glossary and ADR layout.
Read `docs/agents/domain.md` before domain exploration.
