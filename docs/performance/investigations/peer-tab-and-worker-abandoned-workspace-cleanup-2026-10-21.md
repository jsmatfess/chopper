## Peer tab and worker abandoned-workspace cleanup (2026-10-21)

The [real Chromium contract](../../evidence-originals.md#sha256-eaa92b13347d0836c6f5e6f75bb029443668a1f5bec3f3dec96be619d579d558 "Original: docs/benchmarks/browser-peer-cleanup-2026-10-21.json")
exercises the production abandoned-workspace cleaner in two same-origin tabs and
a dedicated worker, using actual Web Locks and OPFS in a fresh temporary browser
context. The worker holds a synchronous access handle while its workspace is
locked. An initial cleanup removes only the abandoned directory, preserving both
active workspaces. After worker termination, its lock/handle releases and cleanup
removes exactly that workspace while retaining the active tab. Closing the peer
tab releases its lock and the next cleanup removes exactly that directory.
Unrelated entries and exported results outside the workspace namespace survive
every pass; all test-owned entries are removed at the end.

The production cleanup loop is extracted into
[cleanup.ts](../../../ui/src/browser/cleanup.ts) so the button and browser contract
execute the same function. It now checks directory kind as well as the workspace
name pattern. With the previous name-only condition restored, the contract fails
because a UUID-shaped ordinary file is deleted along with the abandoned directory;
with the guard, the file remains intact. The artifact preserves that failing pass,
the successful report and exact source hashes. Initial harness CSP/worker-header
and unintended app-startup issues are separately identified as harness failures.
The final harness uses same-origin request routes, the hosted isolation/CSP model,
an isolated fixture document and explicit owner lifecycle; it neither weakens
production headers nor writes test assets into the deployable output.

Reproduce with `node scripts/test-browser-cleanup.mjs` after hosted build and
Chromium setup. CI and the maintained validation instructions include this check.
This is deletion-coordination correctness evidence, not a timing comparison,
persistent-profile/device test, shared allocation ledger across workers/tabs,
engine cancellation test or termination-during-export acceptance. Those separate
resource and destination-lifecycle gaps remain in [TODO](../../../TODO.md).

The [final follow-up validation](../../evidence-originals.md#sha256-8235925254aeb5c8178902e8179b4b1db6b026041c069dd8be287650ad55bf35 "Original: docs/benchmarks/current-todo-validation-2026-10-21.json")
records 15 benchmark/provenance and four catalog checks, 28 UI tests, native UI
and debug engine builds, 25 standard Chromium contracts, bridge, peer cleanup
and both base/candidate WASI resource reactors. Clean hosted packaging passes
the production export guard with no test assets. Production WASM retains hash
`c18a5139ebb5c0b960ad84cd5f62794f055cca66fbb23922bfc2615dfaa18ea3`.
These are separate validation passes, not additional timing samples or a new
full Rust workspace/macOS/deployment/scale acceptance claim.
