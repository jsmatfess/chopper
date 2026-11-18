## Gzip input codec admission (2026-10-22)

The existing gzip input adapter charged Chopper's 8 KiB reader but omitted
flate2's inflater, read buffer and header metadata. The new
[`input_gzip`](../../../crates/chopper/src/engine/input_gzip.rs) owner admits those
allocations before constructing the decoder, which immediately parses the first
header. Its grant survives EOF, partial reads and decoder errors until the
reader drops. The [source-audited envelope](../../evidence-originals.md#sha256-71ce07e0e9b0fdba903f4808351fcb77305a97108947803626103aea91aa267d "Original: docs/benchmarks/gzip-codec-source-audit-2026-10-22.json")
uses the pinned miniz inflater's public layout, the boxed reader layout, a fixed
32 KiB codec buffer and 512 KiB for bounded header storage/growth overlap. The
native Windows codec allowance is 600,624 bytes plus the separately owned input
buffer; the calculation follows target layouts. Exact flate2/miniz versions
retain the audited implementation; backend or version changes require re-audit.
See the [ownership contract](../../resource-policy-research.md#gzip-input-codec-admission-2026-10-22).

Six local/shared edges use concatenated members with maximum accepted extra,
filename and comment metadata and optional header CRC. Controls cover admission
before header reads, retained grants at EOF and after decoder failure, reader
drop, early/partial consumer failure, bad header/trailer CRC, truncation,
reserved flags and overlong names. The original adapter suite additionally
checks competing shared owners, typed denial and release/retry. CSV and gzip
parsing behavior remain unchanged; admission may now reject a tighter budget
that formerly left codec storage uncharged.

The [initial Windows pass](../../evidence-originals.md#sha256-97b6872bea9e3b0f8fb81e285f786fda968d09d2e3ce2b85a7a7ccf1b7aeccd3 "Original: docs/benchmarks/gzip-codec-final-validation-2026-10-22.json")
passes native checks but its first WASI resource run fails because the new test
probe used unsupported `File::try_clone`. The corresponding
[Linux native pass](../../evidence-originals.md#sha256-c60b0439f27088e33bba61165949eeed471cdb138ff8926accd4f1714704ff3b "Original: docs/benchmarks/gzip-codec-linux-validation-2026-10-22.json")
passes. Raw results remain preserved. The corrected probe counts reads through
the same generic input-reader constructor, requiring zero source reads when
admission fails without depending on descriptor duplication.

The [corrected 20-command Windows pass](../../evidence-originals.md#sha256-3b56b7c8ba6729f7ae3f3ab85567b216a5efbdc92b2fd9056a58fbb9a05ddf2d "Original: docs/benchmarks/gzip-codec-portable-final-validation-2026-10-22.json")
and [six-command Linux/WSL pass](../../evidence-originals.md#sha256-35b70db852b8d65ed0c933686dc00542b3c61194b11f325ebcb50d729f689239 "Original: docs/benchmarks/gzip-codec-portable-linux-validation-2026-10-22.json")
both retain unchanged compilation-source inventories and pass all commands.
Windows covers 249 default workspace tests, 306 combined-feature Chopper tests,
formatting/default and combined Clippy, UI's 28 tests/build, native release,
combined-feature WASI resource contracts in bundled Chromium/installed Chrome
and Edge, and 25 standard production Chromium contracts including compression
round trips. Linux independently covers default and combined native checks.
The [package identities](../../evidence-originals.md#sha256-c1028d2816a5c869a9aee265571fe3650af7e4258f77dd48cd5eae7ce4c2a380 "Original: docs/benchmarks/gzip-codec-package-identities-2026-10-22.json")
pin 25 native test executables, the release binary and seven final hosted assets;
the production resource-test entry point and test assets are absent.

Output gzip/deflate, deflated ZIP members, Zstandard and native runtime/stack
storage remain separate work. These deterministic small fixtures add no timing,
physical-I/O, large-job, external-device or complete RSS-cap claim. The local
build is separate from the previously published Pages artifact; macOS remains
deferred.
