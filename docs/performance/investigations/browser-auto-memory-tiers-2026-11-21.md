## Browser Auto memory tiers (2026-11-21)

Hosted Run selects a larger memory tier for eligible plain-output uniform
shuffle and Partition → Uniform Shuffle with automatic grouping. This
implements the next step after the
[resource calibration](browser-auto-resource-calibration-2026-11-21.md).
The rule targets seconds saved by making an expensive sort resident. It
preserves explicit memory settings, the original Job, and actual admission.

[Raw runs and build identities](../../benchmarks/browser-auto-memory-tiers-2026-11-21.jsonl)

### Held-out execution

Two matched rounds per shape compare numeric 256 MiB, Auto Run, and explicit
Analyze followed by Auto Run, for 54 verified jobs. The last two arms use the
same new WASM and production workers as the control. The Chromium destination
is same-origin OPFS on WSL. Each run verifies the CSV fields, conservation,
partitions and ordering where applicable, strict 4 MiB serialized caps,
manifest agreement, completion marker, and cleanup. Timing covers worker
startup, processing, destination writing and marker verification, and
retirement. The after-Analyze Run clock starts after the scan, so it answers
how fast the remaining work is once observations are available. Analyze + Run
also includes the scan and lets us evaluate the cost of initiating it.
File selection and
independent verification are outside the clock.

| Shape | Fixed 256 MiB seconds | Auto MiB / Run seconds | After Analyze MiB / Run seconds | Analyze + Run total seconds |
| --- | ---: | ---: | ---: | ---: |
| Large shuffle | 13.41 | 2048 / 6.38 | 2048 / 6.27 | 7.49 |
| Wider rows | 3.80 | 512 / 1.91 | 512 / 1.88 | 2.21 |
| Many narrow rows | 5.17 | 512 / 2.35 | 1024 / 2.33 | 2.79 |
| Gzip input | 3.62 | 256 / 3.63 | 512 / 1.68 | 1.85 |
| Late wide rows | 3.92 | 512 / 1.91 | 512 / 1.92 | 2.26 |
| 42 columns | 6.54 | 512 / 6.61 | 1024 / 2.84 | 3.49 |
| Skewed Partition → Shuffle | 6.72 | 1024 / 3.23 | 1024 / 3.21 | 3.79 |
| Streaming | 1.67 | 256 / 1.66 | 256 / 1.66 | 2.07 |
| Partition → Shuffle → Shuffle | 0.89 | 256 / 0.90 | 256 / 0.88 | 1.05 |

The large shuffle and composed sort gained several seconds with file-size
planning alone. Analyze refined the choice for gzip and the 42-column job, both
of which improved enough to cover the extra scan on these fixtures. Analyze also
raised the budget on the many-narrow-row fixture, where 512 MiB already fit.
That is a conservative overestimate. Both budgets had similar Run time and
resident working allocation. The scan itself accounts for the higher combined
time. Streaming and the unsupported
three-step shape retained the baseline tier. A user who already ran Analyze can
reuse its observations without another profiling scan.

### Selection and safety

Eligible Run uses a rough sort-footprint estimate of 1.5 times source bytes for
plain UTF-8 CSV at or above 48 MiB. Matching Analyze data replaces this with
decoded field bytes plus a per-row allowance of 200 bytes and eight bytes per
column. The fused partition sort adds one-eighth for keys. These are empirical
heuristics. The planner selects the smallest supported budget whose nominal
quarter-budget sort target fits and uses the baseline beyond the tested tier
range. Compressed inputs use the baseline until Analyze supplies decoded facts.
A higher target needs shared free capacity of at least half the nominal tier.
Static pressure tests cover fallback and zero reservation during resolution.
The engine validates the current input and keeps the normal spill path.

The completed Run report shows the selected and actual amounts, the estimate,
whether Analyze changed the target, and a capacity fallback when applicable.
The samples establish behavior in the recorded runtime. User-selected disk
folders, broad CSV distributions, and competing tabs need separate throughput
and browser-process memory measurements.

### Replay

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
node scripts/benchmark-browser-auto-resources.mjs policy
```
