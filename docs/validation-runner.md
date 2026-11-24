# Local validation batches

## Actual-host acceptance preflight

Release acceptance is held for the prerequisites in [specification #176](history/prior-issues.md#issue-176).
Run preparation on the intended host before qualifying a complete tiny journey;
then freeze the qualified harness for its batch. The active order is in [GitHub Issues](https://github.com/jsmatfess/chopper/issues).
Preflight and tiny receipts do not replace scale acceptance or authorize publication.

```sh
python -B scripts/acceptance-preflight.py preflight REQUEST.json FRESH_EVIDENCE_DIRECTORY
```

The request uses schema `chopper-acceptance-preflight-v1`, a `profile` of `native`,
`small` or `browser-scale`, the actual `host_os` (`Linux` or `Windows`), an absolute
`plan` path and its `plan_sha256`. Native selects an existing native plan; SMALL
selects its existing config; browser-scale selects its frozen identity packet.
Use the selected real Python interpreter and native Windows dispatch where applicable.
The checker is bound separately from the selected product, producer and harness;
it can inspect their frozen files without copying new code into those snapshots.

Declare positive integer `limits`: `seconds` (at most 900), `read_bytes`, `visits`,
`capture_bytes` and `storage_bytes`. There are no automatic increases. Capture needs
at least 4 KiB and storage must reserve capture plus 64 KiB for failure metadata.
Select sufficient allowances for the complete declared inventory and repeated
validation reads. A metadata census rejects a known full-inventory read or visit
shortfall before payload hashing. Preparation uses the existing validation runner with a separate
deadline and fresh logs; it never calls a session, claim, acceptance window or
workload entry point. Windows preparation owns a separate kill-on-close Job.

The machine result is `result.json`; the command also prints a concise status.
The runner preserves its admitted `worker-result.json` unchanged; the separate
parent result records supervision and aggregate usage. Rejected unsafe/existing
destinations receive a machine error on stdout and are never created or overwritten.
It binds the request, checker sources, actual host and selected input identities,
and retains diagnostics and remaining runtime obligations. A failed, blocked or
incomplete result cannot authorize execution. Windows native admission remains
blocked until its existing proof requirements are met.

The parent and child share one allowance. The meter conservatively charges full
file size for each Python file open, including repeated reads and imports, plus
metadata visits and directory entries. Supervisor admission, polling and final
receipt work are included; maximum polling/receipt costs are reserved before
giving the remainder to the child. Cleanup remains available after exhaustion.
This is not physical I/O accounting. Fixed Git and compiler probes have
separate retained duration/capture records; compiler subprocess reads are covered
by the selected complete input inventory, rather than Python-open accounting.
Capture and output storage stops are sampled by the supervising runner and may
overshoot. A deadline or resource failure retains an incomplete/failed result;
it never increases the allowances or turns a component check into qualification.

Selected final-package Native UI and actual-picker candidates may place preparation
evidence only at their declared flat C: case root's `preflight` child, keeping native
generated data on NTFS. The candidate must be exactly `caseRoot/candidate.json`;
the fresh plain output must remain disjoint from every immutable input, runtime
directory and controller source. Other protected-root exclusions remain unchanged.
For these two profiles the checker verifies the requested candidate hash before
output admission and takes protected roots from the owning schema's explicit
controller/input/runtime/owned fields. Actual-picker retained roots come from its
hash-bound custody document. Sampled volume/capacity/custody observations are data,
not extra source roots; a drive explicitly declared as an input remains protected.

Generated hosted packets keep immutable inventory and storage-accounting roles
separate. A closed input forest retains all its file pins and membership checks
when a later authoritative ledger already covers that exact root. Only roots
outside that ledger's covered union are fresh allocations; materialization and
after-exit accounting add them once. Nested or differently spelled aliases still
deny admission. Carry the latest charged floor rather than reverting to an older
ledger to preserve input declarations.

SMALL quota receipts are judged at completion of their bounded file read: a
concurrent append may be newer than a clock captured before that read. Keep the
original observation timestamps and freshness limits. Quota denials retain the
exact path/PID, comparison time, sample age, observed capacity and required floor.
Independent observation streams full binding rows, including their input
manifests, under the same 32 MiB bound as the owning receipt consumer; it never
adopts process identities from those input manifests or historical data.

Runner identities retain the declaration's absolute or root-relative key form.
Consumers use the runner's `identity_record` resolver for Windows/POSIX spelling,
then check the expected digest; they do not reconstruct keys with `relpath`.
Multiple aliases, a conflicting resolved path or a directory record deny admission.

Local JavaScript helpers are compiled together without evaluating them. Known
package definitions are resolved from the selected UI dependency tree and required
Chromium/compiler APIs are checked without launching a browser. Optional unused
package backends are not bundled. Dynamic imports and live ownership, capacity,
quota, picker/permission behavior, full cold guard timing and cleanup remain
explicit obligations for the complete actual-host tiny journey. Recheck mutable
conditions at execution; a preparation receipt is not permanent permission.

The [#177 preparation record](history/prior-issues.md#issue-177)
covers the selected Linux native plan and native Windows SMALL/Chrome config,
using identical checker source contents. Windows checks all 3,270 declared files
(950,666,301 bytes for one hashing pass), the selected compiler/package APIs and
an owned preparation Job with no remaining child processes. No browser, product
workload, acceptance window or scale slot was started. Complete native/hosted
tiny journeys and the full cold guard remain prerequisites under #178/#179.
The [hosted qualification guide](maintainer/hosted-tiny-qualification.md) routes #179's
explicit modes through their existing controllers and records the common
actual-picker preflight integration hook. Source controls do not establish
actual-host qualification.

## Local batch execution

For experiment hypotheses, reasoning routing and compact evidence handoffs, use
the [coded experiment cycle](maintainer/experiment-cycle.md). It wraps this runner without
adding model calls or replacing harness measurement/verification.
The [native experiment controller](experiment-controller.md) adds cumulative session
budgets and decision boundaries through this runner's optional guard callback.
The callback checks before/during commands (at most 0.2 seconds between waits,
plus census time); a guard denial stops/reaps the child and retains its attempt.
The Windows controller also establishes an unnamed kill-on-close Job before any
children start, so abrupt controller exit kills its remaining descendants. This
containment is opt-in; standalone runner lifecycle and resume remain as below.
JSON checkpoints flush and fsync their temporary file before atomic replacement;
this protects process-crash recovery, not arbitrary filesystem/power-loss behavior.

Run sequential checks with durable logs and conservative resume:

```powershell
python scripts/validation-runner.py scratch/validation-plan.json scratch/validation-batch
python scripts/test-validation-runner.py
```

The first command also resumes a batch. Use a new directory when changing its
plan. The runner writes the original manifest, full numbered stdout/stderr logs,
attempt exit codes, durations, input/artifact SHA-256, file metadata and resolved paths,
resolved executable hashes, environment digest and atomic status after every
command. Environment values are not recorded. Failed attempts remain intact.
Commands run directly as argument arrays from the declared root, without a shell.
The [validation receipt importer](performance/README.md#validation-receipts-and-claims)
queries every retained attempt and never-attempted step without executing commands.
Optional per-step `coverage` metadata declares contract references, runtime, browser
and features; it is retained in the manifest and does not change execution or
establish verifier adequacy. Imported snapshots do not replace runner reuse checks.
Optional `stdin_file` names a file relative to that root and must also be a declared
input. It is opened as raw bytes for the command and participates in the same
identity/resume checks; omitted stdin keeps the existing inherited behavior.
Use explicit executable paths when reproducibility depends on toolchain selection.
Windows Store app aliases may be executable but unreadable for hashing; select
the real installed executable in the plan in that case.

A plan looks like this (replace the absolute root and Python path locally):

```json
{
  "root": "C:/path/to/chopper",
  "batch_timeout_seconds": 120,
  "estimated_seconds": 5,
  "estimated_disk_bytes": 1048576,
  "toolchains": {"python": "3.13.14; record executable and version used"},
  "features": [],
  "fixtures": ["tiny subprocess controls"],
  "steps": [{
    "id": "runner-controls",
    "argv": ["C:/path/to/python.exe", "scripts/test-validation-runner.py"],
    "timeout_seconds": 30,
    "inputs": ["scripts/validation-runner.py", "scripts/test-validation-runner.py"],
    "artifacts": [],
    "depends": []
  }]
}
```

Declare all relevant inputs, including dirty/untracked files, complete vendor
directories, build scripts, lockfiles, configuration and fixture/toolchain files.
Patterns are Python pathlib globs relative to the root. Each pattern must match;
matched directories include all descendants, including empty directories.
Exact absolute regular-file paths are also supported for inputs and artifacts on
another volume. Absolute paths are literals, never glob-expanded; directories are rejected.
Directory symlinks are rejected: declare the actual directory or explicit file
paths instead. Missing or unreadable inputs stop the batch before command launch.
For a native CLI build include `Cargo.toml`, `Cargo.lock`, `crates/**/*`,
`vendor/**/*`, any build configuration and externally selected tools. Native
builds do not embed UI assets. Hosted builds additionally declare `ui/src/**/*`,
UI package/lock files, HTML/styles, hosted build scripts and their shared helpers,
the bundled sample inputs `examples/customers.csv` and `examples/quickstart-job.json`,
the inline formula help source `docs/formula-functions.md`,
plus the WASI engine and toolchain inputs. Exclude output/cache paths
from input patterns; list required built files in `artifacts`. Record actual
toolchain versions, features, fixture identities, dependencies, expected disk/time
and deadlines before starting. Estimates are scheduling limits, not acceptance
thresholds. The runner does not discover a build's transitive inputs for you.

A pass is reusable only when it is the latest attempt for that step and its
inputs, artifacts, executable, environment and dependency attempt IDs match.
The runner's own source SHA-256 also participates in reuse; older receipts
without that identity require a fresh attempt and remain preserved unchanged.
Missing or unreadable declared artifacts fail the command. Source identity changes
across a command invalidate it; a change before a later resume also prevents reuse.
The runner checks file metadata before and after hashing and rechecks successful
steps' inputs before reporting batch completion. Later commands that mutate earlier
inputs invalidate those steps and their dependents.
Use a frozen source snapshot for runs where concurrent edits could be reverted
between identity checks. Do not edit active build inputs. This is validation
provenance, not a complete hermetic build system or benchmark harness.

The first failed, timed-out, interrupted or invalidated command stops the batch;
later steps remain incomplete. Resume retries incomplete steps and affected
dependents without overwriting earlier logs. The batch deadline applies to each
invocation. Timeout/interruption terminates the owned process group on Unix or
process tree on Windows, then reaps the child. Detached descendants are outside
this small runner's ownership: checks must not daemonize.

On Linux, ordinary completion also checks for accidentally abandoned group
members. PIDFD readiness observes exit while the leader remains unreaped, a lazy
`/proc` census reads at most 4097 bytes per process (accepting at most 4096)
within the command deadline,
and group termination occurs before reaping that identity anchor. An observed
remaining member fails the attempt even if the immediate child exited zero;
inaccessible census metadata or deadline exhaustion also denies completion.
This requires Linux PIDFD support and an accessible matching `/proc` namespace.
The census and cleanup are part of the attempt duration, not free observation.
`on_process` callbacks may observe the child but must not wait for or reap it.

This is not a cgroup/Job custody certificate or a process-global subreaper.
Detached/session-escaping descendants remain unsupported. Ordinary Windows and
other Unix completion retains its existing immediate-child scope; use the owning
specialized controller for stronger whole-tree supervision. Linux controls do
not establish native Windows lifecycle coverage.

If signalling or reaping fails, the attempt records `cleanup_unresolved` with
the captured process identity and full exception. The batch retains `runner.lock`,
invalidates its passes and skips potentially live artifact/input rechecks. Resume
must refuse while that gate remains. A status-write failure also leaves the gate
held. The recorded Linux PID/group/start ticks aid investigation; they do not
authorize later signalling of a possibly reused numeric PID. Resolve ownership
and positively complete cleanup before manually removing this lock, preserving
the failed attempt. Specialized controllers still require their own custody and
release checks.

A force-killed runner
can leave a running attempt and `runner.lock`; inspect the PID in that file,
stop/reap any surviving owned commands, then remove the stale lock before resume.
Never remove a live runner's lock. Only one process can own a batch directory.

For unattended Windows use, launch this command with `Start-Process` and
`-WindowStyle Hidden`, redirecting launcher stdout/stderr to separate files.
The runner owns command cleanup; no recurring automation is installed. Hand off
the batch path and `status.json`, including current attempt and incomplete count.
The broader accumulated-change validation checkpoint remains separate work.

## Optional immutable status observation

Python callers may pass `run(plan, batch, guard=..., observe=callback)`. The
callback receives a freshly constructed `StatusObservation`: an immutable tuple
of `AttemptObservation(id, attempt, status)` values and a `terminal` boolean.
It contains no references to mutable runner state or input/artifact maps. The
runner emits an initial checkpoint, running and completed attempt checkpoints,
and a terminal checkpoint after the final input/dependency recheck. Each follows
its durable rich-status write. Callback exceptions propagate and stop execution;
the full status, manifest and existing attempt logs remain available for audit.
The callback is synchronous and must bound its own work. Construction visits
attempts only, independently of retained input/artifact-map size.

Ordinary callers omitting `observe` retain their existing writes, CLI, guard,
resume and provenance behavior. Observation adds no command-line option and no
controller recovery mode. A terminal checkpoint can invalidate earlier passes;
observing a completed attempt alone does not establish final batch success.

The SMALL adapter in `browser-small-runner.py` owns its separate no-resume
transport: `runner-observation.json`, at most 8192 UTF-8 bytes and 16 ordered
attempts (the existing selection ceiling). Schema `chopper-small-runner-status-v1`
binds `runner_pid`, the SHA-256 of the **entire** `runner-plan.json`, and `owner`
(the approved unique reservation, also included as `small_observation_owner` in
the execution plan). It carries `sequence`, `terminal`, and exact ordered
`{id, attempt, status}` entries. Sequence starts at one, increments for each
actual callback, and covers initial/running/completed/terminal transitions.
The worker publishes the initial observation before waiting for parent readiness;
it transfers its original Job handle only after that readiness acknowledgement.

The parent reads at most 8193 bytes to detect overflow, closes the file before
JSON decoding, and rejects unknown/duplicate fields, malformed/oversized data,
wrong identities, wrong step order or attempt numbers, unknown states, impossible
prefixes, regression, checkpoint substitution and terminal coverage gaps.
Identical repeated reads are allowed without refreshing progress. Atomic
replacement can coalesce intermediate transitions; sequence and prefix validation
must still describe the exact approved non-retrying order. Only the terminal
input recheck may invalidate an earlier pass. A worker result requires a matching
terminal observation covering every successful step and matching observer cleanup
receipts. Missing/failed observations deny; live supervision never falls back to
loading cumulative rich status.

Only this transport retries Windows sharing errors 5/32, at most three operations
with 5/10 ms sleeps. The reader holds no persistent file handle. Exhaustion and
other I/O errors propagate. Observation reads are inside the existing 800 ms
sampling task and independent one-second watchdog; no limits or channel clocks
are extended. Progress refresh requires actual completed steps **and** matching
observer cleanup receipts; metadata, quota and unchanged observations do not
refresh it. Full rich status, raw input and artifact maps and manifests are retained
unchanged. Fake controls live in the existing runner/SMALL Python suites already
run by the tooling job; native Windows protocol qualification remains separate.

## Opt-in protected SMALL parent adapter

[`browser-small-runner.py`](../scripts/browser-small-runner.py) is a separate,
explicitly approved native Windows caller; see its [configuration, commands,
containment transfer and evidence limits](browser.md#executable-parent-producer).
It invokes `run(plan, batch, guard=..., observe=...)` inside a worker while an external
host-lock owner produces the atomic heartbeat and enforces a hard watchdog.
The narrow `owned_windows_job()` API queries this session's actual Job flags
and bounded PID list and exposes its handle only for supervisor duplication.
It fails without native Windows containment; configured flags/labels are not
capabilities. The supervisor queries the duplicate through
`browser-small-windows.py`, retains it through cleanup, and transfers the worker's
original ownership before commands start. Ordinary runner CLI/default CI and
resume behavior above remain unchanged. SMALL never resumes or retries.

`python3 scripts/test-browser-small-runner.py` and
`node --test scripts/browser-small-bootstrap.test.mjs` are fake-only controls.
The explicit native fake probe and all installed contracts remain parent-owned;
see the browser guide for the retained probe command and platform limits.
