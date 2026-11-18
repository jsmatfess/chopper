## Streaming group state accounting (2026-10-16)

Probabilistic and interleaved membership now reserve counts, resolved-column
indices and weights before allocating them. Actual capacities remain charged
through routing, sorting fallback and emission. The existing one-sixteenth local
metadata ceiling remains in effect. Column and weight validation failures drop
partial storage and release reservations; shared pressure can deny construction
before allocation and callers can retry after the competing reservation ends.
Seeded draws, tuple framing, membership, ordering and defaults are unchanged.

Two new tests cover just-below/at/above capacity, competing reservations,
failure/retry, invalid columns/weights and local-limit cleanup. **166 workspace
tests, 84 combined-feature library tests and 24 Chromium/WASI contracts pass.**

The final matched-source native comparison contains **84 timed complete jobs
and 28 allocation censuses**: 100,000 rows, 33 fields, one/four workers, three
alternating repetitions. Cases cover probabilistic routing/forced sorting,
stratified downstream shuffle pipelines, interleaving, rare-wide records and an
unchanged resident-shuffle control. All preserve exact output bytes/order,
filenames, lineage, stage counts and logical digests. Median changes range from
**−1.4% to +1.8%**; no throughput improvement is established. Allocation counts
are unchanged; resolving columns into exact storage removes a few scratch bytes
on the tested stratified pipeline.

The native/Chromium-WASI matrix adds **36 verified complete jobs**: 12 native,
12 browser baseline and 12 browser candidate, with four-field 100,000-row inputs,
three alternating repetitions and probabilistic routing/sort, interleaving and
uniform-shuffle controls. Browser candidate median changes are −3.6% to +3.6%;
all output/profile-independent metadata checks pass. These are warm uncontrolled
WSL/OPFS measurements, with uncontrolled host load, not physical SSD evidence.

The initial native pass used a pre-existing on-disk baseline and showed ~33–37%
regression even on the unchanged control. It is retained as **superseded**, with
no causal claim. The final baseline was rebuilt from the current source with
only the streaming constructor restored, using the same release settings as the
candidate. The candidate was explicitly rebuilt after copying baseline artifacts
out of the shared target directory. Do not compare stale top-level Cargo outputs
from different source workspaces as though they were matched builds.

Artifacts: [matched native jobs and allocations](../../evidence-originals.md#sha256-e64e06e9f5f1fe294fd0f66a932fe342fa1a50f2a464bf3f082905833ec69070 "Original: docs/benchmarks/streaming-state-matched-native-2026-10-16.jsonl"),
[native/browser timings and parity](../../evidence-originals.md#sha256-28aaea7de03b0cba416a3f18dcc9ff9bb54da273ebc5ad558198f5fe3ebc1b65 "Original: docs/benchmarks/streaming-state-engines-2026-10-16.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-308b5f2573b72290045d7c8a831eaf6c3bd38eeaa583af11c1cf55a85850947e "Original: docs/benchmarks/streaming-state-browser-2026-10-16.json"),
[summary and build hashes](../../evidence-originals.md#sha256-2a927023cd71bba6a719da0ea09ab6cf6323e1d248ab1fe2562790c694b88878 "Original: docs/benchmarks/streaming-state-summary-2026-10-16.json"),
[superseded initial native pass](../../evidence-originals.md#sha256-9bd83c0d4afe401bcc5a9146ba5b6531d4d247800639079f8e7aa754021a34a2 "Original: docs/benchmarks/streaming-state-native-2026-10-16.jsonl").

Reproduce with matched baseline CLI/allocator/WASM artifacts, then:

```sh
python3 scripts/benchmark-compact.py --before BEFORE --after .tools/linux/target/release/chopper \
  --before-allocator BEFORE_ALLOCATOR --after-allocator .tools/linux/target/release/examples/allocation-profile \
  --rows 100000 --workers 1 4 --repeats 3 \
  --cases probabilistic_route probabilistic_sort streaming_pipeline streaming_pipeline_sort interleaved_pipeline streaming_pipeline_wide resident
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 3 \
  balanced_probabilistic_shuffle,balanced_probabilistic_sort,balanced_interleaved_shuffle,uniform32 128 BEFORE.wasm
```

Operation-key/lineage/catalog JSON, serializer/codec/input adapters, temporary-file
construction and native runtime allocations remain outside full accounting.
Independent profiling/preparation workspaces still need an aggregate policy;
this ledger is not a process/RSS cap. Target-SSD and other-platform validation
remain separate work.
