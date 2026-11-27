# Chopper's miniz-only flate2 package

Upstream `flate2` 1.1.10 has package checksum
`6e634e2e0ebac1ee034020da1ca582e17ffe4e0f5e985823721e168928136dcb`.
The original MIT and Apache-2.0 license notices are included.

`chopper-flate2` has its own Cargo package identity. The manifest exposes no
backend features, and the backend module always selects miniz. Another
dependency can enable an alternate backend on upstream `flate2` without
changing the codec Chopper executes or the allocations it must admit.
The pinned `miniz_oxide` 0.9.1 is shared with the engine's `size_of` charges.
The inflater's buffers live inline in that type. The compressor's additional
boxes follow the pinned source and target architecture, irrespective of stable
miniz features elsewhere in the graph.

Chopper also uses this package through its separately named ZIP reader.
Keep the [codec admission audit](../../docs/resource-policy-research.md#zip-member-and-output-deflate-codec-admission-2026-10-22)
and the downstream package checks current when updating this source.
