## Retained partition boundary key admission (2026-10-22)

The ordinary sorted partition emitter formerly copied each tuple key with an
uncharged `to_vec` while the decoded row remained live. Its new
[`BoundaryKey`](../../../crates/chopper/src/engine/keys.rs) owns a reusable vector and
reservation. It admits replacement capacity, including both old and new vectors
during growth, before changing key bytes. Shorter keys retain the vector's actual
capacity/grant; final owner destruction drops bytes before returning admission.
The next child's sink is entered only after boundary-key admission succeeds.
The key can outlive its decoder row independently.

An explicit initialization bit preserves the first empty-tuple boundary: empty
selected columns still start a logical group instead of matching an uninitialized
empty buffer. Tuple framing, canonical ordering and shuffle suffix removal are
unchanged. Failed growth keeps the preceding key and grant intact. Reuse can
retain more capacity after a rare-wide key; new accounting may deny tight jobs
that formerly left this copy uncharged.

The [validation record](../../evidence-originals.md#sha256-e5874d948baa6377856a0099e993586f8b1fbe4c8fdecb5eecdf9f302af6f5c4 "Original: docs/benchmarks/partition-boundary-final-validation-2026-10-22.json")
includes shared native/WASI checks for six local/shared replacement boundaries,
zero-allocation empty tuples, exact escaped/NUL/Unicode key bytes, retained
capacity after shortening and a competing owner that denies growth until released.
Failures preserve both owners; final drops restore zero reservations. Existing
ordinary and experimental pipeline contracts cover seeded order, child membership
and metadata, sink/cancellation cleanup and retry. These are accounting and
correctness fixtures, not speed, storage-throughput or RSS-cap evidence.

All 20 final-source commands pass with unchanged source identities: formatting,
default/combined-feature Clippy, 247 default workspace tests, 304 combined-feature
Chopper tests, printed lineage/boundary contracts, UI checks/build, native/WASI
releases, three browser resource runs, 25 production browser contracts and final
test-free packaging. The [binary/package binding](../../evidence-originals.md#sha256-67484d2e50a712ab0218bae6f68cd7ded1eab8af5cbf4ad7f2b588cc139b8c99 "Original: docs/benchmarks/partition-boundary-package-identities-2026-10-22.json")
retains native test/release hashes, the harness and seven local hosted file hashes.
This local package is separate from the published Pages artifact. Later weighted
fixture-only changes have their own report above.
