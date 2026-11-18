## Validated current build published to Pages (2026-10-22)

After the user explicitly approved publishing, Wrangler 4.152.0 uploaded only the
validated seven-file `ui/dist` package to the existing Pages project `chopper`.
The production branch was verified as `master`, distinct from the local `main`
branch, and supplied explicitly. The
[deployment record](../../evidence-originals.md#sha256-554746247a9c6f78a9a76095e31f95c4e67f98f765151e550d2f1bec68adab64 "Original: docs/benchmarks/current-build-pages-deployment-2026-10-22.json")
pins every package hash/size, the dirty source/build validation, previous
production deployment and exact upload command/output. The new production ID is
`31da2710-941c-4e0c-8e5d-a21ee3646315`, with
[deployment URL](https://31da2710.chopper-1rx.pages.dev) and
[production URL](https://chopper-1rx.pages.dev/). The upload returned success before
a Windows terminal Unicode-printing error; a separate production listing
confirmed the deployment. No duplicate upload was issued.

The separate live
[Chrome](../../evidence-originals.md#sha256-8c5940320c5cb183b2daa1ff5eadfc0f0a4c8458c28cf9075f5f0eb8e2a84479 "Original: docs/benchmarks/current-build-hosted-acceptance-2026-10-22.json") and
[Edge](../../evidence-originals.md#sha256-4f3c33caf09ddcc922d38afd0861c5cbaca4707a63811b6678f9d23f4e475f06 "Original: docs/benchmarks/current-build-hosted-edge-acceptance-2026-10-22.json") passes
verify that all six served asset bodies exactly match the validated package;
Pages consumes `_headers` as configuration. Hashes remain stable through each
pass and the WASM exposes profiling without a resource-contract entry point.
This binds the live app to the current source inventory in the preceding
19-command native/WASI validation, rather than assuming a commit identifies a
dirty build. Production WASM SHA-256 is
`143b1e27c17feae5177007dcf51d95e135ddf19131e88cff4f7578b5d54b8a55`.

Both disposable browser contexts use the actual deployed UI and workers, with
only picker results replaced by a synthetic File and unique same-origin OPFS
parent. Analyze input reports five exact records and distinct counts, creates no
destination outputs and leaves confirmation disabled. Prepare exact outputs then
reports three CSVs/96 bytes and still leaves the destination unpublished.
Confirmation exports exact canonical CSV bytes with active two-row and 50-byte
limits, manifest counts/byte metadata/empty lineage, and a valid v1 marker for the
four result files. CSV byte hashes agree across browsers. The deployed cleaner
removes the deliberately abandoned preflight-reload workspace while preserving
the committed export and unrelated sentinel. Each fixture directory is removed
and each browser closes. Captured requests are GETs with no request payload.

This closes current-build startup/profile/preparation/export/cleanup deployment
parity for this small fixture in Windows Chrome/Edge. It does not validate native
picker dialogs, external filesystem destinations, real quota/device faults,
arbitrary interruption timing, other devices/OSes or large hosted jobs. The
previous deployed-artifact smoke check below remains separate evidence.
