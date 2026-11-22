## Browser Auto resource calibration (2026-11-21)

The selection objective is **absolute seconds saved per complete Run**.
Resource changes that save milliseconds on short jobs have lower priority than
changes that save seconds on expensive jobs. This panel measures nominal
working-memory budgets and the production grouping choice in the hosted engine.

[Primary jobs and provenance](../../benchmarks/browser-auto-resource-calibration-2026-11-21-primary.jsonl)

[Held-out shape and compression checks](../../benchmarks/browser-auto-resource-calibration-2026-11-21-holdout.jsonl)

[Composed pipelines and key skew](../../benchmarks/browser-auto-resource-calibration-2026-11-21-pipeline.jsonl)

[Replay harness](../../../scripts/benchmark-browser-auto-resources.mjs)

### Complete jobs and resource use

| Job | Smallest tested resident budget | Median Auto seconds | Median candidate seconds | Seconds saved |
| --- | ---: | ---: | ---: | ---: |
| 190.6 MiB standalone shuffle | 2048 MiB | 13.61 | 6.56 | 7.05 |
| 95.3 MiB even Partition → Shuffle | 1024 MiB | 7.41 | 3.58 | 3.83 |
| 95.3 MiB skewed Partition → Shuffle | 1024 MiB | 7.46 | 3.65 | 3.81 |
| 95.3 MiB standalone shuffle | 1024 MiB | 6.88 | 3.34 | 3.55 |
| 55.5 MiB narrower-row shuffle | 1024 MiB | 5.06 | 2.35 | 2.71 |
| 0.44 MiB gzip shuffle | 512 MiB | 3.60 | 1.69 | 1.91 |
| 58.1 MiB wider-row shuffle | 512 MiB | 3.76 | 1.88 | 1.87 |

| Job | Request | Verified Runs | Median seconds [min, max] | Spill runs / merges | Peak working reservations MiB | Peak OPFS workspace MiB | OPFS reads + writes MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Streaming control | Auto | 3/3 | 0.685 [0.682, 0.692] | 0/0 | 0.19 | 0.00 | 0.00 |
| Streaming control | 512 MiB | 3/3 | 0.692 [0.672, 0.694] | 0/0 | 0.19 | 0.00 | 0.00 |
| Streaming control | 1024 MiB | 3/3 | 0.682 [0.673, 0.705] | 0/0 | 0.19 | 0.00 | 0.00 |
| Streaming control | 2048 MiB | 3/3 | 0.683 [0.681, 0.693] | 0/0 | 0.19 | 0.00 | 0.00 |
| Shuffle, medium | Auto | 3/3 | 6.883 [6.851, 6.997] | 3/1 | 64.26 | 216.77 | 433.69 |
| Shuffle, medium | 512 MiB | 3/3 | 6.985 [6.903, 7.018] | 2/1 | 128.26 | 216.77 | 433.69 |
| Shuffle, medium | 1024 MiB | 3/3 | 3.336 [3.267, 3.379] | 0/0 | 142.67 | 95.26 | 190.53 |
| Shuffle, medium | 2048 MiB | 3/3 | 3.328 [3.286, 3.336] | 0/0 | 142.67 | 95.26 | 190.53 |
| Shuffle, large | Auto | 3/3 | 13.609 [13.553, 13.721] | 5/1 | 64.26 | 433.74 | 867.81 |
| Shuffle, large | 512 MiB | 3/3 | 13.809 [13.748, 13.907] | 3/1 | 128.26 | 433.74 | 867.81 |
| Shuffle, large | 1024 MiB | 3/3 | 13.841 [13.788, 13.938] | 2/1 | 256.26 | 433.74 | 867.81 |
| Shuffle, large | 2048 MiB | 3/3 | 6.563 [6.455, 6.587] | 0/0 | 285.10 | 190.64 | 381.27 |
| Partition, 8 keys | Auto | 3/3 | 6.538 [6.537, 6.558] | 0/0 | 64.71 | 128.37 | 423.78 |
| Partition, 8 keys | Sort | 3/3 | 6.687 [6.659, 6.699] | 3/1 | 64.26 | 205.07 | 423.78 |
| Partition, 256 keys | Auto | 3/3 | 7.713 [7.693, 7.722] | 3/1 | 64.32 | 213.30 | 427.44 |
| Partition, 256 keys | Sort | 3/3 | 7.672 [7.634, 7.689] | 3/1 | 64.32 | 213.30 | 427.44 |
| Shuffle, wider rows | Auto | 3/3 | 3.756 [3.752, 3.844] | 2/1 | 64.26 | 122.58 | 245.44 |
| Shuffle, wider rows | 512 MiB | 3/3 | 1.882 [1.867, 1.893] | 0/0 | 70.19 | 58.07 | 116.14 |
| Shuffle, wider rows | 1024 MiB | 3/3 | 1.850 [1.847, 1.851] | 0/0 | 70.19 | 58.07 | 116.14 |
| Shuffle, narrower rows | Auto | 3/3 | 5.057 [5.045, 5.094] | 3/1 | 52.00 | 147.17 | 294.36 |
| Shuffle, narrower rows | 512 MiB | 3/3 | 5.141 [5.118, 5.180] | 2/1 | 103.65 | 147.17 | 294.36 |
| Shuffle, narrower rows | 1024 MiB | 3/3 | 2.346 [2.312, 2.365] | 0/0 | 175.59 | 55.50 | 110.99 |
| Shuffle, gzip input | Auto | 3/3 | 3.598 [3.578, 3.620] | 2/1 | 64.84 | 122.58 | 245.44 |
| Shuffle, gzip input | 512 MiB | 3/3 | 1.689 [1.683, 1.694] | 0/0 | 70.77 | 58.07 | 116.14 |
| Shuffle, gzip input | 1024 MiB | 3/3 | 1.687 [1.685, 1.709] | 0/0 | 70.77 | 58.07 | 116.14 |
| Partition → Shuffle, even | Auto | 3/3 | 7.407 [7.372, 7.417] | 3/1 | 64.26 | 230.12 | 460.40 |
| Partition → Shuffle, even | 1024 MiB | 3/3 | 3.576 [3.532, 3.603] | 0/0 | 162.14 | 95.27 | 190.53 |
| Partition → Shuffle, skewed | Auto | 3/3 | 7.460 [7.448, 7.493] | 3/1 | 64.26 | 230.12 | 460.40 |
| Partition → Shuffle, skewed | 1024 MiB | 3/3 | 3.650 [3.604, 3.651] | 0/0 | 162.14 | 95.27 | 190.53 |

The Auto jobs resolved to 256 MiB. Browser jobs used one processing worker,
uncompressed output, the default record allowance, and a strict 4 MiB CSV cap.
The primary file sizes were 23.7, 95.3, and 190.6 MiB for streaming and shuffling, and 95.3 or 95.9 MiB for partitioning. The held-out cases change
row count, row width, and compression. A third panel compares an even and a
skewed Partition → Uniform Shuffle with the same input size and eight keys. All arms use the same WASM and production
storage and destination workers. The driver rotates request order over three
rounds and uses a fresh Chromium context for each job on the same WSL machine.
The destination is same-origin OPFS. Run timing includes setting up the
workers, the engine, saving the result files, verifying the completion marker,
and cleaning the engine workspace. File selection, independent validation, and
deleting the fixture's result are outside the clock.

Every verified result preserved its exact input fields and membership, matched
manifest counts and serialized byte caps, and had a valid completion marker.
Ordered streaming and partition paths also preserved record order. Uniform
shuffle uses the same algorithm at every budget. The verifier checks row
conservation and fields, and independent randomized runs may produce different
orders. The memory column contains tracked engine reservations. The OPFS
columns contain logical workspace bytes and traffic through the storage bridge.
Browser process RSS, CPU, and physical disk I/O need separate measurement.

### Rules supported by the measurements

- **Evaluate larger budgets when they are likely to avoid a merge.** The
  nominal retained-sort targets at 256, 512, 1024, and 2048 MiB are 64, 128,
  256, and 512 MiB before shared capacity constraints. Reducing the number of
  spill runs while keeping the merge gave little benefit in the primary
  shuffles. The smallest observed resident tier kept the absolute savings and
  avoids requesting more capacity than the job needs.
- **Use a footprint estimate per physical stage.** Applicable Analyze data
  supplies decoded row counts and field bytes. Account for row and field
  descriptors and buffer growth as well as decoded payload. For a pipeline
  with independent groups, estimate the largest live partition or parent
  working set. For a fused sort across all rows, estimate the whole stage.
  Preserve real admission and the existing external fallback.
  The 58.1 MiB wider-row CSV needed 512 MiB, while the 55.5 MiB CSV
  with many narrow rows needed 1024 MiB. The gzip version of the wider-row
  input also needed 512 MiB even though its on-disk size was 0.44 MiB.
  Both even and skewed Partition → Shuffle cases used a combined tuple and
  random-key sort across all rows and benefited from the same higher tier.
  See the [physical rewrite](../../pipeline-rewrites.md).
- **Keep the current resource policy for fast streaming and unsupported
  shapes.** The streaming control gave no practical absolute time savings
  from raising its budget. Unknown footprints can use the current plan and
  its normal spill behavior. Reuse an applicable Analyze result when present.
  This panel supplies no evidence to add a full Analyze pass automatically.
- **Keep adaptive grouping in the tested browser cases.** Automatic routing
  avoided sort runs for eight keys. At 256 keys both requests sorted and had
  similar elapsed time. The WASI engine uses one processing worker and final
  publication is serial, so this build has no browser worker or final-writer
  concurrency setting to sweep. The [native resource screen](auto-chromium-thresholds-and-resource-calibration-2026-11-21.md)
  already compared 1, 2, and 4 workers. [Browser destination buffering](browser-direct-destination-writes-and-batching-2026-11-21.md)
  is a separate experiment. User-supplied output, record and storage limits
  remain independent of throughput tuning.

These measurements identify useful budget tiers under the tested conditions.
A pre-run estimator and its confidence bounds still need calibration on varied
column counts, skewed or late-wide rows, composed pipelines, competing browser
jobs, and user-selected disk destinations. A budget policy must respect the
existing strategy gates, including the calibrated hosted fusion that currently
accepts only certain budgets. The current browser Auto defaults remain in force.

### Replay and setup

From a built hosted checkout with the bundled Chromium:

```sh
node scripts/benchmark-browser-auto-resources.mjs primary
node scripts/benchmark-browser-auto-resources.mjs holdout
node scripts/benchmark-browser-auto-resources.mjs pipeline
```

The raw environment records pin the WASM, production workers, driver and
harness hashes. The primary used the plain-input version of the harness. The
held-out version adds filename handling for gzip and runs the same primary
recipe. The exact earlier harness revisions and rejected setup receipts are retained in
`scratch/browser-auto-resources-20261121`. An initial attempt used a historical
driver assertion that enumerates retained owners from an older accounting
schema. That assertion rejected completed jobs, so the attempt was stopped
and excluded. The measured harness replaces that legacy check in its own
bundle and retains the actual reservation diagnostics, publication verification
and workspace cleanup checks.
