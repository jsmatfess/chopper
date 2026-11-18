## Approved options implementation, 2026-10-13

Added three explicit alternatives; existing operation types and `auto` retain
their behavior:

- `assign_probabilistic` uses exact decimal target weights, with an independent
  seeded draw per original row ID and selected stratum tuple. It avoids counting
  or partitioning strata. Zero-weight destinations stay empty, named empty
  outputs remain present, and rows retain their encounter order per destination.
  The UI and analysis warn that counts are approximate, particularly for small
  strata. Counts displayed after preparation are the actual exact results.
- `interleaved` routes encounter position i to part `i mod files`. Counts remain
  exactly balanced, and fewer rows than parts still fails. Hard byte/row caps
  cannot silently increase the requested file count. Later operations act on
  the interleaved memberships.
- `shuffle` with `strategy: fisher_yates` performs descending Fisher–Yates swaps
  on compact resident rows using the versioned `fisher-yates-v1` random domain.
  It preserves uniformity under the existing random-source model but produces a
  different seeded permutation from random-key v1. It never silently falls back.
  Retained descriptors, payloads and vector capacity must fit one quarter of the
  configured job memory budget; an oversized group fails before publication.
  All successful runs with the same logical input/settings/seed reproduce across
  memory budgets and worker counts.

The new options are available in the native and hosted UI, ordered JSON jobs,
and convenience CLI (`--probabilistic` with `--groups`, `--interleaved` with
`--files`, and `--shuffle fisher_yates`). The manifest records the selected
options. Their versioned random rules are documented in
[the specification](../../specification.md#probabilistic-allocation).

When first in a pipeline, each option runs during ingestion. Count-independent
membership starts bounded destination routing immediately, writes decoded rows
without a pack/unpack round trip, and returns field buffers to the parser for
reuse. Too many destinations trigger the existing sorted-run fallback, reusing
already-written routes. Destination counters are explicitly reserved. No
per-stratum RNG map grows with cardinality. Later occurrences use the same
membership rules within each parent group. The old exact allocator also benefits
from bypassing packing once its router is active.

These are still prepared-snapshot workflows: routed rows may go through temporary
spools, and CSV outputs are finalized before confirmation. This work does not
introduce direct publication during ingestion or relax CSV validation.

### Measurements and recommendation

Five alternating comparisons of existing versus opt-in settings on the same
final native binary, with 200,000 rows, three columns, a 32-byte repeated payload,
one worker, and warm uncontrolled local storage. Resident shuffle uses 256 MiB;
other cases use 32 MiB. Stratified allocation has 10,000 strata of 20 rows each.
Timings include CLI preparation and publication. No builds or other test suites
were launched concurrently with these final measurements.

| Workload | Existing seconds | New option seconds | Existing/new ratio |
| --- | ---: | ---: | ---: |
| Uniform shuffle → Fisher–Yates | 0.196 | 0.197 | 1.00× |
| Consecutive balance → interleaved balance | 0.108 | 0.120 | 0.90× |
| Exact allocation → probabilistic allocation | 0.180 | 0.154 | 1.17× |
| Exact stratified allocation → probabilistic allocation | 0.466 | 0.152 | 3.07× |

**Probabilistic allocation is the performance recommendation from this fixture.**
Its temporary bytes written fell from 49.4 MB to 29.9 MB without strata, and from
90.4 MB to 29.9 MB with strata. Median peak RSS fell from about 11.9/12.5 MiB to
5.3 MiB. Actual treatment/control counts were 159,995/40,005 without strata and
159,987/40,013 with strata, versus exact 160,000/40,000 for this fixture.

Fisher–Yates showed **no clear complete-job speedup** here; its elapsed ranges
were 0.179–0.206 seconds versus 0.176–0.220 for random-key sorting. Median CPU time
was 0.16 seconds for both. This is evidence against promising a gain merely from
removing comparison sorting; parsing, field conversions, random draws and output
remain. The resident limit also makes it unsuitable as an automatic replacement.

Interleaved splitting was **about 12% slower** here (ranges 0.114–0.123 versus
0.106–0.110 seconds). Terminal consecutive balance already counts during input
ingestion and then makes one spool-to-output pass. Routing into multiple spools
does not remove that pass in the current prepared-output design, and destination
keys add about 1.6 MB of writes in this fixture. Keep this option for its requested
membership behavior; do not recommend it as a demonstrated speed improvement.
An encoded destination-output path would be a separate future optimization.

Outputs intentionally differ across the compared settings. The harness verifies
every original row and field exactly once, input order within allocation/split
destinations, interleaved membership, balance, manifest row/byte counts, equal
logical digests, and identical seeded outputs across repetitions of each setting.
It does not establish whole-job uniformity statistically, browser speedups,
cold-storage performance, billion-row scaling, or universal gains.

Raw data: [option comparisons](../../evidence-originals.md#sha256-d700c6947cae1437fd5c21db3487e349c82aac1e448d33c918a8214795ca1f1a "Original: docs/benchmarks/options-native-2026-10-13.jsonl").
Reproduce with:

```sh
python3 scripts/benchmark-options.py --binary PATH_TO_CHOPPER --rows 200000 --repeats 5
```

### Validation

All 77 native tests and workspace Clippy with warnings denied pass. New coverage
includes budget-independent seeded membership, routing versus forced sorting,
fallback after exceeding destination capacity, nested pipelines, zero weights,
empty inputs/outputs, invalid strata, exact caps, malformed CSV, oversized
resident groups, cancellation and reservation release. The convenience CLI
successfully composes all three options and records them in its manifest.

The 15-case existing-operation suite also passed three alternating A/B repetitions
against the pre-change executable (90 complete jobs), checking output bytes/order,
names, counts, lineage, stage metadata and logical digests. Physical diagnostics
can change because active routers now avoid packing decoded rows. Raw results:
[existing-operation compatibility](../../evidence-originals.md#sha256-cc264f3d7a664571f57f9b753cf85c1c3da7a6e3234733b608def418ddd5ea7d "Original: docs/benchmarks/options-compatibility-2026-10-13.jsonl").

All 21 Chromium contracts pass, including native-output golden hashes for each
new option and interleaved rejection cases. Native UI build, hosted build,
TypeScript checking and UI unit tests pass. Chromium runtime libraries were
extracted under `/tmp`; no system packages were installed. Browser measurements
here establish correctness, not an A/B performance claim.

Recorded contract results and WASM hash:
[browser verification](../../benchmarks/options-browser-2026-10-13.jsonl).
