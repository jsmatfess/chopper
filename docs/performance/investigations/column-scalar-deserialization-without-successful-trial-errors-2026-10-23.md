## Column scalar deserialization without successful trial errors (2026-10-23)

The portable Column deserializer now recognizes valid names and checked indexes
directly. It avoids the prior untagged numeric trial's formatted error and moves
owned names without copying. Quoted numeric strings remain names; floats remain
invalid and serialization stays unchanged. Rejected containers strictly validate
nested input without building a temporary tree. Legacy generic error creation
occurs after the visitor returns, preserving the original lack of an additional
JSON position suffix. The initial
[position-compatibility failure](../../evidence-originals.md#sha256-ec4b09f0db3a959d50e95064a63dd9ff982bc6e872a5e262392b5e249e680dd3 "Original: docs/benchmarks/column-deserialize-error-position-development-2026-10-23.json")
is retained before that correction. The
[ownership/behavior contract](../../resource-policy-research.md#column-scalar-deserialization-2026-10-23)
records scalar, borrowed/owned, syntax and format assumptions.

The [allocation replay](../../evidence-originals.md#sha256-ebf30ae888d63499ad4f11a24355bfac29eae83158dc9545d23b11a7a3612a20 "Original: docs/benchmarks/column-deserialize-allocation-probe-2026-10-23.json")
retains all 40 preceding fixtures and promotes the previously excluded long-name
control to the same successful-conversion full requested-heap assertion. Both
Windows and Linux pass 41 cases (39 successful conversions and two observed
errors), with exact retained Job capacity and final zero. The 16,384-control-
character name now peaks at 18,167 requested heap bytes versus the retained prior
201,770-byte observation, while typed payload remains 16,499 and the unchanged
source-plus-conversion envelope is 39,960. Realloc observation includes old/new
replacement overlap. This closes that specific successful numeric-trial error
path; it does not establish a complete RSS cap, general speedup or admission of
all error-object/runtime internals. Earlier positive/negative records are preserved.

Native core tests compare exact values/errors with the former derived untagged
implementation, verify owned pointer/capacity movement and check non-JSON scalar/
wrapper forms. Thirty-six JSON cases are also shared with the native/WASI resource
reactor, including invalid containers, Unicode/escapes, recursion and
32/64-bit usize boundaries. The browser assertion requires the 32-bit report and
owned-name move. Configuration representation, pipeline order, exact membership,
strict CSV caps and seeded/replay behavior are unchanged.

[Windows/native/core-target/browser validation](../../evidence-originals.md#sha256-5e6dad9fce37c8fc68275992a394de83559091124fe5b7ec9d315961d7d19733 "Original: docs/benchmarks/column-deserialize-validation-2026-10-23.json")
records formatting, default/combined Clippy/tests, the unknown-unknown core target,
focused native/shared contracts, all-feature compilation, UI tests/build and
release packaging. Production browser checks cover the standard suite, bridge,
peer cleanup and temporary/persistent/forced-process interruption. Base and
shuffle-partition WASI reactors include the new reference contract; Chromium,
installed Chrome and Edge check the candidate. Production is rebuilt and packaged
without test assets afterward. All 33 Windows/core/browser commands and seven
Linux commands pass. Windows default/combined suites pass 284/338 tests plus nine
doctests each; Linux passes 287/341 tests plus nine doctests each. The 28 UI tests,
25 production Chromium contracts, bridge/cleanup and three interruption modes
pass. Base Chromium and candidate Chromium/Chrome/Edge reactors each require all
36 Column reference cases and the owned-name move. Final package identities pin
27 native test binaries and seven production assets; initial/final production
WASM hashes match and test-only exports are absent.
[Linux/WSL validation](../../evidence-originals.md#sha256-da2371bd117b902d1a0b79cd1827cbd2fc5ee862f5b5cc3cf9236ac8e83aa1ae "Original: docs/benchmarks/column-deserialize-linux-validation-2026-10-23.json")
records native default/combined checks and request contracts.
[Retained native CLI parity](../../evidence-originals.md#sha256-102c129331c2dac4b184e2f4749c77d2c94421c2c4a8cace54396ac671de82a3 "Original: docs/benchmarks/column-deserialize-native-parity-2026-10-23.json")
adds numeric-string and control-character header selection to the seeded corpus,
with twelve exact CSV/metadata/configuration/Analysis comparisons and four invalid-column
error/no-publication checks (32 CLI commands).
[Native-server parity](../../evidence-originals.md#sha256-7f1d97e1f45ff130e770caf0aac50252d6410c33dcb88ae6034204125a2ec393 "Original: docs/benchmarks/column-deserialize-server-parity-2026-10-23.json")
retains defaults, request errors/limits, profile/prepare/cancel/retry and exact
strict-cap publication.
[Package identities and harness sources](../../evidence-originals.md#sha256-de95834898c9e4be82dc50820e9ee575798d28414b422be62f6c01aaf888be31 "Original: docs/benchmarks/column-deserialize-package-identities-2026-10-23.json")
pin the native tests/release, WASI builds and seven-asset production package.
This build remains local; no new deployment, macOS, other device, scale or
physical-I/O claim follows.

Other terminal/error-formatting internals, picker subprocess output/response,
State/progress/error source storage, caller/CLI construction, carriers, discovery/
parent normalization and native OS/runtime/stacks remain open. The conversion
preflight retains its conservative copy/container allowance; no budget ceilings
or experimental defaults are promoted by this allocation-path change.
