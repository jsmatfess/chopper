## Native experimental plain publication delivery (2026-11-05)

**Decision: deliver `experimental-plain-publication` as a native opt-in Cargo
feature, keeping serial defaults.** The
[delivery validation record](../../evidence-originals.md#sha256-c59b918777c2930f230a0dcf2739571ab09c763b5dbc16ffa2ebedb2bec8510b)
tracks functional checks of the actual feature. The
[unchanged production Run comparison](../../performance.md#plain-publication-overlap-unchanged-production-run-transfer-2026-11-05)
and [10-MB-cap comparison](../../performance.md#plain-publication-overlap-10-mb-output-cap-2026-11-05)
supply the existing scoped timing evidence; this delivery adds no timed jobs,
Auto threshold or broader performance claim.

The feature reuses the existing Context workers and compressed-publication
memory ceiling for plain prepared files. Batch task capacity is additionally
bounded by remaining planned files, avoiding unused slots for one-file and final
partial batches. Independent snapshot readers, per-file flush/sync, admitted
names/paths/buffers, joined workers, ordered manifest records and atomic directory
commit retain their contracts. Concurrent ownership may still deny later work;
no retry or admission-parity guarantee is added. Default plain publication,
limits-only direct Run and WASM keep their current paths. Execution graph work
and default/Auto integration remain separate.

Fresh Linux formatting, default/all-feature Clippy and workspace tests pass.
Focused real Run tests pass with the feature disabled, enabled alone and enabled
through all features. Native Windows release feature contracts and a packaged
CLI smoke compare exact one/four-worker CSV bytes, ordered output records and
logical Analysis fields, with independent ID/field/cap checks. A one-file case
and fifteen-file case verify actual retained batch capacity, including the final
partial batch. Cancellation and a typed shared-memory denial after a written
prefix preserve private-output/temp cleanup and final pool release. The shared
pressure case deliberately leaves 32 KiB free; it is a functional failure control,
not a feasible-capacity estimate or performance observation.

Complete build-input identities include both vendor directories and embedded UI
assets. Full runner manifests, statuses, logs and native executable remain in
private `scratch/experimental-plain-publication-20261105T0325/` and its native
Windows counterpart. The record retains their hashes and actual command results.
The initial Windows manifest used unsupported absolute artifact globs; the runner
stopped after building the CLI, leaving that attempt incomplete. Its status/logs
and binary are retained. A fresh manifest using relative artifact paths reruns
all four native steps to a terminal pass; no source change was needed.
The full local browser acceptance suite is not rerun for this native-only feature;
normal required CI remains the merge gate. Working-allocation reservations are
not RSS measurements.
