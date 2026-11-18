## Follow-up optimization pass (2026-10-11)

Implemented four changes against the workspace version described above:

- **Bounded browser source read-ahead:** one 256 KiB window per source file, shared by its descriptors and released when the last descriptor closes. Small reads reuse the window; seeks refill it as needed. Larger requests retain their existing bounded direct-read behavior. Physical reads, including prefetched bytes, remain visible in diagnostics.
- **Larger browser output batches:** the retained snapshot writer and execution copy buffer use 256 KiB instead of 64 KiB. The execution buffer is heap allocated to avoid pressure on the 1 MiB WASM stack. Native buffer sizes and merge-reader buffers are unchanged. Source read-ahead and these buffers add bounded memory outside the sorter; this is still not an RSS guarantee.
- **Less CSV serialization work:** unquoted fields are appended as strings instead of decoded and appended character by character. UTF-8 serialization transfers ownership of the completed byte buffer instead of copying it through the encoding API. Quoting, escaping, other encodings, strict byte caps, and seeded output semantics are preserved.
- **Reduced storage handle churn:** the browser's LRU cache holds at most 64 handles, up from eight. On an explicit `QuotaExceededError`, it evicts cached handles and retries; other failures still fail the job. New opt-in `handle_open` and `handle_eviction` counters measure these events per phase. Their `calls` values are counts; `bytes` and `seconds` are zero because storage operation timings already include handle acquisition. Opens include both new files and reopened files.

### Browser measurements

100,000 rows, 128-byte payload, 13,988,917-byte source, same Ryzen/WSL environment, Chromium 156 headless, warm caches, OPFS export. Three repetitions per case in each build, alternating native/browser order within each case. Before/after build suites were sequential, not interleaved, so the timing ratios are observational. Every run verified complete logical output parity with native output.

| Pipeline | Baseline | Read-ahead only | Final | Reduction vs baseline |
| --- | ---: | ---: | ---: | ---: |
| Rows only, 32 MiB | 2.183 s | 1.354 s | 0.697 s | 68% |
| Uniform shuffle, 32 MiB | 3.211 s | 2.394 s | 1.711 s | 47% |
| Buffer shuffle, 10,000 rows, 32 MiB | 3.122 s | 2.288 s | 1.490 s | 52% |

Final uniform/256 MiB and uniform → gzip/32 MiB medians were 0.823 s and 1.656 s, respectively; this pass did not collect matching old-build baselines for those cases. Plain analysis source reads fell from **1,709 to 54**, snapshot writes from **215 to 55**, and execution reads/writes from **215 each to 55 each**. The source-read regression reproduces 385 physical reads for a roughly 3 MiB sequential fixture before the change and 13 afterward, and checks seeks, boundaries, EOF, independent descriptor offsets, and cache release.

A separate million-row uniform/32 MiB diagnostic compared eight and 64 cached handles after read-ahead, serialization, and snapshot batching. Both had 43 initial runs, one merge, and 3,343 temporary reads. Handle opens fell **3,578 → 47**, evictions **3,569 → 0**, and analysis wall time **15.39 → 12.41 s**. Analysis read-call time fell **5.36 → 2.18 s**. Total time fell **21.35 → 15.45 s**, but that comparison also includes the later execution-copy batching improvement; it must not be attributed solely to the handle cache. These are single diagnostic runs, not repeated timing estimates.

Additional final-build native/browser comparisons passed for 100,000 rows with zero payload bytes and 10,000 rows with 8,192-byte payloads, for both rows-only and uniform/32 MiB pipelines. Those are shape/parity checks, not before/after speedup measurements. The cache unit test also simulates a two-handle quota, checks the 64-handle ceiling and merge reuse, propagates permission errors, and verifies cleanup.

Raw results: [baseline](../../evidence-originals.md#sha256-ab1fe92c53bea7fbec40650cddea0f4a3b8abd48e2a26d6c7513200f5f6baced "Original: docs/benchmarks/followup-baseline-2026-10-11.jsonl"), [read-ahead](../../evidence-originals.md#sha256-b9424549b8e3335266cc84db9e3bb5517cf18c67283134593b46c8dfbf2b50c6 "Original: docs/benchmarks/followup-readahead-2026-10-11.jsonl"), [snapshot batching and serializer](../../evidence-originals.md#sha256-e3cc593a9ee28ae3441409af1362d5c0aace46b8a3fe09a2b37e4cb084c4f56f "Original: docs/benchmarks/followup-snapshot-batches-2026-10-11.jsonl"), [final](../../evidence-originals.md#sha256-8a62bac45ef1d86ef2fe979e0ba7869d70db0d9ba3cc04ae03073a522d4239e9 "Original: docs/benchmarks/followup-final-2026-10-11.jsonl"), [eight-handle merge](../../evidence-originals.md#sha256-4277ef36268dabb8bd7180a21417b252a194314677babad14e83e752d9f96a73 "Original: docs/benchmarks/followup-merge-eight-handles-2026-10-11.jsonl"), [64-handle merge](../../evidence-originals.md#sha256-8c7d6f0e15ab096264748cb3da5ffb00597e1541597969c767b4d2599c325670 "Original: docs/benchmarks/followup-merge-64-handles-2026-10-11.jsonl"), [narrow](../../evidence-originals.md#sha256-dc04a924dde2292eb48a1318075c128cc61adb6a118cd6e872d58e08d0615471 "Original: docs/benchmarks/followup-narrow-2026-10-11.jsonl"), [wide](../../evidence-originals.md#sha256-5ea18005cb11e85c8b6fc926ed6003d9ad57c0db9e1d51daa5a8940676481893 "Original: docs/benchmarks/followup-wide-2026-10-11.jsonl"). A brief Clippy check overlapped the intermediate snapshot-batching suite; the baseline, read-ahead, final, and large-merge suites did not overlap compilation or other benchmarks.

The browser harness now accepts an optional sixth argument for payload bytes (default 128), bounds estimated fixture size to 160 MiB, and reports a server startup failure instead of waiting indefinitely. Example shape checks:

```sh
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 100000 1 rows,uniform32 0
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper 10000 1 rows,uniform32 8192
```

### Native measurements

The serializer change was compared with the executable saved at the start of this pass: 300,000 rows, 128-byte payload, three alternating repetitions per build/case. All 48 jobs matched output fingerprints, filenames, manifest row/byte/lineage metadata, logical digests, and stage statistics. Temporary peaks were unchanged. Full-job medians:

| Pipeline | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| rows | 0.4855 s | 0.4272 s | 12.0% |
| balanced | 0.5902 s | 0.5258 s | 10.9% |
| shuffle32 | 0.7851 s | 0.7212 s | 8.1% |
| shuffle256 | 0.9564 s | 0.9130 s | 4.5% |
| partition_shuffle | 1.2530 s | 1.1771 s | 6.1% |
| partition_assign_shuffle | 1.6204 s | 1.6083 s | 0.7% |
| gzip | 0.9840 s | 0.9261 s | 5.9% |
| zip | 0.9909 s | 0.9376 s | 5.4% |

[Native results](../../evidence-originals.md#sha256-9d481740130a8615b4047bc2a12e3929085539fe52cb109516d7b0caa0e3bcd4 "Original: docs/benchmarks/followup-native-2026-10-11.jsonl"). The smallest differences are within plausible run-to-run noise; these warm-cache observations do not establish a universal speedup.

### Remaining work and limits at the end of this pass

Buffer-shuffle fusion, parser reuse, digest batching and smaller merge heads were subsequently delivered in the passes above. The [current checklist](../../../TODO.md) supersedes this historical list.

- Parser, record allocation, and logical hashing still need a CPU/allocation profile. `perf` is not installed in this environment. This pass measured a targeted serializer improvement but did not obtain a full ingestion profile or rerun the billion-row test.
- Buffer shuffle still materializes an extra spool. Eliminating it requires preserving its seeded replacement sequence and downstream membership; it was not changed in this pass.
- Merge and intermediate row-file buffers remain 64 KiB. Increasing every reader would multiply memory use by merge fan-in; the measured improvements here use one source/snapshot/copy buffer and bounded handle reuse instead.
- The 64-handle ceiling and quota fallback were tested with injected storage handles; real Chromium exercised a 43-input merge. Behavior across other Chrome/Edge versions and arbitrary output devices remains unverified. Handle internals are browser-owned and not included in the engine working-memory accounting.
- Automatic memory/shuffle strategy selection remains unchanged. Warm-cache results vary with row shape, run count, and storage; they do not yet calibrate a reliable automatic policy. Billion-row shuffling, high-cardinality stress, cold storage, and storage saturation remain open.

The local server initially could not bind inside the sandbox; authorized local test runs resolved that. Chromium was present under `/tmp/chopper-playwright` with dependencies under `/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`, rather than Playwright's default cache. Setting `PLAYWRIGHT_BROWSERS_PATH` and `LD_LIBRARY_PATH` enabled all browser runs without installing anything.

Final verification for this pass: **43 native tests**, **13 browser contracts**, all four UI test files (including source read-ahead and storage-cache regressions), TypeScript checking, Rust formatting, Clippy with warnings denied, and native/WASI release builds passed. The browser benchmark artifacts contain 108 verified native/browser job runs across the baseline, intermediate, final, merge, and shape checks; the native before/after harness adds 48 verified jobs. Existing workspace edits were preserved.
