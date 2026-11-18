## Billion-row native full-shuffle acceptance point (2026-10-16)

One complete native job now shuffles **1,000,000,000 uniquely identified,
presorted rows** using uniform random-key v1 and emits four balanced CSV files of
250,000,000 rows each. Four fields contain the ID, seven cycling country labels,
three cycling segments and an empty payload. This is a narrow full-permutation
acceptance point, beyond the earlier repeated-value billion-row plain-copy test.
It does not certify wide/high-cardinality or terabyte workloads.

The WSL2 host reports an AMD Ryzen AI 9 HX 370 and about 15.2 GiB Linux memory.
The job uses **256 MiB configured memory, four native workers, a 256 GiB overall
experiment disk ceiling and a two-hour deadline**. Its original source is
15,888,888,917 bytes; final CSV is 17,888,888,998 bytes (empty fields are quoted).
The source was generated immediately before execution. Source and spills exceed
available page cache; Linux/Windows/device cache behavior is uncontrolled, not a
controlled warm/cold SSD measurement.

| Measurement | Result |
| --- | ---: |
| Fixture generation | 128.4 s |
| Complete preparation + publication | 1,131.4 s |
| Preparation (including fused final encoding) | 1,108.1 s |
| Native user / system CPU | 952.7 / 188.9 s |
| Native peak RSS (GNU time) | 57,368 KiB (56.0 MiB) |
| Peak charged workspace | 67,308,105 bytes (64.2 MiB) |
| Engine peak temporary data | 109,777,450,329 bytes (102.2 GiB) |
| Sort runs / merge operations / merge inputs | 2,892 / 46 / 2,937 |
| Native sort-loop wall time | 24.84 s |
| Logical temporary reads / writes | 170.8 / 187.5 GiB |
| Initial exact conservation check | 246.2 s |
| Supplemental lexical-ID/value check | See recheck artifact |

The run crosses hierarchical merge levels. Its final stage statistics, filenames,
lineage, CSV byte counts and logical digest are retained in the raw result.
Reported workspace reservations remain an incomplete algorithm ledger, and the
observed RSS is not a memory cap. Engine temporary counters exclude source and
publication filesystem space. GNU filesystem input/output counters are zero in
this environment; that does not mean no physical I/O occurred.

Exact acceptance uses a streaming strict CSV checker and a **125,000,000-byte
ID bitset**, independent of the engine's conservation counters. Every ID must
be canonical decimal text in range, occur once, retain its expected country and
segment, and have an empty payload. Headers, widths, manifest counts and encoded
file sizes are checked. Range + uniqueness + exact total prove ID conservation.
All four output BLAKE3 hashes are recorded. The checker accepts a valid control
and rejects duplicate, missing, out-of-range and altered-value controls, including
changed ID spelling (`01`). A million-row complete-job smoke test also passes.

The original runner's checker validated numeric IDs; a separate hardened pass
against retained hard links additionally validates ID spelling. Its field/count
results and every output hash agree exactly with the original pass. Retained
links and all large temporary data have been cleaned up after evidence capture.

**Build scope:** the copied native executable includes the output snapshot writer
buffer-accounting step, and predates the later serializer/digest-accounting
candidate. Binary/generator/verifier hashes are recorded. This is one seeded
native acceptance point, not a billion-row comparison across builds, budgets,
worker counts or runtimes. Later changes still require their own validation;
no billion-row browser, wide-record, high-cardinality or terabyte result follows.
The filesystem had about 923 GiB available before this run, below a full terabyte
of retained output even before source/spill overhead, so that acceptance remains
outside this host's capacity.

Artifacts: [complete run and resource heartbeats](../../evidence-originals.md#sha256-eb44c61e9561d4f1db4ea43f090a511d11c344c10f30378bcc677ba6ebe119b4 "Original: docs/benchmarks/shuffle-billion-2026-10-16.jsonl"),
[hardened supplemental verification](../../evidence-originals.md#sha256-e47905c69759383a492762a8a0af68328e96bfc800f8dd063f8fcbfc20501565 "Original: docs/benchmarks/shuffle-billion-recheck-2026-10-16.json"),
[checker controls](../../evidence-originals.md#sha256-857398e6cf4341690a006d434f5d4bf110ad3b866c7fcc7868a1f5063450f4d7 "Original: docs/benchmarks/shuffle-scale-verifier-controls-2026-10-16.json"),
[million-row smoke](../../evidence-originals.md#sha256-2d6db1dfc92fe79665fbeef4ded3e4b8f403010dc80e96ed7d5566dbc39637c0 "Original: docs/benchmarks/shuffle-scale-smoke-2026-10-16.jsonl"),
[scope, summary and raw measurements](../../evidence-originals.md#sha256-275a42669416c3dedd8d2a18b9a46ef2d392c4999a404ebe0b4073b8f5f4836c "Original: docs/benchmarks/shuffle-billion-summary-2026-10-16.json").

```sh
cargo build --release --locked -p chopper --bin chopper --examples
python3 scripts/benchmark-shuffle-scale.py --rows 1000000 --disk-gib 8 --seconds 300
python3 scripts/benchmark-shuffle-scale.py --rows 1000000000 --memory-mb 256 \
  --workers 4 --disk-gib 256 --seconds 7200
```

The harness uses a private job directory, reserves source/destination headroom
separately from the engine temp budget, kills timed-out process groups and cleans
up on failure. This is cleanup/budget evidence, not power-loss testing.
