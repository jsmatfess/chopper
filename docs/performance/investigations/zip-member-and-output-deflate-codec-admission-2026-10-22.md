## ZIP member and output deflate codec admission (2026-10-22)

The [`ZIP adapter`](../../../crates/chopper/src/engine/input_zip.rs) now admits a
worst-case member-reader allowance after metadata parsing and before any
`by_index` lookup. It stays live through member/archive destruction. The pinned
[vendor extension](../../../vendor/zip-2.4.2/CHOPPER.md) exposes the explicit 8 KiB
buffer and private boxed-container layouts; Chopper adds the miniz inflater
layout. The native Windows allowance is 51,880 bytes, separate from metadata
and Chopper's source buffer. Stored-only archives retain that conservative
allowance too. Selection still opens each member, preserving unrelated
unsupported/encrypted-member errors. Case-insensitive ASCII suffix matching no
longer allocates a lowercase name.

The [`output encoder owner`](../../../crates/chopper/src/output/deflate.rs) admits
352,110 bytes per native Windows gzip/raw-deflate encoder before construction.
The [source audit](../../evidence-originals.md#sha256-e33cd3bde26727b7b9bc22c5f9c3a4b89cc2a917964f2401ad7f220ef02cfd50 "Original: docs/benchmarks/zip-output-codec-source-audit-2026-10-22.json")
covers all pinned miniz nested boxes, the flate2 output Vec and metadata-free
gzip header; target layouts and wasm32's separately boxed code array determine
the corresponding WASI value. Grants survive explicit finalization, implicit
drop-time finalization and error-time codec destruction. Gzip CSV chunks, ZIP
CSV payloads and the ZIP manifest use the same owner. Existing publication
buffers and compressed temporary files keep independent charges; settings,
compressed bytes, strict CSV caps and publication semantics are preserved.

ZIP contracts cover six Stored/Deflated/lookup/selection shapes, 36 local/shared
edges, competing-owner denial/release/retry, retained EOF scopes, partial
consumer failure, seven malformed/selection error cases and real public-profile
cancellation after 65,536 decoded rows. Output contracts cover twelve local/shared
edges, denial before construction, concurrent encoder ownership, exact compressed
bytes for empty/Unicode/incompressible payloads, explicit finish, implicit Drop
and destination write/finish errors. Twenty-four output cases assert ownership
inside actual destination callbacks; twelve successful cases compare exact bytes
with the prior direct flate2 recipes.

The [development diagnostic](../../evidence-originals.md#sha256-df79c93ce697c7261ae6884fbae9f974865667cc370bc513598654e2d50ba404 "Original: docs/benchmarks/zip-output-codec-development-2026-10-22.json")
preserves the initially failing failed-directory-candidate assertion. That test
had treated whole-job peak as metadata-only peak; the new later reader grant
can dominate it. The corrected check records parser-requested peak separately
and still requires release of the failed candidate's extra metadata before the
small accepted candidate is retained. Whole-job admission-edge tests remain.
The [first broad attempt](../../evidence-originals.md#sha256-57d0032a177ca5e3abd5c7ce9bb667f983d92957ae788a2b37002b877732cafc "Original: docs/benchmarks/zip-output-codec-final-validation-2026-10-22.json")
stops at Clippy's unused-unit warning in the new test probe; the redundant unit
expression was removed.

The [corrected 20-command Windows pass](../../evidence-originals.md#sha256-8d7dedc8aab54cdffa2741b365aa4f6b32c0d61917fb5203f2749f3e777bf3c1 "Original: docs/benchmarks/zip-output-codec-checked-validation-2026-10-22.json")
and [six-command Linux/WSL pass](../../evidence-originals.md#sha256-016137972f66e90a2eb74e999a87438d38f13ee537e28f9ec611cdf126366c5a "Original: docs/benchmarks/zip-output-codec-linux-validation-2026-10-22.json")
both complete with unchanged compilation-source inventories. Windows passes 251
default workspace tests, 308 combined-feature Chopper tests, formatting/default
and combined Clippy, UI's 28 tests/build, native release and all new shared
contracts in bundled Chromium, installed Chrome and installed Edge. WASI reports
51,784 bytes for the ZIP reader allowance and 352,058 per output encoder. The
production WASI rebuild passes all 25 standard Chromium contracts, including
gzip/Zstandard/ZIP round trips, caps and cancellation. Final test-free packaging
is checked in the [package identity record](../../evidence-originals.md#sha256-2163739fb626a8849f6c324ff8ac2fc60449dd66943e8ef6df4db79eead8861b "Original: docs/benchmarks/zip-output-codec-package-identities-2026-10-22.json"),
with 25 native test executable hashes, release identity, seven hosted asset
hashes and absence of the production resource-test export. These runs use
disposable browser contexts and same-origin OPFS.

These are deterministic allocation/correctness checks, not performance or
physical-I/O measurements. The [ownership contract](../../resource-policy-research.md#zip-member-and-output-deflate-codec-admission-2026-10-22)
keeps Zstandard, source/job trees, parent discovery, runtime/stacks and OS/error/
allocator internals separate. No complete RSS-cap or broader platform/device
claim follows. Local packages remain distinct from the published Pages build;
macOS remains deferred.
