## Hosted release comparison 0.6.5 to 0.6.6 (2026-11-27)

The release comparison checks the startup cost of automatic CSV settings
detection and measures two ordinary CSV Run controls. Both use bundled
Chromium 156.0.8078.4 on WSL2. The baseline uses the published v0.6.5 packages.
The candidate asset hashes in the capture identify the same bytes as the
v0.6.6 release package. See the [release charts](../../releases/0.6.6.md#performance-compared-with-v065)
and [sample data](../../benchmarks/0.6.6-performance-data.json).

The Browse timing starts at the input button click and stops when the preview
renders its eight data rows. Browser and engine initialization precede the
timer. Each trial uses a fresh page and context with a synthetic File handle.
The fixtures contain 64 and 12,000 rows of comma CSV. The harness checks
the header and all eight preview rows. Each fixture has eight alternating
pairs after an excluded warmup per arm. The v0.6.6 median preview times are
4.4 and 4.5 ms longer, respectively. This measures the interactive selection
path with a supplied file handle.

The two Run controls reuse the small Shuffle then Partition and below-floor
Balanced then Balanced fixtures from the previous release. Their timer runs
from the Run request through export and worker retirement. A separate
persistent Chromium profile owns each workload on WSL2 ext4. File loading
and the independent output copy and verifier run outside the timer. Each
case uses one worker, a fixed job memory budget and three alternating pairs
after a warmup per arm. The independent verifier checks output fields,
membership, quotas, caps and completion markers. Deterministic Balanced
output has the same ordered CSV digest across releases.

The Run effects vary across pairs. Both cases retain the same median logical
temporary reads, logical temporary writes, peak tracked temporary storage
and peak working reservations. These counters describe the recorded logical
work and admission, with cache and storage conditions scoped to the local
replay. The sample size supports a bounded release control.

For replay, use the locked UI dependencies and extract the exact hosted ZIPs.
Pass their directories and a fresh JSONL path to the
[Browse comparison harness](../../benchmarks/hosted-csv-selection-065-to-066.mjs).
For Run, use the [existing paired harness](../../benchmarks/hosted-release-comparison-064-to-065.mjs)
with the two recorded recipes and the
[independent verifier](../../benchmarks/hosted-release-comparison-064-to-065.py).
