## Resident allocation challenger (2026-11-02)

The [experiment-only patch](../../benchmarks/resident-allocation-prototype-2026-11-02.patch)
asks whether fitting probabilistic-allocation rows can reuse the existing bounded
`Sorter::new(Key)` path before routing on overflow, avoiding the temporary pass
identified above. It is applied only in a separate native Windows checkout at
`C:/Users/USER/git/jsmatfess/chopper-resident-20261102`, based on `1cf44a9`.
The repository's production engine and defaults are unchanged. Apply the retained zero-context patch to that revision with
`git apply --unidiff-zero docs/benchmarks/resident-allocation-prototype-2026-11-02.patch`
in an isolated experimental checkout. Interleaved
membership retains immediate routing. The patch reuses existing admission,
Router eligibility and one-way fallback; it introduces no new selector threshold.
Its focused fit/overflow control checks conservation, routing and cleanup; existing
semantic parity and admission/failure contracts remain applicable.

The initial isolated baseline build failed before tests or measurement because its
source copy omitted `ui/index.html` and `ui/style.css`, embedded by `server.rs`.
The failed snapshot, manifest, helper and logs remain at
`scratch/resident-allocation/{baseline-src,build-batch}/` in that checkout.
A separately declared attempt adds those assets to `baseline-src-v2` and declares
them in both baseline and candidate build inputs; it retains the first attempt.
Incremental compilation cache is reused, not a passing build result. The shared
build ceiling remains 2,400 seconds including the first 12.53-second failure;
the fresh runner has a 2,380-second limit. Estimated build storage is 8 GiB;
each build requires 12 GiB free headroom, which is not a hard filesystem quota.
Session deadline remains 2026-11-03 00:17 UTC, including reviews and CI waits.

This failure also exposed a gap in the maintained baseline-plan generator: it
listed `ui/public` but omitted the embedded HTML and CSS. The generator now declares
all three, and its regression check derives asset paths from the current server's
`include_bytes!` references. The native runner guidance is corrected accordingly.
This qualifies earlier claims of complete build-source inventory, including the
routing audit above: rehashing all recorded inputs cannot prove completeness of
that inventory. Earlier executable hashes and verified output observations remain
valid, but missing build-time HTML/CSS hashes cannot be supplied retroactively.
Raw historical records are preserved unchanged.

The second build attempt passed baseline compilation and formatting, then stopped
at Clippy with E0308 in the new test's `&group?` expression. The test now binds the
charged wrapper before borrowing it, matching existing consumer code. That failed
source is retained as `candidate-streaming-v2.rs`, with full `build-batch-v2` logs.
A separately declared `build-batch-v3` uses a fresh binary destination/status and
2,330-second ceiling; the earlier roughly 58 seconds still count against the
same 2,400-second build budget. No benchmark failure or retry occurred.


**Outcome: retain the prototype as useful in this tested development regime;
withhold production selection and broader speed claims.** The
[derived comparison](../../benchmarks/resident-allocation-comparison-2026-11-02.json)
retains four new complete native Windows Runs, separate from the earlier panel.
Both cells use `grouping: auto`, default features, 64 MiB and one worker, on the
same 20,000-row/eight-region entity-list fixture and seeded campaign recipe.
Baseline/candidate have separate retained binaries and frozen source trees;
only the candidate contains the experimental execution/test patch. Build-status
and manifest hashes identify complete vendor/source/UI inputs and saved binaries.

| Pair and launch order | Baseline auto seconds | Resident candidate seconds | Candidate minus baseline seconds |
| --- | ---: | ---: | ---: |
| 1: baseline, candidate | 0.3559293 | 0.2719950 | -0.0839343 |
| 2: candidate, baseline | 0.2283765 | 0.1524230 | -0.0759535 |

Each cell has n=2 on one fixture/host, not two independent workloads. Baseline
median/min/max are .2921529/.2283765/.3559293 seconds; candidate values are
.2122090/.1524230/.2719950. The timer includes CLI launch through successful
Run/publication, including packing/sorting and downstream child shuffles;
build, fixture generation, preflight hashing and verification are excluded.
No builds or other experiments ran during timing. Cache and host load were
uncontrolled; each binary's first observation was slower. Opposite-order pairs
support the observed direction here but cannot remove startup/cache confounding,
establish tails, prove exclusive storage cost or predict another runtime/scale.

Both pairs remove exactly 4,702,179 logical bytes written and read, and 16 files:
baseline counters are 16,798,172 written/14,490,224 read/22 files; candidate
12,095,993/9,788,045/6. Resident sorts rise from 17 to 25 and sorted rows from
40,000 to 60,000; routed groupings fall from eight to zero. No sort runs, routing
fallback/reuse or cleanup failures occur. Candidate sort clocks increase
(.0049086/.0050345 versus .0036220/.0036712 seconds), while complete jobs improve.
Peak workspace reservations are 8,057,072 bytes in all four Runs; that maximum
may be dominated by another phase and does not establish equal allocation traffic,
RSS or per-parent retained memory. Logical temporary transfers are not physical
SSD I/O. This is evidence for avoiding the added pass, not for faster sorting.

The native runner passed formatting, Clippy and the full default workspace tests,
including the experimental fit/overflow control. The controller/cycle/runner then
passed independent field/ID conservation, group/lineage/size verification for all
four outputs and exact algorithm-version/ordered-lineage/CSV parity for both pairs.
It used file decisions to admit only the preapproved opposite-order repeat after
verified mechanism success, then stopped normally: four Runs, two batches/two
decisions, 67.987 seconds of session age including decision waits, 29,223,853
boundary bytes and 31,276,624 sampled peak bytes within 300 seconds/512 MiB.
Stored bytes are logical owned-tree observations, not RSS or a hard disk quota.
Postflight rehashed every recorded passing build/batch input and artifact again.
The verifier still is not an independent membership oracle or uniformity proof.

Successful build records are in `scratch/resident-allocation/build-batch-v3/`;
concrete plans, self-review, raw per-Run records, outputs, full logs, verification,
packets and decisions are in `scratch/resident-allocation/comparison/` in the
isolated Windows checkout. The scratch preparation adapter also had an import-path
failure before creating comparison artifacts; its original script/traceback is
preserved separately and a separately named corrected adapter prepared the plans.
No timed attempt failed or was retried. Nothing was uploaded, deployed or deleted.

The build-input fix passes the 14 Python harness tests; an in-memory negative
control confirms the new asset-coverage assertion rejects the old incomplete
inventory. This does not retroactively validate historical omitted inputs.
The next bounded action is to inspect the actual workload corpus's parent working
sets and required admission/denial guarantees before deciding whether another
candidate experiment is warranted. Do not add timing pairs, a fanout/size sweep,
a selector or default change merely because this tiny case improves. Browser
launch/path prerequisites and its unsupported controller remain unresolved.
