## Resident full-shuffle comparison, 2026-10-15

The first full-shuffle experiment compares the existing random-key v1 and
Fisher–Yates v1 implementations on identical complete jobs. Defaults remain
unchanged: there is no consistent whole-job Fisher–Yates advantage across these
fixtures, and seeded orders differ by algorithm.

### Method and complete-job results

AMD Ryzen AI 9 HX 370, WSL2 x86-64, 1,024 MiB job budget, warm uncontrolled local
storage, one fixed seed and one/four native workers. Each shape runs a 16-row
single group, a 300,000-row single group, and balanced(100) → shuffle with
3,000 rows per group. IDs ascend in source order. Narrow rows have two fields;
many-column rows have 33; rare-wide rows use the same 33 columns with a single
1,800,000-byte field. Payloads repeat while unique IDs identify every record.

Five alternating repetitions per algorithm/case/worker count produce **180 timed
jobs**, plus **36 separate allocation-census jobs**. Builds and correctness tests
finished before this final timing run. Timings include CLI startup, CSV ingestion,
RNG, preparation, serialization and publication; fixture creation and verification
are excluded. Allocation instrumentation is excluded from timing summaries.

Median complete-job seconds (the raw artifact also records every sample and range):

| Shape | Group size | Random-key, 1 worker | Fisher–Yates, 1 worker | Random-key, 4 workers | Fisher–Yates, 4 workers |
| --- | --- | ---: | ---: | ---: | ---: |
| Narrow | 16 | 0.0110 | 0.0095 | 0.0088 | 0.0091 |
| Narrow | 300,000 | 0.2158 | 0.2231 | 0.2137 | 0.2326 |
| Narrow | 100 × 3,000 | 0.4694 | 0.4423 | 0.4550 | 0.4363 |
| 33 columns | 16 | 0.0092 | 0.0087 | 0.0093 | 0.0090 |
| 33 columns | 300,000 | 0.8940 | 0.8813 | 0.8291 | 0.8171 |
| 33 columns | 100 × 3,000 | 1.1043 | 1.0111 | 1.0931 | 1.0277 |
| 33 columns + rare wide field | 16 | 0.0154 | 0.0149 | 0.0152 | 0.0154 |
| 33 columns + rare wide field | 300,000 | 0.8140 | 0.8903 | 0.8549 | 0.8867 |
| 33 columns + rare wide field | 100 × 3,000 | 1.0663 | 1.0528 | 1.0435 | 1.0553 |

The tiny cases are dominated by startup and fixed costs. Small-group narrow/many-column medians
favor Fisher–Yates on this corpus; small-group rare-wide results are mixed.
Large narrow/rare-wide groups favor random-key sorting. Many-column large groups differ little. Sample ranges overlap
in several cases; this single-seed warm-storage experiment establishes neither a
universal speedup nor a threshold for automatic algorithm selection.

### Loop attribution and memory

New `fisher_yates_calls`, `fisher_yates_rows` and `fisher_yates_seconds` diagnostics
count completed resident shuffles and time their RNG draws, cancellation checks
and descriptor swaps. Existing `sort_seconds` measures comparison sorting plus
Rayon dispatch/join, excluding random-key generation. Both exclude ingestion and
output, so these are attribution measurements with different included work,
not interchangeable complete-algorithm benchmarks. Median large-group loop times:

| Shape | Workers | Random-key sort only | Fisher–Yates RNG + swaps |
| --- | ---: | ---: | ---: |
| Narrow | 1 | 0.0166 s | 0.0566 s |
| Narrow | 4 | 0.0064 s | 0.0600 s |
| 33 columns | 1 | 0.0166 s | 0.0605 s |
| 33 columns | 4 | 0.0057 s | 0.0569 s |
| 33 columns + rare wide field | 1 | 0.0158 s | 0.0621 s |
| 33 columns + rare wide field | 4 | 0.0064 s | 0.0595 s |

All jobs have zero sort spills/merges and release workspace reservations. Both
algorithms reserve the same peak workspace on each fixture. Large-group peaks
are about 54.5 MiB for narrow rows, 129.8 MiB for 33 columns and 131.8 MiB with
the rare wide field. These are current engine reservations, not complete
allocation accounting or RSS caps. Census counts/bytes and peak live requested
bytes are effectively identical between algorithms; the raw artifact includes
size distributions, CPU seconds, RSS, temporary traffic and disk-space peaks.

Both implementations already permute compact descriptors while payloads retain
their allocations. These measurements do not attribute a bottleneck to descriptor
movement or establish a memory advantage for indices. An index permutation would
add at least one index array (2.29 MiB for 300,000 native 64-bit indices), plus
indirection/application costs, so no index variant is introduced in this pass.

### Correctness, reproduction and limits

Every timed and census job verifies exact unique-ID conservation, field text,
group isolation, headers, manifest row/CSV-byte counts, logical input digests,
stage metadata and seeded byte/order replay within each algorithm across repeats
and worker counts. Different algorithms are intentionally not compared for order.
The existing seeded fixtures, collision/refinement, malformed-input, cancellation
and budget tests remain in the workspace suite. All **86 workspace tests** pass
(the two local-server tests require socket access outside the sandbox); formatting,
Clippy with warnings denied, native release and browser/WASI release builds pass.
The composition test also checks accumulated Fisher–Yates diagnostics for first
and intermediate grouped shuffles.

```sh
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
python3 scripts/benchmark-resident-shuffle.py \
  --binary .tools/linux/target/release/chopper \
  --allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 300000 --repeats 5 \
  > docs/benchmarks/resident-shuffle-native-2026-10-15.jsonl
```

Use `target/release` in environments without the repository-local toolchain.
[Raw measurements](../../evidence-originals.md#sha256-e0b6842ac13949d6a701ea6bab0f817f04f60ad1365615a5ff43e63c760f1289 "Original: docs/benchmarks/resident-shuffle-native-2026-10-15.jsonl") include
binary hashes and fixture parameters. This closes the native resident comparison;
browser timing, external algorithms, constrained memory thresholds, controlled
cold/slow storage, physical I/O, broader seeds/statistical diagnostics and
large-scale acceptance remain separate TODO items. No automatic selection,
reproducibility policy or shuffle implementation changes are enabled.
