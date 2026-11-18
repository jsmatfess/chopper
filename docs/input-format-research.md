# Parsed-input formats: research and experiment contract

Historical research/proposal: dormant Rust `experimental-parquet-input` wiring
and its unused dependency were removed on 2026-10-24; no Rust Parquet decoder or
public runtime selector existed. Python adapter measurements remain historical.
The direct compact/Arrow IPC experiment was subsequently rejected and removed
on 2026-10-26; use direct CSV input. The dated proposal below is historical.
Current work belongs in [GitHub Issues](https://github.com/jsmatfess/chopper/issues).

Research date: 2026-10-16. This supports the two input-format experiments in
[historical TODO](../TODO.md); it contains no implementation or performance result.
Upstream unversioned documentation and `main` manifests can change. Pin the actual
crate versions and feature sets in any experiment's evidence.

## What the formats provide

| Candidate | Documented properties | Consequence for Chopper (inference) |
| --- | --- | --- |
| Arrow IPC file / Feather V2 | Feather V2 is exactly the Arrow IPC file format; supports LZ4/Zstandard. Feather V1 is distinct. [Arrow Feather docs](https://arrow.apache.org/docs/python/feather.html) | Treat Feather V2 and IPC file as one format candidate, not two independent alternatives; record compression explicitly. |
| Arrow IPC stream | One schema precedes successive record batches. IPC files add a footer with block locations for random access. [Arrow format specification](https://arrow.apache.org/docs/format/Columnar.html#ipc-streaming-format) | Stream batches without constructing a whole table; files suit retained snapshots, while streams give a useful sequential control. Neither layout alone imposes a byte budget. |
| Parquet | Column chunks are organized into row groups; readers first obtain footer metadata locating those chunks. [Parquet file layout](https://parquet.apache.org/docs/file-format/) | Existing seekable files can feed bounded scans, but decoding every output column still needs measurement. A forward-only CSV decompressor cannot directly replace random access without staging. |
| Existing compact row framing | Current compact paths preserve checked field views and avoid many owned conversions. [Repository implementation and evidence](performance-opportunities.md#already-delivered) | Include a bounded row-block snapshot control so improvements are not attributed to columnar layout when avoiding repeated CSV parsing explains them. |

The Rust IPC `StreamReader` accepts `Read` and yields individual `RecordBatch`
results. Rust IPC `FileWriter` accepts batches and requires `finish()` after
writing. These APIs support incremental adapters; retaining all returned batches
would defeat bounded execution. [StreamReader API](https://arrow.apache.org/rust/arrow_ipc/reader/struct.StreamReader.html),
[FileWriter API](https://arrow.apache.org/rust/arrow_ipc/writer/struct.FileWriter.html).

## Preserve decoded text

For a CSV snapshot, use the existing strict Chopper parser, then explicitly build
non-null UTF-8 columns. Preserve empty strings, leading zeros, date-looking text,
literal `null`/`NA`, whitespace, embedded newlines, column positions and row order.
Keep header presence and original header strings in Chopper metadata; do not rely
on unique Arrow field names to identify columns. This is a proposed experiment
contract derived from [Chopper's CSV and encoding rules](specification.md#csv-and-encoding).

Arrow's CSV reader infers types even for quoted values; its docs specifically
require explicit string types to retain leading zeros. String/null conversion and
UTF-8 checking are configurable. Replacing Chopper's parser with a convenience
CSV reader would therefore require an independent compatibility proof.
[Arrow CSV conversion docs](https://arrow.apache.org/docs/python/csv.html#customized-conversion).

For existing Parquet inputs, UTF-8 text has a `STRING` annotation on `BYTE_ARRAY`.
Typed numeric/date fields do not carry the original CSV spelling (inference).
Start a parity experiment with flat, required string columns; broader input
support needs an explicit policy for nulls, binary values, nesting, decimals,
timestamps and formatting before CSV output can be specified.
[Parquet logical types](https://parquet.apache.org/docs/file-format/types/logicaltypes/).
This restriction is an experiment scope, not a claim of general Parquet support.

## Memory and runtime limits

Rust Parquet's `with_batch_size` configures output rows but explicitly does not
guarantee internal buffer capacities. Account for metadata, pages, dictionaries,
codec state, decoded arrays and row-conversion overlap; a batch-row limit is not
a byte cap. Rare wide values must exercise rejection/cleanup paths.
[ArrowReaderBuilder API](https://arrow.apache.org/rust/parquet/arrow/arrow_reader/struct.ArrowReaderBuilder.html).

Parquet `ChunkReader` offers both offset-based range reads and sequential readers;
`get_bytes` returns an in-memory byte range. Its file-reader documentation also
warns about shared-reader position effects. Keep reads bounded and validate the
actual WASI descriptor adapter rather than loading an entire file into `Bytes`.
[ChunkReader API](https://arrow.apache.org/rust/parquet/file/reader/trait.ChunkReader.html).

The upstream IPC crate has no default features and optional compression
dependencies; the Parquet manifest enables several codecs by default and has
specific `wasm32` dependency settings. These are integration clues, not proof of
`wasm32-wasip1` compatibility. Compile and execute the pinned, minimal feature set
with this repository's WASI SDK and browser harness before claiming support.
[IPC manifest](https://raw.githubusercontent.com/apache/arrow-rs/main/arrow-ipc/Cargo.toml),
[Parquet manifest](https://raw.githubusercontent.com/apache/arrow-rs/main/parquet/Cargo.toml).

Chopper's browser uses bounded `File.slice` input, OPFS temporary files, a 1 MiB
storage transfer buffer, eight open OPFS handles and a 1 GiB WebAssembly memory
ceiling. Include transfer copies and OPFS space in the experiment; desktop
memory-mapping results do not establish browser behavior. [Current browser limits](browser.md#processing-and-limits).

## Proposed cache policy and acceptance

These are Chopper design requirements, not guarantees supplied by Arrow/Parquet:

- Identify snapshots by source content digest, compression/archive-member
  selection, resolved CSV settings and parser/semantic version. File path, size
  and timestamp can reject a candidate cheaply but cannot prove unchanged content.
  Record decoded logical digest, row/field counts and ordered headers separately.
- Write an incomplete artifact in the job workspace, validate the complete scan
  and footer/end marker, and only then make its manifest reusable. Validate framing,
  schema, lengths, row counts and digests on reads. Reject unsupported versions;
  never reinterpret old metadata silently.
- Reserve snapshot bytes alongside intermediate and prepared output bytes.
  Cancellation/failure removes incomplete artifacts; retained snapshots need
  explicit ownership, bounded eviction and abandoned-workspace cleanup. Start
  session-local; cross-session persistence needs a separate retention policy.

The source consistency requirement and canonical-spool option already exist in
the [specification](specification.md#analysis-and-confirmation); the format is not a
substitute for source-change detection.

Alternate direct CSV, IPC and bounded row-block complete jobs. Report first-job
conversion cost separately from repeated reuse; include source revalidation cost
in each reuse policy. Record allocations, peak reservations/RSS, snapshot size,
temporary logical traffic, cache conditions and native/WASI results. Check exact
decoded values/order, logical digest, seeded output bytes and metadata, strict
serialized CSV byte caps, malformed/truncated snapshots and cancellation cleanup.
Measure existing Parquet inputs separately from CSV-to-Parquet preconversion.
No speedup, bounded-memory guarantee or production support follows from this research.
