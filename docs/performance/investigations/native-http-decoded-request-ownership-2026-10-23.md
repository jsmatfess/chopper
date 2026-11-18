## Native HTTP decoded request ownership (2026-10-23)

Native request parsing now reuses the existing catalog JSON decoder's admitted
scratch/preflight/tree construction. A ChargedJson owner keeps retained Value
storage after the raw request bytes drop. The JobRequest wrapper carries its
source grant when strings move into typed Job fields, through profile/inspection
worker scope and until preparation establishes an independent PreparedJob owner
or unwinds an error. Picker requests borrow their decoded tree through command
completion. The [ownership contract](../../resource-policy-research.md#native-http-decoded-request-ownership-2026-10-23)
records the original helper's conservative scratch/node/growth assumptions,
source movement and the separate typed-conversion/default-allocation boundary.
The generic decoder's construction algorithm and existing catalog callers are
unchanged; native visibility and guarded owner extraction are shared seams.

Five new contracts add six local/shared construction edges, two early scratch
denials, competing-owner release/retry, source/raw/tree destruction ordering,
serialization failure, independent worker drops and typed-conversion error
cleanup. Thirty-eight valid/malformed fixtures compare exact values and syntax
errors with the prior parser, including duplicate keys, integer/float limits,
UTF-8/escapes, trailing data and recursion limits. A pointer check follows an
original input String into JobRequest and PreparedJob; callbacks require source
admission through preparation, then source release after independent handoff.
Cancellation, missing-input failure and abandoned preparation publish no output.
The initial [invalid record-budget fixture](../../evidence-originals.md#sha256-cab33e352adfc1abdb3814bf62fae6741d80fd508055a99266e71b647a0602c7 "Original: docs/benchmarks/native-request-json-development-2026-10-23.json")
is preserved before correction; the engine's validation contract was unchanged.

The representative construction peak is 59,468 bytes: 16,384 raw wire capacity,
32,768 parser scratch allowance and 10,316 tree construction allowance. The
returned tree retains 9,996 bytes after scratch and raw bytes release. These are
requested working capacities and conservative envelopes, not usable-size or RSS
measurements. Whole-input scratch pre-admission can require additional capacity
for padding and unescaped input as well as actual escape decoding.

[Windows validation](../../evidence-originals.md#sha256-1fa4c110d35dba984a96e201dee1a0362d4d7a0c041394a7cbd939d9505c562a "Original: docs/benchmarks/native-request-json-validation-2026-10-23.json")
and [Linux/WSL validation](../../evidence-originals.md#sha256-8d3e9aa60d1a15606e9835d4e683ad81215b3912587b514fa752d67964d96a8b "Original: docs/benchmarks/native-request-json-linux-validation-2026-10-23.json")
record default/combined native checks and all eleven request contracts. Windows
also records all-feature compilation, UI tests/build, the release build and the
all-feature serde_json dependency graph. All eleven Windows commands and seven
Linux commands pass. Windows default/combined suites pass 278/335 tests plus nine
doctests each; Linux passes 281/338 tests plus nine doctests each. All 28 UI tests
pass. The dependency graph retains serde_json default/std features only.
[Retained-server compatibility](../../evidence-originals.md#sha256-f0e601ae2aabbfde034297cc3717ebe317959c8134abf752c631a6b05f3ddceb "Original: docs/benchmarks/native-request-json-server-parity-2026-10-23.json")
compares the preceding admitted-wire release with this decoded-owner release:
oversized Expect rejection, exact-one-MiB valid requests, malformed JSON/UTF-8,
authentication/assets/defaults, inspection/profile, prepare/cancel/retry,
confirmed strict-cap CSV/manifest publication and terminal failure. Compared
JSON fields, CSV hashes and output records remain exact on the 60-row fixture.
[Package identities and harness sources](../../evidence-originals.md#sha256-579ca932b42929f023b3816abbc75ca02ccbe471e39ca5e724de99ad18110234 "Original: docs/benchmarks/native-request-json-package-identities-2026-10-23.json")
pin native binaries and relevant pinned parser-source hashes, and verify the
seven preceding local hosted assets remain unchanged. No hosted rebuild or new
WASI/browser/device, macOS, deployment, scale, physical-I/O or speedup claim follows.

This closes original request-Value construction/scratch/retained ownership and
its moved-allocation lifetime, not all typed request allocation. Additional
conversion/default Job/serde buffering, picker subprocess output/response trees,
state/progress/error source storage, carriers, discovery/parent normalization,
HTTP/OS/runtime allocations and native stacks remain open. The typed-source
wrapper's retained original-tree grant does not prove admission of those extras.
