## Windows Chrome and Edge release acceptance (2026-10-22)

The [47-command pass](../../evidence-originals.md#sha256-087f66139475e1e1e0b559c3140fd77bb161d2661bcd6da1d1895945b44e860d "Original: docs/benchmarks/shuffle-lineage-and-browser-channels-2026-10-22.json")
checks the same production and test-engine builds in bundled Chromium
156.0.8078.4, installed Chrome 155.0.8059.85 and installed Edge 155.0.4283.62 on
Windows. All commands pass and the recorded source identities remain unchanged.
`CHOPPER_BROWSER_CHANNEL` selects the installed browser in the existing standard,
bridge, peer-cleanup and termination runners. The default stays bundled Chromium;
an unavailable selected browser fails instead of silently switching engines.
Reports record the actual channel/version. All contexts and saved profiles are
test-owned; no existing browser profile is opened or terminated.

Each browser passes 25 standard correctness contracts, the UTF-8 storage-error
bridge, peer-tab/worker deletion coordination, temporary-context interruption,
persistent-profile shutdown/restart and forced process termination/recovery.
The lifecycle tests cover preparation, CSV write before close, after one CSV
closes, marker write before close and committed marker close before reply. They
preserve exact closed CSVs and valid completed exports, reject incomplete markers,
remove unlocked abandoned workspaces and complete a fresh exact-CSV job after
restart. The process-kill mode verifies the PID from its own CDP session, process
exit and disconnection. The disposal checks pass in all three channels.

Each browser also passes base, retained-parent shuffle/partition and flexible
resource-reactor variants. The flexible variant enables partition/allocation
composition, XOF and independent-bucket code, while the new focused lineage
contract checks uniform, Fisher–Yates, buffer and automatic shuffle emission.
Native validation passes formatting, default and combined-feature Clippy, the
default workspace suite (245 tests), the combined-feature Chopper suite (301
tests), 28 UI tests/build, and native/WASI release builds. These are counts from
this pass, not totals added to earlier passes. Final `build:hosted` removes every
test asset and the production WASM has no resource-contract entry point.
[Retained binary identities and packaging](../../evidence-originals.md#sha256-5af2c20c85be3b89ff99656efe69aeaf8b8885ba7579442f609c47bf608f0f78 "Original: docs/benchmarks/shuffle-lineage-browser-packaging-2026-10-22.json")
bind the native tests/release and final hosted assets to this pass.

This extends desktop-browser checkpoint acceptance on this Windows host. It does
not establish physical SSD effects, other devices/OSes, browser RSS bounds, real
quota/device faults, external filesystem destinations, arbitrary crash timing or
power-loss durability. Resource-contract durations are not A/B timing evidence.
This local pass does not validate a hosted deployment; the separate deployed
acceptance below has its own artifact identity. macOS validation is deferred at
the user's request; the [release checklist](../../../TODO.md#release-validation) retains
other platform/device/deployment gaps.
