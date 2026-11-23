# Next focused release acceptance plan

> **Historical plan:** This plan was written for the earlier focused 0.2
> acceptance scope. The current 0.2 product scope is CLI-only on Windows/Linux
> plus the hosted browser UI, with no native server or UI. Its native-picker,
> server-retirement, and selected native UI smoke steps below are historical and
> are not current release requirements. Use [current release notes](../releases/0.2.0.md)
> and [validation claims](../validation.md) for current scope. This document is
> preserved as a record, not as a second backlog or authorization to run work.

Planning for [#87](../history/prior-issues.md#issue-87), coordinated
with release [#10](https://github.com/jsmatfess/chopper/issues/10).
This is a proposed bounded execution specification, not a validation receipt or
permission to start costly runs. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active backlog and specs. Execution
children below must record their frozen manifests before execution; unknown host,
package or toolchain identities are blocking fields, not inferred values.

The owner selected completed validated fixes and the completed hosted execution
graph for the next release. Native CLI Windows/Linux and hosted desktop Chrome/
Edge on Windows are selected. Initial inputs are **10,000,000,000 bytes native**
and **1,000,000,000 bytes browser**, exceeding engine working memory. Current
defaults remain unchanged ([#16](https://github.com/jsmatfess/chopper/issues/16));
experiments remain optional. Guided CLI, server retirement, macOS, mobile,
Safari and Firefox are outside this milestone. No release, deploy, hardware
purchase, infrastructure rental or physical fault injection is authorized here.

## Existing evidence and the remaining claim

Use [validation](../validation.md), its [index](../validation-index.md),
[0.1 review](../releases/0.1.0-review.md) and
[publication receipt](../releases/0.1.0-publication.json) as the source records.
Historical evidence retains its original build, fixture and environment scope.

Concrete reuse candidates (inspect the referenced attempts, not just summaries):
the [0.1 publication receipt](../releases/0.1.0-publication.json) records release
source `7d78706c432f34742bbc29c17be9261002a6816a`, with native/hosted, CI,
human-acceptance and rollback identities in their respective JSON fields. The
[merged graph receipt](../evidence-originals.md#sha256-c1bd573196f9b3cc545246f760b9609606dc4485ec39b9f3984fec29bc19f055)
records source base `db1ae5041fe3a675391037b366c0d1b4b6777e56`; `/checks/11`
through `/checks/15` bind graph parity/lifecycle/inspection/bounds/composed checks,
and `/checks/26` and `/checks/30` bind the two resource variants in the validation
index. Its `/batches` and per-attempt status records own full input identities.
The [integrated graph summary](../benchmarks/execution-graph-validation-summary-2026-11-05.json)
separately owns production asset hashes, source-matched batch locators and the
limited earlier all-feature/core reuse rationale. These are candidate historical
receipts, not certification of current main or the future release. Neither graph
record fills the Windows installed-browser or selected scale cells below.

| Intended claim | Credit already earned | Smallest remaining acceptance |
| --- | --- | --- |
| Native CLI Windows/Linux correctness | 0.1 published-source CI and later native contract checks; source identities are recorded in validation | Match relevant identities to final Linux/Windows receipts; rerun affected contracts through the existing CI gate, then the two selected scale jobs on each OS |
| Hosted graph in Windows desktop Chrome/Edge | Completed graph implementation and integrated acceptance, including 42 parity families, lifecycle/inspection/bounds; latest merged-source hosted checks used bundled Chromium on Linux | Installed Chrome and Edge final-asset correctness/lifecycle/resource checks on Windows; two scale jobs in each browser; no new overhead study |
| Large inputs exceeding working memory | Historical narrow billion-row native points and smaller external-sort jobs | Selected final-build direct and composed workloads below; neither a count-only split nor an earlier build certifies all operations |
| Real picker/external output usability | Completed owner-reported 0.1 native/hosted success, cancellation and malformed-input smoke | Selected small new-package smoke with actual dialogs and ordinary filesystem destinations; record browser versions this time |
| Publication and recovery | Completed 0.1 served-hash parity, injected File/OPFS export, lifecycle/recovery, rollback retrieval and publication | New-package hashes, final packaged smoke, recovery packet and separately approved served-asset verification belong to #91 |

Do not reopen 0.1 acceptance. In particular, older gap prose does not undo the
later owner acceptance or publication. Existing automated File/OPFS handles are
valid engine/worker/marker evidence, **not actual system-picker or external-device
evidence**. Physical device faults, origin eviction, quota exhaustion on real
hardware, disk deletion faults and power loss remain untested unless a specific
future claim selects them. No universal current-build billion-row, complete RSS,
device durability, throughput or exhaustive pipeline claim follows from this plan.

The graph's [accepted path inventory](../execution-graph-acceptance.md) already covers
codecs, strata, probabilistic assignment, interleaving, resident shuffle and
inspection with small fixtures. Reuse matching identity receipts or run the owning
checks on changed inputs. Do not multiply each path by both large shapes. The
historical overhead result remains scoped to its recorded source/browser; this
release plan makes no new Windows performance claim.

## Freeze before execution

The execution child prepares a validation-runner manifest and a human-readable
claim-to-step ledger in a new owned attempt directory. #91 supplies the included
fixes/version and proposed immutable release source and artifact identities; its
closure/publication is not a prerequisite for testing. Record:

- Clean source commit/tree, resolved dependency locks, all features (default
  product builds), source-input digests including complete vendor directories,
  and build scripts/configuration. Native CLI builds have no embedded UI asset.
  Follow the
  [runner input contract](../validation-runner.md); a commit alone is insufficient.
- Native executable and proposed archive hashes; hosted file inventory/hashes,
  production WASM exports and absence of test assets. Test reactors have separate
  identities. Restore the default engine and test-free hosted build after tests;
  compare the restored inventory to the proposed package before scale/smoke.
- Resolved Rust/C compiler/linker, target, WASI SDK, Node/npm/Python executables,
  versions and hashes; harness/verifier sources, generated Job JSON and fixtures.
  Do not copy an old build's tool versions into a fresh receipt.
- Actual OS build/architecture, host/CPU/RAM and admission ceiling; native versus
  WSL environment; physical volume/filesystem, mount, free capacity and exact
  input/temp/output paths. WSL results identify Linux coverage, never Windows.
- For each browser, installed channel, executable path/hash and actual running
  version, Windows build, fresh owned persistent profile, origin, secure-context
  and COOP/COEP status, storage estimate/persistence permission and physical
  profile/output volume. Missing Chrome or Edge is blocked, with no substitution.
- Starting cache state as uncontrolled unless actually controlled; no storage
  speed claim. Record process/RSS samples only as observations, separate from
  reservations, logical I/O and physical I/O. Browser worker count is one.

For each existing receipt record its locator, exact step/attempt and relevant
input/artifact/executable/environment/dependency identities, reuse verdict and
reason. Reject missing/failed/latest-incomplete receipts or changed relevant
identities. A passed small graph fixture is reusable for that contract, never
for a new large shape. CI path selection alone is not a final-release coverage
ledger: applicable final checks must be present or explicitly blocked. Parent
serializes real local CI and delivery using the host lock; this planning slice
runs neither. Under the later [owner-selected local-only CI policy](../ci.md),
GitHub CI is disabled and #79 restoration is deferred rather than a #91 release
gate. Re-enablement or hosted dispatch requires a new owner instruction; product,
platform, browser, package and release acceptance remain required.

## Deterministic fixtures and selected jobs

Proposed fixture format `release-acceptance-v1` is public synthetic data only.
UTF-8, comma delimiter, quote `"`, header, LF, no BOM, no empty-line skipping;
uncompressed input/output. This scale format intentionally has no embedded CSV
metacharacters; tiny adversarial fixtures retain Unicode, quotes, multiline,
empty-field, CRLF/BOM/encoding coverage through existing contracts.

For width W, the header is ASCII `id,region,` followed by `p` repeated W-11 times
and LF: exactly W bytes. Row i, starting at zero, is a 12-digit zero-padded decimal
ID, comma, `r` plus decimal i modulo 8, comma, then the lowercase hex SHA-256 of
UTF-8 `release-acceptance-v1:` followed by ordinary decimal i, repeated and
truncated to W-17 ASCII bytes, then LF. Each row is exactly W bytes, with unique
IDs, eight balanced region keys and no private records. All IDs fit 12 digits.
Raw encoded bytes equal UTF-8 decoded text bytes here; heap/string layouts differ.
The generator must assert this formula and refuse existing paths. Freeze source,
parameters, actual byte/row counts and streaming SHA-256 before every Run.

| Job | W | Native data rows / total bytes | Browser data rows / total bytes | Pipeline |
| --- | ---: | --- | --- | --- |
| D: narrow direct | 100 | 99,999,999 / 10,000,000,000 | 9,999,999 / 1,000,000,000 | No operations; limits-only Run, preserve order |
| G: wider composed | 1000 | 9,999,999 / 10,000,000,000 | 999,999 / 1,000,000,000 | partition(region) → exact assign(treatment=80, control=20, no strata) → uniform shuffle |

Both use `limits.bytes=10000000`, `limits.rows=1000000`, no compressed-byte cap,
`compression=none`, `memory_mb=64`, `workers=1`, `max_files=4096`,
`max_record_bytes=4096`, grouping `auto`, explicit seed
`release-acceptance-v1`, policy `seeded_v1`, RNG `blake3_counter_v1` and algorithm
`adaptive_v1`. Use existing Job field names (`type: assign` and
`strategy: uniform`); validate generated JSON before launching. No Prepare before Run.
Native `temp_bytes=107374182400` (100 GiB) with a fresh owned temp directory;
browser `temp_bytes=8589934592` (8 GiB) using the worker's OPFS directory.
These are intermediate caps, **not total filesystem limits**; staged snapshots,
private/published output, profiles and verifier data need separate space.
The header must itself fit the strict CSV cap. Additional per-chunk headers mean
total exported bytes exceed input bytes. The 4096 file cap is ample for these
roughly 1,000 native / 100 browser byte-capped CSVs, including grouping tails.

This is eight large successful Runs maximum: D/G on Linux, D/G on Windows,
D/G in Windows Chrome, D/G in Windows Edge, sequentially. No repetitions or
unconditional budget/worker/codec cross-product. Run tiny controls first, D before
G on each environment, and stop on failure. Compare same-input Linux/Windows
CSV names/order/hashes; compare same-input Chrome/Edge similarly. Native and
browser large fixtures have different row counts, so cross-size parity is invalid.
Use a shared tiny fixture for native/browser same-version seeded parity. Record
actual spill/merge observations for G; if it does not exceed resident execution,
the external-memory path claim is unmet rather than inferred from input size.

## Independent verification and the tooling prerequisite

Source inspection confirms that `scripts/workload-baselines.py` preparation and
verification and `scripts/run-workload-browser.mjs` reject fixtures over 16 MiB.
The Python verifier retains all rows; `ui/tests/workload-baseline.ts` returns whole
base64 output arrays. Removing those guards would not produce a scale-safe test.
The existing `workload_entities.py` generator has a different variable-width
format and cannot promise the exact sizes above. No current harness is claimed
to execute this specification unchanged.

The tooling child should reuse validation-runner provenance, browser launch/
production-worker seams and independent CSV/manifest readers. Add only:

- A streaming fixed-width generator for the formula above and explicit D/G Job
  construction. Keep existing small workload limits intact.
- A streaming independent verifier that reconstructs expected fields from each
  ID without importing the generator's row constructor. Use a disk-backed ID
  bitmap to reject duplicates and omissions (largest bitmap 12,500,000 bytes),
  exact row/byte/header counts, CSV caps, manifest config/lineage and safe unique
  names. Stream digests; reject unexpected extra outputs and truncated manifests.
- For D, exact global ID order and independently calculated greedy row/byte
  boundaries. For G, region membership, largest-remainder exact quotas per region
  with configuration-order tie breaking, parent totals and within-arm ordering parity.
  Track allocation membership by ID and seeded output hashes across OS/browser
  peers. Quotas/conservation and parity do not independently reconstruct random
  draws or prove uniformity; existing versioned tiny randomization regressions
  retain that role. Do not label an aggregate digest alone exact conservation.
- A public-Run browser adapter using the actual production page/workers and a
  selected local File, with an explicitly injected OPFS output handle. Read
  exports in bounded slices (at most 1 MiB per transfer), never one complete
  array/base64 result; check the full marker schema/count and exported bytes.
  Record bounded graph snapshots and actual spill facts. Keep this adapter and
  test hooks outside deployable assets. It cannot certify an external destination.

First self-check with at most 2,000 rows per width (under 3 MiB total fixtures),
temporary directories and verifier mutation controls: duplicate/missing/changed
ID or field, wrong region/quota, chunk over cap, changed order, bad manifest and
missing/invalid marker. Include known tiny quota answers and exact size
arithmetic. No native/WASM builds or real browser launches are necessary for
these initial generator/verifier controls; browser adapter integration is a later
prerequisite using the selected frozen product. Record unsupported checks as gaps.

## Bounded execution, faults and stop rules

These are conservative planning ceilings, not measured throughput predictions.
The executing parent must accept the concrete manifest and capacity inventory;
do not start if #80 or CI owns the host, or any required identity is unfilled.

| Batch | Planning estimate | Hard attempt ceilings / storage preflight |
| --- | --- | --- |
| Tooling self-check | 5 minutes, under 3 MiB fixtures | 10 minutes, 64 MiB owned artifacts; no product builds |
| Native scale per OS | 2–6 hours including generation/verification | 8 hours total; generation ≤1 hour per fixture, each Run ≤2 hours, verifier ≤1 hour; ≤160 GiB owned tree, start ≥200 GiB free on every involved volume |
| Browser scale per channel | 1–4 hours including verification | 6 hours total; generation ≤30 minutes each, each Run ≤90 minutes, verifier ≤30 minutes; ≤24 GiB owned profile/data/export tree, start ≥40 GiB physical free and ≥16 GiB usable origin quota after the engine reserve |
| Small installed-browser contracts | 30–90 minutes per channel | ≤2 hours/channel, ≤64 GiB owned tree with 56 GiB sampled stop; prior charges retained; build capacity separate |
| Real-user smoke | 30–60 minutes total | ≤90 minutes; selected Windows campaign ≤1 MiB combined synthetic inputs and ≤32 GiB owned artifacts, with 24 GiB sampled stop |

The [owner's disk-monitor/storage amendment](../history/prior-issues.md#issue-105)
supersedes the earlier 672 MiB/32 MiB smoke allowances. Windows smoke now permits
4 GiB hosted per-attempt growth, 2 GiB profiles and a 512 MiB harness temporary-disk
guard; native smoke reserves 4 GiB future growth separately. SMALL preparation
allows 2 GiB cumulatively and 64 MiB in new preparation namespaces. Old frozen
namespace limits and every prior charge/failure remain historical; no directory
change resets the campaign. New smoke/SMALL writes and launch must leave at least
128 GiB physical space after declared future growth, using a fresh volume sample;
their live guard stops below that physical floor.
The 1 MiB synthetic-input cap, input identities, memory, engine temporary limits,
cancellation and cleanup requirements remain binding. Individual JSON/read/parse
memory bounds are separate. This does not authorize publication/deployment.

Separate final build/CI estimates and limits come from their owning #91/CI
manifests, not these scale ceilings. Overall large-job ceilings are eight Runs
and 28 hours (two 8-hour native and two 6-hour browser batches); installed-browser
contracts add at most four hours. Shared identical fixtures may be copied with
hash verification. Generate one shape at a time; retain receipts/digests after
verification, and archive or explicitly approve deletion of completed owned data
before the next shape. Never delete failure artifacts or unrelated files to fit.
No automatic retry/expansion after a failure; diagnose and obtain a revised plan.

Enforce deadlines with the existing runner and stop/reap owned processes. Disk
observations may take at most 30 seconds, target a 15-second cadence and start at
most 45 seconds apart. Capacity facts expire 90 seconds from their original
observation start; heartbeat/polling cannot renew that timestamp. Require a
completed capacity observation before Run, and a new post-write census plus
joined sampler before original ownership release. Stop before Run if these
bounds cannot be enforced. Keep hot identity, memory, process/census and
cancellation watchdogs at their separate bounds while disk work is pending.
Input-custody age remains separate (60 seconds for the selected smoke path).
Stop at the owned-tree ceiling or the applicable physical floor: smoke/SMALL
128 GiB; scale retains native 20 GiB and browser 8 GiB, plus browser usable quota
below 2 GiB. Samples can miss transient peaks; log
them as sampled bounds, not complete physical-I/O/RSS accounting. Also stop on
nonzero exit, unexpected source/package drift, no progress for ten minutes,
verification mismatch, cleanup failure, storage denial, browser disconnect or
host reservation conflict. A timeout/denial/blocked launch is never acceptance.
Retain logs, partial outputs, identities, reason, exact checkpoint and unrun steps.

Fault checks use small fixtures, not additional large Runs. On native Windows/
Linux select malformed input after valid rows, preexisting destination rejection,
temp-cap denial and cancellation during processing and private publication;
require no successful destination, no overwrite and owned staging cleanup where
the filesystem permits. Reuse matching contract fixtures/receipts rather than
invent timing sleeps. Hosted installed-browser checks reuse the
[browser acceptance sequence](../../AGENTS.md#build-and-verification): standard,
graph parity/inspection/bounds, direct and composed lifecycle, bridge/peer cleanup,
temporary/persistent termination, persistent process-kill prepared/direct/composed,
both resource variants and default production restoration. Use declared runner
steps for the actual owning commands, with native/UI/core checks supplied by the
matching final CI receipts. Do not rerun the long graph overhead experiment.

For hosted cancellation/export failures verify processing cleanup, CSV close,
marker write-before-close, committed marker-before-reply, abandoned-workspace
cleanup preserving completed exports and fresh retry. Distinguish injected worker/
writer faults and process termination from actual quota, device or power failure.
An absent/invalid marker is incomplete; cancellation after committed completion
does not revoke success. The historical dialog smoke plan included native UI
pickers. Current native acceptance is through CLI filesystem paths; hosted
browser file APIs are covered by hosted acceptance. Native UI picker steps in
this plan no longer apply.

## Execution children and handoff

Children are specifications, not permission for expensive execution. Each links
this plan, records a separate receipt and keeps #87 open until selected claims
are reconciled. Readiness for scale requires the tooling child **and** a frozen
#91 candidate manifest, available named host/storage/browser capacity, parent
scheduling and review of estimates. #91 remains open for packaging/publication;
do not add a circular dependency on its closure.

| Child | Deliverable and completion evidence |
| --- | --- |
| [#102 tooling preparation](../history/prior-issues.md#issue-102) | Tiny verified generator, streaming independent verifier, bounded browser export adapter and concrete runner manifests; negative controls and explicit remaining integration prerequisites |
| [#103 native acceptance](../history/prior-issues.md#issue-103) | Frozen Linux/Windows receipts, D/G output verification/parity and small cleanup controls, or explicit unmet platform/shape claim; blocked by #102 |
| [#104 Windows hosted acceptance](../history/prior-issues.md#issue-104) | Installed Chrome/Edge final-build contracts, D/G verification/parity, graph/spill facts and valid markers; separately label injected handles; blocked by #102 |
| [#105 actual filesystem smoke](../history/prior-issues.md#issue-105) | New-package real dialog/ordinary destination steps, exact package/OS/browser identities, success/cancel/malformed outcomes; distinguish owner reports from automated receipts |

At handoff, #87 records child links and selected completed/blocked/deferred claims.
#91 consumes the claim ledger, exact source/package identities, failed attempts
and release-note limits; only it owns the later packaging, rollback and approved
deployment/served-hash checks. A shortfall requires fixing/rerunning the affected
claim or explicit owner reconciliation of scope before publication. It is never
converted silently into a general support claim.
