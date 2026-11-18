## Materialized-parent allocation retry (2026-11-03)

A [fresh first-wide probe](../../benchmarks/resident-first-wide-probe-2026-11-02.patch)
rejects the prepared-router patch as a general admission remedy. In four matched
synthetic pairs (128,000/200,000-byte payloads, owned/compact ingestion), immediate
routing accepts the single row while the prepared-router path denies. All cleanup
assertions pass. These use the earlier scaled local-workspace overrides and
preassigned keys; they are not failed CLI jobs, probability tests or occurrence
estimates. Apply this diagnostic after the earlier prepared-router patch in a
fresh source copy. Original records and that patch remain unchanged.

The [experimental successor](../../benchmarks/resident-parent-retry-prototype-2026-11-03.patch)
uses materialized input as a bounded recovery boundary. Raw initial ingestion
keeps immediate routing. For an existing probabilistic-allocation parent under
explicit Auto grouping, attempt retained sorting and finish it **before emission**.
A typed admission denial destroys the failed state, readers and sort files;
`ctx.check()` then rejects cancellation/cleanup failure before one immediate-routing
retry from the same immutable Dataset parent. Original domain, IDs and encounter
order reproduce membership without resampling. Cancellation, malformed input,
I/O and all output-side errors are terminal. The output sink is outside the retry
boundary; no publication or partially emitted parent is rewound.

This avoids constructing speculative routes for unused allocation keys. The
alternative of fixing first-row conversion alone would leave retained/decode
admission overlap elsewhere; a numeric headroom observation is not a grant.
Parent recovery uses an already retained source rather than introducing new
reservation-transfer machinery. Its failed work and reread can cost time and
logical traffic, so those costs remain part of complete-job execution.

The [derived investigation record](../../benchmarks/resident-parent-retry-comparison-2026-11-03.json)
separates controls from timing. The occupied 2,500-row/128-byte parent completes
through an observed admission retry with exact emitted metadata/row-frame parity
against immediate routing. A 64-row fit and a one-row 200,000-byte case also match;
the wide parent control has 500,000 available bytes, distinct from the bare-sorter
probe's 300,000. Cancellation, malformed input and a typed sink denial each perform
one scan, release owned grants/files and never replay output. The isolated v4
snapshot passes formatting, workspace/all-target Clippy and the full locked native
workspace suite, including existing seeded/cap/publication tests. Initial test-only
E0308 and Clippy failures remain retained; dependent checks stopped until separately
declared corrections. Patch roundtrip matches the three native-tested changed files.

After these gates, fresh baseline/candidate release builds ran the existing
20,000-row/eight-region development campaign: partition -> probabilistic 80/20
allocation -> child uniform shuffle, 64 MiB, one worker, default features, both
Grouping Auto. Both opposite-order pairs pass independent fields/IDs/groups/sizes
and exact same-version lineage/CSV parity. CLI launch through successful
Run/publication includes all candidate work; build/preflight/verification is excluded.

| Pair/order | Baseline seconds | Candidate seconds | Candidate minus baseline |
| --- | ---: | ---: | ---: |
| Baseline, candidate | 0.3680451 | 0.2802139 | -0.0878312 |
| Candidate, baseline | 0.2261706 | 0.1487501 | -0.0774205 |

There are two observations per cell. Baseline median/range is
0.29710785 / 0.2261706..0.3680451 seconds; candidate is
0.21448200 / 0.1487501..0.2802139. Cache/startup/host load remain uncontrolled;
no tail, significance or cross-corpus claim follows. Each pair removes exactly
4,702,179 logical bytes both written and read, and 16 temporary files. Routed
allocation groupings change from eight to zero, resident sorts from 17 to 25.
Both record the same 8,057,150-byte peak workspace reservation; this is not RSS
or exclusive allocation-stage memory. Logical counters do not establish physical
I/O. The fitting panel does not estimate retry prevalence or adverse retry cost.

Decision: reject prepared-router construction as the general remedy and retain
the pre-emission parent-retry successor as an **unapplied experiment**, supported
for these controls and this complete-job development case. No selector or default
is promoted. Arbitrary shared-pressure success-domain inclusion and later emission
metadata admission remain unproved. Experimental browser behavior is untested;
the separate readiness evidence below uses the unchanged production engine.
The declared native controller stopped after four Runs/two decisions; it and all
earlier terminal controllers remain terminal. Raw manifests, source/vendor/native
HTML/CSS/app.js identities, fresh targets/binaries, failed attempts and full logs
remain under `scratch/unattended-continuation-20261102/` in the retained Windows
checkout. WSL dispatch/review/session records use the same relative directory.
Repository CI checks retained evidence; it does not execute the unapplied patch.
