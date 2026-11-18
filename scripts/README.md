# Build, validation and experiment commands

Use the current [development checks](../CONTRIBUTING.md) and owning guides before
running a script. Names in old performance narratives describe their recorded
source trees; they are not a list of current engine capabilities.

| Purpose | Current entry point and contract |
| --- | --- |
| Browser engine | `node scripts/build-browser.mjs`; the Bash alias uses the same Node implementation. Feature flags are supported; use `CARGO_TARGET_DIR` for output placement. [Browser build contract](../docs/browser.md#local-development). |
| Hosted package | `npm --prefix ui run build:hosted`, after restoring the default production engine. [Packaging and test boundaries](../docs/browser.md). |
| Hosted step motion | `node scripts/test-browser-step-motion.mjs` after the default hosted build; real observed shuffle strategies, live materialization rows/time, themes, pause/reduced motion and terminal stop. [Browser setup](../docs/browser.md#local-development). |
| Hosted value distributions | `node scripts/test-browser-value-shares.mjs` after the default browser build; real profiling/preparation counts, bounded high-cardinality omission, themes and mobile layout. [Browser setup](../docs/browser.md#local-development). |
| Durable sequential checks | `python3 scripts/validation-runner.py PLAN BATCH`; declare inputs, artifacts and deadlines. [Lifecycle and resume](../docs/validation-runner.md#local-batch-execution). |
| Local workflow gate | `python3 scripts/local-ci.py check`. Landing requires separate authorization and `local-ci.py land`. [CI policy](../docs/ci.md). |
| Release preparation/acceptance | Use the profile's owning [preparation](../docs/validation-runner.md#actual-host-acceptance-preflight) and [qualification](../docs/hosted-tiny-qualification.md) commands. Source controls do not grant actual-host or scale acceptance. |
| Performance work | Follow the [benchmark guide](../docs/benchmarks/README.md), current decision registry and named experiment's provenance. No harness matrix is authorized implicitly. |
| Hosted memory experiment | `node scripts/benchmark-hosted-memory.mjs BASELINE.wasm CANDIDATE.wasm OUTPUT MODE`; explicitly select `pilot`, `paired`, `control` or `resident`. [Measurement and verification boundary](../docs/benchmarks/README.md#bounded-random-draw-comparisons). |

The [historical shuffle source archive](../docs/history/shuffle-harnesses-2026-11-16/README.md)
contains `benchmark-flexible.py`, `benchmark-allocation-ranges.py`,
`validate-allocation-ranges.py`, `validate-partition-first.py`,
`benchmark-partition-first.py`, `benchmark-random-buckets.py`,
`benchmark-fast-rng.py`, `followup-bucket-window.py` and
`reproduce-bucket-window.py`. Their original bytes/hashes and evidence references
are preserved. They can emit removed schemas and require their recorded engines;
they are not current-main benchmark entry points.
