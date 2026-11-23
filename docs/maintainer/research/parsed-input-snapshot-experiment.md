# Historical experiment: removed after E3

Direct compact and IPC integrations were separately rejected and removed on
2026-10-26. `experimental-input-snapshots` is invalid and `engine::snapshots`
is no longer available. Migrate callers to direct CSV through the ordinary Job
input and preparation API. The dated design/checkpoint below is historical;
replay requires the [archived source and original build inputs](../../history/rejected-input-snapshots-2026-10-26/README.md).

# Direct parsed-input experiment

Implementation design, 2026-10-19. This supplements the
[dependency/format research](columnar-input-followup.md); it is not a benchmark
result or an enabled cache. The existing CSV-to-CSV adapter measurements do not
close this experiment.

## Native prototype test checkpoint, 2026-10-20

The opt-in `experimental-input-snapshots` feature now has direct compact-row
and Arrow IPC readers feeding the common ingestion consumer. Six native tests
cover exact prepared output/metadata parity with CSV, literal text and header
conventions, partition/shuffle/balanced operations, UTF-8/UTF-16 output caps,
source/settings/artifact binding, malformed lengths/UTF-8/logical digests,
memory/disk denial, cancellation and cleanup. Existing caller-owned directories
survive failed creation; failed replay retains the cache and publishes no job.

Conversion hashes a bounded temporary copy of the raw source and parses that
copy, then verifies the original source hash before committing the manifest.
The regression test changes and restores the original during parsing: matching
before/after hashes alone previously admitted records from the changed source.
The copy prevents that mismatch. Its disk overlap with the encoded artifact is
included in the creation ceiling and reported peak; the copy is removed before
manifest publication. This ceiling covers the fresh owned directory only. A
future cache manager must separately account for any retained older artifacts.
IPC accepts the pinned Arrow writer's all-valid bitmaps, checks their lengths
and bits, and continues to reject null values.

Validation: `cargo test --workspace --all-features` passes all 293 tests,
including the six snapshot tests and two decoded-text packing contracts.
The local HTTP server tests require localhost access outside the sandbox;
they pass in that run. Workspace Clippy with all targets/features and
`-D warnings`, formatting and whitespace checks also pass.

This checkpoint does not complete the performance TODO. Conversion-inclusive
and repeated-job benchmarks, allocation/storage measurements, actual WASI
reader execution and browser import integration remain unverified. Parquet
reader support is not implemented. No cache or input defaults are enabled.

## Reader seam

Keep the existing strict CSV parser and its owned/compact reuse paths. Extract
the common ingestion consumer behind a statically dispatched record reader:
advance into reusable owned fields or checked compact fields, report record
ordinal, and expose retained scratch capacity for reservation transfer. CSV,
compact snapshots and IPC must enter the same header handling, logical digest,
source-ID assignment, packing, operations and CSV output plan. A snapshot reader
must not serialize a CSV stream for another parser. Profile/sniff support is a
separate integration concern and must not be implied by an ingestion benchmark.

The format reader owns metadata, batch buffers and their reservations. The
caller separately retains output-record capacity until consumed/transferred.
Any denial or malformed input aborts that reader; restarting an admitted
physical plan reopens the immutable artifact. Preserve the CSV-only compiled
path and measure its complete-job control after extraction.

## Explicit artifact ownership and validation

Start with explicitly owned experiment artifacts, without an automatic global
cache or a new default UI choice. A completed artifact consists of a versioned
manifest and one data file. The manifest binds raw source content hash, complete
CSV settings, format/version, source header convention, record/column counts,
existing logical digest and artifact content hash. Hash bytes rather than
trusting size/mtime. A replay validates the source and artifact before consuming
the cached records; include those scans in repeated-job time and traffic.
This validates the source bytes observed during the check, not an atomic lease
against subsequent external mutation.

Build in a fresh owned staging directory. Count conversion data, manifest,
staging overlap and any retained old artifact against a separate explicit disk
ceiling. Publish only after strict parsing, digest/count verification, writer
finish and artifact hash succeed. Failed conversion/replay must release its
memory/files and publish no job results. Never delete a caller's source or
unrelated cache directory. Do not enable reuse from an incomplete manifest.

Use the strict Chopper parser to produce snapshots, not inferred Python/Arrow
types. IPC storage names are positional `c0`, `c1`, …; preserve the original
header as the first record when present. This preserves duplicate/empty header
strings without requiring duplicate physical schema names. All values are
non-null UTF-8, including empty strings, literal null-like tokens, leading
zeros, dates, Unicode, NUL and embedded newlines. Preserve batch/file order.
Header-only and empty inputs need explicit controls.

Bound metadata before decoding it. Compact blocks need checked lengths/counts,
byte-bounded blocks and rejection before allocation. IPC initially permits only
uncompressed, dictionary-free text produced by this experiment; preflight footer
and message/body bounds before readers allocate metadata or batches. Reserve
old/new overlap, descriptors and decoded offsets/data, not just an Arrow batch
row count. Replayed record limits may conservatively reject an artifact made
under a larger input working limit; document that policy rather than silently
relaxing the current job ceiling. CSV output byte caps remain identical.

For existing Parquet, keep a separately identified flat, required-string scope.
Use actual schema names for its synthetic CSV header and preserve row-group/
row order. Reject nulls and unsupported typed/nested columns; do not invent
original CSV spellings. Preflight footer, column/page sizes, dictionary and
decoded working memory. A fixed batch row count alone is insufficient. The
initial interoperability experiment must distinguish supported external text
datasets from Chopper-created source-bound snapshots.

## Measurement and acceptance

Compare direct CSV, compact blocks and IPC with the same complete operations,
fields, logical IDs/digest and output settings. Report first jobs including
conversion, validation and publication; then independently source-validated
replays. Compare existing text Parquet against its declared text-equivalent CSV
without charging a fictitious CSV-to-Parquet conversion to an existing dataset.
Keep timing runs separate from allocation/storage censuses and alternate order.

Cover narrow/many-column/quoted/rare-wide records, resident/external pipelines,
partition/full-shuffle/downstream output, strict caps and changed-source/corrupt/
truncated/oversized/denied/cancelled artifacts. Verify exact bytes/order/metadata
for unchanged seeded algorithms. Record whole-job CPU/time/ranges, native
allocations/RSS, reservations, source/artifact/temp/output traffic and retained/
staged disk peaks. WSL eviction requests do not establish cold physical SSDs.

Compile and run a tiny direct-reader job with the actual WASI bridge before
claiming browser compatibility. Browser probes may mount explicit source and
artifact files; a working probe does not imply that the shipped picker/import
flow supports reusable caches. Keep unsupported deployment paths explicit and
all support/cache defaults unchanged until complete-job evidence warrants them.
