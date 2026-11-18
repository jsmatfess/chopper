## Analysis warning and timing admission (2026-10-23)

Analysis now retains immutable [`Warnings`](../../../crates/chopper/src/engine/warnings.rs)
and [`Timings`](../../../crates/chopper/src/engine/timings.rs) owners. Clones share the
vector/tree, String capacity and admission through serialization, discarded
preparations, returned execution results and independent payload clones. Public
Rust fields have owner types; ordered warning-array and timing-object JSON stay
unchanged. Explicit caller copies and construction/deserialization remain
outside engine admission. Tight budgets can now reject previously uncharged
warning/timing storage; preparation fails rather than omitting metadata.

Warning construction preserves the existing nine conditions and their text/order.
The first selected entry admits a nine-slot vector; each String is admitted
before copying and finalization admits the shared controller. Partial-copy denial
leaves existing entries/root charged and unchanged, allowing exact retry after
pressure release. A tenth warning fails before growth. No selected warning
creates no vector/controller. The file-count warning now formats into bounded
stack scratch before copying, including the maximum `u64` count, instead of
creating an unadmitted `format!` String.

Three phase timings collect static keys/scalars on the stack at the original
observation points. Duplicate keys replace a scalar; a fourth distinct key fails
before heap construction. Finalization admits a conservative single-leaf BTree
allowance, copied keys and shared controller before allocating. The three keys
fit the audited eleven-slot leaf; a compile guard and
[ownership contract](../../resource-policy-research.md#analysis-warning-and-timing-ownership-2026-10-23)
record the bound and re-audit requirements. Map finalization remains inside
`analysis_seconds`; warning construction remains outside. These are
working-allocation allowances, not a node-allocation census or RSS cap.

The [Windows run](../../evidence-originals.md#sha256-f3e8c15547a980f78ef0bcaae8eba22e18d90ba58e22ae74885b5363c8266a23 "Original: docs/benchmarks/analysis-notes-validation-2026-10-23.json") passes
261 default workspace and 318 combined-feature Chopper tests; the
[Linux/WSL run](../../evidence-originals.md#sha256-766804b48fac65fbec8d45721a4825480f4767453f5efb9e5d520a8d1dbb48cb "Original: docs/benchmarks/analysis-notes-linux-validation-2026-10-23.json") passes
264 and 321 respectively. Each suite also passes eight read-only compile-fail
doctests. Default/combined Clippy, formatting, UI's 28 tests/build, native release
and the Windows all-features compile check pass.

The three-warning fixture retains a 304-byte grant on 64-bit native and 172
bytes in WASI, including the nine-slot vector and shared controller. The
three-key timing fixture retains 750/454 bytes; its conservative node allowance
is 672/400 bytes. Each owner passes six exact local/shared edges, competing-owner
release/retry, unchanged JSON, shallow clone identity and native concurrent
final drops. Warning controls deny a partial String copy without changing prior
entries/root and retry after pressure release; ninth/tenth entry and empty-owner
controls pass. A synthetic metadata control checks all nine warning conditions
in original order and maximum-`u64` formatting, without claiming that synthetic
operation list is an executable pipeline or scale test. Timing controls keep
observations on the stack, replace duplicate values, reject a fourth key and
release an already-built partial map after key-copy denial.

Public prepare/drop/execute controls preserve exact CSV and metadata, retain both
owners through serializer failures, and share them with Analysis and independent
payload clones. Dropping the Analysis leaves exactly warning/timing grants;
dropping those independently releases each grant in turn. Cancellation of an
already prepared snapshot starts with both owners live and leaves no destination
or grants after destruction. Existing header, preview, summary, stage, text and
pressure equations include these new owners explicitly and retain final-drop
checks. Bundled Chromium, installed Chrome and Edge pass the shared WASI resource
contract, including the warning conditions and public lifetime/cancellation cases.

All 22 Windows commands and six Linux commands pass with unchanged compilation
inputs. Production's 25 Chromium contracts and final test-free hosted packaging
pass. The [package identities](../../evidence-originals.md#sha256-433ccc2f55b7c7d0b5f7d13336c47cd617f478437c78725c8e04d263bbefe6dd "Original: docs/benchmarks/analysis-notes-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven hosted assets;
production has no resource-test export.

The [retained CLI comparison](../../evidence-originals.md#sha256-b5f043a654bc6af1122309b412c4f57908db2677ee62189dd88b677401e4dd80 "Original: docs/benchmarks/analysis-notes-native-parity-2026-10-23.json")
passes nine operation fixtures/eighteen commands against the preceding Analysis
text build. It compares warning contents/order and timing keys in addition to
all three Analysis text fields, CSV hashes, output records, normalized config,
header/preview/selected values and stages under active row/byte caps. New cases
include probabilistic allocation and a named zero-percent group. Timing values
remain observations of separate jobs, not values expected to match or evidence
of a speedup. The fixture directory is removed.

This package remains local. Diagnostic trees, other Analysis metadata, response/
error framing and native thread/runtime allocations remain open in
[TODO](../../../TODO.md); macOS stays deferred. These correctness fixtures establish
no throughput, physical-I/O, RSS, scale or additional-device claim.
