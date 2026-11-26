## Hosted Partition Shuffle direct output (2026-11-26)

[Issue #100](https://github.com/jsmatfess/chopper/issues/100) ·
[Engine publication contracts](../../direct-execution.md#shared-implementation-responsibilities) ·
[Run route prerequisites](../../execution-decisions.md#run-route-prerequisites)

### Current routes

The engine decides whether to retain the serialized CSV payload. Hosted export
separately decides where the publication writer's output files go. An engine
Run can retain a CSV snapshot and still write its eventual result files
straight to the browser destination. Read the
[route selection](../../../crates/chopper/src/engine/run_route.rs),
[direct plan selection](../../../crates/chopper/src/engine/direct.rs), and
[hosted engine worker](../../../ui/src/browser/engine-worker.ts) together.

| Engine route in the default build | Pipeline and format | Observation and runtime constraints |
| --- | --- | --- |
| Streaming private publication | No operations or calculated columns. Plain CSV, gzip and ZIP. | Native and WASI, including observed Run. |
| Retained processing with grouped private output | One Balanced operation, plain output. Input is retained to establish exact quotas. | Native and WASI, including observed Run. An eligible unobserved native counted plan takes precedence. |
| Counted or bounded native writer | Large Balanced or Partition → Balanced reads the plain source twice and verifies the counted source. Bounded Partition, Interleaved, probabilistic assignment and supported two-step membership chains can write while consuming the source. | Linux and Windows, unobserved, with operation-specific input, encoding, size, working headroom, file/leaf and descriptor bounds. The Linux UTF-16LE Interleaved and batched-sync cases have narrower guards. |
| Grouped private output from a selected retained native plan | Large calculated-only plain output on Linux. Linux can widen the terminal merge for explicit Uniform → Balanced. Large plain stratified exact allocation can use retained bounded writers and has a pre-emission fallback. | Unobserved. The allocation route also supports Windows. Size, memory, encoding and descriptor checks are in the owning selectors. |
| Encoded snapshot then publication | Remaining ordinary routes, including plain hosted Partition → Shuffle and composed gzip/ZIP jobs. Most terminal operations already emit into a common serializer, which writes an encoded data file and chunk catalog. | Native and WASI. Native publication can use multiple writers in eligible large cases. Internal Prepare always retains the exact serialized bytes for later execution. |

The [direct execution history](../../direct-execution.md) records opt-in
qualifications. The terminal-shuffle feature adds plain Uniform/Auto → Balanced
on native and WASI, including physical observation. It also adds native
unobserved standalone Shuffle and Uniform/Auto → Partition. Native terminal
routing and bounded fanout add selected singleton plain routes. Counted and
bounded fanout experiments may have different guards from default Auto. The
counted codec feature adds gzip and ZIP for the qualifying native counted
route. The hosted calculated Partition fusion writes an encoded snapshot even
when calculation feeds the grouping or sort pass directly.

Native output stays private on the destination filesystem until the commit
after source validation, file finalization and manifest creation. Its
destination witness and platform-specific no-replace commit protect against
destination races. The hosted worker maps private staging CSV/gzip files to
the selected folder, whether the engine got there through a snapshot or
during processing. ZIP stays staged in the worker filesystem because the
archive finalizer reopens the manifest and writes ZIP64 metadata before
export. The storage worker handles CSV/gzip destination writes. The engine
worker exports the staged ZIP. Both paths use the same publication helper
to close every result stream before writing and reading back the marker. The session
promotes a matching receipt and retires the worker before exposing a complete
Run. Owned incomplete output is subject to cleanup on failure or cancellation.

### Candidate priority and constraints

1. **Hosted plain Partition → Uniform.** The leading fused sort already
   knows the group boundary when the tuple changes, and the existing
   serializer knows each chunk boundary before writing the following row.
   Switching that serializer to the grouped private writer preserves the
   sort/traversal, normalized shuffled ordinals, child domains, tuple order,
   strict serialized caps and lineage. It needs one active final writer and
   a disk-backed manifest catalog. Its active writer, output names and held
   private destination overlap the last merge. Destination file creation can
   start before all logical stages have reported completion. It starts after
   the source scan and finishes before the browser marker.
2. **Hosted plain standalone Uniform and Uniform → Partition.** The engine
   already has terminal traversal seams for these shapes and feature-gated
   native use. Each could avoid a full encoded payload pass in each direction.
   Measure hosted destination block sizes, spill topology and late admission
   before generalizing. The [native standalone test](standalone-uniform-direct-publication-2026-11-25.md)
   found mixed elapsed results for direct publication alone despite removing a
   full snapshot. Widening that native merge separately created an admission
   denial under a fixed peer.
3. **Terminal plain operations over retained parent groups**, including
   terminal Partition and per-parent explicit Fisher–Yates. The general
   terminal operation path can use the shared grouped writer. It can overlap
   a parent dataset, read-ahead, resident shuffle state, or routed sort
   fallback with the writer. Many parents, wide late rows and known pressure
   counterexamples make this a separate eligibility and resource decision.
   [Prior native failure boundary](https://github.com/jsmatfess/chopper/issues/19)
4. **Composed compressed output.** The same serializer can retain its row and
   byte caps, but live codec grants and prepared compression concurrency change,
   and ZIP still requires archive finalization and later browser export.
   Quantify compression scheduling and publication separately before replacing
   the snapshot on these routes.

Direct emission advances output I/O relative to deferred publication. Once
emission starts, a storage failure or memory denial is terminal. The owner
must clean up the unpublished result, and the existing serializer remains
responsible for every file boundary. A fixed number of live writers bounds
writer overlap, while the browser's file metadata grows with the results
already created. Managed temporary accounting excludes selected destination
bytes. File retention, browser memory and joint storage use need separate
checks when evaluating a selector.

### Why the existing direct writer was slower

The first matched screen compared a snapshot with 64 KiB and 256 KiB
direct output. All arms used the same leading Partition/Uniform planner and
one worker. The 420,003-row fixture used eight repeating keys, 240-byte ASCII
payloads, a 4,000-row ceiling and a 512 KiB serialized limit. Its 128 MiB cell
produced six sort runs. The 32 MiB cell produced 22. Both ended with one merge.
The 32,771-row fixture with 48-byte payloads tested resident sorting and the
row cap. Each cell ran one warmup and three measured Runs per arm, rotating
the arm order for each triple.

| Working set | Snapshot median, s | Direct 64 KiB median, s | Direct 256 KiB median, s |
| --- | ---: | ---: | ---: |
| Resident, 128 MiB | 0.241 | 0.256 | 0.249 |
| External, 128 MiB | 3.974 | 4.979 | 3.858 |
| External, 32 MiB | 4.033 | 4.992 | 3.887 |

The 64 KiB writer generated 1,814 destination write calls per external Run
versus 414 for snapshot publication. Snapshot publication reads the prepared
data into an admitted 256 KiB copy buffer and can pass that entire span to the
destination sink. Writing newly serialized rows flushes at the direct
writer's own buffer boundary. Raising that buffer to 256 KiB cut the median
call count to 462 at 128 MiB and 463 at 32 MiB. It recovered the slowdown,
but at 128 MiB its median paired improvement was only 0.082 s
[0.075–0.189 s], below the declared 0.15 s gate. At 32 MiB it saved
0.170 s [0.115–0.284 s]. Both variants cut engine-managed temporary writes
by about 105.3 MB per external Run. A 512 KiB buffer tests one destination
write per capped file on that fixture.

### Matched fixed-budget result

The final screen added a 512 KiB direct buffer and retained the 256 KiB arm.
A control used 180,003 wider rows with 576-byte payloads and a 2 MiB cap. Both
screens used persistent disposable bundled Chromium 156.0.8078.4 on WSL2
with warm uncontrolled OPFS caching. Both selected input and destination
through the hosted browser API with test-provided OPFS handles. The timer
starts at the Run request and ends at verified export and worker retirement.
Fixture import, output verification and successful-result removal occur after
or before the timed interval. Each cell below contains three matched triples
after one separate warmup per arm.

| Workload | Snapshot median [min–max], s | Direct 512 KiB median [min–max], s | Paired seconds saved [min–max] | Destination write calls, median |
| --- | ---: | ---: | ---: | ---: |
| Resident, 128 MiB | 0.236 [0.236–0.236] | 0.226 [0.225–0.229] | 0.010 [0.007–0.011] | 17 → 17 |
| External, 128 MiB | 3.996 [3.976–4.011] | 3.612 [3.596–3.687] | 0.380 [0.309–0.399] | 414 → 214 |
| External, 32 MiB | 4.026 [4.011–4.038] | 3.696 [3.636–3.698] | 0.341 [0.316–0.390] | 414 → 214 |
| External, 128 MiB, 2 MiB cap | 3.015 [2.950–3.026] | 2.658 [2.651–2.682] | 0.333 [0.299–0.368] | 411 → 212 |

The 512 KiB arm cleared the timing gate and kept the same sort topology in
every fixed-budget triple. In the 128 MiB external cell it reduced managed
temporary reads from 254.8 MB to 149.4 MB, writes from 254.8 MB to 149.4 MB
and peak managed temporary use from 254.5 MB to 149.4 MB. The resident cell
managed 1.89 MB at peak with the snapshot and 2.9 kB with direct output.
The wider-cap cell saved 105.5 MB of managed reads and writes per Run.
Small differences between removed CSV bytes and counters come from
read-ahead and the different snapshot and publication catalogs.

The combined logical peak stayed around 255 MB in the 512 KiB-cap external
cells because the output grows while the merge retains its spill files.
It fell from 3.79 MB to 1.90 MB in the resident control. Both writers retained
one active writer slot in every measured Run. The reported peak workspace
reservations were equal in all fixed-budget cells, including 8.67 MB at the
32 MiB setting. A larger live CSV buffer can still require more memory at
the point where it opens. Managed temporary accounting, the browser's
combined logical file accounting, working reservations, RSS and device
I/O each have distinct scopes.

### Automatic memory must follow the producer

The existing hosted memory planner checks the snapshot route before
considering a higher sort tier. Selecting the direct writer alone therefore
changed the workload. With automatic memory and the same 420,003-row input,
the snapshot resolved 1,024 MiB and sorted in memory. The route-only direct
build resolved 256 MiB and made three initial spill runs. That build took a
median 3.618 s versus 3.408 s for the snapshot and wrote 149.4 MB of temporary
data versus 105.3 MB for the snapshot.

A separate build applied the existing hosted memory planner to both retained
publication choices. It resolved the same 1,024 MiB and remained resident in
all four attempts, including the warmup. The three measured pairs saved a
median 0.317 s [0.287–0.341 s]. Its median Run took 3.091 s, against 3.408 s
for the same-budget snapshot. Its temporary writes fell from 105,343,967
bytes to 38,248 bytes, for the manifest catalog. Combined logical peak fell
from 210.7 MB to 105.4 MB. The tracked workspace peak increased by 255,798
bytes, to 177,715,605 bytes. Preserving the Auto planner is a prerequisite for
evaluating this route with automatic memory. The 256 MiB counterexample serves
as an eligibility control and is excluded from the same-budget timing result.

### Contract evidence

The independent verifier checked every ID and field, eight exact partition
memberships, canonical group and output numbering, manifest lineage, file
inventory, byte and row caps, and absence of incomplete workspaces. All groups
contained departures from encounter order. Each Run drew its own shuffle, so
ordered CSV hashes identify individual results. The construction preserves
the existing composite key, collision refinement and group traversal, which
carry the shuffle guarantee. The observed progress recorded both configured
operations, the final serialization and the completed export and marker.
The snapshot showed a separate materialization span. Direct publication
retired after serialization and export without such a span.

All 21 fault controls retired with an empty destination and zero workspace
bytes after cleanup. The snapshot and both buffered arms rejected a malformed
late record, a row too long for its serialized cap, and an exceeded file
limit. The malformed row failed before opening destination files. The
destination-write error and cancellation were exercised after one CSV had
closed. Marker write failure and invalid marker readback were exercised
after all 16 CSVs and the manifest had closed. None of these faults acquired
a confirmed publication receipt.

With 190 MiB of managed temporary space at the 32 MiB working setting, the
snapshot reported temporary-space budget exhaustion before destination
creation. Both buffered direct arms completed the same 420,003-row job,
verified every output and retired their workspaces. Each used 149,442,694
bytes of peak managed temporary storage. This is a job-budget completion
case. The backing filesystem still needs capacity for the simultaneous
spill and destination files.

### Decision

Retain the 512 KiB candidate with Auto sizing parity for guarded follow-up.
The 64 KiB version costs about a second on the spilling fixture, and the
route-only Auto change can add spills. Larger blocks clear the fixed-budget
gate on this browser and preserve the completion contracts exercised here.
A future selector needs a late-admission control through first output and
evidence from a real desktop destination, where write round trips and the
storage device can behave differently. High fanout, large late rows,
contention and alternate browser/platform behavior remain separate
qualification questions. The native route inventory is based on source and
existing evidence.

### Reproduction and provenance

Build [baseline fc85297](https://github.com/jsmatfess/chopper/commit/fc85297a41d24eb558daecf8ead9b40a816328e1)
with the feature-free WASI release command, `node scripts/build-browser.mjs`.
Retain each `ui/dist/engine.wasm` before rebuilding. Apply the
[route patch](../../benchmarks/hosted-partition-shuffle-direct-route-2026-11-26.patch)
in a scratch checkout for the 64 KiB arm. For the larger buffers apply one
of [256 KiB](../../benchmarks/hosted-partition-shuffle-direct-buffer-256-2026-11-26.patch)
or [512 KiB](../../benchmarks/hosted-partition-shuffle-direct-buffer-512-2026-11-26.patch)
on top of the route patch. Add the [Auto sizing patch](../../benchmarks/hosted-partition-shuffle-direct-auto-sizing-2026-11-26.patch)
to the 512 KiB source for the fourth build. The recorded builds used Rust
1.99.1, Node 22.23.4, the workspace lockfiles and the production browser
workers. WASM and compiled asset hashes, the exact browser executable hash,
fixture hashes, stage observations, post-publication counters and timed and
warmup samples are in the raw records.

The [primary harness](../../benchmarks/hosted-partition-shuffle-direct-harness-2026-11-26.mjs)
bundles the existing hosted driver and runs the page, engine worker and
storage worker in a fresh profile. From the repository root, install the
locked UI dependencies with `npm --prefix ui ci` and pass the bundled
Chromium headless-shell executable explicitly.

```sh
node docs/benchmarks/hosted-partition-shuffle-direct-harness-2026-11-26.mjs \
  BASELINE.wasm DIRECT_256.wasm DIRECT_512.wasm scratch/fixed-rerun measure CHROME_HEADLESS_SHELL
```

For each other batch, copy the primary harness to `scratch/REPLAY/harness.mjs`
and apply the corresponding harness diff with `patch -d scratch/REPLAY -p1`.
Keep the same repository-root invocation and a fresh output directory.

| Replay | Harness diff | Build argument order and mode | Raw results |
| --- | --- | --- | --- |
| First screen | [64 KiB screen](../../benchmarks/hosted-partition-shuffle-direct-harness-64-screen-2026-11-26.patch) | snapshot, 64 KiB, 256 KiB, `measure` | [Samples](../../benchmarks/hosted-partition-shuffle-direct-64-screen-2026-11-26.jsonl) |
| Fixed budgets | Primary | snapshot, 256 KiB, 512 KiB, `measure` | [Samples](../../benchmarks/hosted-partition-shuffle-direct-buffers-2026-11-26.jsonl) |
| Automatic memory | [Auto](../../benchmarks/hosted-partition-shuffle-direct-harness-auto-2026-11-26.patch) | snapshot, 512 KiB, 512 KiB with Auto parity, `measure` | [Samples](../../benchmarks/hosted-partition-shuffle-direct-auto-2026-11-26.jsonl) |
| Publication and budget controls | [Controls](../../benchmarks/hosted-partition-shuffle-direct-harness-controls-2026-11-26.patch) | snapshot, 256 KiB, 512 KiB, `faults` or `quota` | [Faults](../../benchmarks/hosted-partition-shuffle-direct-faults-2026-11-26.jsonl) · [Budget](../../benchmarks/hosted-partition-shuffle-direct-quota-2026-11-26.jsonl) |

The local runner retains the smoke attempts, initial two-arm pilot and
failed verifier or harness receipts. The first screen's dependent verifier
initially assumed identical catalog bytes and ordered variant names
lexically. The corrected receipt rechecked the unchanged raw Runs by
explicit variant name and allowed the measured catalog overhead. An
initial fault harness also polled asynchronous status before retirement.
Its successor used the worker's retired-storage acknowledgment. The
two-arm pilot overlapped a later compile and is excluded from the timing
tables. The three reviewed cohorts ran sequentially without concurrent
compilation. The fault and quota controls provide contract evidence
independently of their elapsed times.
