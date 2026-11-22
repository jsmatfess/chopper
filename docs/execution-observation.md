# Hosted Run execution observation

The hosted execution graph is included in the production Run path. The original
[#50 slice](history/prior-issues.md#issue-50) began with limits-only
plain CSV; subsequent extensions cover internal preparation, grouping, shuffles,
allocation, splitting, spill/merge, codecs and export. See the
[production inventory and scoped acceptance](execution-graph-acceptance.md).
Explicit Prepare and Analyze have no complete physical graph coverage; retained
Run history remains separate from those actions. Current randomization has no
public seed or replay policy; older seeded fixture records retain their own scope.

## Implementation contract

Physical reporting is part of a processing boundary's contract, not a UI timer
or an occasional loop checkpoint. Every `Kind` must exhaustively declare a
`ProgressUnit` in `observation/physical.rs`: streamed rows, consumed bytes,
batch-only row work, or a phase without a row total. Adding a kind without a
policy fails to compile. Comparison sorts, Fisher–Yates and spill-run construction
report their final batch size; they do not manufacture intermediate sort progress.

An `Attempt` is a non-copyable, must-use owner. It retains the small delivery
owner and its latest real counters. An explicit terminal method consumes it;
otherwise dropping active work emits Interrupted, and dropping unused pending
work emits nothing. Known errors use `finish_error`, `finish_result` or an
explicit classified terminal outcome. Successful aggregate completion remains a
separate processing acknowledgement; a completed attempt does not prove that
later groups will not invoke the same step.

Row consumers must account at each successful row boundary. Logical stages
forwarding rows use `observation::rows::ObservedRows`, which starts pending work
when a row arrives, forwards both owned and compact rows, and counts only
successful calls. An explicitly inclusive scope can also cover preparation before
its first emitted row; that interval has elapsed time but no emitted-row count.
Grouping and strata materialization use this adapter. Physical writers, merge
cursors and allocation/input loops account in their owning row methods or loops
through `rows_processed(total)`; encoded I/O uses `bytes_processed(total)`.
Metadata-only staging reports successful groups independently of row counts.
The reporter alone owns the 4096-row / 65536-byte checkpoints and 100 ms delivery
throttle. These checks never require callers to read a clock, and do not retain
a callback admission grant between emissions. Disabled observation remains
optional and cannot turn required CSV work into an error.

Debug checks reject skipped row boundaries, backwards counters, the wrong unit,
and streamed-row success whose final total was not accounted for. This catches
missing instrumentation even on small jobs that finish before a live update is
due. The contract tests cover unpublished tail counts, early returns, pending
work, repeated attempts, success/error classification, owned/compact forwarding,
byte units, empty groups and bounded admission. These checks enforce accounting
at declared boundaries; semantic changes still require a workload proving that
the chosen boundary and units describe the actual work.

## Measurement and result boundaries

`measurements.ts` declares exhaustive display units for each card kind and keeps
row counts, row visits, frame lengths and bytes distinct. Branded work durations,
timeline coordinates and activity-window durations cannot be substituted at the
rate or timeline APIs; a compile-time test checks both directions. Rates use
inclusive measured work, not the activity window or whole-job elapsed time.
Nonfinite durations and unsafe counts are rejected at the measurement boundary.
This adds type constraints without redefining the existing timing arithmetic.

Input/configuration result ownership and publication receipts are described in
[the hosted lifecycle contract](browser.md#result-ownership-and-publication-contracts).
Native publication uses a nonconstructible `EnginePublication` token, created only
after the commit point, and an internal `PublishedAnalysis` owner. Native job
completion consumes that typed result or receipt; an ordinary prepared Analysis
cannot mark a job complete. Public engine Run/execute facades still return
Analysis and preserve the same serialized result shape.

## Facts and lifetime

Prepared serialization and sorted grouping announce their start when the first
row reaches their processing boundary, rather than when a writer is constructed
or its downstream source is wired. Streaming membership likewise starts on its
first input. Completed empty work and failures during output-prefix construction
still receive explicit outcomes at finalization/failure; unused pending scopes
emit nothing when discarded. Pending scopes retain source links and use the same
single-byte state slot as active/finished spans, without a new heap owner.
Input reading, exact allocation, grouping and snapshot serialization publish
admitted, throttled row progress at 4096-row checkpoints. Exact-allocation
progress counts rows as memberships are assigned, before its inclusive scope
finishes downstream sorting and emission. A final merge can remain active while its rows are grouped
and serialized: these are nested streaming scopes on the one worker, not proof
of parallel execution or a requirement to materialize each whole stage first.

The client copies the submitted Job before permission/worker awaits, then
establishes a Run identity and freezes its bounded configured-flow projection
before starting processing. Form edits cannot change the queued request. The projection is UI state, not a Job schema change.
Only non-null CSV settings and limits appear. The final CSV output operation is
number 1 for limits-only jobs and follows the configured transformations for
prepared jobs. CSV writing maps to it; input, export and
marker support do not. Editing the form cannot relabel retained history.

The shared engine's optional `run_observed` sink supplies fixed `read` and `write`
physical identities and scoped row counters. Reading begins before input opening;
writing begins at direct writer construction. Counts advance in 4096-row batches,
with final counts at traversal completion. Input completion follows the stable
source metadata check; writing completion follows private output publication.
Both scopes overlap on one synchronous streaming worker. Rows/elapsed wall time
is an attributable average for that scope, not exclusive CPU time. Missing or
zero-duration rates are omitted. The graph is data flow, not parallelism.

The export adapter reports saved-and-closed files including manifest.jsonl.
On the browser's direct destination path, saving starts when the storage bridge
confirms the first destination writer opened. It can overlap CSV processing.
Processing completion does not confirm destination export. The marker step starts
after result writers close. It confirms only after the existing marker writer
closes and a bounded read of that exact marker matches the v1 completion record;
readback failure fails verification and does not issue a publication receipt,
even when a completion record was successfully closed on disk.
There is no destination scan or new rollback contract. Directly attributable
export/marker failures mark that step failed. Unfinished work on cancellation is
interrupted; lost terminal observation is unknown. Confirmed completions survive
shutdown and cleanup failure. Early failures can leave no physical nodes.

The page retains one history until a new Run. Analyze/Prepare do not replace it.
Messages carry a Run identity, and worker handlers also check worker generation.
New Runs replace DOM cards; ordinary updates preserve existing list elements,
keyboard focus and the collapsed/expanded panel state. Graph and keyboard list
use the same retained facts. Source rows, previews and partition values are never
included in observation records.

## Fixed bounds and ownership

These are current fixed capacities, independent of rows, files and duration
(direct producer facts and the shared hosted transport/view envelopes):

| Owner | Fixed envelope |
| --- | --- |
| Rust producer | Two inline steps; no Vec, String, graph, event queue or summary map. Snapshot contains two enum statuses, two u64 counts, two f64 durations and one availability flag. |
| Rust delivery | At most one snapshot serialization at a time; fixed 1024-byte stack buffer. An 8192-byte workspace/shared grant covers callback serialization overlap and scratch. It is released before mandatory CSV work resumes, including after sink rejection. Inline retained state has no heap allocation. |
| Adapter stdout | One observation line at most 1024 UTF-8 bytes. Static field names/statuses; no producer-controlled text. |
| Worker retained state | One cumulative snapshot, four fixed direct/export categories plus at most 1152 prepared physical summaries. No per-file records. At most 128 significant events and a 1156-slot Uint16 deduplication mask (2312 bytes), described below. At most 1156 worker-clock timing windows retain first observed start (nullable), last activity, status and the latest attempt ID. The worker writes pause coordinates to a single current shared block of 1,024 entries and sends each block to the page when it starts filling it. |
| Worker → page | One observation message outstanding, using one 4-byte shared credit. One pending cumulative snapshot replaces intermediate measurements. A terminal request reply may additionally contain one final cumulative snapshot; it never waits for credit. Each producer record is under 1024 serialized bytes. Prepared delivery batches are bounded by 4 MiB serialized observation content. Pauses use separate fixed-size shared blocks and continue to accumulate while observation credit is held. |
| Page retained state | Four direct/export steps plus at most 1152 prepared summaries, up to four source edges per summary, 128 retained significant events, at most 1156 timing windows and one frozen configured flow. Coordinates for all observed pauses remain available until the next Run, so their memory usage grows with the number of pauses. Up to 16 operation projections (16 column names of 64 UTF-16 code units each), eight CSV setting values of at most 64 code units, and three numeric limits. Compression and strategy text are clipped to 64 code units; part counts and requested percentages to 32. Extra configuration detail is explicitly labeled omitted. No submitted Job or row payload is retained by the history. |
| Presentation | One shared semantic list of at most 1156 selectable step cards, styled as graph/list, plus a lazily rendered Timeline table of at most 1156 selectable rows; at most 17 configured-operation buttons, one inspector and one warning/summary. Retained significant events are not rendered as event buttons. Generated measurement text has fixed structure and bounded numeric fields. Controlled observation strings, aggregate snapshots and DOM text stay within a conservative 32 MiB logical payload envelope across worker/page copies. Full pause coordinates are separate from that envelope. Dense rows draw their earlier segments in one bitmap. These bounds do not cap JS heap or RSS. |

The direct schema saturates at four categories/three dependencies; the prepared extension has the additional fixed bounds below: additional
work cannot append nodes, edges, text or categories. Repeated updates replace
counters; coalescing is explicitly labeled and does not imply lost rows.
At 8191 available working bytes, observation admission is denied transactionally;
a bounded unavailable snapshot is attempted and execution continues. Later
serialization admission denial also disables collection. Delivery exceptions
retain unavailability where possible. A lost stream never retroactively completes
last-active steps from overall success. Rendering failure cannot fail processing.
Native callers use the existing non-observing path with no graph construction or
serialized-output changes. WASI requests without observation credit likewise
run without the observer. The grant is not retained between producer callbacks,
so optional telemetry cannot hold capacity needed by later CSV allocations.

## Validation boundary

Timeline timing is captured in the worker before credit/coalescing, using a
single monotonic JavaScript clock across processing, export and marker steps.
It is independent of the 128-event prefix. Each identity retains one activity
window, bounded to 1156 windows; repeated attempts extend its last activity rather
than adding trace records. Duplicate/stale terminal records cannot extend a
completed window. Missing first starts remain unknown even if later attempts
start. This is worker-observed scope timing, not Rust-exclusive CPU or per-attempt
scheduling evidence. Windows may include idle gaps or nested downstream work.

The page validates finite, ordered coordinates and the fixed count before
copying timing fields. Live windows extrapolate elapsed time from the latest
worker clock; completion/interruption freezes the page clock, while legitimate
late terminal confirmation can supply final captured data without reactivation.
An interrupted window without a terminal observation has a filled final segment
with a dashed border to the frozen capture cutoff and an explicit “end not
observed” label. Earlier segments keep their solid borders.
Timeline refresh runs at most four times per second only while visible, open and
active. It pauses in hidden tabs/collapsed panels, retaining observations and
refreshing on return. A new Run releases prior timing rows/models. Missing data
renders an explicit unavailable message. No trace is fabricated from cumulative
duration or event-prefix order.

The Timeline table exposes step names, observed time ranges, statuses and
measured work as text, with native row-selection buttons and decorative bars.
Rows sort by observed start (or last activity if the start is unknown), retaining
DOM/focus while updating. Each row maps to the existing configured-operation
links and inspector. The bounds harness saturates both graph cards and Timeline
rows/windows at 1156, including their extra fixed logical envelopes under the
existing 4 MiB delivery / 32 MiB logical-payload bounds. These are not heap/RSS
claims. Unit, workspace and real-worker refinement checks cover timing beyond
event saturation, repeated-attempt gaps, missing timing, frozen clocks, hidden-tab
refresh, keyboard/bar selection and local horizontal scrolling at narrow widths.

The public hosted page Run test uses real workers, production WASI, OPFS and
picker fixtures. It independently reads two 11-byte, one-data-row CSVs, manifest
and valid marker using a fixed seed, checks graph/list facts and frozen labels,
and repeats Run with observation disabled at the worker request boundary. Only
telemetry admission changes in that baseline; CSV execution/export remain real.
Focused tests cover disabled delivery, 10,000 coalesced updates with one credit,
stale Runs, unknown markers, confirmed history, native CSV parity, malformed
input attribution, grant denial and release. The existing resource reactor runs
the admission/release assertions in WASI as well.

These small fixtures and lifecycle checks do not establish the parent issue's
long-running 5% overhead target, scale acceptance, broader physical-path coverage,
advanced inspection or repeated-work summaries. Subsequent slices must extend
the schema with explicit caps and ownership before adding instrumentation.

## Internal preparation, grouping and resident shuffle

Issue [#51](history/prior-issues.md#issue-51) extends only hosted
Run. The optional `run_with_observations` path supplies a caller-owned bounded
fact sink, injected into the same preparation implementation used by existing
Run. Explicit Prepare has no sink. No Job, Progress, native output, execution
eligibility or seeded-domain change is introduced. Empty-operation calls retain
normal direct dispatch. The WASI adapter selects the observing internal path
only for a Run with observation credit and configured operations.

Actual producer sites report input traversal, resident comparison sort,
Fisher–Yates loops, grouped-row materialization, CSV snapshot serialization and
private-result materialization. A sort uses its actual resident selection;
external sorting uses the actual spill/merge observations described below.
Routed-group traversal is distinguished from traversal after comparison sorting.
Private materialization reports elapsed time, not invented row throughput for an
encoded-byte copy. Serialization maps only to the final output operation.

Original operation identities travel with Context scopes. A partition/uniform
sort carries the partition and final uniform-shuffle indices. Earlier overwritten
uniform shuffles emit explicit elision annotations, including later pipeline
spans. These annotations carry no data-flow edge and imply no shuffle execution.
Known input/sort/group/snapshot/materialization/export sources are connected;
unknown upstream scope is explicitly labeled omitted, without guessed rescan,
reuse or worker-parallelism claims. A source edge is drawn only when its source
has been observed. Inline metrics identify completed aggregate work, and partial
interrupted rows/time remain separate from confirmed completed attempts.

The producer retains no graph or per-group records. Facts are at most 384 bytes
inline and spans at most 512 bytes (checked on native/WASI contract builds).
The existing Context budget has two additional fixed atomic controls; Context
clones carry the caller-owned sink, two operation indices and optional source ID.
Category IDs are assigned by Rust using one encoding helper and transmitted on
the wire; TypeScript never infers Rust enum ordinals. Sixteen configured
operations plus final output yield at most 18 operation slots times 32 reserved
category slots times two roles (pipeline and exact stratification), or 1152 summaries. Supporting work uses operation zero.

At most 65,536 ordinary producer records are emitted per Run, followed by one
bounded omission notification. Collection then disables; CSV processing and
cancellation continue. Admission uses an 8192-byte callback grant, released
before required work resumes. Ordinary denial or sink rejection disables further
collection; the sink is caller-owned just like Notify. The WASI sink has fixed
1024-byte stack serialization. No source text or row payload enters facts.

The worker folds all records into the bounded operation/category summaries
before delivery. Completed and interrupted attempts have separate counts,
rows and duration totals. Ordinary summary snapshots are delivered at most every
100 ms, plus terminal synchronization. One shared delivery credit still bounds
outstanding messages; a final request reply may contain the same final bounded
snapshot without waiting for credit. No acknowledgement blocks processing.
Unsafe numeric counters or exhausted detail bounds retain unavailability.

The public hosted fixture command is `node scripts/test-browser-graph.mjs`, now
part of hosted CI and the standard acceptance sequence. It includes direct Run
followed by prepared Run, standalone partition/uniform/Fisher–Yates, exact fusion,
initial and later shuffle elision, and repeated child-group shuffling. Each case
uses real workers/WASI/OPFS and independently verifies CSV membership, order/parity,
strict caps, manifest records and the valid marker with collection disabled.
Default/advanced inspection, other
advanced inspection and long-running overhead acceptance remain later work.

## External sorting, fallback and ordered-file reuse

Issue #52 adds actual spill construction, materialized merge passes, hierarchical
merge passes and final streaming traversal. Each spill reports its sorted rows
and one completed run only after its writer and catalog are finalized. Merge
passes report **row visits**, input-run counts and available merge levels; these
are not unique input rows and must not be summed with other passes as conservation
counts. Final traversal counts rows actually consumed, including cancellation
partials, with counters batched every 65,536 rows and at most every 100 ms.

Bounded value grouping now has a distinct lifetime. Accepted rows count only
successful routing writes. A late-key/order fallback closes those ordered files,
marks prior grouping handed off, and reports their reuse without re-sorting.
Fallback does not replay source CSV input. Fresh rows become new spill runs;
actual consumers reference the origins of their consumed runs. Each existing
SortRun catalog entry has one inline origin tag, admitted through Catalog
using the current entry size; native/non-observing runs leave this tag empty.
Materialized outputs replace their ancestor provenance with their merge origin,
so a later traversal never claims to read already-consumed spill/reuse files.
Source sets have four fixed slots. Summary-level self edges are prohibited; unrepresented
higher-level sources are explicitly omitted rather than drawn as graph cycles.

Facts have a monotonic attempt identity within a Run. The worker retains separate
completed, handed-off, interrupted and failed outcomes, with their own row visits,
runs, durations and attempt counts. Repeated passes/parents do not create retained
per-file or per-group nodes. Default production grouping handoff is not a failed
attempt or raw-input retry; experimental retry paths are not enabled for coverage.
The existing fixed producer record cap and one-message delivery credit remain.

Router and MergeRows retain only inline observation state. Callback grants end
before filesystem work resumes. Drop records interrupted traversal/grouping
without changing cancellation/error cleanup. Context cancellation keeps its
existing displayed error text with an internal typed marker, so cancellation is
distinguished from attributable decode/write failure without parsing messages.
Materialized merge errors retain measured partial row visits and input-run counts. Router's into-runs and finish paths
consume their observation once, retain independent reader/file ownership, and
transfer the existing reservation before destroying the routing owner. Sorter
metadata admission uses its current size; tree bucket/value layout is unchanged.
Native non-observing output and seeded ordering remain unchanged.


## Allocation and stratification

Issue #53 observes exact and probabilistic membership at their actual executors.
Their inclusive elapsed time and row visits cover membership plus the executor's
ordering/materialization work; they are not exclusive CPU timings. Exact strata
partitioning and its sorting use a distinct fixed role and map only to allocation.
Probabilistic strata alter membership sampling without inventing a partition or
shuffle node. A following uniform shuffle keeps its original operation mapping.

Each outcome retains actual completed logical groups, empty groups and the first
16 configured membership counts. Percentages remain requested configuration;
observed counts reflect successfully closed groups, including zero memberships.
Repeated parents aggregate into these fixed slots; omitted parent/group membership
entries are counted explicitly. No stratum values or samples are retained. Frozen
configuration retains at most 16 group labels of 64 UTF-16 units per operation.
Snapshots copy nested count arrays before delivery.

Intermediate Dataset writers report successful framed rows and group metadata,
including metadata-only shared storage, under a distinct materialization identity.
Their returned Dataset carries one inline source ID to the next consumer. Sink
handoff connects actual sort/group traversal to dataset or CSV construction;
producer edges are not inferred from configuration. Inline observation owners
hold no callback reservation during required storage work. Typed push failures
are failed outcomes; cancellation remains interrupted. These additions preserve
seed domains, rounding, group order and existing file/publication ownership.


## Balanced and interleaved splitting

Issue #54 observes the production split executors. Intermediate balanced work
scans frame lengths, writes logical child metadata and shares the existing data
file; its card reports frame lengths scanned, while the intermediate Dataset
reports zero framed rows written. Terminal balanced work reports rows emitted in
consecutive groups. Uniform-to-balanced fusion reports one sorted traversal under
the balanced operation's original index, sourced from the actual shuffle sorter.
Partition/uniform fusion followed by balanced can instead materialize parents
before ordinary balanced emission; the graph does not infer split fusion from
adjacency in the configured flow.

Interleaved membership reports inclusive encounter-modulo routing and emission,
with the actual sorting/traversal producers shown separately. No parallel-worker
or separate-copy claim follows from logical child groups. Each parent contributes
a bounded attempt, aggregated into the existing operation/category summary;
first-16 part counts and omitted membership entries keep their existing bounds.
Frame scans and row loops check cancellation and offer progress every 65,536
visits, at most every 100 ms. Counts/rates identify their own work and are not
added across metadata scans, routing and final output as unique rows.

The frozen flow shows the configured part count, omits unset options and assigns
final CSV row/byte limits only to the last numbered output operation. Existing
exact descendant groups retain their hard-cap and nonempty constraints, including
a following shuffle. This instrumentation does not alter rounding, membership,
lineage, encounter order, seeded ordering or publication/cleanup behavior.


## Compressed input and output

Issue #55 observes actual gzip and ZIP adapters after signature
detection, including construction, selected-member lookup, reads and finalization.
Input adaptation is supporting work, with no configured-operation badge. Input
counters measure successfully returned decompressed CSV bytes **before character
decoding**, including any input BOM. Their inclusive elapsed scope spans the
consumer's work; it is not exclusive decoder CPU time. Read/constructor errors
are attributed to adaptation; a consumer failure or cancellation interrupts an
unfinished adapter without falsely blaming the codec. Input names/extensions do
not select graph categories or alter existing signature/member-selection rules.

Output gzip compressors and ZIP CSV-member deflaters measure encoded
CSV bytes actually accepted, including BOM/header copies for each chunk. These
counts implement strict CSV caps; they are not compressed payload sizes. Their
inclusive lifetimes include actual compressor finalization and writer sync.
ZIP assembly separately measures successful outer archive writes and finalized
entry counts, including its manifest and central directory. Archive bytes are not
per-member CSV bytes or the advisory compressed target. Actual member-spool
consumption supplies the archive's deflate dependency; raw CSV is not declared as
a direct archive input. All output codec/archive facts map to the final output
operation. Destination file closure and marker confirmation remain separate.

Direct Run retains its two fixed row snapshots and adds these bounded physical
facts through `run_observed_with_physical`. Its CSV writer remains the direct
writer, without a fictitious snapshot step. Prepared Run uses the same codec
boundaries, sourcing input traversal from actual adaptation and compressors from
the encoded snapshot. Native non-observing entry points retain their output and
construct no graph. A codec callback rejection or admission failure disables
optional collection while required CSV/codec work continues.

Input observation borrows the already-admitted boxed reader through a stack
wrapper; it adds no Box or heap buffer. Output wrappers retain fixed inline
state, while codec owners/grants remain unchanged through explicit/implicit
finalization and destruction. Byte counters share the existing safe-integer,
record, serialization, summary and delivery bounds. Up to four source edges can
reference the four fixed direct steps or prepared identities. No event capacity
or codec-backend change is introduced by this slice.


## Interrupted and degraded observation

Issue #56 keeps terminal facts separate from job status. Stale active facts cannot
reopen a terminal attempt, and prior Run/generation messages cannot update a new
Run. After shutdown, an actual queued completion for the same retained Run may
confirm work; it cannot change processing status or release the new worker's
credit. Overall success never substitutes for missing physical completion facts.

The [session module](../ui/src/browser/session.ts) owns worker errors, success
cleanup and overlapping cancellation continuations, checking their captured
lifecycle identity after awaits. Pending requests, worker resources and delivery
credit belong to the originating session; retired messages never acknowledge a
replacement session's credit. Cleanup failure preserves confirmed
exports and reports cleanup uncertainty. Cancellation does not wait for an
observation acknowledgement. The page reports last-observed interrupted/unknown
counts, rejects unsafe direct measurements and marks unavailable detail explicitly.
Prepared CSV parse/width errors, snapshot construction/write/finalization errors
and private-result materialization errors report their attributable scope and
measured partial rows. Typed cancellation remains distinct from processing failure.

`node scripts/test-browser-graph-lifecycle.mjs` exercises the public hosted Run
with production workers/WASI/OPFS and test-only worker routes. Its sixteen cases
cover worker death, processing cancellation, result close, marker write/close/read,
cancellation before/after confirmation, delayed confirmation and replacement Run,
observation transport/loss/render failure, and success/cancel cleanup errors.
Independent destination reads verify CSVs, manifests and marker contents. Routes
and fault controls live in the harness; production packaging has no injection API.
These small fixtures establish lifecycle behavior, not broad timing or overhead
claims. The final combined resource/performance acceptance remains #58.


## Advanced inspection and significant events

Issue #57 captures events in the engine worker before physical snapshot coalescing
and before delivery credit. Direct/export state updates use the same collector.
The first observed start, each terminal outcome and fusion/fallback/reuse/elision
annotation per physical identity are retained; individual attempts, rows, groups
and files never append a trace. Repeated work remains in summary counters. Event
timestamps are worker receipt time since collection began, not reconstructed
producer start times or exclusive timings. Strategy annotations have no data-flow
arrow; graph cards' arrows name their actually observed input producers.

The event collector owns at most 128 fixed-shape records (index, step identity,
elapsed seconds, enum kind) and the fixed 2312-byte mask. Unique changes beyond
the cap increment an omission count; masks prevent repeated outcomes from growing
it, so its maximum is 1156 times ten categories. The event payload, including its
omission metadata, is bounded by 32768 serialized bytes. It joins the existing
cumulative pending/delivery and terminal snapshots inside the existing 4 MiB
message and conservative 32 MiB logical payload envelopes. The page retains one
128-entry cumulative event prefix, rejects malformed times/identities and never
retains the worker mask. Event omission is explicit; it does not lose row counts
or block processing. Worker shutdown drops its collector; retained page events
last until the next Run. Late actual same-Run confirmations may enrich history.

Graph/list modes style one keyboard-operable ordered list, using identical
metrics, dependencies, status and operation mappings. List rows follow the same
activity/dependency order as the graph; existing card nodes are retained while
late producers repair that order. DAG slots are assigned from observed
dependencies in a graph viewport that grows with its content. Updates change text in place;
there is no second graph model or full-history JSON render cache. One revision
counter suppresses redundant renders. Selection highlights operation mappings in
both directions and labels supporting work. Controls preserve selection across
views. Ordinary events, metrics and omission updates do not announce a live
trace or move focus. The former Details toggle, technical notes, category tags,
dependency counts and event-navigation panel are removed. Bounded event capture
still supports observation lifecycle/unknown-state handling; it is not rendered.
Cards show cumulative rows/bytes, spill-run counts where applicable, elapsed
time and average throughput when positive work and a finite positive measured
duration are available. Rates use the same cumulative work/time scope as the
card: rows/s for row-processing steps, row visits/s for merge traversal, and
binary B/s, KiB/s, MiB/s or GiB/s for codecs/archive work. These are attributable
wall-time averages, not instantaneous rates, exclusive CPU or physical disk
throughput. Materialization, file-count-only export, reuse/fallback and marker
steps do not invent rates. Number and rate unit wrap together.
Active attempt counters add to confirmed work, so starting the next attempt
does not replace cumulative totals with waiting text or membership detail. The
last observed counters survive interruption or lost terminal delivery; a later
partial terminal measurement can update them without crediting completed work. The
selected-step inspector retains full measurement scopes, group memberships and
partial outcomes on demand; unavailable memory/RSS remains unavailable.

Configured-flow buttons also show a compact strategy observed for each operation:
random-key or comparison sorting in memory/external storage, Fisher–Yates,
bounded routing, explicit routing fallback, ordered-file reuse or shuffle elision.
Fused sorts map to both configured operations. These labels derive from retained
physical observations, not a guess from the selected Auto setting. Before a
shuffle/partition strategy is observed, the label says so. Incomplete observation
is explicitly marked partial. Selecting the operation repeats its strategy in
the existing inspector; the results' Execution strategies disclosure retains
aggregate counts, and Processing details records effective memory/workers.
“Memory + external” means both resident and spilled execution were observed for
the operation, potentially in different parent groups; it does not assert a
single-parent transition. Only an explicit fallback observation earns the
“Routing → sorting” label. An Auto shuffle uses external-capable random-key
sorting; buffering records before a first spill is not a completed resident sort
or evidence that Fisher–Yates was selected. No additional Job/configuration
projection fields or event history are retained for strategy labels.

`node scripts/test-browser-graph-inspection.mjs` verifies real fused partition /
uniform work and 100000 rows summarized across 64 parent groups with child
Fisher–Yates. A test-only worker route pauses at an actual observed input start;
release permits real processing/terminal updates while checks retain the focused
card, its position relative to the viewport and scroll offset. Semantic checks
cover collapsed capture, cross-highlighting, selected inspection, view selection,
explicit supporting work, frozen limits after form edits and unchanged history
across real Analyze/Prepare/cancel activity. Independent CSV membership/counts,
manifest and marker checks establish the processing seam. Optional
`--screenshots=<directory>` records targeted wide/narrow graph and list views;
390px and 1280px layouts were visually reviewed. This does not establish the
representative long-job overhead or final saturation acceptance owned by #58.


The [integrated acceptance record](execution-graph-acceptance.md) inventories
production paths, composed codec/lifecycle coverage, the explicit logical-value
census and the accepted scoped per-workload overhead result, including retained
unmet reports and conditional precision-selection limitations. Its saturation harness
supplements real Run acceptance with focused synthetic boundary data; those
synthetic counters are not reported as actual processing measurements.

Locally ending an active physical attempt does not supply a terminal measurement.
The renderer uses that newest attempt's last observed active rows/bytes/time
when its attempt identity has no terminal fact. Prior confirmed completed totals
remain separate, and an actual terminal fact selects its own measured outcome.
Focused rendered-history regressions cover interrupted/unknown lifetimes, merge
row visits, codec bytes and terminal precedence. The first overhead cohort was
stopped when this display defect was found; its partial data are excluded from
the replacement comparison.


## Layered DAG presentation

Graph view draws SVG producer-to-consumer arrows behind the same retained,
keyboard-accessible step cards used by List view. Physical operation identities
group related work into horizontal layers. Pipeline stages progress downward;
related physical work is arranged across lanes within a stage and may have
horizontal dependency arrows. These rows represent logical stages, not strict
per-edge dependency depth or concurrently executing workers.
Input, final CSV materialization, destination export and marker confirmation have
their own positions. Explicit source sets provide the edges. The fixed direct
read/write/export/marker relationships are used only where their contracts are
known; omitted prepared sources and elision annotations never acquire guessed
arrows. Missing producers stay unavailable until observed. Defensive cycle
removal affects display only, with an unavailable-link count; history facts remain
unchanged.

A Run retains at most 1156 node positions and four source links per node. SVG
paths, the topology key and layout maps are bounded by that envelope; the bounds
harness includes conservative additional logical layout/path allowances. These
working logical estimates are not a heap/RSS bound. Existing producer,
transport/event limits and execution semantics are unchanged. Historical graph
overhead measurements do not qualify this renderer's performance.

Live counter updates reuse the layout and existing focusable buttons. New nodes
append activity slots; each activity row shares its largest measured card height.
Late producers repair left-to-right dependency order without replacing card DOM
or keyboard focus. Redundant within-row edges are omitted when another observed
path already connects the same producer and consumer. Opening the panel or
reenabling Auto-fit recomputes dependency order from available observations.
The graph grows vertically with the scaled content, including newly observed
steps. Auto-fit scales to the available width and follows new lanes and viewport
resizing. It never enlarges cards above their natural size. The Zoom slider
switches to a manual scale until Auto-fit is checked again.
Node state, operation matching, selection, upstream omission and the full inspector
share the retained observations. Color has visible status labels;
List view provides the same cumulative measurements and selected-step inspection
without the diagram layout.

Physical step cards keep In Progress across all repeated attempts, including spill
run sorts and writes. Attempt completion still appears in the inspector,
but a card becomes complete only after its logical stage is finalized and its
attempts have ended. An exhaustive kind-to-lifecycle table distinguishes input,
operation, serialization, intermediate and publication work. Output codecs link
to the output plan but belong to publication, so CSV snapshot finalization cannot
finalize them or reject their later start. The engine emits a `stage_complete` metadata fact after all
parent groups and admitted stage statistics commit. A monotone frontier covers
both fused and ordinary operation spans, including experimental commit paths.
Input finalization follows the stable-source check; CSV output finalization
follows the retained output plan. These facts occupy the reserved final category
slot and never create graph cards. The worker coalesces at most 18 stage IDs with
the latest physical snapshot. The page rejects new active attempts for a stage
that has already finalized. Fused cards require every owning stage to finalize.
A final complete snapshot and `processingComplete` remain the fallback barrier
for supporting work and older/missing per-stage detail. Interrupted processing
never certifies unfinished stages. Later destination-marker uncertainty does not undo an
already observed processing completion; export/marker cards retain their own
lifetimes. This display flag does not change Rust attempt status or counters.

## Adjacent range and mixed-shuffle observations

A full-shuffle/exact-assignment producer maps both original operations; its range
consumer reports ExactMembership with actual quotas and the real permutation
source. It does not report an assignment RNG or grouping sort that never ran.
Leading ingestion and retained parents preserve their distinct Read/Dataset
sources. Mixed-method elision retains every configured stage; skipped earlier
auto/uniform work has a source-free Elided fact, and final Fisher–Yates reports
its original operation index and actual resident work. No intermediate row trace
is exposed by these count/fact summaries.

Destination admission precedes active export observations and exporting/progress
notifications. Rejection may report a failed attempt after the check; it never
reports export start or modifies an existing result. Marker confirmation remains
after all result writers close.

## Live graph layout and merge delivery

The hosted graph grows vertically with its observed activity rows and wrapped
card content. Each activity row retains its greatest measured card height for the Run, including
when Auto-fit is reenabled or the panel reopens. A new Run resets that minimum. Rows identify
the configured operation or input/output/export activity; raw partition values are not collected. Hover or keyboard focus on a
card or activity label connects to matching output-plan entries at the plan card
border. A scrollable plan pane reveals the matching entries while the graph stays
in place. An entry outside the visible area gets a continuation arrow at the
edge. In a stacked layout hover leaves the page in place. Click the selected card
again or click empty graph space to clear the selection. Dragging to pan preserves
it. Stacked card edges mark a step with more than one observed attempt. The shared
semantic list and bounded node count remain unchanged.

New physical identities and attempt/status transitions bypass the 100 ms
counter-display throttle. Storage bridge activity flushes pending delivery when
the page has returned credit, even while WASI is synchronously processing.
Materialized merge loops sample row visits every 4096 rows using the existing
100 ms producer throttle. This preserves the one-message credit and fixed-record
envelopes; it does not infer exclusive work or finalize repeating attempts early.

Cards and unstarted work are distinct: unknown-only observations do not invent
placeholder cards. Bounded routing starts observation on its first row, rather
than when its empty router is constructed. Allocation therefore precedes its
routing consumer. Unit-bearing measurements wrap as individual tokens, while
card text remains untruncated. Same-row arrows are straight; cross-row curves
finish with a vertical segment aligned with their arrowhead.

`node scripts/test-browser-graph-refinements.mjs` exercises the reported three-step
shuffle/partition/probabilistic-allocation pipeline with 10,003 rows, 60 parents,
real workers, WASI and OPFS. It checks ordering, equal row heights, unit wrapping,
straight row links, action button heights at three widths and
independently exported row conservation and partition membership. It does not
establish the 25-million-row workload's performance.

The configured flow uses compact numbered operation buttons; full frozen settings
remain in their accessible names/tooltips and the selected-operation inspector.
Execution view controls are grouped in a keyboard-navigable toolbar. The hosted
Output plan retains configuration and actions; a separate Results & analysis
card holds phase progress, result location, exact analysis and cardinalities.
These cards sit alongside each other on wide layouts and stack on smaller ones.
Paired cards share header/body grid tracks, aligning their title dividers and
stretching to equal total heights. A wider editor and narrower result columns
reserve more of the viewport for configuration and execution.
Phase elapsed time freezes when a job leaves a busy state; successful completion
replaces the active phase display with the result summary. Card counters retain
rows, units and elapsed measurements without derived completion percentages.

Hosted text follows the browser's preferred root size, with 15px primary text
and a 13px secondary-text floor at the default preference; text inputs retain
16px. Processing metadata remains in its result disclosure. Observation-unavailable
and omitted-configuration warnings stay visible. List view uses compact activity
labels and a vertical sequence with the same cumulative counters and selections
as the graph. Keyboard users can open every disclosure; no required information
depends on hover alone.

### Execution presentation

Graph, List and Timeline keep one aggregate In Progress badge while more parent
groups may invoke a step, including gaps between attempts.
Completed appears after an authoritative stage-finalization fact confirms no
more parent attempts can run for that stage, or after the complete processing
barrier for remaining supporting work. Direct read/write/export/marker
steps retain their own one-shot boundaries. Missing observations remain unknown;
overall success never fabricates a terminal step fact. Cumulative counters still
combine confirmed attempts and current observed work without resetting at
boundaries. Badges and card treatments stay steady between groups. After an
actually observed active attempt, decorative animation instances pause at their
current frame during gaps and resume for the next active attempt. They are not
removed/restarted at every boundary and do not move while waiting. Steps first
observed in a terminal snapshot retain a static diagram until activity is seen.

Intermediate dataset writers now report actual row/time progress during writes
and metadata construction, using the existing 100ms emitter throttle with checks
every 4096 rows or groups. This adds no per-row clock read and preserves the
fixed-record observation admission/omission path. It replaces start/finish-only
reporting; card times and rates remain observed measurements, not invented work.
Read diagrams scan across successive lines. Sort diagrams lift and reorder bars
of different heights into ascending order. Merge diagrams follow both incoming
branches, join at the confluence and send one larger output to the right.

Context labels and configured-flow controls name the selected mode, including
exact versus approximate assignment and consecutive versus alternating splits.
The editor's picker and editable card headings use the broader family names
(Assign groups by percentage and Split into equal parts), since their controls
contain both modes. JSON/CLI operation identifiers remain unchanged. Timeline bars use the
output plan's operation colors; a fused step uses its first mapped operation's
color and lists all mapped operations. Unmapped work stays neutral.

The graph grows to fit all activity rows at every zoom level. Vertical scrolling
moves the page. The Zoom slider supports dragging and native keyboard controls.
Dragging empty graph space pans horizontally without taking card clicks or text
selection. The focusable graph also supports horizontal arrow-key scrolling.

The results metrics promote the existing analysis processing duration and average
row throughput. That processing duration excludes destination export/publication;
it is not a newly introduced end-to-end stopwatch. Warning messages have a separate
section outside the resource/strategy disclosures. A timeline row spans the first
observed start to the latest activity. The worker records pauses between an
observed attempt ending and the next attempt starting for the same step, before
delivery to the page can coalesce observations. Every observed pause is retained and included in the row count and duration.
Gaps narrower than a pixel may be hard to distinguish at the full-run scale. Measured work sums
recorded attributable attempt durations plus the observed active or partial
measurement. Nested scopes may overlap, so sums cannot isolate CPU time or
decompose the complete job's wall time.
