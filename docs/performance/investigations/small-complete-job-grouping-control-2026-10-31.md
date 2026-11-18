## Small complete-job grouping control (2026-10-31)

A bounded native Windows control compared current `grouping: sort` and `auto`
for region partition -> probabilistic 80/20 allocation -> child uniform shuffle.
The entity-list-v1 fixture has 20,000 rows, eight possible regions, a 30% hot-region
branch, independent 24..128-byte notes, explicit seeded_v1, 64 MiB and one worker.
Three alternating pairs used fresh output directories. All six jobs passed the
independent verifier and their ordered output lineage/CSV hashes matched exactly.

Always-sort elapsed samples were 0.3167774, 0.1504176 and 0.1451243 seconds;
auto samples were 0.2622542, 0.2638808 and 0.2605678 seconds. Medians were
0.1504176 and 0.2622542 seconds respectively. These are CLI-launch-through-Run
publication measurements, with preflight hashing and verification excluded.
Cache state is uncontrolled; the first sort observation is visibly slower.
Three observations do not support tail estimates or a calibrated selector.

Interpretation: routing is not automatically worthwhile for this small complete
job. The result supports investigating grouping/materialization overhead before
replacing shuffle kernels; it does not justify changing the default strategy or
claiming a general routing regression. Next useful contrast: lower region fanout
at the same row/width/resource conditions, if another test is warranted.

Local raw records, preparation source, immutable plans, source/build/artifact
identities, logs and verification outputs remain in
`scratch/grouping-comparison-001/`; `summary.json` is derived, not another sample.
Browser launch failed before the first workload with
`browserType.launchPersistentContext: Target page, context or browser has been closed`.
A fresh-profile retry under `scratch/gc-browser-retry/` completed the first
browser job and its independent verifier, but the batch failed because the copied
plan declared the verification artifact under the original directory. Retain this
completed job and orchestration failure separately; exclude the incomplete batch
from comparative conclusions. The initial launch failure is not a timing sample,
and no native-to-browser transfer is claimed. No code/default or held-out data changed.
These local records have not been uploaded to the private archive; preserve them
under the existing storage policy before cleanup.


Follow-up on 2026-11-02: a fresh native Windows release build and bounded
controller session tested the named lower-fanout question at 20,000 rows and two
regions, retaining the independent 24..128-byte notes, 30% hot branch, 64 MiB,
one worker and seeded recipe. Two alternating pairs completed, independently
verified fields/conservation/group membership, and matched exact seeded lineage
and CSV bytes. Sort seconds were 0.2473079 and 0.1226816; auto seconds were
0.1364276 and 0.1442540. Auto-minus-sort paired differences were -0.1108803 and
+0.0215724 seconds. The mixed direction is inconclusive under the frozen rule;
no selector, default change or general speed claim follows. Cache was uncontrolled,
the first sort observation was slower, and two pairs cannot establish tails or
isolate fanout causally against the historical eight-region build/context.

The session stopped normally after four admitted Runs, two batches and two
predeclared decisions, using 3.166 seconds of session age and 24,282,771 boundary
stored bytes (29,963,058 sampled peak), within 300 seconds/512 MiB. Stored bytes
are logical owned-tree observations, not RSS or physical I/O. CLI launch through
Run/publication is timed; build, fixture generation, preflight and verification
are excluded. Build provenance includes complete source/vendor/UI identities.
The earlier Application Control build failure remains separately retained; after
the owner disabled Smart App Control, a fresh build batch passed without source
changes. No benchmark failure was retried. Browser launch/path failures remain
unresolved and their absent original trees were not reconstructed.

Raw plans, self-review, fixtures, full logs, verification, packets and journal are
at `C:/Users/USER/git/jsmatfess/chopper-baseline-20261102/scratch/lower-fanout-001/`;
matching successful build records are at `scratch/baseline-20261102/native-build-approved/`
in that checkout. The failed build remains in `native-build/`. These local trees
have not been uploaded or deleted. The controller session is terminal; do not
resume it. Next useful action is a separately bounded attribution plan for
routing/materialization cost, with matched current-build controls, before choosing
a challenger; repeating this tiny timing panel alone does not resolve that cost.


A matched-current-build eight-region attribution follow-up completed on 2026-11-02
under `scratch/cost-attribution-001/` in the same Windows checkout. Four complete
Runs passed independent verification and exact seeded parity; the controller
stopped after two alternating pairs (3.370 seconds, 24,368,363 boundary stored
bytes). Sort whole-job seconds were 0.1684517/0.1526242; auto were
0.2332174/0.2364440. Auto-minus-sort differences were +0.0647657/+0.0838198.
Broad remaining-operation clocks were sort 0.0548483/0.0520182 and auto
0.1294257/0.1349907 seconds; ingest/fused clocks were sort
0.0345634/0.0282979 and auto 0.0311879/0.0304819. These observations localize the
visible difference to remaining operations in this tiny development case, without
isolating routing causally. They are not pooled with earlier builds or the
separate two-region panel. Phase clocks are inclusive, not extra whole-job costs;
`final_serialization` measures output planning here, not a standalone complete
publication timer. Cache and background host load were uncontrolled. Two pairs
do not establish a selector, tails or transfer to browser/scale. Defaults remain
unchanged. Next bounded question: identify which existing remaining-operation
paths account for the difference before selecting a challenger or adding counters.
No additional timing repetitions are justified solely to seek a positive result.
