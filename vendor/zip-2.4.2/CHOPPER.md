# Chopper's ZIP metadata and member-container admission patch

Upstream: registry `zip` 2.4.2, package checksum
`fabe6324e908f85a1c52063ce7aa26b68dcb7eb6dbc83a2d148403c9bc3eba50`.
The original MIT license is retained. This copy is excluded from the workspace
and selected by the root Cargo patch; it is not an independent Chopper product.

The patch adds `ZipArchive::new_with_metadata_budget`, a constructor callback
receiving a conservative metadata allocation envelope before the corresponding
allocations. The caller retains its grant through archive/member destruction.
Existing constructors keep upstream behavior. The budgeted constructor retains
the actual parser's directory/fallback selection; a denied budget is terminal,
so resource denial cannot silently select an earlier archive instead.

The envelope covers directory search scratch, EOCD comments, ZIP64 extensions,
entry-vector/map construction overlap, names/comments and extra-field decoding.
It is a pinned-source upper allowance, not an exact allocator/RSS measurement.
The enabled Chopper features remain Stored/Deflate. The member-reader seam below
accounts for its containers; filesystem and runtime allocations remain separate.
Read `src/metadata_budget.rs` before changing
the implementation, features or dependency versions; re-audit allocation bounds
and run native/WASI admission and compatibility controls in the same change.

The current descriptor envelope is `capacity * (4 * size_of::<ZipFileData>() +
256)`, charged before the initial vector allocation and each explicit growth.
It covers vector growth and the simultaneous IndexMap vector/table construction.
`indexmap` 2.14.2 uses a dense `Vec<Bucket<K,V>>` and `hashbrown` 0.17.1 indices;
the pinned hash table rounds its 8/7 load-adjusted capacity to a power of two.
The 256-byte term covers indices/hash/control/alignment overhead. Normal entries
use their declared initial capacity; counts the parser discards do not receive
an unnecessary full-count grant. Growth is explicitly reserved before `push`.

Raw names/comments receive sixteen bytes per serialized byte for CP437/lossy
UTF-8 expansion, retained raw/decoded/map copies and growth/shrink overlap.
Extra data receives `ceil(8 * size_of::<ExtraField>() / 5) + 16` bytes per byte:
retained timestamp/NTFS items require at least five serialized bytes, while the
larger factor also covers vector overlap, raw/processed/replacement buffers and
Unicode extra-field text. A separate 128 KiB fixed constructor allowance covers
the two 2048-byte search buffers, control/Arc state and u16-sized malformed-extra
scratch. Archive comments and ZIP64 extensions are charged independently before
their boxed buffers allocate. Failed candidate objects drop before a checkpoint
restores the smaller live envelope; successful grants remain held conservatively
through archive destruction. These allowances intentionally exceed measured live
heap sizes and can require more admission than the old uncharged input path.

Compilation provenance must include this directory. Do not update the upstream
version independently of the Chopper ownership adapter and its tests.

`read::chopper_reader_container_bytes` exposes the pinned layout of the boxed
CRC/decompressor object and a caller's boxed borrowed `ZipFile`, plus the explicit
8 KiB member buffer. `make_reader` now spells out the existing upstream default
buffer capacity. Chopper adds the pinned miniz inflater size and reserves one
worst-case member-reader allowance before the first `by_index` lookup, retaining
it through selected-member/archive destruction. Name selection continues to open
each member, preserving failures for unrelated unsupported/encrypted members.
The grant conservatively includes a possible inflater even for Stored-only
archives. It is independent of metadata admission and does not alter directory
fallback. Re-audit both container layout and codec heaps when changing features,
dependencies or these constructors.
