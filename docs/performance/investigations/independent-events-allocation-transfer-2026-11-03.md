## Independent events allocation transfer (2026-11-03)

Decision: **the fitting allocation pass reduction transfers, but this workload
already has a production option with the same logical traffic**. The
[events study](../../evidence-originals.md#sha256-b010843efd84dc5e65d4e2a122df7cbe211655851b607f4dc74ffb02efa180d9) tests a
separate six-column simulated events schema: 20,000 records, four independently
drawn event types, categorical text including Unicode/quoted multiline fields,
and numeric-looking values retained as text. Event type partition is followed
by independent 80/20 allocation with no child shuffle or final cap. This is a
named variation of the agreed events schema, not the corpus's full-shuffle /
balanced-split recipe. The 1,147,993-byte fixture is development evidence; reserved
correlated-width/skew, late-key and sorted-tie performance holdouts stay untouched.

Two opposite-order native Windows pairs compare the original immediate-routing
baseline against the unchanged, unapplied materialized-parent retry candidate.
Two more compare the original production binary's explicit `grouping: sort`
against `auto`. Each job has 64 MiB, one worker and a 32-MiB shared ceiling.
Retained executables match their original completed build records; no new engine
build or behavior change occurred. The record pins original source/build identities,
fixture and harness hashes, manifests, full logs and verification references.

| Separate panel / pair order | Baseline auto seconds | Challenger seconds | Challenger minus baseline |
| --- | ---: | ---: | ---: |
| Resident candidate; baseline then challenger | 0.132623 | 0.094125 | -0.038498 |
| Resident candidate; challenger then baseline | 0.130123 | 0.093951 | -0.036172 |
| Existing explicit sort; baseline then challenger | 0.135946 | 0.095796 | -0.040150 |
| Existing explicit sort; challenger then baseline | 0.137840 | 0.096281 | -0.041559 |
| Shared 2 MiB, candidate; baseline then challenger | 0.153607 | 0.163582 | +0.009974 |

Both fitting challengers remove four allocation routing groups, 2,757,745
engine-reported logical bytes each written/read and eight temporary files.
Resident sorts change from one to five, with 40,000 rather than 20,000 sort rows.
The fitting panels have two observations per cell and favor each challenger in
both pair orders. Existing explicit sort obtains this mechanism without the
experimental prepare/retry path; these panels do not establish a statistically
resolved difference between the two challengers. Timings span CLI launch through
successful Run/publication and result emission; preflight and verification are
outside that clock. Cache and host load are uncontrolled. These subsecond
measurements do not calibrate an Auto rule or establish general speedups.

A separately frozen single pair uses a 2-MiB shared ceiling. Both complete with
identical logical traffic (9,258,469 written, 8,182,239 read, 16 files), five routed
groupings and no resident sorts. Neither records a typed retry marker. The
candidate's one slower sample cannot establish a regression or retry cost; its
resident attempt can transition to routing within the existing sorter. Together
with the earlier [actual retry costs](../../performance.md#allocation-retry-safety-and-runtime-evaluation-2026-11-03)
and [post-preparation denial](../../performance.md#allocation-post-preparation-pressure-boundary-2026-11-03),
this argues against promoting the unchanged candidate or adding complexity for
this fitting regime. It does not prove explicit sort's general pressure behavior.

All ten paired jobs pass exact field/ID conservation, partition/allocation lineage,
child order, manifest sizes/file inventory and temporary cleanup. All five pairs
match exact CSV bytes, ordered lineage and logical Analysis fields, including
seed/version, digest, stage counts, summaries and output counts/bytes. Positive
and corruption controls reject changed fields, reordered rows and wrong partition
lineage. There is no independent seeded-membership oracle or distribution proof.
Two earlier successful baseline Runs failed verifier setup on nullable limits and
an omitted seeded-policy default; their failed batches/logs remain separate and
are excluded from paired comparisons. No candidate had launched in either attempt.

Raw fixtures, outputs, original binary/build references, frozen harnesses, plans,
logs and mutation controls remain private in the Windows checkout's
`scratch/todo-unattended-20261103*` roots; WSL operational records are under
`scratch/todo-unattended-20261103/`. Twelve attempted measured Runs include both
excluded setup attempts. No new raw archive upload, cleanup, deployment, RSS/CPU
census, physical-I/O, browser-events or scale claim follows. Only evidence checks
are required for this retained experiment; repository CI does not execute these
private historical binaries. TODO retains the admission-feasibility and broader
workload/runtime questions; no default or selector is changed.
