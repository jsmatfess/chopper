## Input-adapter capacity and Windows profile invalidation (2026-10-20)

This resource-correctness slice charges fixed compressed-input source buffers
before allocation and holds the reservation in the actual reader. Gzip and ZIP
retain their existing 8 KiB buffers; Zstandard retains its installed codec's
recommended input capacity (`DCtx::in_size()`, 131,075 bytes on this build).
The ZIP end-directory preflight also charges its bounded tail allocation
(at most 65,557 bytes), then releases it before archive construction.
Preparation, full-file profiling and experimental input snapshots use their
existing workspace/shared pool. Column inspection and sniffing share the process
pool for these adapter buffers. Buffer sizes and decoding semantics are unchanged.

This does not account for codec-native heaps/windows, decoded ZIP directory
entries/names/scratch, boxed adapter descriptors, OS handles, sniff samples or
the inspection parser's other allocations. These reservations remain working
allocation accounting, not an RSS cap. Native capacity-edge/concurrent-owner
tests cover denial, release, retry, concatenated gzip/Zstandard frames, ZIP/plain
input, truncated input and cancellation. A compressed-profile test checks shared
admission and final returned-owner release.

Full-suite validation exposed a pre-existing Windows cache bug: a rapid same-size
rewrite preserved length, creation time and modification time. A cached profile
therefore accepted a corrupt gzip while a fresh scan rejected its CRC. Reverting
only the new gzip buffer wrapper reproduced the failure. The deterministic
regression rewrites equal-length CSV text and restores modification time; it
must return the new row. Windows now rescans and retains no unused cache owner.
Returned profiles still retain their own charges through the final drop, with
capacity-edge and denial tests. Unix metadata-based reuse and browser File-object
invalidation are unchanged. Existing pre/post scan metadata checks remain;
this fix does not establish a snapshot guarantee during concurrent modification.

A simple NTFS USN token was considered but not adopted: Microsoft documents that
repeated same-kind changes can coalesce while a file remains open
([change-journal records](https://learn.microsoft.com/en-us/windows/win32/fileio/change-journal-records)).
A safe bounded token would need writer-sharing and journal-reset handling with
separate platform acceptance. No whole-source hash pass or unverified token is
added to cache lookup. Windows repeated profiling now costs another full scan;
there is no speedup claim for this correctness fallback.

Cleanup acceptance is also extended from the earlier Linux checkpoint below:
actual Windows and Linux unlink failures retain orphan charges and stop retry.
Two concurrent failed unlinks retain both files' bytes and one charged first-error
path; the final context drop releases the path owner and removes the workspace.
These tests inject a pathname failure, not physical-device failure.

The [validation record](../../evidence-originals.md#sha256-96e4e084a5e6fd756d83b6948e1b223068605c46995ddea16b5ebb18326e97a4 "Original: docs/benchmarks/input-adapters-device-cadence-validation-2026-10-20.json")
pins sources, WASM and test harnesses and preserves failed attempts separately
from the final checks. The Windows default workspace passes (129 library tests),
and combined shuffle-partition/spill-block/parallel-profile library tests pass
146. Formatting, default/combined Clippy, portable-core WASM and experimental
input-snapshot compilation pass. Rebuilt default WASI passes 25 Chromium contracts plus
the storage-error bridge check; production hosted output is rebuilt afterward
to remove test assets. Linux focused checks cover nine profile unit tests,
eight profile integration tests, two cleanup tests and the exact retained-parent
retry regression. Browser typed memory denial/late-parent rollback and actual
WASI unlink-error injection remain open: the production protocol has no injected
pool-owner or filesystem-failure seam. Disk-budget and UTF-8 bridge tests do not
substitute for them. No allocation-completeness, scale, throughput, physical-I/O
or default-promotion claim follows.
