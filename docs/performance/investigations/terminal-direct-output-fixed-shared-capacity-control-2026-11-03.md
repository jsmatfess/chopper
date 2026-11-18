## Terminal direct output: fixed shared-capacity control (2026-11-03)

**Decision: both frozen native plans complete at the selected 12-MiB shared
capacity point; general concurrent-pressure feasibility remains open.** The
[fixed-capacity record](../../benchmarks/terminal-direct-shared-capacity-2026-11-03.json)
uses the same 200k-event input and unchanged, unapplied terminal direct prototype
as the [storage controls](../../performance.md#terminal-direct-output-storage-lifetimes-and-temp-budget-control-2026-11-03).
Only the aggregate pool changes from 32 MiB to 12 MiB, plus fresh output/temp
paths. Nominal job memory remains 64 MiB, one worker and 256-MiB temporary budget.
These two diagnostic CLI jobs supply no additional speed observations.

| Fixed 12-MiB shared-pool control | Outcome | Peak tracked reservations, bytes | Charged temporary peak, bytes |
| --- | --- | ---: | ---: |
| Prepared baseline | Success | 6,762,823 | 44,150,137 |
| Direct prototype | Success | 6,762,832 | 34,141,695 |

Both process diagnostic snapshots confirm configured and admission limits of
12,582,912 bytes. The tiny reservation difference is not evidence of an algorithmic
memory effect: retained configuration/path lengths differ. Both outputs exactly
match the existing baseline CSV names, bytes, order, lineage and seeded membership;
17 logical Analysis fields match. Each returns 200,000 rows, eight files and
11,673,614 CSV bytes, with empty temporary directories and no private staging.

The earlier approximately 13.7-MB reservation peaks are therefore not minimum
required capacities for these jobs. `Workspace::sort_buffer_limit` caps its nominal
target at half the current shared admission limit; `Sorter::new` uses that target
for buffering. The source supports an adaptive buffering explanation, not a proof
of every allocation lifetime. A fixed smaller pool is not an injected concurrent
owner or an adversarial late-pressure trace. No complete admission-domain inclusion,
RSS, physical storage, speed, browser or codec claim follows from this point.
Windows startup discovery still reports its conservative fallback, not measured
host RAM. Do not tune a threshold or infer a selector from this pair.

The first harness attempt failed importing `workload_entities`, before binary
matching, record creation or Chopper launch. Preserve its failed batch and full
trace. A fresh reviewed driver adds the task-owned module search path and uses a
new plan, guard and cell directories; both jobs and comparison then pass. Original
storage evidence's 69 hash references remain unchanged. Binaries again match the
original completed build; no new engine algorithm or build is introduced.

Raw manifests, verified outputs and full logs remain private in Windows
`scratch/terminal-pressure-20261103T1354/`; WSL retains interpretation and evidence
checks under the same name. The original start and continuation deadline remain
unchanged. Totals are 34 actual engine attempts and 37 conservative admissions,
including three never-launched reservations. The declared engine-run limit is now
exhausted; the remaining TODO acceptance questions stay open. Production defaults,
engine dispatch, promotion and deployment remain unchanged.
