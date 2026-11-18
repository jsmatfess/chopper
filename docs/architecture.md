# Architecture and development entry points

This describes the current implementation. The [Auto brief](auto-mode-and-maintainability.md)
describes future behavior; [GitHub Issues](https://github.com/jsmatfess/chopper/issues) orders changes. Start with the
[README](../README.md) for setup and [AGENTS.md](../AGENTS.md) for applicable checks.

## Follow a job

1. [Portable configuration](../crates/chopper-core/src/config.rs) validates the
   ordered operations, CSV settings, versioned randomization and explicit limits.
   [CLI](../crates/chopper/src/main.rs) and [hosted UI](../ui/src/app.ts)
   construct that configuration. The ordered
   [Run CLI parser](../crates/chopper/src/run_cli.rs) accepts JSON via
   the admitted decode owner or appends explicit `--step` blocks to a caller-owned
   Job, without changing the fixed-order `split` interface; see its
   [reference](run-cli.md). The shared UI tracks
   edits by revision: a successful Run/Prepare acknowledgement clears changed
   settings only if no invalidation occurred since submission. In-place operation
   edits, imports and edits subsequently reverted still require new preparation.
   New executions obtain internal entropy; no user seed remains in the draft.
   The native interface is the CLI; there is no native HTTP server or embedded
   UI. The hosted interface runs in the browser and communicates with its WASI
   engine worker.
2. [CSV intake](../crates/chopper/src/csv_intake.rs) owns the decoded source,
   strict parser, reusable records, column-count validation and their grants for
   Run, preparation, profiling and first-record inspection. Owned and compact
   records retain their separate uses. Headers transfer under admission without
   copying, and parser failures/EOF are terminal. The profiling batch adapter
   destroys retained slots before the intake grant that covers them.
   [Input profiling](../crates/chopper/src/profile.rs) scans without producing
   outputs. Its advisory cache is separate from exact preparation. Windows source
   invalidation deliberately differs from Unix; see the README.
3. [Engine](../crates/chopper/src/engine.rs) dispatches Run to limits-only
   [direct processing](../crates/chopper/src/engine/direct.rs) or exact preparation
   followed by execution. Explicit preparation retains an immutable encoded output
   snapshot. Ingestion uses the shared CSV intake; original-stage execution and
   fused paths share [operation keys](../crates/chopper/src/engine/keys.rs) and
   logical domains.
   [Retained execution](../crates/chopper/src/engine/retained_execution.rs)
   shares writer lifetime and successful result/stage commitment for optional
   consecutive partitions, streaming chains and partition/shuffle/balanced fusion.
   Each caller retains its own selection and fallback rules; raw ingestion and
   retained-parent preparation/retry keep their separate owners.
   [Rewrite rules](pipeline-rewrites.md) govern which paths can be combined.
4. [Storage](../crates/chopper/src/storage.rs) owns intermediate datasets, sorts,
   merge traversal and temporary accounting. Its
   [adaptive primitives](../crates/chopper/src/storage/adaptive.rs) own resident
   rows, reservations and routing. [Resources](../crates/chopper/src/resources.rs)
   supplies shared admission; it does not impose an RSS cap.
   [Progress phases](../crates/chopper/src/storage/progress_phase.rs) borrow static
   text or share an immutable dynamic allocation and grant through callbacks,
   cached state and clones; response serialization owns independent bytes.
5. [Output](../crates/chopper/src/output.rs) shares encoded chunk/cap decisions
   across snapshot and [direct publication](../crates/chopper/src/output/direct.rs)
   adapters, and shares codecs/finalization/native publication across execution
   paths. [WASI adapter](../crates/chopper-browser/src/lib.rs) exposes
   engine requests to [browser workers](../ui/src/browser). The hosted [session module](../ui/src/browser/session.ts) owns startup,
   requests, guarded job-state updates and retirement. Each private browser
   session retains its worker pair, pending replies and workspace lock; the
   [client](../ui/src/browser/client.ts) adapts browser file access, UI operations
   and history rendering. Browser
   [export](../ui/src/browser/export.ts) commits through completion markers;
   [cleanup](../ui/src/browser/cleanup.ts) respects workspace owners. Native atomic
   directory publication and browser commit semantics are separate contracts.

Physical execution reporting has a shared [implementation contract](execution-observation.md#implementation-contract).
The scoped guard owns outcomes, counter retention and delivery cadence;
`observation/rows.rs` accounts for successful logical-stage row forwarding.
New step kinds must declare their unit policy, and streamed stages account at
every row boundary rather than publishing progress from scattered checkpoints.
A committed operation frontier emits stage-finalization facts separately from
physical attempts. Browser result origins bind input/configuration revisions;
measurement types distinguish counters, work and timeline time. Native completion
requires the engine publication token; hosted completion requires a separately
verified destination marker receipt. The [result/publication contract](browser.md#result-ownership-and-publication-contracts)
owns these boundaries.

## Make a small change

Read the owning specification and nearby tests before editing. Rust tests include
module-local ownership controls, integration tests under `crates/chopper/tests`
and a separately packaged resource-contract reactor. The reactor is never a
production feature. UI tests and generated bundle checks live in
[ui/package.json](../ui/package.json); CI commands live in
[ci.yml](../.github/workflows/ci.yml). Native builds produce the CLI only and
have no Node or UI-bundle dependency. Hosted `ui/dist` contains the WASI engine
and browser UI. Use [browser.md](browser.md) for WASI SDK, browser selection and
clean packaging.

For evidence work, start with the [current performance overview](performance-overview.md)
and [decision registry](performance/README.md), then use the
[benchmark guide](benchmarks/README.md), catalog/export and [strategy review](strategy-review.md).
The registry supports subsystem queries without loading the historical log:

| Subsystem filter | Current implementation and contract | Selected decision records |
| --- | --- | --- |
| `input` | [Portable CSV parser](../crates/chopper-core/src/csv.rs), [specification](specification.md) | [Serial field spans](performance/decisions/serial-csv-spans-2026-11-05.json), [rejected copied parser](performance/decisions/copied-parallel-csv-2026-11-05.json) |
| `storage` | [Storage](../crates/chopper/src/storage.rs), [ownership contracts](resource-policy-research.md) | [Inline spool keys](performance/decisions/inline-spool-key-2026-11-05.json), [validated packed views](performance/decisions/validated-compact-fields-2026-11-05.json) |
| `output` | [Output](../crates/chopper/src/output.rs), [publication contracts](direct-execution.md) | [Quoted spans](performance/decisions/quoted-serialization-2026-11-05.json), [opt-in publication](performance/decisions/plain-publication-2026-11-05.json) |
| `execution` | [Engine](../crates/chopper/src/engine.rs), [rewrite eligibility](pipeline-rewrites.md) | [Retained fusion](performance/decisions/fusion-prepared-spill-2026-11-05.json), [blocked allocation retry](performance/decisions/allocation-retry-pressure-2026-11-03.json) |

For example, `python3 scripts/performance-registry.py --query --subsystem storage --json`.
Read each record's validation summary and source links for actual test/build coverage;
the [validation index](validation-index.md) locates individual structured checks,
and the [validation guide](validation.md) owns supported platform and scale claims.
Use [narrative topic queries](performance/README.md#investigation-narratives) for the
full historical corpus and [observation queries](performance/README.md#normalized-observations-and-validation)
for metrics with source locations and reviewed comparison membership.
Research is reference material, not a
second backlog. Do not reset dirty files or discard failed validation artifacts.
Documentation-only changes require link/command review, not an engine build.

The separate public evidence-site source has been retired. The hosted Chopper
app is the only web UI. [Evidence storage](evidence-storage.md) preserves the
archive and historical reader metadata contracts; those contracts do not imply
that the retired evidence site remains a current product.

## Hosted Run observations

The optional [observation producer](../crates/chopper/src/observation.rs) supplies
fixed direct-Run snapshots and bounded prepared-Run physical facts through WASI stdout and a bounded worker delivery credit.
The hosted [history](../ui/src/browser/execution-history.ts) retains a frozen
configured flow and observed steps independently of worker lifetime. Export and
marker facts originate in the destination adapter, not final engine diagnostics.
See the [scope, bounds and ownership contract](execution-observation.md).

Prepared Run scopes carry original operation mappings through Context into the
actual sorter, resident shuffle, group sink and output writer. The hosted worker
aggregates repeated work by operation/category before coalesced page delivery;
completed and interrupted outcomes retain distinct counters. Explicit preparation
and native Run do not install a physical sink. Unsupported work is marked incomplete
rather than inferred from final diagnostics.

External sort observation follows actual SortRun catalog provenance. Retained
ordered grouping files become explicit reuse inputs; a materialized merge's
output carries its own origin rather than all historical ancestors. Router and
MergeRows keep fixed inline attempt state; callback admission and transport
failure do not change their CSV/temporary ownership lifetimes.

Allocation observers retain fixed membership counts without stratum values. Exact
stratification has a separate observation role; intermediate Dataset producers
carry an inline source identity through parent and downstream scopes. Dataset
writer metrics distinguish framed row construction from logical group metadata.
Balanced range observations distinguish shared metadata scans, terminal emission
and fused sorted traversal. Interleaved membership uses the existing streaming
router; repeated parents fold into fixed summaries without retaining child nodes.
Signature-selected input adapters report decompressed bytes before text decoding.
Output compressor lifetimes report encoded CSV bytes consumed; ZIP assembly
reports actual archive bytes/entries and consumes observed deflate spools. Direct
Run combines its fixed row snapshots with bounded codec facts. The input wrapper
borrows existing admitted readers; output observation stays inline beside the
existing codec/temporary owners.

Observation history and job lifecycle use separate terminal evidence. Captured
worker generations guard success, error and cancellation cleanup continuations;
a late same-Run confirmed fact may enrich retained history without changing job
status. New Runs reject prior identities. The [lifecycle contract](execution-observation.md#interrupted-and-degraded-observation)
and public fault harness cover these races without a production fault API.

The hosted inspector styles one semantic ordered list as graph/list, retaining
selection across default/advanced views. Its fixed card slots and scroll viewport
preserve focus through updates. A worker-owned 128-entry significant-event prefix
is captured before delivery coalescing, with fixed deduplication masks and explicit
omissions. Page history retains that prefix and a frozen bounded configured flow;
no per-row/group/file trace or second graph model is introduced.


Locally retiring a worker supplies no terminal physical measurement. Retained
history therefore keeps the newest attempt's last observed active metrics when
no terminal fact exists, with prior confirmed completed work labeled separately.
An actual terminal fact takes precedence. The [integrated acceptance record](execution-graph-acceptance.md)
connects this behavior to composed lifecycle/codec checks, fixed state/transport/
DOM bounds and independently verified same-build complete-job overhead evidence.
Benchmark-only collection omission and fault routes remain outside production
Job configuration and deployable assets.
