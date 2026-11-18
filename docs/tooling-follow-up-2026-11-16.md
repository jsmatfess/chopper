# Tooling audit follow-up

The source audit was revalidated against fetched main
`de93a7a728fd8652f01627b1d1483409ed499455`, after the separate four-optimization
investigation completed. The separately reviewed tooling branch was then combined
with those optimization commits for [owner-authorized main delivery](shuffle-and-tooling-integration-2026-11-16.md).
Existing acceptance checkouts, campaign receipts, failed
attempts and release records remain untouched. This record describes code and
focused controls, not new browser/device or scale acceptance.

## Browser artifact selection

The old wrapper accepted `--target-dir`, built there, then copied an old engine
from its separately resolved default directory. An isolated fake-Cargo control
reproduces that successful stale copy. The active wrapper now accepts a bounded
set of feature/offline/locking/verbosity options and rejects artifact-location,
package, manifest/config, target and profile overrides before Cargo or output
modification. `CARGO_TARGET_DIR` is the supported directory override. Package,
WASI target and release profile remain fixed.

Independent review found that implicit Cargo configuration could still redirect
the build. The wrapper now binds both target-directory environment forms to one
resolved path before Cargo; controls cover unset/empty directory overrides,
inherited alternate settings and repository configuration with a stale engine.

The Bash entry point delegates to the Node builder, including SDK/toolchain
selection, flags, exit status and resource-test asset routing. It now requires
Node; [browser setup](browser.md#local-development) records that change.
`browser-build.test.mjs` exercises stale sources, redirected arguments, selected
environment target, Cargo failure, resource assets and the Linux Bash alias.
The production export guard remains in force. Historical build source versions
remain available through their recorded Git/evidence identities.

## Focused CI routing

Browser bootstrap and launch-option edits retain browser-only routing. The owning
`browser-acceptance.test.mjs` now imports their focused suites, along with artifact
build controls. Scope tests assert that the selected job executes that entry point
and imports the required suites. Build wrapper changes additionally select tooling,
where portable fake-Cargo controls run on native Windows as well as Linux.
GitHub Actions remains disabled; workflow edits are exercised by local CI.

## Ordinary runner completion

On Linux, the runner observes command exit with PIDFD readiness without reaping
its leader. A lazy bounded-per-record `/proc` census checks for remaining group
members within the step deadline, then the group is terminated before the leader
is reaped. This prevents a reused numeric PGID from being killed. An observed
abandoned member, inaccessible census or deadline failure cannot yield success,
even when the immediate command exited zero. No process-global subreaper is
installed by production code. The test fixture adopts/reaps its own orphan only.

Focused controls reproduce the original false pass, require termination of the
non-detached helper, retain the leader through signalling, deny census failure,
accept joined children and preserve an unrelated group. The runner's own source
hash participates in resume so historical passes without the new implementation
identity must rerun, rather than acquire a new guarantee retroactively.

Review also found that a cleanup exception could bypass the terminal record and
release the batch lock. Cleanup now has one boundary. Signal/reap failure records
the unresolved process identity and full exception, invalidates batch passes,
skips potentially live artifact hashing and retains the lock. Fault controls
require refusal of resume until the fixture positively cleans up its owned child.

These controls establish Linux behavior only. Ordinary Windows/other Unix
completion retains its prior immediate-child scope. Detached/group-escaping
commands remain unsupported; `on_process` observers must not reap the child.
Specialized Job/cgroup custody, retained Original locks, watchdogs and release
verification are unchanged and still required for their profiles. See the
[runner contract](validation-runner.md#local-batch-execution).

## Campaign data and legacy observation reuse

`campaign_native639.py` owns the unchanged selected product/build/receipt pins,
Linux report identities and recorded absolute lineage locator.
`native_scale_identity.py` keeps reusable verification and its required-input
contract. The locator remains explicit campaign data; it is not silently replaced
with a convenient current checkout.

`campaign_host_observer_v1.py` owns the existing reviewed consumer hashes,
function/import exclusions and exact AST normalizations. No exception is added or
broadened. The common host check takes the identical fresh-producer path first;
legacy rules remain a separate frozen campaign compatibility evaluator. Controls
pin the extracted values and normalizer source to the audit baseline, retain the
release-record pins and require both modules in the complete checker closure.
Existing preflight controls still reject observer/writer/import changes.

Changed current checker/runner code requires fresh preparation/host observations;
old evidence is not relabeled and allowlists are not expanded to accept it.
Frozen acceptance sources continue using their own recorded code. No new actual
qualification, scale slot, release artifact, acceptance service or publication
is authorized by this reorganization.

## Historical harness source archive

Nine harnesses (1,038 lines) move unchanged to
[the historical source archive](history/shuffle-harnesses-2026-11-16/README.md).
Two unchanged dependency copies preserve sibling imports. The source inventory
records original and archived paths, exact bytes and hashes. New controls verify
those identities, bounded `--help` imports and current command routing without
running any workload. This is not a net line-count saving.

Three narrative source-link relocations use the existing reversible metadata.
Their original section identities, prose, fenced commands and all raw artifacts
remain unchanged; whole-corpus reconstruction verifies this. The catalog maps
historical command mentions to the archive. [Current commands](../scripts/README.md)
remain distinct from old `full_shuffle_policy` / `flexible_v1` recipes.

## Validation and delivery boundary

Focused controls supplement the existing tooling, preflight, native and browser
checks. Final acceptance uses clean committed-head `scripts/local-ci.py check`
on Linux and native Windows, with exact head/base receipts. Preserve failed
attempts and report actual runtime coverage. Linux helper controls, fake Cargo
and syntax tests do not establish Windows whole-tree lifecycle, browser/device
or scale acceptance. Default production WASM/test-free hosted packaging remains
the final packaging state after browser test builds.

Main delivery of the integrated revision is owner-authorized and uses the existing
guarded local-CI workflow with matching combined-head Linux/native Windows receipts.
Public deployment and release/scale qualification remain separate.
