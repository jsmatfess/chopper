## Persistent browser interruption and restart recovery (2026-10-21)

The next browser acceptance decision was whether the production-worker cleanup
and completion-marker checks hold in a saved browser profile and after a browser
restart. [`test-browser-termination.mjs --persistent`](../../../scripts/test-browser-termination.mjs)
now runs the ten-case interruption suite in a disposable persistent Chromium
profile. Contract v3 retains the temporary-context mode. Both modes exercise the
same production client/WASM/workers and test-only pause hooks; no engine,
admission policy or product default changes.

The persistent mode adds three simultaneous real jobs paused during preparation,
after a marker write before close, and after committed marker close before reply.
Peer cleanup skips their active locks. The browser then shuts down and relaunches
with the same saved profile and origin. CDP browser process IDs must differ and
the old browser connection must be closed. All three workspaces survive shutdown
with their file counts intact and locks released; peer cleanup removes exactly
those three. Closed CSV/manifest contents and the final marker state survive
restart and cleanup. The uncommitted marker remains invalid and the completed
folder remains complete with every file hash unchanged. Unrelated entries survive.
Restart recovery here removes abandoned workspaces; resumability remains deferred.

The first [development run](../../evidence-originals.md#sha256-eece9eabbff9ab5921e1c47ab42095a318d6dd915fdc0fa9bb5b088403452238 "Original: docs/benchmarks/browser-persistent-restart-development-2026-10-21.json")
exposed a pending `CHOPPER-COMPLETE.json.crswap` entry with the 67-byte pending
marker payload while its writable was open. It disappears when the browser
aborts that transaction at shutdown. The initial assertion incorrectly required
all directory entries, including that uncommitted transaction file, to persist.
The final control compares all closed result files and the final marker strictly,
and records the pending file separately. Only that exact transaction filename is
eligible for normalization, and its size/hash must match the known pending marker
text. Unexpected entries or changed committed bytes still fail. Before/after
snapshots and the initial failed attempt are preserved. This is an observed
Chromium transaction detail, not a production cleanup rule or permission to
delete arbitrary files with a similar suffix.

The [final validation](../../evidence-originals.md#sha256-8eaac7eee9fe2b8105d9afd783af1c94fba40e3ce5e38ce2ce49bbfe34e02ace "Original: docs/benchmarks/browser-persistent-restart-validation-2026-10-21.json")
passes twelve commands: syntax, 28 UI tests/build, a fresh production WASI/hosted
build, both interruption contexts, 25 standard Chromium contracts, bridge/peer
cleanup and final production packaging. The temporary report is in
`/commands/5/output`, the persistent report in `/commands/6/output`. WASM and both
worker hashes, fixture/pause bundle identities and successful CSV hashes match
between modes. The persistent report includes different browser process IDs and
complete restart snapshots. Compilation-source identities remain unchanged;
production assets are unmodified by the harness and test assets are removed.
The task-owned profile is created under the OS temp directory and removed only
after its resolved parent/name checks and browser shutdown. No existing user
profile is read or deleted. CI and maintained validation commands include this mode.

Coverage is Windows Chromium 156.0.8078.4 with small controlled workloads. A saved
profile and normal shutdown/relaunch do not establish origin persistence
permission, quota-eviction resistance, process-crash/power-loss durability,
external destinations, physical SSD throughput or a shared memory/RSS cap.
No new timings are treated as performance samples and no native Rust workspace/
Clippy pass is claimed for this harness-only change. Other TODO requirements
remain open.
