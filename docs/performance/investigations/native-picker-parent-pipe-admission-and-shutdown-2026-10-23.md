## Native picker parent pipe admission and shutdown (2026-10-23)

Native server picker capture now admits stdout/stderr Vec growth and old/new
replacement overlap through the process pool, retains each buffer through
consumption and decodes selection JSON with the admitted catalog helper. Separate
readers drain both pipes; directly owned helper processes are stopped/reaped on
capture failure or shutdown. Failed-helper errors retain admitted raw stderr and
stream UTF-8 replacement text, preserving the original message without an
unadmitted full formatting/lossy copy. The
[ownership/lifecycle contract](../../resource-policy-research.md#native-picker-parent-capture-and-lifecycle-2026-10-23)
records buffer, error, child-guard and gate release ordering.

Three focused controls cover six local/shared growth boundaries, competing pipe
release/retry, read-failure release and independent pipe/error-reader lifetimes.
The Cursor fixture retains 32,768 bytes after a 49,152-byte replacement-overlap
peak; real pipe capacities are checked from their actual allocations rather
than assuming OS read sizes. All 65,536 two-byte combinations and representative
longer invalid UTF-8 sequences match the original lossy text; encoded JSON stays
exact. A Rust-compiled test helper exercises success, dialog-cancel JSON,
malformed output, failed status/invalid stderr and simultaneous 256 KiB stdout/
stderr. Further controls deny/retry JSON decoding, force shared admission denial,
stop/reap a continuously writing helper, release failed-spawn sessions, cancel a
sleeping helper when its Owner drops and prevent post-close spawning. All parent
payload grants and task-owned fixture directories release.

An [initial shutdown implementation](../../evidence-originals.md#sha256-55b0a2aaa8e26c6dce3bd2d947659ee29e95aa3f714f0aacfaf2a6bfb1340100 "Original: docs/benchmarks/picker-shutdown-incomplete-request-development-2026-10-23.json")
waited for the whole picker busy flag and hung after SIGINT while a request body
was incomplete. The replacement registers only actual helper sessions, before
spawn, and closes that gate before waiting. An
[early follow-up timeout](../../evidence-originals.md#sha256-7cfcc887a6dad097746194eaba93e1a9850a3ec615d75f6ce4c370d8c3adc116 "Original: docs/benchmarks/picker-shutdown-readiness-development-2026-10-23.json")
failed to establish the busy precondition; it did not test shutdown. A subsequent
[ready-server control](../../evidence-originals.md#sha256-410506cb694e062d890d1773d43dcdc34b80787a16c9c0b36f3efd1618655807 "Original: docs/benchmarks/picker-shutdown-incomplete-request-validation-2026-10-23.json")
and [final-source replay](../../evidence-originals.md#sha256-f4c836e48d9edadff92cefa5fe271cdeb88e925695fadd8d5be0fd770a3cdc29 "Original: docs/benchmarks/picker-shutdown-incomplete-request-pipe-eof-validation-2026-10-23.json")
confirm HTTP 200 readiness and HTTP 409 busy, then successful server exit on
SIGINT before the one-byte partial body reaches EOF. No actual native dialog is
opened by this control. These development records remain distinct from final
acceptance.

A final [pipe-EOF regression](../../evidence-originals.md#sha256-7fcdd147bc0f7b3c71d4e43316cc6980badbedaedb3d29e748346bbb49473f6f "Original: docs/benchmarks/picker-capture-pipe-eof-development-2026-10-23.json")
closes stdout/stderr OS handles while leaving the helper alive. The initial
blocking final wait ignored shutdown after EOF and returned only at the fixture's
30-second watchdog. The corrected wait polls process exit and cancellation after
both pipe readers finish, preserving the primary error and direct-child reaping.
The same control now passes on Windows and Linux. Earlier completed
[Windows](../../evidence-originals.md#sha256-12971573822d505ed4ff05fc04a15726c25c0f2b9014cea2ba83f15fe180defe "Original: docs/benchmarks/picker-capture-validation-2026-10-23.json"),
[Linux](../../evidence-originals.md#sha256-acab6dd4191569f50113c7ef7f55bdfe77cefd7f247101042b52701423b9504a "Original: docs/benchmarks/picker-capture-linux-validation-2026-10-23.json"),
[server](../../evidence-originals.md#sha256-c4c39bfadec69c825457d173659f0e6ad16c972e7f28cf1462d792d1bc4f5776 "Original: docs/benchmarks/picker-capture-server-parity-2026-10-23.json") and
[package](../../evidence-originals.md#sha256-2246c887700dee7075d1b72f2897eb23eda3344644ec8afa409166296c837283 "Original: docs/benchmarks/picker-capture-package-identities-2026-10-23.json") records are
preserved as pre-EOF-fix snapshots, rather than overwritten.

[Windows validation](../../evidence-originals.md#sha256-2735e6643c932d486dd81bac93332a88fcba47c36faab7bdb06a71dfdb890830 "Original: docs/benchmarks/picker-capture-final-validation-2026-10-23.json")
and [Linux/WSL validation](../../evidence-originals.md#sha256-2cac8912527b4d374756d34c5980e5e0bb208a817ff103da401a8791e1a4b798 "Original: docs/benchmarks/picker-capture-linux-final-validation-2026-10-23.json")
record default/combined native checks and the focused picker controls. Windows
also records all-feature compilation, UI tests/build, the release build and the
serde_json feature graph. Linux additionally builds the normal server and runs
the incomplete-body shutdown replay. All 11 Windows and nine Linux commands
pass with unchanged source inventories. Windows defaults/combined features pass
296/350 tests including nine doc tests; Linux passes 299/353 including nine doc
tests. Each platform separately passes the three focused picker controls;
Windows also passes all 28 UI tests. Counts describe these snapshots rather than
additional independent coverage when the same test is run in several commands.
[Retained-server parity](../../evidence-originals.md#sha256-cffeb8567b6707d4445a66dc3fae2a496c61e41551a858e1daac502574044e4e "Original: docs/benchmarks/picker-capture-final-server-parity-2026-10-23.json")
checks original defaults, request errors/limits, profile/prepare/cancel/retry,
strict-cap publication and invalid picker modes without opening dialogs; repeated
invalid requests verify the busy flag clears.
[Package identities and harness sources](../../evidence-originals.md#sha256-83788148ac6f8b2f8438a26ad64db0671f693f7d1bcbca552f13a8f355fd56b4 "Original: docs/benchmarks/picker-capture-final-package-identities-2026-10-23.json")
pin native binaries and verify all seven preceding local hosted assets remain
unchanged. The module is excluded from WASI and adds no new hosted/browser,
actual-picker/device, macOS, scale, physical-I/O or performance claim.

This closes parent-owned pipe/selection/error-byte payloads and directly owned
helper shutdown for the tested paths. Helper-process/WSL bridge and command/path
construction, actual dialogs/brokers/descendants, State/progress/error sources,
carriers/channels, native thread stacks and OS/runtime allocations remain
separate. Kill/wait/real-device fault recovery and full process-tree cleanup are
not inferred. Working-allocation admission remains distinct from RSS.
