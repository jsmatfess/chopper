## Native inspection HTTP payload admission (2026-10-21)

This resource-correctness follow-up closes the serialized success-body allocation
for native `/api/columns` and `/api/sniff`, following the
[returned-tree owner](../../performance.md#returned-inspection-json-admission-and-serialization-lifetime-2026-10-21).
The decision is to keep the tree and wire payload independently admitted during
serialization, then release the tree while the HTTP reader retains the payload.
This is allocation ownership work, not a timed baseline/candidate experiment or
a throughput claim; no experimental selector or default changes.

The [native body owner](../../../crates/chopper/src/engine/inspection_result/wire.rs)
first counts actual escaped JSON with an allocation-free counting writer. It
then admits an exact-reserve vector through the inspection's existing local and
shared workspace, reconciles reported capacity, and serializes into a fixed
slice that cannot grow. The immutable tree is retained through both passes.
The payload reservation lives inside the `Read` owner consumed by tiny_http,
including header failure, partial send, EOF retention and abandoned responses.
The payload drops before its grant. Admission denial follows the existing HTTP
400 JSON error path. Other response trees/buffers, error payloads, tiny_http
headers/framing, socket buffers, native threads and serializer/runtime overhead
remain outside this slice; reservations still do not cap RSS.

Three [native contracts](../../../crates/chopper/src/engine/inspection_result/wire/tests.rs)
cover local/shared combined tree-plus-body minus-one/exact/plus-one boundaries,
typed denial and rollback, competing-owner release/retry, exact escaped UTF-8 JSON,
two response readers moved across threads, EOF retention and final-owner drop.
The fixture contains Unicode, quotes, backslashes and control characters: the
tree retains 35,360 bytes and the serialized payload/capacity is 34,864 bytes on
this Windows build. These are simultaneous working charges during serialization,
not RSS measurements. The tiny_http `raw_print` path verifies decoded chunked
HTTP parity and injected broken-pipe failures before headers and after 1,024
wire bytes, with zero final charges. This is an injected writer disconnect,
not an operating-system socket fault experiment.

A [public server test](../../../crates/chopper/tests/interfaces.rs) compares both real
HTTP endpoints with engine JSON and checks the existing missing-input error
response. The [validation record](../../evidence-originals.md#sha256-93e823af6de332274097757527cf01b4e6d657ad016f852f97c6d678814c6a52 "Original: docs/benchmarks/native-inspection-wire-validation-2026-10-21.json")
retains toolchain, dirty tracked/untracked compilation-source hashes including
vendor inputs, per-command outcomes and the two initial test-development failures
(nonexistent test hash helper and missing chunked framing decode). Its elapsed
command durations are validation durations, not performance observations.
The Windows pass succeeds on formatting, default workspace tests (144 chopper
library tests), candidate library tests (159), and all-target workspace Clippy
with and without `experimental-shuffle-partition`. Compilation-source identities
remain unchanged through the pass. The full workspace includes the new public
HTTP test. A nonfatal Windows incremental-cache finalization error 5 is retained
in the transcript; it did not prevent compilation or execution. No Linux/macOS
or browser run is claimed for this native-only change.
Broader TODO resource ownership, SSD selectors and platform acceptance remain open.
