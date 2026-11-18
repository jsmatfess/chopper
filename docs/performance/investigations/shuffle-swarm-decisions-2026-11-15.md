## Shuffle swarm decisions (2026-11-15)

Retain two bounded rewrites in the ordinary build on feature branch
`investigate/shuffle-swarm-20261115`: adjacent full shuffle → unstratified exact
assignment, and removal of earlier auto/uniform shuffles before a final explicit
Fisher–Yates. Reject the ingestion-integrated adaptive pilot for no demonstrated
complete-job benefit. Defer direct shuffled balanced parts after its predefined
pilot rule failed. The latter two implementations and storage APIs are removed;
their frozen source, binaries, tests, failed attempts and measurements remain
private evidence. This is an adopted, **awaiting delivery** result, not a landing,
public deployment or native Windows performance claim.

The fetched starting and integration base is
`de93a7a728fd8652f01627b1d1483409ed499455`. The existing
[policy removal and shuffle/partition result](seeded-policy-removal-and-shuffle-partition-fusion-2026-11-15.md)
and its [verified evidence handoff](policy-removal-evidence-delivery-2026-11-15.md)
remain baseline behavior, unchanged evidence and available originals. No removed
runner, seeded-output compatibility architecture, blanket partition-first or
retained-data resident selector was restored. Seeds are optional RNG inputs;
prepared confirmation still consumes its immutable retained output snapshot.

### Decision and experiment boundaries

All eight requested roles used GPT-6.1 Sol, with the requested high/xhigh/medium
settings, in waves with explicit ownership. Shared engine integration stayed with
the lead. Authors first supplied read-only designs, proofs, owners/failure paths
and falsifiers; independent semantics and resource reviewers challenged them.
The lead integrated isolated candidates, measured each against pinned production,
removed losing candidates, then measured the combination that would ship.
Independent reviewers inspected the integrated source and connected owners.
Their reports, cutoffs and hashes are in the private replay package below.

Each eligible cell has one excluded warmup per variant followed by three matched
alternating pairs, B/C, C/B, B/C. Retain all individual repetitions, including the
53 ms combined fitting candidate sample. No outlier deletion, cross-cell/runtime
pooling, tails, confidence intervals, fitted thresholds or new profiling pass is
used. There are 19 native and seven browser cells: 114/42 measured jobs and 38/14
warmups respectively. These are inventory counts, not independent studies. The
failed first browser warmup is a separate excluded attempt, never a rescued pass.

Native clocks cover GNU-time wrapper launch through CLI exit, including input
reading, validation/profiling, materialization, serialization, publication and
product cleanup. Fixture generation, independent verification and successful
harness output removal occur outside that clock. User/system CPU and max RSS are
separate GNU-time observations. Analysis temporary traffic/reservations are
**prepublication** counters, not total physical device I/O or an RSS cap.

Browser clocks cover prepare, confirmation, file export/completion marker and
session retirement after defaults/pickers, including per-job WASM restart, in a
persistent bundled Chromium context. Browser/server startup and result collection,
verification and harness export removal are outside the clock. Both variants pay
the same profiling/observation overhead. Actual CSV, manifest and marker bytes,
zero workspace cleanup, retained-owner sums, export byte counts and bounded
handles are checked before successful harness cleanup. CPU, RSS and device I/O
are unavailable there. Profiles and failures remain local; owned browser/server
closures are recorded.

The host is x86-64 WSL2 Linux/ext4, warm uncontrolled caches, 16 available CPUs,
one configured worker, explicit 32 MiB and 1 MiB maximum records. Seed is
`shuffle-swarm-v1`; plain CSV jobs use 10,000-row and 4 MiB encoded-byte output
caps except balanced experiments, whose exact-file-count control has no caps.
No concurrent expensive experiment was launched. No cold-cache, physical disk,
native Windows/macOS, installed-browser/device or broad-scale performance claim
follows. Rust/Cargo 1.99.1, Node 22.23.4/npm 10.9.9, WASI SDK 33 and actual
compiler/dependency/embedded-asset identities are retained in build receipts.

### 1. Full shuffle → exact percentage assignment: retain narrow fusion

Previously a complete parent permutation was produced, then exact assignment
constructed another random membership ordering and restored each child's order
from that permutation. The replacement cuts the one completed permutation at
existing largest-remainder quotas, emits allocations in configured order,
including named zeros, and starts each child's ordinal at zero. Retained parents
are independent; ingestion uses its actual completed producer and EOF count.
`AssignmentScratch` and quota arithmetic are shared with current assignment.
There is no per-row membership vector or second sorter.

For parent size N and fixed quotas q, the old independent exact membership law
assigns each membership probability product(q!)/N!. Conditional on membership, a
uniform full permutation induces independent uniform orders within the children,
with probability 1/product(q!). Thus every tuple of ordered children has mass
1/N!. Cutting a uniform permutation is a bijection onto those tuples and has
that same mass. Group order, zero quotas and deterministic remainder tie rules
are fixed, not random. This is a joint membership/order proof under the existing
ideal independent randomness model; statistical tests alone cannot establish it.
The full intermediate row trace is not separately exposed. Any later operation
sees the same joint distribution, original group lineage and logical steps.

Eligibility is visible adjacent Auto/Uniform/Fisher–Yates → Assign with no strata.
Stratified assignment needs a separate joint proof and is excluded. Existing
upstream grouping/random-key fusion keeps priority; an immediately following
Auto/Uniform suffix after Assign keeps the prior assignment/shuffle fusion.
Explicit Fisher–Yates still builds a resident-only permutation and can reject.
No global random-key capability predicate, user strategy or failure fallback is
broadened.

Retained quota scratch is admitted before constructing the parent permutation;
root scratch is admitted with its completed permutation/output writer still live.
Child and chunk lineage copies and serializer growth retain separate grants.
Rows are borrowed through the existing packed cursor; clearing keys does not
release live key ownership early. Missing/trailing rows, metadata/serialization,
cap, cancellation and finalization errors propagate terminally, including after a
child emitted. There is no reroll, retry of consumed raw input or successful
publication of a failed prefix. Logical stages and physical producer/range/source
facts cover both ingestion and retained execution.

Root fitting/external, wide and downstream jobs improve in this bounded native
sample; the many-parent case is nearly flat and overlaps. Browser fitting and
external jobs also favor the candidate. Retain this small mechanism without a
size selector. Do not infer a universal completion domain or performance benefit.
The historical [allocation ranges experiment](../../allocation-ranges-experiment.md)
and its pressure/retry constraints remain relevant: this implementation has no
membership-dependent retry boundary.

### 2. Adaptive resident shuffle during ingestion: reject measured pilot

The baseline fitting random-key sorter already consumes parsed rows without a
complete input spool. The rejected retained-data selector's extra replay was
therefore not reintroduced. A new single-Sorter-buffer prototype held rows with
capacity admission while parsing and deferred key construction. If EOF arrived
while pending, the same vector underwent Fisher–Yates. On capacity decline,
including a parser pressure callback, it activated random keys in place and
irreversibly continued through the existing external sorter. The threshold row
was neither discarded nor duplicated. It created no additional complete
intermediate Dataset and never reread the original input.

Pending admission counted descriptor old/new overlap, retained field capacity,
late wide rows, source/parser handoff, eager Dataset/output and shared pressure.
Parser-owned rows kept actual capacity rather than an unadmitted replacement
shrink. A fitting decision occurred before permutation draws; under exogenous
resource pressure it did not inspect sampled membership/order. Once activated,
key construction and collision refinement used the existing random-key path.
Explicit Fisher–Yates remained resident-only, with no external fallback. All
validation, cancellation and temporary cleanup boundaries remained terminal.

The smallest discriminating native cells were 12,000 × 192-byte fitting rows and
50,000 × 192-byte external rows. The actual fitting method changed to FY, but
elapsed medians were slightly slower, with overlapping ranges and mixed paired
signs. External output, three runs/one merge and logical traffic matched baseline;
all eight verified external attempts had the same pinned ordered digest. This
establishes a lossless transition in that fixture, not a uniformity proof or a
universal slowdown. Stop for insufficient benefit: remove the candidate and its
storage fields/helpers, retain its source/build/tests as evidence, and make no
WASI claim or arbitrary tuning threshold.

### 3. Broader consecutive shuffle elimination: retain final-method obligations

A final independent uniform permutation maps every preceding order to each
output order with probability 1/N!. Averaging over any earlier permutation gives
the same law; the earlier Auto/Uniform full shuffle can be omitted when no semantic
barrier intervenes. The final shuffle remains at its original operation index
and uses its own existing random domain. This argument does not permit removing
explicit resource obligations merely because their output distribution is
redundant.

The separate adjacency predicate now permits an earlier Auto/Uniform immediately
before explicit Fisher–Yates, including a leading Auto/Uniform prefix that can
ingest directly into final FY. Every earlier explicit FY still executes:
FY→Auto, FY→FY and FY→Auto→FY retain that resident-only request and its failure.
The final FY retains its quarter-budget resident admission and has no spill
fallback. Nothing crosses grouping, assignment, positional split or another
semantic barrier. Existing upstream grouping/shuffle fusion still wins; its
bypass control has the same physical path and is not an optimization gain.

The new direct-ingestion prefix avoids parser-owned trimming and charges actual
capacity. This can change fit/headroom relative to a materialized parent; no
claim of identical success under every shared-owner schedule is made. Row
conservation, final original-domain order, prepared Analysis-clone ownership,
wide rows, explicit failure, downstream assignment and parent isolation are
covered. All configured logical stages remain; Elided facts have zero work and
no invented source, while the final FY records actual Read/Dataset dependencies.

Retained-parent/downstream native cells and separate WASI cells favor the narrow
change. The native root effect is only about a millisecond and remains weak
practical evidence. Wide-row elapsed improves while RSS and reservations rise;
that cost is retained explicitly below. No additional mixed-method extension or
upstream-fusion override is adopted.

### 4. Direct shuffled balanced parts: defer after fixed pilot falsifier

The production sequence fully shuffles each parent once and traverses balanced
quota ranges. Ordinary balanced-first → shuffle fixes membership from input
order and is not equivalent. The pilot instead sampled exact part labels without
replacement, routed by those labels, and independently shuffled each child.
It used retained parents with exact `Group.rows`, avoiding an uncharged counting
pass. The pilot's initial Balanced(1) materialization, all routing Dataset I/O,
child sorts, observation, serialization/publication and cleanup were inside the
complete-job clock. A root version would need EOF buffering/counting; it was not
implemented or assumed free.

For quotas q, sampling labels by remaining quota/remaining rows gives each
membership product(q!)/N!. Independent uniform child orders multiply by
1/product(q!), so each ordered tuple has mass 1/N!, matching full shuffle then
balanced cut. Quotas/remainders, nonempty parts, parent isolation and original
lineage remain fixed. Hard-cap rejection stays terminal; subdivision or reroll
to obtain a publishable result would change the request.

Independent resource review rejected the first fallback design: membership-dependent
routing denial followed by a fresh sample can bias successful memberships (the
N=3 counterexample gives 5/9 instead of 1/3). Revision B preserved the exact
sampled labels and owning packed rows through a soft routing decline using the
existing streaming Key sorter. Real admission errors remained terminal. Child
random streams were separately tagged, only one child sorter was live, and an
owning cursor transfer kept row grants across movement. The fallback was the
same pointwise function of membership and child random choices, not conditional
resampling.

The bounded experiment was retained-parent Auto/Uniform→Balanced(8), constant
partition key, 192 ASCII payload, 4,003 and 100,003 rows. Its declared rule required
all three external pairs to improve and no fitting-control regression. Although
the external median improved, the third pair did not; fitting median was slower.
Total CPU medians for the external cell were both 0.14 s at coarse resolution.
The candidate added routing/child materialization, and fitting logical temp
traffic rose despite lower peak reservations/RSS. The actual predeclared harness
seed was `shuffle-swarm-v1`, not the illustrative `balanced-revision-v1` from the
initial design; there was no seed search. Defer, remove the pilot/cursor API and
stop without threshold fitting or a larger matrix. No WASI inference follows.

### Complete-job measurements

Each entry is elapsed milliseconds, median [minimum, maximum], n=3 per variant.
Within-cell fixtures/config/resources match; output paths intentionally differ.
The compact summary supplies exact raw SHA-256, physical sample lines, repetition
IDs and JSON pointers to all metrics. A summary is not another observation.

**Individual native candidates**

| Cell | Baseline ms | Candidate ms |
| --- | --- | --- |
| exact-pilot-native: exact-fit | 41.639 [41.052, 50.280] | 34.905 [34.555, 34.922] |
| exact-pilot-native: exact-spill | 134.281 [134.125, 137.428] | 99.366 [99.308, 105.786] |
| exact-controls-native: exact-many | 4427.399 [4372.583, 4539.800] | 4376.403 [4356.087, 4389.123] |
| exact-controls-native: exact-wide | 66.978 [66.524, 67.124] | 53.136 [52.995, 53.985] |
| exact-controls-native: exact-downstream | 173.836 [172.652, 175.118] | 158.662 [146.335, 164.921] |
| mixed-pilot-native: mixed-fit | 20.054 [19.743, 20.173] | 19.072 [17.941, 19.661] |
| mixed-pilot-native: mixed-retained | 139.240 [137.593, 142.109] | 118.299 [116.922, 118.630] |
| mixed-controls-native: mixed-wide | 29.505 [28.959, 31.160] | 26.337 [26.287, 26.554] |
| mixed-controls-native: mixed-upstream | 90.864 [87.869, 91.424] | 90.365 [88.715, 90.675] |
| mixed-controls-native: mixed-downstream | 279.339 [268.956, 305.991] | 253.967 [251.003, 257.860] |
| adaptive-native: adaptive-fit | 29.225 [28.956, 31.251] | 29.708 [28.249, 31.250] |
| adaptive-native: adaptive-spill | 90.132 [88.473, 93.158] | 90.622 [89.036, 102.132] |
| balanced-native: balanced-fit | 48.939 [48.721, 51.011] | 50.093 [49.851, 51.054] |
| balanced-native: balanced-spill | 198.128 [191.056, 201.619] | 192.605 [191.204, 197.677] |

**Individual WASI candidates**

| Cell | Baseline ms | Candidate ms |
| --- | --- | --- |
| exact-browser: exact-spill | 680.710 [658.765, 688.695] | 468.290 [466.090, 487.370] |
| exact-browser: exact-fit | 182.830 [175.725, 183.555] | 165.075 [163.610, 165.395] |
| mixed-browser: mixed-retained | 692.870 [669.060, 712.330] | 567.800 [567.545, 578.925] |
| mixed-browser: mixed-fit | 142.185 [142.110, 142.960] | 123.705 [121.115, 133.010] |

**Integrated combination, native and WASI kept separate**

| Cell | Baseline ms | Candidate ms |
| --- | --- | --- |
| combined-native: exact-spill | 145.521 [138.771, 147.767] | 105.635 [104.530, 110.480] |
| combined-native: exact-wide | 67.055 [66.998, 68.581] | 54.262 [53.743, 57.542] |
| combined-native: mixed-retained | 146.121 [141.815, 147.391] | 117.434 [116.468, 120.714] |
| combined-native: mixed-downstream | 265.371 [264.556, 308.043] | 224.867 [224.015, 229.581] |
| combined-native: combined-fit | 45.801 [45.795, 46.031] | 33.701 [33.515, 53.311] |
| combined-browser: exact-spill | 659.905 [648.625, 689.435] | 477.495 [468.595, 488.485] |
| combined-browser: mixed-downstream | 1014.560 [993.380, 1024.280] | 810.580 [802.585, 821.620] |
| combined-browser: combined-fit | 204.440 [203.340, 213.470] | 155.175 [154.240, 156.905] |

The combined build enables only retained exact ranges and narrow mixed elision.
It was measured against production, not against the isolated candidates. The
combined-fit recipe is Auto→FY→Exact; the retained/downstream cells exercise
materialized parents and assignment. The 53.311 ms native combined-fit sample
remains in its range and prevents a claim that every fitting pair improves.
Native and browser clocks differ and must not be compared as cross-runtime ratios.

### Resource observations, distinct from elapsed

| Cell / variant | User / system s | RSS KiB | Working bytes | Logical temp read / write bytes |
| --- | --- | --- | --- | --- |
| exact-spill / baseline | 0.05 / 0.03 | 14,788 | 8,798,849 | 39,330,842 / 49,392,254 |
| exact-spill / candidate | 0.03 / 0.02 | 14,208 | 8,657,658 | 13,510,287 / 23,571,699 |
| exact-many / baseline | 0.06 / 0.23 | 6,260 | 237,544 | 36,730,990 / 8,590,279 |
| exact-many / candidate | 0.07 / 0.21 | 6,396 | 235,741 | 20,005,420 / 5,331,355 |
| mixed-wide / baseline | 0.00 / 0.01 | 10,148 | 5,782,910 | 2,477,494 / 3,902,395 |
| mixed-wide / candidate | 0.00 / 0.00 | 10,736 | 7,237,325 | 0 / 1,424,901 |
| adaptive-fit / baseline | 0.00 / 0.01 | 9,404 | 4,399,370 | 0 / 2,406,125 |
| adaptive-fit / candidate | 0.00 / 0.01 | 9,800 | 4,561,782 | 0 / 2,406,125 |
| balanced-fit / baseline | 0.00 / 0.00 | 7,364 | 1,490,904 | 2,023,575 / 1,812,648 |
| balanced-fit / candidate | 0.00 / 0.00 | 6,540 | 746,029 | 3,067,248 / 2,856,321 |
| balanced-spill / baseline | 0.08 / 0.06 | 14,580 | 8,669,192 | 77,769,298 / 72,470,407 |
| balanced-spill / candidate | 0.09 / 0.05 | 10,484 | 4,538,501 | 76,969,274 / 71,670,383 |

CPU columns are separate user/system medians in seconds, not sums of independent
peaks. RSS is GNU-time KiB; working reservations and logical temporary reads/writes
are prepublication bytes. Full per-metric ranges, fs input/output counters, sort
runs and merges are in the summary/raw records. Filesystem counters are not a
measurement of physical device traffic. Browser has no CPU/RSS metric. Exact-many
removes sorts without a material total-job gain; mixed-wide explicitly pays more
memory. These controls do not justify a hidden threshold or a broader selector.

### Independent reviews, failures and acceptance limits

Independent integrated semantics and resource source reviews both gave GO for
retained rewrites, composition and export admission ordering. Review hashes/cutoff,
owner traces and dispositions are in the replay. Two semantics coverage gaps were
closed by ordered external quota-slice and root/retained FY→exact oracles. The
resource gap was closed with a private combined selector/emitter control using
real resident owners and PlanWriter: local/shared quota denial after permutation,
serializer denial after prior-child emission, first/late-wide success, one FY,
no sort/retry, no successful failed-prefix finalization, full release and empty
cleanup. Existing prepared/Analysis clone checks retain last-owner release.
Focused public integration checks passed 7 exact and 11 mixed tests; the private
combined phase control passed separately. These counts are not cumulative across
reruns. UI tests passed 111 checks and native generated-bundle rebuilding matched.

An inherited baseline accounting gap remains: parser-origin `PackedRow::trim_fields`
can shrink without an explicit replacement-overlap grant. Ordinary first-FY and
random-key producers retain that baseline seam; the new mixed-prefix path retains
actual capacity and avoids it. Both storage files are byte-identical to baseline.
This limitation is recorded in TODO and prevents any blanket allocation/RSS-cap
claim; no corruption or newly introduced owner defect was found by source review.
Deterministic controls do not exhaust every allocator/fault schedule.

The starting browser exported progress only after admission but still emitted an
initial active export fact before checking an existing name. Move that one fact
after lookup/create admission, retaining truthful failed-rejection telemetry.
Tests require no export-start/progress or modification on existing/create-denied
destinations. Native atomic publication and browser marker semantics remain
separate, unchanged contracts.

Full failures remain retained: initial mixed cap fixture rejection, adaptive
parser-headroom fixture denial, balanced snapshot helper/empty-Dataset fixture
failures, first combined-control compile lifetime error, and browser canonical-default
verification failure. Fixture corrections kept the rejection assertions and
never weaken product contracts. The first browser helper explicitly submitted
serialization-default fields; correcting its fixture to omit those defaults
preserved the verifier assertion and used a fresh attempt namespace.

A shared-target WASM build exited zero but reused the exact candidate for the
mixed forest; compiler dependencies omitted `shuffle_elision.rs`. It is quarantined
and never counted. A separate fresh target rebuilt mixed with the expected source
dependencies. Combined WASM also used a fresh target and both dependency checks.
Successful Cargo exit alone is insufficient source binding. Native/WASM manifests
pin source forests, complete vendor sources, features, tools, assets, dependency
files, binary hashes and runner receipts. No policy-specific architecture or
feature configuration was introduced.

Final clean committed-head Linux/native Windows `scripts/local-ci.py check`
receipts remain the separate delivery gate; this immutable benchmark narrative
does not anticipate their results. The workflow restores the default production
WASM and test-free hosted package after resource-contract builds. No GitHub
Actions enablement/dispatch, public evidence publication, main push or landing
occurred as part of these measurements. Landing requires separately authorized
`python3 scripts/local-ci.py land` and matching final-head/base receipts.

### Provenance, private originals and replay

The [compact derived summary](../../benchmarks/shuffle-swarm-summary-2026-11-15.json)
contains 26 cells, exact identities, metric scopes and raw source locations.
The [private archive receipt](../../benchmarks/shuffle-swarm-archive-receipt-2026-11-15.json)
records fresh upload and independent full remote readback of bundle
`7089e97af7ba2dece5fc51e4026f7a24fcf39e0c9bd95a5f39c278154ca647d8`
(55,592,960 bytes), all 12 top-level regular members and all 2,098 nested replay
objects/4,606 path aliases. Both remote operations used the existing OAuth
principal; this is not separate scoped-reader or public-reader acceptance.
Historical registry entries and originals were preserved unchanged.

The replay archive contains baseline source, immutable native/WASM/source forests
for each candidate including rejected ones, source-matching proofs/quarantine,
full selected runner/test/failure logs, harness versions, fixtures, individual
verification receipts, verified browser exports and author/reviewer reports.
Compiler target caches, whole browser profiles and external SDK/tool/npm
installations are excluded; profiles remain local and tools are pinned in receipts.
`replay-index.json` maps retained original relative paths/modes to SHA-256 objects.
Restore selected files into a fresh owned scratch tree; do not overwrite existing
acceptance trees or historic originals. These frozen source trees, rather than
baseline HEAD alone, identify the dirty candidate builds.

- [shuffle-swarm-exact-pilot-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-77ff2794cb1bcdb7a7665a11452db0e5ffdeb3ee5da64bc8ca6088bb1c45b945)
- [shuffle-swarm-exact-controls-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-1285af2b8779050a680d09ca93521f3f8ee0c7753d710cb109ca293c3e032e03)
- [shuffle-swarm-mixed-pilot-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-9b9397619353d72eeeb082be4a06b378af7d009be0a3ea967e58c244b7ccc484)
- [shuffle-swarm-mixed-controls-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-c66d054d3e202facf6da46dccedc696da17f4cc8d54e56326dfb195bee3fcc06)
- [shuffle-swarm-adaptive-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-892212d4bbe72dcd7bfa7fde7379e83494c5d4238672cfee5ccd4e523f2d11dc)
- [shuffle-swarm-balanced-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-1fa53efffa7f15e5ebb745f8ac672b20a15546364621e85727c2de6e1375159e)
- [shuffle-swarm-combined-native-2026-11-15.jsonl](../../evidence-originals.md#sha256-e377c340638849009c163c81bd3de41935233a03c857e8f93098bc4229574c12)
- [shuffle-swarm-exact-browser-failed-2026-11-15.jsonl](../../evidence-originals.md#sha256-2983b7f39dcd3574dc77e34f81fedce721824e07cbe235b687ee5d5f021c2dba)
- [shuffle-swarm-exact-browser-2026-11-15.jsonl](../../evidence-originals.md#sha256-3c0800d25565d9523e142d10e1199c41ac60b93a88fdf9b7ee64cbc1be049229)
- [shuffle-swarm-mixed-browser-2026-11-15.jsonl](../../evidence-originals.md#sha256-6705a5d824ee7086ecdf6747d3a3be73b2a50a52bb54a4af66956f64827d6070)
- [shuffle-swarm-combined-browser-2026-11-15.jsonl](../../evidence-originals.md#sha256-e81661e96b6b0484fb528049b2ea9e8a68e9e53d07deee5503e9dadb1be010c3)
- [shuffle-swarm-replay-2026-11-15.tar.gz](../../evidence-originals.md#sha256-7bac9d054e3e201e844fba0d4c69bde806737c645812b2712fddac27508d6ebb)

Resolve these aliases using the supported [verified cache/hydration workflow](../../evidence-storage.md#archived-original-alias-resolution).
No private original is committed or exposed through the public evidence reader.
For a fresh experiment, use separate fresh source/target/output directories, match
manifest/toolchain/features/fixture identities, then the bounded commands in the
[benchmark guide](../../benchmarks/README.md#bounded-shuffle-comparisons).
`bench-shuffle-swarm.py --help` and `bench-shuffle-swarm-browser.mjs --help` list
required manifests and named recipes; no matrix runs implicitly. Preserve each
repetition and failure. Exact seeded bytes apply only to a specifically pinned
unchanged algorithm/plan diagnostic; the product makes no cross-plan guarantee.
