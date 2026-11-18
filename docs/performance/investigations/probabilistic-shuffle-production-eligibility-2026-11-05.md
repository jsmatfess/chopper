## Probabilistic shuffle production eligibility (2026-11-05)

**Decision: retain the real prepared-spill candidate; withhold delivery eligibility.
A bounded retained-parent integration specification is warranted, as proposed below.
It is not an approved implementation or experiment. Keep [#83](../../history/prior-issues.md#issue-83)
open.** Existing evidence supports a useful pass reduction and scoped feasibility,
but does not establish integrated retry, public graph truth or a current-production
complete-job benefit. This reconciliation changes no runtime, policy or default.
[#80](../../history/prior-issues.md#issue-80)'s independent buffered-row-copy
investigation, #91 packaging and #104 browser harness work remain separate.

### Evidence eligibility and completed findings

Review baseline is `7b1b82d112b027464caa995b7f37884b20357792`. Live #83 body
and #80 body/comments were read on 2026-11-05; #83 had no comments. Graphify's
local graph was absent, so scoped source reads were used. No experiment, build,
benchmark, Windows dispatch, real CI gate, hosted action or authenticated download
was run. Parent later restored exact archived aliases from the existing local
cache for the derived checks below; this is not new R2 readback.

The five compact reports linked below are locally present. Their full SHA-256
identities were checked against the existing
[prepared-spill decision](../decisions/fusion-prepared-spill-2026-11-05.json).
Referenced public patch bytes were checked against the
[catalog](../../benchmarks/catalog.json). Parent subsequently verified all 655
archived aliases against the registry while restoring their exact local cache
bytes. Availability does not mean that every historical private build/source
bundle, log or CSV was inspected, or that any old binary matches main. No
privileged endpoint was queried. Historical acceptance remains scoped to its
recorded identities; cache restoration adds no performance observations.

- [Native semantics](probabilistic-shuffle-fusion-native-semantic-and-failure-controls-2026-11-03.md)
  established stratified membership, repeated original shuffle indices, named
  zero groups, forced primary collisions and external tie refinement, plus public
  pre-emission denial/cancellation on Linux and native Windows. These are completed
  controls on their recorded candidate; they do not prove its new retry seam.
- [Real owner](probabilistic-shuffle-fusion-prepared-spill-owner-control-2026-11-05.md),
  [report](../../evidence-originals.md#sha256-04bf720fcc13a5ec164d7d74842eef42c2bab2baa08caa48ef666558681911e4)
  and [patch](../../benchmarks/probabilistic-shuffle-prepared-spill-2026-11-05.patch)
  restore the fixed before/after-observation peer cases on Linux/Windows and
  retain fitting parity/traffic savings. Partial construction and live-owner
  cancellation release cleanly. This supersedes the storage remedy, not the
  [late-peer falsifier](probabilistic-shuffle-fusion-peer-after-buffer-observation-2026-11-05.md):
  observing available capacity never reserves a future writer.
  The earlier [live-owner completion counterexample](probabilistic-shuffle-fusion-live-owner-completion-counterexample-2026-11-03.md)
  also remains preserved: the baseline completed while the then-current candidate
  typed-denied. Fixed-point repairs do not erase either failure history.
- [Changed-owner cost](probabilistic-shuffle-fusion-prepared-spill-working-set-cost-2026-11-05.md)
  and [report](../../evidence-originals.md#sha256-6dfef6e55af954491dbd57cb55cde67cf041b34ed2d060c6d8172eb001872c7e)
  retain four native Windows ABBA jobs, n=2 per variant. Exact sample locations
  are `/records/observations/0` through `/records/observations/3`; scope is
  `/records/scope`, resource summaries `/records/summaries`. Both paired elapsed
  differences favor the candidate, with overlapping ranges. The clock is explicit
  Prepare plus Execute through publication, excluding CLI startup, fixture/hash,
  verification and cleanup assertions. It is not current Run/export acceptance.
  Logical traffic/files fall while tracked workspace peak rises. No historical
  observation-only timing is pooled with this changed-owner panel.
- [External-wide acceptance](probabilistic-shuffle-fusion-external-wide-owner-acceptance-2026-11-05.md)
  and [report](../../evidence-originals.md#sha256-323acadca34ea8076365a8098d2b541d5d4e4c7d2b0c5792fae290321189675d)
  cover the unchanged owner spilling/merging on one fixed wide shape. Independent
  fields/IDs/groups/caps and canonical CSV hashes, ordered records and 17 logical
  Analysis fields match across Linux/Windows. More candidate runs remain visible;
  no width threshold, speed result or universal completion follows.
- [Changed-owner persistent Chrome](probabilistic-shuffle-fusion-prepared-spill-browser-acceptance-2026-11-05.md)
  and [report](../../evidence-originals.md#sha256-54334de75d25e17cc06f8b8c018fe99aeb476cd3c0de2d9c15eb356bcc9f8e0d)
  establish the fixed events-transfer parity, 35 default contracts, bridge/peer
  cleanup and 22-job forced-termination lifecycle, including the live prepared
  writer checkpoint. Preserve failed setup/build attempts and their reuse bounds.
  This is OPFS picker export on installed Chrome, not external-device, Edge,
  arbitrary pressure or new production-path graph acceptance.
- [Spill/temp controls](probabilistic-shuffle-fusion-prepared-spill-temporary-failure-control-2026-11-05.md)
  and [report](../../evidence-originals.md#sha256-a8cc0819aea3ce7d2758fe52275d0f24bf5cf99d3e8017614399bac97e36a1ee)
  establish zero-byte and partial-prefix write-denial cleanup on both native
  runtimes, plus exact six-job fixed temporary-budget acceptance. Both variants
  complete at that point. Lower candidate charged temporary peak does not prove a
  wider completion domain or whole-job failure recovery.

Contract durations and diagnostic sort clocks are not speed observations.
Reservation peaks are working-allocation accounting, not RSS; logical temporary
reads/writes are not device traffic. Charged temporary peaks exclude other
private/public filesystem overlap. Independent peaks cannot be summed. The small
old Windows panel is a reason to specify integration, not a promotion threshold or
an estimate of current-platform benefit. None of these completed studies is queued
for wholesale repetition by this document.

### Source-verified production and owner boundary

Current [engine.rs](../../../crates/chopper/src/engine.rs) preparation loops over
retained Dataset operations. `following_shuffles` includes Partition and exact
Assign, excluding AssignProbabilistic. `apply_into` traverses parents;
`apply_parent` sends probabilistic allocation to `StreamingGroups`, then a separate
uniform stage sorts the children. Terminal work uses `output::PlanWriter` (encoded
snapshot); intermediate work uses DatasetWriter. Run with operations reaches
preparation under the [direct-execution contract](../../direct-execution.md).
This candidate is neither ingestion fusion nor direct terminal publication.

The retained [initial candidate patch](../../benchmarks/probabilistic-shuffle-fusion-2026-11-03.patch)
extends that dispatch and adds `streaming::fused_probabilistic_shuffle`: existing
Membership chooses original allocation, admitted child domains supply the last
following uniform index, and GroupRandom sorts allocation index plus random key
and collision domain. Named children emit in configured order, retaining source
IDs and normalizing only physical ordinals/keys. The private non-test selector
returns true; it must never be copied as a production default. The patch is an
historical base, not a patch proven applicable to current main.

Current [Membership](../../../crates/chopper/src/engine/streaming.rs) owns charged
counts/columns/weights and uses categorical_views with original IDs/stratum fields.
Current [storage.rs](../../../crates/chopper/src/storage.rs) Sorter has no prepared
spare; flush separately reserves I/O before sorting/writing, then releases row
storage and adds/merges the run. The prepared-owner patch adds an alternative
constructor returning Result and a spare containing buffered SpillFile before its
Reservation field. Constructor admission precedes retained rows. Flush transfers
that writer and grant, writes/finalizes, releases rows and performs add_run/merge
before renewing the spare. Resident return/cancellation drops unused spares.
Writer destruction must precede its buffer grant on success and every error path.
Temporary path/file ownership remains separately admitted and atomically created.

A real spare protects that writer, not all future catalog/merge/decoded-row/path
allocation or renewal. It adds a live file/path and 64-KiB buffer; it can deny
construction earlier, displace a peer, create unused files after the last flush,
and alter spill count/merge cost. A smaller observed row target is still only a
target. Preserve live-owner denial counterexamples and temporary write failures;
there is no proof of universal completion or unchanged competitor admissibility.
See [resource ownership](../../resource-policy-research.md#controlled-temporary-construction-and-reopen-2026-10-22)
and [rewrite eligibility](../../pipeline-rewrites.md).

### Proposed bounded implementation seam — authorization still required

Restrict an initial opt-in implementation to the seeded-v1 retained Dataset path:
adjacent AssignProbabilistic followed by one or more uniform/seeded-auto shuffles,
keeping the last shuffle's original index and explicit earlier elisions. Permit
existing strata and zero allocations. Exclude exact assignment, interleaved,
Fisher–Yates, flexible policy, intervening operations, raw ingestion and direct
publication. Unsupported cases execute ordinary stages. No learned size threshold,
public automatic selection, new RNG/version or distribution-equivalent substitute
is justified. Keep other fusion selectors' precedence explicit and unchanged.

Introduce a plan at the retained-operation dispatcher and use
[exact_plan::Proposal](../../../crates/chopper/src/engine/exact_plan.rs) per parent.
The plan owns original allocation/last-shuffle indices; the parent retains source
identity, lineage and replayable rows. Its preparation owns Membership, admitted
domain vector, composite keys, real prepared Sorter and all sort/merge completion
needed to return a prepared traversal. It takes no sink and commits no stage stats.
The emission method receives that traversal and named-child counts; it preserves
original entries, exact flags, order, source IDs, collision domains, logical
stages, Analysis fields and encoded output caps through existing sinks.

Only typed local/shared memory admission denial during preparation is initially
retryable. Drop every tentative owner before Proposal's Context check; cancellation
or cleanup failure overrides retry. Retry only this un-emitted parent through the
original allocation then child shuffle stages with original domains. Earlier
parents remain once; do not retry the whole Dataset or raw CSV. Bound fallback to
one original attempt, including its work in costs. Sink setup denial before any
parent may select original stages after rollback. Invalid schema, decode, I/O,
temporary-budget and cleanup errors remain terminal in the initial scope.

Define emission entry before any child metadata/sink mutation. Once entered,
**every** error is terminal, including admission, final sorting accidentally left
there, child metadata, row writes and sink finish. Do not infer safety from zero
CSV rows: a child group or earlier parent may already be committed. Aggregate
logical stats exactly once across fused/fallback parents, including empty groups.
Keep stage-capacity admission and immutable Analysis payload owners intact.

### Proposed public graph mapping and independent gates

[Execution observation](../../execution-observation.md) governs the optional sink;
existing graph acceptance does not cover this new plan. Use original allocation
and last-shuffle mappings for composite physical sorting, actual membership counts
only under allocation, and elision annotations for overwritten uniforms. Strata
sampling does not create partition work. Connect actual retained Dataset input,
resident sort or spill/merge origins, named-child traversal and real Dataset/CSV
materialization. Do not invent the removed allocation Dataset, reuse arrows,
parallelism, a source rescan or completed work from overall success.

Preparation denial/fallback must retain failed or handed-off attempt identity and
actual repeated visits; partial membership never masquerades as completed groups.
After-emission failure is terminal, cancellation interrupted, lost facts unknown.
Keep existing fixed record/category/source/event/transport limits and callbacks'
short admitted lifetime. Prefer existing categories; any new encoding requires a
separate bounded native/WASI/wire/worker/UI audit. Collection disabled, denied,
rejected or saturated must preserve required work and exact output.

A following implementation review needs the following independently checkable
receipts, scoped to the changed seam rather than rerunning old matrices:

- Native Linux and Windows: independent field/ID and group/stratum membership
  checks, exact pinned CSV/order/lineage/output records/logical Analysis, encoded
  BOM/header/quoting/multiline caps, empty children, repeated shuffle indices and
  forced ties across resident/external traversal; test actual mixed fused/retried
  parents and downstream consumers. Record source/vendor/assets/build identities.
- Owner/retry controls: domain-vector denial; partial spare construction; peer
  arriving after construction and during renewal/merge; first/later-parent denial;
  clean typed rollback then exact original success; original-path failure; bounded
  no-retry after child metadata, first/last rows and sink finalization. Cancellation
  during preparation/merge/emission and unlink failure must override retry with
  charged orphan reporting. Verify peer-only residual grants then zero after its
  drop, independent reader offsets and file identity.
- WASI: portable builds plus resource-contract execution of the new proposal,
  owner and rollback boundaries. Compile success alone is insufficient. Browser:
  actual observing/disabled Run through new resident, external and fallback paths,
  independent CSV/manifest/marker reads, bounded truthful mappings and omission,
  worker death/replacement, cancellation and cleanup with a live spare. Preserve
  native atomic publication versus browser closed-file/marker confirmation.
- A current-baseline complete-job comparison only after correctness and separate
  experiment authorization: rebase without disturbing #80, freeze identities and
  the stronger current Auto baseline, candidate opt-in, fixture, runtime/storage,
  worker/memory/seed/caps, timing boundary, retry control and finite decision rule.
  Start with the existing 200k development question and a fitting/denial control
  only if they can change the decision. Include preparation, actual retry,
  observations and usable publication/export; keep verification outside the clock
  and account for it separately. No historical speed estimate substitutes for this.

### Remaining decision questions and stop criteria

The minimal unresolved questions are whether current ownership can support bounded
pre-emission rollback without reducing required completion, whether public facts
truthfully describe fused/fallback work within existing bounds, and whether that
integrated plan benefits a named current workload after extra ownership and retry
cost. All three remain open. Existing completed semantic, wide, lifecycle and
scoped temp controls answer earlier questions and are not newly missing evidence.

Stop implementation eligibility on changed seeded bytes/membership/caps, duplicate
emission/stats, leaked or prematurely released ownership, swallowed cleanup failure,
unbounded retry/telemetry, or any after-emission replay. Stop a later performance
proposal if its frozen benefit/resource rule fails; retain the result and ordinary
path, without retuning or expanding a matrix. A peer/renewal counterexample can
narrow or reject the proposal; it cannot be repaired by relabeling a denial as
success or weakening current contracts.

Thus #83 has a reviewable reconciliation and proposed seams, **not completed
acceptance**. Missing authorization is a bounded implementation/experiment mandate
and available host time; missing evidence is the integrated retry/graph/owner and
current complete-job decision above. Hosted dispatch remains owner-blocked by
billing; this document authorizes no hosted settings, billing, deploy or archive
writes. Parent review, actual delivery gates and issue disposition remain with the
parent. Future work stays only in [TODO](../../../TODO.md).

### Verification of this reconciliation

Six lightweight evidence test scripts pass, as do narrative reconstruction,
existing decision-registry validation, resolver index freshness, selected report/
patch hashes, relative-link/heading review and diff whitespace checks. These are
document/evidence checks, not runtime acceptance or receipt reuse.

Parent restored 655 exact archived aliases from the existing hash-verified local
cache, then regenerated narrative compatibility navigation, strategy audit,
catalog, registry overview and normalized views. The complete read-only evidence
check sequence passes, including the unchanged 38-cell historical synthesis.
Both parent review axes found no substantive issue in the reconciliation.
This resolves the worker checkout's missing-corpus blocker without credentials or
authenticated downloads; it does not establish fresh remote archive readback,
new runtime acceptance or production eligibility. Exact local delivery gates
remain required before main integration.
