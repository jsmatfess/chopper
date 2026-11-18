## Scale and cross-engine benchmarks (2026-10-11)

### Billion-row validation

`python3 scripts/benchmark-scale.py --binary .tools/linux/target/release/chopper`

A one-column CSV containing a header and **1,000,000,000 `x` records** occupied 2,000,000,002 bytes. Plain output, no operations or row cap, 32 MiB working budget, one worker, 1 MiB maximum record. The complete output SHA-256 matched the input. Fixture generation and streaming verification were excluded from engine timing.

| Measurement | Result |
| --- | ---: |
| Total engine wall time | 158.19 s |
| Analysis, including fused serialization | 153.85 s |
| Execution / publication, including process overhead | 4.34 s |
| Throughput | 6.32 million rows/s |
| User / system CPU time | 136.22 / 7.18 s |
| Peak RSS reported by GNU time | 4,284 KiB |
| Peak engine temporary storage | 2,000,000,119 bytes |
| Source + snapshot + output upper estimate | approximately 6 GB |
| Generation + engine + verification | 163.04 s |

The run stayed within the authorized 20 GiB / 30-minute limits and cleaned its fixture, temporary files, and output. This is a row-count stress test with exceptionally narrow, repeated records. It does **not** validate billion-row shuffles, wide records, high cardinality, or cold storage. WSL/GNU time reported zero filesystem input/output counters; those counters do not establish that no I/O occurred. A brief WASI build overlapped the beginning of this run, so its timing is observational rather than an isolated comparison.

Most time was in the ingestion loop, which also hashes logical records and encodes the final snapshot. Output copying was under 3% of wall time. The next useful native investigation is allocation/parser/hash/encoder profiling on narrow and wide rows; another plain-output parallelization pass is unlikely to help this narrow-row case much. Phase timings alone cannot distinguish parser cost from hashing or serialization.

### Comparable native/browser jobs

```sh
bash scripts/build-browser.sh
npm --prefix ui run build:hosted
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 1000000 3
```

The harness alternates native/browser order, runs rows-only, uniform shuffling at 32 and 256 MiB, buffer shuffling, and gzip cases, and verifies every output's logical bytes (decompressing gzip before hashing). The fixture is identical across engines. It reports every repetition, engine-internal analysis phases, analysis wall time, execution/export wall time, and optional browser storage-call diagnostics. Initial defaults startup, fixture creation, and hashing are excluded; per-job WASM restart and cleanup are included in browser wall time.

Browser results use an OPFS test destination because automation cannot reproduce a user's directory-picker grant. Native results use the local filesystem. Treat this as engine-plus-storage-bridge performance, **not** a promise about File System Access export to an arbitrary device. Browser hashing loads each bounded output chunk, so the harness limits fixture size to one million rows. Benchmark pages and fixtures are removed on completion and by production builds.

### Instrumentation and optimization questions

Analysis now includes `timings` for ingestion plus fused operations, remaining operations, and final serialization. A near-zero final serialization time means it was already fused into an earlier phase. `diagnostics` records cumulative temporary bytes written, initial spilled sort runs, merge operations, and the number of input runs consumed by merges. These counters cover analysis, not later compression/export; a merge operation includes the final streaming merge and is not synonymous with a full dataset pass.

Opt-in browser diagnostics aggregate call counts, bytes, and elapsed seconds for source reads and storage bridge operations separately for analysis, execution, and export. Call time includes worker scheduling and storage waits. It is not pure disk-service time. Normal app use leaves this timing instrumentation disabled.

Questions to answer with those measurements:

- Does browser time track source-read count, bridge wait time, or engine CPU? Larger I/O batches may help the first two, but won't fix WASM parser or comparator cost.
- Does the storage worker's eight-handle cache churn during a merge with up to 64 input runs? Measure reopen/eviction counts before increasing the cache; browser handle limits also matter.
- Do smaller sort buffers win through cache locality despite more runs? Compare run counts, cumulative writes, and wall time instead of assuming more memory is faster.
- Is approximate buffer shuffling actually faster? It currently loses the uniform shuffle's ingestion fusion and can write an additional spool. Approximation alone is not evidence of a speedup.

### Resource simulations

```sh
python3 scripts/simulate-resources.py --allow-approximate
# Override machine assumptions and input shape explicitly:
python3 scripts/simulate-resources.py --rows 1000000 --row-bytes 140 \
  --memory-mb 32 128 256 512 --disk-mib-s 50 500 --cpu-rows-s 250000 1000000 \
  --allow-approximate
```

This sensitivity model varies decompressed row count/width, memory, disk throughput, and CPU throughput. It estimates spill runs, merge passes, temporary space, uniform/buffer runtime, and buffer size. For each machine/input combination, it recommends the smallest tested memory budget within 10% of its modeled best runtime. Approximate mixing is eligible only with `--allow-approximate`, and only when modeled at least 20% faster.

These are explicit hypotheses, not calibrated predictions or guaranteed memory bounds. Mean row width omits worst-case records; compressed source size is not decompressed size. Compression, browser RPC latency, skew, and exact operation fusion are not fully modeled. Use benchmark measurements to replace throughput assumptions and test the recommendation before enabling it in the engine. The existing `auto` behavior remains uniform pending that calibration; the user's permission to choose approximate mixing removes a product constraint but does not establish when it is beneficial.

### Native/browser measured results

One million rows with 128-byte generated payloads (140,888,917 source bytes), Ryzen AI 9 HX 370, WSL/ext4, one engine worker, warm OS caches, Chromium headless. Three alternating repetitions per case. All **30 runs** passed complete logical output fingerprint comparisons, including gzip decompression. Medians below include analysis and execution/export, with the destination caveat above. No concurrent compilation or other benchmark ran during this comparison.

| Pipeline | Memory | Native median | Browser median | Browser/native |
| --- | ---: | ---: | ---: | ---: |
| Row limits only | 32 MiB | 1.97 s | 27.97 s | 14.2× |
| Uniform shuffle | 32 MiB | 2.92 s | 39.65 s | 13.6× |
| Uniform shuffle | 256 MiB | 3.46 s | 34.77 s | 10.0× |
| Buffer shuffle, 10,000 rows | 32 MiB | 2.23 s | 34.24 s | 15.4× |
| Uniform shuffle → gzip | 32 MiB | 4.30 s | 36.54 s | 8.5× |

The 256 MiB budget helped the browser shuffle by about 12% but hurt native time by about 19%. Buffer mixing reduced time by about 24% natively and 14% in the browser relative to uniform/32 MiB. Browser gzip was faster overall than plain uniform output despite doing compression: fewer output bytes can offset codec work on this export path. Treat these as prioritization evidence, not universal tuning rules.

Raw observations are retained in [engine repetitions](../../evidence-originals.md#sha256-4cb991c6533ad3d627244ad114d4c724f1deccdd3d46fdbad8d0d07d58fd7a7d "Original: docs/benchmarks/engines-2026-10-11.jsonl"), [billion-row run](../../evidence-originals.md#sha256-26081041b3e180972d3341ab0ea7c83fc18b07ba5004327296254d4c68871971 "Original: docs/benchmarks/scale-2026-10-11.jsonl"), and [small simulation example](../../evidence-originals.md#sha256-c3daf486f870678c6508d5b8c1f39a395a1330ae71d0a323bd86234d0ce51234 "Original: docs/benchmarks/model-example-2026-10-11.jsonl"). The simulator did not predict every observed tradeoff, which is why live `auto` tuning has not been changed.

### Browser diagnostic pass

A separate 100,000-row run (13,988,917-byte source) with profiling enabled passed all six native/browser output comparisons. It is a diagnostic sample, not a three-repetition timing comparison. [Raw counters](../../evidence-originals.md#sha256-db1a3e0a2d59e4dcc31f9aa628d8500a24b179ebf785bafaa60fad0673af2faa "Original: docs/benchmarks/profile-2026-10-11.jsonl") include machine and browser metadata.

| Browser analysis | Plain rows | Uniform shuffle, 32 MiB |
| --- | ---: | ---: |
| Wall time | 1.675 s | 2.635 s |
| Source reads | 1,709 calls / 0.965 s | 1,709 calls / 0.931 s |
| Temporary writes | 215 calls / 0.408 s | 546 calls / 0.980 s |
| Temporary reads | none | 331 calls / 0.258 s |
| Initial sort runs / merge operations | 0 / 0 | 5 / 1 |
| Cumulative temporary bytes written | 13,989,028 | 35,577,918 |

Source reads averaged about 8 KiB and accounted for roughly 58% of plain analysis wall time. Source reads plus temporary writes accounted for roughly 82%. This makes **bounded source read-ahead and larger storage batches** the first browser optimization experiment. Profile both narrow and wide records and verify seeks, partial reads, memory overhead, and output parity before adopting it. This sample used only five sort runs, so it does not establish whether the eight-handle storage cache churns on larger merges.

For the same shuffled records, gzip reduced execution bridge writes from 215 calls / 13.99 MB to 72 calls / 3.00 MB. Browser execution/export fell from 0.747 s to 0.565 s despite codec work, consistent with the million-row comparison. Compression can therefore be an I/O tradeoff, not simply extra CPU expense.

Final verification: 41 native tests, 13 browser contracts, TypeScript checking and UI unit tests, Clippy with warnings denied, and native/WASI release builds passed. An actual UI smoke run also verified sniffing, hidden fields, file-picker filters, expandable selected values, and cancellation.
