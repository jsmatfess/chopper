## E4 explicit probabilistic-allocation advice (2026-10-28)

**Decision: retain the explicit option, withhold general app speed advice and
automatic substitution.** This bounded native pass demonstrates useful savings
on its stratified shapes and substantial within-stratum count variation. It does
not supply a universal acceptable deviation, a runtime predictor or browser advice.
Choosing probabilistic allocation remains an explicit CLI/app operation with its
approximate-count warning; exact allocation remains available and unchanged.

The [frozen harness](../../benchmarks/e4-allocation-advice-2026-10-28.py) ran four shapes,
three fixed seeds and two repetitions per seed/option: 48 complete CLI jobs on
Windows, alternating exact/probabilistic order. Each cell has six observations
per option nested under three seeds, not six independent workloads. Timing covers
process startup, configuration decoding, preparation and publication; no optional
profile was requested. Generation and verification are excluded. Warm filesystem
cache is uncontrolled. No builds or correctness suites ran during measurement.
The declared stop was first failure, with no matrix expansion, a 12-minute
measurement ceiling, 60-second job deadline and under 1 GiB working-data estimate.
All jobs and verification passed; no observations were discarded.

Both options use the same default release binary
`5d317c632c2e2d398cfa831a30696808ef6eb81c04af62064e9d6dae92d410b2`,
32 MiB numeric memory, one worker, 64-byte repeated payloads, no compression and
an active 262,144-byte serialized CSV cap. The release build derives from the
[validated Auto/reproducibility source](../../validation.md#reproducibility-and-opt-in-automatic-memory-2026-10-28).
Build/source/vendor manifests and full release logs remain under
`.tools/todo-auto-20261028/`; full command/configuration logs and source fixtures
remain under `.tools/todo-e4-20261028/`. The raw design record pins binary, source
proof, generator/harness and Win32 counter implementation hashes.

| Shape / treatment target | Exact seconds, median [range] | Probabilistic seconds, median [range] | Exact/probabilistic median ratio |
| --- | --- | --- | --- |
| 4,000 rows, unstratified / 50% | 0.068 [0.063–0.186] | 0.075 [0.071–0.084] | 0.90 |
| 4,000 rows, 1,000 strata of four / 1% | 0.107 [0.103–0.115] | 0.065 [0.052–0.077] | 1.65 |
| 60,000 rows, 90:9:1 stratum skew / 20% | 0.225 [0.222–0.247] | 0.130 [0.127–0.139] | 1.73 |
| 200,000 rows, 1,000 strata of 200 / 80% | 1.210 [1.172–1.270] | 0.771 [0.740–0.791] | 1.57 |

The first small exact run's 0.186 seconds remains included. The small cell's
overlapping ranges and slower probabilistic median do not support advice to
switch. The three stratified cells have separated observed ranges, but their
absolute savings and limited seed/shape panel do not establish a general selector.
The larger exact cell makes 14 sort runs; probabilistic makes none. Median peak
tracked temporary bytes are 74.60 versus 37.43 MiB there, and peak Win32 working
sets are 16.37 versus 9.74 MiB. Median process CPU is 0.625 versus 0.312 seconds.
These are separate accounting/OS observations: temporary counters omit private
final output, working set is not the admission ledger, and process transfer bytes
do not establish physical device I/O. No simultaneous peaks are added together.

Every stratum's realized counts, signed deviations from decimal targets and empty
destinations are retained for each seed/option. Repetitions reference matching
count hashes rather than adding independent count observations. In the four-row,
1% case, exact largest-remainder quotas give zero treatment rows in every stratum;
probabilistic totals are 44, 41 and 33, against 40 expected over the population.
Yet 956, 959 and 970 of 1,000 strata have no treatment rows. Maximum within-stratum
deviation reaches 49 percentage points in the third seed. A population total near
its target therefore says little about tiny-stratum allocation.

The unstratified treatment totals are 1,942/1,999/1,990 against 2,000 expected.
The skew case totals are 11,794/12,011/11,899 against 12,000, with maximum
within-stratum deviations of 0.83/2.83/0.50 percentage points. The larger-strata
case totals are 159,899/159,906/159,914 against 160,000, while maximum stratum
deviations are 9.5/10.5/9.0 percentage points. These finite observations describe
the panel; they are neither probability bounds nor proof of distribution quality.

The harness verifies each original ID/field exactly once, per-destination encounter
order across chunks, exact largest-remainder quotas where requested, logical
digests, manifest counts/bytes, strict caps, temporary cleanup and identical seeded
replay per option. Exact and probabilistic memberships intentionally differ.
Current failure/cancellation/publication coverage is recorded separately in
[validation](../../validation.md). Browser performance, other platforms/devices, cold
storage, optional-profile cost and larger scale remain unmeasured here. The
conservative outcome is the existing explicit advanced option with clear variation
language and no generic performance recommendation; E5 is separate.

Raw observations: [48-job/count panel](../../evidence-originals.md#sha256-29a8a1d931617cd96073c447a2f53de6e0a321727d8bbbc0b33c6193ae1882a7 "Original: docs/benchmarks/e4-allocation-advice-native-2026-10-28.jsonl").
The [derived summary](../../evidence-originals.md#sha256-ce8e9a233f521ed6154288f293cd22aed8471ce9505d476db3345d8132b84486 "Original: docs/benchmarks/e4-allocation-advice-summary-2026-10-28.json")
identifies physical JSONL observation lines and the raw source hash; it is not
additional measurement evidence.

Current status (2026-10-24): independent random buckets and buffered XOF have been
removed. Their dated sections below preserve historical builds, measurements,
requests and interpretation; they do not describe current supported features.
See [validation](../../validation.md#independent-buckets-and-buffered-xof-removal-2026-10-24).

Measurements and validation through 2026-10-23. Each dated pass describes its own build, fixtures and limitations; earlier test counts and remaining-work notes are historical. Results from separate passes are not a single controlled comparison. See [validation](../../validation.md) for the evidence summary, [TODO](../../../TODO.md) for active work, and [opportunities](../../performance-opportunities.md) for experiment designs.

Browser storage context correction (2026-10-17): earlier Playwright runs used
new temporary browser contexts. Their OPFS timings and logical I/O observations
remain valid for those contexts, but do not establish disk-backed OPFS behavior.
A storage-only reproducer in the installed Chromium returns an invalid write
count after approximately 1 GiB of retained data in a temporary context, while a
persistent profile completes 1.5 GiB. New external-browser comparisons use a
persistent profile and record it explicitly; neither context measures physical
SSD I/O. See the [storage diagnostic](../../benchmarks/browser-opfs-contexts-2026-10-17.jsonl).
