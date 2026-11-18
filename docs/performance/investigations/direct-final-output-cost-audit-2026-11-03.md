## Direct final-output cost audit (2026-11-03)

Decision: **investigate a direct terminal Run target before adding more resident
allocation complexity**. The [source/payload audit](../../evidence-originals.md#sha256-5a0513432af3e4d9b6e5c7becb37450f739358bc83f0e975c89aa8af32430066)
identifies a remaining encoded snapshot pass, not a new measured speedup or an
implemented grouped direct path. It uses the already verified plain-output events
cell and current owning source; six native source files match the exact retained
baseline build attempt. No new engine or browser job was launched.

In [engine preparation](../../../crates/chopper/src/engine.rs), a terminal remaining
operation already emits through `apply_into` into `output::PlanWriter`.
For this path there is no final unencoded Dataset write/read to remove. The
[writer's Snapshot target](../../../crates/chopper/src/output.rs) instead retains encoded
CSV bytes and a chunk catalog. Later `output::execute` opens each chunk range and
copies it into its final output sink. Explicit Prepare needs that immutable
snapshot; Run currently selects it for every nonempty pipeline.

The retained 20,000-event, one-worker, plain-output baseline has eight output CSVs
totaling **1,148,385 encoded bytes**, matching independent file sizes, the manifest
and Analysis. A direct terminal target could eliminate that payload's temporary
snapshot write and later payload copy/read, while retaining the same final CSV
write, serialization, operation passes and required metadata. This is an identified
payload scope, not an observed future saving. Catalog reads, buffered read-ahead,
new direct-record metadata and codec temporaries prevent equating it with an exact
whole-job diagnostic counter difference. `DiskReader` counts returned bytes,
including read-ahead; neither those counts nor file sizes establish physical I/O.

Prepared Analysis diagnostics are captured **before publication**. `Prepared::execute`
returns the existing Analysis after copying; it does not refresh those diagnostics.
The earlier allocation comparisons retain their pre-publication scope. A future
comparison must observe the complete live context/publication lifecycle separately;
subtracting the returned temporary-read counters would miss the removed snapshot
publication reads. This audit does not change diagnostics or reinterpret historical
measurements as a complete I/O census.

[DirectPublication](../../../crates/chopper/src/output/direct.rs) already shares the
chunk writer but deliberately rejects nonempty lineage and names outputs without
a header. Extending only that guard would not support grouped direct Run correctly:
column-index partitions need the admitted original header for filename parity.
A viable experiment needs a separate Run target/result seam carrying publication,
final counts and admitted header-aware naming through Analysis/manifest completion.
Explicit Prepare and flexible prepared-snapshot replay stay separate. Original
operation indices, seeds, exact membership/order, empty named allocations, strict
serialized caps and balanced-group restrictions must survive unchanged.

The [resident metadata revision](../../performance.md#resident-child-metadata-preparation-control-2026-11-03)
prepares the allocation sink's child lineage only. PlanWriter still admits a
chunk-lineage clone and encoded row/prefix capacity, and publication admits names,
paths, writers, codecs and final manifest metadata. Those are concrete later
admission boundaries; this source finding is not a new executed failure control.
Any error after sink emission starts remains terminal, with private-output cleanup
and no replay. Native no-replacement commit and browser completion markers retain
their different contracts.

Start a later bounded implementation comparison with seeded Run, plain output,
one worker and an existing materialized parent, using the shared cap logic.
Prepared publication can compress chunks concurrently, whereas the existing direct
adapter has one active sink; codec concurrency and ZIP member temporaries require
separate accounting before broader eligibility. Browser
[export](../../../ui/src/browser/export.ts) still copies engine result files to the chosen
destination and writes the marker after every writer closes. Removing the engine
snapshot does not remove that export or prove browser throughput.

The source-only runner pass and all identities remain under
`scratch/todo-unattended-20261103/final-output-audit-*`. The first audit failed closed
because it combined source identities from baseline and candidate build attempts;
the revised audit selects the attempt producing the exact retained executable.
Both attempts are preserved; neither launched an engine. No raw upload, deployment,
new strategy/default, benchmark Run, candidate revision, RSS or scale claim follows.
