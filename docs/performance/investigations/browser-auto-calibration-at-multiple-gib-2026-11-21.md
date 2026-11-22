## Browser Auto calibration at multiple GiB (2026-11-21)

This panel tests whether Analyze before Run or a higher working-memory budget
reduces elapsed time on multi-GiB browser jobs. A separate production check
replays the two preview and Analyze decisions identified by the
[larger-file calibration](browser-preview-calibration-on-larger-files-2026-11-21.md).
The gzip follow-up tests a four-byte trailer read using the existing preview.

### Evidence

[Multi-GiB initial comparisons](../../benchmarks/browser-auto-multigib-2026-11-21-screen.jsonl) ·
[Multi-GiB reversed controls](../../benchmarks/browser-auto-multigib-2026-11-21-repeat.jsonl)

[Production preview and Analyze controls](../../benchmarks/browser-auto-multigib-2026-11-21-production.jsonl) ·
[Gzip trailer controls](../../benchmarks/browser-auto-multigib-2026-11-21-gzip.jsonl)

The first scale screen ran bundled Chromium 156 on WSL/Linux on a Ryzen 7
5800X, with sources from a disk-backed browser `File` and same-origin OPFS
destinations in fresh persistent profiles. Each synthetic source has
1024-byte rows and three columns. The skewed partition has 93.75% of rows in
one key. Run used capped 8 MiB output files. The clock includes planning,
any Analyze, execution, destination publication, completion-marker
verification and workspace cleanup. Input selection, the already available
preview, and the independent verification of every result row are outside
that clock. The verifier checks field contents, conservation, partition
membership, streaming order, strict serialized caps and results inventory.
Preview reads eight input rows without preparing output.

The release-scale 16 GiB startup quota gate rejected both ephemeral and
persistent attempts because Chromium exposed a 10 GiB quota. These
[ephemeral](../../benchmarks/browser-auto-multigib-2026-11-21-quota-ephemeral.jsonl)
and [persistent](../../benchmarks/browser-auto-multigib-2026-11-21-quota-persistent.jsonl)
attempts record the rejection. The separate research harness admits one job
at a time with 8 GiB available at entry and cancels if a live quota sample
falls below a 2 GiB free-space floor. Individual jobs own their OPFS folders
and delete them after checking completion. The research screen ran alongside
some low-priority development checks and medium-sized controls on the same
host. The reversed comparisons also run one scale arm at a time and sample
browser-process CPU and RSS. Peak RSS sums the observed browser processes at
one sample and can include shared pages. RSS, working reservations, logical
workspace traffic, storage RPC traffic and physical disk I/O have separate
scopes.

### Production sizing checks

All arms below requested automatic memory. Both source
selections take the same eight-row preview; the file-size-only control
reselects the file before Run, clearing its preview ownership. Values are
two-run medians with the observed range. The current planner validates source
identity and parser settings before accepting observations, and preserves
resource admission for all allocations.

| Shuffle fixture | File size only | Preview Run | Analyze + Run | Resource decision |
| --- | ---: | ---: | ---: | --- |
| 163.85 MiB, 42 columns | 15.64 s [15.36, 15.91] | 6.79 s [6.62, 6.97] | 8.20 s [7.88, 8.52] | Preview raises 1024 to 2048 MiB and removes two spill runs. |
| 156.95 MiB, narrow tail | 15.85 s [15.79, 15.91] | 16.04 s [15.80, 16.29] | 8.47 s [8.40, 8.54] | An existing Analyze estimates about 524.5 MiB, which fits the 528 MiB calibrated estimate allowance for the 2048 MiB tier. |

The 42-column preview saves 8.84 seconds at the median. The narrow-tail
Run after Analyze takes about 7.18 seconds, excluding the scan that a user
may already have completed. Its first eight rows are wide and hide changes
later in the file. The near-ceiling allowance applies only to the Analyze
estimate. Above it, the starting target remains in force. Neither rule
changes the actual sort allocation limits.

### Scale results

| Job | File-size Auto | Analyze + Auto | Analyze scan | Fixed 2048 MiB |
| --- | ---: | ---: | ---: | ---: |
| 4.01 GiB streaming | 109.54 s | 139.42 s | 28.96 s | — |
| 2.00 GiB standalone uniform shuffle | 59.36 s | 73.29 s | 15.13 s | 61.48 s |
| 2.00 GiB skewed Partition → Uniform Shuffle | 59.45 s | 73.89 s | 15.03 s | 59.99 s |

Each cell is one verified job from the first screen. The streaming arm
published 513 capped files and used about 207 KiB of peak working
reservations in both arms. Managed temporary writes were 75,924 bytes in
each run.

The standalone shuffle made 36 runs at 256 MiB and 5 at 2048 MiB. The skewed
pipeline made 38 and 5. Both budgets needed one merge on both inputs. Logical
temporary traffic was 2.14 GiB read and 4.14 GiB written for the standalone
shuffle, and 2.21 GiB read and 4.21 GiB written for the skewed pipeline. Both
budgets moved the same bytes within each comparison. Peak working
reservations rose from about 64 MiB to 512 MiB.

The reversed-order runs matched the scale shape and used the same WASM
and worker hashes. CPU and sampled RSS refer to the observed Chromium
processes. The first screen did not capture those two metrics.

| Reversed comparison | Budget | Complete Run | Sampled CPU | Sampled peak RSS |
| --- | ---: | ---: | ---: | ---: |
| Standalone shuffle | 256 MiB | 64.07 s | 87.95 CPU-s | 681 MiB |
| Standalone shuffle | 2048 MiB | 68.20 s | 91.44 CPU-s | 1,129 MiB |
| Skewed Partition → Shuffle | 256 MiB | 59.66 s | 81.67 CPU-s | 686 MiB |
| Skewed Partition → Shuffle | 2048 MiB | 59.50 s | 81.34 CPU-s | 1,128 MiB |

All 12 multi-GiB jobs verified. The standalone shuffle took longer at
2048 MiB in both comparisons. A change of less than a second in either
direction on the skewed pipeline leaves no practical speed difference
at this scale.

The file and Analyze footprint estimates exceed every calibrated resident
target on both shuffles. Raising memory arbitrarily by file size would spend
more memory on these jobs without removing the merge. Keep the baseline tier
on these shapes and leave Analyze user-initiated.

### Gzip trailer follow-up

[Initial gzip screen](../../benchmarks/browser-auto-multigib-2026-11-21-gzip-screen.jsonl) ·
[Production gzip controls](../../benchmarks/browser-auto-multigib-2026-11-21-gzip-production.jsonl)

These are synthetic Chromium/OPFS jobs with two rounds of each variant. The
initial screen read the trailer during setup. The main gzip controls count the
four-byte read and sizing calculation inside the Run clock. Reported timing
below is the median of the main controls. Some medium jobs overlap the scale
screen or local validation work, which adds absolute elapsed variation.

| Source and pipeline | File size only | Preview + trailer | Analyze + Run | Result |
| --- | ---: | ---: | ---: | --- |
| 157.10 MiB decoded, stable single-member gzip, Shuffle | 10.20 s | 4.83 s | 5.16 s | 1024 MiB, resident |
| Held-out single-member gzip, skewed Partition → Shuffle | 7.35 s | 3.47 s | 3.74 s | 1024 MiB, resident |
| Small single-member gzip, matching wide preview | 0.20 s | 0.20 s | 0.25 s | Stays at 256 MiB |
| Concatenated gzip, short final member | 10.05 s | 9.95 s | 5.02 s | Stays at 256 MiB, Analyze still helps |
| Concatenated gzip, large final member | 11.86 s | 4.86 s | 5.34 s | 1024 MiB, resident |

A gzip trailer describes the final member modulo 4 GiB and can underestimate
total decoded size. The negative control with a short final member has the same
decoded CSV as the simple positive case. A different narrow-tail fixture with a
wide preview also frustrates the estimate. Its trailer arms raise the tier
and still spill. Analyze has complete width and row counts and can choose
the resident tier. These cases support a one-way starting-budget hint, with
independent Run validation and actual admission. They provide insufficient
discrimination for automatically starting a full Analyze scan. [RFC 1952](https://www.rfc-editor.org/rfc/rfc1952#section-2.3.1)

The production replay checks that the engine selects the same tiers with a
matching preview, leaves the short-final-member case at the baseline, and
preserves real memory admission. Chromium acceptance also exercises an invalid
checksum with an otherwise plausible trailer and checks destination cleanup.

### Competing jobs

[Paired runs](../../benchmarks/browser-auto-multigib-2026-11-21-paired.jsonl) ·
[Initial harness assertion failure](../../benchmarks/browser-auto-multigib-2026-11-21-paired-assertion.jsonl)

Two pages in one Chromium context released identical 163.85 MiB 42-column jobs
from a shared barrier. Each had its own engine and output folder. With the
size-only policy, both pairs completed in 15.73–16.17 seconds. With preview
sizing, both pairs completed in 6.60–6.66 seconds. All eight jobs published and
passed the output verifier. The clock is the time from the first start to the
last completion. The data covers two simultaneous jobs on this host and
separate WASI ledgers. The first harness attempt wrongly expected a missing
preview tier on the paired fixture. The corrected assertion checks that the
reported preview tier matches the requested arm.

### Replay

Build the default hosted WASI engine and distribution before replaying. Supply
the asset directory from a given build to compare like for like. The artifacts
pin the WASM, workers, harness, driver and fixture hashes. Initial screens
used an earlier build without preview-driven Auto. The production and gzip
checks include the integrated policy and retain the size-only control by
reselecting the source after its preview.

```sh
mkdir -p scratch/scale-screen scratch/scale-repeat
node scripts/benchmark-auto-multigib.mjs screen ui/dist scratch/scale-screen
node scripts/benchmark-auto-multigib.mjs repeat ui/dist scratch/scale-repeat
node scripts/benchmark-browser-auto-resources.mjs preview-production
node scripts/benchmark-browser-auto-resources.mjs preview-gzip-trailer
node scripts/benchmark-browser-auto-resources.mjs preview-gzip-production
node scripts/benchmark-browser-auto-resources.mjs preview-pair
```

The prototype gzip panel uses a numeric override to validate the resource
choice. The production tests use Auto throughout. These results apply to
bundled Chromium with the documented OPFS setup. User-selected destination
volumes, native Windows, other engines, and a broadly applicable automatic
Analyze trigger need separate evidence.
