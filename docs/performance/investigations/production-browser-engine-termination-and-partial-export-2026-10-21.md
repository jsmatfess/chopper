## Production browser engine termination and partial export (2026-10-21)

The remaining browser acceptance gap included actual engine termination/export
timing: the earlier peer-cleanup contract held synthetic locks and a sync handle,
while resource-reactor export tests injected write/finalization rejection. Neither
established the production client's cancellation/tab-close behavior with a live
WASI job and an interrupted CSV export. The new
[`test-browser-termination.mjs`](../../../scripts/test-browser-termination.mjs) resolves
that bounded acceptance decision using the production client source, production
WASM, engine worker and storage worker. It changes no product behavior or defaults.

The harness runs two same-origin pages in a fresh temporary Chromium context,
replaces pickers with fixtures, and uses an OPFS destination outside the temporary
workspace namespace. Request-route-only worker/FSA hooks pause execution at three
actual boundaries: Rust input preparation after 65,536 rows, a completed real CSV
write before its writable closes, and one closed CSV before the next result/marker.
Each boundary is exercised with public-client cancellation and forced tab close.
The hooks neither replace WASM nor add production worker entry points/assets.
These deterministic pauses test selected lifecycle edges, not arbitrary timing
or browser crash/power-loss behavior.

All six interruption cases pass. The preparation fixture records 3,472,886 logical
temporary bytes and two real OPFS file entries at its pause. Active peer cleanup
skips every held workspace lock. Cancellation terminates the engine and lets the
storage owner remove the workspace; a cancelled job cannot run. Each cancellation
case then prepares and completes a new job in the same client/module instance,
with exact CSV rows/order/fields and matching per-file hashes. Tab close leaves
an abandoned workspace, releases its lock, and peer cleanup removes exactly that
one workspace. Unrelated entries and exported result folders remain intact.

Mid-write termination leaves a zero-byte CSV entry on this Chromium build; the
after-close cases preserve one 27-byte CSV. Both also retain the already-closed
manifest. None has `CHOPPER-COMPLETE.json`, including after subsequent workspace
cleanup or same-client retry. A separate successful control writes five CSVs and
a manifest before a valid completion marker, then removes its workspace. All
test-owned destinations/workspaces are removed at the end. These are observed
OPFS semantics for this build, not a general promise about transactional file
sizes on other destinations.

The [final validation](../../evidence-originals.md#sha256-e97308116d5487e7d9c25294ed647b1fd75cb8a034a86ddfb1b9d9d4918acd91 "Original: docs/benchmarks/browser-engine-termination-validation-2026-10-21.json")
passes all eleven commands: harness syntax, 28 UI tests/build, a fresh production
WASI/hosted build, the six-case termination contract plus retries/control,
25 standard Chromium contracts, bridge/peer cleanup and final production packaging.
Compilation-source identities remain unchanged; the termination report pins WASM,
both production workers, harness and pause/fixture bundle hashes and checks that
production artifacts are unmodified. Final packaging excludes all test assets.
The browser is Chromium 156.0.8078.4 on this Windows host. No fresh native Rust
workspace/Clippy pass is claimed: production Rust/TypeScript sources are unchanged.

[Development attempts](../../evidence-originals.md#sha256-72713497f0da979eb71201c74afb4aee9a7e15b360df840f74a4bda98ef12e37 "Original: docs/benchmarks/browser-engine-termination-development-2026-10-21.json")
retain the initial timeout and diagnostic failure from an invalid fixture: the
default 8 MiB record limit did not fit a 32 MiB job's existing 1/16 rule. The fixture
now selects 1 MiB; explicit state polling exposes validation failures promptly.
The first passing pilot paused on manifest writes/closes and is superseded for
CSV timing coverage by the later CSV-specific pass, which also adds same-client
retries. Earlier failures and pilot outputs are preserved, not added as successful
observations. Contract/command durations do not establish performance effects;
logical temporary traffic and OPFS entries do not measure physical SSD I/O or RSS.

CI and the maintained browser validation commands now include this harness.
This closes selected production-engine interruption edges in temporary OPFS.
Persistent-browser and external destinations, marker-finalization termination,
quota/device/process-crash faults, candidate request-pressure injection, shared
memory admission across tabs/instances and other TODO requirements remain open.
