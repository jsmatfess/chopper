# Contributing to Chopper

Start with the [README setup](README.md#build-the-cli-from-source), [architecture and development entry
points](docs/architecture.md) and [maintainer guide](docs/maintainer/README.md). Run commands
from the repository root. [AGENTS.md](AGENTS.md#build-and-verification) routes the
standard checks; command definitions live in `Cargo.toml`, `ui/package.json`,
`scripts/` and [CI](.github/workflows/ci.yml).

The [specification](docs/specification.md) and [rewrite rules](docs/pipeline-rewrites.md)
describe current contracts. Preserve pipeline semantics, exact membership, serialized CSV
caps and admitted ownership; native atomic publication and browser completion
markers have distinct failure/cancellation contracts. The [Auto brief](docs/maintainer/auto-mode-and-maintainability.md)
describes future work, not delivered behavior. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active
backlog and specs; [tracker guidance](docs/agents/issue-tracker.md) covers issue
operations. Dated research and external handoffs do not add tasks.

For Linux/WSL development paired with native Windows builds and benchmarks, use
[the two-checkout workflow](docs/windows-wsl-workflow.md). Keep platform toolchains,
build outputs and measured data on their own filesystems.

## Choose the checks for your change

When changing Run dispatch, resource resolution/admission, spill/retry boundaries,
rewrite eligibility or Auto policy delivery, update the affected
[execution decision diagrams](docs/execution-decisions.md) alongside the owning
contracts. Review success and failure branches and current-versus-designed status.

| Changed surface | Applicable checks and owning guidance |
| --- | --- |
| Rust engine, native CLI or storage | `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace --locked`; add focused coverage for changed contracts. See [implementation boundaries and ownership](AGENTS.md#implementation-boundaries). |
| Portable `chopper-core` | Rust checks above plus `rustup target add wasm32-unknown-unknown` when needed and `cargo check --locked -p chopper-core --target wasm32-unknown-unknown`. |
| Surviving optional Rust features | `cargo clippy --workspace --all-targets --all-features -- -D warnings` and `cargo test --workspace --locked --all-features`, plus isolated feature checks when needed to exercise a changed path. Features remain opt-in. |
| Hosted UI TypeScript | Install dependencies with `npm --prefix ui ci` when needed and typecheck with `npm --prefix ui run check`; UI tests run in the browser job. For hosted output, build the WASI engine first, then run `npm --prefix ui run build:hosted`; see [browser setup](docs/browser.md#local-development). For hosted workspace interaction changes, also run `npm --prefix ui run test:workspace` ([mocked DOM coverage and prerequisites](docs/browser.md#hosted-workspace-127)). |
| Hosted engine or browser workers | Follow the complete [browser acceptance sequence](AGENTS.md#build-and-verification) and [browser prerequisites, harness modes and limits](docs/browser.md#tests), including resource and interruption checks. After test builds, run `node scripts/build-browser.mjs` without feature flags, then `npm --prefix ui run build:hosted` to prepare test-free `ui/dist`. Preserve the production export guard. |
| Browser resource reactor build/routing | Run `node --test scripts/browser-resource-routing.test.mjs` and `python3 scripts/test-package-release.py` for fake-only routing, missing/wrong variant, production restore and packaging controls. These compile test JavaScript and synthetic production fixtures, without a browser or WASM execution; real acceptance remains separate. |
| Hosted graph acceptance harnesses | Run `node --test scripts/browser-acceptance.test.mjs`, then each affected graph harness (including lifecycle `--composed`) against the production hosted build; see [browser tests](docs/browser.md#tests). Keep fixture assertions and fault routes local to their harness. |
| Protected installed SMALL browser orchestration | Run `python3 scripts/test-browser-small-runner.py`, `python3 scripts/test-validation-runner.py`, `node --test scripts/browser-small-bootstrap.test.mjs scripts/browser-small-observer.test.mjs`, `node --test --test-skip-pattern='real ' scripts/browser-acceptance.test.mjs` and `python3 scripts/test-ci-scope.py` for fake-only controls. Shared `browser-small-windows.py` FFI changes also run `python3 -B scripts/test-hosted-qualification.py` for its [hosted-picker FFI/census callers](scripts/test-hosted-qualification.py). Parent-owned guarded Windows execution and packet approval remain separate; see [packet/guard contract](docs/browser.md#protected-small-installed-contracts-121). |
| Browser scale acceptance orchestration | Run `python3 scripts/test-scale-acceptance-browser-scale.py` and `node scripts/test-scale-acceptance-browser-scale.mjs scratch/new-scale-controls` with a fresh owned evidence directory. These fake controls run in the tooling job; actual installed-browser and scale execution require their separate frozen plan and approval. |
| Evidence, audit scripts or evidence links | Run the [read-only evidence checks](docs/benchmarks/README.md#evidence-checks). Refresh derived outputs only after reviewing intended source changes; preserve raw evidence/source snapshots byte-for-byte. |
| Local release packaging | `python3 scripts/test-package-release.py`; Python 3.11+ and Node required. For actual native archives, run the [extracted-package smoke](docs/release-packaging.md#extracted-native-smoke) on each supported host. |
| Saved Job schema or decoder | After building the native CLI, install `scripts/requirements-job-schema.txt` and run `python3 scripts/test-job-schema.py target/debug/chopper` (use the actual binary path). The [Job guide](docs/job-json.md#verify-the-release-schema) covers tagged-download verification. |
| Native CLI help or Job recipes | Build with `cargo build --release --locked -p chopper`, then run `python3 scripts/cli-reference.py target/release/chopper --check` and `python3 scripts/test-job-recipes.py target/release/chopper`. Omit `--check` to regenerate the reference. On Windows, use `python` and `target/release/chopper.exe`. |
| Documentation or CI routing | Review links, actual command options and workflow syntax; execute newly routed checks. Documentation alone does not require a full engine rebuild. |

Run the applicable checks above while developing; the [CI policy](docs/ci.md)
defines local delivery and hosted merge gates. Use `python3 scripts/local-ci.py check`
to execute the workflow YAML with act, and `python3 scripts/local-ci.py land` for authorized
delivery to main. Install the push guard in each delivery clone and connect its
Windows checkout; see the policy for receipt rules and existing-hook integration.
The retained workflow declares PR/main validation and manual dispatch, but GitHub
CI is disabled by owner decision because Actions minutes are exhausted. Use
`local-ci.py land` and the required exact Linux/native Windows receipts as the
sole CI delivery gate. Product and release acceptance remain required. Do not
re-enable or dispatch hosted CI without a new owner restoration instruction;
[#21](https://github.com/jsmatfess/chopper/issues/21) remains deferred. See
[CI policy](docs/ci.md) for the full local procedure and future restoration gates.

The workflow file retains configured native checks and full hosted acceptance;
macOS source availability does not qualify it as a supported release platform.
One Ubuntu job runs the surviving
features together with all-feature Clippy/tests, and a separate evidence job checks
derived files without rewriting them. This bounded combination does not establish
every isolated feature combination, every browser feature or platform execution.
Report checks actually run, reused identities and blocked prerequisites separately;
[validation.md](docs/validation.md) owns supported platform and scale claims.
Archived originals use explicit hash-verified hydration under the
[storage access boundary](docs/evidence-storage.md#archived-original-alias-resolution).
Historical evidence CI requires the private reader when those originals are
absent; forks without that access remain blocked and need trusted maintainer
validation. Do not pass private credentials or originals to untrusted fork code.
For unattended sequential checks with durable logs and conservative resume, use
the [local validation runner](docs/validation-runner.md); declare the batch's inputs,
artifacts, toolchains and scheduling limits before launch.

## Evidence and project metadata

The repository includes the [chopper-benchmarks skill](.agents/skills/chopper-benchmarks/SKILL.md)
in `.agents/skills/`, the repository skill directory used by Codex. Invoke it with
`$chopper-benchmarks`, for example: "Use $chopper-benchmarks to compare the existing
native shuffle results." For unattended end-to-end investigations, pair it with
[$chopper-unattended](.agents/skills/chopper-unattended/SKILL.md), which maintains
the overall objective and cumulative budget across experiment and PR checkpoints.
It supports evidence analysis and targeted experiments;
the maintained benchmark rules remain in the documents below.

Find existing runs through the [benchmark guide and catalog](docs/benchmarks/README.md)
before proposing experiments. Follow its provenance, matched-comparison and failed-run
rules and the [experiment criteria](docs/performance-opportunities.md#acceptance-for-experiments).
Contract timings, working-allocation accounting, RSS and physical I/O are distinct.
Do not run broad matrices or reinterpret historical measurements for routine cleanup.

Workspace packages declare `MIT` in `Cargo.toml`; the root [LICENSE](LICENSE)
contains the project license with the owner's confirmed copyright wording.
Preserve the separate upstream license and attribution files in vendor sources.
