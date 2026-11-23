# Build, validation and experiment commands

Use the current [development checks](../CONTRIBUTING.md) and owning guides before
running a script. Names in old performance narratives describe their recorded
source trees; they are not a list of current engine capabilities.

| Purpose | Current entry point and contract |
| --- | --- |
| Native CLI reference and Job recipes | `python3 scripts/cli-reference.py target/release/chopper --check` and `python3 scripts/test-job-recipes.py target/release/chopper`. Use the native release binary path and omit `--check` to regenerate the [CLI reference](../docs/cli-reference.md). To check actual package bytes, pass the extracted executable and `--quickstart PATH/quickstart` to the [recipe harness](test-job-recipes.py). |
| Browser engine | `node scripts/build-browser.mjs`; the Bash alias uses the same Node implementation. Feature flags are supported; use `CARGO_TARGET_DIR` for output placement. [Browser build contract](../docs/browser.md#local-development). |
| Hosted package | `npm --prefix ui run build:hosted`, after restoring the default production engine. [Packaging and test boundaries](../docs/browser.md). |
| Native release package | `python3 scripts/package-release.py` to assemble, verify and smoke-test release archives. [Packaging and exact-binary smoke](../docs/release-packaging.md). |
| Hosted step motion | `node scripts/test-browser-step-motion.mjs` after the default hosted build; real observed shuffle strategies, live materialization rows/time, themes, pause/reduced motion and terminal stop. [Browser setup](../docs/browser.md#local-development). |
| Hosted value distributions | `node scripts/test-browser-value-shares.mjs` after the default browser build; real profiling/preparation counts, bounded high-cardinality omission, themes and mobile layout. [Browser setup](../docs/browser.md#local-development). |
| Durable sequential checks | `python3 scripts/validation-runner.py PLAN BATCH`; declare inputs, artifacts and deadlines. [Lifecycle and resume](../docs/validation-runner.md#local-batch-execution). |
| Local workflow gate | `python3 scripts/local-ci.py check`. Landing requires separate authorization and `local-ci.py land`. [CI policy](../docs/ci.md). |
| Release preparation/acceptance | Use the profile's owning [preparation](../docs/validation-runner.md#actual-host-acceptance-preflight) and [qualification](../docs/hosted-tiny-qualification.md) commands. Source controls do not grant actual-host or scale acceptance. |
| Performance work | Follow the [benchmark guide](../docs/benchmarks/README.md), current decision registry and named experiment's provenance. No harness matrix is authorized implicitly. |
| Native tool comparison | `python scripts/benchmark-tool-comparison.py --help`; Python environment with DuckDB 2.0.0, explicit Chopper/qsv binaries and fresh work directories. Synthetic eight-file split/shuffle development cells include startup/count/materialization/output and independent field/quota checks. qsv random sort has no matched memory limit. [Evidence and interpretation](../docs/performance/investigations/cross-tool-csv-split-and-shuffle-comparison-2026-11-18.md). Verifier controls: `python3 scripts/test-benchmark-tool-comparison.py`. |
| Hosted memory experiment | `node scripts/benchmark-hosted-memory.mjs BASELINE.wasm CANDIDATE.wasm OUTPUT MODE`; explicitly select `pilot`, `paired`, `control` or `resident`. [Measurement and verification boundary](../docs/benchmarks/README.md#bounded-random-draw-comparisons). |

The [historical shuffle source archive](../docs/history/shuffle-harnesses-2026-11-16/README.md)
contains `benchmark-flexible.py`, `benchmark-allocation-ranges.py`,
`validate-allocation-ranges.py`, `validate-partition-first.py`,
`benchmark-partition-first.py`, `benchmark-random-buckets.py`,
`benchmark-fast-rng.py`, `followup-bucket-window.py` and
`reproduce-bucket-window.py`. Their original bytes/hashes and evidence references
are preserved. They can emit removed schemas and require their recorded engines;
they are not current-main benchmark entry points.

`benchmark-data-movement.py` compares pinned native baseline/candidate binaries
for one explicitly selected Fisher–Yates/Balanced or plain Balanced cell. It
alternates complete Run jobs with an excluded warmup, records process counters,
and independently verifies every output field, ID, quota, lineage and cap before
removing successful payloads. Select `--case` explicitly; `--rows` is for a small
harness smoke check. Source/build identity and admission/publication controls
remain required separately; this harness does not qualify a build or platform.

Drivers containing the removed hosted Prepare/Confirm protocol or the former
native `profile` command are historical replay tools and require their original
pinned build/harness identities. They are not current acceptance commands. Use
the current Analyze/Run acceptance commands in `docs/browser.md` and the matched
Run harness above for new experiments; changing a command name alone can compare
different response/measurement scopes across old and new binaries.
