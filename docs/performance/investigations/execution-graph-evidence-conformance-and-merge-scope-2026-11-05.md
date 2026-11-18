## Execution graph evidence conformance and merge scope (2026-11-05)

**Decision: preserve the recorded acceptance within its original build scope.**
The [126-job finding](hosted-execution-graph-126-retained-jobs-accepted-2026-11-05.md)
belongs to the execution-graph source completed at local commit
`488525ef0c6465f994b39247c8237ff70c8eb3ca` and the exact WASM/worker/app
identities in its [unchanged report](../../evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830).
Integrating `origin/main` at `80894c6f0ba13ce1fa940e87002a97450b0dff06`
changes CSV, spool and publication code. Those measurements do not establish the
merged engine's performance. No performance jobs were rerun for this migration.
Correctness checks on the merged source are separate validation attempts; their
durations are not overhead samples. Native Windows/macOS and installed desktop
Chrome/Edge coverage are not established by this Linux/WSL integration.

At the merge checkpoint there was no dirty work or active runner. A backup ref
retains the old committed source. The local preservation manifest under
`.tools/evidence-conformance/pre-merge-preservation.json` pins 287 retained
artifacts, including frozen plans, raw observations, interrupted/failed attempts
and runner statuses. The earlier production assets were copied byte-for-byte
before rebuilding; their supplemental manifest is
`.tools/evidence-conformance/pre-merge-builds/manifest.json`. Neither old manifests
nor old reports were relabeled. Raw originals and private hydrated historical
aliases remain local and ignored; this migration uploads nothing.

The three graph findings were registered as separate investigations in the
`execution-observation` family. Their original section identities and prose are
retained, with only relative Markdown link relocation. The earlier
[72-job unmet result](hosted-execution-graph-first-complete-overhead-gate-unmet-2026-11-05.md)
and [108-job unmet result](hosted-execution-graph-108-job-precision-result-remains-unmet-2026-11-05.md)
remain visible. All original slow observations stay in their original matched
cells. The accepted report retains post-gate extension selection and conditional
bootstrap limitations; this migration adds no population, tail or sequential
confidence claim.

The [reviewed comparison locations](../../benchmarks/execution-graph-comparison-locations-2026-11-05.json)
pin all eight cells' explicit baseline/candidate raw SHA-256 identities, physical
JSONL lines and `/elapsed_seconds` clock. Every locator was checked against the
literal original row, matching within its raw cohort and block. This primary
clock ends at the successful Run reply after destination export/marker;
`/public_complete_seconds` includes later cleanup/polling and remains separate.
The original context records pin build, harness, fixtures, browser executable,
resource/configuration/seed, OPFS/profile and cache conditions. They remain exact
references rather than inferred row dimensions. Missing metadata stays unknown.

Normalized extraction is deliberately narrower than comparison eligibility:
`/samples/*` projections are summaries and `/runs/*` diagnostic projections are
diagnostics. Neither supplies new independent executions or eligible speed
samples. Local `.tools` raw originals are outside the public catalog; the
reference manifest is not a normalized comparison binding. That unsupported
comparison layout remains explicit rather than promoting summary copies.
Compact `/batches/*/commands/*` validation rows retain unknown status when the
command omits one, even when its parent says passed or its exit code is zero.
Use the receipt importer on each retained runner batch to inspect all actual
statuses, logs, identities and latest-attempt flags; an older pass cannot
establish acceptance after a newer failure.

The registry's acceptance outcome records the earlier observation. Its
informational disposition and unapplied delivery independently state that this
is local evidence, with no origin push or main delivery. Future authorized main
delivery must use the current local-CI gate with the exact committed head/base
and its selected Linux/native Windows receipts. This investigation does not
waive that gate or authorize another performance study.
