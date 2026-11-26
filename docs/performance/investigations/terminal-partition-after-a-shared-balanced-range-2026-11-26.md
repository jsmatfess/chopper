## Terminal Partition after a shared Balanced range (2026-11-26)

[Issue #102](https://github.com/jsmatfess/chopper/issues/102) ·
[Run samples](../../benchmarks/terminal-partition-shared-balanced-2026-11-26.jsonl) ·
[Measured patch](../../benchmarks/terminal-partition-shared-balanced-2026-11-26.patch)

A shared intermediate Balanced split needs offsets only to the start of its
final child. The final child's frame validation can wait for its consumer when
the sole remaining operation is a terminal Partition with resolvable selectors,
the job has no formulas, and the build uses ordinary Partition. Partition
decodes each parent's complete retained range before emitting its groups.
Both stages and final CSV limits retain their original indices and behavior.

### Measured result

The matched 600,003-row fixture has eight repeating keys and 144 payload bytes
per row. Both arms ran with Auto grouping, 256 MiB, one worker, plain CSV, and a
4 MiB serialized cap in persistent bundled Chromium on WSL2. The timer covers
Run through successful marker and workspace retirement. Three alternating
pairs follow one excluded warmup per arm and cell. Independent verification
checked exact ordered CSV hashes, canonical lineage, membership, byte metadata
and caps for every export.

| Workload | Baseline median [min–max], s | Candidate median [min–max], s | Paired seconds saved [min–max] | Temporary read bytes, before → after | Frames scanned, before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Balanced(2), Partition | 3.954 [3.939–3.980] | 3.853 [3.849–3.921] | 0.105 [0.018–0.126] | 374,076,670 → 311,984,215 | 600,003 → 300,002 |
| Balanced(1), Partition | 3.899 [3.892–3.904] | 3.692 [3.674–3.712] | 0.200 [0.193–0.225] | 374,068,750 → 249,979,239 | 600,003 → 0 |

Read counters count actual temporary-file reads and can include buffered
read-ahead. Frame visits are separate. Neither establishes device I/O.

### Correctness and provenance

The focused regression injects truncated, oversized and malformed UTF-8 final
frames. The boundary records the exact final offset and Partition rejects
the damaged frame before emitting that range. Earlier frames still require
a successful checked scan. An already cancelled Balanced(1) fails through
the normal cancellation check. Invalid Partition selectors retain the original
full scan and its validation order. For unexpected private-spool damage in a
deferred frame, the read error can surface during Partition.

Build the baseline for these pairs from
`ab8e1519afd15d6c22d42ee2b2ec4a5e4deca393` plus the measured
[allocation lookup patch](../../benchmarks/probabilistic-allocation-cumulative-2026-11-26.patch).
Apply this investigation's patch for the candidate. Both used feature-free
`node scripts/build-browser.mjs` with Rust 1.99.1 and identical hosted worker
assets. The sample file records the engine hashes, fixtures, browser, harness
and verifier identities. The Run driver derives from
[`benchmark-swarm.ts`](../../../ui/tests/benchmark-swarm.ts) with an
OPFS-backed input and the final worker observation captured.
