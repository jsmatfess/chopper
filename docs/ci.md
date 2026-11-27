# CI policy and routing

The current public tracker uses [issue #21](https://github.com/jsmatfess/chopper/issues/21) for CI restoration (original issue #79). Historical records below retain original numbering and private-archive source identities.

## Local development and transitional delivery gate

GitHub CI is **disabled by owner decision** because Actions minutes are exhausted.
The pause is enforced by repository-level Actions permissions. The owner must
explicitly request restoration before enabling or dispatching hosted jobs.
Release work uses the local delivery gate during the pause.

`.github/workflows/ci.yml` retains its PR/main/manual trigger declarations and
complete matrix so the same commands remain available locally. Disabled GitHub
execution does not alter those local jobs. Delivery uses `local-ci.py land` with
matching Linux and applicable native Windows receipts as its sole CI gate.
Product, platform, package, browser and release acceptance remain required.

The tooling workflow exercises the library publisher against simulated registry
responses. Use the separate [library release process](maintainer/library-release.md)
to qualify the artifacts and publish them explicitly after source delivery.

[PR #101](history/prior-issues.md#issue-101) delivered the trigger patch.
Its hosted attempt was blocked before job steps by account capacity; no hosted
runner or artifact-service acceptance is claimed. [#21](https://github.com/jsmatfess/chopper/issues/21)
remains deferred, and hosted restoration is not a release gate while this
owner-selected local-only policy is active. Keep the failed attempt and future
restoration requirements recorded in [issue #21](https://github.com/jsmatfess/chopper/issues/21).

The wrapper executes the actual workflow YAML with
[act](https://nektosact.com/usage/index.html); it contains no copy of the check
commands. Install [act](https://nektosact.com/installation/) on each validation
host and Docker Engine in Linux/WSL. `act` and `docker` should be on `PATH`; a
checkout-local `.tools/act/act` (or `act.exe` on Windows) is also recognized.
From the Linux/WSL repository root:

```sh
python3 scripts/local-ci.py install-hooks
git config --local chopper.windowsCheckout /mnt/c/src/chopper
python3 scripts/local-ci.py check
```

Replace the Windows checkout path with the actual independent NTFS checkout.
Follow the [two-checkout workflow](windows-wsl-workflow.md) for native prerequisites.
With your clean feature branch pushed to `origin`, prepare the native Windows
receipt from WSL:

```sh
python3 scripts/local-ci.py check-windows
```

This uses the configured Windows validation checkout and verifies the receipt
against the WSL branch's exact head and base. For manual validation in a native
Windows terminal, run the following at the **same committed revision**:

```powershell
python scripts/local-ci.py check
```

Once review findings are resolved and delivery is authorized, from WSL:

```sh
python3 scripts/local-ci.py land
```

Linux job containers use Docker's init process to reap orphaned subprocesses;
Git staging still requires each owned process group to be absent before returning.

Both `check` and `land` fetch `origin/main`, require clean committed inputs and
require main to be an ancestor of the tested head. Merge or rebase current main
into the feature branch first if necessary. Each run freezes the committed head
in an independent local clone, giving act a self-contained `.git` directory even
when the caller uses a linked worktree. `land` rechecks the Linux workflow and
requires a matching Windows pass whenever native or tooling jobs are selected.
Documentation-only changes need only the workflow's planner/result checks.

`check` and `land` acquire a nonblocking, OS-held lock at
`~/.chopper/local-ci.lock` before installing delivery hooks, fetching, revoking
receipts or starting act. The same user/home on a host shares this lock across
linked worktrees and independent repositories, regardless of checkout or cache
settings. Ownership lasts through workflow execution, Docker teardown, receipt
creation and, for `land`, verification and push. A competing invocation fails
with the lock path and a contention diagnostic; it does not queue or change an
existing receipt. Retry explicitly after the owner exits.

Linux/macOS use `flock`; native Windows uses a nonblocking CRT byte-range lock.
Closing the descriptor or process death releases ownership. File contents and
PID liveness are never used to decide ownership, so a file left after a crash
does not block a later run. **Never delete or replace the lock file**: it remains
in place on release to prevent callers from locking different file identities.
Acquisition rejects an identity changed between open and lock; Windows opens
also deny deletion. Failure to open or acquire the lock blocks the operation.
This coordinates these local-ci entry points under the same OS user/home; it
does not coordinate direct act commands, older wrappers, other users or hosts
sharing a remote Docker runtime. Forced termination releases the lock but does
not certify successful Docker cleanup or a completed validation pass.

`python3 scripts/test-local-ci.py` covers admission through real, separate
local-ci main/runner processes with fake act/shared resources and an explicit
shared fixture lock path. Coverage includes independent repositories and linked
worktrees, check/land contention, teardown and guarded-push lifetime, failure and
process-death release, stale files and replacement races. These tests do not
launch Docker or establish native Windows coverage when run on Linux. The #99
reproduction reached a shared fake-container collision before this guard;
retained real container-name/removal errors support the overlap diagnosis but
do not establish OOM as the cause of the observed exit 137.

The workflow's `local_platform` input owns these coverage profiles:

- `linux`: Ubuntu containers, Linux/amd64; all selected jobs, including browser,
  core and feature checks. Jobs run sequentially to limit local contention.
- `windows`: native Windows act, with `windows-latest=-self-hosted`; selected
  Windows native/tooling jobs, plus planner/result. Docker is not required.
- `macos`: native act on a Mac, with `macos-latest=-self-hosted`; selected native
  jobs, plus planner/result. This is available for additional validation, but
  the temporary Linux/Windows delivery gate does not require a Mac receipt.
- `all`: the default for hosted dispatch; retains the complete hosted matrix.

Local profiles keep the build/test commands and omit GitHub artifact uploads:
act's artifact service does not support the workflow's `upload-artifact@v7`.
Hosted runs retain both uploads. Local passes do not validate that hosted service.

Windows/macOS host execution uses the host's provisioned tools; setup actions run
on hosted runners and in Linux containers. Native runs need Git/Bash, Python,
Node/npm, Rust with rustfmt/Clippy and the platform build prerequisites; Windows
builds need MSVC/C++ Build Tools. WSL and cross-compilation
do not establish native Windows/macOS behavior. A Mac is needed for native macOS
tests. A macOS VM on this Windows PC is not part of the local setup. Missing
platform coverage stays explicit under [validation](validation.md);
release/platform acceptance requirements remain in force.

The wrapper passes the fetched base SHA into the workflow's own path planner.
Use `check --full` or `land --full` for every check in that host's profile.
Full logs, frozen source, tool versions, tracked input identities and failed
attempts are retained under the shared Git directory's `local-ci/attempt-*`, using
the [validation runner](validation-runner.md). Each invocation has a two-hour
deadline; one hour and 20 GiB are planning estimates, not disk quotas. Successful
completion issues a receipt bound to the exact head, main base and platform.
A failed rerun revokes the earlier receipt for that pair/platform. New commits,
dirty inputs, changed records or an advanced main cannot reuse it. Removing old
receipts or their logs requires validation again.

`land` installs the push guard, validates and performs a normal fast-forward push
of the exact tested commit to `origin/main`. It does not switch this worktree to
main, create another commit or force-push. The `pre-push` hook also guards direct
pushes to `refs/heads/main`, checking the actual remote old SHA and both required
receipts. An advanced main stops delivery; update and rerun. Feature pushes need
no receipt. Install the hook in every independent delivery clone; it covers all
worktrees sharing that Git directory. Existing hooks or custom `core.hooksPath`
are preserved: integrate `python3 scripts/local-ci.py pre-push` into the existing
pre-push hook with its original stdin before using `land`.

This is a local guard, not server-side branch protection. GitHub UI/API merges,
unguarded clones and `git push --no-verify` can bypass it. During this phase,
agents must deliver through `local-ci.py land` after the usual review and merge
authorization checks, instead of waiting for hosted CI or merging through GitHub.
Do not report a local receipt as a hosted `CI result` success. If a ruleset requires
that hosted check, record its configuration and temporarily remove only that
requirement; restore it after hosted acceptance. Private-repository plans can
restrict access to these settings.

While local CI is the delivery gate, note that in the PR description and record
Linux and applicable native Windows pass results for the landed head and base.

Gate runs reject user/project `.actrc` overrides, which could select one job or
a dry run, and accept no arbitrary act flags. Default `.env`, `.vars`, `.input`
and `.secrets` files are not loaded. Trusted evidence checks can receive existing
`CHOPPER_R2_ENDPOINT`, `CHOPPER_R2_READ_ACCESS_KEY_ID` and
`CHOPPER_R2_READ_SECRET_ACCESS_KEY` through the environment; only their names enter
act arguments. `GITHUB_TOKEN` can be supplied the same way for authenticated action
downloads. Missing private evidence access fails validation and never issues a
receipt. Preserve the [evidence access boundary](evidence-storage.md#archived-original-alias-resolution);
provide credentials only to trusted code.

When evidence checks are selected, the wrapper first looks for existing blobs in
`scratch/evidence-cache` in the current checkout and the shared Git repository's
main directory. It verifies each blob against the committed evidence registry,
copies exact originals into the isolated snapshot and declares those aliases as
validation inputs. Originals stay outside the delivery worktree and its index.
Act copies this whole isolated snapshot, including the deliberately ignored
original aliases; host caches, tool directories and secret files are not copied.
Corrupt cache entries fail validation; absent entries retain the workflow's
normal authenticated hydration requirement. This reuses local evidence without
copying secret files or changing the workflow's checks.

## Shared check selection

The small `changes` job always tests routing and the local gate, then compares Git trees.
For PRs it compares the event's base commit with the tested merge revision; for
main pushes it compares `before` with the new revision, including multi-commit
pushes. It explicitly fetches the base object and uses a NUL-delimited diff
without rename detection: deletion and addition paths both contribute. There is
no API changed-file limit or last-commit-only shortcut. Diff/fetch failures stop
the planner; a missing base/new branch falls back to full validation. Manual
dispatch without `base_sha` selects every job in the chosen platform profile.
Existing base objects need no network fetch.

`scripts/ci-scope.py` owns the revision diff, filename decoding, and path rules
used by the workflow planner, local evidence staging, and the Windows receipt
gate. Selected checks are the union of all changed paths:

| Changes | Selected jobs |
| --- | --- |
| Ordinary Markdown and `docs/` guidance | Planner and result only |
| Portable-core source | Native Windows/Linux/macOS, combined features, core WASM target, browser, tooling on Linux and Windows |
| Shared engine or vendored source | Native Windows/Linux/macOS, combined features, browser, tooling on Linux and Windows |
| WASI adapter source | Native Windows/Linux/macOS, combined features, browser |
| Standalone Python package and root `pyproject.toml` | Tooling on Linux and Windows |
| UI sources/generated native bundle | Native Windows/Linux/macOS (including UI parity), browser |
| Browser build wrappers and build controls (`build-browser.mjs`, `build-browser.sh`, `browser-build.test.mjs`) | Browser and tooling on Linux; tooling on Windows |
| Other browser acceptance helpers | Browser |
| SMALL Python runner, Windows helper and runner controls (`browser-small-runner.py`, `browser-small-windows.py`, `test-browser-small-runner.py`) | Browser and tooling on Linux; tooling on Windows |
| Benchmark artifacts, historical evidence, decision registry/overview, their linked contracts and evidence tools | Evidence checks |
| Windows dispatcher, local release packaging or Graphify/RTK tooling | Tooling on Linux and Windows |
| Shared migration validator and archived artifact aliases | Evidence checks |
| Workspace manifest/lockfile, attributes/ignore policy, workflow/routing changes, unclassified paths | All jobs |

Evidence checks also verify extracted narrative reconstruction and legacy anchors,
normalized-view coverage, exact historical comparison populations and reviewed
validation bindings. Historical narrative/registry checks run after explicit private hydration;
full corpus checks require exact archived originals. The separate historical-harness
controls validate only their three public source relocations and need no private
corpus access. Checks never regenerate
derived files to accept drift.

The script is authoritative for exact filenames; for example, a benchmark
harness not explicitly classified conservatively receives all checks. These
rules select existing checks, not benchmark experiments. Selected native/browser
jobs keep their complete commands and coverage limits from
[CONTRIBUTING](../CONTRIBUTING.md) and [validation](validation.md). The browser job includes the public execution-graph
and lifecycle fault harnesses; their worker/export injections are test-context
routes, not production build options. The independent graph codec fixture helper
is also browser-owned. The browser job runs independent overhead-gate and
retained-data extension regressions; it does not launch the long benchmark. Unknown paths retain the full-validation fallback. The independent
private-evidence retrieval workflow remains manual. Fork evidence checks retain
their documented private-access limitation; routing never provides secrets to
untrusted fork code. The separate public evidence reader has been retired;
routing has no dependency on its former manifest. Retired reader code paths
receive the same conservative fallback as other unclassified source paths.

`CI result` always runs after the jobs. It requires a successful planner, valid
boolean outputs, and success for every selected job. Intentional skips are
accepted; selected-but-skipped, failed and cancelled jobs fail the gate. Use this
stable aggregate name if configuring a required check; individual matrices may
be intentionally absent on docs-only PRs. The workflow does not change branch
protection settings or grant merge bypasses. Avoid workflow-level path filters
that leave required checks permanently pending.

## Hosted delivery after restoration

When automatic GitHub CI is restored, keep the PR open while checks and reviews run.
Watch the open PR for check/review events, then re-read its head SHA, review
state, conflicts and `CI result` before merging. Require `CI result` success
for the exact current head and resolve outstanding review findings. A watcher
notification is a wakeup, not merge approval. If the head changes, verify the
new head's checks. Merge explicitly after these gates pass; do not rely on
auto-merge to enforce checks when branch protection is unavailable. Stop the
watch before the final handoff. The PR watcher handles open PRs only; post-merge
CI is a separate run and must not be treated as the pre-merge gate. Until hosted
activation and acceptance are recorded, the local delivery gate above applies. After acceptance, retain local development checks and require
the exact-head hosted gate for PR delivery; do not use local receipts to bypass it.

## Restore automatic GitHub CI

Only after a new explicit owner request to restore hosted execution, record
confirmed Actions capacity or the selected next-release requirement in
[#21](https://github.com/jsmatfess/chopper/issues/21) before enabling hosted
execution. An inaccessible billing endpoint, a prepared trigger patch or an
implementation request does not establish this prerequisite. Keep preparation
separate from restoration: local tests and syntax checks cannot establish hosted
runner or artifact-service success.

The selected release satisfied the earlier prerequisite, but the later owner
decision to disable Actions takes precedence. It does not authorize re-enablement.
The retained restoration workflow
now declares these triggers alongside `workflow_dispatch` in `ci.yml`:

```yaml
  pull_request:
  push:
    branches: [main]
```

After explicit owner restoration authorization, re-enable the disabled workflow
with `gh workflow enable ci.yml --repo jsmatfess/chopper` after the intended
trigger configuration reaches main. A disabled workflow cannot be manually
dispatched. [GitHub's disable/enable procedure](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)
preserves its file and jobs. Explicitly dispatch a full `all` run to verify the
retained matrix, browser checks and artifact uploads. Restore any recorded
required `CI result` setting after the complete gate succeeds, and reconcile
this policy, contributor/agent guidance and the owning issue in the same change.

PR updates and main pushes will share the same routing/commands, validating the
merged revision and producing artifacts. Feature pushes without an open PR do
not run CI. Superseded runs for the same PR/branch are cancelled. Local workflow
execution remains useful after hosted CI returns.

### Restoration implementation and operational handoff for #79

The following records preserve the earlier restoration work. The current
owner-selected local-only policy above takes precedence. Pending activation
steps apply only after a new explicit owner restoration instruction.

The owner selected the focused next release in #91 on 2026-11-05 and explicitly
recorded that it satisfies #79's alternative release prerequisite. Actions
capacity remains unconfirmed; capacity confirmation is not an additional condition
once the release trigger is selected. Release selection does not authorize
publication or deployment.

The restoration patch adds the PR/main triggers to the actual workflow. All jobs,
permissions, concurrency, diff planning, local profiles, aggregate gating and
artifact paths remain intact. PR #92's earlier inactive preparation packet did
not restore execution and does not satisfy the hosted acceptance below.

Before activation, API inspection on 2026-11-05 reported CI `disabled_manually` and repository
admin permission. Both `GET /repos/jsmatfess/chopper/branches/main/protection` and
`GET /repos/jsmatfess/chopper/rulesets` returned HTTP 403 with
"Upgrade to GitHub Pro or make this repository public to enable this feature."
Required-check settings therefore could not be read or reconciled; do not infer
that they are absent. Re-read current state during activation and record any
continuing access limitation. Do not change visibility or plan to work around it.
No enablement, dispatch or settings mutation was performed during implementation.

PR #101 is already delivered; do not replay its old delivery command or receipts.
After a new owner restoration instruction, re-read current main, capacity and
settings, then complete these operational acceptance steps in #79:

1. Record the delivered main SHA, current workflow state and settings access.
   Enable `ci.yml` only after explicit owner restoration authorization and verification
   that the intended trigger configuration is on current main.
2. Dispatch `ci.yml` at that exact main revision with `local_platform=all` and
   empty `base_sha`. Record the run URL, event and tested SHA. Require successful
   planning, every native Windows/macOS/Linux matrix leg (including UI tests and
   native bundle parity), combined features, portable-core WASM, browser,
   evidence and tooling jobs, and the aggregate `CI result`.
3. Download and inspect all three native OS/arch artifacts and `chopper-hosted`.
   Native uploads read `target/release/chopper` and `target/release/chopper.exe`
   after the release build; hosted upload reads `ui/dist/` after rebuilding the
   default engine and test-free package. Verify actual artifact contents and
   production export guard, including absence of resource-contract test WASM and
   other test assets. Record names, identities and inspection results. Local act
   omits uploads and cannot establish the hosted artifact-service path.
4. Validate actual `pull_request` and `push`-to-`main` runs, recording run URLs,
   base/before and tested SHAs, selected jobs and aggregate results. For the PR,
   bind the current PR head to the tested merge revision; for main, bind the run
   to the exact pushed SHA. Confirm docs-only skips and a representative code
   change route, full multi-commit diff selection and superseded-run cancellation.
   Focused local planner/gate tests support these checks but do not replace event
   execution. Any head update requires checking the new head again.
5. After the complete hosted gate succeeds, restore any recorded required
   `CI result` setting where supported. Record exact existing/resulting settings
   or the actual access limitation. If branch protection is unavailable, enforce
   the exact-head check explicitly in the authorized merge process. Record the
   completed transition here and reconcile contributor/agent guidance and #79.

### Current activation record

PR [#101](history/prior-issues.md#issue-101) was delivered at
`5de660799b42c5e4129bb05843fd5127a808bc52` through passing Linux and native
Windows local gates against base `77eec95f8aa52f61bae1742bf8d5d3177d32a249`.
At that earlier activation, the workflow API state was `active`. The owner has
since requested local-only CI and the current state is `disabled_manually`.
The full `all`/empty-base
[hosted attempt](https://github.com/jsmatfess/chopper-private-archive/actions/runs/42107563826)
tested that exact SHA but was denied before any job steps by GitHub account
billing/spending capacity. Planner and aggregate jobs failed to start, dependent
jobs were skipped, and no hosted artifact acceptance is established.

The owner must restore Actions capacity before retrying. Preserve this failed
attempt; do not repeatedly dispatch against the unchanged account blocker, narrow
coverage, change account payments/plan/visibility, or report local passes as hosted
passes. Until actual hosted acceptance is complete, the transitional local
`land` gate remains in force. Exact-head PR/main execution and uploads remain
unverified, and #79 stays open.

Keep #79 open until actual hosted criteria are satisfied. Failed, blocked and
unrun checks remain explicit; no local syntax/test pass counts as a hosted pass.
Forks without private originals remain blocked on historical evidence and need
trusted maintainer validation. Retain `pull_request` (never a credential-bearing
`pull_request_target` execution of fork code); never give private credentials or
originals to untrusted code. Private-evidence retrieval remains a separate manual
workflow.

## Changing the policy

When changing ownership boundaries, generated artifacts or routed commands,
update the classifier, focused tests and this table together. Unknown paths must
remain conservative; a failed check is not a reason to narrow routing. Verify:

```sh
python3 scripts/test-ci-scope.py
python3 scripts/test-local-ci.py
python3 scripts/ci-scope.py --base origin/main --head HEAD
```

Use `ci-scope.py --full` to inspect manual-dispatch selection. Actual CI planning includes
the complete event diff rather than just the last commit; local analysis must
choose its intended comparison explicitly. Validate workflow expressions with
actionlint when available. Document-only skips do not replace the command/link
review required by CONTRIBUTING.

The public hosted graph inspection harness runs after lifecycle checks. It uses
real execution with test-only worker pauses and independent artifact checks;
its `test-browser-*` prefix follows the same browser CI ownership rule.

Browser CI also runs focused graph saturation, composed gzip/operation lifecycle
and persistent process-kill cases, plus the deterministic overhead-analysis
regressions. The long performance experiment remains separately bounded and
manual. Its benchmark/analyzer helpers are explicitly browser-owned; unknown-path
conservative fallbacks are unchanged.

The three SMALL Python orchestration paths above also select the tooling job
that runs their Python controls; their browser coverage is retained. The macOS
profile selects neither job for these paths.

Local release-packaging fixture controls run in the tooling job with Python and
Node. Changes to the archive's quickstart template or saved Job select tooling.
The shared browser artifact guard selects both browser
and tooling checks. Packaging controls cover hashes, ZIP inventories/CRC/modes,
source cleanliness and production WASM. Run the [extracted native smoke](release-packaging.md#extracted-native-smoke)
with actual release builds for platform acceptance.

The tooling job also checks the standalone PyO3 crate with its own Cargo
lockfile and checks Python source syntax on Linux and Windows. The tagged
[library release qualification](maintainer/library-release.md) builds and
tests installed wheels on the supported platforms.

## Current owner-selected local-only operation

On 2026-11-05, the owner requested that GitHub CI be disabled and only local CI
be used, with no planned Actions-minute reload. The CI workflow was set to
`disabled_manually`; queued and in-progress run queries were empty. This
supersedes the earlier activation and hosted-release prerequisite while active.
Retain the complete workflow, exact local gates and failed hosted acceptance
record. Restore hosted execution only on a new owner instruction.
