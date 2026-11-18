## Zstandard modern and legacy input allocation ownership (2026-10-23)

The [`input owner`](../../../crates/chopper/src/engine/input_zstandard.rs) now admits
Zstandard CSV input allocations through synchronous callbacks, including an
aligned layout header for each C block. It retains simultaneous live storage
and releases grants after deallocation. Source buffers and reader/controller
boxes keep separate owners. The zstd-rs reader state machine and raw decoder
call sequence remain in use, preserving initialization, reset, EOF, window
limits and format detection. Footprint can grow after consumer entry; tight
budgets may now deny storage that was formerly uncharged.

The [pinned C bridge](../../../vendor/zstd-sys-2.1.1/CHOPPER.md) forwards allocator
callbacks into buffered legacy 0.4-0.7 contexts. It cleans up failed inner
construction and clears the freed prior-version pointer before a fallible
replacement, preventing repeated destruction after denial. The
[source audit](../../evidence-originals.md#sha256-69c495229aa2e0fff583f1616d1a9fb5eb21ac61f1d12743f00be2e08ade74db "Original: docs/benchmarks/zstandard-input-source-audit-2026-10-23.json") preserves
upstream package/file hashes, eleven changed upstream files and added bridge/
fixture hashes. The vendored backend is required; system substitution cannot
silently bypass the allocator path. The [ownership contract](../../resource-policy-research.md#zstandard-input-streaming-allocation-ownership-2026-10-23)
keeps allocator usable-size, runtime and other application storage separate.

The retained upstream corpus covers four legacy versions and one modern 0.8
control. Fault injection denies all eighteen observed context/buffer allocation
requests, including version switches and partial construction, with zero final
payload/header grants. Five individual frames have thirty exact local/shared
edges, EOF/drop ownership, competitor release/retry and partial consumer failure.
Modern concatenation adds six edges, two faults, skippable-frame parity,
window-limit/detection preservation, truncation and public-profile cancellation
after 65,536 decoded rows. Larger direct destinations can avoid internal buffers;
edge/retry baselines therefore use a matched `read_to_end` pattern.

The [initial Windows record](../../evidence-originals.md#sha256-f51c8d1248222deac2f40d9e3966def8346cab79a94122b615befd62aeccff92 "Original: docs/benchmarks/zstandard-input-validation-2026-10-23.json")
passes 253 default workspace tests, 310 combined-feature Chopper tests,
formatting/default and combined Clippy, UI's 28 tests/build and native release.
Its first WASI run completes the Rust controls but fails in the browser receiver:
the dynamic case omitted the common shared-edge report fields. The
[17-command follow-up](../../evidence-originals.md#sha256-15a400cc1acbf0d76ec0e9d94eda6f7b279f3de6e889e23691b0618db3a93ad7 "Original: docs/benchmarks/zstandard-input-report-followup-2026-10-23.json")
records the sole changed compilation input: those test-report JSON fields.
Production/C ownership code remains unchanged. Focused default/combined native
contracts and native adapter checks pass, followed by Chromium, installed Chrome
and Edge resource contracts. The production WASI rebuild passes 25 standard
Chromium contracts and final test-free packaging. The
[six-command Linux native record](../../evidence-originals.md#sha256-f6de6c30d86b35babb22e1ef4d3b75e523caf2267546ccdf27b07942aceb9a17 "Original: docs/benchmarks/zstandard-input-linux-validation-2026-10-23.json")
passes independently; a [three-command report follow-up](../../evidence-originals.md#sha256-4fa9b97e9128d3d582f04f8c35b0aed3a4eaddda1db79df3539f25eb6fb0d6bc "Original: docs/benchmarks/zstandard-input-linux-report-followup-2026-10-23.json")
checks the corrected fixture metadata. Each pass retains its own unchanged
source inventory; these are not cumulative test counts or one identical snapshot.

The separate [C AddressSanitizer pass](../../evidence-originals.md#sha256-bebfcbf61873649b169e07a4fd643f6ddffe0b33536785495b70f8b00d5f990d "Original: docs/benchmarks/zstandard-input-c-asan-2026-10-23.json")
builds a Linux/WSL target with C dependency instrumentation, then runs the
decoder's shared allocation-fault/edge/cancellation test with leak detection and
abort-on-error enabled. Both commands pass. Rust code/stdlib are not Rust
sanitizer-instrumented. This uses the pre-report-fix source; C and ownership
implementation are unchanged by that JSON-only correction.

The [unpatched/patched CLI comparison](../../evidence-originals.md#sha256-79636a214f8d39145d3d70429cfdf3113b58fe9e687b577f67d27b3a32e2ccc4 "Original: docs/benchmarks/zstandard-input-native-compatibility-2026-10-23.json")
pins its retained baseline to the prior package hash. Eight valid fixtures cover
all versions, skippable prefixes, individual frames and reverse/reused version
transitions: exact CSV hashes, per-output records, fields/order and row/byte caps
match. Five truncated fixtures fail without publication in both builds. All 26
commands and fixture cleanup are retained. The
[initial verifier configuration](../../evidence-originals.md#sha256-15bf84ce7a84d2667ae31955b1cba50cbebb9c595092baee675fb96ca1078592 "Original: docs/benchmarks/zstandard-input-native-parity-2026-10-23.json")
was rejected before processing because its default record ceiling did not fit
the chosen 32 MiB job budget; the corrected verifier explicitly uses a 1 MiB
record ceiling and preserves the failed attempt.

The [package identities](../../evidence-originals.md#sha256-74293566830272ec72ae2edbff0241e8e137b0d529ac91cc7949c1113dcb9a55 "Original: docs/benchmarks/zstandard-input-package-identities-2026-10-23.json")
pin the two focused native test executables, release binary, seven final hosted
assets and absent production resource-test export. C payload peaks and requested
working grants remain distinct from RSS. These small deterministic fixtures add
no performance, physical-I/O, arbitrary-input, large-job or device claim. The
local build is not the published Pages artifact; macOS stays deferred. Remaining
allocation/application/platform work stays in [TODO](../../../TODO.md).
