## Seeded policy removal and shuffle partition fusion (2026-11-15)

Decision: remove the seeded-output policy, its UI/CLI controls and alternate
flexible runner. Enable the existing tuple/random-key shuffle/partition fusion
in ordinary builds. Withhold the newly evaluated blanket partition-first and
resident Auto selectors because their complete-job costs regress controls.
The optional seed remains an RNG input; exact allocation, column membership,
pipeline semantics, caps, admission and publication/cleanup remain binding.
Prepared confirmation still executes its immutable encoded snapshot.

The [compact receipt](../../benchmarks/shuffle-policy-removal-summary-2026-11-15.json)
pins raw artifact hashes, sources/toolchains and every cell summary. Raw originals
and source patches remain local under the repository's existing raw-evidence
ignore rules; no remote upload or evidence publication was performed. The new
raw paths below are local evaluation inputs, not public archive retrieval claims.
The [native harness](../../../scripts/bench-shuffle-policy-removal.py) and
[shared native/browser harness](../../../scripts/benchmark-external-browser.mjs)
are retained. Historical experiment records are unchanged.

### Correctness and opportunity screening

Stable column partitioning discards the interleaving between distinct tuples.
Under ideal independent uniform permutations, the induced within-tuple orders
have the same joint distribution as independent uniform child permutations.
This makes adjacent full-shuffle/column-partition exchange legal statistically;
it does not make arbitrary exchanges with balanced/interleaved splits, allocation
or final caps legal. Those can change membership and require separate proofs.
The historical [partition-first proof and measurements](flexible-partition-first-shuffle-experiment-2026-10-18.md)
were consulted before implementing a bounded candidate.

The first candidate partitioned a retained parent and independently shuffled its
children, attempting resident Fisher–Yates before external fallback. On the
50,000-row, 192-byte-payload, 32-MiB/one-worker reverse-pipeline cells, its median
elapsed changes were 2.4% faster for balanced groups, 28.1% slower for skewed
groups and 32.2% slower for a single group. Its extra materialization and replay
costs block blanket promotion. Standalone resident Auto trials were 17.8% slower
for the fitting 12,000-row fixture and 33.8% slower for the external 50,000-row
fixture. Forward partition/shuffle controls also regressed. These diagnostic
comparisons selected the simpler fused sort; they are not additional samples of
the production comparison.

The promoted fusion sorts by partition tuple and the original parent random key,
then emits each tuple's shuffled subsequence. It avoids the intermediate globally
shuffled dataset while retaining original logical indices, lineage and both
stage summaries. It is compatible with current admission and collision handling;
explicit Fisher–Yates remains excluded from this physical sort. The surviving
feature name enables additional bounded audit instrumentation, not a second
output policy. No new universal cost threshold or extra profiling pass is added.

The alternate flexible runner and its allocation-range feature are removed with
the policy split. This does not promote that historical allocation rewrite or
reopen rejected bucket/XOF/storage strategies. Existing other optional fusions
retain their gates.

### Matched production measurements

Each native cell uses three measured repetitions after one warmup per variant,
alternating variant order, complete CLI start-to-exit including publication.
Fixture generation and independent CSV verification are outside the clock.
Inputs contain 250,000 IDs, a key and a 192-byte payload (about 50 MB), exceeding
the 32-MiB working budget. Caps are 10,000 rows and 4 MiB per CSV. Balanced keys
have 32 groups; skewed keys put 99% of rows in one group; the last control has
one group. Every job independently verifies unique IDs, exact fields, grouping,
conservation and row/byte limits. Seeds and requested pipelines are matched;
realized output equality is not assumed by the new policy.

| Shape | Baseline median (s) | Production median (s) | Elapsed reduction |
| --- | ---: | ---: | ---: |
| Balanced | 0.47545 | 0.35470 | 25.4% |
| Skewed | 0.45631 | 0.33918 | 25.7% |
| Single group | 0.45139 | 0.34719 | 23.1% |

The separate matched native/WASI cell uses 100,000 rows with 31 extra columns,
32 MiB and one worker, three alternating repetitions, and the same existing
uniform-shuffle/column-partition recipe. The browser uses a persistent disposable
Chromium profile. Its clock covers prepare, confirmation and destination export,
including per-job WASM restart; native covers complete CLI Run. Each runtime is
compared within itself. The browser timing is not a native timing sample.

| Runtime | Baseline median (s) | Production median (s) | Elapsed reduction |
| --- | ---: | ---: | ---: |
| Native Linux | 0.37644 | 0.23438 | 37.7% |
| WASI Chromium | 1.49125 | 0.88979 | 40.3% |

The shared harness independently verifies fields, IDs, group membership and
logical metadata, then also requires exact pinned byte/order/metadata parity
across the native and WASI variants. This stronger observed parity qualifies
this fused algorithm, not a restored user-facing seed guarantee. Measured ranges
and individual repetitions remain in the compact receipt/raw records. Working
reservations, logical temporary traffic, CPU, native peak RSS and physical I/O
counters are distinct; no physical-throughput or browser RSS claim is made.

### Controls, failures and limits

The first browser harness attempt failed before any eligible measurement: its
old assertion counted only header/path ownership. Current Analysis preview,
text, warning/timing, stage, column-summary, configuration, diagnostic and
directory-path owners remain admitted. The corrected assertion sums every
current retained owner and still requires exact workspace equality. It does not
weaken admission or treat workspace reservations as process RSS. The failed
context/log is retained and excluded from the final population.

This is a small warm Linux/WSL and bundled-Chromium evaluation. It establishes
neither native Windows/macOS/device performance, billion-row scale, tail latency,
universal skew selection nor other browsers. No historical percentage gains are
pooled with these measurements. The final source retains only the winning fusion;
failed trial selectors are absent.

### Local raw records

- [Production native comparison](../../evidence-originals.md#sha256-f732913761afdbec1e7b117e997e6faa826156da7cf239b6e22bc872f04594f2)
- [Matched production browser/native comparison](../../evidence-originals.md#sha256-b12041efac96ced22df6f5977f27b38bd0703bb3f257c413f989ce7845541c9f)
- [Rejected blanket partition-first candidate](../../evidence-originals.md#sha256-a425ee02735b7967c922bbad2954246067ee14acf614a2947114ed6e5736f0c6)
- [Intermediate fused/resident candidate](../../evidence-originals.md#sha256-df52794cdaa8d74d868081e58611cca37a2509a6530cb6d2fa8ee75242520e8d)
- [Forward controls](../../evidence-originals.md#sha256-1e8f571f86af1b72595d0d72ba43a4df6dcb6019493c19628fdcde8bfb1799a3)
- [Resident fitting control](../../evidence-originals.md#sha256-89f9381a68361c894bbaf4bb636d03fc35c7e92d8268283fc0c1818dc38432b3)
- [Resident external control](../../evidence-originals.md#sha256-c9101f76a175d705d2f1a4e1f18edd413dd3ead716e540ce5f463b9191c4d91c)
- [Excluded stale-harness attempt](../../evidence-originals.md#sha256-a74465d78914b12b2b8f7d9490ca5fc555d94380d18a3b28abdd387145e2d7f9), [failure log](../../evidence-originals.md#sha256-24ff835788fa98b94f9f90bb41cd46910819cef23c45f1efd4118979815b57d4)
