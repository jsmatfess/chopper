## Flexible partition-first shuffle experiment (2026-10-18)

`experimental-flexible-partition` (forwarded by the browser crate) adds an
opt-in distribution-preserving plan for **adjacent flexible auto shuffle → value
partition**. The default seeded policy and all explicit uniform/Fisher–Yates/
buffer requests keep their existing selectors and semantics. This prototype is
an experiment, not a replacement for the faster exact-output fusion.

### Distribution identity and execution

Within each original parent, partition first in canonical tuple order, then
independently fully shuffle each child. Under ideal independent permutations,
a full parent shuffle followed by stable value partitioning induces precisely
that joint distribution of within-tuple orders: for tuple counts n1…nk, each
combination has N!/(n1!…nk!) possible global interleavings, hence probability
1/(n1!…nk!). The [eligibility/proof notes](../../pipeline-rewrites.md#adjacent-flexible-partition-first-prototype)
and an exhaustive five-ID test record the finite identity and its assumptions.
This changes pinned seeded output and does not establish PRNG independence or
statistical quality by itself.

The selector matches only the adjacent `auto` pair under `flexible_v1`. It never
crosses a split, assignment or another operation and never substitutes child
buffers for a full shuffle. Initial parent boundaries remain independent.
Partitioning uses the existing bounded grouping and external sort paths at its
original logical index; it materializes one immutable partitioned dataset.
Each child then attempts actual-capacity Fisher–Yates, with full random-key
sorting after resident/aggregate admission denial. Oversized children retain
that external path. The original full parent shuffle is not materialized.

Domain derivation keeps the original shuffle index and full physical child
lineage, followed by the separately versioned BLAKE3 context
`chopper.flexible.partition-first.v1`. Group records distinguish the original
logical parent from the physical partition child and label
`independent-partition-child-v1`. An `execution_rewrite` record identifies the
original two indices, physical operation order, version and distribution claim.
Logical shuffle statistics come from original parent sizes; partition statistics
come from actual grouped children. Analysis retains both stages in requested
order, while downstream operations keep their original indices and lineage.
The experimental planner is version 2; the sequential flexible planner is version
1. The existing prepared snapshot/replay contract remains authoritative.

### Controls and scope

Selector tests cover policy gating, adjacency, explicit strategies,
assignment/positional barriers and original indices. Execution tests cover
terminal/intermediate plans, multiple parents, downstream interleaving, exact
logical statistics, unique-ID conservation and separate physical/logical scopes.
The existing full-shuffle collision refinement and typed admission cleanup are
unchanged; this is a new domain/plan rather than a new collision algorithm.

An independent 38-job CLI control matrix compares the sequential and rewritten
plans. Twenty-eight successes preserve exact text/IDs, canonical tuple order,
original parent isolation, stage statistics, strict caps/counts, and cleanup
across quoted multiline Unicode/NUL data, UTF-16/BOM, headerless indices, gzip,
ZIP, empty input, named zero-quota groups and downstream splitting. Explicit
uniform, Fisher–Yates, bounded buffers and intervening interleaving confirm
selector exclusion. Ten invalid jobs reject file/record/disk limits, malformed
CSV or insufficient balanced groups without output or retained temporary files.

The complete-job native timing matrix compares original `uniform → partition`,
its exact-output fusion, existing `partition → uniform` fusion, sequential
flexible `auto → partition`, and the rewritten flexible auto plan. Whole-job
comparison includes ingestion, both stages, materialization, RNG, serialization
and publication. Unique-ID/field conservation, tuple ordering/membership,
original-parent bounds, strict encoded caps/file counts and logical statistics
are checked independently. The two exact-v1 plans also require identical
bytes/metadata. Distribution-equivalent plans require invariants and repeat
within their pinned plan, rather than equality to the original seed output.

Fixtures include 120,000 balanced/skewed/presorted rows, 60,000 rows split among
3,750 tuples, 60,000 rows with 32 extra columns, 180,000 external 512-byte-payload
rows, and 40,000 rows including one 1.8 MB payload. Parent scopes and downstream
balanced splits are included. Jobs use 32 MiB, one/four native workers, 50,000-row
and 20 MB encoded-byte caps, three alternating repetitions and warm uncontrolled
WSL filesystem cache. Rare-wide/source fixtures are generated and independently
checked outside timing. Temporary traffic is logical engine accounting, not
physical SSD throughput; RSS/allocator observations are not a hard process cap.

The first 160 successful jobs cover the first five fixtures. The initial
external fixture asked for two exact balanced outputs per group, which could
not fit its strict byte cap; the standard engine correctly rejected that
configuration. The corrected fixture uses four outputs and resumes the final
two cases. That rejection is recorded separately and excluded from timings.
The valid earlier data are retained; no engine change was needed for the cap.

Reproduce using pinned release builds and the candidate allocation profiler:

```sh
python3 scripts/benchmark-partition-first.py \
  --standard /tmp/chopper-partition-first-standard \
  --exact /tmp/chopper-partition-first-exact \
  --sequential /tmp/chopper-flexible-after \
  --candidate /tmp/chopper-partition-first-after \
  --allocator /tmp/chopper-partition-first-after-alloc
python3 scripts/validate-partition-first.py \
  --baseline /tmp/chopper-flexible-after \
  --candidate /tmp/chopper-partition-first-after
node scripts/benchmark-engines.mjs /tmp/chopper-partition-first-after 100000 3 \
  flex_reverse_auto,flex_reverse_uniform,flex_reverse_parents_auto 128 \
  /tmp/chopper-flexible-after.wasm \
  --native-before=/tmp/chopper-flexible-after --interleave-cases
```

Build the standard, exact and rewritten engines with no experiment,
`experimental-shuffle-partition`, and `experimental-flexible-partition`
respectively; the sequential baseline uses `experimental-flexible`. Browser
comparison builds forward the corresponding features. The Chromium runner needs
its local runtime-library path and loopback access. All timed native and browser
matrices run separately from heavy build/test work.

### Complete-job results and decision

All 210 timed native jobs, 70 allocation censuses, 36 native/WASI comparisons,
38 CLI controls and 24 Chromium/WASI contracts pass. The planner checkpoint
passes 255 all-feature workspace tests, including 162 library tests; formatting
and all-feature Clippy pass. The separate XOF-source experiment adds its own
coverage and does not supply the RNG used in these measurements.

| Fixture / workers | Original (s) | Exact fusion (s) | Partition/shuffle fusion (s) | Sequential flexible (s) | Rewritten flexible (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| balanced / 1 | 0.2413 | 0.1958 | 0.2025 | 0.2755 | 0.2279 |
| balanced / 4 | 0.2402 | 0.1944 | 0.2009 | 0.2742 | 0.2278 |
| skewed / 1 | 0.3472 | 0.2663 | 0.2737 | 0.3773 | 0.3846 |
| skewed / 4 | 0.3442 | 0.2694 | 0.2767 | 0.3816 | 0.3901 |
| many / 1 | 8.8810 | 8.7649 | 8.7287 | 8.8202 | 8.9877 |
| many / 4 | 9.1720 | 8.8870 | 8.9497 | 9.0210 | 9.1689 |
| presorted / 1 | 0.2756 | 0.2185 | 0.2166 | 0.3099 | 0.2596 |
| presorted / 4 | 0.2863 | 0.2226 | 0.2317 | 0.3043 | 0.2607 |
| columns / 1 | 0.5214 | 0.4174 | 0.4400 | 0.5606 | 0.4796 |
| columns / 4 | 0.5175 | 0.4303 | 0.4426 | 0.5459 | 0.4881 |
| external / 1 | 0.9527 | 0.8334 | 0.8148 | 1.0064 | 1.0693 |
| external / 4 | 1.0275 | 0.8074 | 0.8400 | 1.0668 | 1.0522 |
| rare_wide / 1 | 0.2571 | 0.2404 | 0.2421 | 0.2579 | 0.2724 |
| rare_wide / 4 | 0.2407 | 0.2534 | 0.2317 | 0.2536 | 0.2685 |

The rewrite improves balanced/presorted/column-heavy jobs by approximately
11–17% against sequential flexible execution. Skew, high-cardinality and rare-wide
controls regress roughly 2–6%; the external controls range from 6% slower to 1%
faster. Every rewritten native median trails the exact-output fusion. High
cardinality is dominated by creating/publishing 3,750 output files: roughly
nine seconds wall time versus around one second CPU across plans. Smaller
shuffles alone do not win the full job.

One-worker paired allocation/traffic examples:

| Fixture / plan | Whole-job allocations | Peak live requested MB | Peak tracked temporary MB | Temporary bytes written MB |
| --- | ---: | ---: | ---: | ---: |
| balanced / exact | 361,285 | 8.46 | 31.82 | 31.82 |
| balanced / sequential | 634,187 | 7.94 | 49.10 | 75.17 |
| balanced / candidate | 481,715 | 7.93 | 40.84 | 57.53 |
| external / exact | 546,274 | 8.68 | 258.13 | 415.28 |
| external / sequential | 931,646 | 9.74 | 260.96 | 720.94 |
| external / candidate | 913,988 | 8.69 | 354.09 | 710.22 |

The balanced rewrite reduces allocations/temporary writes against sequential
flexible execution but remains substantially above exact fusion. For the large
external fixture, write traffic barely falls against sequential execution while
peak temporary space increases from 261 MB to 354 MB; exact fusion writes about
415 MB compared with the rewrite’s 710 MB. Retaining partition materialization
and an external child shuffle carries a large cost. Full census/RSS/reservation
records are retained; census timing is perturbed by atomic allocation tracking.

The separate browser matrix uses 100,000 rows with 128-byte payloads, seven
country tuples, 32 MiB and one/two original parents. Matching pinned sequential
and rewritten plans each require exact native/WASI byte/metadata parity; the two
plan families are compared by conservation and logical metadata instead.

| Requested case | Native sequential (s) | Native candidate (s) | Browser sequential (s) | Browser candidate (s) |
| --- | ---: | ---: | ---: | ---: |
| flex_reverse_auto | 0.2829 | 0.2253 | 3.7736 | 2.8155 |
| flex_reverse_parents_auto | 0.3108 | 0.2634 | 4.6271 | 3.6928 |
| flex_reverse_uniform | 0.2906 | 0.2797 | 3.4560 | 3.7634 |

Browser auto medians improve about 25% globally and 20% with two parents. The
explicit uniform exclusion control regresses about 9%, despite unchanged
requested algorithms/output. Three warm repetitions and that mixed control
limit the confidence and generality of the gains. The prototype remains
**opt-in**: it demonstrates a correct, audited distribution plan and per-child
admission, but does not justify changing defaults or replacing exact fusion.
Fast RNG/random buckets, full fixed-corpus diagnostics for rewritten algorithms,
broader multi-level/device calibration and complete memory accounting remain
separate work.

Raw evidence: [native timings/censuses](../../evidence-originals.md#sha256-dfa864dc6d20941342fc323e368ce39af6364a4f77f702036ad41768f2a838e4 "Original: docs/benchmarks/partition-first-native-2026-10-18.jsonl"),
[native/WASI plans](../../evidence-originals.md#sha256-cd14e232a60edb122d5e3b5833eeae976466503102daad4c72645be2208ce95b "Original: docs/benchmarks/partition-first-engines-2026-10-18.jsonl"),
[summary/ranges/hashes](../../evidence-originals.md#sha256-37eb44bad78891783939ee1d1825f7bee87d4791469ee744f8bcc333b21f3a3f "Original: docs/benchmarks/partition-first-summary-2026-10-18.json"),
[38 CLI controls](../../evidence-originals.md#sha256-6d4a7875341ea29e632669e6ca2c494e1fbf6fb7007040c9312193bfa0909917 "Original: docs/benchmarks/partition-first-controls-2026-10-18.jsonl"),
[24 browser contracts](../../evidence-originals.md#sha256-17c2681e9917e203ba38e5ae4b4c5e8cab14a7c734a31eb00091e1ff634119f6 "Original: docs/benchmarks/partition-first-browser-2026-10-18.json"), and
[excluded invalid-cap rejection](../../evidence-originals.md#sha256-ce6b340000f8337dde6b4f902092ec57f099b127f19ce213f8e029171a76104f "Original: docs/benchmarks/partition-first-invalid-external-2026-10-18.log").
