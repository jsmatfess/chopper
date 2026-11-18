## ZIP metadata parser admission and owner lifetimes (2026-10-21)

The allocation-coverage decision is to admit the metadata selected by the actual
ZIP parser before it allocates, including earlier-directory fallback and ZIP64
extensions. The old final-EOCD eligibility expression cannot establish that bound.
The implementation now uses a [pinned zip 2.4.2 patch](../../../vendor/zip-2.4.2/CHOPPER.md)
and a private [input adapter](../../../crates/chopper/src/engine/input_zip.rs). Existing
Stored/Deflate selection, CRC validation and legacy eligibility remain intact.
No experiment default, seed, pipeline or publication policy changes.

The callback receives a conservative total allowance before fixed search/control
scratch, archive comments, ZIP64 extensions, descriptor vector/map overlap and
raw/decoded names, comments and extra fields. Actual vector growth is charged even
when the parser discards an untrusted initial count. Failed candidates drop before
their allowance shrinks; callback denial aborts every parser fallback loop. The
adapter preserves the original typed local/shared error and holds its separate
grant through archive/member destruction, including EOF and consumer failure.
Keeping the grant only inside the archive reader would release it before the
archive's metadata fields drop. The [source audit](../../evidence-originals.md#sha256-8def2d8ad5ffee8969eb5cb2f9edb75336e5d0461eb3c9e743f253097cda4c00 "Original: docs/benchmarks/zip-metadata-owner-source-audit-2026-10-21.json")
records upstream identity, unchanged files and the pinned indexmap/hashbrown
allocation sources. The patch document owns the allowance formulas and re-audit
requirements; fresh build source inventories now include `vendor/`.

The shared [contract](../../../crates/chopper/src/engine/input_zip/resource_contracts.rs)
uses twelve small archive forms: ordinary, many-entry, earlier-directory fallback,
failed large candidate, underreported directory length, UTF-8/lossy comments,
CP437, repeated timestamp extras, NTFS extras, malformed extra-field length,
ZIP64 extension and a long archive comment. It compares admitted names/comments
against the original constructor and verifies complete CSV bytes. Ninety separate
callback-denial checkpoints must terminate without parser fallback. Exact shared
peak minus one/exact/plus one, typed local denial, a held competing owner followed
by release/fresh retry, retained EOF metadata, source-buffer lifetime, consumer/CRC
failure and public-profile cancellation all require final release. Explicit
allowance checks cover decoded expansion and failed-candidate release rather
than relying only on self-measured admission edges.

The [red/green control](../../evidence-originals.md#sha256-37bb0f22f897bf8b7350c8970a2f51d0a02b6987e6161a3bc5c4cd28e7b5ebe6 "Original: docs/benchmarks/zip-metadata-owner-regression-2026-10-21.json")
removes the production metadata charge temporarily and observes the lifetime
assertion fail, then restores it and passes. This earlier ten-form development
pass is separate from the expanded final twelve-form contract. The
[initial native build](../../evidence-originals.md#sha256-7d3e04910057d2693b2fe7135b742403e7609a11499b2405630823f03f6fbd2b "Original: docs/benchmarks/zip-metadata-owner-build-2026-10-21.json"),
[allocation probes](../../evidence-originals.md#sha256-d9a92f4564c0ee68b8fbb2dadefe00acd86c1592a9d5ff60c4e4484a710e4df5 "Original: docs/benchmarks/zip-metadata-owner-probe-2026-10-21.jsonl") and
[initial browser contracts](../../evidence-originals.md#sha256-cb4b6b0a2cbf231b0cabbdf979c1ea10a94f20738d3d2b7a579ee1d90431eeb5 "Original: docs/benchmarks/zip-metadata-owner-browser-contracts-2026-10-21.json")
are retained with their original sources and development transcripts; they
predate the final actual-vector-growth refinement and expanded cases.

The final [validation pass](../../evidence-originals.md#sha256-bda8a71b010c29db43df6d26e165e0bcf57ac34d9f4a86fc0f383a2d548f0e05 "Original: docs/benchmarks/zip-metadata-owner-final-validation-2026-10-21.json")
passes the Windows default workspace (140 library tests), candidate library
(155), formatting, both all-target Clippy configurations, 28 UI tests/build,
embedded native rebuild, 25 standard Chromium tests, bridge and peer-cleanup
checks, and base/candidate WASI resource contracts. The recorded
[17-feature combination](../../evidence-originals.md#sha256-b2e8f8f67960e9dd196338574928f054e0eaedcea58d87327b14caf6ec25118b "Original: docs/benchmarks/zip-metadata-owner-feature-validation-2026-10-21.json")
passes 221 library tests and all-target Clippy, plus fifteen benchmark/provenance
unit tests. Linux/WSL passes the focused twelve-form contract. These counts belong
to separate configurations and are not added together.

The [cross-runtime report](../../evidence-originals.md#sha256-c0bad41b7e6be9d99b8954c9a0b90a2b0df836b339790bfde9854988220914b1 "Original: docs/benchmarks/zip-metadata-owner-cross-runtime-2026-10-21.json")
compares all twelve fixture identities across Windows, Linux/WSL and both WASI
variants. Native reports match exactly; the ordinary archive's required peak is
140,512 bytes on native and 140,352 on WASI because representation sizes differ.
Every report retains ninety terminal callback denials, CRC/cancellation cleanup
and zero final reservation. Final hosted packaging passes the production export
guard and removes test assets. These are real local files/OPFS and controlled
failures, not physical-device faults, deployed-browser coverage or codec/RSS
accounting closure.

The initial patched native probe rejects fallback, long-name and independent
8 MiB ZIP64 cases under a 1 MiB shared ceiling with typed denial; all remain
accepted under 128 MiB. The ordinary 8,193-entry archive retains its legacy
4 MiB eligibility rejection. Successful native scan reservation peaks are
11,130,556, 1,211,488 and 8,640,177 bytes for those three accepted cases,
respectively, versus approximately 119 KiB in the original diagnostic build.
These are conservative working-allocation reservations, separate from measured
requested heap, allocator retention and RSS. Different probe paths also prevent
attributing tiny incidental allocation differences to this patch. No timing or
whole-job performance effect is inferred. Tight budgets can now reject an input
whose metadata previously allocated without admission; that is the intended
resource behavior, not a new archive-format restriction.

The [final pinned release build](../../evidence-originals.md#sha256-950ad72f3d4aa98b7da36aac02979539ddcbd91d442b5b3f41734b913fec156e "Original: docs/benchmarks/zip-metadata-owner-final-build-2026-10-21.json")
includes the complete vendor inventory and verifies unchanged compilation inputs.
Its [fresh probe pass](../../evidence-originals.md#sha256-5cbdaa062bf8a24a8ebeda3a4cd7d55553bee9b8485c41eb4fec6c67872b4b7b "Original: docs/benchmarks/zip-metadata-owner-final-probe-scope-2026-10-21.jsonl")
retains the same low/high-capacity outcomes and reservation peaks described
above. The [comparison](../../evidence-originals.md#sha256-e214907d8f3d2f546ac7e229dd093eb0d101967f9475d1a0799b0c70f1b20160 "Original: docs/benchmarks/zip-metadata-owner-final-probe-summary-2026-10-21.json")
links each original observation by source hash/physical line and confirms all
five deterministic fixture identities match the pre-owner pass. The immediately
preceding [duplicate final probe](../../evidence-originals.md#sha256-5579229d54b956412f160a6787924ef0ab0d15a05aa6aed741f43c5b8a37f504 "Original: docs/benchmarks/zip-metadata-owner-final-probe-2026-10-21.jsonl")
is preserved but excluded: its harness's old closing scope text still claimed no
metadata grant existed. That wording is corrected to distinguish diagnostic
observations from the separate ownership proof; no engine/fixture behavior changed.
The [public browser profile probe](../../evidence-originals.md#sha256-093a0bce9426b495f4dbd406382d514baaab90661e1a7fa4982230119e111d98 "Original: docs/benchmarks/zip-metadata-owner-final-public-browser-2026-10-21.json")
uses the final production WASM and real OPFS, preserving all four accepted forms,
the ordinary many-entry eligibility rejection and complete workspace/fixture
cleanup. It does not measure browser allocations or inject the native shared
pool ceilings. This closes the audited ZIP metadata slice; the broader resource
coverage item remains open.
