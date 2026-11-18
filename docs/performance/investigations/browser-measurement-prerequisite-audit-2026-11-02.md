## Browser measurement prerequisite audit (2026-11-02)

A bounded read-only audit found neither original `grouping-comparison-001` nor
`gc-browser-retry` failure tree, nor `workload-baseline-final` build records, in
the three available Windows Chopper checkouts. The earlier recorded launch error
and copied verification-artifact failure remain historical observations; missing
logs cannot establish their causes or an engine defect.

The retained resident checkout has Windows Node 22.23.4 and installed Chrome/Edge
executables, but lacks checkout-local Playwright/esbuild packages, the discovered
WASI SDK 33 compiler/archive tools, the installed `wasm32-wasip1` Rust target,
hosted engine/workers and completed browser build provenance. Package absence
prevents resolving bundled Chromium through Playwright; no browser was launched.
The first audit script incorrectly imported a Windows absolute path as an ESM
specifier; a separately retained v2 uses a file URL and confirms missing package
resolution. This probe defect is unrelated to the historical launch failure.

Current `workload-baselines.py` generates verifier arguments and declared artifacts
from the same record path. `run-workload-browser.mjs` requires fresh output/profile
paths and checks all three hosted assets against completed build provenance.
No current harness defect is established by the absent copied manifest. Fresh
plans must be generated for their actual output roots; do not transplant old
plans. The controller remains native-only. Browser measurements are blocked
pending restored prerequisites, fresh reviewed build/execution manifests and a
supported execution boundary. No controller adaptation, measurement, deployment,
installation or security change was performed. Audit source/output identities
are retained in the [control record](../../evidence-originals.md#sha256-ee2d0aac8fd1bc6fb9c1b4efad1f18646cfbb141b67abef17a83254f7ae82843).
