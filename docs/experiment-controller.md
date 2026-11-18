# Bounded native experiment sessions

The controller executes frozen development batches through
[experiment-cycle.py](../scripts/experiment-cycle.py) and the
[validation runner](validation-runner.md). It performs no engine implementation,
selector/default promotion, browser adaptation or scheduler installation. Model
invocation is opt-in through the separate authenticated CLI adapter. Browser remains
a first-class investigation runtime; its controller
adapter is deferred. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the implementation backlog.

## Run a small control

Use a real installed Python executable rather than a Windows Store alias. Native
Windows is currently the supported controller runtime. Reuse a completed matching
native build record; the planner checks the executable against it. From the root:

```powershell
python scripts/experiment-native-control.py plan scratch/control-001 --build-status scratch/workload-baseline-final/native-build/status.json
python scripts/experiment-controller.py run scratch/control-001/session --config scratch/control-001/control.json
python scripts/experiment-controller.py status scratch/control-001/session
python scripts/experiment-controller.py stop scratch/control-001/session
```

Preparation creates concrete fixtures, Job files and two plans; it launches no
engine. Defaults are 2,000 rows, eight regions and independent 24..128-byte notes,
with the existing complete region partition -> probabilistic 80/20 allocation ->
child uniform shuffle recipe. The two batches alternate sort/auto then auto/sort.
Both jobs in each pair undergo independent field/conservation/group checks and
exact same-version seeded lineage/CSV parity. Preflight hashing and verification
are outside the harness's CLI-launch-through-Run/publication timer.

The control uses five minutes, 512 MiB of sampled owned storage, two batches,
four measured Runs and two predeclared decisions: repeat the approved second pair,
then stop. This is an orchestration acceptance control, not evidence for a selector
threshold or speedup. `--provider file` prepares a decision-needed demonstration;
`--rows` allows 1..20,000 and `--regions` allows 2 or 8. Use a fresh directory.
These options select concrete development cases, not a Cartesian sweep.

## Freeze the experiment space

The session config uses schema version 1, a repository `root`, `first` batch ID,
`provider` (`predeclared`, `file` or `codex`) and 1..12 `batches`. Each batch declares its
unique `id`, `kind` (`initial`, `repeat`, `refine`, `challenger`), earlier `parent`
ID or null, concrete `plan`, disjoint `outputs`, `storage_reserve_bytes` and
1..6 `metrics`. A metric declares `path`, JSON `pointer`, `unit`, timing/resource
`scope` and comparison `cell`. See the generated control config for a complete
example. Extra config/decision/descriptor fields are rejected.

Plans retain the existing fixture/build/toolchain inputs, resources, cost estimates,
question/hypothesis, falsifier/stop rule and dependent correctness checks. Each
measurement must have a dependent verifier. Only development cohorts are accepted.
Held-out correlated wide/dominant groups, late new keys/high fanout and nearly
sorted scores/ties crossing batches remain reserved under the
[investigation rules](workload-investigation.md). New seeds alone do not establish
generalization. Queue a named fanout or working-set question, not kernel rankings.
Account for all complete-job work and separately identify candidate-added work.

All declared artifacts, metric files and native Job output/temp/record paths must
resolve beneath the owned session and the selected batch's output roots before
launch. Paths are explicit and relative to the repository; globs, traversal,
links/junctions and overlapping batch outputs are rejected. Native `run-native`
Job recipes are restricted to the current seeded auto/sort campaign pipeline.
Frozen sources include inputs, concrete plans, native Jobs/fixtures/executables
and controller/cycle/runner/provider identities. Declare transitive inputs;
this is trusted local command execution, not a sandbox or hermetic build system.
Opaque custom commands are useful for tiny controls and remain the plan author's
responsibility for undeclared writes. Do not edit active inputs.

## Budgets, storage and recovery

Defaults are two hours, 20 GiB, eight batches, 32 measured Runs and eight decisions.
Hard configuration maxima are those time/storage limits, 12 batches, 48 Runs and
12 decisions. Each batch has at most six measured Runs, 32 steps and a 120-second
deadline. Repeat lineages allow at most three batches. Longer experiments need a
revised concrete plan and a deliberately revised controller contract; a Run beyond
15 minutes is outside this version. The model cannot expand any of these bounds.

Elapsed session age includes execution, failed attempts, downtime and decision wait;
resume never starts a new clock. Backward clock movement fails closed. Runs are
charged conservatively at batch admission, including uncompleted admitted Runs.
Decisions and batch counts persist. Two consecutive inconclusive decisions,
scientific rejection, repeated identical decisions, unsupported/out-of-scope
choices, correctness failure or infrastructure failure stop further launches.
There is no automatic infrastructure retry; it stops on the first failure.

These bounds apply to one frozen controller session. The
[unattended skill](../.agents/skills/chopper-unattended/SKILL.md) defines time-window
renewal on continuation prompts at the objective level. Start a fresh reviewed
controller session for that renewed window; preserve the old session and its
accounting. A prompt does not alter this controller's immutable deadline or reset
explicit user-specified non-time caps.

Storage admission compares the declared reserve with both actual free disk and a
real recursive byte census of the entire owned session (fixtures, logs, outputs,
temporary files and journal). The runner repeats that census while a command runs
and stops/reaps its tree when the threshold is observed. It records check counts,
observed peaks and boundary byte totals. **This is sampled stop enforcement, not a
hard filesystem quota:** writes can overshoot between polls, a census takes time,
and short-lived peaks may be missed. Logical file sizes are not allocated blocks,
physical I/O or RSS. Choose conservative harness limits/reserves and leave headroom;
if an absolute simultaneous ceiling is necessary, use a separately provisioned
quota volume. No evidence is deleted to regain room, and nothing is overwritten
to retry an attempt. Small checkpoint writes after denial may also exceed the
threshold; the audit remains authoritative.

`session.json` is immutable. `controller-status.json` is an atomic, fsynced
checkpoint containing the decision/accounting event journal. An OS-held exclusive
lock releases automatically on process exit. A Windows Job Object is established
before launching children; if unavailable the controller fails before execution.
Normal deadline/stop/interruption cleanup uses the existing runner. Abrupt controller
exit kills remaining Job descendants. Resume after an ambiguous in-flight launch
records `interrupted-review-required` and never automatically retries it or removes
its runner lock. Inspect/preserve the partial attempt; continuing that scientific
question requires a separately reviewed plan, not editing the session state.
This conservative terminal recovery differs from safe resume at a decision boundary.

`stop` creates a durable STOP marker without taking ownership; the active runner
observes it on its next guard check. Idle sessions observe it at resume. `status`
is read-only and reports current elapsed age/storage as well as saved accounting.
Terminal sessions cannot be restarted by resubmitting a decision. Source/artifact
invalidation stops reuse rather than silently rerunning into existing outputs.

## Decision-provider boundary

[experiment_decisions.py](../scripts/experiment_decisions.py) is the narrow offline
provider boundary. Its input packet follows the
[strict packet schema](../scripts/experiment-packet.schema.json), with a maximum
32 KiB encoded size. Its response follows the
[strict decision schema](../scripts/experiment-decision.schema.json), at most
16 KiB. Packet files contain individual harness samples, units/scopes, n/median/
min/max, correctness status, distinct resource limits, immutable hash/pointer
references and the exact next decision. Raw logs remain on disk. Summaries stay
within each batch/cell; the controller does not pool unrelated boundaries or
treat runner command duration as benchmark time. Failed/incomplete batches yield
the existing cycle failure packet and a terminal journal entry, never timing samples.

A file-provider session exits with `decision-needed`, leaving `packet-NN.json` and
an exact quoted resume command. Read that packet, then create a response such as:

```json
{"action":"stop","target":null,"assessment":"inconclusive","reason":"No useful next approved question.","packet_sha256":"REPLACE_WITH_PACKET_FILE_SHA256"}
```

```powershell
python scripts/experiment-controller.py run scratch/control-001/session --decision scratch/decision.json
```

The hash must identify the current immutable packet. `repeat`, `refine` and
`challenger` can select only an unused, preapproved child batch of that exact kind.
Commands, new strategies, models and runtime settings are not response fields.
Decision files are accepted only for sessions frozen with provider `file`;
they cannot silently override or be mislabeled as a live/predeclared provider.
Predeclared responses omit the not-yet-known hash; the journal binds it at use.
Missing responses leave the boundary durable; invalid responses terminate it.
Exit 0 means a requested stop or decision boundary; exit 1 means another terminal
stop; exit 2 means setup/manifest/ownership rejection. Inspect status for the reason.

The separate [Codex CLI adapter](../scripts/experiment_codex.py) uses the installed,
authenticated `codex exec` route described in the
[official noninteractive guide](https://learn.chatgpt.com/docs/non-interactive-mode).
It reuses saved CLI authentication without copying credentials or adding an API
dependency. From a normal signed-in PowerShell terminal:

```powershell
codex login status
python scripts/experiment-native-control.py plan scratch/live-control-001 --build-status scratch/workload-baseline-final/native-build/status.json --provider codex --codex-executable (Get-Command codex).Source --model gpt-6.1-sol --reasoning-effort high
python scripts/experiment-controller.py run scratch/live-control-001/session --config scratch/live-control-001/control.json
```

An adapter session must explicitly freeze `codex.executable`, `model`,
`reasoning_effort` and `timeout_seconds` (1..120). `xhigh` additionally requires a
nonempty `escalation_reason`; it is not the default. The planner exposes medium/high.
The adapter uses an ephemeral invocation without a shared daemon, read-only sandbox,
disabled shell/search, and zero project instruction bytes. Only the bounded packet
and decision instructions enter stdin; the runner's declared `stdin_file` preserves
the exact bytes without shell quoting or command-line length limits. The response
uses the decision schema; the controller separately checks target/action semantics.
No persistent chat thread, scheduler or engine implementation is created. Failed
auth, unsupported settings, invalid output or timeouts stop without retry, alternate
model or provider substitution. The initial restricted tool environment could not
find the user home; a normal user-context login/status and smoke succeeded. Do not
fix that by copying auth files or weakening the controller's limits.

CLI invocation is another runner plan, with the same storage/time guard and retained
full stdout JSONL/stderr. Model wait counts against session age. Provider-request
events preserve failed/in-flight attempts; an interrupted request is never
automatically reissued. Supplied settings, response/event/status hashes and any
actual returned usage/model are kept in `provider-NN/provider-record.json` and the
journal. Unreported model/usage remains unknown. CLI/system prompt overhead is part
of reported usage; packet size is not a token-savings measurement.

The predeclared queue is fully unattended within its frozen schedule; file mode is
**not** fully unattended adaptive execution. Codex mode makes at most one model
request per meaningful batch and validates each answer before continuing. Retain the
[existing reasoning recommendations](experiment-cycle.md#reasoning-policy): Sol
high for design/interpretation, medium for routine harness work/initial diagnosis,
xhigh only by explicit escalation. Recommendations never change runtime settings.

## Validation and evidence

```powershell
python scripts/test-experiment-controller.py
python scripts/test-validation-runner.py
python scripts/test-experiment-cycle.py
python scripts/test-workload-baselines.py
```

Controller subprocess tests retain their commands' stdout/stderr and partial
session trees in fresh `scratch/controller-tests-*` directories. They include
actual Windows hard-kill/child-exit coverage and exclusive ownership, in addition
to resumed budgets, strict decisions, failures, source/artifact invalidation,
copy-path rejection and preserved evidence. Other platforms skip Windows controller
acceptance; that does not validate their unattended execution.

The initial native controls remain at `scratch/controller-native-001/` and
`scratch/controller-native-002/`; each completed four independently verified Runs,
two seeded parity checks and two predeclared decisions. The latter charged initial
freezing as well as execution: 2.681 seconds and 2,711,930 boundary stored bytes.

The authenticated CLI smoke is retained at `scratch/controller-codex-001/`: four
verified Runs, two parity checks, and live repeat/stop decisions. It consumed
22.291 seconds of session age, 2,759,463 boundary/peak observed bytes, four of four
admitted Runs and two of two decisions within a 300-second/512-MiB session. Packets
were 3,330 and 3,268 bytes. The CLI reported input/output token counts of
13,803/202 and 13,770/188 respectively (reasoning output 88 and 68, retained as
reported rather than added to output). It did not return a model identifier;
`gpt-6.1-sol`/high is the supplied setting, not a fabricated returned identity.
Matching driver bytes/hashes were retained in `driver-snapshot/` before a later
offline-provider audit guard was added. This verifies the live decision path,
not broader adaptive quality or a performance improvement.

Storage observations are lower bounds, not RSS. CLI-owned shared auth/cache files,
pre-existing builds/inputs outside the session and launcher redirections outside
the session are outside its census; choose the owned root/redirections accordingly.
Raw records, all earlier attempts and full runner logs remain local pending selection
for the existing [private archive](evidence-storage.md); no cleanup or upload occurred.
The initial catalog refresh was blocked by unhydrated archived evidence. The PR
CI follow-up hydrated and hash-verified the originals, then refreshed the catalog
and explicitly classified the two new coverage sections without weakening checks.
The next useful scientific question remains lower fanout at the earlier 20,000-row
width/resource conditions, with a concrete falsifier and alternating complete jobs.
