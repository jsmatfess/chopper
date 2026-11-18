## Decoded group owners and WASI resource contracts (2026-10-21)

Resource-correctness follow-up: `Dataset::groups()` now reserves decoded group
JSON before materialization and returns a public opaque `ChargedJson<Group>`.
The owner retains string/vector capacity and conservative map allowance after
reader/dataset destruction; callers borrow fields through `Deref`, and JSON
serialization is unchanged. The wrapper replaces the former bare-Group return
type so moving decoded lineage cannot silently shed its reservation. Internal
parallel tasks retain the decoder's original grant rather than charging a second
postdecode estimate. Replay retains that grant through `sink.end`, including
failure. Nested-balanced traversal retains its wrapper while mutating the group;
new construction, clones and mutation growth remain outside this slice.

Optional parallel prefetch uses a resumable catalog reader. Typed admission
denial drops partial line/scratch and seeks to the current record's logical start,
including denial after several buffer reads. Logical consumed-byte tracking
avoids a new file-position syscall per record. The parallel stage consumes queued
parents exactly once, releases optional task owners/vector capacity and retries
the pending record serially. This also handles a first-parent denial caused only
by the optional vector. A catalog-reader allocation denial before any emission
falls back to the ordinary stage. A second denial is terminal; cancellation,
malformed JSON, cleanup and seek errors never become successful retries.
Other catalog iterators retain their stop-on-error behavior.

The [validation record](../../evidence-originals.md#sha256-66b6e87c26aa4fc2af5c25cf43925d8ec700feb70ff575aeb7c1397784de5237 "Original: docs/benchmarks/group-catalog-wasi-resource-validation-2026-10-21.json")
retains the source inventory, two WASM identities, commands, browser observations
and failed attempts. Windows default workspace checks pass (133 library tests);
the recorded 17-feature library configuration passes 207 tests and its all-target
Clippy check passes. This excludes Parquet and is not an all-feature workspace
runtime claim. Twelve JSON, nine parallel-group and two nested-balanced focused
tests also pass on WSL Linux. They cover admission edges/concurrent owners,
reader-independent ownership, partial-record rewind/read-ahead, optional vector
and retained-batch fallback, moved-lineage sink failure, cancellation, corruption
and real pathname cleanup failure. The initial combined run exposed a fixture
that still owned a decoded parent while asserting zero usage; the regression now
asserts its exact retained charge, then drops it before requiring zero.

A separate nondefault `resource-contract-tests` build now executes the same
internal input-adapter helper in native tests and Chromium/WASI. It exercises
plain/gzip/Zstandard/ZIP decoding against real OPFS: capacity edges, typed shared
denial for compressed adapters while another owner is retained, release/retry,
charges through EOF, consumer errors, truncated gzip/Zstandard and zero final
reservations. The final browser resource contract observes four OPFS files,
192 bytes peak logical workspace size, zero bytes before worker cleanup and
removal of the workspace directory. These tiny fixture/storage observations
are neither a codec-memory census nor throughput/RSS measurements.

The first test-reactor run failed because `tempfile::tempdir()` invokes an
unsupported WASI default-temp-directory call. The shared helper now explicitly
uses `/tmp` on WASI, as production does; native fixture selection is unchanged.
The worker preserves Rust diagnostics, and the harness preserves primary errors
alongside cleanup failures. Earlier failed attempts remain in the record.

The [browser instructions](../../browser.md#tests) and CI now build the separate
`engine-resource-tests.wasm` and dedicated test worker/page. Production engine
and worker protocols have no injection API. `build:hosted` removes all test assets
and rejects an engine exposing `chopper_resource_contracts`; checks against both
actual WASM modules verify this guard. Rebuilt default WASI passes the existing
25 Chromium contracts plus bridge check. Production output is rebuilt afterward,
with all test/benchmark assets absent and the production WASM hash unchanged.

This closes controlled adapter denial/retry coverage on the recorded WASI build.
Typed late-parent fusion rollback, decoded-group admission and actual unlink-error
injection in WASI, broader browsers/devices, constructed/cloned lineage and
remaining codec/runtime allocations stay open in [TODO](../../../TODO.md). No new
benchmark jobs, device effects, scale claims, RSS cap or defaults are introduced.
