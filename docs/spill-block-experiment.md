# Compact external-spill block experiment

Status: evaluated opt-in candidate, 2026-10-16. [Measurements and decision](performance.md#compact-external-spill-block-evaluation-2026-10-16): keep v1 defaults; native jobs regress while tested active browser jobs improve. See the [GitHub Issues](https://github.com/jsmatfess/chopper/issues)
for acceptance work and the [implementation](../crates/chopper/src/storage/spill_blocks.rs).
`experimental-spill-blocks` applies to external sort runs and routing buckets.
Its former prefix-distribution consumer was removed on 2026-10-24; dated evidence
retains that build context. Intermediate datasets and final encoded
CSV snapshots retain their existing representations. Defaults remain v1 rows.

## Interface and reservations

The adapter accepts and returns the exact existing v1 row byte stream. It does
not change row IDs, ordinals, keys, field text, collision refinement, random
domains or operation algorithms. Grouping, sorting and final consumers share the
same implementation across formats; the storage interface selects the adapter.

Each writer uses its caller's one existing I/O-buffer grant. For a block file,
the buffer sits inside the encoder and the outside `BufWriter` has zero capacity;
for a raw file, the outside writer holds it. Encoder-box capacity has its own
reservation, released with the file. If that optional construction reservation
is denied, the file uses raw v1 framing. Flush closes the last block and releases
the payload buffer; append can continue through the same interface.

Each reader keeps the existing 64 KiB fixed grant: about 60 KiB of physical input,
4 KiB of reconstructed v1 input, and the exact decoder-box size. No block-sized or
wide-row-sized vector is allocated per reader. This preserves the existing merge
reader allowance while reducing physical read calls relative to small-buffer
transcoding. Consumer row/key/decode reservations remain separate and unchanged.

## Experimental on-disk format

All integers are little-endian. A nonempty file contains one or more blocks:

```text
block:
  8-byte magic/version "CHOPSB01"
  repeated rows:
    u8 marker = 1
    u64 row ID
    u64 ordinal
    u32 key length
    key bytes
    u8 field-count tag:
      0: reuse this block's previous field count
      1: read a new u32 field count
    repeated fields:
      u32 UTF-8 byte length
      field bytes
  u8 marker = 0
  u32 number of rows in this block
```

The first row must define a field count. Counts can change within a block; equal
counts reuse the previous value. The writer closes after 256 rows or reaching a
64 KiB physical-byte target, whichever comes first, finishing the current row.
A large record therefore forms a larger block while streaming through fixed
buffers. Empty files contain no blocks. Footer counts avoid seeks, header patches
and rewrite traffic; both native and WASI execution remain forward-only.

The decoder bounds block row count, field count, key length and cumulative field
payload against the same job limits used by the existing row readers. Individual
key/field lengths must additionally fit u32 in this prototype. UTF-8 is checked
by the existing row/borrowed-field consumers. No numeric/date/null inference,
string dictionary, compression or checksum is introduced. A valid-frame bit flip
can still change data, as with the existing unchecked spill framing.

Incomplete words/rows, unknown versions/tags, missing counts, invalid lengths,
truncation and inconsistent footer counts fail. Stream failures are terminal;
callers discard the job's temporary state and do not publish partial output.
The five codec tests cover arbitrary source chunks, changing/zero field counts,
multiple blocks, wide Unicode streaming, corruption, capacity edges, fallback,
append, reader lifetimes, cancellation and exact disk-quota edges.

## Measurement requirements

Build default and candidate binaries from identical sources, changing only the
feature. Alternate complete native jobs, retain separate allocation censuses,
and verify actual block use through diagnostics. Include global/per-group
shuffle and downstream balanced splitting, narrow/many-column/rare-wide shapes,
one/four workers, and hierarchical merges. Compare exact CSV output and logical
metadata, independently verify unique IDs/fields/group isolation, and retain CPU,
RSS, reservation and temporary I/O/space counters. Native/WASI comparisons must
use paired builds too.

`compact_spill_source_bytes` counts v1 bytes represented by sealed blocks;
`compact_spill_stored_bytes` counts their physical bytes. Together with actual
temporary-write traffic, they let tests verify the original write-once invariant
without assuming v1 physical sizes. File/block/row/fallback counters distinguish
active paths from unchanged resident controls. These are logical engine counters,
not physical SSD traffic, allocator internals or RSS bounds.

Transcoding through the existing v1 interface adds work. Results evaluate this
specific adapter and format, not a future direct compact consumer. Warm WSL/OPFS
results cannot certify physical SSD/cache conditions. Compression remains a
separate experiment requiring storage evidence; no default-format promotion is
implied by the feature's presence.
