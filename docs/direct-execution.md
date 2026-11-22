# Direct execution slice

This records the implementation decisions for TODO's first execution slice. The
later [opt-in controls](validation.md#reproducibility-and-opt-in-automatic-memory-2026-10-28)
add reproducibility and automatic memory sizing without enabling Auto strategy
selection or changing omitted-mode defaults.
Validation and delivered eligibility are recorded in [validation.md](validation.md).

## Reconcile the policy and execution designs

The [Auto brief](auto-mode-and-maintainability.md) authorizes configure → Run
without mandatory exact preparation. The existing
[stage/parent design](adaptive-execution.md#evidence-based-stage-and-parent-policy-design-2026-10-20)
remains the proposal for choosing physical implementations of operation spans.
The [Auto policy reconciliation](adaptive-execution.md#auto-policy-reconciliation-2026-10-28)
defines selection precedence, optional-observation costs and conservative fallback
using surviving strategies; it does not enable cost selection.
These are separate choices: this slice changes how output is produced and
published, while retaining pipeline semantics and output/publication contracts.

The shared engine owns Run dispatch. A limits-only job or a single uncompressed Balanced operation can serialize
records directly to private publication output. Balanced still retains its input
Dataset to establish exact quotas; it avoids the additional encoded output snapshot. An unsupported job selects existing
exact preparation and execution before consuming input. Internal preparation retains an immutable encoded output snapshot until publication.
Analyze is optional, produces only input statistics and estimates, and does not
validate a later execution snapshot.
The former alternate flexible-policy runner and its build features are removed.
There is no Job policy selector.

The opt-in `experimental-terminal-shuffle` build also permits exactly a root
Uniform/Auto shuffle followed by Balanced, with uncompressed output. Its existing
external or resident random-key sort streams the same rows into grouped private
publication; explicit internal preparation still retains a snapshot. This is a
performance experiment, not a default selector or a new randomization algorithm.
Qualify its hosted graph using a build with
`--features chopper/experimental-terminal-shuffle` and
`node scripts/test-browser-graph.mjs --terminal-direct`. The default graph check
continues to require snapshot materialization for this pipeline.

On native builds, the same terminal-shuffle experiment additionally permits an
unobserved standalone Uniform, Auto or resident-only Fisher–Yates operation, or
root Uniform/Auto followed by Partition, with plain output. The existing sort,
permutation, grouping and final traversal are retained. These additional cases
use the snapshot path for physical/snapshot observations and WASI; the existing
Uniform/Auto–Balanced eligibility above is unchanged.

The Linux opt-in `experimental-short-terminal-uniform-merge` applies to
unobserved terminal Uniform sorts using raw spill files. The sorter admits a
pending catalog before transferring runs into it. The existing quarter-memory
formula controls how many input readers can open, with a ceiling of 512 and
a soft Unix descriptor limit of at least 4096. Once the complete run count is known,
the sorter materializes only the number of inputs needed to fit the final merge.
If the catalog cannot be admitted, the active reader limit falls to 256 or
below, temporary space usage exceeds half its budget, or pending ownership
would reach 1024 files, it switches to the existing hierarchy. This transition
moves the existing run owners and preserves their grants, cleanup, order and
publication behavior. [Benchmark and contract evidence](performance/investigations/terminal-uniform-short-tail-2026-11-21.md)

The native-only `experimental-terminal-routing` build permits a single
Partition, Interleaved, stratified exact assignment or probabilistic assignment
operation with plain
output. The existing partition tuple sort, quota assignment or count-independent router
and bounded sorting/spill fallback preserve membership and encounter order. Its final traversal writes
grouped private output without an encoded snapshot/copy. Named empty groups,
original lineage, caps and explicit internal preparation keep their contracts.
WASI does not select this experiment. Unstratified exact assignment retains the
snapshot path after a measured complete-job regression.

The native-only `experimental-final-writers` build permits a single plain
Interleaved or probabilistic assignment with at most 16 configured groups and
`grouping: auto`, when physical/snapshot observation is absent. It uses the
original count-independent membership draws, but serializes each arriving row
into that group's existing chunk writer. Each writer owns its admitted header,
catalog and private publication state; active sink buffers are
admitted when opened. A charged vector bounds the configured writer set.
The global file ceiling applies as chunks open, including named empty outputs.
After input validation, finished files move between private sibling directories
into canonical group/chunk order. The first group keeps its original destination
witness and becomes the final publication owner; CSV payload is not copied. The final directory
commit remains atomic. Larger fanouts, explicit Sort, composed jobs, compression,
explicit internal preparation, observed execution and WASI use existing paths.
There is no fallback after emission. This remains an opt-in experiment.

The native-only `experimental-memory-final-writers` experiment depends on the
shared serializer and raises the configured group/leaf ceiling to
`min(4096, memory_mb * 4)`: one writer per 256 KiB of nominal configured memory.
Before automatic memory resolution, `memory_mb: auto` conservatively uses the
minimum valid 32 MiB budget for this eligibility check. On Unix, the ceiling also
reserves 64 descriptors from the soft `RLIMIT_NOFILE` limit and allows two per
writer (catalog and active CSV); failed limit discovery retains at most 16.
This is a selection bound, not a memory or descriptor reservation. Wide headers,
concurrent jobs and unrelated open handles can still cause terminal admission or
open failures. The original owners and cleanup remain in force. Fanouts above
the ceiling select the existing pipeline before CSV consumption. No public Job
field, automatic budget resolution, default or WASI eligibility changes.

The separate `experimental-small-final-buffers` control changes only configured
fanout's plain file buffers from 64 to 16 KiB. It uses eight writers per nominal
MiB, capped at 8,192, with the same Unix descriptor guard and conservative 32 MiB
automatic-budget substitution. The 8 KiB catalogs, prefixes and metadata still
need independent admission. Ordinary direct, snapshot and codec buffers retain
their sizes. Fixed-count comparisons isolate its buffer effect; comparisons
above 4,096 writers also change path selection and must be labeled accordingly.

The separate native `experimental-small-final-catalogs` control changes only
bounded fanout's per-writer metadata catalog buffers from 8 KiB to 512 bytes.
The selected capacity is admitted before construction. CSV sink buffers, writer
selection, chunk boundaries, metadata decoding and all other publication catalogs
retain their existing behavior. Larger metadata records stream through the buffer;
512 bytes is not a metadata size limit. This resource experiment remains opt-in.

The native `experimental-single-final-catalog` control omits the private disk
catalog for a bounded fanout group proved to need one chunk: the group is exact,
or all row/byte/compressed-byte chunk limits are absent. Close retains one typed
record by moving the admitted relative filename and copying numeric fields;
lineage remains in the admitted Group. At source merge, a counting serializer preserves the old metadata line length
limit, excluding its newline; root materialization keeps the original streamed
non-decoding path. Multiple-chunk groups and
other publication constructors retain disk catalogs. This control changes no
writer ceiling or descriptor selection guard.

Canonical merge uses the same naming and rename helpers. If a group becomes the
root publication, its record is materialized into one ordinary catalog in its
original private stage after its CSV sink closes; its original destination witness
is retained. Publication requires that disk catalog. Materialization, metadata,
cancellation and emission errors remain terminal with private cleanup. There is
no new shared directory abstraction or Analyze dependency.

The independent native `experimental-single-catalog-capacity` control requires
the single-record catalog and small CSV-buffer experiments. Only jobs without
any row/byte/compressed-byte chunk cap use `min(16384, memory_mb * 16)` and a
one-descriptor-per-writer Unix guard after leaving 64 handles. Unresolved Auto
still substitutes 32 MiB. Capped jobs keep their previous ceiling and conservative
two-descriptor guard, even when an exact Group permits a typed catalog. This
selection bound grants no memory or handles; all owners still admit capacity.
Above-ceiling, codec, observed and WASI jobs retain their existing path. It remains
an opt-in experiment and never uses Analyze output as an execution certificate.

The Linux-only `experimental-batched-final-sync` control applies to unobserved
plain one-chunk writers using typed catalogs. It flushes each buffer into its
original File, releases buffer capacity, and transfers that handle into an admitted
root queue during canonical merge. After every writer has flushed, it synchronizes
all queued files before returning final counts for Analysis. Publication repeats an
empty guard before manifest construction/sync and original atomic commit. No file
is reopened or cloned and no required synchronization is omitted. Descriptor count
stays bounded by writer count plus publication/runtime headroom; handles live longer.
Sync, cancellation, admission and metadata errors remain terminal with private
cleanup. Other platforms, observed execution, codecs and multi-chunk catalogs keep
their original scheduling. This control is opt-in.

The native-only `experimental-bounded-final-partition` control permits one
unobserved plain Partition with Auto grouping when the configured `max_files`
ceiling is no larger than that writer capacity. Every successful output group
requires a physical file, so this existing job limit also bounds distinct groups;
an estimate is not used as a correctness bound. A charged exact escaped-tuple
map assigns rows to private final writers in encounter order. At EOF, its original
tuple sort order supplies canonical group/chunk names. A separate seed publication
retains the original destination witness and also handles zero-output jobs.
Keys/nodes, resolved columns, writer slots, lineage and sink buffers are admitted
before construction. Exceeding the file ceiling or admission ends the attempt
and cleans private output. Byte/row caps can require more files than groups.
There is no post-emission fallback or input replay. Larger configured ceilings,
explicit Sort, compression, composed jobs, observations and WASI retain existing
paths. The default file ceiling and all default features remain unchanged.

Native final-writer experiment builds add optional `writer_estimate` information
to Analyze. Existing input key statistics and configured group multipliers supply
logical group estimates, labeled exact only if the pipeline is feasible. Strata
do not multiply named allocation outputs. Unsupported conditional-parent or
multiple-partition combinations remain unknown instead of multiplying correlated
marginal cardinalities. Capacity and file-ceiling comparisons are advisory;
neither certifies full allocation, physical chunk counts, stable input or execution.
The advice is recomputed for the submitted job after cache reuse, requires no
additional scan, and creates no prepared result or approval token. Run receives
no previous Analysis and validates its current input independently.

The native `experimental-retained-exact-writers` control applies only to a
singleton stratified exact assignment with plain UTF-8 output, Auto grouping,
no physical observer and a configured allocation count within the existing writer
ceiling. It retains ingestion's immutable Dataset. Before emitting any allocation
rows it counts exact tuple keys from that parent, admits the original largest-
remainder quota vector and RNG state for each stratum, and prepares bounded final
writers in configured name order. A second retained traversal advances each
stratum's original draw stream while preserving global encounter order inside
each allocation. It removes the strata and allocation-row sorting passes.

The original empty PlanWriter captures its destination witness before tentative
preparation. Count/catalog/quota/writer setup uses the existing retained-parent
Proposal seam; typed memory denial drops tentative owners and falls back from
the same Dataset with that same original writer. Parent-reader setup denial is
handled before a parent proposal can be created. Cancellation and cleanup faults
override both forms of denial. All errors after emission begins are terminal.
The prepared path consumes the still-empty writer's publication as its canonical
seed, keeps named zero outputs and existing caps, and commits stage statistics
once. It never reopens the source CSV or trusts an earlier Analysis. Internal
snapshot preparation, observed/WASI, composed, unstratified and other-output modes
retain their prior execution. This remains an opt-in experiment.

The `experimental-shared-final-serializer` control shares one admitted encoded
row scratch across those writers, retaining the same prefix and cap decisions.
Per-file buffers and encoded prefixes remain separate; fanout/header metadata
can therefore require more working capacity than a sequential traversal. All
admission failures are terminal and clean private output.

The separate `experimental-release-final-header-scratch` control drops each
fanout writer's unused header-serialization text/encoding buffers after retaining
the serialized prefix. Shared fanout uses its central serializer for every data
row. The old buffers drop before their grant shrinks; prefixes, per-file buffers
and cap decisions remain owned. Other PlanWriter constructors retain their
normal reusable scratch. This is a resource-lifetime experiment, not a shared
header representation or default change.

The native-only `experimental-final-writer-chains` experiment enables two through
four Interleaved/probabilistic operations whose configured leaf product is at
most 16, with the same plain/unobserved/Auto restrictions. It depends on the
shared serializer. An admitted bounded tree retains each original parent's
lineage domain and encounter counter, with original input row IDs. It validates
every Interleaved parent and records every logical stage before finalization.
Zero-sized named probabilistic outputs remain present; an Interleaved child of
an empty parent still fails. Unsupported depth, product or operations select the
existing pipeline before CSV consumption. Explicit preparation and WASI retain
their existing paths. This is not a shuffle or probability algorithm change.

The native CLI experiment `experimental-counted-balanced` selects a strict
compact CSV count pass followed by direct Balanced serialization for a single
uncompressed Balanced job with a plain UTF-8 input. A bounded container
signature peek selects this path before CSV consumption. Both passes validate
CSV and UTF-8. Before publication, Run checks the decoded header, row count,
source byte length and modification time. An edit between passes can go
undetected if it preserves all four. Analysis and the published manifest
report the logical digest of the rows emitted by the second pass.

The two passes need no retained Dataset. The first-pass header drops after
comparison, before final metadata and publication. The returned Analysis
owns its independently admitted immutable header. Explicit preparation and
physical-observation dispatch retain their original paths; WASI does not select
this experiment. Failure in either pass is terminal and private outputs are
discarded. It remains opt-in pending complete-job and contract evidence.

The separate native `experimental-counted-codec-balanced` control extends the
same source checks and exact Balanced traversal to gzip
and ZIP outputs through the existing grouped direct publication adapter. Output
codec versions, ownership, checksums, strict uncompressed serialized caps and
advisory compressed targets remain unchanged.

The native `experimental-counted-partition-balanced` experiment handles a
plain UTF-8 source and plain output with exactly Partition followed by Balanced.
Auto grouping and a configured file ceiling within the existing writer limit
are required before input consumption. The first pass admits exact tuple keys
and counts, with parent count bounded by the file ceiling divided by the number
of Balanced parts. The second pass routes source-order rows into each parent's
consecutive quota ranges. Publication walks the tuple keys in canonical order
and the parts in numeric order. This composed path also compares the first-
and second-pass logical digests, along with its per-key quota, writer
admission and cleanup checks.

There is no admission-error replay of raw input after direct execution begins.
Parsing, decoding, reservation, output, cancellation and finalization errors end
that attempt. A retained-parent rewrite's pre-emission retry is a different seam;
it does not authorize retrying partially published direct output.

## Shared implementation responsibilities

Encoded chunk construction owns serialization, BOM/header bytes, strict byte and
row caps, the advisory compressed target and file-count limits. Snapshot and
direct publication adapters consume the same chunk decisions. Neither adapter
may reinterpret a byte cap using decoded field lengths or compressed bytes.

Publication owns admitted output names, codecs, staging, manifest records and
final commit. Direct execution does not know exact output counts at launch.
Its canonical job manifest record is assembled after successful input validation,
before final commit; bounded disk-backed output metadata may precede that step.
This avoids retaining all output CSV bytes merely to put the job record first.

The parser, header, preview, selected-column summaries, digest, final Analysis
payloads and immutable prepared configuration retain their existing admission
owners. [CSV intake](../crates/chopper/src/csv_intake.rs) now keeps the decoder,
buffered source, parser and reusable owned/compact records together with their
grants. Direct Run keeps owned strings and its existing observation checkpoints;
prepared ingestion keeps compact retention and sorter/chain admission relief.
Header payload admission still overlaps the parser charge before transfer to
the immutable Analysis header. Profiling and first-record inspection use the
same intake with their existing accounting and scan scopes; neither acquires
execution or publication policy from it. Serialized output and codec allocations retain grants through writer
finalization and destruction. No direct path may bypass shared process admission.
Memory accounting remains a working-allocation budget rather than an RSS cap.

Windows uses admitted verbatim UTF-16 paths and `MoveFileExW` without replacement
or copy flags; a competing empty destination is rejected as on Linux. Native
output remains private on the destination filesystem until complete
validation, finalization and the existing no-replacement directory commit.
Browser CSV and gzip publication writes final result files to the
selected destination through the storage worker. ZIP retains staged export
because finalization reads the manifest. Both paths close every result stream
before committing and verifying `CHOPPER-COMPLETE.json`. The browser attempts
cleanup of job-owned incomplete destination folders after direct Run failure or
cancellation and after staged export failure. A confirmed invalid marker triggers
this cleanup. A closed marker with an unreadable readback remains in place for
inspection. If cancellation leaves a destination, the browser reports its path.
An outstanding speculative source read does not delay storage cleanup.
For plain output from a `.csv` selection with an empty pipeline or one
Partition, the hosted bridge keeps one bounded source read outstanding.
An empty pipeline also permits one pending batched destination write. The
bridge drains the write before every destination control operation. The
storage worker flushes buffered data before closing a stream or publishing
the marker. Failure or cancellation discards any uncommitted write buffer.

For a Linux or Windows Run that reaches snapshot publication for one plain Partition,
2 GiB or more of validated serialized output and at least 1,152 files qualify for
up to four publication workers when the resolved worker count is at least four.
Each batch uses current workspace and shared memory headroom, the descriptor
ceiling and the remaining file count. Writers still admit their own allocations.
The ordered publisher writes the manifest and commits the destination after
all tasks succeed.


### Compression selection

Parallel compression processes bounded 256 KiB DEFLATE blocks. Independent
blocks start with empty dictionaries and are written in order in one gzip stream
or one ZIP member. CRCs and stored sizes describe the finished result.

Direct Run uses the current source size and serialized byte cap. A source and cap
of at least 2 MiB can use parallel compression. For sources at least 64 MiB,
byte caps of at least 512 KiB can also use multiple blocks. An explicit row cap
keeps limits-only compression serial. Native Run uses up to four codec tasks
from the resolved worker pool. Native prepared publication can instead use
multiple existing writers and can parallelize blocks when one writer is active.

Hosted Run coordinates from one WASI engine worker. With automatic workers it
can start up to four codec Web Workers. A prepared batch can compress separate
files when the planned average is at least 256 KiB and each file in the batch is
below 2 MiB. Larger files may use several workers within a file. Compression
buffer admission or unavailable Web Workers can reduce parallelism. An explicit
single worker uses serial compression.

Direct ZIP writes each member into its private archive and fills its ZIP64 local
header once the CRC and sizes are known. Ordered prepared publication may
retain up to 512 KiB of compressed bytes for an eligible member up to 2 MiB of
CSV. The writer can use a temporary file when memory admission is denied or a
member outgrows its buffer. Native atomic commit and browser completion-marker
rules still apply to the completed archive.

### Native Auto paths

Unobserved native Run can use bounded Partition, a two-step Interleaved and
probabilistic assignment chain, counted Balanced, counted Partition followed
by Balanced, and retained stratified exact writers. Auto requires plain UTF-8
output, Auto grouping, about 256 MiB of nominal memory and at least 96 MiB of
live working headroom. Bounded Partition starts at 307,200,000 source bytes
with a declared 128 KiB record ceiling and at most 32 files on Linux or 16
on Windows. Counted Partition and composed writers start at 2 GiB with the
same declared record ceiling and a hard writer bound. Known writer leaves
are capped at 16. Large singleton Interleaved and probabilistic assignment
use their configured fanout. Linux Interleaved with sixteen plain UTF-16LE
outputs may share one row serializer from 1.5 GiB of input and a declared
1 MiB record ceiling. Counted Partition uses the declared file limit up to 64
and actual descriptor capacity. Counted singleton Balanced starts at 2 GiB.
Gzip and ZIP inputs use the ordinary single-decode path.

Large uncapped plain Interleaved jobs on Linux can batch syncs for 8,192 to
16,384 known outputs. The path requires at least 2 GiB of input, a declared
4 KiB record ceiling, room for the live descriptors and 512 MiB of working
headroom. With automatic memory it targets 1,024 MiB. A smaller explicit
memory setting uses the ordinary path. Native batching keeps each
original file handle,
flushes all files and syncs every handle before publishing.

Linux can widen a terminal Uniform merge for plain Shuffle followed by
Balanced on inputs of at least 8 GiB with one resolved worker and descriptor
headroom. The nominal 256 MiB tier allows up to 256 readers. The nominal
96 MiB tier can retain a bounded short tail of runs and admits up to 512
readers within the actual memory calculation. Low descriptors or tight live
reader admission retain the ordinary hierarchy.

Linux exact assignment can use an in-place quota index for a single
unstratified operation with 1,000 destinations, at least 4,200,000 validated
scope rows and at least 500 estimated linear tests per draw. The cost is
computed from the rounded quota vector and uses no Analyze scan. The indexed
cursor selects the same position for each draw. Retained exact writers have
a separate typed-memory fallback at their existing preparation boundary.

All auto-selected direct writers keep the existing incremental admission,
file limits, serialization and atomic publication checks. Auto can decline a
direct plan before opening any output when its actual workspace no longer
meets the starting bound. Analyze can recommend a tighter file ceiling for
an uncapped singleton Partition when it has an exact count and the other
configuration bounds fit. The user decides whether to change that limit.

## Interface and acceptance

`engine::run` and `run_with_memory_pool` provide Run to the CLI and WASI adapter.
The CLI and WASI `chopper_run` accept the current configuration. CLI `analyze`
and WASI `chopper_analyze` return bounded full-file input statistics and pipeline
estimates without building outputs. The hosted UI exposes Analyze and Run; Run
always submits the current configuration. No browser prepared handle or approval
request remains. `prepare`/`Prepared::execute` are internal engine/test seams,
including the exact snapshot fallback for unsupported Run pipelines. Source selection/import loads a bounded
sample independently of these processing actions.

CLI confirmation happens before direct input consumption and describes the
configured paths, without claiming exact counts. `--yes` skips the prompt but
never validation. Direct errors can arrive after processing starts. Final output
counts, byte totals and digest describe the successfully consumed input.

Acceptance compares direct and prepared fields, order, filenames, lineage,
digests, encoded caps and manifest output records. It also covers late-wide and
malformed input, header/BOM edge cases, local/shared admission denial, output and
codec failure, source changes, cancellation, destination races, native cleanup
and browser export/marker behavior. Source metadata checks retain their existing
limits; they cannot prove detection of same-size edits with preserved timestamps.

The seeded-output policy, reproducible option and user seed input have been removed.
A new execution generates internal entropy; internal snapshot publication keeps its bytes. Automatic
memory sizing remains available. Adjacent shuffle/partition fusion is enabled
by default; broader cost-based Auto selection remains separate work. The
[E4 study](performance.md#e4-explicit-probabilistic-allocation-advice-2026-10-28)
retains explicit approximation and withholds generic speed recommendations. These
slices do not select numerical performance thresholds.

The first slice's [executed acceptance and limits](validation.md#limits-only-direct-run-2026-10-27)
cover Windows native execution and bundled Chromium. Other platform/device and
deployment claims retain their previous evidence scopes.

## Terminal pipeline output

A single uncompressed Balanced operation can use grouped direct publication.
The [native Auto paths](#native-auto-paths) and opt-in paths above cover
additional terminal shapes. These paths share chunk construction and
header-aware naming, and carry admitted private publication through final
Analysis creation. Errors after emission remain terminal. Other terminal
pipelines use the snapshot path. The studies below describe earlier prototypes.

The [current implementation and measurements](performance/investigations/csv-data-movement-and-analyze-run-2026-11-18.md)
record source identities, runtime coverage and the remaining eligibility limits.

## Earlier terminal-output investigations

The [source/payload audit](performance.md#direct-final-output-cost-audit-2026-11-03)
identifies a proposed Run-only extension; it is not current eligibility. Terminal
stages already send rows to PlanWriter, avoiding a final row Dataset. Replacing its
encoded Snapshot target with private direct publication could remove the snapshot
payload write/copy without removing serialization, final output or browser export.

A grouped extension needs admitted header-aware naming and original lineage/exact
flags, a Run result carrying final counts/publication through Analysis construction,
and terminal error cleanup for chunk, codec and manifest admission. Removing the
existing direct adapter's empty-lineage guard alone is insufficient. Explicit
Prepare and flexible snapshot replay remain outside this proposed extension.
Prepared Analysis diagnostics precede publication, so future complete-job traffic
verification must observe beyond those returned counters. No implementation,
selector, default or new runtime coverage is established by this audit.

The later [isolated native prototype](performance.md#isolated-terminal-direct-run-native-comparison-2026-11-03)
implements that seam for seeded, plain, explicit-one-worker partition followed by
probabilistic assignment. It is retained as an unapplied patch; production Run
eligibility remains unchanged. Exact native output and cleanup controls pass,
while the [later Chrome/working-set study](performance.md#terminal-direct-output-chrome-and-working-set-transfer-2026-11-03)
checks exact export/marker/cleanup behavior in the recorded cases. Broader
pipeline/codec acceptance and shared-pressure feasibility remain separate work.

The [terminal storage controls](performance.md#terminal-direct-output-storage-lifetimes-and-temp-budget-control-2026-11-03)
record earlier private-output overlap and a narrow temporary-budget completion
benefit in the unapplied prototype. Its charged intermediate budget excludes
normal private output; these controls do not establish lower total filesystem
space or general admission-domain inclusion.

## Typed publication boundary

Engine publication produces an opaque `EnginePublication` only after committing
the destination. Internal Run/confirmation paths attach it to the admitted
Analysis; native job lifecycle completion consumes that published result. The
public engine Analysis facade remains unchanged. Browser engine publication is
still private staging: destination completion additionally requires its separate
exact-readback marker receipt. Native HTTP schema references in older acceptance
records describe the retired server. See the
[result/publication contract](browser.md#result-ownership-and-publication-contracts).
