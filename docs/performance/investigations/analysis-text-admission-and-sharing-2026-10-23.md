## Analysis text admission and sharing (2026-10-23)

[`AnalysisText`](../../../crates/chopper/src/engine/analysis_text.rs) now owns seed,
logical digest and accuracy strings retained by Analysis. Each nonempty string
admits its copied payload and shared controller before allocation, reconciles
actual String capacity and shares both with Analysis clones and returned
execution results. Empty text allocates nothing. The source Job retains its own
separate grant. Seed copying is admitted before requesting any CSV record;
digest copying uses the fixed hexadecimal representation after scanning. Public
Rust fields have an immutable owner type; string JSON and text contents remain
unchanged. Explicit caller copies and caller construction/deserialization remain
outside engine admission. Tight budgets may now reject previously uncharged
Analysis text.

The [ownership contract](../../resource-policy-research.md#analysis-text-ownership-2026-10-23)
records final destruction ordering and the separate
`analysis_text_reserved_bytes` diagnostic. The existing stage diagnostic counts
only its stage owner. Expected digest strings used after deliberately dropping
an Analysis in a zero-ledger test are explicit caller copies; separate contracts
exercise retention through text/Analysis clones.

The [initial Windows record](../../evidence-originals.md#sha256-1da27e0d8319bf3e037f8bb8981b3bd696aa31f4f6cc3b578c9d9f9cf4829f3c "Original: docs/benchmarks/analysis-text-validation-2026-10-23.json")
and [initial Linux record](../../evidence-originals.md#sha256-be573d8615fbaef8ba36b38b7214ff9ee6f1ee8079f7a5645db18d15f50fdbd8 "Original: docs/benchmarks/analysis-text-linux-validation-2026-10-23.json")
preserve a combined-feature compile failure: one JSON comparison needed to
borrow the new text field as `&str`. Linux's initial default suite passed before
that compile failure. Source review also caught text bytes being included in
both text and stage diagnostics; that double count was corrected before browser
acceptance. These attempts do not establish complete final-build validation.

The [final Windows record](../../evidence-originals.md#sha256-cb856b0f96981f8204cd66ba93093494ede29e95deb50a8fdf79b185a5856a67 "Original: docs/benchmarks/analysis-text-final-validation-2026-10-23.json")
passes 259 default workspace and 316 combined-feature Chopper tests; the
[final Linux/WSL record](../../evidence-originals.md#sha256-43070434ac39bfb069f4cf6b2c658d7bc2b43dbc46addde9fafd0fa2b62b6d3f "Original: docs/benchmarks/analysis-text-linux-final-validation-2026-10-23.json")
passes 262 and 319. Each suite also passes six read-only compile-fail doctests.
Default/combined Clippy, formatting, UI's 28 tests/build and the native release
build pass. The all-features compile check covers optional snapshot adapters.

The ten-byte Unicode/quoted text fixture has a retained grant of 82 bytes on
64-bit native and 58 in WASI, including the shared controller. Six exact
local/shared edges, competing-owner release/retry, unchanged string JSON,
shallow clone identity and native concurrent final drops are covered. Empty
text has no payload/controller. A 4,096-byte seed's controller denial returns
typed shared admission without requesting a header record. Public prepare/drop/
execute controls check all three text values and clone identity, retain the
grant through serializer failure and release it with the final Analysis clone.
Malformed input and cancellation after 65,536 populated scan rows leave no
destination, temporary workspace or grant. Header, preview, summary, stage and
pressure tests explicitly include text owners in their live-capacity equations
and retain their final destruction checks.

All 21 final Windows commands and six final Linux commands pass with unchanged
compilation inputs. Bundled Chromium, installed Chrome and Edge pass the shared
WASI resource contract, including the 58-byte text fixture and public lifetime/
failure cases. Production's 25 Chromium contracts and final hosted packaging
pass. The [package identities](../../evidence-originals.md#sha256-3ca8ad0d7e3951f2addcd4ee2e61d2f9c890dd2aa2213c30fa94eff0341f029b "Original: docs/benchmarks/analysis-text-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven hosted assets;
production has no resource-test export.

The [retained CLI comparison](../../evidence-originals.md#sha256-e10bf03466eecdeecdb045ccdc6f687447d10d7b6593badf6a0adf36216f4773 "Original: docs/benchmarks/analysis-text-native-parity-2026-10-23.json")
passes seven operation fixtures/fourteen commands against the preceding stage
build. It independently compares all three Analysis text fields in addition to
CSV hashes, output records, normalized configuration, header/preview/selected
values and stage metadata under active row/byte caps. The fixture directory is
removed. This package remains local. Warnings, timing/diagnostic trees, other
Analysis metadata and native thread/runtime overhead remain open in
[TODO](../../../TODO.md); macOS stays deferred. No throughput, physical-I/O, RSS,
scale or additional-device claim follows from these correctness fixtures.
