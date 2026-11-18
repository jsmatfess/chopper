## Native typed Job construction admission (2026-10-23)

Native Job requests now pre-admit conversion/default working capacity while the
original decoded Value remains owned. The
[conversion preflight](../../../crates/chopper/src/server/request_body/conversion.rs)
accounts for pinned serde Content buffers, typed vectors and replacement overlap,
possible column-name copies and CSV defaults. After conversion, grants combine
without a release gap and reconcile to the existing exhaustive Job String/Vec
capacity audit. Workers retain an immutable typed owner; preparation replaces it
with an independent PreparedJob owner before release. The GET defaults source
also admits its fixed default payload before constructing it. The
[ownership contract](../../resource-policy-research.md#native-typed-job-construction-ownership-2026-10-23)
records schema/layout assumptions and remaining error/runtime scope.

Three new controls cover twelve local/shared conversion edges (default-only and
1,024-column requests), six default-source construction edges, competing typed
owners/retry and 27 schema/error parity cases across operation variants. Prior
request pointer/handoff/cancellation/failure tests now require reconciled typed
capacity. The empty request admits 28 conversion bytes and retains 14 default
bytes. The column fixture has 44,193 decoded source bytes plus 277,021 conversion
allowance (321,214 peak), then retains 29,754 typed bytes. These are requested
working capacities/conservative envelopes, not RSS. Earlier
[unreconciled-grant expectations](../../evidence-originals.md#sha256-0480055861fef8eb6308f8db8078619da86cd9c27d6615b192e454b64cbf1b0a "Original: docs/benchmarks/native-job-conversion-development-2026-10-23.json")
and a [source-vector-capacity model error](../../evidence-originals.md#sha256-6e3f32e02120927a7f9d15e27ea7204e6282bc422346bc565ebbb2e8c0d96385 "Original: docs/benchmarks/native-job-conversion-capacity-development-2026-10-23.json")
remain preserved; fixture expectations were corrected without weakening admission.

The separate [allocation probe](../../evidence-originals.md#sha256-cd94d0919076c1abac5f1af12567dd604f412867f787db2ecec40a14f0cd73de "Original: docs/benchmarks/native-job-conversion-allocation-probe-2026-10-23.json")
checks real System allocation layouts through fresh source Value creation and
conversion. On both Windows and Linux, 38 successful fixtures fit the pre-admitted
source-plus-conversion envelope and retain exactly the audited Job capacity;
two malformed conversions additionally verify observed final release. All 40
cases on each platform return to zero. Realloc observation includes old/new
replacement overlap. Error-object heap is observed but excluded from the payload
bound. The corpus covers defaults, every operation family, vector growth, large
strings and nested buffered errors. These are allocation-correctness controls,
not timings, allocator usable-size, RSS or performance comparisons.

An explicit [successful-column error control](../../evidence-originals.md#sha256-742f4c7b779a549a9d1c97ac4e604262b7f70491bfa868c2bc5f24b9af7a6ed7 "Original: docs/benchmarks/native-job-conversion-error-control-2026-10-23.json")
uses 16,384 control characters in one column name. The failed numeric alternative
formats an error before the name alternative succeeds. On both platforms the
total observed requested-heap peak is 201,770 bytes versus a 39,960-byte Job-data
envelope; retained typed payload is 16,499 bytes and final observed heap is zero.
The [initial whole-heap assertion failure](../../evidence-originals.md#sha256-5cf7c334795056dd391a707b0cee1a03f5b005a59c8060fecb5609b7b323efd5 "Original: docs/benchmarks/native-job-conversion-error-control-development-2026-10-23.json")
is retained. This control intentionally observes, rather than asserts admission
of, excluded error internals. It demonstrates that successful typed conversion
can still need unadmitted error/runtime headroom; the data envelope is not a
bound on the entire conversion heap or RSS. The earlier 40-case payload controls
and their original assertions remain unchanged.

[Windows validation](../../evidence-originals.md#sha256-7705a00aff57187ca4abde35df7e31920956ec6f4affc0d5436aa44985df9f74 "Original: docs/benchmarks/native-job-conversion-validation-2026-10-23.json")
and [Linux/WSL validation](../../evidence-originals.md#sha256-3611e09c88fb86d20a27f3dd65f5856661d5962b068052398d6f05d7c63273ba "Original: docs/benchmarks/native-job-conversion-linux-validation-2026-10-23.json")
record default/combined checks and fourteen request contracts. Windows also
records all-feature compilation, UI tests/build, the release build and the
all-feature serde_json dependency graph. All eleven Windows commands and seven
Linux commands pass: Windows default/combined suites pass 281/338 tests plus nine
doctests each; Linux passes 284/341 tests plus nine doctests each. All 28 UI tests
pass and serde_json retains only its default/std features.
[Retained-server parity](../../evidence-originals.md#sha256-9448e6c1a842ac8d82d46209818412d36c523bb928886e8b2bb82590ccc6d501 "Original: docs/benchmarks/native-job-conversion-server-parity-2026-10-23.json")
checks defaults, oversized Expect rejection, exact-one-MiB acceptance, malformed
JSON/UTF-8, authentication/assets, inspection/profile, prepare/cancel/retry,
confirmed strict-cap publication and terminal failure. Compared visible fields,
CSV hashes and manifest output records remain exact on the 60-row fixture.
[Package identities and harness sources](../../evidence-originals.md#sha256-0c206ba6dd6822f3df3c0104787f4e6febf9495888aee7625ae7107fed57b205 "Original: docs/benchmarks/native-job-conversion-package-identities-2026-10-23.json")
pin native binaries, pinned serde/derive source hashes and the allocation proof;
the seven preceding hosted assets remain unchanged. No new hosted build,
deployment, WASI/browser/device/macOS, scale, physical-I/O or speedup claim follows.

This closes native HTTP Job data/default/conversion-buffer ownership for the
audited schema. Typed-conversion error internals, picker subprocess output and
parsed response, State/progress/error source storage, caller/CLI construction,
carriers, discovery/parent normalization, HTTP/OS/runtime allocations and native
stacks remain open. This is working-allocation accounting, not a full RSS cap.
