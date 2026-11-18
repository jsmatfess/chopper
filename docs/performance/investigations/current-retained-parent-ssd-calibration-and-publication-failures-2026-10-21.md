## Current retained-parent SSD calibration and publication failures (2026-10-21)

This pass tests whether the retained-parent shuffle/partition experiment still
benefits complete Windows jobs after directory-path and inspection accounting.
The [fresh build record](../../evidence-originals.md#sha256-634bdbe2a3af479cc4e67f9d232444af1fb35d3b745149f4be5d5d4b9340e5ff "Original: docs/benchmarks/retained-current-calibration-builds-2026-10-21.json")
pins the dirty compilation inventory, toolchain, commands and separate release
artifacts: baseline `51bd081104fd13dc82210d83b3c15c83e03ce8192cfc8bc9793bde0d4c48e189`,
candidate `a6f9f7eeebe384b311b05e21142528444b5bf9c9cd6034b0201a9d4fcd266c9d`.
Only the candidate enables `experimental-shuffle-partition`. Both builds finish
before any further UI source edits. The measurement environment records the
Windows/NTFS/NVMe mapping, fixture hashes, harness hashes, seed, 32 MiB job budget,
four workers and warm/uncontrolled cache. It measures complete CLI startup,
preparation, execution and publication, excluding generation and verification.
Stop on any failure, parity or cleanup mismatch; three alternating pairs per cell
are the planned sample, with no default promotion.

The [first raw pass](../../evidence-originals.md#sha256-987f578d1b6d03aaa794403b6194a6b03ede7c7f1cc69a5b27b5bf3d89b4a996 "Original: docs/benchmarks/retained-current-calibration-2026-10-21.jsonl")
completes three cells, with three repetitions per variant. Its
[derived summary](../../evidence-originals.md#sha256-2a099109d0cac9237481875cfee5534a97da194726d906750d150839336a7377 "Original: docs/benchmarks/retained-current-calibration-2026-10-21-summary.json")
retains the source hash and physical measurement lines. Median baseline/candidate
seconds and min–max ranges are: resident 0.078 (0.075–0.255) / 0.063
(0.062–0.224); 300,000-row external 1.654 (1.588–1.701) / 1.281 (1.226–1.314);
1,400,000-row hierarchical 8.350 (8.041–9.532) / 6.375 (6.200–6.608).
Candidate median reductions, using baseline median as denominator, are 19.1%,
22.6% and 23.7%. The resident ranges are noisy and overlap. Both hierarchical
plans perform two merge operations; candidate run count grows from 77 to 86.
Candidate peak tracked reservations fall from 8.61 to 7.93 MB and median process
peak working set from 18.49 to 18.01 MB in that cell; these are distinct metrics,
not an RSS cap. The summary retains CPU, logical traffic and temporary-space
metrics separately. A brief test-bundle build occurred during the hierarchical
cell, and background/cache conditions were uncontrolled; these are local
calibration observations, not isolated device-throughput estimates.

The [separate 17,000-row control](../../evidence-originals.md#sha256-77ebd8c670e2dd9542f2ea0b330a61ae1725588749a5839211957823aaf738a6 "Original: docs/benchmarks/retained-current-calibration-transition-2026-10-21.jsonl")
also completes three pairs. Its
[summary](../../evidence-originals.md#sha256-d390e2fd8b8922b351bce4ff4c4c5e2e6ae57f445610bae232060cbac8d5e77e "Original: docs/benchmarks/retained-current-calibration-transition-2026-10-21-summary.json")
reports baseline 0.135 (0.132–0.167) seconds and candidate 0.136 (0.131–0.172):
candidate median is 1.0% higher, with overlapping ranges. Baseline stays resident;
candidate creates two runs and one merge. This preserves the near-flat spill
transition counterexample and supplies no universal row-count threshold.

The original pass stops at a skew baseline publication denial (Windows error 5).
An [unchanged-build retry](../../evidence-originals.md#sha256-0d4bc90215b4dbcf68ea90f89f3776ac7c14a0f7b4ed67a7e599eef3fae908ee "Original: docs/benchmarks/retained-current-calibration-shapes-2026-10-21.jsonl")
fails at the same boundary. A
[final-size-only diagnostic attempt](../../evidence-originals.md#sha256-56e768d84b0d557b8762b24e889a7fca8a368630fa45c8fc7910c234c974adda "Original: docs/benchmarks/retained-current-calibration-no-sampler-2026-10-21.jsonl")
publishes successfully but exposes locale-dependent verification: the shared
Python verifier reads UTF-8 manifest filenames and CSV fields as Windows CP1252.
The verifier now reads/writes UTF-8 explicitly. Two regression cases first fail
on the Windows locale, then pass; the full focused harness suite passes 14 tests.
The retained-parent skew cell now actually partitions the 90/9/1 payload key,
rather than a balanced `c0` key. Historical artifacts are unchanged; this corrected
cell is not interchangeable with the earlier balanced-key workload.

After that correction, the
[UTF-8 shape pass](../../evidence-originals.md#sha256-0ffeda347e06c4d77ea4dee0bc98b6b823e057b47efd39ccc1b94573f4a26b07 "Original: docs/benchmarks/retained-current-calibration-shapes-utf8-2026-10-21.jsonl")
verifies five skew jobs before the final candidate publication fails. A
[rare-wide attempt](../../evidence-originals.md#sha256-2284e08829168fc81cfc45ca8ab0a02134c3fb1a3ccb375437bc30d0bc9a81c2 "Original: docs/benchmarks/retained-current-calibration-wide-transition-2026-10-21.jsonl")
verifies one baseline before candidate publication fails. These partial cells
are excluded from completed-cell effects; failed and unmatched observations
remain raw evidence. No silent retry or success-only replacement is used.

The [publication diagnostic](../../evidence-originals.md#sha256-d522f6e475638b66f50c13f48fac096e4e34f093a94c1bae3c1a7aee45dca462 "Original: docs/benchmarks/retained-current-publication-diagnostic-2026-10-21.json")
retains the minimization scripts/results. Removing the live sampler does not
eliminate the error. Smaller direct jobs succeed; repeated layout controls fail
once with sampling, while a rename stress control does not fail. A controlled
open child handle without delete sharing reproduces error 5 and release permits
rename, but the holder in the benchmark failures remains unidentified. No native
publication behavior is changed. The harness's new `--space-sample-ms 0` diagnostic
mode observes final output size only after exit; its scope explicitly disclaims
a live storage peak. Engine temporary peak and logical traffic remain separate.
The successful transition pass uses that mode and cannot supply a simultaneous
temp/staging/output peak. Physical I/O is unmeasured throughout.

Decision: retain opt-in status and the current capacity ceilings. Current-build
external/hierarchical gains support further evaluation, while the transition,
partial shape cells and publication failures prevent selector calibration or
broader acceptance. Resolve the Windows publication contention before completing
these shape cells; other runtimes, controlled physical effects and selectors
remain open in [TODO](../../../TODO.md).

Reproduction uses [benchmark-windows.py](../../../scripts/benchmark-windows.py) with
`--retained-parent --repeats 3`, fresh `--baseline`/`--candidate`, `--work-dir`
on the tested volume, a new `--output` path and recorded `--hardware` JSON.
The transition adds `--transition-rows 17000 --space-sample-ms 0`.
Reused artifacts additionally require `--build-evidence` pointing to the original
environment record; its hashes must match the binaries. Source and fixture
identities, raw line locations and per-run settings are retained in the artifacts.
