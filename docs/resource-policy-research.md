# Host-aware memory policy: research and implementation constraints

Research date: 2026-10-16. This supports the remaining
[adaptive execution](adaptive-execution.md) work. Source facts, local observations
and proposed policy are distinguished below. The subsequent [shared-admission implementation and measurements](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16) implement the aggregate ledger and startup Linux discovery. The [dynamic-pressure follow-up](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16) adds boundary rechecks; automatic per-job sizing and complete accounting remain proposals. This research establishes no performance improvement.

## Residual ownership inventory for #86

This inventory reconciles the original resource gaps with the shipped native
CLI and hosted worker. [#14](https://github.com/jsmatfess/chopper/issues/14)
tracks residual work. The retired native HTTP server and picker have no active
process ownership here. Their completed [request](#native-http-decoded-request-ownership-2026-10-23),
[response](#native-http-json-response-ownership-2026-10-23), and
[retained error](#native-retained-state-error-ownership-2026-10-28) contracts
remain in the dated record. Current filesystem and browser acceptance follows
[validation](validation.md).

### Completed owners to preserve

| Boundary | Source and contract |
| --- | --- |
| Retained configuration and generated seed | [PreparedJob](../crates/chopper/src/engine/job_owner.rs) charges its [retained capacity](#prepared-configuration-capacity-ownership-2026-10-23) after caller construction and validation. |
| Engine-produced Analysis and inspection payloads | [Shared payloads](../crates/chopper/src/engine/shared_analysis.rs) keep their grants through the last clone. See [Analysis header](#analysis-header-and-shared-payload-ownership-2026-10-23), [diagnostics](#analysis-diagnostic-snapshot-ownership-2026-10-23), and [inspection JSON](#returned-inspection-json-owner-2026-10-21). |
| Hosted Analyze and Run report serialization | The [WASI adapter](../crates/chopper-browser/src/lib.rs) streams the typed input profile and Run report, including the completion flag, through the stdout newline with their existing payload owners alive. This removes the intermediate Rust JSON value trees. [#71](https://github.com/jsmatfess/chopper/issues/71) |
| Hosted worker invocation references | The [engine worker](../ui/src/browser/engine-worker.ts) holds the encoded Job file only through its synchronous reactor call, then clears the file entry and the stdout reply slot on success or failure. The response path owns the parsed reply through posting or export. [#76](https://github.com/jsmatfess/chopper/issues/76) |
| Retained destination, joined names and paths, and manifest | [Destination retention](#retained-absolute-publication-destination) belongs to the engine after absolute resolution. [Joined file paths](#retained-publication-path-owners-2026-10-21), [names and publication batches](#publication-batch-and-name-owners-2026-10-21), and [manifest assembly](#job-manifest-construction-owner-2026-10-21) have their own grants. |
| Controlled temporary names and reopening | [Controlled construction and reopen](#controlled-temporary-construction-and-reopen-2026-10-22) owns retained path creation and identity checks after parent discovery. |
| Input/output codecs and ZIP metadata | See [ZIP metadata](#zip-parser-admission-implementation-2026-10-21), [gzip input](#gzip-input-codec-admission-2026-10-22), and [publication DEFLATE](#zip-member-and-output-deflate-codec-admission-2026-10-22). Preserve the pinned backend and owner lifetimes. |
| Saved native Job decoding and streamed report | [DecodedJob](../crates/chopper/src/cli_job.rs) pre-admits saved config decoding and retains the charge through engine handoff. The [decoding contract](cli-job-decoding.md) defines the shared-only envelope. Analysis streaming borrows the existing output through the final flush. [Historical report change](history/prior-issues.md#issue-96) |
| Validation scratch and portable progress | Allocation percentages validate through the shared scalar parser without a temporary weight vector. [Historical validation change](history/prior-issues.md#issue-93) · [Progress ownership](#portable-progress-phase-ownership-2026-10-28) |

### Residual boundaries

| Owner and source | Construction and retention | Admission boundary and remaining gap |
| --- | --- | --- |
| Caller-built Job and validation in the [CLI](../crates/chopper/src/main.rs), [WASI entry points](../crates/chopper-browser/src/lib.rs), and [core Job](../crates/chopper-core/src/config.rs) | Flag/guide Job construction, WASI `/job.json` decoding, and library caller construction precede engine admission. The hosted loader drops its 8 KiB read buffer before calling the engine. The caller owns the Job until handoff or drop. | The saved native Job decode envelope and retained PreparedJob owner cover separate lifetimes. WASI decoding and ordinary caller construction have no predecode envelope. A bounded WASI admission child would need to preserve the browser ABI, job formats, first errors, and preview/analysis/Run handoffs. |
| Conversion and validation errors in [core](../crates/chopper-core/src/config.rs), the [CLI decoder](../crates/chopper/src/cli_job.rs), and the [WASI report path](../crates/chopper-browser/src/lib.rs) | serde and anyhow errors can retain formatting and cause chains after the source payload drops. | Existing success-path grants cover their owned data. Error objects and formatting internals have no measured envelope. Any new bound needs typed error and first-error parity on malformed inputs. |
| Explicit caller copies of [pool usage](../crates/chopper/src/resources.rs), [diagnostics](../crates/chopper/src/engine/diagnostics.rs), and [inspection](../crates/chopper/src/engine/inspection_result.rs) | Copies and deserialization allocate independent payloads that live with the caller. | Engine-owned shared clones already retain their grant. Explicit caller-owned copies lie outside the ledger. A future admitted-copy API needs its own use case and lifetime. |
| Startup and refresh observations in [host discovery](../crates/chopper/src/resources/host.rs) and [pressure](../crates/chopper/src/resources/pressure.rs) | Startup reads precede pool initialization. The pool retains its startup observation, and the current observation overlaps its replacement during refresh. | The individual discovery read is capped. Retained strings, parser scratch, pool carriers, and replacement overlap lack a separate grant. A future design must avoid reserving through the pool while holding its pressure lock. |
| Parent discovery and normalization in [JobDirectory](../crates/chopper/src/storage/job_directory.rs) and [publication](../crates/chopper/src/output/destination.rs) | Temp parent discovery and absolute resolution precede controlled construction. Native preflight resolves an inspection-only path and holds an identity witness when needed. | Staging/temporary names and the retained publication destination have grants. Discovery buffers, opaque standard-library scratch, path normalization and OS conversion remain outside those grants. |
| Framing and carriers in the [CLI](../crates/chopper/src/main.rs), [WASI adapter](../crates/chopper-browser/src/lib.rs), and [engine worker](../ui/src/browser/engine-worker.ts) | CLI report/error formatting, WASI stdout framing, JS job serialization and parsed messages, callbacks and shared carrier objects have separate lifetimes. | Engine payload grants and streaming stdout bound selected owners. Framing, browser JS message storage and transfers, and allocator/runtime overhead remain outside those grants and need adapter-specific bounds and tests. |
| Native thread and opaque runtime allocations in [publication](../crates/chopper/src/output.rs) and [directory cleanup](../crates/chopper/src/storage/job_directory.rs) | Thread runtime, channel internals, stacks, filesystem traversal, and allocator retention have platform-specific lifetimes. | No complete envelope. Startup keeps headroom outside tracked capacity and has a 128 MiB tracked fallback when native host capacity is unknown. These bounds describe working allocations. RSS includes runtime allocations. |

### Cross-instance browser admission

Each [WASI instance](../crates/chopper/src/resources.rs) has its own working
ledger. The engine worker owns linear memory, JS metadata, and transfer
buffers. [Workspace cleanup locks](../ui/src/browser/cleanup.ts) coordinate
storage ownership, including abandoned workspace cleanup. Multiple workers or
tabs still have no common memory admission policy. A proposal needs a lease
lifetime and recovery behavior before implementation. Keep actual
quota/deletion/destination behavior scoped to the [filesystem acceptance
record](history/prior-issues.md#issue-87) and the
[browser limits](browser.md#processing-and-limits). Injection establishes the
fault path exercised by the test.

### Bounded ownership changes

The completed [publication destination child](https://github.com/jsmatfess/chopper/issues/9)
covers retained destination capacity and exact/adjacent local and shared
limits, competing owners, cancellation, cleanup, and CSV/manifest parity.
The remaining rows need separately specified implementation children or
explicit deferrals in the owning issue. For each change, identify the live
owner, check the overlap with existing grants, and exercise denial,
cancellation, and release through the applicable public entry points.

## Fixed-size spool header keys (2026-11-05)

The private `storage::frame_key::FrameKey` retains eight- and sixteen-byte spool
keys inline. Other lengths retain their original Vec capacity through decode;
variable-key boxing still pre-admits old/new overlap. Spool framing, key bytes,
comparators and seeded algorithm identities are unchanged. This representation
is private and does not reinterpret arbitrary eight-byte keys as group indices.

`RowHeader` declares key storage before its independent grant, so field destruction
frees heap bytes first. Owned and compact decoders move key storage into a local
declared after the aggregate grant before fallible field construction. Packed
conversion transfers inline bytes directly; owned-row conversion pre-admits its
new Vec through `Reservation::reserve_vec`, retaining actual capacity through the
returned `DecodedRow`. Existing returned-owner field order retains storage through
last use and deallocation. Error, denial, truncation and cancellation retain the
same ownership ordering.

The larger header descriptor is retained only in merge `Head` heap arrays;
`MergeRows` pre-admits requested and actual BinaryHeap capacity with the target's
actual `size_of::<Head>()`. Reader buffers, variable keys and decoded fields retain
their separate charges. Inline header storage removes no variable-key ownership
requirement. Stack/runtime memory remains outside complete working-allocation
coverage; this is not an RSS cap or a general admission-domain claim.

Re-audit inline-to-owned conversion, variable capacity/boxing overlap, key/grant
destruction order and every retained metadata envelope before changing this type
or adding a decoder. Fixed-key frame round trips, all key truncation points,
owned-copy exact/adjacent admission edges and corruption cleanup complement the
existing variable-key, wide-row, shared-pressure and merge collision controls.

## Validated packed-field traversal (2026-11-05)

`CompactFields` and packed `FieldViews` borrow validated UTF-8 and use unchecked
UTF-8 conversion during iteration. Their private constructors and immutable byte
borrows are the safety boundary; slicing and framing bounds checks remain.
`CompactRecord` accepts only strict-parser fields validated before appending or
text copied from `&str`. Default/recycled storage is empty; errors clear partial
records. Its only iterator constructor is `fields()`.

Packed `FieldViews` originate from `CompactRecord`, `PackedRow::new_reusing_fields`
(valid String sources), or `PackedRow::read_fields_reserved` (each complete spool
field validated before returning a row). Recycling clears the parser destination;
capacity trimming and key/ordinal changes do not alter field bytes. No public raw
packed constructor or mutable byte view escapes. Partial framing after unwinding
cannot introduce invalid field text: appends validate complete fields first and
existing bounds checks precede conversion. Re-audit these facts before adding a
constructor, byte mutation, decoder bypass or view lifetime change. External bytes
still require strict CSV/spool validation; this is not a trusted-input mode.

No representation, allocation, reservation, handoff or last-owner lifetime changes.
Existing corrupt-spool, truncation, Unicode refill, growth-denial and wide-buffer
reuse controls remain required. The [comparison and limits](performance.md#validated-compact-field-traversal-2026-11-05)
record complete-job evidence separately from this safety argument.

## Shared CSV intake ownership (2026-11-05)

[`csv_intake.rs`](../crates/chopper/src/csv_intake.rs) owns the decoded buffered
source, strict parser, reusable owned/compact records and terminal state. Its
allocation-bearing fields precede their grants, including on early errors;
preparation no longer depends on a separate list of successful-path drops.
Run/preparation/profiling retain the existing 64 KiB source-buffer plus
`size_of::<DecodeReader<R>>()` allowance. First-record inspection retains its
64 KiB source-buffer allowance; decoder inline arrays, configuration clones and
codec internals remain outside that inspection envelope. These are the prior
working-allocation scopes, not a complete runtime/RSS bound.

The opt-in `experimental-direct-decode` path can decode directly into an already
admitted caller buffer when it has at least the existing 32 KiB decoded-output
capacity and no buffered decoded bytes remain. It supplies exactly 32 KiB to the
same pinned strict decoder, preserving its BOM, malformed-input and incremental
state handling. Small reads and pending buffered bytes retain the original path.
The inline decoder arrays, source buffer, record owners and grant lifetimes are
unchanged; this removes a byte copy without releasing any capacity grant early.

Header transfer pre-admits retained field capacities while the parser charge is
still live, then reduces the latter to scratch. Analysis headers keep their
immutable shared controller; profiling keeps its independently owned Vec and
grant. First-row prefetch discovers profile columns without copying or moving
width validation ahead of selection/statistic setup. Inspection reads one
logical record and makes no whole-input validation claim; buffered read-ahead
is still possible.

Each session fixes its data-record representation on its first read/prefetch;
headers transfer separately. Switching representation is rejected before a
second buffer can escape the existing charge. Raw-parser construction is private
apart from test-only pre-read controls.

Record consumption keeps parser admission through the existing owned/packed
consumer handoff and reconciles returned compact capacity afterward. Sorters
and streaming chains retain their own admission-relief callbacks. The optional
profiling adapter charges other live slot capacities during refill and declares
its batch before intake, so all slots drop before their aggregate grant. Parsing,
admission and read errors, failed consumption and EOF prevent further parser
calls; source identity, full-profile serial retry, observation and publication
policy stay with callers. Native and hosted validation remain scoped to the
actual checks recorded for a build; this ownership change is not performance
evidence or a new selector/default.

## Native static status source (2026-10-28)

Native status originally moved from owned text to `&'static str`. The current
[job lifecycle owner](../crates/chopper/src/server/jobs.rs) uses a private enum
whose serde unit variants emit those same fixed literals (idle, profiling,
profiled, analyzing, ready, running, complete, cancelled or failed). Status
construction and replacement still need no heap-backed source or reservation;
request-backed text cannot become status. The shared JSON estimator handles a
unit variant exactly as its static string, preserving response preflight.

The JSON field remains a string. Response construction still admits its own
payload; denial leaves state unchanged, and the state mutex is released before
sending. Cancellation, worker completion, error formatting/fallback and literal
acknowledgements retain their existing control flow. Static status text has no
local/shared capacity edge or competing source owner to release; the existing
response and output-owner tests cover those separate admitted lifetimes.
[Validation](validation.md#native-static-status-source-2026-10-28) records native
interface coverage. Error/progress source ownership remains open. This establishes
no complete state/runtime accounting or RSS bound and changes no job schema,
defaults or execution strategy.

## Native cached output-path source owner (2026-10-28)

The native server's analyze and direct-Run transitions now copy `Job.output`
through a private admitted owner in
[`server/state_output.rs`](../crates/chopper/src/server/state_output.rs).
The existing String-copy reservation helper admits the borrowed source length
before allocation and reconciles actual String capacity before copying bytes.
The state-owned String drops before its independent shared-process grant.
Request decoding, prepared configuration and HTTP response payload grants remain
separate owners; none can substitute for this idle-state lifetime.

Construction completes before replacing the previous State or spawning a worker.
Denial therefore preserves cached state and launches no job. Cancellation and
worker completion retain the output path for the existing state response; state
replacement or destruction releases it. State serialization borrows `str`,
preserving the existing string/null representation, while response payloads keep
their own grants after state replacement. Old/new state output grants overlap
during successful replacement rather than briefly releasing the old allocation.

Focused native tests cover empty, short, Unicode and long paths, local/shared
capacity edges, competing independent owners and release/retry, denied state
replacement, cancellation retention, and response-reader lifetime after state
replacement. See [validation](validation.md#native-cached-output-path-ownership-2026-10-28).
This closes only the cached output String copy. State error/progress
sources (status is now static as described above), source discovery/pressure storage, parent discovery/normalization,
caller construction, carriers and native HTTP/OS/thread/runtime allocations
remain separate gaps. No schema/default/strategy changes or full RSS claim follow.

## Authoritative platform facts

Linux cgroup v2 membership appears as `0::$PATH` in `/proc/PID/cgroup`.
Controllers apply hierarchically; descendants cannot override ancestor limits.
`memory.current` measures the group and descendants, including anonymous memory,
page cache and tracked kernel allocations. Amounts are bytes. `memory.max` is a
hard limit with possible temporary overshoot and OOM handling when reclaim cannot
reduce usage. `memory.high` triggers throttling/reclaim pressure; it is not an
OOM boundary and can be exceeded. Both accept `max` for no configured limit.
Swap has separate accounting. [Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory).

`/proc/meminfo`'s `MemAvailable` estimates memory for new applications without
swapping, accounting for reclaimability and necessary reserves; it is not merely
free pages. `VmRSS` includes anonymous, file-backed and shared resident memory.
RSS counters can be asynchronous/imprecise; scanning `/proc/PID/smaps` gives a
more precise instantaneous view at greater cost. [Linux proc documentation](https://docs.kernel.org/filesystems/proc.html).

Microsoft documents `.wslconfig` memory as the amount assigned to the WSL 2 VM,
with a default of 50% of Windows memory; swap is configured separately.
Consequently guest memory observations describe the Linux VM, not Windows-wide
available application memory (inference). Do not infer Windows capacity by
doubling guest RAM: users can configure a different VM limit.
[Microsoft WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config#main-wsl-settings).

The Device Memory API reports approximate physical device memory, rounded to a
single significant bit and clamped to implementation-defined bounds for privacy.
It does not measure currently available memory or a worker/JavaScript heap budget
(inference). [W3C Device Memory specification](https://www.w3.org/TR/device-memory/).

`navigator.storage.estimate()` returns storage usage and quota estimates for the
origin's storage shelf. Usage is deliberately approximate, and quota is an
implementation-defined conservative storage capacity estimate. It is not a RAM
signal or a reservation against concurrent writes (inference).
[WHATWG Storage Standard](https://storage.spec.whatwg.org/#usage-and-quota).

## Current repository behavior

`resources.memory_mb` defaults to 256 and validates within 32–1,048,576. The name
uses `mb`, but conversion is binary MiB (`* 1024 * 1024`). Preserve that meaning.
[Resource schema](../crates/chopper-core/src/config.rs).

Each preparation/profile scan retains its own half-budget workspace, now backed
by one shared process admission ledger. Cached observations, returned profiles
and prepared snapshots keep aggregate charges through their final owners.
Transactional local/aggregate acquisition rolls back on denial. Startup Linux
proc/cgroup discovery constrains the process ceiling; native
`CHOPPER_MEMORY_LIMIT_MB` can lower it. Browser sharing covers a single WASI
instance, with a fixed 1 GiB tracked ceiling inside 2 GiB linear memory. This is
address-space policy, not discovered host capacity. Native unknown-host fallback
remains 128 MiB. See the
[implementation and boundaries](performance.md#shared-process-admission-and-linux-startup-discovery-2026-10-16).
Linux pressure is now rechecked at safe preparation/profiling/run/merge/export
boundaries, throttled to one observation per second. This is a boundary cadence,
not a background polling guarantee. Grants are serialized across observation;
releases may proceed. The policy records the charged baseline after observation
and permits net growth against half fresh additional headroom, still capped by
the startup/configured ceiling. Incomplete observations can lower admission but
cannot restore a previously reduced allowance. See the
[policy, tests and measurements](performance.md#dynamic-pressure-rechecks-at-execution-boundaries-2026-10-16).
Per-job numeric budgets still determine existing worker/algorithm thresholds.
The ledger remains incomplete and is not an RSS cap.

The native server retains prepared output state and a separate profile cache.
Any aggregate ledger must follow those owners through idle time, execution,
replacement and cancellation, including independently returned copies.
[Server lifecycle](../crates/chopper/src/server.rs). Browser workers additionally
have fixed transfer/runtime overhead and a 2 GiB WebAssembly linear-memory ceiling;
existing working budgets are not browser-process RSS limits.
[Browser constraints](browser.md#processing-and-limits).

## Job manifest construction owner (2026-10-21)

Publication's existing job-record JSON tree is now pre-admitted and retained
through its serializer. The schema is first walked by a stack-only capacity
serializer; it counts owned strings and keys, current char-string allocation,
sequence descriptors with growth overlap, and the shared conservative map-node
allowance. Checked arithmetic rejects overflow. Actual `to_value` construction
then runs under that grant, its capacity traversal is checked and reconciled,
and value destruction precedes grant release, including partial-construction and
write failure. Canonical serialized bytes stay equal to the previous `json!` form.

The estimator is private to the immutable, repeatable borrowed `JobRecord`
schema. The current `Job`, `Analysis`, nested derived types and JSON diagnostics
use supported forms. Custom display serialization, externally tagged data enums
and non-string map keys fail before constructing a tree. Schema or serializer
changes must update/revalidate the estimator; it does not account arbitrary
stateful/user-defined serialization, preserve-order maps, arbitrary-precision/raw
JSON representations or serializer-owned temporary buffers. Current char-string
admission uses the supported toolchain's eight-byte minimum `Vec<u8>` capacity;
toolchain/representation changes require re-auditing that assumption too.

The owner shares the job's existing local/process workspace and overlaps source
metadata and writer buffers. Its source `Job`/`Analysis` allocations, other
lineage/path/response allocations, codecs and runtime storage remain independent
coverage gaps. Conservative envelopes are working-allocation accounting, not RSS.
See [contracts and validation](performance.md#job-manifest-tree-construction-admission-2026-10-21).

## Output planning lineage clones (2026-10-21)

`PlanWriter` now charges the `Group` clone retained in an active output chunk,
and materialized-dataset output planning independently charges its temporary
output-group clone. Admission precedes cloning; the source group's conservative
JSON capacity envelope bounds known-length vector/string clones and full map
nodes. The actual clone envelope is checked and retained after construction.
Scalar counter/offset changes do not grow lineage; any future lineage mutation
needs separate admission. No parse or serialization scratch is allocated by the
clone seam.

Each value drops before its grant. Chunk ownership survives rollover and catalog
serialization; the materialized output group retains its grant through `end()`,
including named empty outputs and failure. Shared source/catalog owners remain
independent. A denied chunk open does not increment its index or emit a prefix,
so release/retry before emission is safe. Other failure/cancellation paths keep
their existing terminal semantics. See [contracts and evidence](performance.md#output-planning-lineage-clone-ownership-2026-10-21).

This boundary depends on the existing JSON-capacity representation assumptions
and supported standard `Clone` implementations; changing map representation or
adding allocating fields to `Group` requires re-auditing both the envelope and
`JsonCapacity`. Original lineage creation, other clones/growth, job-manifest JSON,
codec/error and native/browser runtime storage remain outside this slice. Spare
source capacity can make construction admission conservative. No RSS or speedup
guarantee follows.

## Publication batch and name owners (2026-10-21)

Publication now pre-admits a vector of task slots containing both decoded chunk
owners and optional results. Native workers fill the preallocated slots in place;
WASI uses serial iteration. No separate result vector is collected. The vector's
grant survives ordered draining and failed collection until the actual allocation
drops, and remaining decoded/result owners are destroyed before that grant.
The existing concurrency and ZIP temporary-space policies are unchanged.

Output names independently own their grants through completion, ZIP assembly and
manifest serialization. Construction reserves a 214-byte final string plus a
32-byte numeric-label workspace, then reconciles reported capacities and releases
scratch. The bound follows the existing 180-byte UTF-8 descriptive prefix, hyphen,
`part-`, maximal u64 suffix, `.csv` and longest compression extension. Formatting
into already-admitted strings preserves the existing naming rules. On current
native/WASI targets, numeric labels fit 32 bytes. Re-audit this bound when changing
the naming format or supported integer widths.

The [shared contracts and validation](performance.md#publication-batch-descriptors-and-output-name-ownership-2026-10-21)
cover capacity edges, typed denial/retry, concurrent owners, real task failures,
ordered drain lifetimes and cleanup. Temporary joined paths, job-manifest JSON,
other lineage clones, codec/error payloads and runtime/thread storage remain
outside this slice. It establishes working-allocation ownership, not an RSS cap
or a throughput improvement.

## Native inspection response payload owner (2026-10-21)

The native column/sniff success response now serializes through an independently
charged payload, sharing the returned inspection's local and process workspace.
An allocation-free counting pass measures escaped JSON; exact vector admission
precedes allocation, reported capacity is reconciled, and the second pass writes
to a fixed slice. Immutable inspection data makes the passes consistent. Tree
and body charges overlap during serialization; the HTTP body reader can outlive
the tree and retains its grant until destruction, including EOF or send failure.
The owner stores payload before reservation to preserve destruction order.

This covers the two inspection success payloads only. Error JSON, other native
responses, tiny_http headers/framing and socket/runtime/thread allocations remain
uncovered. Denied body admission returns the existing 400 error response rather
than allocating an uncharged success body. No RSS or throughput guarantee follows.
See [contracts and validation](performance.md#native-inspection-http-payload-admission-2026-10-21).

## Temporary construction ownership audit (2026-10-21)

This source audit supports the allocation-coverage item in
[historical TODO](../TODO.md#resource-correctness). It distinguishes retained directory
paths from opaque constructor allocations; it is not an executed acceptance
result or performance measurement.

The [lockfile](../Cargo.lock) pins `tempfile` 3.27.0, package checksum
`32497e9a4c7b38532efcdebeef879707aa9f794296a4f0244f6f69e9bc8574bd`.
The inspected registry source files have these SHA-256 identities:

| File under `tempfile-3.27.0` | SHA-256 |
| --- | --- |
| `src/util.rs` | `f70d9ecc5a778a01c783dd84baaa6ab81ab48a6faac0693cfec124ee42db421b` |
| `src/file/mod.rs` | `b6752b11a575021eeab87cb8b5b6914aaff86ad8d49a9678a8f4c95b5a21ef81` |
| `src/dir/mod.rs` | `d144325a6528a9a6e7c78a42e0eec42ee401c3b834ef5851376323725756f219` |
| `src/error.rs` | `cc7d8eace0fff11cb342158d2885d5637bfb14b24ef30755e808554772039c5f` |

`util::tmpname` allocates an `OsString` for prefix, random characters and suffix.
`create_helper` joins that name to the parent, with additional current-directory
discovery and joins when the parent is relative. The joined `PathBuf` becomes a
boxed path on successful named-file or directory creation. Naming lengths are
predictable with an explicit random-character count; private join/growth/shrink
capacities are not exposed by these APIs. Filesystem calls also have platform
conversion and runtime allocations outside this ownership seam. A multiple of
the final path length alone does not establish complete constructor admission.

`Builder::make_in` receives the generated path after name/join allocation, so its
callback cannot acquire a grant before those allocations. `create_named` and
`IoResultExt::with_err_path` can clone a path into a returned `io::Error`; a
constructor-only grant released on return would not follow that error's lifetime.
These cases need controlled construction or a dependency seam before claiming
complete coverage.

The bounded next owner is the successful context/staging directory's boxed
path, reserved before construction and held through final directory ownership.
Its charge belongs in the existing local/shared workspace, with a separate
directory-path diagnostic term. A live context therefore retains a nonzero
baseline even after all intermediate files are dropped. Exact verifier equations
must include this owner; they must still reject unexplained residual bytes.

`TempDir::keep` transfers the existing boxed path into a `PathBuf` and disarms
implicit removal. `TempDir::close` uses `std::fs::remove_dir_all`, then decorates
failure with a separate owned path. Chopper can use the same deletion primitive
on the transferred original path and report errors while that path and grant
remain alive, avoiding its previous cleanup-path clone. Native publication must
still disarm cleanup only after rename; WASI internal finalization remains
distinct from the JavaScript completion-marker protocol.

Parent discovery/normalization, constructor scratch, library error paths,
filesystem conversion, recursive-delete internals and runtime overhead remain
separate coverage gaps. The dependency identities above pin this audit; a
dependency change needs a fresh source check.

The [retained directory-path pass](performance.md#retained-job-and-staging-directory-path-ownership-2026-10-21)
implements and validates this successful boxed-path owner and original-path
cleanup seam. It does not close the separate construction gaps above.

## ZIP input metadata ownership audit (2026-10-21)

This is a source inspection supporting the allocation-coverage item in
[historical TODO](../TODO.md#resource-correctness), not an executed regression or benchmark.
The inspected dependency is the registry `zip` **2.4.2** pinned in
[`Cargo.lock`](../Cargo.lock), package checksum
`fabe6324e908f85a1c52063ce7aa26b68dcb7eb6dbc83a2d148403c9bc3eba50`.
The following line references name files in that installed crate's source, not
Chopper files. SHA-256 of the inspected `src/read.rs` is
`7ae4d97dbcef72484f3db6d9db7e56f28af1811b0d9e59152e495578b039ce1f`;
`src/spec.rs` is
`223b49c70b9853b129e8a2513ad3427f7f8dff55a49da21a0fd233bf7da76782`.
These identities pin this audit; a dependency update needs a fresh inspection.

Chopper's [`check_zip_directory` and `with_input`](../crates/chopper/src/engine.rs)
currently reserve the ZIP preflight tail and fixed source buffer. The existing
`directory_length + 512 * entry_count` check constrains eligibility against one
eighth of the job's configured memory. It neither acquires a shared decoded
metadata reservation nor proves the downstream library's allocation bound.
The fixed-buffer coverage and exclusions are recorded in the
[input-adapter evidence](performance.md#input-adapter-capacity-and-windows-profile-invalidation-2026-10-20).

The inspected ownership boundary is `ZipArchive`'s private `Arc<Shared>`:
`src/read.rs:49–84` stores an `IndexMap<Box<str>, ZipFileData>` and archive comments.
Central decoding first allocates a `Vec<ZipFileData>` (`src/read.rs:685–726`), then
builds the map while the vector's backing allocation still exists, cloning each
decoded name for its map key (`src/read.rs:71–76`). Each entry can retain raw and
decoded names, decoded comments, an `Arc<Vec<u8>>` extra-data buffer and parsed
extra fields (`src/read.rs:1310–1353`; `src/types.rs:434–487`). UTF-8 replacement
or CP437 conversion can expand text; names also appear in both the entry and
map key. Extra-field processing can retain overlapping original/replacement
buffers and grow a parsed timestamp/NTFS vector (`src/read.rs:1375–1501`).
Private map/vector capacities are not exposed by the public archive API, so a
preallocation reservation would require an explicitly conservative,
version-audited allowance rather than an exact retained-capacity measurement.

Two parser-selection boundaries also need to be resolved before that allowance
can be called sufficient. Chopper selects a final EOCD whose comment ends at EOF,
but `ZipArchive::get_metadata` retries earlier EOCD candidates if central parsing
fails (`src/read.rs:650–682`); the library's EOCD search permits trailing data
(`src/spec.rs:620–646`). A grant calculated for Chopper's selected candidate
therefore does not by itself bound whichever directory the library eventually
accepts. Central parsing iterates the selected entry count, rather than bounding
reads by the EOCD directory-length field (`src/read.rs:685–726`). ZIP64 additionally
decodes an extensible data sector of `record_size - 44` bytes
(`src/spec.rs:501–536`), independently of the central-directory byte count used by
Chopper's current check. The library checks that this record fits before its
locator; that file-extent check is distinct from a memory grant. These are
inspected accounting gaps, not demonstrated
exploits or observations of an allocation failure.

A compatible implementation must establish that the preflight and archive reader
select the same bounded metadata extents, or conservatively admit every extent
that fallback can select. It must include both ZIP64 extension and archive-comment
allocations, verify count/length/offset arithmetic and actual central records,
cover decoded-text expansion and temporary construction overlap, and acquire
local/shared grants before the corresponding allocations. The grant must follow
the actual archive and borrowed member through EOF, consumer failure and final
drop. Simply retaining the current eligibility expression would leave these
proof obligations unresolved. Replacing the parser or restricting accepted
archive forms would also require explicit compatibility evidence; this audit
authorizes neither change.

Useful shared native/WASI contracts would exercise many small entries, long
UTF-8/CP437 names and comments, repeated supported extra fields, ZIP64 extensible
metadata, inconsistent directory counts/lengths, and a malformed final EOCD with
an earlier candidate. Admission controls should verify typed shared denial before
the consumer runs, a held competing owner, release and retry of the immutable
source, retained capacity at EOF, and error/cancellation cleanup on real storage.
Those ZIP-directory regressions have **not** been run for this audit. Existing
input-adapter contracts cover the narrower fixed-buffer boundary. Codec heaps,
allocator retention and process/runtime memory remain distinct; no RSS cap or
allocation-coverage closure follows from this inspection.

The later [executable ZIP metadata probes](performance.md#zip-metadata-selection-and-allocation-probes-2026-10-21)
confirm the earlier-directory fallback, underreported central length and separate
ZIP64 extension cases on pinned native and browser/WASI builds. The ordinary
many-entry eligibility rejection becomes acceptance with a malformed final EOCD;
the ZIP64 fixture retains an independent 8 MiB metadata sector while the native
scan ledger remains about 119 KiB. These are diagnostic observations, not a
metadata grant or RSS-cap result. The broad extra-field/CP437 and ownership
denial/release/lifetime controls listed above remain unexecuted. A compatible
implementation needs a parser allocation/selection seam or an equivalent proved
bound; the existing EOCD expression alone is demonstrably insufficient.

## ZIP parser admission implementation (2026-10-21)

The preceding source audit and diagnostic observations describe the unpatched
registry build. The current implementation uses a [local zip 2.4.2 patch](../vendor/zip-2.4.2/CHOPPER.md)
selected by the root Cargo patch and excluded from the workspace. The
[source inventory audit](evidence-originals.md#sha256-8def2d8ad5ffee8969eb5cb2f9edb75336e5d0461eb3c9e743f253097cda4c00 "Original: docs/benchmarks/zip-metadata-owner-source-audit-2026-10-21.json")
records every retained upstream file, the three modified upstream modules, the
new metadata module and the exact indexmap/hashbrown allocation sources.
Original constructors retain their behavior; the private Chopper adapter uses
`new_with_metadata_budget` and holds its separate grant until archive and borrowed
member destruction. The final-EOCD eligibility check remains a separate policy.

The callback charges before archive comments, ZIP64 extensions, actual entry
vector allocation/growth and variable central-entry decoding. A 128 KiB fixed
constructor allowance covers search/control and malformed-extra scratch;
descriptor capacity receives `4 * size_of::<ZipFileData>() + 256` per slot.
Name/comment bytes receive 16x, and extras receive
`ceil(8 * size_of::<ExtraField>() / 5) + 16` per serialized byte. The patch document
explains the pinned representation and overlap bounds. These deliberately
conservative envelopes are not measured allocator capacities or RSS limits.
Failed candidate objects drop before their allowance shrinks. A uniquely typed
callback error aborts every fallback loop, preserving the original local/shared
admission error at the Chopper boundary. An admission failure cannot cause the
parser to accept an earlier candidate instead.

[Executed contracts and validation](performance.md#zip-metadata-parser-admission-and-owner-lifetimes-2026-10-21)
now cover the twelve forms, ninety denial checkpoints and ownership controls
proposed above, including failed-candidate allowance release. Codec heaps,
inspection/result allocations and native runtime overhead remain separate work.

## Returned inspection JSON owner (2026-10-21)

Column and sniff APIs previously returned a bare `serde_json::Value` after their
parser/sample grants dropped. They now return the immutable serializable
[`Inspection`](../crates/chopper/src/engine/inspection_result.rs) owner. The tree
and its independent reservation move together; field drop order releases the tree
before its grant. Borrowed JSON access remains available, but caller-created
clones are independent allocations. Native HTTP and browser JSON schemas remain
unchanged. Rust callers now receive `Inspection` rather than an unowned `Value`.

Admission occurs before `json!` constructs either fixed schema. Up to sixteen
object fields receive sixteen `(String + Value + usize)` widths each, using the
existing decoded-catalog conservative BTreeMap-node allowance, plus 512 bytes for
fixed keys/scalar formatting. Column header arrays additionally receive one
`Value` width per item and their UTF-8 string lengths. Serde's known-length array
and string serializers allocate those lengths; parser/sample owners remain
separately charged during construction overlap. Sniff settings have eight fixed
fields, bounded detected encoding/line-ending names and char scalars; its note is
charged by byte length. This is a version/source-dependent working allowance,
not exact heap or RSS. Schema, serde features/map representation or allocation
behavior changes require re-auditing this bound.

The native server keeps the result through serialization and response consumption;
its serialized response `Vec` remains a separate gap. The WASI reporter accepts
serializable owners and writes JSON directly to stdout without first cloning a
Value or creating a full serialized String. Serializer/runtime buffers remain
outside this slice. [Executed controls](performance.md#returned-inspection-json-admission-and-serialization-lifetime-2026-10-21)
cover construction/retention and failure lifetimes rather than a throughput claim.

## Proposed native discovery and policy

These are engineering proposals, not kernel guarantees or calibrated constants:

1. Read bounded `/proc/meminfo`, membership and mount information; resolve the
   actual cgroup2 mount/root rather than concatenating a fixed path blindly.
   Walk accessible ancestors. Record unsupported v1, absent controllers,
   inaccessible ancestors, malformed values and transient migration as unknown
   discovery states. Never treat an unreadable limit as zero or unlimited proof.
2. For each finite ancestor limit, calculate its own saturating
   `limit - memory.current`. Take the minimum across ancestors and host
   `MemAvailable`. Parent current includes sibling use: subtracting only leaf
   current from the smallest ancestor limit overstates headroom. Treat a finite
   high threshold as a conservative pressure boundary, separately labeled from
   the hard maximum. Do not add swap to a throughput-oriented RAM budget.
3. This computes instantaneous *additional* headroom, not the entire future
   process allowance. Existing allocations are already reflected in host/cgroup
   use. A separate ledger tracks Chopper's committed reservations. Do not subtract
   all existing reservations again from observed free headroom, or interpret them as resident RAM: reservation capacity, resident bytes and
   unallocated promises are different quantities. The implemented pressure rule
   uses held capacity as the baseline for *net new charged growth*, plus half
   observed additional headroom, under the unchanged aggregate ceiling. This
   engineered allowance is not a physical-memory grant: existing reservations
   can still include uncommitted pages, and allocator retention is not free RAM.
   Keep both observations and capacity totals visible; neither is an RSS bound.
4. Reserve an empirically justified runtime/allocator margin, retain a conservative
   fallback, and report discovery inputs, timestamps and chosen effective limits.
   Unknown capacity is not permission to increase the historical default. A
   computed budget below the minimum feasible job must defer/fail clearly rather
   than round upward beyond discovered capacity.
5. Recheck pressure at stage/run boundaries. Lower future grants or spill eligible
   rows; do not revoke live reservations or change seeded algorithms. A host
   observation cannot guarantee that another process will not allocate afterward.

## Explicit settings and shared reservations

Sorter retention now uses the smaller of the existing job-quarter target and
half the shared admission ceiling observed at sorter construction. A 512 MiB
numeric job under the native Windows 128 MiB fallback therefore retains at most
64 MiB for sort rows, leaving headroom for separately admitted spill I/O and
construction. The observation clones no diagnostic payload and grants nothing;
local/shared acquire, growth overlap, release and pressure rules remain binding.
The hosted ledger is now 1 GiB, so a 2048 MiB job can target up to 512 MiB
of sort rows; smaller requests retain their existing quarter-budget target.
The numeric job budget and reported memory stay exact. The Sorter scalar target
is covered by its existing `size_of::<Self>()` row-buffer overhead accounting.
This is feasibility sizing, not an Auto cost selector, a larger pool, a revoked
grant or an RSS guarantee. Native/WASI contracts compare complete seeded CSVs,
fields, IDs, quotas and final owner release under a smaller fixed shared pool.

Preserve existing v1 numeric `memory_mb` as an explicit per-job working ceiling
with the existing unit and algorithm thresholds. Automatic host selection needs
an explicit, coordinated Rust/UI policy field and documented precedence; omission
of a new field must not silently turn old numeric jobs into automatic jobs.

A process admission ceiling now coexists with per-job ceilings. State which limit
denied a reservation; an explicit job request never promises the host can supply
it. Share one ledger across independent profiling/preparation contexts, caches,
returned profiles and retained prepared objects. Acquiring local and aggregate
charges must be transactional, with rollback and final-owner release. Keep
per-job diagnostics available while recording aggregate current/peak usage.

Ledger totals measure charged capacities and conversion peaks. RSS additionally
reflects runtime/allocator behavior, stacks, libraries and mappings; cgroup usage
also includes charged file cache and other processes. Report all separately.
Completing the shared ledger cannot by itself justify an RSS-cap claim.

## WSL-measurable evidence and acceptance

A read-only observation in this session found kernel
`6.18.54.1-microsoft-standard-WSL2`, membership `0::/non-systemd`, and a cgroup2 mount
at `/sys/fs/cgroup`. The leaf's `memory.max` and `memory.high` were both `max`;
`memory.current` was 1,236,123,648 bytes. `/proc/meminfo` reported `MemTotal`
15,918,072 KiB, `MemAvailable` 14,285,120 KiB and `SwapTotal` 4,194,304 KiB.
These changing observations are discovery smoke evidence, not controlled pressure
tests, hardware capacity certification or benchmark results.

Use parser fixtures for nested mounts/ancestors, finite/`max` limits, missing files,
overflow, parent sibling pressure and unknown-platform fallback. Use a controlled
delegated cgroup only if available; lack of writable delegation must be recorded,
not bypassed. Test concurrent profiling/preparation, retained cache/snapshot
lifetimes, failed acquisition rollback and cancellation. Alternate complete jobs
under explicit and opt-in automatic policies, reporting chosen limits, ledger
peaks, RSS/cgroup observations, spill/I/O/time and exact output/metadata parity.

For Chromium/WASI, test absent/coarse device-memory hints, quota changes and
concurrent workspace pressure while preserving current explicit budget semantics.
Keep storage grants separate from memory grants. Broader browser/device and
Windows-host pressure behavior remains outside one WSL measurement.

## Retained publication path owners (2026-10-21)

Publication now owns joined `PathBuf` capacity for the manifest, ZIP archive and
individual CSV files. A single filename component is validated without allocation;
checked parent encoded length plus separator and filename bytes supplies the
initial admission. `try_reserve_exact` precedes `PathBuf::push`, and reported
capacity is reconciled before returning the owner. Path construction preserves
`Path::join` behavior, including Windows prefixes. The path drops before its
reservation, including when file creation or metadata lookup fails.

Each CSV task reuses its admitted path for creation and metadata lookup. The
manifest path remains charged through its later ZIP read; the archive path only
needs to live through archive creation. These lifetimes differ from open file
handles, which do not retain these caller path buffers. Independent active paths
retain independent grants. Additional grants can reject a tight job that formerly
left these allocations uncharged.

The [shared native/WASI controls](performance.md#retained-publication-path-capacity-ownership-2026-10-21)
cover Unicode/separator parity, capacity edges, typed denial/retry, independent
owners, file errors and all four publication compression modes. Destination
absolute-path discovery, opaque standard-library normalization scratch (including
Windows verbatim-path push internals), OS path conversion and other temporary-file
constructor/runtime storage remain outside this retained-capacity slice. The
reconciliation does not establish complete transient allocation admission or an
RSS cap.

## Retained absolute publication destination

The [destination owner](../crates/chopper/src/output/destination.rs) moves the
`PathBuf` returned by `std::path::absolute` into private storage and charges
its actual capacity through the Context's local and shared reservation. It does
this before inspecting the destination or creating staging. Snapshot publication
holds the owner through commit, and direct publication carries it in its
publication object through final use or abandonment. The path drops before
its grant. A failed admission returns the typed memory error before filesystem
inspection or staging. Already-requested cancellation takes precedence over
admission.

Native preflight's transient resolution, absolute-path construction, opaque
standard-library scratch and OS conversion retain their existing boundaries.
Joined file paths and the staging directory remain separate owners. The
[shared native/WASI resource controls](../crates/chopper/src/output/destination/resource_contracts.rs)
exercise capacity edges, overlapping owners, denial and staging cleanup.

## Controlled temporary construction and reopen (2026-10-22)

[`storage/temp_path.rs`](../crates/chopper/src/storage/temp_path.rs) now owns
temporary file and job/staging-directory name/path construction. It receives an
absolute parent, computes checked final encoded length, admits one `PathBuf`
before allocation and reconciles capacity before writing into it. Prefix and six
random alphanumeric bytes are appended directly; randomness uses inline scratch
and rejection sampling. A possible capacity-shrinking box conversion admits
old/new overlap before filesystem creation. The successful boxed path transfers
into the existing TempPath or directory owner without a name/join allocation.

Creation remains atomic (`create_new`/`create_dir`). Unix file mode 0600 and
Windows temporary attributes remain explicit. Collisions reuse the admitted
buffer, retry at most 128 times and never install a cleanup guard for an existing
name. Failure returns the OS error without tempfile's owned error-path decoration.
`JobDirectory::new` still accepts externally owned TempDir values; native
publication disarms cleanup only after rename, independently of WASI finalization.

Reopening ports the pinned tempfile platform operation while omitting its
`with_err_path` wrapper: Windows `ReOpenFile` selects the original handle; Unix
and WASI open by name and compare device/inode through rustix. Returned handles
have independent offsets. Identity mismatch uses a bare NotFound error instead
of constructing a path-bearing message. This removes the error-path copy rather
than retaining speculative error capacity on every successful reader open.
Existing reader admission equations remain intact. `rustix` and `windows-sys`
are direct target dependencies, using versions already pinned in the lockfile.

The [source audit](evidence-originals.md#sha256-b903cb030b315b07f7f0b9b036c06409754e457b84f0c1926ff9fc9b537c85a6 "Original: docs/benchmarks/temporary-construction-source-audit-2026-10-22.json")
pins the upstream constructor, platform reopen and error-wrapper sources. Review
these identity/offset checks and path transfers when changing the implementation
or its dependencies. The [validation interpretation](performance.md#controlled-temporary-construction-and-identity-preserving-reopen-2026-10-22)
records shared-capacity, collision and cleanup controls and rejected approaches.
Parent discovery/absolutization, OS path conversion/syscall internals, allocator
and runtime/error-formatting storage, recursive deletion, codec heaps and native
stacks remain separate. This closes the controlled name/path boundary, not all
temporary/runtime allocations or an RSS cap.


## Gzip input codec admission (2026-10-22)

[`engine/input_gzip.rs`](../crates/chopper/src/engine/input_gzip.rs) retains a
separate codec reservation around the existing `read::MultiGzDecoder`. Admission
precedes construction because flate2 parses the first header in `new`. The owner
retains the grant through EOF, consumer failure and decoder destruction, while
Chopper's 8 KiB input buffer keeps its independent reservation. Pipeline order,
CSV bytes and the existing gzip parser/error behavior are unchanged.

The [source audit](evidence-originals.md#sha256-71ce07e0e9b0fdba903f4808351fcb77305a97108947803626103aea91aa267d "Original: docs/benchmarks/gzip-codec-source-audit-2026-10-22.json") pins flate2
1.1.10 and miniz_oxide 0.9.1 and records the selected miniz feature tree. Cargo
uses exact direct versions, including miniz for its public inflater layout. The
envelope contains the outer boxed reader size, one boxed `InflateState` (nested
storage is inline), flate2's fixed 32 KiB read buffer and 512 KiB for gzip header
storage. Extra is bounded by its u16 length; filename/comment each reject a
non-NUL byte after 65,535 bytes. The header envelope covers two maximum retained
headers, old/new vector growth overlap and fixed boxed header CRC storage; the
actual member reset drops the old header before parsing the next and reuses the
inflater. This is conservative requested working storage, excluding allocator
usable-size overhead. Re-audit version or backend changes rather than assuming
these bounds hold for other implementations.

Shared native/WASI contracts exercise local/shared exact edges, maximum extra,
filename and comment fields with header CRC across concatenated members,
admission before the first header read, retained ownership after EOF, early and
partial-read consumer failures, and malformed header/trailer checksums,
truncation, reserved flags and overlong names. The existing input-adapter suite
also retains a competing shared owner, verifies typed denial and retries after
release. Fixture construction/decoded comparison buffers belong to the test
harness, outside job accounting. See the [validation interpretation](performance.md#gzip-input-codec-admission-2026-10-22).

Output deflate/gzip codecs, selected deflated ZIP members, Zstandard contexts,
source/job configuration, parent-path discovery, native runtime/stacks and
error/allocator/OS internals remain separate allocation work. No complete RSS
cap, new default, performance or broader device/scale claim follows.


## ZIP member and output deflate codec admission (2026-10-22)

ZIP directory metadata and its source buffer have independent owners. The
[`input_zip`](../crates/chopper/src/engine/input_zip.rs) adapter now declares a
third grant before archive construction, then admits it after metadata parsing
and before the first `by_index` lookup. The grant outlives both the selected
borrowed member and archive. Only one member reader exists at a time. The
[pinned vendor seam](../vendor/zip-2.4.2/CHOPPER.md) exposes its 8 KiB buffer,
boxed CRC/decompressor layout and caller's boxed `ZipFile` size; Chopper adds the
public miniz inflater layout. The allowance is conservative for Stored-only
archives, which still construct buffered/boxed reader containers. It covers name
lookup and selected-member lifetimes without changing lookup/error ordering or
directory fallback. Unrelated unsupported/encrypted members still fail selection.
The ASCII case-insensitive CSV suffix check now borrows name bytes instead of
allocating a lowercase copy.

[`output/deflate.rs`](../crates/chopper/src/output/deflate.rs) admits the pinned
miniz/flate2 encoder before construction and owns the grant alongside the codec.
Field order keeps it through implicit drop-time compression. Explicit `finish`
keeps it through success, returned-writer extraction and any error-time codec
destruction. Gzip CSV chunks, ZIP compressed CSV chunks and the separately
compressed ZIP manifest use this owner. Each publication worker admits its own
codec; publication I/O buffers and temporary compressed files keep their own
reservations. Output compression settings, bytes, CSV caps and publication rules
remain unchanged.

The [source audit](evidence-originals.md#sha256-e33cd3bde26727b7b9bc22c5f9c3a4b89cc2a917964f2401ad7f220ef02cfd50 "Original: docs/benchmarks/zip-output-codec-source-audit-2026-10-22.json")
records both dependency feature trees and source hashes. Output allowance adds
`size_of::<CompressorOxide>()`, the boxed Huffman tables, LocalBuf, dictionary and
two hash-chain arrays, wasm32's additional boxed LZ code array, flate2's fixed
32 KiB output Vec and sixteen bytes for the metadata-free ten-byte gzip header.
The pinned writer never grows that output Vec. These are requested working
allocations; transient native stack construction and allocator usable-size
storage remain outside the ledger. Re-audit all nested ownership on dependency,
backend, feature or builder-setting changes. The separate
[gzip input header envelope](#gzip-input-codec-admission-2026-10-22) remains in use.

Shared native/WASI controls cover Stored, Deflated, Unicode/mixed-case names,
mixed-member lookup, explicit selection, empty data and directory exclusion;
local/shared edges, competitor denial/release/retry, EOF ownership, partial
consumer failure, malformed compression/CRC, selection failures and public
profiling cancellation. Output controls cover both formats at local/shared
edges, factory denial, concurrent owners, exact legacy compressed bytes for
empty/Unicode/incompressible payloads, explicit finish, implicit Drop, write and
finish failure. Destination callbacks assert that the codec grant is still live.
These fixtures allocate their comparison/input/destination buffers outside job
accounting. See the [validation interpretation](performance.md#zip-member-and-output-deflate-codec-admission-2026-10-22).

ZIP metadata controls separately record parser-requested peak and the whole-job
ledger peak. The failed-large-directory candidate must still release its extra
metadata before the accepted small candidate is retained. A later live codec
allowance can dominate the whole-job peak; it must not be mistaken for retained
failed-candidate metadata. Whole-job local/shared edge checks remain in place.
Zstandard contexts, parent discovery, source/job trees, native runtime/stacks and
error/OS/allocator internals remain separate. This does not establish a complete
RSS cap or change defaults.


## Zstandard output context admission (2026-10-23)

[`output/zstandard.rs`](https://github.com/jsmatfess/chopper/blob/87df5c047a05eafc0e886da8524a69494329925d/crates/chopper/src/output/zstandard.rs) admits the
single-threaded, dictionary-free Zstandard output context before construction.
It preserves level 3, window log 21, checksum enabled and unknown source size.
A consuming `finish` retains the grant through codec destruction on success or
failure; field order also retains it through abandonment. The existing zstd-rs
behavior is preserved: dropping an encoder does not implicitly finish its frame.
Publication buffers, compressed output files and source readers remain separate
owners. The previous publication concurrency ceiling is unchanged.

The [pinned-source audit](evidence-originals.md#sha256-979b30c210a43fe9392008bc394f35619cb53727612848e5eceef9f75147855d "Original: docs/benchmarks/zstandard-output-source-audit-2026-10-23.json")
records exact zstd/zstd-safe/zstd-sys versions and Zstandard 1.5.7 sources.
Admission calls `ZSTD_getCParams(3, 0, 0)`, sets window log 21 and uses
`ZSTD_estimateCStreamSize_usingCParams`, then adds zstd-rs's fixed 32 KiB output
Vec with checked arithmetic. The pure size/status calls receive no pointers or
contexts; a runtime version check precedes the unstable estimation API. The
estimator covers context, buffered streaming workspace and both row-matchfinder
choices. The pinned dynamic resize frees its prior workspace before allocating
a replacement. No dictionary, internal workers, long-distance matching or
external sequence producer is configured. These assumptions must be re-audited
when changing parameters, features or dependency versions.

The upstream `experimental` Cargo feature exposes static-linking-only estimator
declarations. In the audited build script it affects binding exposure; this
change sets no experimental compression parameter and promotes no execution
experiment. Exact direct versions retain the audited Rust/C ownership chain.
Requested C context/workspace bytes and the Rust output Vec are included;
allocator usable-size overhead, stack/runtime and destination storage are not.

Shared native/WASI contracts exercise local/shared edges, retained concurrent
owners and release/retry. Twelve cases cover empty, Unicode and a 3 MiB-plus
incompressible stream with explicit finish, abandonment, destination write and
finish failure. Destination callbacks assert that grants remain live; successful
finish and abandonment compare exact bytes against the prior encoder recipe.
Independent `CCtx::sizeof` probes sample context storage during streaming and
finalization and require it to fit the estimator. Fixture input/comparison and
collector storage is outside job accounting. See the
[validation interpretation](performance.md#zstandard-output-context-admission-2026-10-23).

Input remains a separate open boundary. The modern DStream estimator includes
modern buffers, whose resize frees before replacement. However, the default
build also enables legacy decompression. `ZSTD_decompressStream` can dispatch
legacy frames following a modern frame, and `ZSTD_initLegacyStream` creates
version 0.4-0.7 contexts through separate ZBUFF constructors. Those allocations
are outside the modern estimate and do not use the parent context's custom
allocator. A complete input owner must cover these lifetimes while preserving
supported behavior; applying the modern estimate alone or silently disabling
legacy support would not close that requirement. The source audit records this
next implementation constraint without claiming full input coverage.


## Analysis diagnostic snapshot ownership (2026-10-23)

`Analysis.diagnostics` is an immutable `Diagnostics` owner. Nonallocating borrowed
views expose the existing context schema, process-memory observations and bounded
retained-parent audit. They do not clone discovery strings or construct nested
JSON before admission. The shared preflight now lives in
[`storage/json_estimate.rs`](../crates/chopper/src/storage/json_estimate.rs), with
the job-manifest path retaining a forwarding module. It supports only the audited
borrowed Serialize forms, not arbitrary serializers that allocate or mutate their
shape during a pass. Existing BTree entry and sequence-growth allowances are
working-allocation bounds; default serde_json features use BTree maps and inline
numbers. Dependency/backend/Serialize changes require re-auditing those assumptions.

A visit holds the audit lock before the process-pressure lock and keeps borrowed
record/observation data stable through preflight and construction. No reservation
operation runs inside that visit: it returns a required allowance, releases both
locks, then admission occurs. A fresh visit re-estimates the current data before
allocating; a larger source requests a larger grant and repeats. Cancellation is
checked between visits. This monotonic recheck handles new audit records or
changed observation strings without trusting a stale estimate or constructing a
partial unadmitted tree. Numeric counter changes do not alter capacity.

After construction, actual retained JSON capacity replaces the construction
allowance. Shared-controller admission precedes its allocation. Private unique
access then patches existing numeric slots without allocating: workspace/process
reserved and peak counts reflect reconciliation/controller admission, and
`analysis_diagnostics_reserved_bytes` reports this owner's final grant. These are
snapshot counts, not live metrics after later owners drop. Analysis and independent
Diagnostics clones share the tree/grant; final destruction frees the Arc block
and JSON before releasing admission, including concurrent native drops. Absent
default diagnostics allocate nothing. Caller construction/deserialization and
explicit Value copies remain caller allocations outside engine admission.

`Context::diagnostics()` remains an explicit caller-owned JSON-copy convenience
accessor, using the same borrowed schema without a retained engine grant. Required
engine results use the admitted capture path. The optional parsed-input `Created`
owner and its dedicated commit/cleanup path were removed after the separate E3
compact/IPC rejections on 2026-10-26. Their original implementation and tests are
[archived](history/rejected-input-snapshots-2026-10-26/README.md); this does not relax
required Analysis capture, shared JSON admission, or last-clone release ordering.
The source audit's
original vector and its grant still follow Context separately from the copied
JSON snapshot.

Tight budgets can reject previously uncharged diagnostic snapshots. The optional
audit's own collection-denial/omission contract is unchanged; final required
Analysis storage must be admitted. All heap-backed fields of engine-produced Analysis now have admitted shared
owners; its remaining fields/ExecutionSummary are inline scalars or fixed arrays.
Source host discovery/pressure-observation allocation, carrier/runtime storage
and response/error/progress framing stay open.
This is not a complete RSS cap. See the
[validation interpretation](performance.md#diagnostic-snapshot-preflight-and-shared-ownership-2026-10-23).

## Analysis warning and timing ownership (2026-10-23)

`Analysis.warnings` and `Analysis.timings` are immutable `Warnings` and `Timings`
owners. JSON stays an ordered warning array and timing object. Analysis clones
and independently cloned payloads share their allocations and admission through
serialization, discarded preparations and returned execution results. The common
shared-payload destruction rule frees the controller and vector/tree/Strings
before releasing the grant, including concurrent native final drops. Caller
construction/deserialization and explicit copies remain outside engine admission.
The snapshot diagnostics are `analysis_warnings_reserved_bytes` and
`analysis_timings_reserved_bytes`; each counts its own owner once.

Warnings retain their nine existing independent conditions, text and order.
The first selected warning admits a nine-slot vector, reconciles its actual
capacity and copies each selected String under a separate grant before insertion.
Entry denial preserves earlier warnings and the root grant; release permits
retry. Finalization admits the shared controller. A tenth warning fails the
private construction bound before growth. Adding conditions requires auditing
that bound. No selected warnings means no vector/controller. The one dynamic
file-count message formats a checked `u64` into an 80-byte stack buffer before
copying; it no longer allocates an unadmitted temporary String.

The three phase observations use a fixed stack array of static keys and scalar
values until finalization. Duplicate keys replace their value without allocating;
a fourth distinct key fails before growth. Finalization pre-admits one conservative
BTree node envelope and every copied key before insertion, then the shared
controller. The [audited Rust node layout](https://doc.rust-lang.org/src/alloc/collections/btree/node.rs.html)
has eleven key/value slots per leaf, so three entries cannot split it. The
allowance is `16 * (size_of::<String>() + size_of::<f64>() + size_of::<usize>()) + 4 * size_of::<usize>()`;
it includes alignment/edge headroom. A compile guard requires re-auditing the tree
before increasing the entry bound beyond one leaf. Standard-library layout
changes also require an audit. Partial key-copy denial drops the already-built
map before its grant. An empty builder creates no node/controller.

Phase observation points and key names stay unchanged. Timing-map finalization
occurs before recording `analysis_seconds`, preserving inclusion of timing
metadata work in that duration; warning construction remains outside it. Stack
scratch remains runtime headroom, not a heap/RSS grant. Diagnostic trees, other
Analysis metadata, response/error framing and native thread/runtime storage
remain open. See the [validation interpretation](performance.md#analysis-warning-and-timing-admission-2026-10-23).

Calculated-column jobs add preparation and traversal timings. The current
builder admits up to five entries under the same single-leaf envelope.
Traversal includes spool reads and writes or final serialization when the
calculation is terminal.

## Analysis text ownership (2026-10-23)

`Analysis.seed`, `logical_digest` and `accuracy` are immutable `AnalysisText`
owners with unchanged string serialization. A nonempty engine string admits its
copied payload before allocation and reconciles actual String capacity. The
shared controller is admitted before allocation. Empty text has no payload or
controller. The Analysis seed is admitted before requesting a CSV record;
digest text is copied from the fixed hexadecimal representation after scanning.
The source Job remains a separately admitted owner; these are actual Analysis
copies rather than a claim that their capacity belongs to the Job grant.

Analysis clones and returned execution results share each String and its grant.
The existing shared-payload last-owner rule deallocates the controller and String
before releasing admission, including concurrent native final drops. Public
text access is read-only. Caller construction/deserialization and explicit String
copies remain caller allocations. Serializer failure preserves ownership. The
`analysis_text_reserved_bytes` diagnostic and `Analysis::text_reserved_bytes()`
report the sum of these three owners; stage-statistics admission remains a
separate term. Live-owner equations retain these bytes until final destruction.

Warnings, timings, diagnostic trees, other Analysis metadata, response/error
framing and native thread/runtime overhead remain open. These are working-heap
grants, not an allocator census or complete RSS cap. See the
[validation interpretation](performance.md#analysis-text-admission-and-sharing-2026-10-23).

## Analysis stage-statistics ownership (2026-10-23)

`Analysis.stages` is an immutable `Stages` owner. Its public JSON remains an
array of the existing scalar `StageStats` records. Engine construction admits
one vector for the validated operation count before requesting the first CSV
record, including a header. The reservation reconciles the vector's actual
capacity and admits the shared controller before allocating it. Zero operations
allocate neither vector nor controller. Tight budgets can now reject stage
metadata that was previously uncharged.

Private append operations check the entire incoming length against the logical
operation count and physical capacity before insertion. They require unique
ownership through the private shared-payload helper; a live clone rejects
mutation without changing either view. Dropping the alias allows construction
to continue. No mutable slice, Arc or Weak handle escapes through the public
wrapper. There is no copy-on-write allocation or later vector growth. Existing
streaming/flexible rewrite results use fixed arrays; consecutive/nested counters
use bounded stack arrays. Those stack/runtime costs remain outside heap grants.

Cloned and returned Analysis share the payload and its grant. The common
last-owner destruction rule releases the Arc block and vector before the grant,
including concurrent native drops. Serialization and execution preserve that
ownership; caller construction/deserialization and explicit copies remain
caller allocations outside engine admission. The preparation snapshot diagnostic
is `stage_stats_reserved_bytes`. Exact live-owner equations include this term,
and still require release after the last Analysis drops.

Seed/digest strings, warnings, diagnostics, other Analysis metadata, response/
error framing and thread/runtime storage remain open. This is working-allocation
accounting, not a complete RSS cap. See the
[validation interpretation](performance.md#analysis-stage-statistics-admission-and-sharing-2026-10-23).

## Selected-column summary admission (2026-10-23)

`Analysis.column_values` is an immutable `ColumnSummaries` owner with the same
array/column/value/truncated JSON schema, with an additive optional `frequencies`
map for complete value lists (frequency extension, 2026-11-17). Analysis clones share its vector,
String keys, trees and grant using the private shared-payload helper. Explicit
summary copies and caller construction/deserialization remain caller allocations.
The snapshot diagnostic is `column_values_reserved_bytes`.

Selection retains the original lowest 64 unique resolved column indices. A fixed
64-index stack array replaces the unbounded temporary resolved vectors/set;
every requested column is still resolved, including missing/ambiguous/out-of-range
selections after the display limit. This stack scratch remains part of runtime
headroom, not a heap/RSS grant. Empty input and no selected columns create no
summary vector, tree or shared controller.

The original 100-values-per-column, 256 KiB global display budget and sticky
truncation remain unchanged. The historical display cost `value.len() + 64`
only selects visible values; it is not the heap reservation. Before each new
distinct insertion, admission covers two copied String capacities (the value set
and frequency map) and conservative node allowances for both trees:
`16 * (2 * size_of::<String>() + size_of::<u64>() + 2 * size_of::<usize>()) + 8 * size_of::<usize>()`.
Counters update existing keys during ingestion, with no extra scan. Crossing either
display limit clears frequency payloads and stops counting that column; its
existing conservative grant remains with the immutable summary until last release.
No shares are reported for incomplete lists.
Root vector capacity and the shared controller have separate admission.
Denied String/node growth leaves that entry and the display counter unchanged;
it fails preparation with typed admission rather than changing completeness
according to available memory. Earlier successful entries remain charged until
builder destruction. Grants transfer into the shared owner at finalization.

The [audited Rust node layout](https://doc.rust-lang.org/src/alloc/collections/btree/node.rs.html)
uses eleven key slots, twelve child edges and five-key minimum non-root nodes
after insertion/splitting. For insert-only sets capped at 100 keys, height is at
most two; a split allocates at most three additional nodes. At a split (at least
eleven existing keys), the old node-count bound plus these nodes fits below the
new key count. Smaller sets only allocate the initial leaf. One full-node envelope
per admitted key per tree therefore covers retained/splitting nodes. This is deliberately
conservative, not an allocator census or usable-size/RSS bound. The value-limit
compile guard requires re-auditing the envelope before raising that cap; changing
the standard-library tree implementation also requires an audit.

Seed/digest strings, stage/warning/diagnostic trees, other Analysis clones,
response/error framing and runtime storage remain open. See the
[summary validation interpretation](performance.md#selected-column-summary-admission-and-sharing-2026-10-23).

Profiling uses the same bounded frequency policy. Its map nodes are pre-admitted
with `16 * (size_of::<String>() + size_of::<u64>() + size_of::<usize>()) + 4 * size_of::<usize>()`
per key, plus separately copied String capacity. Profile copies pre-admit their
independent maps. Truncation destroys the map before releasing its corresponding
metadata reservation; profile destruction still releases payloads before grants.
The <=100-key BTree node/split reasoning above applies independently to each map.

## Analysis header and shared payload ownership (2026-10-23)

`Analysis.header` is now `Option<Header>` rather than `Option<Vec<String>>`.
Header fields and their reservation travel together through preparation,
serialization, returned execution Analysis and all Analysis/Header clones. The
previous separate `Prepared._header_buffers` grant could end before those header
values; it has been removed. Borrowing through `as_deref`, iteration, indexing
and the read-only capacity accessor remains available. Serialization still uses
an array (or null for an absent header); caller-created/deserialized headers and
explicit field copies remain caller-owned allocations.

The reserved CSV parser still admits header construction. Header reading preserves
the existing payload transfer overlap: admit retained vector/String capacity,
reduce parser ownership to scratch, then admit the shared controller before
allocation. Empty input produces no header, headerless input skips header reading,
and header-only input retains its header. Duplicate/empty/multiline/Unicode names
preserve their values and order. The `input_header_reserved_bytes` snapshot now
includes the shared controller allowance as well as retained fields.

Headers and previews use one private
[`Shared<T>` helper](../crates/chopper/src/engine/shared_analysis.rs). Its payload
places values before their grant, including controller-admission failure. Its
controller allowance is `size_of::<Payload<T>>()` plus four machine words,
covering the audited Arc counters and alignment headroom. Every clone uses
`Arc::into_inner` at final drop, retaining the existing deallocation ordering
described below. No mutable payload, Weak or underlying Arc escapes. Sharing
adds no per-clone heap allocation or duplicate capacity grant.

Stage/warning/diagnostic trees, other Analysis fields/clones,
response framing and runtime allocations remain open. See the
[header validation interpretation](performance.md#analysis-header-sharing-and-final-owner-admission-2026-10-23).

## Analysis preview ownership (2026-10-23)

`Analysis.preview` is an immutable `Preview`, serialized as the same array of
row arrays. Its builder preserves the eight-row/32 KiB decoded payload selection
rule, including skipping oversized rows and accepting later rows that fit. Each
retained row separately admits String descriptors and text capacity before
copying. The root vector reserves eight slots once. A partial copy owns its own
grant and transfers that grant into the builder only after success; failure
drops partial storage before releasing admission.

Finalization pre-admits the shared controller allowance: `size_of::<Payload<Vec<Vec<String>>>>()`
plus four machine words, covering the two Arc counters and alignment headroom
in the audited Rust implementation. Allocator usable-size and runtime metadata
remain separate. All clones share the same immutable rows and grant. Every
wrapper's Drop uses [Arc::into_inner](https://doc.rust-lang.org/std/sync/struct.Arc.html#method.into_inner),
whose exactly-one-result guarantee applies when all clones use that method,
including concurrent drops. No Weak handles or underlying Arcs escape. The
[audited implementation](https://doc.rust-lang.org/src/alloc/sync.rs.html#1237-1262)
moves out the payload and drops the implicit Weak before returning it; the Arc
block therefore deallocates before the returned rows and finally their grant
drop. Preserve this ordering when changing the wrapper or shared allocation.

Analysis cloning (including the server's cached copy) now shares preview storage
instead of allocating a second row tree. Prepared execution returns the same
owner, retaining its charge until the final Analysis/Preview clone drops. Empty
previews allocate no shared controller. The analysis snapshot records
`analysis_preview_reserved_bytes`; snapshot diagnostics are not a live ledger
after owner destruction. Caller-constructed/deserialized previews and explicit
row copies remain caller allocations. Their serialization uses the same schema.

Stage/warning/diagnostic trees, other Analysis clones,
request deserialization, response framing and runtime allocations remain open.
This closes the preview boundary, not all Analysis ownership or RSS coverage.
See the [validation interpretation](performance.md#analysis-preview-capacity-and-shared-lifetime-2026-10-23).

## Prepared configuration capacity ownership (2026-10-23)

`Prepared.job` is now a read-only `PreparedJob` owner. Admission counts retained
String capacities and operation/column/allocation Vec capacities, including
spare capacity and nested names/percentages. Exhaustive schema matches require
future fields and operation variants to receive an ownership audit. The grant
follows the configuration through preparation and publication and is released
after the payload. `reserved_bytes()` exposes its charge; the analysis snapshot
records `prepared_job_reserved_bytes` alongside other live owner diagnostics.

Callers construct/deserialize the input Job before this boundary. Validation
and Context construction also precede this admission. This change accounts for
retained configuration during processing, not those earlier allocations. A
missing seed reserves 64 bytes before generating the same 32 random bytes as
lowercase hexadecimal. Canonical serialization still forwards the Job schema.
Borrowing remains available through Deref; mutation through Prepared.job is
rejected at compile time. Explicit Job clones are separate caller allocations.
Replacing an entire prepared owner transfers that owner's existing grant; this
is not a general capability boundary over externally accessible Contexts.

Source Analysis trees/clones, validation scratch, caller-created inspection
configuration, response/error buffers and runtime/OS allocations remain open.
This is working-allocation accounting, not an RSS cap. See the
[validation interpretation](performance.md#prepared-configuration-capacity-ownership-2026-10-23).

## Zstandard input streaming allocation ownership (2026-10-23)

[`engine/input_zstandard.rs`](https://github.com/jsmatfess/chopper/blob/87df5c047a05eafc0e886da8524a69494329925d/crates/chopper/src/engine/input_zstandard.rs)
now uses Zstandard's custom allocator for CSV input. It reuses zstd-rs's `zio`
reader state machine and mirrors the raw decoder's initialization, empty
dictionary, cursor transfer, flush, frame reset and EOF rules. Current format
detection and window limits are preserved. Legacy-at-start remains outside the
public format detector; legacy frames following modern/skippable frames retain
 their existing decoding behavior.

The [pinned C bridge](https://github.com/jsmatfess/chopper/blob/87df5c047a05eafc0e886da8524a69494329925d/vendor/zstd-sys-2.1.1/CHOPPER.md) forwards parent callbacks
into buffered legacy 0.4-0.7 constructors and buffers. Versions 0.4-0.6 retain the
bridge around their fixed inner context and outer/input/output owners; 0.7 uses
its existing advanced API. A version switch clears the freed old-context pointer
before fallible replacement construction, and partial inner construction frees
the admitted outer owner. This avoids stale-pointer destruction on admission
failure. Ordinary callers keep malloc/free fallback. The root Cargo patch,
direct vendored feature and build-script guard keep system libraries from
bypassing the ownership seam. Upstream byte hashes, the eleven modified files
and added sources/fixtures are pinned in the
[source audit](evidence-originals.md#sha256-69c495229aa2e0fff583f1616d1a9fb5eb21ac61f1d12743f00be2e08ade74db "Original: docs/benchmarks/zstandard-input-source-audit-2026-10-23.json").

Rust callbacks admit each payload plus an aligned sixteen-byte layout header
before allocation, retain simultaneous allocations/growth overlap and release
the grant after deallocation. No separately allocated pointer registry is used.
A stable UnsafeCell controller outlives every C callback/context; no mutable
State reference spans a C call, and decoding is synchronous/single-threaded.
Reader/controller boxes and the existing source buffer have independent
preadmission. C storage/source buffers release with the reader; the conservative
fixed controller allowance lasts until its enclosing callback scope ends. The
first admission error is terminal and restored as its typed Rust error after
reader destruction. Source/codec errors and consumer cancellation still clean up.

The [upstream legacy corpus](https://github.com/jsmatfess/chopper/blob/87df5c047a05eafc0e886da8524a69494329925d/vendor/zstd-sys-2.1.1/chopper-tests/SOURCE.json)
contains four legacy frames and a modern 0.8 control. Shared contracts inject
failure at all eighteen observed corpus allocation requests, including version
replacement and inner construction; payload/header grants return to zero.
Individual modern-prefix frames cover thirty local/shared edges, EOF/drop,
competing-owner release/retry and partial consumer failure. Modern concatenation
adds six more edges, two allocation faults, skippable frames, preserved window
limits/detection, truncation and real public-profile cancellation. The tests
compare exact decoded bytes with the retained upstream expected text.

Footprints depend on the read pattern: a larger direct destination can avoid an
internal decoding buffer. Edge and competitor/retry controls therefore use the
same `read_to_end` pattern as their baseline. Fixed adapter and dynamic codec
admission remain distinct; a dynamic C allocation can fail after consumer entry.
The [validation interpretation](performance.md#zstandard-modern-and-legacy-input-allocation-ownership-2026-10-23)
records native/WASI runs, C AddressSanitizer and retained unpatched CLI controls.
This closes requested allocation ownership for the configured CSV streaming
input path. One-shot legacy APIs outside that production call graph, allocator
usable-size overhead, source/job trees, parent discovery, runtime/stacks and
error/OS internals remain separate; there is no complete RSS-cap claim. Output
[Zstandard](#zstandard-output-context-admission-2026-10-23),
[deflate/ZIP](#zip-member-and-output-deflate-codec-admission-2026-10-22) and
[gzip input](#gzip-input-codec-admission-2026-10-22) keep their existing owners.


## Native HTTP JSON response ownership (2026-10-23)

[`server/json_body.rs`](../crates/chopper/src/server/json_body.rs) owns native
JSON response construction and transport payloads. A stable borrowed Serialize
schema is preflighted with the shared JSON estimator before building the
canonical sorted-key Value tree. Actual retained capacity is reconciled below
the preflight allowance. A separate sibling grant admits the exact encoded Vec
capacity while the tree remains live. The tree releases before the HTTP reader
escapes; the wire Vec releases before its Reservation, including failed sends,
abandonment and EOF followed by delayed reader drop. The shared response
workspace uses the existing process pool and dynamic pressure rechecks, with
no separate arbitrary per-response cap.

`/api/state` borrows the cached Analysis/Profile under the state mutex for both
passes and encoding. The lock releases before HTTP sends. A denied response
preserves cached owners and a ready Prepared job; it does not publish or cancel
anything. Defaults and picker-result response copies use the same owner; native
inspection success responses retain their separate existing owner. Static assets,
fixed authentication/busy errors and job-transition acknowledgements borrow
literal bytes. The latter cannot fail response allocation after a state mutation.

Dynamic error chains are counted with Display, formatted into an admitted UTF-8
buffer, then passed through the admitted JSON path. The original error is retained
if that admission fails: a bounded inline formatter copies a UTF-8 prefix and
adds ` [truncated]` when necessary, then escapes it into a 2,048-byte inline JSON
buffer. Ordinary admitted error bytes preserve their full prior content and
escaping. The low-memory fallback needs no heap payload and retains the original
status/error prefix rather than replacing it with a second allocation error.
The private helper only accepts stable, known Serialize sources; re-audit that
assumption and the shared estimator when adding schemas or serde_json features.

This covers response payload trees, formatted error copies and wire buffers,
not complete native-server ownership. Incoming request Vec/Value parsing,
picker subprocess output and parsed source, default Job/source construction,
State/progress/error/source Strings, workspace/Arc carriers, tiny_http framing
and internal I/O, thread stacks and OS/runtime allocations remain separate.
Display implementations may have their own allocations. The inline fallback
uses runtime stack headroom. This is working-allocation admission, not an RSS cap.
[Validation and limitations](performance.md#native-http-json-response-admission-2026-10-23).


## Native HTTP request byte-buffer ownership (2026-10-23)

[`server/request_body.rs`](../crates/chopper/src/server/request_body.rs) admits
incoming wire-byte Vec capacity before copying from an 8 KiB inline read buffer.
Growth doubles capacity up to the existing 1 MiB payload limit, accounts for
old/new replacement overlap with Reservation::reserve_vec and reconciles actual
capacity. Declared bodies above the limit fail before opening tiny_http::Request::as_reader,
which would otherwise send 100 Continue, as well as before reading or allocation.
Unknown-length/chunked bodies read at most one byte beyond the cap to detect
oversize; that sentinel never requires another heap allocation. Interrupted
reads retry, other read failures release the buffer before its grant, and empty
input needs no payload allocation.

The RawBody owns data before its Reservation and retains both through JSON
parsing, including malformed UTF-8/JSON and successful conversion. It does not
transfer admission to the returned Value or later Job. Those parsed/source
owners and serde_json parser scratch remain explicitly outside this byte-buffer
slice. Every native request path using the shared body helper, including
inspection and picker requests, now uses the same process transport workspace.

On admission failure the old Vec and grant release before any further I/O.
The reader then drains at most the remaining 1 MiB-plus-one allowance using the
same inline scratch, retrying Interrupted and stopping on EOF or other errors,
then returns the original typed admission error. This permits a valid JSON
rejection for a still-uploading chunked client instead of closing over unread
bytes and losing the response to a socket reset. Drain failures do not replace
the primary error. This is a byte bound. The later
[native HTTP deadline contract](maintainer/research/native-http-requests.md) adds an absolute socket
read deadline and shutdown interruption to this same drain without changing its
byte allowance or original-error precedence. Header/size validation behavior is unchanged.

Focused controls cover local/shared overlap edges, competing-owner release/retry,
partial read failures, EOF/parse/drop lifetimes, malformed input, header/stream
caps, release before drain, drain interruption/failure and the sentinel bound.
Real tiny_http fixed/chunked echo and zero-pool rejection tests cover transport.
The 32,768-byte retained fixture has a 49,152-byte replacement-overlap peak; these
are working capacities, not RSS. Runtime/HTTP framing, native stacks, parsed
request/picker/job trees and state/source storage retain their separate scope.
[Validation and limitations](performance.md#native-http-request-byte-admission-2026-10-23).


## Native HTTP decoded request ownership (2026-10-23)

Native RawBody::parse now reuses the existing
[`decode_reserved`](../crates/chopper/src/storage/json_lines.rs) path for
serde_json::Value instead of constructing an uncharged tree. Raw wire bytes
remain admitted while the decoder first admits escape scratch, visits the slice
without constructing a Value, admits the tree allowance, constructs the Value
and reconciles retained capacity. ChargedJson retains the tree/grant after raw
bytes and parser scratch release. Drop order frees data before its grant.

The decoder's existing scratch envelope is twice the next power of two of the
whole input length, with an eight-byte minimum before rounding. It covers old/new
Vec growth overlap across preflight and owned decode, including escaped keys and
strings. The preflight visitor borrows text, counts array descriptor growth and
uses the existing conservative BTreeMap node envelope. Duplicate keys count all
input occurrences during construction, then reconcile to the surviving tree.
Whole-input scratch admission is deliberately conservative even for unescaped
strings or padding; the 1 MiB wire cap does not promise that parsing needs only
1 MiB of working capacity. The helper only supports the audited Value/metadata
schemas implementing JsonCapacity, not arbitrary Deserialize implementations.
The pinned serde_json 1.0.151 default/std features retain BTreeMap objects and
ordinary inline numbers; version/features, parser scratch, node layout or schema
changes require re-auditing these assumptions.

[`JobRequest`](../crates/chopper/src/server/request_body.rs) keeps the decoded
source grant when serde_json::from_value moves original strings into Job.
Borrow-only profile/inspection paths retain that owner through their worker
scope. Preparation consumes JobRequest and holds the source grant until the
engine returns: success has established PreparedJob's independent capacity
owner; failures/cancellation unwind consumed allocations before source release.
The wrapper exposes immutable borrowing and no unguarded Job extraction. Picker
requests borrow the ChargedJson tree through command construction and completion.
The picker subprocess's own output/parsed response remains separate.

This admits the original decoded JSON tree and retains coverage for original
allocations moved into Job. Additional allocations made by typed conversion,
serde tagged/untagged buffering, default Job fields and conversion error internals
are not newly admitted by this source grant. It is not a proof of complete typed
request ownership or process RSS. State/progress/error sources, carriers,
HTTP/OS/runtime allocations and native stacks retain their separate scope.
Caller-initiated clones still need their own owner.

Controls cover parser-scratch and construction denials, local/shared peak edges,
competing trees with release/retry, duplicate-key/numeric/Unicode/recursion/error
compatibility, serialization failure, thread transfer/drop and pointer-preserving
input-string movement. Preparation controls observe the source grant during
progress and the independent PreparedJob owner after handoff, plus cancellation,
missing-input failure and no publication. The representative fixture has a
59,468-byte construction peak and retains 9,996 bytes after raw/scratch release.
[Validation and limitations](performance.md#native-http-decoded-request-ownership-2026-10-23).


## Native typed Job construction ownership (2026-10-23)

[`request_body/conversion.rs`](../crates/chopper/src/server/request_body/conversion.rs)
now preflights additional Job-construction working capacity while the original
ChargedJson owner remains intact. A sibling reservation admits the entire
allowance before serde_json::from_value runs. Only then is the original Value
consumed. On success, the existing exhaustive
[`job_owner::capacity`](../crates/chopper/src/engine/job_owner.rs) audit measures
all retained Job String/Vec capacities; original and conversion grants combine
without releasing either, then shrink to that measured capacity. JobRequest
keeps Job before its Reservation and exposes immutable borrowing. Preparation
holds this typed owner until PreparedJob establishes its independent owner or
consumed data unwinds on error/cancellation. Profile/inspection workers retain
the typed owner through their scope.

The envelope is specific to the pinned serde 1.0.229/serde_json 1.0.151 Job schema:

- Every input array allows both one Content vector and one typed vector, using
  the largest Operation/Column/Allocation descriptor. Each allowance includes
  hinted allocation, geometric growth and old/new overlap: max(4, 3 * count)
  slots for nonempty arrays.
- Every input object allows a Content key/value-pair vector on the same basis.
  The tagged visitor's size hint includes the tag even though the resulting
  buffer omits it. Original Value descriptors remain independently admitted.
- All input string/key lengths conservatively allow one additional copy. Valid
  owned Column names now move directly without a trial error; borrowed adapters
  can still copy text. Invalid column containers are strictly visited without a
  retained tree. The unchanged envelope still allows Content buffers for every
  source container; tagged operations continue to build one Content graph and
  nested owned extraction moves it. JSON does not produce Content Some/Newtype boxes.
- Job::default creates two CsvSettings defaults. Provided input/output settings
  can create two more; each allocates only `utf-8` and `lf`. Conversion admits all
  four (28 bytes), even when fields are provided or absent. Other defaults have
  scalar/None/empty storage. The GET defaults source separately pre-admits its
  two CsvSettings instances (14 bytes) before constructing Job::default.

The Content slot bound is String plus one pointer-sized discriminant allowance;
a versioned private-type test checks the pinned layout. Configuration/default,
serde/derive buffering, string-copy, size-hint or layout changes require this
audited envelope to be revisited. Error object/message formatting internals,
allocator usable-size overhead and runtime/carrier allocations remain separate;
this covers Job data and conversion buffers, not a complete RSS cap.

Native edge tests cover empty/default conversion, a 1,024-column conversion and
GET-default construction at local/shared boundaries. Competing typed owners deny
and permit exact retry after release. Twenty-seven schema/error fixtures cover
all operation variants, defaults, invalid types/fields and exact original
configuration serialization/validation errors. Existing pointer/handoff tests
now require actual typed capacity rather than the prior larger source-tree grant.

An isolated allocation probe uses System allocation layouts, counts old/new
realloc overlap and enables observation only around fresh source Value creation
and Job conversion. Each successful fixture's observed conversion peak fits the
source-tree plus conversion allowance, and retained requested heap equals the
exhaustive Job-capacity audit; all observed allocations release after drop.
Windows and Linux each pass 40 cases (38 successful conversions and two observed
errors). The retained successful-column negative control demonstrated a failed
numeric-trial error exceeding the Job-data envelope. The subsequent
[Column scalar decoder](#column-scalar-deserialization-2026-10-23) removes that
successful-conversion trial and reruns the control within the unchanged envelope.
The earlier records remain immutable. Other error-object internals remain outside
the payload bound; no timing, usable-size or RSS inference follows.
[Validation and limitations](performance.md#native-typed-job-construction-admission-2026-10-23).


## Column scalar deserialization (2026-10-23)

[`config/column.rs`](../crates/chopper-core/src/config/column.rs) decodes supported
indexes and names directly instead of buffering an untagged enum and formatting
failed trial errors. Valid unsigned/nonnegative signed indexes use checked usize
conversion. Floats remain invalid, including integral-looking floats/negative
zero, and quoted numeric text remains a name. Borrowed names copy once; owned
String/UTF-8 byte buffers move into Column::Name, retaining capacity. Serialization
remains the existing untagged scalar representation and no seeded/replay version
changes. Explicit caller construction and generic format scratch retain their
own scope.

Rejected arrays/maps use the same strict deserialize_any scalar validation
recursively without retaining an intermediate tree. IgnoredAny is deliberately
avoided because its fast skip can omit UTF-8/escape validation. Scalar rejection
is represented as an internal None and converted to the legacy generic Column
error only after deserialize_any returns; producing that custom error inside the
visitor would add a JSON position suffix absent from the original untagged
implementation. Parser syntax/Unicode/recursion failures still propagate during
traversal. The visitor's 128-bit/enum callback behavior and optional/newtype
traversal preserve the original supported non-JSON behavior.

A retained derived untagged reference checks exact decoded values, serialized
forms and errors. Thirty-six shared JSON cases run natively and in the WASI
resource reactor, with platform usize limits kept explicit. Native tests also
cover non-JSON scalar/wrapper forms and an owned 16,384-control-character name
whose pointer and 32 KiB capacity must move unchanged. The prior full-heap control
is replayed alongside the 40 original allocation fixtures with the original
successful-conversion envelope assertions restored for all 39 successes. The
control's requested-heap peak falls from 201,770 to 18,167 bytes while retained
Job capacity stays 16,499 bytes and the 39,960-byte envelope is unchanged, on
both Windows and Linux. These are exact requested-layout observations on the
fixture, not timings, allocator usable size or RSS claims. Other error/runtime
allocation gaps remain separate.
[Validation and evidence](performance.md#column-scalar-deserialization-without-successful-trial-errors-2026-10-23).


## Native picker parent capture and lifecycle (2026-10-23)

[`server/picker_capture.rs`](../crates/chopper/src/server/picker_capture.rs)
replaces the native server's Command::output capture. Parent-owned stdout/stderr
Vec capacity is admitted before copying from two inline read buffers. Growth
covers old/new replacement overlap and reconciles actual capacity through the
shared process workspace. The streams are read concurrently so a full stderr
pipe cannot deadlock a blocked stdout capture. Each Bytes owner stores its Vec
before its Reservation and retains admission through EOF, child completion and
subsequent use. No arbitrary new output-size cap is introduced; available shared
capacity determines admission.

Successful selection stdout uses the existing admitted JSON decoder. Unused
stderr releases before decoding; the returned ChargedJson tree survives the
capture buffers and remains admitted while the HTTP response is encoded. Failed
helpers discard unused stdout and move the admitted stderr owner into their
error. A streaming UTF-8-lossy formatter preserves String::from_utf8_lossy output
without creating an unadmitted full error String or lossy String copy. The raw
stderr grant survives formatting and releases independently of an admitted error
response's encoded reader. Fixed error/context carriers and formatter/runtime
internals retain their separate headroom scope.

A Child guard stops and waits for the owned helper on failure. It lives inside
the scoped-reader closure, so unwind or reader-start failure stops the child
before thread::scope waits for blocked readers. Reader panic is converted to a
capture failure; the first read/admission/cancellation error remains primary.
The helper status is collected before successful output or a pipe error escapes.
Normal child wait and cancellation/denial cleanup are covered with real test-owned
processes; arbitrary OS kill/wait failures are not claimed as validated recovery.

A single parent Owner shares a lifecycle gate. Capture registers a session before
spawning. Closing atomically prevents new sessions, signals cancellation and
waits for registered captures to reap/join; dropping the Owner closes it on early
server returns too. The gate is not the HTTP picker-busy flag: an incomplete
request body has no registered helper and cannot keep server shutdown waiting.
The busy flag has its own unwind-safe guard. State locks are released before
process waiting. This controls the directly owned helper, not all broker/dialog
or WSL PowerShell descendants.

Native controls cover local/shared pipe edges, competing-owner retry, read failure,
independent EOF lifetimes, all 65,536 two-byte lossy combinations plus longer
invalid sequences, exact error JSON and source/error-reader release ordering.
Real helpers cover JSON selection/cancel, malformed stdout, failed status/invalid
stderr, simultaneous 256 KiB streams, denial kill/reap, session cleanup after
spawn failure, owner-drop cancellation and rejection after closing. The real Linux
server also exits on SIGINT while a picker request body is incomplete, after a
busy response confirms the precondition. Actual desktop dialogs, descendant
process cleanup, helper-process/WSL bridge allocations, command/path construction,
thread stacks, channels, carriers and OS/runtime allocations remain outside this
parent-payload slice. No complete RSS cap or new picker-device claim follows.
[Validation and evidence](performance.md#native-picker-parent-pipe-admission-and-shutdown-2026-10-23).

The helper's process-exit wait remains cancellable after both pipe readers reach
EOF. Pipe closure alone does not prove helper exit; polling `try_wait` and the
same cancellation flag prevents shutdown from waiting indefinitely for a helper
that closed its outputs but kept running. A test helper closes the actual OS pipe
handles, signals readiness separately and stays alive until killed or its
30-second watchdog; the parent must cancel and reap it before that watchdog.

## Buffer-shuffle removal ownership audit (2026-10-24)

The shuffle operation now retains only its scalar strategy. Removing its scalar
row limit and default adds no heap defaults. The exhaustive PreparedJob capacity
match still visits every operation; its operation vector uses the actual
`size_of::<Operation>()`, and nested Column/Allocation ownership is unchanged.
The native typed-Job preflight likewise computes its largest typed descriptor
from the current layouts. CsvSettings are still the only allocating Job defaults,
so BASE_DEFAULTS/DEFAULTS and pinned serde Content allowances remain unchanged.
Strict wire/owned decoding rejects both the former strategy and the former field,
including that field alongside supported strategies. Conversion error tests
retain and release source/construction grants through rejection.

The removed warning leaves eight independent conditions. MAX_WARNINGS and its
pre-admitted vector now use eight slots; boundary, failed-copy, concurrent-clone
and final-release tests continue to cover the actual capacity and grant. The
remaining messages keep their text and order. The old nine-condition section
above describes its dated build, not the current bound.

Removing the diagnostic counter removes the same entry from both the borrowed
Serialize view and legacy parity reference. The shared JSON estimator still
preflights that view, releases audit/pressure locks before admission, and rechecks
before construction. No Serialize form or serde_json feature changed. Native and
WASI diagnostic ownership contracts cover construction, denial, retry, exact
source parity and last-clone release. HTTP request/response ownership, storage
primitives, native atomic publication and browser marker semantics are unchanged.

## Radix and prefix-distribution removal ownership audit (2026-10-24)

Removing the two physical sorting experiments changes no Job, Resources, Column,
Operation or RNG schema/default. Prepared configuration, typed-request grants and
capacity accounting keep their current layouts and retained owners. Cargo
features had no runtime public selector. Unknown enum values still fail strict
wire/owned conversion before input I/O; unsupported feature names fail Cargo.

Sorter no longer retains distribution state or its enable flag. Row-buffer
admission still charges actual `size_of::<Sorter>()`, PackedRow descriptors and
heap capacities, including growth overlap; boundary tests compute current sizes.
Radix index/histogram scratch and recursive distribution files/buffers are gone.
Shared packed rows, checked frame decoding, catalogs, routing, merge readers,
spill blocks, collision-domain comparison and final merge streaming remain.
`PackedRow::read_fields` is now test-only; reserved/reusing production decoding
is preserved. Pressure coverage now requires both 8/16 MiB cases to succeed,
removing the former distribution-only bounded-failure exception.

The borrowed diagnostic Serialize view and legacy parity reference both omit
four dedicated distribution counters. Flexible execution counters omit the
prefix-pass field and the compiled-feature header uses 14 surviving entries.
Recorded physical implementation now reports resident comparison sorting or
external merge (or independent buckets/resident swaps when explicitly eligible).
No source/algorithm/domain version changes. The audit/snapshot contents and
plan digest reflect the current build rather than promising old flexible replay.
Shared JSON preflight still sizes the actual view, releases locks before reserve,
rechecks before construction and retains grants through the final clone. No
serde_json features or custom Serialize forms changed. Native HTTP lifetimes,
atomic publication and browser completion-marker semantics are preserved.

## Independent buckets and buffered XOF removal ownership audit (2026-10-24)

The removal deletes `engine/flexible/buckets.rs`, `engine/flexible/source.rs` and
core `fast_random.rs`, their routing/node statistics, XOF caches/state and exclusive
packed-row routing helper. Shared packed storage, adaptive tuple routing,
comparison sorting, collision refinement, resident admission, external merge,
counter draws/domains and flexible scope derivation remain. No dependency is
exclusive: BLAKE3 still implements counter-v1, domain derivation and digests.
The lockfile and codec backends/features are unchanged.

`FullShuffleAlgorithm` retains only `AdaptiveV1`; `FullShuffleRng` retains only
`Blake3CounterV1`. Their explicit JSON values remain accepted and default values
remain omitted from canonical serialization. Removed variants fail strict enum
decoding. `Resources.shuffle_rng_buffer_bytes` is deleted, so even its former
64-byte default is an unknown field. The exhaustive retained-configuration
capacity match removes that inline scalar; all remaining String/Vec owners,
actual capacities, seed construction and payload-before-grant release persist.

Typed native construction still derives vector descriptor sizes from
`size_of::<Operation/Column/Allocation>()`; none of those descriptors changes.
The Job/Resources inline layout may shrink; neither is a heap descriptor charged
by that conversion envelope. Allocating CsvSettings defaults remain 14 bytes for
GET defaults and 28 for conversion. Other defaults still allocate no payload.
Pinned serde Content and strict source decoding remain unchanged. Conversion
regressions include removed variant/field errors without weakening admission.

ExecutionSummary retains only the counter RNG variant. Flexible streamed plan
headers lose the XOF resource field and two compiled-experiment entries (12
remain); group choices lose the XOF cache field and bucket-specific choices.
Planner versions remain 1/2/3 for the surviving baseline/partition/allocation
builds. Records still stream to owned admitted disk; no group catalog is retained.
Manifest preflight uses the actual Serialize shape and retains byte/tree/admission
checks with surviving variants. Diagnostic JSON counters, borrowed source visits,
lock release before reservation, recheck, retained controller/tree grants and
HTTP reader lifetimes remain unchanged. There is no new JSON form or serde feature.

The exact live-resource equations, including the validated optional
shuffle/partition decision-audit grant, are unchanged. Named zero allocation
quotas, membership, original indices and counter-domain range-cut regression
remain exercised. Publication, completion markers, cancellation and failure
cleanup continue through the shared owners. This audit asserts working-allocation
ownership, not a complete RSS cap; platform checks are recorded in
[validation](validation.md#independent-buckets-and-buffered-xof-removal-2026-10-24).


## Partition-first and dormant Parquet removal ownership audit (2026-10-24)

Only the compile-time partition-first planner, child domain/lineage scope,
exclusive streamed rewrite/stage diagnostics and dedicated tests are deleted.
The flexible header now records 11 compiled experiments and planner version 1
(ordered baseline) or 3 (allocation ranges). The historical version 2 is no
longer emitted. Shared Recorder buffer/descriptor admission and disk ownership
are unchanged; no retained in-memory audit catalog is added. Logical-parent and
allocation-range domains, counter draws, ordered fallback and external merge
remain unchanged. Exact shuffle/partition retains its original parent domain,
collision refinement and retained-parent admission fallback.

No Job, Resources, Operation, Column, ExecutionSummary or public request schema,
default, typed construction descriptor or retained-capacity equation changes.
There was no dedicated runtime selector for partition-first and no Rust Parquet
decoder/control. Removed build gates fail Cargo resolution, including browser
forwarding/wrappers; flexible auto is still a supported ordinary ordered request.
Prepared configuration capacities, native source/conversion grants, allocating
CSV defaults and pinned serde decoding/layout assumptions are unchanged.

Manifest preflight still sizes the actual Serialize schema and its owned tree;
the streamed plan loses one static feature entry and exclusive rewrite records.
Diagnostic source visits, lock release before reserve, borrowed-schema recheck,
last-clone payload/grant release, HTTP reader grants and temporary identity/offset
helpers are untouched. Exact live-resource equations, including the validated
optional decision-audit grant, are retained without relaxed assertions. Native
atomic publication, browser completion markers and cancellation/failure cleanup
continue through the same shared owners.

Cargo pruned only parquet 60.0.0, base64 0.23.1, seq-macro 0.3.6, snap 1.1.2 and
twox-hash 2.1.5. No package was added or upgraded; only chopper's dependency list
changed among retained packages. Arrow array/buffer/schema/IPC, shared Arrow
transitives, compact storage and all pinned codec backends/features remain.
Direct snapshot correctness/resource tests remain acceptance requirements.
This audit concerns working allocations, not an RSS bound or new platform claim.

## Independent-parent batching removal ownership audit (2026-10-25)

The rejected E2 adapter, its optional sibling workspaces/materialized Datasets,
replay owners and retryable catalog mode are removed. Shared Dataset, DiskFile,
Reservation, MemoryPool and serial parent-stage lifetimes remain. Three
AtomicU64 fields leave Budget; the test-only hook and peak-reset API are gone.
Generic batch/sort/compression workers retain their existing owners.

Both borrowed diagnostic serialization and the test legacy schema lose the same
three `parallel_group_*`/`parallel_groups` numeric entries. Diagnostic admission
still estimates the actual borrowed Serialize source, reserves after releasing
audit/pressure locks, revisits the stable schema, builds the tree and reconciles
to `Value::json_capacity()` plus its shared controller. No hardcoded allowance
or weaker assertion replaces that calculation. The changed tree's key/String and
BTreeMap node capacities therefore follow actual owner types. The flexible
execution header now contains ten compiled-experiment entries instead of eleven;
its fixed array and exact integration expectation change together.

The live workspace equation still includes temporary paths, directory paths,
prepared configuration, header, preview, column summaries, stage statistics,
text, warnings, timings and the self-inclusive diagnostic owner, plus the
optional validated decision-audit grant. Process accounting includes separately
retained owners outside that workspace; unrelated owners cannot be absorbed as
a residual. The surviving diagnostic contracts retain exact shared/local edges,
last-clone release, serialization failure and final-zero checks. Budget/Context
inline carriers and runtime/RSS remain outside those payload claims.

Fresh Windows default/all-feature tests and WASI base, shuffle-partition and
combined surviving-feature resource reactors exercise these equations. See
[validation](validation.md#independent-parent-batching-removal-2026-10-25) and the
[decision](performance.md#independent-parent-batching-removal-2026-10-25).
## Direct Run encoded chunks and publication ownership (2026-10-27)

The [direct-execution slice](direct-execution.md) adds an empty-pipeline,
seeded-policy adapter behind the existing encoded `PlanWriter`. Snapshot mode
keeps its admitted data/catalog buffers; direct mode owns its output-record
buffer separately and does not construct the encoded snapshot or dataset writer.
Both use the same admitted serializer/prefix, `Chunk` lineage owner and exact
encoded cap decisions. Chunk/group schema and retained summary-tree layout are
unchanged. Output metadata is a disk-backed JSONL stream, not a retained tree of
every output file.

Direct publication reuses admitted names/paths, readers, publication buffers,
deflate/Zstandard encoders and ZIP directory streaming. Codec versions, backends
and settings are unchanged. Open chunk handles, archive and metadata writer are
destroyed before the staging directory; allocation owners precede their grants
in field destruction order. The canonical manifest tree still uses the shared
preflight and admitted Job/Analysis schema after successful EOF, then copies
bounded output records before finalization and commit.

Direct traversal retains the existing immutable prepared-configuration owner and
input/header/parser/preview/summary/digest admission recipes. Returned Analysis
uses the same shared header, preview, summaries, stage/text/warning/timing and
diagnostic owners, including last-clone release. No serialized Analysis/Job field
was added. Native `JobRequest::run` retains decoded/typed source grants across
the entire direct call or preparation fallback. The new request route uses the
same size-limited admitted request body and allocation-free transition reply.

Private final output remains separate from temporary spool accounting; direct
mode still charges output-record metadata and ZIP member temporaries. Browser
quota additionally covers private outputs until export. Destination discovery,
normalization, caller/CLI/WASI JSON construction, native state/progress/error
sources, JS/browser runtime and OS/thread allocations retain their documented
open scope. These changes do not establish a complete RSS cap.

Focused direct contracts check codecs/caps, failures, cancellation, source-change
and destination-race rejection, admission release/retry and shared Analysis
lifetimes. The shared resource reactor additionally exercises direct local/shared
denial and retry on native/WASI layouts; current executed coverage belongs in
[validation](validation.md), rather than being inferred from this ownership audit.


## Opt-in memory and reproducibility ownership audit (2026-10-28)

The portable `MemoryBudget` number/`"auto"` representation is inline (16 bytes on
supported native and wasm32 layouts), with no heap payload. Its scalar visitor
uses no untagged buffering or failed numeric trial for `"auto"`. Numeric values
serialize unchanged; omission remains 256. CsvSettings allocating defaults remain
14 bytes for GET defaults and 28 bytes for typed conversion; this field adds no
payload to those envelopes. Preserve the existing [typed Job construction](#native-typed-job-construction-ownership-2026-10-23)
and [decoded request](#native-http-decoded-request-ownership-2026-10-23) ownership.

Automatic resolution observes the existing shared ledger after pressure refresh;
it creates no grant and changes no requested Job fields. The effective Context
is resolved before directory/configuration admission and retained for prepared
execution. Requested `"auto"` persists in manifest configuration; effective numeric
memory/workers belong to Analysis. See the [resource contract](specification.md#resources-publication-and-interfaces)
and existing [prepared configuration](#prepared-configuration-capacity-ownership-2026-10-23)
and [manifest](#job-manifest-construction-owner-2026-10-21) owners.

ZIP metadata and Zstandard window limits use the numeric requested budget, or
the resolved workspace budget for Auto. An injected smaller reservation ceiling
still produces typed admission denial without changing those numeric format
limits. Internal WASI publication fixtures select its supported single worker.

`Analysis.algorithm_version` is a borrowed static scalar in parent and child
Analysis, with strict decoding to supported static literals; it adds no retained
text allocation. Seed ownership continues through the existing
[Analysis text owner](#analysis-text-ownership-2026-10-23). Shared JSON preflight
continues to visit the actual borrowed Serialize schema, including this field;
[response ownership](#native-http-json-response-ownership-2026-10-23) and
[diagnostic lock/admission ordering](#analysis-diagnostic-snapshot-ownership-2026-10-23)
remain the applicable contracts. This audit records source behavior, not new
allocation-probe, platform-validation or performance evidence.

## Native retained state error ownership (2026-10-28)

`server/state_error.rs` privately owns full alternate Display bytes before their
Reservation. The shared count/fixed-slice formatter pre-admits allocation and
reconciles actual Vec capacity. Denial drops partial construction before releasing
its grant and uses the immediate HTTP error's shared inline UTF-8 prefix helper
(at most 224 prefix bytes plus ` [truncated]` when necessary). It never retains
the anyhow chain as an allocation owner or recursively formats a denial.

All four profile/preparation/direct/prepared-execution paths use the
[job module's shared completion handling](../crates/chopper/src/server/jobs.rs),
which samples cancellation before formatting, then constructs text outside the state mutex and
profile/pool/pressure audit locks. Completion remains infallible. Replacement
destroys bytes before releasing their grant. State serialization borrows the
immutable text; response tree/wire admission is independent, so clearing state
can release the source while a reader retains its response grant through drop.
The source lock ends before sending; literal transition acknowledgements remain.

This supersedes the retained State.error exclusion in earlier sections only.
Static status and cached output keep their existing owners. Progress producer
and retained progress text, error-object/Display internals, source discovery,
carriers and OS/thread/runtime allocations remain separate; working-allocation
admission does not establish an RSS cap. The native server is excluded from WASI
by `lib.rs`; these private helpers do not affect the hosted engine.

## Portable Progress phase ownership (2026-10-28)

`storage/progress_phase.rs` owns immutable phase text on native and WASI.
`Progress.phase` is now the public string-like `ProgressPhase`, rather than
`String`; borrowed access, Display/Debug, comparisons and string serde remain.
Callers assigning String use `.into()`; mutable String operations are unavailable.
Explicit caller construction/deserialization remains caller-owned and unadmitted.
`Notify = Arc<dyn Fn(Progress) + Send + Sync>` and JSON fields/text/counters/order
are unchanged. Native callbacks move the same owner into cached State.

Built-in literals use `ProgressPhase::literal` without heap allocation or grants.
`Context::event` accepts static text, checks cancellation and refreshes pressure
in the existing order. `dynamic_event` does the same before admission; denial
returns the typed resource error before invoking Notify, leaving prior cached
progress intact and following ordinary prepublication failure/cleanup. No
truncation, skipped event or substitute phase is permitted. The sole formatted
producer uses checked stack UTF-8 formatting for `Preparing operation N of M`,
with two bounded decimal usize fields, then makes one admitted retained copy.

Before heap construction, reserve the String/controller envelope (Payload with
String and optional Reservation, two Arc counters plus alignment headroom), then
pre-admit text length and reconcile actual String capacity. Old cached events
remain charged during new construction. Each immutable owner retains its producer
Workspace via Reservation through callback handoff and arbitrary Progress clones.
Every shared clone drops with `Arc::into_inner`: the winning drop deallocates the
controller before destroying String and finally releasing the grant, including
concurrent final drops. No Weak or mutable payload access escapes.

Profile literals and both actual postcommit Complete producers construct static
phases directly. They never call fallible Context events after commit, including
when admission is exhausted or cancellation arrives after publication. Response
JSON owns a separate admitted copy and can outlive replacement/destruction of
source State. This supersedes earlier Progress source exclusions only: scalar
carriers, callback/runtime overhead, caller decoding and CLI/WASI JSON framing
are outside this slice. Working allocation admission is not total RSS accounting.
Executed runtime coverage belongs in [validation](validation.md).


## Hosted codec observation ownership (2026-11-05)

Hosted Run observation adds no codec heap, reader Box or retained callback grant.
The [input adapter](../crates/chopper/src/engine.rs) still constructs its original
admitted boxed gzip, Zstandard or borrowed ZIP-member reader. An admitted observer
borrows that reader through an inline stack wrapper; otherwise the consumer uses
the original reader directly. Parser adapters now borrow a `dyn Read`; their
existing input-buffer allowance uses the actual `DecodeReader<&mut dyn Read>`
layout. The fat-pointer representation replaces the former boxed-reader pointer;
it does not replace or release the separately admitted adapter allocation.
Existing inspection callers keep their reader ownership and error ordering.

[Output observation](../crates/chopper/src/output.rs) wraps the original Sink
inline and borrows archive writers on the stack. It counts successful writes,
then classifies the existing explicit factory/finish/sync result. Original codec
fields still own their grants through error-time and implicit destruction. No
backend, pin, window, compressor option, buffer capacity or archive format changes.
ZIP observation starts before construction, captures admission failure, and
consumes actual member-spool provenance. Its optional owner has no live callback
reservation during required creation, writes, finalization or cleanup.

The fixed physical fact adds one `u64` byte counter; its inline-size and maximal
1024-byte serialization assertions remain in the shared native/WASI resource
contracts. Worker outcomes/active summaries retain one bounded scalar each and
reject unsafe integer totals. Codec unit meanings and inclusive lifetimes are
owned by the [observation contract](execution-observation.md#compressed-input-and-output).
These counters establish neither RSS bounds nor physical I/O throughput.

## Native experimental plain publication ownership (2026-11-05)

The `experimental-plain-publication` Cargo feature extends the existing bounded
prepared-publication batch to native plain files. The default build and WASM
remain serial for plain publication. It reuses the Context worker pool and the
compressed-publication worker/memory ceiling; no additional queue or worker pool
is constructed. The exact formula lives in the
[resource contract](specification.md#resources-publication-and-interfaces).

Before batch construction, the experiment caps task slots by the remaining
`OutputPlan.files` count. Each `PublicationBatch` continues to pre-admit its Vec
capacity and retain the grant after decoded chunks/results are destroyed. Names,
paths, independent snapshot readers and plain writer buffers keep their existing
owners. Concurrent copying retains per-file flush/sync; `for_each_batch` joins
before ordered result collection, manifest finalization and directory commit.
Shared admission can deny a later task even when preparation and an earlier
batch succeeded. Such failure and cancellation remain terminal and remove owned
private output; this feature introduces no retry or weaker publication contract.

The native `output::plain_publication_contracts` tests use the real seeded Run
path. One/four-worker, one-file and partial-batch cases compare exact CSV bytes,
ordered output records and logical Analysis fields, independently parse quoted
multiline Unicode rows and verify strict caps. A caller-local test observer checks
actual retained task capacity. Cancellation and a competing grant leaving 32 KiB
free after the first Writing output callback check complete private-output/temp
cleanup and final pool release. These are functional ownership controls, not
throughput, RSS or universal admission-parity evidence.

## CSV admitted ordinary spans (2026-11-05)

The [strict serial control](performance.md#strict-csv-serial-admitted-span-control-2026-11-05)
borrows a complete nonempty unquoted field only through its synchronous copy into
an admitted destination. It retains no input-buffer reference after `consume`.
Eligibility requires empty scratch, a fresh field and a buffered delimiter/LF;
quoted, escaped, split, CRLF and final unterminated spans retain the scalar path.
The raw working check includes the terminating byte and the historical 32-byte
charge per already completed field before field validation/allocation.

Reserved owned slots preserve their existing capacity ledger and explicit old/new
growth overlap; first/new slots still move admitted scratch. Compact targets
pre-admit the same length/payload growth and keep retained scratch capacity in
the reservation equation even when no scratch copy is needed. Denial leaves all
remaining parser/target capacities charged; the caller must not resume parsing.
This changes copying, not the caller's grant handoff/destruction contract, and
establishes neither a complete RSS cap nor universally lower capacity requests.

## Bounded input sample inspection (2026-11-15)

`engine::input_preview` and native `/api/preview` / WASI `chopper_preview` reuse
inspection intake and its admitted owned-record construction. They inspect at
most eight data records after an optional header, retaining rows through the
existing Analysis preview builder (eight rows / 32 KiB of field text, with
separate admitted vector/String/controller capacity). Header fields and their
transferred grant stay together through JSON construction. The returned
`Inspection` pre-admits header items, outer row items, nested field items and
all retained UTF-8 text in addition to the existing fixed-object allowance.
All input/sample owners overlap tree construction; native response serialization
retains its separate admitted response owner. The fixed schema has four fields
and fits the existing sixteen-field object allowance. Column-only first-record
inspection and sniff schemas remain unchanged. Sampling does not certify unseen
input or prepare publication output. Focused inspection tests exercise row/text
bounds, adapter/dialect/header behavior, construction failure and result release.

## Seeded-policy removal and shuffle/partition default (2026-11-15)

Removing the scalar Job policy field and execution-summary policy field reduces
inline schema size without adding owned capacity. PreparedJob's exhaustive match
and size-based typed construction continue to pre-admit current layouts. Existing
key, column, tentative-sort, payload, publication and last-clone ownership remain
in place for the promoted shuffle/partition implementation. The rejected resident
selector is absent; the resident-only explicit Fisher–Yates contract is unchanged.

## Random-source buffering and public seed removal (2026-11-16)

Job JSON and the CLI no longer accept a seed. `Job.random_seed` is a skipped,
undocumented internal execution/test slot, not a wire field; `seed` and
`random_seed` both fail strict public decoding. PreparedJob retains the same
optional String capacity and admits 64 bytes before creating internal entropy.
The exhaustive capacity match follows the renamed field. CLI decoding no longer
has a separate seed-construction method. The engine still owns generated entropy
and Analysis's immutable diagnostic copy through their existing last-owner grants.
Neither that diagnostic identifier nor a saved Job is a replay interface.

The bounded-draw source now consumes four disjoint little-endian u64 words from
each existing 32-byte keyed block. Each rejected draw consumes a word and the
existing unbiased rejection threshold is unchanged. Block/domain construction,
random sort keys and collision refinement are unchanged. The source has a fixed
32-byte buffer and offset in its stack-resident state, with no heap allocation or
shared mutable stream. ResidentShuffle and exact-assignment cursors retain their
existing scope/lifetimes; no per-row or per-parent heap owner is added. The new
algorithm identity is `chopper-v2-blake3-words-1`; the v1 block primitive retains
its identity. No finite-generator independence proof or seeded replay promise is
introduced. Prepared confirmation still consumes its immutable encoded snapshot.

Per-row categorical allocation retains the original unbuffered single-use draw
(including its rejection sequence), rather than constructing a buffered cursor
whose remaining words would be discarded. Only repeated-draw Fisher–Yates and
exact-allocation cursors use the new buffer; neither source allocates heap state.

## Scoped physical reporting ownership (2026-11-17)

Physical attempts now retain a small `PhysicalReporter`: shared budget, workspace
and callback references. Cloning these references allocates no new heap owner,
retains no job directory or worker pool, and holds no callback grant. The same
8192-byte per-emission admission, fixed fact schema, 1024-byte serialized envelope,
visit cap and omission/disable behavior remain in force. Each non-copyable guard
records its own terminal state; explicit outcomes suppress its fallback Drop,
while interrupted unwinding retains the latest unthrottled counters.

The native/WASI observation resource contracts retain the 384-byte Fact and
512-byte Span envelopes and bound the inline SortedRows cursor to 640 bytes.
The enum intentionally keeps its merge cursor inline rather than adding an
unowned allocation merely to equalize variant sizes. The row-forwarding adapter
contains two borrowed references, preserves compact-row borrowing, and acquires
no reservation or copied row payload. Input codec observation reuses its guard's
delivery owner instead of storing another full Context. Existing writer/catalog
capacity calculations use their compiled layouts, and release/denial tests cover
observation remaining optional. See the [reporting contract](execution-observation.md#implementation-contract)
for unit policies, row/byte cadence and lifecycle checks.

## Stage finalization and publication proof ownership (2026-11-17)

`StageComplete` metadata uses the remaining fixed physical category slot; the
32-slot identity layout, Fact shape, 384-byte Fact, 512-byte Span, 640-byte cursor,
1024-byte serialized envelope and per-emission grant remain unchanged. Stage
finalization is admitted through the same optional reporter and record cap.
The worker retains a bounded set of at most 18 logical stage IDs and sends it
with its existing coalesced snapshot; metadata facts never allocate graph cards.

`EnginePublication` is a zero-sized commit proof and `PublishedAnalysis` moves
its existing admitted Analysis without copying payloads or changing serialization.
Decoded native request grants survive Run through this typed publication handoff;
state transitions consume the proof before extracting the original Analysis.
No Job/Resources/Analysis or native StateView fields were added. Browser result
origins are presentation metadata paired with existing result slots. Mandatory
marker verification retains the previous exact-file 256-byte bound and produces
a fixed-field destination receipt; it performs no directory or CSV rescan.

## Parser-owned packed-field capacity (2026-11-17)

`PackedRow::trim_fields` preserves parser-owned capacity when no decode reservation
is attached. The parser continues to charge that actual capacity until the
existing row/sorter handoff admits and assumes ownership. This closes the
replacement-allocation overlap gap in ordinary first-Fisher–Yates and random-key
intake without adding a new allocation or changing row bytes. Decoder-owned rows
retain the existing old-plus-new pre-admission, denial and final-capacity resize.
The focused regression keeps a 128-byte parser-owned buffer at an exhausted
shared boundary and verifies exact fields and release; decoder shrink-denial
coverage remains unchanged. [Issue #2](https://github.com/jsmatfess/chopper/issues/2)
tracks delivery and final platform validation.

## Clean inactive-file cgroup headroom experiment (2026-11-18)

The default Linux observer retains raw ancestor `limit - memory.current`
headroom. The opt-in `experimental-cgroup-cache-headroom` build can instead
estimate additional room below `memory.max` after reclaiming the job leaf's own
clean inactive-file cache. A dedicated 1 GiB cgroup experiment reproduced a
shared-admission denial with a roughly 57 MiB reduced admission ceiling and hundreds of MiB of
clean inactive-file cache; this motivates the experiment, not an RSS guarantee.

Credit is `min(inactive_file, file) - shmem - file_dirty - file_writeback`, with
saturating subtraction and a cap at observed current usage. Required counters
must be present, unsigned and unique. Credit requires no leaf descendants and
readable zero `memory.min`/`memory.low` along the accessible branch. Each finite
ancestor can reduce the same leaf credit; sibling caches are never added. Current
usage is sampled before and after the statistics read, using the larger value.
The final minimum credit applies to all ancestor maximum constraints, including
any amount already over a limit. Missing or malformed optional data disables
credit. Incomplete hierarchy, hidden ancestors or changed membership retain the
raw partial bounds and existing conservative discovery fallback.

Finite `memory.high` retains its raw throttle boundary. Host `MemAvailable`, the
startup aggregate ceiling, half-headroom growth margin, existing reservations
and numeric/automatic job-budget rules remain in force. This changes an estimate
of additional capacity; it neither revokes retained grants nor changes their
lifetimes, retries raw input, credits swap, or turns working accounting into a
resident-memory cap. No browser/Windows discovery change is selected.

This is an engineering estimate, not a proven lower bound on reclaimable memory.
Kernel counters are sampled separately; protected, pinned or temporarily
unevictable pages and composition changes can defeat an estimate. The exclusions
above narrow those risks without eliminating them. Keep this policy opt-in until
its intended workload and pressure coverage supports promotion. The kernel owns
the [counter, protection and throttle semantics](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files).

## Native terminal routing publication ownership (2026-11-18)

The opt-in `experimental-terminal-routing` build permits a single plain-output
Interleaved or probabilistic assignment operation, including strata, to emit its
existing final routed traversal through `PlanWriter::direct_grouped`. It retains
the same router, sort/spill owners, membership domains, encounter order and
stage counters. It neither retains an encoded output snapshot nor copies one at
publication. Explicit internal preparation still selects a snapshot; WASI does
not select this experiment.

The Context's private `direct_terminal_output` bit conveys Run eligibility to
initial producers; it creates no resource grant. Direct output names, immutable
shared header, serialized scratch, writer buffers, paths and disk-backed metadata
retain their existing owners. Earlier private output overlaps the router's live
sort/spill resources. Managed temporary counters exclude private destination
staging and therefore cannot establish total peak disk or physical I/O savings.
Final Analysis construction precedes the existing native atomic publication.
Errors and cancellation after emission begins remain terminal, with no raw-input
replay; private output drops before its ownership grants.

Focused native controls compare exact internal-seed output bytes, metadata,
lineage, empty named groups, strict caps and stable Analysis against explicit
snapshot execution. UTF-8/UTF-16, multiline Unicode, empty input, unrepresentable
output, final cancellation, destination races and competing-owner admission are
covered. These controls do not establish an RSS cap, browser eligibility, native
Windows performance or cross-plan CLI seeded replay.

## Windows directory publication without replacement (2026-11-19)

Native publication now uses `MoveFileExW` with flags zero on Windows. The
standard-library rename replaced an empty destination in the new race control;
this violated the intended no-replacement commit boundary. No replacement or
cross-volume copy flag is supplied. The first bounded writer retains its
original destination witness; the explicit originally-empty case still removes
that directory only after a final emptiness check.

The two UTF-16 path vectors share an admitted reservation through the OS call.
Absolute normal paths originate from `std::path::absolute` (Windows
`GetFullPathNameW` normalization); disk and UNC paths acquire verbatim prefixes
for long paths, and existing verbatim/device prefixes are preserved. Each vector
reserves its counted UTF-16 length plus nine code units before construction,
covering prefix and terminator; interior NUL is rejected. Both vectors drop
before the shared grant. This adds no codec or packed-field constructor and
changes no Linux/browser publication mechanism. Native NTFS race and long/Unicode
path controls own qualification; other filesystems remain outside those claims.

## Experimental configured final writer capacity (2026-11-19)

The native opt-in memory-final-writer selector bounds configured singleton or
bounded-tree leaves by nominal memory and a hard ceiling. This is a pre-input
selection bound, not capacity admission: every vector, membership tree, lineage,
header prefix, catalog, publication path and active sink retains its existing
reservation. Automatic memory is not resolved twice; eligibility conservatively
uses the minimum valid nominal budget until the existing resolver runs. Unix's
soft descriptor ceiling leaves 64 descriptors and allows two per configured
writer; unrelated handles and concurrent jobs remain possible open failures.
No descriptor reservation or complete RSS cap is implied.

The separate small-buffer control uses 16 KiB buffers only in the private
configured-fanout constructor. Ordinary publication keeps its original buffer.
PublicationWriter admits the selected actual capacity before construction and
retains it through flush/sync/destruction. The larger selector ceiling does not
bypass local or shared grants. Unsupported fanout selects the original pipeline
before input consumption; emission failures remain terminal.

Shared row serialization never reuses an individual writer's header encoder.
The header-scratch release control replaces that encoder with an identically
configured empty one, dropping its old text and encoded allocations before
shrinking the aggregate serialization grant to the still-owned prefix capacity.
The encoded BOM/header remains per writer. It does not share mutable buffers,
introduce a new Arc owner, or release the header's existing immutable owner.

The compact-final-row intake prototype was rejected and removed after a measured
primary regression. Its archived source used existing immutable parsed views and
batched framing; direct execution retains owned records. This does not reverse
the validated compact representation used by preparation and counting.

Counted compressed Balanced output reuses existing direct codec owners and the
same two-pass header/count/digest proof. It changes no codec version, allocation
bridge, checksum, serialized cap, source identity check or publication lifetime.
All controls remain opt-in and native-only in selection. Correctness, resource
censuses and timing claims are distinct and require their own pinned evidence.

## Experimental small final-writer catalogs (2026-11-19)

`experimental-small-final-catalogs` is a native fanout resource control: each
`PlanWriter::direct_fanout` requests a 512-byte private metadata catalog buffer
instead of 8 KiB. `DirectPublication` admits the selected capacity before
constructing its `BufWriter<DiskFile>`. Its existing owner-before-grant field
order, disk-file lifetime, private staging cleanup and metadata EOF validation
remain unchanged. Header/lineage strings and decoded catalog trees retain their
separate admission. A catalog record can exceed this buffer without changing its
metadata limit, chunk boundary or original decoded bytes.

Ordinary new/grouped direct publications and snapshot catalogs keep their existing
8 KiB setting; CSV sink sizes and the memory/descriptor writer ceiling are
independent. Construction/release tests check both capacities and denied admission;
the multi-chunk Partition control uses lineage records larger than 512 bytes and
compares original snapshot publication. No complete-job performance is inferred
from those tests. This experimental flag does not activate default behavior.

## Bounded final Partition and advisory writer counts (2026-11-19)

The opt-in native shape requires a single plain unobserved Partition, Auto
routing and `max_files <= writer_capacity`. A successful group needs at least
one output file; this existing configured ceiling is a hard cardinality bound,
not an Analyze prediction. Further byte/row chunking still shares the original
global physical-file ceiling. Above-bound groups, metadata/sink admission,
parsing, codec or finalization failures remain terminal and private.

The exact tuple catalog admits a conservative full internal-node envelope per
entry before insertion (sixteen key/value/edge slots plus four pointers), as in
other bounded tree owners. Each key's Vec capacity and resolved-column vector
are additional aggregate charges. Re-audit the envelope for standard-library
node-layout changes. A separate reusable tuple buffer admits growth before
encoding the original zero-escaped, double-zero-terminated key. Its bytes are
comparison keys, never a new packed-field or UTF-8 constructor. Original borrowed
child-metadata schemas admit the copied lineage before construction. No hash
substitutes for key equality.

Writer slots own their individual outputs; taking them in catalog order performs
no new row allocation. The consuming map iterator destroys keys and nodes before
its aggregate grant is returned, including early finalization errors. Column and
scratch owners also drop first. A seed private publication retains the original
destination witness through canonical renaming and supplies empty-output commit.
Other unconsumed writers remain owned and clean on failure. Entry-vector capacity
survives until all slots and the Vec are destroyed.

Analyze's optional WriterEstimate contains only Copy numeric/boolean options and
no additional heap payload. Cached scan observations retain no advice; each
returned job-specific profile recomputes it from existing stage statistics after
cloning. Existing admission of stage strings, summaries, headers and previews is
unchanged. Exactness means logical group counts if feasible, not physical file
counts or successful admission. Conditional-parent/multiple-partition estimates
remain unknown. HLL cardinality error is statistical, not a hard upper bound.
No new Job field, mutable prepared configuration, executable profile or Run trust
of prior observations is introduced.

## Experimental retained exact-allocation writer ownership (2026-11-19)

`experimental-retained-exact-writers` prepares only against the already retained
immutable root Dataset. Original parent metadata remains charged during the
existing `exact_plan::Proposal` boundary. The exact tuple catalog reserves a full
BTree node envelope per entry, including key/State/child descriptors and split
headroom, plus actual key, column and quota Vec capacities. The State stores the
existing fixed-size Random object, count and remaining quota; changing that
layout or standard-library node layout requires re-auditing this envelope.
Keys/nodes/quota/column owners drop before their aggregate grant; TupleBuffer's
immutable key scratch retains its separate grant. Original child metadata derives
the legacy stratum JSON domain before its temporary owner drops. No hash replaces
tuple equality and no packed-field constructor/mutation is added.

The original empty PlanWriter is retained across preparation. Setup denial drops
all tentative catalog/writer owners before the seam's cancellation/cleanup check
and original-parent fallback. Reader setup can deny before a charged parent is
available; that outer setup path likewise releases its owners and rechecks before
falling back. There is no source CSV retry or partial statistics commitment.
After setup the existing empty writer's `finish_direct` supplies the original
publication seed; configured final writers retain their existing scalar/chunk
limits and admitted lineage/prefix/serializer ownership. Every emission error is
terminal, including shared admission denial. At EOF, complete remaining/quota
checks precede one stage commit; catalog owners drop before canonical finalization.
This removes row passes only for the selected opt-in shape, not for general
unbounded strata or all execution plans.

## Experimental single-record final catalogs (2026-11-19)

`experimental-single-final-catalog` stores a typed record only when a bounded
fanout Group is exact or every chunk cap is absent. The existing admitted
PublicationName moves from the closed OpenChunk into that record; numeric fields
need no heap owner, and the admitted Group retains lineage until merge. The
Records field drops the name before the existing buffer grant and stage owner.
No per-group catalog DiskFile or BufWriter allocation exists in this mode. The
allocation-free counting serializer enforces the same JSON byte maximum at
source merge as JsonLines, excluding the newline and including escaped names and
lineage. Close and root materialization retain the original non-decoding path;
adding the merge-only limit there would reject formerly valid root records.

The canonical first group materializes one root disk catalog after its CSV sink
has closed, admitting its buffer before allocation and using the same stage and
initial destination witness. Other typed records use the existing path/name
admission and canonical merge helpers. Failed construction, second-record
invariants, materialization denial and cancellation remain private and terminal;
there is no source replay. Codec, snapshot and potentially multi-chunk paths keep
disk catalogs. Writer ceilings and their conservative descriptor guard do not
change. Resource controls compare typed and disk metadata descriptors with equal
open CSV counts; that census is distinct from complete-job performance evidence.

## Experimental single-catalog writer capacity (2026-11-19)

`experimental-single-catalog-capacity` depends on the single-record catalog and
small CSV-buffer controls. When every chunk cap is absent, every admitted writer
has at most one CSV descriptor and no private metadata descriptor. The configured
ceiling becomes sixteen writers per nominal MiB, capped at 16,384; unresolved
Auto conservatively uses 32 MiB. Unix retains 64 descriptors from the soft
RLIMIT_NOFILE bound and allows one per writer. Canonical root materialization
opens its one catalog after closing its CSV. This is a pre-consumption heuristic,
not a descriptor reservation or a complete RSS cap. Concurrent opens/pressure and
wide headers can still cause terminal admission errors with private cleanup.

Jobs with any row/byte/compressed-byte cap retain the previous ceiling and
conservative two-descriptor allowance. The metadata representation may still be
typed when an exact Group proves one chunk, but the selector does not rely on
that operation-specific fact. Codec, observed, WASI and above-ceiling jobs retain
prior selection. Analyze advice recomputes this same bound from current settings;
Run independently checks its current input and never consumes a prior estimate.

## Experimental flush-before-sync ownership (2026-11-19)

`experimental-batched-final-sync` is selected only for Linux native unobserved
plain one-chunk typed catalogs. PublicationWriter flushes and consumes its
BufWriter into the same File; both normal and into_inner error paths destroy the
buffer before returning its grant. SingleRecord retains that File temporarily.
It neither reopens a filename nor duplicates a descriptor. During canonical merge,
the root queue admits Vec capacity before taking any source File; denial leaves
the source owner intact until terminal unwinding. First/root catalog materialization
also transfers the pending handle before replacing the typed record. Other source
queues transfer only after destination capacity admission. Files/Vec drop before
the queue grant and private stage.

After all group buffers have flushed and canonical metadata is complete,
Writers.finish_in_order synchronizes/drains every queued original handle before
returning counts for Analysis. This preserves the existing Analysis/timing boundary.
Publication repeats an empty guard before manifest creation/sync and original
atomic commit/witness. Sync failure or cancellation drops all remaining drain
handles, then ordinary private cleanup runs. No sync or input validation/replay
requirement is relaxed. CSV handles remain at most the writer count; the single
root catalog/publication descriptors use the existing fixed headroom. Buffer
capacity is returned earlier while descriptor lifetime extends. The queue/type's
inline size and Vec storage are covered by actual-size admissions. Default,
Windows, WASI, observed, codec and potentially multi-chunk paths retain prior finish.
