## Compact dataset decode accounting (2026-10-16)

Compact intermediate dataset readers now reserve field-buffer capacity before
allocation, including old/new growth and shrink overlap. A decoded `PackedRow`
owns its reservation: dropping or exhausting the reader does not release a live
row's charge. Lending consumers reuse that reservation and its actual retained
capacity through late-wide and subsequent small rows. Sort, resident Fisher–Yates
and bounded-buffer consumers release the input charge only after their retained
reservation succeeds; direct routing keeps it with the reusable input row.
Denied reservations, malformed UTF-8 and truncation release decoded storage on
error. Spill framing and seeded algorithm identities/order are unchanged.

This is the **compact dataset field payload** slice of the working-set backlog.
Owned intermediate readers, decoded key buffers, merge/routed decode allocation
overlap beyond their existing aggregate allowances, packed-to-owned conversion,
profiling/cache metadata, codec/runtime metadata and sorting overhead remain
open. Shared decode pressure can return a clean budget error; this change does
not add pressure-triggered spill/retry to intermediate decoding. The ledger is
not a complete live-memory or RSS cap. Keeping a reservation in the row also
increases its descriptor size, including descriptors used by CSV-origin rows.

Four added tests check just-below/at/above shared growth peaks, reservation lifetime
after reader destruction, wide-to-small reuse, failed shrink, invalid UTF-8,
truncation and transfer to retained sort storage. Existing complete-job contracts
exercise cancellation, strict caps, failure without publication, grouped routing
fallback and exact seeded parity across memory budgets/workers. Workspace tests,
combined experimental-feature library tests, formatting, Clippy with warnings
denied, TypeScript and native/WASI release builds pass. Chromium/WASI contracts
also pass. HTTP tests use loopback permission; Chromium uses the staged libraries
under `/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

The existing `scripts/benchmark-compact.py` alternates complete baseline/candidate
jobs, checks exact bytes/order, names, lineage, stages and logical digests, and
records CPU, RSS, allocation censuses, temporary traffic and reservation peaks.
The native fixtures use presorted IDs, 33 columns, optional 1.8 MB fields,
one/four workers, three repetitions, resident/external uniform shuffles,
Fisher–Yates, terminal balanced output and routing/forced-sort pipelines.
`benchmark-engines.mjs` additionally compares complete native and Chromium/WASI
jobs and alternates baseline/candidate WASM. These remain warm, uncontrolled
WSL/OPFS measurements; physical SSD throughput and controlled cache conditions
are outside this pass. This is accounting work, with no throughput improvement
claim.

Native 100,000-row median seconds (one worker; four-worker percentage changes
are shown separately):

| Pipeline | Before → after | Change, one / four workers |
| --- | --- | --- |
| `streaming_pipeline` | 0.4518 → 0.4523 | +0.1% / -3.8% |
| `streaming_pipeline_wide` | 0.4581 → 0.4679 | +2.1% / +5.6% |
| `streaming_pipeline_sort` | 0.4913 → 0.4995 | +1.7% / +3.6% |
| `uniform_pipeline` | 0.2608 → 0.2838 | +8.8% / +3.0% |
| `uniform_pipeline_spill` | 0.3100 → 0.3176 | +2.5% / +0.8% |
| `uniform_pipeline_wide` | 0.3264 → 0.3262 | -0.0% / +1.4% |
| `balanced_terminal` | 0.2992 → 0.2997 | +0.1% / +1.6% |
| `balanced_terminal_wide` | 0.3261 → 0.3269 | +0.2% / -1.2% |
| `fisher_pipeline` | 0.2593 → 0.2621 | +1.1% / +2.3% |

All 108 native timed jobs and 36 separate allocation censuses pass. Descriptor
growth increases requested allocation traffic: the one-worker resident uniform
pipeline goes from 130.87 MB to 135.06 MB, with unchanged allocation counts; its
instrumented process peak rises from 20.40 MB to 21.45 MB. The routed streaming
pipeline goes from 139.46 MB to 141.55 MB, with nearly unchanged instrumented
peak (8.69 MB). These are requested allocation bytes, not RSS. Handoff briefly
holds both input and destination charges; the ledger can conservatively
double-charge those bytes until ownership transfer completes. See raw timing
ranges, CPU/RSS, I/O and allocation distributions in the artifacts below.

All 45 additional engine jobs pass exact native/baseline-WASI/candidate-WASI
output and metadata comparisons. Browser whole-job medians:

| Pipeline | Before → after (seconds) | Change |
| --- | --- | --- |
| `grouped_fisher256` | 1.7283 → 1.6789 | -2.9% |
| `balanced_partition` | 1.9876 → 1.8691 | -6.0% |
| `balanced_probabilistic_shuffle` | 3.8685 → 3.9939 | +3.2% |
| `balanced_probabilistic_sort` | 3.9099 → 3.9729 | +1.6% |
| `balanced_interleaved_shuffle` | 3.3176 → 3.0768 | -7.3% |

Browser timings are mixed and include OPFS/export work; browser CPU, allocations
and RSS are unmeasured. The fixtures do not close the full external multi-level,
device or scale matrix. The 100,000-row native and engine passes ran sequentially
after builds/contracts completed; an initial native run overlapping validation
was discarded before the recorded native pass.

Artifacts: [native timing/allocation records](../../evidence-originals.md#sha256-1d913245f0647ad4a8191c5f671218c92755e8254813d7ae520a906fdbee26b9 "Original: docs/benchmarks/dataset-decode-native-2026-10-16.jsonl"),
[native/WASI jobs](../../evidence-originals.md#sha256-bb8ac0cb591c145c311a4dd194ebdd9763a997b3a9eca5d3bc98e5f0fedc084e "Original: docs/benchmarks/dataset-decode-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-d59eba2a1a885e0c17af20a238c97af13a13232a0420593c333831d1848e7e3e "Original: docs/benchmarks/dataset-decode-browser-2026-10-16.json"),
[summary](../../evidence-originals.md#sha256-cc0495b00856492c4c6a65d5a33c4ff9ff8ce523a4afe5ca698e946ab4a37206 "Original: docs/benchmarks/dataset-decode-summary-2026-10-16.json").

Reproduce after preserving baseline native/allocator/WASM binaries, building the
candidate native release/allocator and browser release, and staging Chromium libraries:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases streaming_pipeline streaming_pipeline_wide streaming_pipeline_sort uniform_pipeline \
  uniform_pipeline_spill uniform_pipeline_wide balanced_terminal balanced_terminal_wide fisher_pipeline
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  balanced_partition,balanced_probabilistic_shuffle,balanced_probabilistic_sort,balanced_interleaved_shuffle,grouped_fisher256 \
  128 BEFORE.wasm
```
