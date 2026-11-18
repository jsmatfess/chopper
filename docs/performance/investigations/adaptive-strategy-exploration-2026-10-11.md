## Adaptive strategy exploration (2026-10-11)

A bounded native experiment used the first 1,000,000 data records from the scratch fixture: 12,888,917 source bytes, four columns (`id,country,segment,payload`), seven countries, empty payloads. The full scratch file is 15,888,888,917 bytes, unlike the older two-billion-byte, one-column scale fixture below. Neither these prefix measurements nor that earlier scale test establishes the cause of the user's cancelled full-file job.

Three repetitions per case, reversing case order on the second repetition; one worker, fixed seed `strategy-exploration`, no compression or output caps, 1 MiB maximum record. These measure **native analysis only**, including retained output preparation, on local WSL storage with warm caches. GNU time supplied peak RSS; the existing release executable's SHA-256 is recorded in the raw data. No candidate implementation was introduced. The partition/assignment cases used `country` followed by 80% treatment / 20% control with no strata. They intentionally fix one worker rather than reproduce the uploaded job's automatic-worker setting.

| Pipeline | Budget (MiB) | Median analysis | Max RSS (MiB) | Initial sort runs | Cumulative temp writes (MB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Streaming, no operations | 32 | 0.315 s | 4.4 | 0 | 14.9 |
| Streaming, no operations | 256 | 0.323 s | 4.4 | 0 | 14.9 |
| Streaming, no operations | 1024 | 0.318 s | 4.3 | 0 | 14.9 |
| Uniform shuffle | 32 | 1.045 s | 16.0 | 28 | 103.8 |
| Uniform shuffle | 256 | 1.483 s | 97.8 | 4 | 103.8 |
| Uniform shuffle | 1024 | 1.362 s | 294.0 | 0 | 14.9 |
| Partition → assign | 32 | 1.543 s | 18.6 | 55 | 245.6 |
| Partition → assign | 256 | 1.722 s | 98.3 | 4 | 164.7 |
| Partition → assign | 1024 | 1.634 s | 294.2 | 0 | 87.8 |

All runs completed with the expected row count and identical logical **input** digests. Execution/output parity was not tested here; these observations are not correctness certification for a new strategy. The preliminary streaming/shuffle suite was repeated to regenerate its raw artifact; the table uses that retained repeat suite. Partition/assignment was a separate suite, not interleaved with the other pipelines.

The resident shuffle eliminated spill writes but did not beat the smallest external-sort case on this input and storage. Streaming used approximately constant memory regardless of configured budget. This supports separating feasibility from speed when designing the planner; it does not establish that smaller budgets win for other shapes or at larger scale. CPU/allocation profiling and cold-storage measurements are needed to explain the timing differences.

Reproduction protocol: generate one million zero-payload rows with the existing `chopper` `generate` example (arguments: input path, `1000000`, `0`), then run `chopper analyze --config JOB` for each operation list and memory budget above. Use seed `strategy-exploration`, `workers: 1`, `max_record_bytes: 1048576`, and a temporary directory on the fixture filesystem. Collect `analysis_seconds`, `diagnostics`, and `peak_temp_bytes` from stdout; wrap each command with `/usr/bin/time -f '%M'` for peak RSS in KiB. Exclude fixture generation from timing, repeat three times, reverse case order on the middle repetition, and remove only harness-owned temporary data. This narrow experiment is a starting point; the proposal specifies the broader shape/system matrix needed before automatic defaults change.

Raw observations: [streaming/shuffle](../../evidence-originals.md#sha256-b818ea9370d6c7c4bd6140b74b317bc7a53b761d30273e5ec43e02bbc94310e9 "Original: docs/benchmarks/strategy-prefix-2026-10-11.jsonl"), [partition/assignment](../../evidence-originals.md#sha256-541dc9600c8bf070662f6c157f55bb4da64f7cced9a27c3138af8084fb235808 "Original: docs/benchmarks/strategy-partition-2026-10-11.jsonl").
