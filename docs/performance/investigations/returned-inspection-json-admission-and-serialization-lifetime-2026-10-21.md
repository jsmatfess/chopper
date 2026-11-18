## Returned inspection JSON admission and serialization lifetime (2026-10-21)

The next allocation-coverage slice is the column/sniff JSON returned after parser
and sample destruction. A bare `Value` cannot retain its parser's grant after
return. Both Rust APIs now return immutable, serializable
[`Inspection`](../../../crates/chopper/src/engine/inspection_result.rs), pairing the tree
with a separate reservation. The HTTP/worker JSON schema and detection behavior
stay unchanged. Rust callers borrow through `Deref` or serialize the owner;
explicitly cloned JSON is a new caller allocation, outside this boundary.

Admission precedes `json!` construction. The two fixed schemas use a conservative
allowance for sixteen object fields based on decoded-catalog BTreeMap node widths,
fixed keys/scalar text, known-length header `Value` arrays and UTF-8 string bytes.
Sniff detection bounds the settings text; its note is separately counted. Parser
and decoded-sample reservations stay live during construction overlap. The tree
drops before its own grant. The [resource-policy note](../../resource-policy-research.md#returned-inspection-json-owner-2026-10-21)
records the representation/schema assumptions and remaining limits.

The native server retains the result through serialization and response
consumption. The WASI reporter accepts a serializable owner and writes JSON
directly to stdout, avoiding a cloned Value/full serialized String. Native wire
buffers, stdout/serializer/runtime storage and caller-created clones remain
separate gaps. This is working-allocation ownership, not an RSS cap or speedup.

The [shared contract](../../../crates/chopper/src/engine/inspection_result/resource_contracts.rs)
checks ordinary columns, a 4,096-column Unicode header and sniff settings.
It verifies the constructed tree against the independent catalog-capacity
traversal, then checks exact shared peak minus one/exact/plus one, typed local
and shared denial, held competing-owner release/fresh retry, serialization writes
and failure while the grant remains live, two concurrent returned results and
last-owner drop. A separate rejected-builder control verifies admission before
construction. Existing parser/sniff contracts retain behavior and cleanup checks;
the parser-only retry control stays at its isolated parser edge, with result
construction covered independently.

[Development transcripts](../../evidence-originals.md#sha256-b4163627f2d1e74f08925e5c1370f528d989f07abdceb9377b03fb623db88339 "Original: docs/benchmarks/inspection-result-owner-development-2026-10-21.json")
retain the initial parser-only ceiling failure, missing test import, and first
wide-header fixture whose shell transport replaced Unicode with question marks.
The fixture now uses explicit Rust Unicode escapes. The
[final targeted pass](../../evidence-originals.md#sha256-5b1f6f4ae30abc4872e9d11cf0558c40a7046123aac4fa20a9f28036cb77b0b3 "Original: docs/benchmarks/inspection-result-owner-final-targeted-2026-10-21.json")
pins unchanged compilation inputs and passes the corrected contract on Windows
and Linux/WSL. Its Linux result supersedes the earlier ASCII-fixture report in
the broader validation pass; these are separate observations, not added samples.
The [17-feature pass](../../evidence-originals.md#sha256-c52d1d29c87b1b65b06ff52eb24c01e1de209fab754fb0a24558336ef3c5865d "Original: docs/benchmarks/inspection-result-owner-feature-validation-2026-10-21.json")
passes 222 library tests and all-target Clippy, plus fifteen benchmark/provenance
tests. The [broader validation](../../evidence-originals.md#sha256-7f1b4825f956909ac3663054e0e26c42f0a626b200c81428ca7f38c6598de16f "Original: docs/benchmarks/inspection-result-owner-validation-2026-10-21.json")
passes the Windows default workspace (141 library tests), candidate library (156),
formatting, both all-target Clippy configurations and 28 UI tests/build. Counts
belong to separate configurations. No pipeline, replay or experimental default
changes.

The final broader pass also passes the embedded native rebuild, 25 standard
Chromium contracts, bridge/peer-cleanup checks and both base/candidate WASI
resource variants. [Cross-runtime comparison](../../evidence-originals.md#sha256-14f1cdd2f4fbbced77f20157680e675114f25972a568806a133fc02758197b14 "Original: docs/benchmarks/inspection-result-owner-cross-runtime-2026-10-21.json")
confirms the three corrected fixture identities match Windows, Linux/WSL and
both WASI builds. Native reports match exactly; the wide header retains 168,448
bytes on native and 129,536 on WASI, reflecting representation-size differences.
All cases finish with zero reservations. Compilation inputs stay unchanged
through final targeted and browser validation. Final production packaging passes
the export guard and removes test assets. This closes returned fixed-schema
inspection trees, while the broader resource item and the other TODO tasks remain
open. No new benchmark matrix or default promotion follows from this slice.
