## Publication I/O capacity and cleanup-failure admission (2026-10-20)

Resource-correctness follow-up to the output-catalog work below: publication now
reserves native/WASI manifest buffers (8 KiB), per-file and ZIP output buffers
(64 KiB), snapshot/ZIP assembly readers (the existing 64 KiB storage contract)
and the WASI heap copy buffer (256 KiB) before allocation. Writer ownership
retains charges through codec finalization, flush, sync and worker destruction;
reader/copy ownership retains them for the actual read/copy lifetime. Existing
buffer sizes and compression concurrency ceilings are unchanged. Codec internals,
native stack buffers, result/batch/name allocations, remaining JSON construction
and thread/runtime overhead remain outside this slice. No throughput or RSS-bound
claim follows from these charges.

A separate regression exposed an execution-lifetime bug: DiskFile previously
released temporary-space counters and relied on tempfile's silent Drop cleanup.
An unlink failure could therefore reclaim space that had not been removed and
remain hidden by a later successful retry. DiskFile now closes its handle and
explicitly removes its path. Only successful removal (or an already absent path)
reclaims data/live-file counters. Failure reports the path, increments
`temporary_cleanup_failures`, and retains conservative orphan-byte/file charges.
The first failed TempPath and its existing reservation move into the shared job
budget without allocating another retained path. Subsequent execution checks
return a path-rich cleanup error before retry/publication; the final job-directory
guard still cleans the whole workspace and reports its own failures. No new
background recovery or cleanup policy is introduced.

The red-capable Linux test replaced an open temporary file's name with a directory,
then dropped the file. Before the fix, `Context::check` incorrectly returned
success; after the fix it reports cleanup failure, keeps three temporary bytes
and the failed-path charge, and releases the final owners when the context is
dropped. This is an actual filesystem unlink-error seam independent of UID/chmod,
not a physical device-failure or power-loss simulation. The retained-parent
pressure test now also injects this error at the retry boundary and verifies it
cannot become successful original-stage execution. Linux-specific injection is
not reported as Windows/WASI failure injection.

The default workspace suites pass on native Windows (126 library tests) and WSL
Linux (127 library tests), with no serial override for those workspace runs.
Thirteen focused publication/output tests pass on Linux, covering pre-create
admission edges, moved worker/codec ownership, ZIP failure/finalization, charged
reader/copy lifetimes, manifest denial and cancellation cleanup/retry across
plain/gzip/Zstandard/ZIP, and decoded-catalog ownership. Counts overlap the
workspace suite, not independent acceptance populations. Five native compact-spill
tests pass after updating that opt-in adapter for explicit temporary-file closure.
Default and combined shuffle/partition + compact-spill workspace Clippy pass with
warnings denied; formatting passes. An initial delegated Windows executable was
blocked by Application Control; the subsequent rebuilt Windows workspace suite
executed successfully. No security policy was changed or bypassed.

The [validation record](../../evidence-originals.md#sha256-1e7eba1f5c4af0987776630035bb698bcb3fd84fe344d80ffc58758bd445ffd3 "Original: docs/benchmarks/publication-buffers-cleanup-validation-2026-10-20.json")
pins the current source/WASM/harness identities and retains the final focused and
browser command outputs. The rebuilt default WASI engine passes 25 Chromium
contracts and the bridge error check with the new publication reservations and
explicit cleanup; hosted output is rebuilt afterward to remove test assets.
These are correctness contracts, not matched A/B timing
samples. Historical catalog/parent records below retain their earlier source
hashes and are not rewritten as evidence for this follow-up. Dataset group
decoding, other lineage clones, codec/input-adapter allocations and cross-worker/
tab admission remain in [TODO](../../../TODO.md). The cleanup regression closes one
specific failure boundary, not every candidate's acceptance matrix.
