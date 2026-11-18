---
name: chopper-benchmarks
description: Analyze Chopper benchmark evidence, design or run targeted performance experiments, and record results with provenance and replay constraints. Use for Chopper performance comparisons and benchmark decision tables; not for unrelated benchmarking or general feature development.
---

# Chopper benchmarks

Resolve a named performance or resource decision using Chopper's existing evidence before adding measurements. Support analysis-only requests without launching benchmarks or changing engine defaults.

## Locate the maintained rules

Work from the user's Chopper checkout. Verify the repository using its workspace manifest and benchmark guide rather than assuming a fixed absolute path. Paths below are relative to that checkout. If those documents are unavailable, ask for the checkout rather than substituting another project's rules.

Read `docs/benchmarks/README.md` for evidence rules and `docs/performance-opportunities.md` for priorities, acceptance, and stop/reopen criteria. Use GitHub Issues for `jsmatfess/chopper` as the sole active backlog and spec tracker; read `docs/agents/issue-tracker.md` before tracker operations. Use `docs/README.md` for additional documentation routing.

For repeated experiments, read `docs/experiment-cycle.md` for reasoning routing, declared command pipelines and compact evidence handoffs. For unattended sessions, decision-file resume or session stop/recovery, read `docs/experiment-controller.md` for controller commands and limits. These workflows remain subject to the current task's authorization and resource limits.

Use `docs/benchmarks/INDEX.md` and `catalog.json` to locate relevant artifacts and harnesses. Read the linked individual investigation before deciding which records are eligible; `docs/performance.md` preserves legacy anchors as a generated compatibility index. Start with `docs/performance-overview.md` and the topic, normalized-observation and validation queries in `docs/performance/README.md` for scoped retrieval. Decision coverage is selective; the extraction inventory explicitly lists unsupported schemas. The catalog supplies navigation and provenance, not statistical eligibility. Read `docs/specification.md` and `docs/pipeline-rewrites.md` when evaluating correctness or replay claims; consult `docs/validation.md` and `docs/validation-index.md` for platform and scale coverage.

When selected evidence refers to archived originals, consult `docs/evidence-originals.md` and the archived-original alias resolution contract in `docs/evidence-storage.md`. Use authorized, hash-verified hydration; private originals and credentials stay within that access boundary. Report unavailable evidence as a limitation rather than inferring its contents.

## Analyze existing evidence

Search the index before reading large artifacts. Reuse the lossless exporter when useful:

```sh
python3 scripts/benchmark-catalog.py --export-records --match 'EXPERIMENT-*.jsonl' > /tmp/chopper-records.jsonl
```

Replace the pattern with the selected artifacts. Inspect original schemas, units, record types and context before extracting metrics. JSON documents export as whole documents; identify nested observations by explicit JSON pointers. Preserve source hash and physical JSONL line or JSON pointer in derived tables. Missing metadata stays unknown; filenames and nearby records cannot fill it in.

Start with matched baseline/candidate cells within an experiment. Check build and feature identities, harness, fixture/shape, pipeline, runtime, workers, memory, storage/cache context, physical plan, randomization/algorithm and timing boundary (including seed for historical seeded evidence). Keep repeated runs nested under their cell. Record inclusion/exclusion reasons and retain diagnostic flags, failures and superseded-pass context.

Do not count derived summaries or identical artifacts as additional observations, pool historical percentage gains, or add test counts from separate passes. Contract durations and microbenchmarks do not establish whole-job speedups. Report sample counts, median and spread; avoid tail claims from a handful of repetitions. Define effect direction and denominator when reporting a percentage or ratio.

Keep wall time, CPU, allocation traffic, live reservations, RSS, logical temporary traffic, stored bytes and physical I/O separate. Reservations are not an RSS cap; sampled peaks are lower bounds; independent peaks cannot be added as simultaneous usage. Warm WSL or OPFS timings do not establish SSD throughput. Distinguish temporary/private and persistent browser contexts.

For a decision table, identify the workload/runtime, eligible comparison, effect and spread, resource tradeoffs, correctness/replay evidence, provenance, limitations and resulting decision. If compatible baselines are missing, state the gap rather than manufacture an estimate. Retain separate strata when pooling is unsupported.

## Design and run a targeted experiment

State the decision, baseline, candidate, eligible workload and stop criterion first. Use existing evidence to select the smallest useful experiment. Reuse a harness only after checking its measurement boundaries and side effects. Do not reopen pruned experiments or launch full historical/scale matrices without a decision that requires them.

Pin native/WASM artifacts, features, harness/source and fixture identities. A dirty checkout's commit alone does not identify its binary: retain build hashes and relevant source identity. Do not clean or reset the user's checkout to make it appear reproducible. Record actual environment, cache/storage context, memory/workers, algorithm/randomization/plan and timing scope. Historical seed identities are not current product controls. Alternate matched baseline/candidate complete jobs; retain each repetition and failed attempt.

No standing elapsed-time, disk-space or directory limits are configured. Respect limits supplied in the current task. For a run that needs substantial resources beyond existing authorization, first present its concrete estimated duration, space requirements and output/temp locations and request only the missing authorization. Do not treat this skill as permission to launch expensive runs. Analysis and experiment design can continue independently.

Validate conservation, group membership, logical metadata, strict caps and failure/cancellation/publication cleanup as relevant to the candidate. Preserve exact membership, ordering barriers, serialized caps and prepared-snapshot confirmation under the current specification and rewrite rules. Distribution-equivalent changes require their justification and declared diagnostics; finite diagnostic success does not prove uniformity. Current product execution has no configurable seed or replay policy. Historical seeded comparisons retain their original identities and contracts.

Promote a candidate only when complete-job benefit, bounded resource behavior and replay claims are supported for the intended workload/runtime. Record regressions and uncertainty. A benchmark request alone does not authorize changing product defaults.

## Record the outcome

For requested repository updates, preserve raw artifacts and add new passes without overwriting historical evidence. Put interpretation, controls, exclusions and reproduction details in a new dated investigation under `docs/performance/investigations/`, registered using `docs/performance/README.md`. Preserve migrated prose and stable source hashes; record corrections in a new investigation. Keep future work and acceptance criteria in the owning GitHub issue; do not create a competing checklist. Analysis-only requests do not require rewriting documentation.

After changing benchmark artifacts or performance evidence links, regenerate and check navigation:

```sh
python3 scripts/performance-narratives.py
python3 scripts/audit-strategy-evidence.py
python3 scripts/benchmark-catalog.py
python3 scripts/performance-registry.py
python3 scripts/evidence-views.py --build
```

Then run the complete read-only evidence checks in `docs/benchmarks/README.md`.
Normalized extraction is not eligibility: keep named reviewed comparison selectors
and all metric scopes; never turn allocation censuses or contract durations into
whole-job speed observations. Imported runner receipts do not grant validation reuse.

Summarize the decision, supporting comparisons, resource/correctness tradeoffs and remaining uncertainty. Link the evidence with enough location information to reproduce the result. Distinguish observed results from hypotheses and proposed follow-up work.
