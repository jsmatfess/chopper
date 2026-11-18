# Chopper v1 behavior specification

Status: behavior contract and original design baseline, with explicit later extensions. See the [README](../README.md) for implemented controls, [validation](validation.md) for tested scope and [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for remaining work. Full-file input profiling (including HLL estimates), hosted browser execution and direct Run are implemented. Exact output preparation remains an explicit workflow; unsupported direct jobs use it internally. Sections explicitly marked proposed retain design language and do not by themselves establish delivery or test coverage.

## Scope

- Native CLI for technical users on supported 64-bit Windows and Linux; a separate hosted browser UI uses the same engine and job configuration. macOS source builds are unqualified. No local server or native UI is part of current product scope.
- Local files, including ZIP, gzip, and Zstandard inputs and outputs.
- All six operations in v1: balanced file counts, maximum rows, maximum bytes, unique-value partitions, shuffling, and percentage-based treatment/control allocation.
- Typical inputs: tens of thousands to millions of rows. Scale target: one billion rows, potentially several KB per row, with bounded working memory and sufficient external storage.
- Analysis and confirmation, progress, cancellation and cleanup, safe publication, and output manifests.
- Fully client-side hosted UI is implemented; see [browser execution and limits](browser.md). Resumable jobs remain deferred. GPU acceleration has been assessed and deferred; there is no GPU dependency.

## Data and order

Every input data record has a stable ordinal; headers are not data records. Counts and offsets use checked 64-bit or wider arithmetic, never platform-sized row counters.

Without an explicit shuffle, preserve the relative input order within every output. After a shuffle, later operations preserve the sequence established by that shuffle. Assignment randomizes membership independently of row ordering. No operation drops or duplicates data records.

Partition equality compares decoded field text exactly: case, whitespace, leading zeros, and Unicode normalization differences remain significant. Empty text is a value; there is no inferred null or numeric type. Tuple keys use unambiguous field boundaries, never delimiter concatenation. Hash collisions must not merge distinct values.

## Ordered pipeline

Start with one logical group. Each operation applies independently to every group from the preceding operation. Child groups remain separate for the rest of the pipeline. Reordering steps is meaningful and user controlled.

For example, balanced split into 10 followed by country partitioning partitions each of the 10 chunks separately. Country partitioning followed by balanced split into 10 produces 10 balanced children per country, and fails if any country has fewer than 10 rows.

Logical groups are distinct from final physical CSV chunks. Row and byte limits can be final constraints. The UI exposes this distinction and warns about potentially conflicting settings before analysis.

### Balanced split into X

- X is a positive integer. For N rows, produce X consecutive groups with sizes differing by at most one.
- Proposed deterministic rule: the first N mod X groups receive floor(N/X)+1 rows; the others receive floor(N/X).
- Reject N < X, including empty input when X is positive.
- An exact physical file count is never silently exceeded to satisfy a cap. For a terminal balanced split, validate the specified balanced chunks against final caps; fail if they do not fit. Do not change the balance or ordering to make them fit.
- When later partitioning or assignment steps exist, X describes that intermediate step, not a global final file count. Preview explains the resulting scope.

### Interleaved split into X

The explicit `interleaved` operation is an alternative to `balanced`: for each
parent, row i (zero-based encounter position) goes to part `i mod X`. Parts are
emitted in numeric order, preserving the input subsequence within each part.
Nonempty, balance, hard-cap and intermediate-scope rules remain those above.
Concatenating parts does not restore input order. Existing `balanced` jobs remain
consecutive ranges.

### Final chunk limits

- A row limit counts data records only. A strict byte limit counts serialized output CSV bytes in the configured output encoding, including BOM if enabled, headers, quotes, escapes, and line endings.
- With both limits, close a chunk before adding a row that would exceed either limit. Never split a CSV record.
- Fail if a single row plus the required header/BOM cannot fit the strict byte limit. An overlarge header also fails.
- Distinguish decimal units (KB, MB, GB) from binary units (KiB, MiB, GiB).
- Compressed-byte targets are explicitly advisory. Use a cheap conservative estimate and report that the target may be exceeded. An estimate is not a hard resource bound.
- Conflicts known from configuration fail immediately; data-dependent conflicts fail when established by analysis or execution. Nothing is published after a failed job.

### Partition by column values

- Select one or more columns by index or unambiguous header name.
- Produce one logical child per distinct tuple within each parent group.
- Report cardinality, skew where available, and expected physical output count during analysis.
- Proposed canonical group order: lexicographic order of decoded UTF-8 field tuples, comparing fields individually. Storage traversal and randomized hash-table order do not define user-visible order.
- Filenames use safe deterministic identifiers, with full partition values in the manifest. Values never become unchecked filesystem paths.

### Treatment/control allocation

- Any number of uniquely named groups with nonnegative decimal percentages summing exactly to 100. Parse percentages as exact decimals, not binary floating point.
- Exact per-group counts use largest-remainder rounding: floor each ideal count, then distribute remaining rows by descending fractional remainder; ties follow configured group order.
- Randomized assignment is uniform over assignments with those fixed counts under the algorithm's random-source model. Assignment does not reorder records.
- Optional stratification applies these counts independently per stratum within each current parent group. Strata do not create additional output groups unless the user also explicitly partitions by them. Overall group percentages can differ slightly from global rounding because of per-stratum rounding.
- Entity-coherent assignment is deferred as recommended and accepted in discussion.
- Proposed empty-group behavior: retain named groups with zero allocations as header-only outputs (empty files if headers disabled); warn in preview. A later balanced split on an empty group fails.

### Probabilistic allocation

The explicit `assign_probabilistic` operation retains named groups and optional
stratum columns but replaces exact quotas with independent categorical draws.
Percentages still parse exactly and sum to 100; zero weights never receive rows.
Empty named outputs remain present. No per-stratum nonempty or exact-count
guarantee applies. Actual prepared counts and bytes are still reported exactly.
Membership uses the parent/step seed domain separated by
`probabilistic-allocation-v1`, then a keyed hash of the original source row ID
(u64 little-endian) and each selected stratum field's u64 little-endian byte
length and UTF-8 bytes in configured column order. This seeds the existing
rejection-sampled RNG for a draw below 100,000,000, mapped through cumulative
percentage weights in configured group order. No growing per-stratum RNG map is
required. Encounter order is preserved within each allocation.

### Shuffling and seeds

Partition-first and dormant Parquet wiring were removed on 2026-10-24.
`experimental-flexible-partition` and `experimental-parquet-input` are invalid
native/browser Cargo features, including through browser build wrappers. Neither
provided a dedicated public runtime selector or Parquet decoder. The alternate
flexible runner and allocation-range feature are also removed. Automatic/uniform
shuffle followed by column partitioning uses the fused path; counter-v1 remains. Direct compact/Arrow IPC snapshot APIs
and `experimental-input-snapshots` were separately rejected and removed after E3
review on 2026-10-26. Use direct CSV input; the old Rust module no longer compiles
and native/browser builds naming the removed feature fail explicitly.
Historical Python Parquet/CSV adapter research does not describe Rust input support.

Radix sorting and prefix distribution are removed physical experiments. Their
former Cargo features are invalid in both native and browser packages; neither
introduced a public Job option or seeded algorithm version. Unknown shuffle
strategies and full-shuffle algorithm values fail strict decoding. Uniform
execution retains comparison sorting, collision refinement and external merge.

Supported strategies are `uniform`, `auto` and `fisher_yates`. The removed
`buffer` strategy and `buffer_rows` field are invalid, including when that field
accompanies a surviving strategy or an omitted strategy. Reject these requests
during strict decoding before input I/O; never substitute an algorithm.

- Uniform: full permutation, with external storage as necessary. Algorithmically uniform under ideal independent random bits; the implementation uses a documented seeded pseudorandom generator, not a claim that a finite seed can enumerate all possible permutations.
- Explicit `fisher_yates`: resident uniform shuffle, with the parent/step domain separated by `fisher-yates-v1`. Starting from encounter order, descend from index N-1 to 1 and swap with a rejection-sampled index in 0..=i using the existing RNG. This is a different seeded permutation from random-key v1. Retained rows must fit the resident workspace (one quarter of the job memory budget, including capacity accounting). Fail before publication if they do not; do not fall back to random-key sorting. There is no configurable seed or cross-plan replay promise.
- Automatic: choose a physical implementation of the requested guarantee; never downgrade uniform to approximate to fit resources.
- Randomized output has no cross-plan, cross-resource, cross-platform or cross-build seeded replay guarantee. User-configurable seeding is removed. Job JSON rejects `seed` (including null) and internal `random_seed`; the CLI rejects `--seed`. Execution obtains internal entropy under admission; internal test fixtures may pin randomness without adding a product option. Diagnostic entropy identifiers are not replay controls. The `full_shuffle_policy` field and `--reproducible` flag are removed and rejected. Imported JSON must omit the obsolete policy field.
- Prepared confirmation executes the exact retained encoded CSV snapshot. This snapshot guarantee is independent of whether another run would realize the same permutation.
- Automatic/uniform shuffle immediately followed by value partitioning may use a fused tuple/random-key sort. Distribution-equivalent changes are legal when they preserve the joint membership/order guarantees of the requested pipeline; positional splits, allocations and final caps remain semantic barriers requiring their own proof. There is no general permission to exchange arbitrary operations.
- The alternate flexible-policy runner and its feature gates are removed. Removed policy/RNG/algorithm names continue to fail strict decoding.
- Adjacent full shuffle followed by unstratified exact assignment may cut one parent permutation at the existing largest-remainder quotas. Preserve the joint membership and within-allocation order law, configured names/order including zero quotas, parent isolation, original logical stages and downstream semantics. Stratified assignment is excluded. The physical permutation is not a separately observable intermediate row trace; preparation still retains the exact final snapshot.
- An immediately following full shuffle may replace an earlier auto/uniform shuffle within the same parents. A final explicit Fisher–Yates still executes at its original index with resident-only admission; every earlier explicit Fisher–Yates also executes. Grouping, assignment and positional operations remain barriers. Logical stages survive and physical observations identify elided work.
- Assignment and shuffle use separate deterministic random domains. Parallel scheduling does not consume a shared mutable random stream.
- Guarantees concern logical results and configured CSV serialization. Compressed container bytes need not match across codec versions; manifests record versions.

## CSV and encoding

Input and output CSV settings are separate. A copy-input-settings action copies resolved input settings into output settings; subsequent output overrides remain possible. This copies the dialect/encoding, not original lexical formatting. Imported encoding labels absent from the editor’s preset list remain visible and selected through editing, export and submission. The engine resolves supported aliases and rejects unsupported labels; the editor never substitutes UTF-8 for an unmatched label.

Proposed defaults: UTF-8; header present; comma delimiter; double-quote quoting with doubled-quote escapes; input accepts LF and CRLF record endings; output uses LF and minimal required quoting; no output BOM. Input UTF-8 BOM is recognized as a signature. Quoted multiline fields are supported and preserve field content.

Expose encoding, header presence, delimiter, quote/escape policy, line ending, and BOM policy. Publish an explicit supported encoding list during implementation; reject unsupported names, invalid byte sequences, and unrepresentable output text rather than silently substituting characters. Include common UTF encodings and legacy Windows encodings in the compatibility evaluation.

Reject malformed quoting, unterminated quoted fields, unexpected text after a closing quote, and inconsistent field counts. Define validation against the selected dialect, not library permissiveness. Proposed blank-line policy: reject bare blank records by default, with an explicit skip-empty-lines setting. Quoted empty fields remain valid.

Duplicate header names are allowed but name selection must reject ambiguity and offer index selection. Headerless files use indices, infer expected width from the first record, and do not synthesize output headers by default. Empty input produces no data chunks unless named allocation groups require empty outputs; balanced splitting fails. Diagnostics include logical record/field and decoded-stream position where available.

## Compression and archives

- Input: one local source per job; ZIP selects one CSV member, auto-selecting only when there is one eligible member. Multiple eligible members require selection. No automatic concatenation of archive entries.
- Output gzip/Zstandard: one compressed stream/file per physical CSV chunk.
- Output ZIP: one archive containing all output CSV chunks plus the manifest. Physical CSV counts refer to members, not the outer archive count.
- ZIP row and strict uncompressed-byte caps apply to each CSV member. Advisory compressed targets apply to each member's compressed payload; they do not cap the total archive, which includes all members and container overhead. Show this scope prominently.
- Proposed ZIP v1 methods: Stored and Deflate input, Deflate output, ZIP64 support. Unsupported compression methods, encryption, and multi-volume archives produce actionable errors.
- Validate codec checksums/truncation errors. Read selected entries directly without extracting arbitrary archive paths. Budget archive metadata as well as payload buffering.

## Analysis and confirmation

Run validates input while processing. Limits-only jobs write directly
to private publication output; other jobs select exact preparation internally
before consuming input. Direct parsing, codec, admission, storage and cancellation
errors are terminal, without retrying raw input. CLI confirmation precedes
processing and does not promise exact counts; `--yes` skips confirmation, never
validation. Non-interactive execution without `--yes` fails rather than waiting.
Explicit exact preparation retains the immutable output snapshot for confirmation.
Both workflows preserve strict serialized caps and publication/cleanup contracts;
see [direct execution](direct-execution.md).

Original proposed analysis modes (not a list of implemented modes):

1. Auto: full streaming validation/counting, small exact cardinality sets that transition to sketches, and exact disk-backed counts only where operations require them.
2. Exact: full validation with external aggregation or pipeline simulation for exact statistics where possible. Compressed sizes and runtime remain estimates.
3. Quick preview: bounded sample for early configuration feedback. Explicitly incomplete; cannot certify validity, exact counts, or unseen rare values. Required validation still occurs before publication.

Current interfaces separate a full-file input profile from exact output preparation; see [implemented profiling and cache behavior](performance.md#full-file-input-profiling-2026-10-12). The UI also requests a bounded input sample on source selection, import and parser changes: at most eight data records are inspected, retaining at most eight rows and 32 KiB of field text with admitted field/container overhead. This sample does not validate unseen records or predict counts, cardinalities or output sizes. Full-file profiles and prepared analyses also report exact per-value input-row frequencies when a column’s bounded value list is complete (at most 100 values per column and 256 KiB of display values overall). Frequencies include empty fields, count during the existing input pass, and are discarded on truncation. These counts describe input values, not final pipeline groups; incomplete lists never imply a partial percentage distribution. A predictive resource planner remains future work.

HyperLogLog reduces cardinality tracking memory, not bytes read for a full-file scan. It cannot enumerate partition values or supply exact per-partition allocation counts. Estimates of cardinality alone cannot determine capped output counts because group sizes and row lengths matter. Do not extrapolate sampled unique counts as though they were full-stream HLL results.

Report source/member, resolved dialect, validation coverage, row counts, selected tuple cardinalities, available group-size distributions, largest observed record, output count/range, planned passes, memory allocation budget, estimated peak temporary/output storage, and compression caveats. Label every statistic exact, estimated, bounded, or unknown; sketches include error information without presenting it as a deterministic bound.

Warn about file-count explosion and offer a configurable execution ceiling. Estimates do not authorize unlimited fanout: enforce a hard ceiling during execution and abort cleanly if exceeded. Proposed default ceiling and resource defaults will be calibrated, then documented rather than silently changing during a job.

Input must remain consistent between analysis and execution. Record source identity/metadata and content digest during full scans; detect changes during execution before publication. Metadata alone is not sufficient proof. A retained canonical spool can provide a stable snapshot and avoid repeated decompression.

## Resources, publication, and interfaces

`resources.memory_mb` accepts an unsigned JSON integer in MiB or the exact string
`"auto"`; numeric strings, fractions and other scalar/container forms fail strict
decoding. Omission remains numeric 256. CLI `--memory-mb` accepts an unsigned
integer or `auto`. Optional `run`/`analyze` memory and worker flags override
imported values; absent flags retain imported values or the omitted defaults.
Explicit numeric budgets remain exact.

For `"auto"`, after the existing pressure refresh, let F be the effective shared
admission limit minus current usage (saturating at zero). The nominal MiB budget
is `min(256, floor(F / (MiB / 2)))`. This observation grants no capacity: actual
allocations still compete with concurrent owners. Resolve once before Context
job-directory/configuration admission; preserve the requested Job unchanged,
including `"auto"` in manifest configuration. Analysis reports effective numeric
`memory_budget_bytes` and `workers`. Executing a prepared result reuses its
Context rather than resolving again. These are working-allocation budgets, not
RSS caps; see [shared reservations](resource-policy-research.md#explicit-settings-and-shared-reservations).

Validate the resolved budget using the normal 32 to 1,048,576 MiB bounds,
`max_record_bytes <= nominal_memory_mb * MiB / 16`, and explicit workers at most
`min(64, nominal MiB / 8)`. Fail rather than round up the budget or shrink record
limits. `workers: 0` retains native selection
`min(available CPUs, 4, max(memory_mb / 64, 1))`; WASI uses one worker and accepts
only 0 or 1. Browser numeric budgets are bounded to 2048 MiB; automatic budgets
never exceed 256 MiB. Default record size remains 8 MiB, so a small automatic
budget can require an explicit lower record limit.

The hosted WASI instance has a fixed 1 GiB shared tracked-allocation ledger and
a 2 GiB linear-memory ceiling. Neither is discovered host RAM or a browser RSS
cap. Numeric requests remain algorithm budgets, with a half-budget workspace;
actual allocations must also satisfy shared admission. A larger manual request
does not preallocate that amount. Keep default and automatic budgets at 256 MiB.
The signed i32 pointer arguments in the current WASI JavaScript shim make 2 GiB
the boundary without bridge changes; see [browser limits](browser.md#processing-and-limits).

Native `experimental-plain-publication` builds may publish independent plain
prepared-output chunks concurrently using the already resolved workers. The
batch ceiling is `min(workers, max(memory_bytes / (16 MiB + 2 * max_record_bytes), 1))`,
further limited by remaining planned files. Each task independently admits its
owners; the ceiling is not a reservation or a promise of success under competing
pressure. Every file still flushes and syncs, workers join before ordered manifest
collection, and the complete private directory commits atomically. Default plain
publication, limits-only direct Run and WASI publication remain serial.

Omitted or null `resources.temp_bytes` imposes no temporary-space budget. Actual filesystem or browser quota exhaustion still fails the job with normal cleanup; no free-space snapshot becomes an automatic cap. An explicit positive temporary-space override remains enforced. Native Context creation checks it against available disk space; browser quota is enforced by OPFS writes. Output-count overrides remain available. Bound buffers, in-flight work, per-group state, file handles, sketches, archive directories, and manifests. Spill to disk rather than allow cardinality-dependent unbounded memory growth. Oversized records must be streamed/spilled or rejected clearly before exceeding the working allocation budget.

Show advisory storage estimates when available and monitor actual disk consumption. The hosted input picker gives an illustrative 2–8× uncompressed source-size range for sorting/grouping, not a prediction or upper bound; compressed sources warn that expansion is unknown. Free-space checks cannot guarantee future space. Fail cleanly on exhausted storage or codec/parser failure. Output staging and temp files may be on different devices and need separate space accounting.

Stage into a new job-owned directory on the output filesystem. Proposed publication unit: rename the completed result directory into a previously nonexistent destination; never claim multi-file atomic publication using independent file renames. Accept a user-selected empty destination folder by removing it non-recursively immediately before publication; refuse nonempty destinations and links. Recheck at publication and never silently overwrite inputs or existing outputs. ZIP is finalized before publication. Promise no partial successful result, not power-loss durability on every filesystem.

Cancellation removes job-owned staging and temp data where possible; report any cleanup failures and their paths. A future startup can identify abandoned job directories but must not delete unrelated files. Resume is deferred.

Use a streamed manifest format (proposed JSON Lines) so billions of partition entries are not collected into one in-memory object. Include schema/algorithm versions, effective configuration and internal diagnostic entropy identifier, source identity, counts, output paths or members, tuple/group lineage, sizes, and warnings.

Native commands include analyze, profile, run, split and guide. Ordered jobs can use versioned JSON or the [unified Run CLI](run-cli.md), whose explicit --step boundaries preserve requested operation order and reuse Job validation. The hosted web UI provides browser file/member selection, CSV configuration and preview, operation reordering, constraints and resource settings, analysis/confirmation, execution progress/cancellation, and output summary. Both interfaces consume the same resolved plan and structured progress/error events.

Progress remains `{phase: string, rows: number, temp_bytes: number}` in emission
order. Built-in literal phases require no heap allocation. Dynamic engine phases
retain an immutable admitted owner through producer, callback, cache and clones;
admission denial before publication returns a typed resource error without a
callback or cache replacement. Phase text is exact and never truncated or skipped.
Both postcommit Complete producers remain infallible and allocation-free; late
cancellation/admission pressure cannot turn committed publication into failure.
See [phase ownership](resource-policy-research.md#portable-progress-phase-ownership-2026-10-28).


The implemented [hosted version](browser.md) keeps source bytes, temporary data,
and computation in the client browser; hosting delivers application assets only.
Earlier loopback-server and HTTP response contracts describe the retired native
server and are historical, not current interface requirements.
