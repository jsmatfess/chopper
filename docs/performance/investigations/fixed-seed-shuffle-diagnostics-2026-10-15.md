## Fixed-seed shuffle diagnostics, 2026-10-15

The [design](../../shuffling-research.md) was recorded before running the diagnostic
corpus. The standard-library-only `scripts/diagnose-shuffle.py` generates five
256-row fixtures, runs 32 fixed seeds through random-key v1, Fisher–Yates v1
and a four-row bounded-buffer negative control, and checks exact unique-ID
conservation, field text, group isolation, manifest sizes/counts, stage counts,
logical digests and released workspace reservations. All **480 complete native
jobs** passed those checks. This uses the pre-ingestion-change release binary;
the [JSONL record](../../evidence-originals.md#sha256-b335ce23714d7b53230b3a28c56dada3766e12c9d42e7276958e6e65a457acd5 "Original: docs/benchmarks/shuffle-diagnostics-native-2026-10-15.jsonl") includes
binary, script and design hashes, every seed's metrics and order fingerprint,
null summaries and all comparison decisions.

Each fixture uses an independent, domain-separated Python permutation reference:
1,024 pilot permutations fix the null center; 2,047 corpora of 32 permutations
calibrate two-sided departures. Six metrics cover position bins, normalized
absolute displacement, source adjacency, longest label run, window composition
and label adjacency. Group metrics are weighted by row count. The predeclared
Bonferroni family-wise threshold is 0.05/60 for full shuffles and separately
0.05/30 for controls; empirical p-values include ties and the plus-one correction.

| Algorithm | Comparisons | Flagged | Smallest empirical p |
| --- | ---: | ---: | ---: |
| random-key v1 | 30 | 0 | 0.01855 |
| Fisher–Yates v1 | 30 | 0 | 0.02051 |
| bounded buffer, four rows | 30 | 30 | 0.0004883 |

The control detects severe local mixing, including blocks sixteen times its
capacity. No primary diagnostic flags were observed. These statements concern
this finite, small resident corpus only: Python's reference is pseudorandom,
Monte Carlo resolution is 1/2048, and failure to reject does not establish
uniformity. The ascending and explicit-block fixtures retain the
same row values/labels in this v1 generator, so they repeat a workload with
separate null domains rather than add independent workload coverage. Descending
values preserve independent source-position IDs. Skewed partition groups contain
192/48/16 rows. Broader label/entity structures, external sizes and multi-worker
statistics remain future preregistered families. There is no throughput claim
or algorithm/default change.

The follow-up `scripts/diagnose-shuffle-browser.mjs` replays all 480 jobs against
the ingestion/decode-reuse native and Chromium/WASI builds. Every native order/metadata fingerprint
matches the original corpus; every browser CSV SHA-256, output name/lineage,
stage statistic and logical digest matches native. Thus the browser has exactly
the same position/label metrics and diagnostic decisions, without fitting a new
null or selecting a new statistical family. All 480 native and 480 browser
replays passed. The [browser record](../../evidence-originals.md#sha256-9a99689c4c5775f8f7a0b8937deb5afed3fdc2e132062fab5613c95714b5d5cb "Original: docs/benchmarks/shuffle-diagnostics-browser-2026-10-15.jsonl")
records engine/reference/script hashes and per-seed output hashes. This closes
resident parity for this corpus, not external-scale or broader-device statistics.

Reproduce:

```sh
python3 scripts/diagnose-shuffle.py --binary .tools/linux/target/release/chopper \
  > docs/benchmarks/shuffle-diagnostics-native-2026-10-15.jsonl
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/diagnose-shuffle-browser.mjs \
  docs/benchmarks/shuffle-diagnostics-native-2026-10-15.jsonl \
  .tools/linux/target/release/chopper \
  > docs/benchmarks/shuffle-diagnostics-browser-2026-10-15.jsonl
```
