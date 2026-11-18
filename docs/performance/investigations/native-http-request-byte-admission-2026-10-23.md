## Native HTTP request byte admission (2026-10-23)

[`server/request_body.rs`](../../../crates/chopper/src/server/request_body.rs) now
admits the incoming wire-byte Vec through the shared process pool before copying
from inline scratch. Growth covers old/new overlap, the owner survives JSON
parsing, and successful/error/abandoned owners release data before grants.
Declared payloads above 1 MiB fail before reading; unknown-length streams use at
most one extra byte to detect overflow. The existing size and malformed-JSON
errors remain. Parsed Value/Job trees and parser scratch retain separate scope;
this closes the raw-byte-buffer slice, not all request ownership. The
[ownership contract](../../resource-policy-research.md#native-http-request-byte-buffer-ownership-2026-10-23)
records bounds and failure ordering.

A [first loopback failure](../../evidence-originals.md#sha256-cb21a6b358cbf95823e53154401bde956a55d8ffca8ff530ec4243c72b8e31c4 "Original: docs/benchmarks/native-request-wire-development-2026-10-23.json")
and [instrumented reproduction](../../evidence-originals.md#sha256-3e12bffde6a27dd70c950088c79c79b2d9942b786b3a21e873a0dd0d60ef4a95 "Original: docs/benchmarks/native-request-wire-chunked-development-2026-10-23.json")
identify a zero-capacity chunked upload losing its JSON rejection to Windows
socket error 10053. On admission failure, the implementation now frees the old
buffer/grant, drains only the remaining 1 MiB-plus-one allowance using inline
scratch and returns the original typed denial. Interrupted drain reads retry;
EOF, a read failure or the byte bound stops draining. No new timeout or complete
server-runtime accounting claim is introduced.

A separate [retained-release/debug reproduction](../../evidence-originals.md#sha256-4d197646c987f90544ec732fd256c781452950ec6f699e6c265d1392f9282033 "Original: docs/benchmarks/native-request-expect-development-2026-10-23.json")
and [red regression](../../evidence-originals.md#sha256-1dc2603c146bd9c21b88011c1a0975862968f4c4548fbee99784066627e9ea95 "Original: docs/benchmarks/native-request-expect-regression-development-2026-10-23.json")
showed oversized Expect requests incorrectly receiving `100 Continue` before
rejection. Length validation now runs before tiny_http::Request::as_reader,
restoring the prior direct 400 response without requesting any body bytes.
The [initial complete pass and copied build](../../evidence-originals.md#sha256-4b37857a1529e8fed2c471b353a1208ef629fc3e80bb5e13759e35869d567f01 "Original: docs/benchmarks/native-request-wire-pre-expect-identities-2026-10-23.json")
remain distinct from final validation after this ordering fix.

Six focused controls cover six local/shared replacement-overlap edges,
competing-owner release/retry, interrupted and partial-failure reads,
malformed UTF-8/JSON and empty input, declared/unknown-length limits, concurrent
abandonment, release before bounded drain and preservation of the original error
when draining fails. Real fixed/chunked loopback requests and the zero-pool
chunked rejection pass. The representative request retains 32,768 bytes with a
49,152-byte replacement-overlap peak. These are requested working capacities,
not allocator usable-size or RSS observations.

[Windows validation](../../evidence-originals.md#sha256-90e5184d861bf0b149c5e4c54122e96268ed8379f00f1473104ced65f4c92509 "Original: docs/benchmarks/native-request-wire-final-validation-2026-10-23.json")
and [Linux/WSL validation](../../evidence-originals.md#sha256-81149e5ed0ee5d1206af61d1456f2c8c51b152752c0cd883c1d1cf329d6f6b63 "Original: docs/benchmarks/native-request-wire-linux-final-validation-2026-10-23.json")
record default/combined native checks and focused contracts. All ten Windows
commands pass: default/combined suites pass 273/330 tests plus nine doctests each,
all-feature compilation, 28 UI tests/build and the native release build.
All seven Linux commands pass: 276/333 tests plus nine doctests each and the six
focused request contracts.
[Real-server retained-binary parity](../../evidence-originals.md#sha256-9a15d67d035930f2e5104cb11b433a10db92a97a828d0a9eff43767df201adce "Original: docs/benchmarks/native-request-server-parity-2026-10-23.json")
checks oversized Expect rejection before 100 Continue, malformed request JSON/UTF-8
without a state transition, acceptance of a valid request padded to exactly one
MiB, authentication, static assets/defaults, columns/sniff/profile, prepare/cancel/retry, confirmed
strict-cap publication and terminal failure on a 60-row partition fixture.
Compared JSON fields, CSV hashes and manifest output records remain exact.
[Binary identities and harness sources](../../evidence-originals.md#sha256-16ef1f32a0a0bd971a1a948eede64622caf29347d0eb50cc09c1ed52d0160442 "Original: docs/benchmarks/native-request-wire-package-identities-2026-10-23.json")
pin this native build and verify all seven preceding local hosted assets remain
unchanged. No hosted rebuild/deployment, new browser/device/macOS coverage,
scale calibration, physical-I/O or speedup claim follows.

Parsed request and picker output/source trees, Job construction, State/progress/
error source storage, discovery/parent normalization, carriers, HTTP/OS/runtime
internals and native stacks remain open. The two native transport slices do not
establish a complete process RSS cap.
