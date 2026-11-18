## Diagnostic snapshot preflight and shared ownership (2026-10-23)

[`Diagnostics`](../../../crates/chopper/src/engine/diagnostics.rs) now admits retained
JSON before construction and shares its tree/grant across Analysis and independent
payload clones. Borrowed context/process/audit views avoid temporary discovery
String clones and nested JSON trees. The existing nonallocating job-manifest
preflight moved to [`storage/json_estimate.rs`](../../../crates/chopper/src/storage/json_estimate.rs),
with its old module forwarding to that helper. A fresh locked visit estimates
before allocating; admission occurs only after audit/pressure locks release.
Larger data between visits requires a larger grant and a fresh preflight. The
[ownership contract](../../resource-policy-research.md#analysis-diagnostic-snapshot-ownership-2026-10-23)
records stable-source/lock-order assumptions, retained-capacity reconciliation,
controller admission and allocation-free patching of existing numeric slots.

The additional `analysis_diagnostics_reserved_bytes` field reports the final
owner grant. Workspace/process reserved and peak slots include construction,
reconciliation and controller admission. All pre-existing schema fields remain;
counts are snapshots rather than live metrics after later owners drop. Tight
budgets can reject diagnostic storage that was previously uncharged. Caller
construction/deserialization and explicit Value copies remain outside admission;
`Context::diagnostics()` remains a caller-owned convenience copy. Required engine
results use the admitted path.

The [development reproduction](../../evidence-originals.md#sha256-05fe489ae38c8aab8eccae41d3c2907dff2338179a7f020d70d74a5745aa38ef "Original: docs/benchmarks/analysis-diagnostics-development-2026-10-23.json")
preserves an optional snapshot test's stale zero-ledger assertion: its expected
digest clone still held 136 bytes. The test now checks that exact live grant,
drops the clone and requires zero. The
[initial Windows record](../../evidence-originals.md#sha256-33717995133a946e475e67861a046366a70a211011d3cfad7eb8a97dd24c00b2 "Original: docs/benchmarks/analysis-diagnostics-validation-2026-10-23.json")
preserves a base-WASI fixture panic from using the unsupported native default
temporary-directory lookup; its explicit `/tmp` root is corrected. The separate
[initial Linux record](../../evidence-originals.md#sha256-ef4c8e7513d6bcab8dad22714956628e2afe0be848d37facc077b5f76a9e16e7 "Original: docs/benchmarks/analysis-diagnostics-linux-validation-2026-10-23.json")
passes its seven commands for that earlier source; it is not substituted for
final-source coverage.

The native opt-in parsed-input snapshot now captures its returned diagnostics
and checks cancellation before renaming the completion manifest. Its fresh
artifact-directory guard remains active through capture and commit. The
[commit-order regression](../../evidence-originals.md#sha256-3afb2c256f4c0bc2393736f38c15051678e671876c2a13aa99ddbdbf94b8331c "Original: docs/benchmarks/analysis-diagnostics-snapshot-commit-development-2026-10-23.json")
first reproduces diagnostic denial publishing the manifest before cleanup; the
corrected helper leaves the partial file uncommitted, then releases its directory
and grants. Returned `Created` diagnostics retain admission after Context drops.
These native snapshot semantics have separate coverage from browser export markers.

The [final Windows prefix](../../evidence-originals.md#sha256-0f1fad26e122a7dc26b2420357482f33fa7603a8a68efbaac4dd98a801031c44 "Original: docs/benchmarks/analysis-diagnostics-final-validation-2026-10-23.json")
passes its first 18 commands, including native/UI checks, base-WASI acceptance,
combined resource-reactor construction, all-features compilation and the serde_json
feature query. The query succeeds, but the runner then stops printing its Unicode
tree under cp1252. Its record stays unchanged. The
[eight-command browser/package follow-up](../../evidence-originals.md#sha256-539b2be3a353d57768efeb0fa1aa74343e7918d8a854bccb1434c69088d55a77 "Original: docs/benchmarks/analysis-diagnostics-browser-followup-2026-10-23.json")
completes the remaining commands against the same source inventory and pinned
resource WASM. The [final Linux/WSL record](../../evidence-originals.md#sha256-a72ea7902e51f521951d9214c4c75a5f384f409f7bfd77eabc89278b84f38f64 "Original: docs/benchmarks/analysis-diagnostics-linux-final-validation-2026-10-23.json")
passes all seven commands. Windows covers 262 default workspace and 319 combined
Chopper tests; Linux covers 265 and 322. Each suite also passes nine read-only
compile-fail doctests. Both platforms pass all seven optional snapshot regressions,
including the new commit-denial control. Default/combined Clippy, formatting,
UI's 28 tests/build and native release pass. The recorded all-features dependency
graph has serde_json default/std features, preserving BTree/inline-number assumptions.

The nested fixture needs a 6,483-byte construction peak and retains 6,371 bytes
on 64-bit native; WASI needs 4,107 and retains 4,019. These are capacity allowances,
not allocator/RSS measurements. Six exact local/shared construction edges and six
controller edges pass, including denial after tree construction and complete
cleanup. Competing-owner release/retry, canonical caller JSON, shallow clone
identity, native concurrent final drops, fresh preflight after source growth,
growth denial and unsupported display rejection pass. Legacy-schema controls
compare all fields; the experimental variant preserves the first 16 completed
audit records and four omissions, then drops Context/original audit while keeping
the independently admitted snapshot. A native pressure-mutex control checks
capture without reserving inside the borrowed visit.

Public prepare/drop/execute controls preserve exact CSV, legacy counters, clone
identity, self-inclusive reservation numbers and independent snapshot lifetime.
Serializer failures and cancellation of a prepared result retain/release the
correct owners and leave no failed destination. Exact live-owner equations include
the new diagnostic grant and still require release after final destruction.
Bundled Chromium passes the base WASI resource contract. Chromium, Chrome and Edge
pass the combined resource contract, including the populated audit and diagnostic
controls. Production's 25 Chromium contracts and final test-free hosted packaging
pass.

The [package identities](../../evidence-originals.md#sha256-0e1c885f777455240746aedaf938ca7ca54064def596969b80776172ec72d89c "Original: docs/benchmarks/analysis-diagnostics-package-identities-2026-10-23.json")
pin 26 native test executables, the release binary and seven hosted assets; the
production engine exposes no resource-test entry point. The
[retained CLI comparison](../../evidence-originals.md#sha256-4a09947b55c1569f7bfabba97d1f89c6713df1d5a431407cb3b2a47b3da67ac8 "Original: docs/benchmarks/analysis-diagnostics-native-parity-2026-10-23.json")
passes nine fixtures/eighteen commands against the preceding warning/timing build.
CSV hashes, output records, normalized config, all Analysis text, header/preview/
selected values, stages, warnings, timing keys and non-memory/non-timing diagnostic
counters/flags match. Reservation, process-observation and timing values are
separate observations and are excluded from equality. The fixture directory is
removed.

All heap-backed fields of engine-produced Analysis now retain admitted shared
owners; its remaining fields and ExecutionSummary are inline scalars/enums/fixed
arrays. Carrier allocation, source discovery/pressure storage, response/error/
progress framing and native thread/runtime work remain outside this field audit.
The local package is not published; macOS remains deferred. These correctness
fixtures establish no throughput, physical-I/O, complete-RSS or wider-scale claim.
