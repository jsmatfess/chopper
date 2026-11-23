# Columnar input: direct adapter follow-up

Historical research/proposal: dormant Rust `experimental-parquet-input` wiring
and its unused dependency were removed on 2026-10-24; no Rust Parquet decoder or
public runtime selector existed. Python adapter measurements remain historical.
The direct compact/Arrow IPC experiment was subsequently rejected and removed
on 2026-10-26; use direct CSV input. The dated proposal below is historical.
Current work belongs in [GitHub Issues](https://github.com/jsmatfess/chopper/issues).

Researched 2026-10-18. This supplements [input-format research](../../input-format-research.md)
with a concrete dependency/adapter proposal and acceptance boundaries. No adapter
was implemented, compiled or benchmarked for this note.

## What the existing experiment establishes

Repository inspection: [benchmark-input-formats.py](../../../scripts/benchmark-input-formats.py)
uses Python CSV parsing to create snapshots, then decodes each snapshot into a
complete `adapted.csv` before invoking the unchanged CLI. IPC is uncompressed;
Parquet uses Snappy and explicit string arrays. Replays hash the original CSV
source again. Its compact/u64 formats include the header as a row, use
1,024-row blocks and check the 16 MiB payload limit **after constructing the
payload**. Those prototypes are neither direct engine inputs nor proof of
pre-allocation bounds. Existing output/field parity and regression measurements
remain useful; they do not answer whether a direct columnar adapter wins.

Local metadata inspection found PyArrow 26.0.0 under
`/tmp/chopper-format-python`, and no cached Arrow/Parquet Rust crate manifests
in the repository's Cargo registry. These are environment observations, not
dependencies installed by this research.

## Recommended pinned experiment

Use Apache **arrow-rs 60.0.0**, pinning direct `arrow-array`, `arrow-schema` and
`arrow-ipc` dependencies to `=60.0.0`; pin `parquet =60.0.0` separately when
evaluating existing Parquet. The tagged workspace requires Rust 1.88 and edition
2024; local Rust 1.99 satisfies that compiler floor, but this is not a build
result. [Tagged workspace manifest](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/Cargo.toml).

| Candidate | Initial configuration | Direct engine boundary |
| --- | --- | --- |
| Reusable IPC file / Feather V2 | `arrow-ipc`, defaults off; no compression/dictionaries in the Chopper-produced snapshot | One validated batch at a time; expose string views in column-position order and pack into the existing row consumer |
| Compact row snapshot | Existing checked row framing or a separately versioned byte-bounded row-block envelope | Same logical record consumer and digest; no intermediate CSV serialization |
| Existing Parquet | `parquet`, defaults off, features `arrow`, `snap`; initially flat non-null string columns | Ordered row-group/batch scan, all output columns, then the same row consumer |

Feather V2 is Arrow IPC file format; it is one candidate, not a separate layout.
Compression settings must be explicit. [Official Feather documentation](https://arrow.apache.org/docs/python/feather.html).
The [tagged IPC manifest](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/arrow-ipc/Cargo.toml)
has no default features and optional LZ4/Zstandard dependencies. The
[tagged Parquet manifest](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/parquet/Cargo.toml)
enables many codecs by default, exposes the `arrow`/`snap` features, and has
explicit wasm32 dependency configuration. Minimal synchronous features avoid
requiring an async runtime, object store or Python. Record the complete lockfile
and enabled feature graph in measurements; the direct version pins alone do not
pin every transitive crate.

These are plausible native/WASI choices, **not verified WASI support**. First
compile and execute a tiny round trip using this repository's actual
`wasm32-wasip1` target and Chromium filesystem bridge. Test seeking, supported
codecs, descriptor lifetimes, cancellation and malformed inputs before a larger
matrix. Browser `File.slice`, `fd_seek` and `fd_pread` already exist in
[fs.ts](../../../ui/src/browser/fs.ts); native mmap or a JS/Wasm-only upstream example
does not establish compatibility with that bridge.

## Exact text and stable identity

For **CSV-derived snapshots**, keep the strict Chopper parser. Emit only
non-null `Utf8` columns, appending every decoded field as a value, including
`""`, `"null"`, `"NA"`, leading zeros, spaces, date-looking strings, Unicode,
NUL and embedded newlines. Arrow represents null validity separately from string
offsets/data; empty text is not a null. Neither format preserves original CSV
quoting/line-ending bytes unless those bytes are stored separately. The target
is exact decoded field text and Chopper's existing serialization contract.
[Arrow columnar layout](https://arrow.apache.org/docs/format/Columnar.html).

Assign storage names such as `c0`, `c1`, … and keep the ordered original header
strings plus header-present flag in versioned Chopper metadata. This preserves
duplicate/empty names and avoids name-based lookup ambiguity without requiring
other Arrow consumers to accept duplicate names. Resolve user column references
with existing Chopper rules; never silently deduplicate or rename the logical
header. A headerless input remains headerless after replay, and a header-only
input remains a zero-data-row input.

Scan batches and row groups in file order with no filtering, row selection,
projection, reordering or implicit multi-file dataset discovery. Reconstruct the
existing source ID from the cumulative data-row ordinal, using checked arithmetic
and the same header convention as CSV. Parallel decode may be added only with
ordered delivery. Include per-block start ordinal/count and final row count in
Chopper snapshot validation. Recompute the existing logical record digest from
decoded fields rather than hashing Arrow physical bytes or trusting a cached
summary. Feed rows directly into the current packing/profile/ingestion boundary;
writing another CSV would repeat the old adapter experiment.

For **existing Parquet**, begin with flat required `BYTE_ARRAY` annotated
`STRING`, or equivalent UTF8 annotation, and reject unsupported columns/nulls
with a clear schema error. The annotation specifies UTF-8 interpretation; typed
numbers/dates/decimals do not retain their original CSV spellings.
[Parquet logical types](https://parquet.apache.org/docs/file-format/types/logicaltypes/).
That text-only scope is useful input interoperability, not general typed support.

Typed support needs a separately versioned rendering contract: null token and
its collision with literal text, finite/nonfinite floating-point representation,
decimal scale, timestamp unit/timezone, binary encoding, booleans, nested values
and column-name policy. Null-to-empty is lossy and must not be presented as exact
text fidelity. A typed Parquet-to-CSV benchmark compares the declared rendered
records, not reconstructed original CSV text. Keep typed rendering out of the
initial parity experiment.

## Allocation and filesystem constraints

The upstream APIs do not implement Chopper's admission ledger:

- IPC `FileReader` requires `Read + Seek`. Its builder allocates the footer,
  schema/block catalog and eagerly reads dictionaries. Batch decode can copy
  misaligned buffers; validation includes UTF-8 and offset checks. The lower-level
  `FileDecoder` accepts caller-supplied block buffers. Preflight and reserve the
  footer/catalog/schema and each complete block before decoding, or use that
  lower-level API with a bounded Chopper envelope. Leave validation enabled.
  [Pinned IPC reader source](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/arrow-ipc/src/reader.rs).
- String builders expose value/offset/validity capacities and may grow their
  internal vectors. Ordinary `Utf8` offsets have an i32 limit; append can panic
  on overflow. Bound bytes and offsets before appending, including rare wide
  single records, and reserve retained arrays plus construction/growth overlap.
  A row-count batch target alone is insufficient.
  [Pinned builder source](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/arrow-array/src/builder/generic_bytes_builder.rs).
- Parquet `with_batch_size` controls emitted rows and is explicitly only a hint
  for internal capacities. Account for metadata, compressed input, decoded pages,
  dictionaries, offsets, codec scratch and row-pack overlap. Disable unnecessary
  predicate/page-index work; selecting all columns is required for whole-row
  output. Arbitrarily large external dictionaries/pages need bounded admission
  and clean rejection, not an assumed small batch guarantee.
  [Pinned Arrow reader source](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/parquet/src/arrow/arrow_reader/mod.rs).
- `ChunkReader` returns both sequential readers and in-memory `Bytes` ranges;
  its `File` implementation clones descriptors and allocates the requested
  range. Implement a checked source wrapper with offset/length bounds, charged
  retained ranges and independently positioned readers. Do not load the entire
  input into `Bytes` or depend on browser descriptor cloning without testing it.
  [Pinned ChunkReader source](https://raw.githubusercontent.com/apache/arrow-rs/60.0.0/parquet/src/file/reader.rs).

Start with Chopper-produced uncompressed, dictionary-free IPC whose encoded
batch sizes are known. Preflight limits are also required on imported IPC before
calling high-level APIs. Footer/dictionary limits may constrain otherwise valid
foreign files; document the experimental limits. A conservative reservation must
cover actual upstream allocations and release on every error. If that cannot be
demonstrated, keep the adapter experimental and report the accounting gap.

## Reuse and integrity contract

These are proposed Chopper requirements, not format guarantees:

1. Identify a snapshot by source content digest, selected archive member and
   compression, resolved parser settings, ordered header semantics, and parser/
   adapter version. Path/size/mtime are advisory rejection hints. Preserve the
   existing source-stability checks; hash actual source bytes during the scan.
2. Write into a job-owned incomplete artifact, charging every byte to the same
   disk budget as intermediates and prepared outputs. Validate framing, lengths,
   schema, row counts, logical digest and a separate artifact digest before
   atomically sealing a reusable manifest. Version the application envelope,
   logical text contract and codec settings separately from the Arrow IPC version.
3. On reuse, validate the source according to the stated policy and charge its
   full content-hash pass to replay time. Verify artifact digest/framing and
   decoded logical digest. Reject stale, truncated, unsupported or modified
   snapshots; never treat missing trailing data as a shorter valid dataset.
4. Keep prepared output immutable through confirmation/export. Start with
   session-owned snapshots, explicit retained disk grants and final-owner cleanup.
   Delete incomplete files on cancellation/failure; preserve unrelated completed
   artifacts. Cross-session eviction, quota races and abandoned-cache recovery
   need an explicit ownership policy before persistence is enabled.

Parquet page checksums are optional and cover pages, not Chopper's logical text
or source identity; they do not replace this application contract.
[Official checksumming specification](https://parquet.apache.org/docs/file-format/data-pages/checksumming/).

## Measurement that closes the TODOs

Compare direct CSV, direct IPC and direct compact-row input under the same
engine. Report conversion-inclusive first jobs, steady replay jobs with source
revalidation, and amortized totals for a declared number of jobs. Separately
measure existing Parquet input against an equivalent rendered-text CSV; exclude
CSV-to-Parquet preprocessing from that existing-input result and report it in any
preconversion experiment. Include plain output, partition/shuffle/CSV output,
many columns, rare wide fields, many batches and multi-level external execution.

Alternate complete jobs and record native/WASI wall/CPU time, allocations,
simultaneous peak reservations/RSS, source/snapshot/temp/output bytes, transfer
copies and retained space. Separate warm WSL cache evidence from measured cold
cache/physical SSD evidence. Require exact decoded text/order/source IDs, logical
digests, seeded output/lineage/stage parity and strict serialized CSV byte caps
for text-equivalent inputs, including duplicate headers and empty datasets.
Test source replacement, corruption/truncation, oversized metadata/values,
reservation/disk denial and cancellation cleanup. Until direct measurements and
bounded admission pass, the two integration TODOs remain open.
