## Abrupt browser process termination and recovery (2026-10-22)

The browser acceptance gap was recovery after abrupt process termination rather
than the normal saved-profile shutdown already covered. Harness contract v4 adds
`node scripts/test-browser-termination.mjs --persistent --process-kill`. It pauses
five real production jobs at preparation, CSV write before close, after one CSV
closes, marker write before close and committed marker close before reply. The
browser PID comes from that test-owned browser's CDP session. Node sends
`SIGKILL` (`TerminateProcess` on Windows) without requesting graceful shutdown;
process-existence checks and browser disconnection must both confirm exit before
relaunching the same disposable profile and origin with a different browser PID.
The harness never selects a process by name or accepts an external PID/profile.

The [development pass](../../evidence-originals.md#sha256-fe5acf4654abdf4ec18ea7e27282e0afe285aec472e9f395a22e8a54167e4a95 "Original: docs/benchmarks/browser-process-kill-development-2026-10-21.json")
completes all five checkpoints. Windows Chromium retains the exact pending
`part-00000001.csv.crswap` (27 bytes) and
`CHOPPER-COMPLETE.json.crswap` (67 bytes) after forced termination/relaunch; these
are open transactions, not committed results. The normal shutdown pass had
removed the pending marker transaction. The forced-termination verifier permits
only the exact paused target's known transaction filename and control payload
size/hash, plus its empty target entry. It still requires invalid markers before
commit and exact preservation of every committed CSV/manifest/marker. Other entries remain in the exact comparison; changed committed bytes fail it. Raw before/restart/cleanup
snapshots retain these transaction files rather than hiding or deleting them.

The [final thirteen-command validation](../../evidence-originals.md#sha256-4cc2f8b14dfbde35ef361139d1df8855051f53338b946d28f93712d6b183ec3d "Original: docs/benchmarks/browser-process-kill-validation-2026-10-21.json")
passes script syntax, 28 UI tests/build, production WASI/hosted builds, 25 standard
Chromium contracts, bridge/peer cleanup, temporary and normal persistent
interruption suites, the forced-process mode, and final test-free hosted packaging.
Its forced-termination report at `/commands/11/output` confirms five retained
workspaces with released locks, removal of exactly five abandoned workspaces,
unchanged earlier successful exports, and a fresh complete job after recovery
with exact CSV hashes/marker parity. That new job also leaves every interrupted
and completed folder unchanged. The disposable profile and test-owned entries
are removed. Failed-report diagnostics now retain observed checkpoints too.
CI and maintained browser commands include the new mode.

Both records pin dirty tracked/nonignored untracked compilation sources,
including vendor inputs, and harness identities; each harness report pins the
production WASM/workers, route-only fixture/pause sources and browser version.
Final validation sources remain unchanged and packaging contains no test assets.
Production engine/UI sources are unchanged by this harness work; no fresh full
native Rust test/Clippy claim or performance comparison is added. This establishes
forced browser-process termination at these checkpoints on this Windows Chromium
build, not arbitrary crash timing, power-loss durability, external destinations,
quota/device faults or cross-instance memory admission. The broader TODO remains
open and no product defaults change.
