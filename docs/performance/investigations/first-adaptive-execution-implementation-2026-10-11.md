## First adaptive execution implementation (2026-10-11)

The engine now uses three physical paths through the existing sorting/grouping interface:

- **Resident processing:** short fields share an encoded payload allocation while sort keys remain directly comparable. Rows with more than 256 payload bytes per field retain owned strings, avoiding the extra pack/unpack copy. This is an initial conservative representation heuristic, not a calibrated universal optimum.
- **Bounded stable routing:** on the first buffer overflow, plain key grouping inspects its buffered rows. If distinct keys fit within 64 routes and one eighth of the working budget, and each key's ordinals are nondecreasing, rows go to buffered group files. Files are consumed in encoded-key order. This applies to eligible partitioning, allocation, and stratum grouping; random-key sorting retains canonical shuffle semantics.
- **External sorting:** high cardinality or reordered input uses the existing multiway sorter. If new keys exhaust routing capacity, or ordinals later decrease, retained group files are replayed once into sorting. The original source is not reread. Small groups that never overflow remain resident.

`resources.grouping` defaults to `"auto"`; `"sort"` disables routing. The CLI exposes `split --grouping auto|sort`, and the UI exposes the same choice under Resource budget. Both policies use the shape-dependent row representation and preserve logical output. This override selects physical grouping, not shuffle quality or forced spilling.

A shared reservation ledger covers buffered sort rows (including vector capacity allowance), routing buffers/key metadata, and merge readers/heads. Its ceiling is half of the configured job budget, leaving room for parser/decoder storage, output buffers, codecs, conversions and runtime overhead. Those other allocations are **not** tracked by this ledger; the peak reservation metric is not RSS or a whole-process guarantee. Reservations remain live while an iterator retains its data and release on error/cancellation/drop. The ledger is per job, not a server-wide memory coordinator.

Analysis `diagnostics` adds `grouping_policy`, `resident_sorts`, `routed_groupings`, `routing_fallbacks`, `workspace_reserved_bytes`, and `peak_workspace_reserved_bytes`. The UI presents these alongside spill and merge counters under Execution strategies. These are aggregate physical-path counts, not a predictive per-stage execution plan. Empty sorts can contribute to resident counts; routed counts include only groupings that finish through routing.

### Shape benchmark

```sh
python3 scripts/benchmark-adaptive.py \
  --before /path/to/saved/chopper \
  --after .tools/linux/target/release/chopper --repeats 3
```

The harness generates independent fixtures covering narrow rows, 32 extra short columns, 4 KiB payloads, low/high cardinality, skew, late new keys, allocation and stratification. All shapes include occasional Unicode, quoting and multiline fields. It alternates before/after build order, verifies complete logical output fingerprints plus filenames/stage statistics/manifest entry metadata, and removes its own fixtures/spills/outputs. `--work-dir` selects their filesystem. Raw observations include binary hashes and the host platform.

Local WSL/Linux, warm caches, one worker, plain output, three repetitions per build/case. Full-job medians exclude generation and fingerprinting. All **66 jobs** passed parity checks. No compilation or browser tests overlapped this final benchmark. Durations are small; especially small differences need larger-scale confirmation.

| Case | Rows | Budget | Before | After | Before / after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Streaming narrow rows | 100,000 | 32 MiB | 0.0355 s | 0.0344 s | 1.03× |
| Resident shuffle | 10,000 | 256 MiB | 0.0180 s | 0.0169 s | 1.06× |
| Shuffle, many columns | 60,000 | 32 MiB | 0.3299 s | 0.2557 s | 1.29× |
| Shuffle, wide payloads | 10,000 | 32 MiB | 0.2785 s | 0.2862 s | 0.97× |
| Partition, three keys | 120,000 | 32 MiB | 0.1748 s | 0.1454 s | 1.20× |
| Partition, heavily skewed | 120,000 | 32 MiB | 0.1620 s | 0.1428 s | 1.13× |
| Partition, 128 keys | 120,000 | 32 MiB | 0.5760 s | 0.5697 s | 1.01× |
| Partition, late new keys | 120,000 | 32 MiB | 0.5278 s | 0.5745 s | 0.92× |
| Exact allocation | 120,000 | 32 MiB | 0.2025 s | 0.1785 s | 1.13× |
| Partition → allocation | 120,000 | 32 MiB | 0.2864 s | 0.2353 s | 1.22× |
| Stratified allocation | 120,000 | 32 MiB | 0.2911 s | 0.2709 s | 1.07× |

The late-key regression is the cost of discovering that routing is unsuitable after retaining data. `grouping: "sort"` is available when that shape is known in advance. The wide-row case remains slightly slower despite avoiding packing copies; do not describe this pass as a universal improvement. These measurements do not calibrate host-memory auto-sizing, cold/slow storage, billion-row behavior, or browser performance.

[Final native observations](../../evidence-originals.md#sha256-2895f53e3d31b2c0a274710dc25982300a4548891549a7fc03ba1b87651ddbe0 "Original: docs/benchmarks/adaptive-native-2026-10-11.jsonl"). Validation: **47 native tests**, **14 browser contracts**, all four UI test files, TypeScript checking, Rust formatting, Clippy with warnings denied, and native/WASI release builds. New tests exercise concurrent reservations, late cardinality/order changes, cancellation/temp exhaustion, full native pipeline parity, and browser automatic/forced-sort parity. Existing v1 fixture and random-key collision tests pass unchanged. Broader host discovery, complete allocation accounting, sampled previews and an up-front physical plan remain roadmap work.
