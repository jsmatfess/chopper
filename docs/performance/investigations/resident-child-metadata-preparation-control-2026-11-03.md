## Resident child metadata preparation control (2026-11-03)

Decision: **retain a narrower unapplied feasibility revision, without promotion**.
The [native correctness control](../../benchmarks/allocation-child-metadata-readiness-2026-11-03.json)
and [incremental patch](../../benchmarks/allocation-child-metadata-readiness-2026-11-03.patch)
move child-lineage construction inside the optional resident preparation attempt.
This addresses the observed metadata denial under a matched post-preparation
competitor. It does not establish whole-job benefit beyond existing explicit sort,
arbitrary sink/read admission or a generally safe Auto rule.

The revision reserves the child-owner vector before construction and retains each
child's existing admitted lineage owner. These owners are prepared only when the
sorter finishes as resident Memory; routed/merge readers still have their existing
later admission requirements. During emission each child moves its lineage into
`sink.begin` at the sink's actual current offset, retaining its grant through
`sink.end`. Resident iteration transfers existing row grants. Metadata preparation
denial destroys partial owners and remains inside the original typed-admission
retry boundary. Cancellation and errors once emission starts remain terminal;
no partial sink output is replayed. This adds O(child count × lineage size)
retention and can deny a competing request earlier. It is not free headroom.

The same 2,500-row, 128-byte-payload Linux control uses a live DatasetWriter before
preparation, an 8-MiB shared pool and the original 35/65 membership/domain/strata.
The revised resident preparation retains 850,457 shared bytes, 4,328 more than
the original candidate in the prior control. Applying the same declared rule
leaves a 7,537,895-byte admitted competitor, held through emission, and 256 bytes
free in the resident cell. Both that cell and matched immediate routing now emit
all rows. Unpressured resident, pressured resident and pressured routing outputs
match exact serialized lineage and row frames, fields and IDs, with cleanup.

The competitor amount is recomputed from the revised retained capacity, rather
than reused from the original candidate: the old 7,542,223-byte request would no
longer fit alongside the revised resident owners. This control demonstrates
safe emission under its newly admitted competitor, not admission-domain inclusion
for a fixed set of job and competitor requests, real pressure frequency, or a
performance improvement. Existing routing remains the pressure reference.

A separate 16-destination control denies after constructing one child and checks
release of partial lineage/vector grants. Its successful sibling emits 15 empty
destinations and verifies actual offsets, rows and ordered names. Cancellation
after all children are prepared releases every grant. Original fitting/retry,
first-wide, malformed-input, cancellation and terminal sink-denial controls also
pass. Formatting, workspace/all-target Clippy and locked full workspace tests
pass for the isolated final source. These are synthetic native correctness
controls, with no new timed complete jobs, browser, Windows, RSS or physical-I/O
claim. Twelve measured attempts from the earlier events study remain the session
limit; this is the session's single candidate revision.

Replay from source base `409a017625aa856ecfd73263bc11a0a3a61cb18e`: apply
`resident-parent-retry-prototype-2026-11-03.patch`, then
`allocation-post-prepare-pressure-control-2026-11-03.patch`, then the new patch.
Run `cargo test --locked -p chopper --lib parent_retry_ -- --nocapture --test-threads=1`.
Final source/vendor/embedded-UI and binary identities, plans and full logs remain
private in `scratch/todo-unattended-20261103/metadata-*`; no upload or deletion is
claimed. Prior snapshots and attempts remain unchanged. TODO retains the need
for a defensible complete-plan benefit and broader feasibility proof before any
promotion proposal.
