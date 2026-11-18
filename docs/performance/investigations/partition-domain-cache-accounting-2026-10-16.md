## Partition domain-cache accounting (2026-10-16)

Partition followed by uniform shuffle now reserves the domain cache's actual key
and table capacities in the shared workspace before allocation. This covers both
initial ingestion fusion and partition stages over intermediate datasets. A
bounded open-addressed table replaces the estimated `HashMap` allowance: spare
slots and overlapping old/new tables during rehashing are charged explicitly.
Keys move during rehashing; their allocations remain charged throughout. The
local cache ceiling remains `memory / 64` and now includes allocation overlap.
If local/shared capacity or allocation is unavailable, insertion rolls back and
the existing v1 domain is recomputed. Cache insertion failures do not propagate to the job. Cache placement hashing does not affect seeded random domains or order.

Five new tests cover exact capacity edges, table growth overlap, shared pressure,
local-limit denial after key allocation, duplicate insertion, release/retry,
5,000-key collision/rehash retention, and exact v1 partition keys with caching
disabled, partially populated and available. Workspace tests: **160 pass**;
combined `experimental-radix,experimental-distribution` library tests: **78 pass**.
The local-server integration tests require socket access outside the execution
sandbox and pass with that access.

This closes partition domain-cache retention only. Temporary operation-key
construction, selected-column vectors, lineage and its JSON serialization,
assignment-domain vectors, catalog JSON, output/codecs/input adapters, temporary
path construction and native runtime allocations remain separate work. The
ledger is still not a complete working-set or process/RSS cap. No target-SSD,
other-platform or larger-device acceptance is claimed.

Final native controls use 100,000 rows, 33 fields, one/four workers and three
alternating repetitions. The wide pipeline includes a 1.8 MB field and a 32 MiB
budget. All **60 timed jobs and 20 allocation censuses** preserve output bytes,
order, names, lineage, stage metadata and logical digests. Cache-active median
time changes span **−5.4% to +1.0%**; unaffected controls span **−4.2% to +2.2%**.
These overlapping/noisy warm WSL results do not establish a throughput gain.

| Complete native job | Workers | Before (s) | After (s) | Change |
| --- | ---: | ---: | ---: | ---: |
| `partition_shuffle` | 1 | 0.2847 | 0.2748 | -3.5% |
| `partition_shuffle` | 4 | 0.2422 | 0.2447 | +1.0% |
| `partition_pipeline` | 1 | 0.3368 | 0.3400 | +0.9% |
| `partition_pipeline` | 4 | 0.3409 | 0.3430 | +0.6% |
| `partition_pipeline_wide` | 1 | 0.4924 | 0.4659 | -5.4% |
| `partition_pipeline_wide` | 4 | 0.4614 | 0.4618 | +0.1% |
| `assign_shuffle` | 1 | 0.2949 | 0.2824 | -4.2% |
| `assign_shuffle` | 4 | 0.3037 | 0.2909 | -4.2% |
| `resident` | 1 | 0.1819 | 0.1841 | +1.2% |
| `resident` | 4 | 0.1810 | 0.1849 | +2.2% |

The final native/Chromium-WASI comparison adds **27 verified jobs** (nine
native, nine browser baseline and nine browser candidate) across partition/shuffle,
balanced/partition and plain uniform-shuffle controls, using 100,000 four-field
rows and three alternating repetitions. Output bytes/order, names, lineage,
stages and logical digests match exactly. Browser medians:

| Complete browser job | Before (s) | After (s) | Change |
| --- | ---: | ---: | ---: |
| `uniform32` | 1.3782 | 1.3033 | -5.4% |
| `balanced_partition` | 1.6260 | 1.6486 | +1.4% |
| `partition_shuffle` | 0.7641 | 0.7453 | -2.5% |

All **24 Chromium/WASI contracts pass**. These are warm WSL/OPFS measurements;
physical-device throughput and broad high-cardinality complete-job performance
remain unmeasured. The five new unit tests include 5,000 retained domains; the
complete-job fixtures have small group counts. Initial sorted-vector experiments
and a native run overlapping builds/tests are excluded from these final counts.

Artifacts: [native timings/allocations](../../evidence-originals.md#sha256-55933fc9bbb8013ba004b2aaabe74ef396c94842d61499481f729d0612fd9422 "Original: docs/benchmarks/domain-cache-native-2026-10-16.jsonl"),
[native/browser parity and timings](../../evidence-originals.md#sha256-267ae547156eec6b55f288da746594c25f42a4731c638a40a11dbf8029faef76 "Original: docs/benchmarks/domain-cache-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-6ca57b642ac649b7c2284a021f6e6e0c0f0d6fcc1b5f79e4472b5f599cfdd229 "Original: docs/benchmarks/domain-cache-browser-2026-10-16.json"),
[summary, environment and hashes](../../evidence-originals.md#sha256-d7481af67a4df51c502d46d2d4d053f9191948d9941f69ce2e6cc40c715c3ea9 "Original: docs/benchmarks/domain-cache-summary-2026-10-16.json").

Reproduce after saving baseline CLI, allocator-example and WASM binaries, then
building native/allocator and WASI releases:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases partition_shuffle partition_pipeline partition_pipeline_wide assign_shuffle resident
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  partition_shuffle,balanced_partition,uniform32 128 BEFORE.wasm
```
