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

The shared engine owns Run dispatch. A limits-only job can serialize records
directly to private publication output. An unsupported job selects existing
exact preparation and execution before consuming input. Explicit preparation
always retains the immutable encoded output snapshot for later confirmation.
Input profiling remains optional and does not validate a later execution snapshot.
The former alternate flexible-policy runner and its build features are removed.
There is no Job policy selector.

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

Native output remains private on the destination filesystem until complete
validation, finalization and the existing no-replacement directory commit.
Browser engine output remains private in its workspace; the browser export module
closes exported files and then commits `CHOPPER-COMPLETE.json`. These lifetimes
remain distinct. Failure and cancellation must clean owned private output, report
cleanup failure and never claim an incomplete browser export is complete.

## Interface and acceptance

`engine::run` and `run_with_memory_pool` provide Run to the CLI and WASI adapter.
Existing `prepare`/`Prepared::execute` remain the explicit exact workflow.
The CLI and WASI `chopper_run` accept configuration; existing prepared execution
consumes the previously prepared object. The hosted UI groups input
analysis, exact preparation and Run in the output plan. Its single Run button
confirms the retained prepared snapshot only while the submitted configuration
is current; edits restore direct Run. Source selection/import loads a bounded
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
A new execution generates internal entropy; prepared confirmation keeps its snapshot. Automatic
memory sizing remains available. Adjacent shuffle/partition fusion is enabled
by default; broader cost-based Auto selection remains separate work. The
[E4 study](performance.md#e4-explicit-probabilistic-allocation-advice-2026-10-28)
retains explicit approximation and withholds generic speed recommendations. These
slices do not select numerical performance thresholds.

The first slice's [executed acceptance and limits](validation.md#limits-only-direct-run-2026-10-27)
cover Windows native execution and bundled Chromium. Other platform/device and
deployment claims retain their previous evidence scopes.

## Investigated next seam: terminal pipeline output

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
