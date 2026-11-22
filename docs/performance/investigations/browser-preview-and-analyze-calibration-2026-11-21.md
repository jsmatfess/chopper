## Browser preview and Analyze calibration (2026-11-21)

### Decision

The existing preview is a useful input to Auto memory sizing on eligible plain
shuffles. In two 42-column cases it selected the same tier as full Analyze and
saved over three seconds per job compared with file-size Auto. Its best
initial use is to improve Run directly. The tested cue misses a valuable
opportunity and sends false cues. Retain user control over starting a full scan.

[Matched whole-job runs](../../benchmarks/browser-preview-analyze-calibration-2026-11-21-preview.jsonl)

[Matched gzip control](../../benchmarks/browser-preview-analyze-calibration-2026-11-21-codec-control.jsonl)

[Replay harness](../../../scripts/benchmark-browser-auto-resources.mjs) ·
[Candidate rules](../../../scripts/browser-preview-calibration.mjs)

### Complete-job results

The three arms are delivered file-size Auto Run, preview-informed Run with the
candidate's simulated tier, and a fresh Analyze followed by Auto Run. Two matched
rounds covered ten shapes, with 60 verified jobs on the same production WASM
and workers in disposable WSL Chromium contexts. All arms used the real bounded
input preview before starting the timed action. Run elapsed time includes
startup, CSV processing, publication and workspace retirement. Analyze + Run
additionally includes the full scan. Preview latency is retained separately.
Prior user-initiated analysis remains a sunk cost.

A hit means the rule cued Analyze and the fresh Analyze + Run arm saved at least
0.5 seconds in **each** round relative to the indicated Run arm. This is a
practical comparison for this panel. No cue was shown to actual users. Times
are medians with the observed range, in seconds.

| Fixture | Source MiB | Budgets in MiB, size / preview / Analyze | Size-only Auto | Preview Run | Analyze + Run | Size cue | Preview cue |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 42 columns | 73.05 | 512 / 1024 / 1024 | 6.34 [6.30, 6.39] | 2.74 [2.71, 2.78] | 3.37 [3.35, 3.38] | Hit | Quiet |
| 42 columns, Partition → Shuffle | 72.04 | 512 / 1024 / 1024 | 6.62 [6.56, 6.69] | 2.83 [2.80, 2.86] | 3.41 [3.40, 3.42] | Hit | Quiet |
| Stable wide rows | 60.36 | 512 / 512 / 512 | 1.94 [1.94, 1.94] | 1.92 [1.90, 1.93] | 2.27 [2.27, 2.27] | Quiet | Quiet |
| Same head, narrow tail | 60.41 | 512 / 512 / 1024 | 5.79 [5.76, 5.83] | 5.78 [5.78, 5.79] | 3.09 [3.09, 3.09] | Miss | Miss |
| Late wide rows | 60.88 | 512 / 512 / 512 | 1.92 [1.91, 1.93] | 1.91 [1.91, 1.92] | 2.25 [2.25, 2.25] | Quiet | Quiet |
| Preview omits wide rows | 57.94 | 512 / 512 / 512 | 1.87 [1.83, 1.91] | 1.88 [1.86, 1.89] | 2.16 [2.15, 2.18] | Quiet | Quiet |
| Gzip, large expansion | 0.44 | 256 / 256 / 512 | 3.74 [3.72, 3.76] | 3.74 [3.74, 3.74] | 1.95 [1.89, 2.01] | Hit | Hit |
| Gzip, small decoded file | 0.48 | 256 / 256 / 256 | 0.13 [0.13, 0.14] | 0.14 [0.13, 0.14] | 0.15 [0.15, 0.16] | False cue | False cue |
| Streaming, 42 columns | 69.51 | 256 / 256 / 256 | 2.18 [2.18, 2.18] | 2.19 [2.18, 2.19] | 2.76 [2.76, 2.77] | Quiet | Quiet |
| Gzip, matched preview and small decoded file | 0.48 | 256 / 256 / 256 | 0.14 [0.14, 0.14] | 0.14 [0.13, 0.14] | 0.15 [0.15, 0.16] | False cue | False cue |

Every arm independently checked CSV fields, row conservation, partition
membership and stable order when applicable, output manifest and serialized
byte caps, marker publication, and workspace cleanup. Raw records distinguish
engine reservations, OPFS workspace size, managed storage traffic and elapsed
time. The study uses same-origin OPFS destinations. CPU, process RSS, physical
disk throughput and user-selected disk folders require separate measurements.

### What the preview can resolve

For an eligible plain UTF-8 shuffle, the candidate used the actual first eight
decoded records and column count from production preview. It estimated row
density from decoded field widths plus separators, applied the current calibrated
per-row and per-column allowance, and only raised the file-size tier. The
harness submitted it as a numeric setting to exercise the actual engine. This
simulates a recommendation on a fresh isolated engine with sufficient tracked
capacity. A product implementation must preserve live headroom checks, explicit
settings, source/parser binding and ordinary allocation admission.

For the two 42-column inputs, counting per-field overhead steered the job from
512 to 1024 MiB without a scan. Dense CSV quoting, exact consumed source bytes
and line lengths need more precise evidence. The current preview exports decoded
fields. Reconstructing separators can undercount on-disk bytes, including
optional surrounding quotes. The 40 KiB leading rows could exceed the preview's
32 KiB payload allowance, leaving no displayed sample despite a known column
count. The prototype falls back to file-size Auto for that case.

The stable-wide CSV and the narrow-tail CSV are about 60.4 MiB and share the
first eight rows. One stayed resident at 512 MiB. The other needed 1024 MiB,
and Analyze saved about 2.7 seconds even after counting the scan. Gzip inputs
with the same decoded prefix and about 0.44–0.48 MiB on disk expanded to about
60.4 MiB and 0.66 MiB respectively. Analyze saved about 1.8 seconds on the
higher-expansion input. The lower-expansion input was already fast.

### Implications for the UX

The size-only cue used proximity to a sort-tier boundary and a gzip size check.
Against file-size Auto it had three hits, two false cues and one miss. The
preview-aware cue used the same boundary check on the preview estimate and kept
the gzip check. Against preview-informed Run it had one hit, two false cues and
one miss. Preview sizing eliminated two of the original Analyze opportunities
by choosing the better tier during Run. These are matched synthetic cases, with
deliberate boundary examples. They do not estimate the prevalence or cost of
false cues on typical user jobs.

A job-level Auto mode can explain resource and strategy choices in one place.
Keep Run as the immediate primary action, and offer an explicit Analyze + Run
action for users who want the extra scan. Earn a visual recommendation only
when a calibrated cue predicts meaningful absolute savings against the best
feasible Run plan. An automatic fresh scan requires stronger evidence that the
expected seconds saved exceed analysis time and the cost of a wrong choice.

### Replay

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
node scripts/benchmark-browser-auto-resources.mjs preview
node scripts/benchmark-browser-auto-resources.mjs preview-codec-control
```

The raw records pin the fixture, WASM, production worker, driver and harness
hashes. The matching-prefix gzip control extends the original nine-shape
harness. That earlier exact source is retained in
`scratch/chopper-preview-calibration/measured-harness.mjs`. The current
harness preserves the original fixture recipes.
