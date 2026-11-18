## Retained-parent shape calibration outside the checkout (2026-10-21)

The [location-control pass](../../evidence-originals.md#sha256-f6f348eb31963680bd65574e3e1a8910a07cb2581834cc8418d737597c4d630b "Original: docs/benchmarks/retained-targetssd-outside-checkout-2026-10-21.jsonl")
reuses the exact previous pinned Windows accounting-build baseline/candidate,
fixtures, seed, workers and budgets to complete the interrupted skew/rare-wide
cells in a fresh system-temporary parent outside the checkout. It retains the
original build-source evidence instead of attributing those binaries to newer
test edits. Normal 20 ms live sampling remains enabled. The
[post-run context record](../../evidence-originals.md#sha256-59ca646842d970681a46d980052c0ca81fede414fdc352d51ac238647d5235dd "Original: docs/benchmarks/retained-outside-context-2026-10-21.json")
verifies the outside path is still on C: NTFS and the same NVMe disk; the raw
jobs' supplied hardware snapshot retains its original collection time. Cache
and background activity remain warm/uncontrolled. No other build, test or
benchmark ran during the timed cells. Stop on first failure/parity/cleanup
mismatch or after three alternating matched pairs per cell.

All 12 complete jobs pass field/ID conservation, exact output/metadata parity,
strict caps, the retained-parent audit, exact live-owner equations and temporary/
staging cleanup. The parent is empty after the jobs. The
[derived summary](../../evidence-originals.md#sha256-fb079666bb9a2760105c192ffcccc001aaa293984da56d86d0a3894960144190 "Original: docs/benchmarks/retained-targetssd-outside-checkout-2026-10-21-summary.json")
retains the source hash and physical per-variant measurement lines. Skew median
baseline/candidate times are 1.635 (1.634–1.685) / 1.274 (1.260–1.286) seconds;
rare-wide times are 1.746 (1.741–1.768) / 1.292 (1.284–1.298). Candidate median
reductions, relative to each baseline median, are 22.1% and 26.0%. These are
within-cell comparisons, not a pooled effect or a comparison with interrupted
checkout runs. Skew uses the corrected 90/9/1 payload key.

Median CPU baseline/candidate is 1.438/1.141 seconds for skew and 1.500/1.156
for rare-wide. Skew peak tracked reservations are 8.60/8.16 MB; rare-wide
reservations are essentially unchanged at 8.664/8.668 MB. Engine temporary
peaks fall from 319.1 to 256.5 MB and 324.8 to 256.4 MB respectively. Sampled
combined temp/staging/output peaks, process working set and logical temporary
traffic remain distinct fields in the summary; sampled peaks are lower bounds,
and reservations are not an RSS cap. No physical SSD I/O is measured.

Decision: the same pinned build now has completed skew/wide acceptance on this
volume outside the checkout, supporting further opt-in evaluation alongside its
external/hierarchical cells and near-flat transition control. This does not
identify or resolve the holder causing Windows publication error 5 inside the
checkout; it narrows the operational condition without proving causation. The
failed/partial checkout runs remain excluded and preserved. No native publication
retry or overwrite behavior is changed, no universal outside-checkout convention
is imposed, and no selector/default or broader runtime/device claim is promoted.
Reproduce using [benchmark-windows.py](../../../scripts/benchmark-windows.py) with
`--retained-parent --cells skew rare_wide --repeats 3`, a fresh outside-checkout
`--work-dir`, new `--output` and the original matching `--build-evidence`.
