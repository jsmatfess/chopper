# Coded experiment cycle

For bounded unattended native Windows batches, predeclared or authenticated CLI
decisions and durable decision-file resume, use the [experiment controller](experiment-controller.md).
Its session budgets span runner invocations; its storage checks are sampled,
not a filesystem quota. Browser adaptation remains deferred.

The model defines a question, implements necessary changes and interprets evidence.
Code performs the declared repetitions, stops on failures and produces a compact
handoff. Do not exchange agent messages between successful commands. The
[investigation handoff](workload-investigation.md) defines the initial jobs;
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the active backlog and specs.

## Continue toward the end objective

For authorized unattended end-to-end work, use the repository's
[chopper-unattended skill](../.agents/skills/chopper-unattended/SKILL.md).
Its objective-level continuation policy treats experiment results and merged PRs
as checkpoints. This cycle's failure/falsifier rules still stop the affected
batch; the agent diagnoses and reviews a separate next attempt when justified.
The controller's terminal states and runtime/budget bounds remain unchanged.

## Reasoning policy

The policy is executable data in [experiment-cycle.py](../scripts/experiment-cycle.py):

```powershell
python scripts/experiment-cycle.py policy
```

Use Sol high for experiment design, semantic implementation and decision-grade
interpretation; medium for routine harness changes and first failure diagnosis.
Escalate explicitly to xhigh for a difficult proof, tricky fallback or unresolved
diagnosis when extra reasoning has a plausible benefit. Execution and summarization
use code and make no model calls. Do not make xhigh/max the routine default.

These are project recommendations, not API defaults or quality guarantees. They
follow the [official reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort)
on balancing effort against latency/cost and evaluating higher settings. The script
prints recommendations; it does not change the T3 model or launch agents. When
delegating, discover live capabilities and set effort explicitly in target options;
a prompt mentioning high does not change the runtime setting.

## One packet in, one packet out

Add one `experiment` object to a normal [validation-runner plan](validation-runner.md):

```json
{
  "question": "When does routing plus child shuffle beat composite sorting?",
  "hypothesis": "Low fanout and fitting children reduce complete-job data movement.",
  "decision_rule": "Compare verified complete jobs, uncertainty, resources and complexity.",
  "stop_rule": "Stop on correctness failure or loss of plausible benefit.",
  "cohort": "development"
}
```

Each step needs phase `prepare`, `measure`, `verify` or `summarize`. Measurement
and verification steps are required. Declare dependencies so verification checks
the relevant outputs and no dependent command runs after failure. The wrapper
checks structure, not the truth of a verifier or adequacy of a design. Real harnesses
measure jobs; independent checks verify correctness. Declare their outputs as
artifacts and preserve raw samples and failures. Use deterministic summary code.

Copy [the example plan](../scripts/experiment-plan.example.json) into ignored scratch
storage. Replace root, real executable/version, commands, input/artifact identities
and limits. The example is a tiny orchestration control, not an engine benchmark.
Use the actual Python executable, not a Windows Store alias. Run:

```powershell
python scripts/experiment-cycle.py run scratch/experiment-plan.json scratch/experiment-batch
python scripts/experiment-cycle.py packet scratch/experiment-batch
```

`run` executes or safely resumes through the existing runner, retaining provenance,
attempts, logs and deadlines. It returns runner success/failure (0/1); invalid input
or setup errors return 2. Wrapper and runner hashes are frozen in the immutable
manifest. Changed plans, questions or driver versions require a new batch directory.

On completion or recorded command failure, `decision-packet.json` contains the
question/hypothesis, decision/stop rules, latest step states/exit codes, and pointers
to the manifest, full status and logs. It lists at most twelve steps by default,
prioritizing incomplete steps and counting omissions. Read-only `packet --limit`
accepts 1 through 100 to zoom in. Raw logs are never embedded. Detailed identities
remain in runner status; samples/statistics remain in declared harness artifacts.
Command durations are orchestration timings, not complete-job benchmark metrics.
The packet never chooses a winner.

A complete packet recommends high-effort interpretation; an incomplete one
recommends diagnosis. Start with the failed step and relevant log slices, escalating
only when needed. Supply a packet, relevant source paths and a precise question,
not all logs, the whole repository or the entire conversation. Record outcomes as
useful in a defined regime, not worthwhile under tested conditions, or inconclusive.

## Limits and evidence

This foreground/local wrapper installs no automation, calls no model API and does
not replace benchmark harnesses. Subprocess cleanup comes from the existing runner;
commands must not daemonize. An exception before an attempt may leave no new
packet: nonzero exit and stderr remain authoritative. A packet is a status snapshot,
not fresh artifact verification; resume with `run` to recheck identities. Do not edit
active source inputs.

Use concrete manifests within agreed budgets. The runner enforces deadlines, not a
live disk or RSS ceiling; harnesses enforce relevant storage/resource limits. This
tool does not authorize larger runs, expand matrices, repeat indefinitely or tune
heuristics. Interpretation chooses the next worthwhile targeted manifest.

Held-out plans use cohort `held-out` with nonempty `frozen_rules` and `predictions`
describing pinned rules/versions and predeclared expectations. Concrete fixtures
are frozen in the ordinary manifest. Missing declarations are rejected before
launch; the wrapper cannot detect leakage or prove declarations true. Cases used
for tuning become development evidence and need fresh evaluation replacements.

Measurement scope, shared work, uncertainty, distinct resource metrics, rejection
rationale and archive boundaries follow the [benchmark guide](benchmarks/README.md),
[investigation handoff](workload-investigation.md) and [storage policy](evidence-storage.md).
Compact packets do not weaken these contracts. Preserve decisions and evidence
pointers as project memory rather than relying only on conversational transcripts.
Record reviewed outcomes and their delivery status in the
[performance decision registry](performance/README.md); register the dated investigation
through its narrative authoring workflow and link the interpretation
and pinned artifacts. Runner completion alone must not select the disposition.

Verify this routine without running engine experiments:

```powershell
python scripts/test-experiment-cycle.py
python scripts/test-validation-runner.py
```
