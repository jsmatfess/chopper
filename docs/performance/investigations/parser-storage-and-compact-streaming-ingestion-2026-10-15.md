## Parser storage and compact streaming ingestion, 2026-10-15

Native CSV ingestion now returns narrow field storage to the reusable parser
after random-key/Fisher–Yates packing and fused partition ingestion. Previously
these paths packed each row and discarded its strings/vector, allocating them
again for the next record. Rare wide rows still transfer owned strings directly.
Later interleaved/probabilistic allocation stages now consume checked compact
spool fields; categorical v1 hashing reads borrowed views with unchanged column
order, length framing and draws. This removes per-field unpack/repack between
the input spool and routing/sorting. Direct CSV parsing and logical hashing still
use owned, reusable strings; direct packed parsing/digest integration remains open.
No shuffle algorithm, version, default or seed domain changes.

The [native A/B record](../../evidence-originals.md#sha256-bc88f6de829bb40f78b3539adbf3f175385a11e2c79768a157bfd882a55ae072 "Original: docs/benchmarks/parser-reuse-native-2026-10-15.jsonl") contains
120 alternating timed jobs and 40 allocation-census jobs: 300,000 rows, 33 fields,
three repetitions, one/four workers, resident/external shuffle, grouped ingestion
and downstream streaming allocation followed by uniform shuffle. Wide cases
include a 1.8-million-byte field. Exact byte/order, names, lineage, stages and
logical-digest fingerprints match the saved baseline binaries. Whole-job wall,
CPU, RSS, reservations and logical temporary I/O/space diagnostics are recorded.
Fixture generation and validation are outside timing. Builds/tests finished
before the timing pass. These are warm, uncontrolled WSL storage measurements,
not physical SSD throughput or controlled cold-cache evidence.

| Complete job | Workers | Median seconds before → after | Reduction | CPU seconds before → after | RSS MiB before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| resident random-key | 1 | 0.777 → 0.571 | 26.5% | 0.70 → 0.50 | 117.1 → 117.0 |
| resident random-key | 4 | 0.758 → 0.552 | 27.2% | 0.70 → 0.50 | 117.2 → 116.7 |
| resident Fisher–Yates | 1 | 0.782 → 0.580 | 25.8% | 0.71 → 0.52 | 117.1 → 116.8 |
| resident Fisher–Yates | 4 | 0.772 → 0.568 | 26.4% | 0.70 → 0.51 | 117.1 → 116.8 |
| external random-key | 1 | 0.865 → 0.663 | 23.3% | 0.78 → 0.60 | 13.0 → 13.0 |
| external random-key | 4 | 0.857 → 0.668 | 22.0% | 0.81 → 0.62 | 12.7 → 13.2 |
| external, rare wide | 1 | 0.879 → 0.687 | 21.9% | 0.79 → 0.61 | 16.2 → 14.9 |
| external, rare wide | 4 | 0.868 → 0.675 | 22.2% | 0.82 → 0.63 | 16.0 → 14.7 |
| partition + shuffle | 1 | 0.957 → 0.763 | 20.3% | 0.85 → 0.67 | 135.3 → 135.2 |
| partition + shuffle | 4 | 0.943 → 0.703 | 25.5% | 0.88 → 0.67 | 135.4 → 135.3 |
| partition, spill | 1 | 0.856 → 0.624 | 27.1% | 0.75 → 0.54 | 13.7 → 13.3 |
| partition, spill | 4 | 0.843 → 0.624 | 26.0% | 0.74 → 0.53 | 13.7 → 13.5 |
| balanced + probabilistic + shuffle | 1 | 1.649 → 1.492 | 9.5% | 1.51 → 1.37 | 13.1 → 12.5 |
| balanced + probabilistic + shuffle | 4 | 1.656 → 1.505 | 9.1% | 1.54 → 1.40 | 13.1 → 12.4 |
| same, forced sorting | 1 | 1.761 → 1.550 | 12.0% | 1.62 → 1.42 | 15.4 → 15.5 |
| same, forced sorting | 4 | 1.749 → 1.600 | 8.5% | 1.66 → 1.53 | 15.3 → 15.5 |
| balanced + interleaved + shuffle | 1 | 1.586 → 1.459 | 8.0% | 1.44 → 1.32 | 13.2 → 12.5 |
| balanced + interleaved + shuffle | 4 | 1.604 → 1.417 | 11.7% | 1.50 → 1.32 | 13.0 → 12.5 |
| probabilistic pipeline, rare wide | 1 | 1.651 → 1.511 | 8.5% | 1.52 → 1.38 | 14.7 → 14.3 |
| probabilistic pipeline, rare wide | 4 | 1.641 → 1.506 | 8.2% | 1.54 → 1.41 | 14.7 → 14.2 |

One-worker resident random-key allocations fall from **10,500,894 to 300,929**
and reallocations from 1,200,051 to 55; requested allocation bytes fall from
1.141 GB to 168.9 MB. Peak live requested bytes remain about 130.9 MB: retained
row representation is unchanged. The resident Fisher–Yates census is similar.
External allocations fall from 10,800,994 to 601,029, with nearly unchanged
8.63 MB peak live requested bytes. Routing pipeline allocations fall from
11,401,567 to 1,501,567, but requested bytes increase from 663.5 to 747.5 MB:
each compact input decode initially allocates descriptor slack and then trims it.
That remaining decode allocation/reallocation cost motivates the separate
streaming decode-storage reuse follow-up. Fewer allocations do not imply lower
peak RSS or total requested bytes on every path.

Correctness: independent categorical v1 framing tests cover selected/repeated
columns, empty fields, Unicode/NUL/newlines and wide payloads. Compact versus
owned streaming tests compare exact dataset frames and group metadata under
routing, 70-way routing fallback and forced sorting. Existing seeded fixtures,
strict CSV/cap/cancellation, multi-level merges and malformed-spill checks pass.
The first pass passed 105 workspace tests, 30 combined-feature library tests,
formatting, workspace/all-targets/all-features Clippy, TypeScript checks and
native/WASI release builds. All **23 Chromium/WASI contracts** passed, including
new streaming pipelines hashed against the saved pre-change native binary.
[Browser record](../../evidence-originals.md#sha256-85766b108ab3228f3fbceab00d6dfe059391ba5199d7be7131dac06ae8dcf239 "Original: docs/benchmarks/parser-reuse-browser-2026-10-15.json").

Reproduce with baseline CLI/allocation binaries saved before this change:

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-parser-reuse-before/chopper \
  --after .tools/linux/target/release/chopper \
  --before-allocator /tmp/chopper-parser-reuse-before/allocation-profile \
  --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases resident fisher spill rare_wide partition_shuffle partition_spill \
    streaming_pipeline streaming_pipeline_sort interleaved_pipeline streaming_pipeline_wide
```
