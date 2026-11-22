## Browser preview calibration on larger files (2026-11-21)

This follow-up extends the [previous preview calibration](browser-preview-and-analyze-calibration-2026-11-21.md)
to decoded sort inputs around 157–164 MiB and a streaming control near 295 MiB.
It keeps the same preview sizing and cue rules. The question is whether existing
preview observations still improve Run at this scale, and whether recommending
a fresh Analyze still depends on facts the preview misses.

[Matched large jobs](../../benchmarks/browser-large-preview-calibration-2026-11-21-main.jsonl)

[Standalone shuffle and fixed-budget controls](../../benchmarks/browser-large-preview-calibration-2026-11-21-shuffle-control.jsonl)

[Replay harness](../../../scripts/benchmark-browser-auto-resources.mjs) ·
[Candidate rules](../../../scripts/browser-preview-calibration.mjs)

### Results

**Preview sizing replicated.** A 163.85 MiB, 42-column standalone shuffle used
1024 MiB with file-size Auto and still spilled. Preview sizing chose 2048 MiB,
made it resident, and saved 8.05 seconds. File-size Auto had already chosen
2048 MiB for the same file with Partition → Shuffle, so preview sizing left the
tier alone. The two arms at that tier measure normal elapsed variation.

**The Analyze cue still had limited discrimination.** It had one hit, three
false cues, and three quiet cases. Analyze + Run saved 4.64 seconds compared
with preview Run on the 157 MiB decoded gzip fixture. A near-sized compressed
file with the same first eight records expanded to just 1.74 MiB and drew the
same cue. The wide-row plain shuffle was already resident at 1024 MiB. Its
Analyze scan and the streaming control's scan added about 0.9 and 2.4 seconds
respectively.

**Analyze exposed a tier-selection regression.** The 156.95 MiB narrow-tail CSV
shares its first eight records with the 157.10 MiB resident wide-row CSV. For the
narrow tail, file-size Auto chose 1024 MiB and made two spill runs. Analyze put
its estimated footprint at 524.5 MiB, above the nominal 512 MiB sort target at
the highest tier. The planner fell back to 256 MiB, made seven runs, and took
16.03 seconds including the scan. A fixed 2048 MiB request on identical input
completed in 6.65 seconds [6.65, 6.65] with zero spills in both rounds. This
isolates a viable higher tier for this shape. The observation does not establish
that jobs beyond the largest estimated sort target should always use 2048 MiB.
See the [current tier estimator](../../../crates/chopper/src/engine/auto.rs).

This supports using preview facts to improve eligible Run choices. The cue
evidence still favors an explicit Analyze + Run action. The oversized-estimate
fallback needs a separate policy change and validation before automatic Analyze
can be evaluated on this boundary.

| Fixture | Source / decoded CSV MiB | Budgets in MiB, size / preview / Analyze | File-size Auto | Preview Run | Analyze + Run | Preview cue |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 42 columns, Partition → Shuffle | 163.85 / 163.85 | 2048 / 2048 / 2048 | 6.46 [6.33, 6.59] | 6.25 [6.23, 6.27] | 7.70 [7.64, 7.76] | Quiet |
| Same 42-column source, Shuffle | 163.85 / 163.85 | 1024 / 2048 / 2048 | 14.00 [13.90, 14.10] | 5.95 [5.93, 5.97] | 7.40 [7.33, 7.46] | Quiet |
| Stable wide rows | 157.10 / 157.10 | 1024 / 1024 / 1024 | 4.96 [4.92, 4.99] | 4.88 [4.88, 4.89] | 5.79 [5.77, 5.82] | False cue |
| Matching head, narrow tail | 156.95 / 156.95 | 1024 / 1024 / 256 | 14.84 [14.81, 14.87] | 14.74 [14.71, 14.77] | 16.03 [15.98, 16.09] | False cue |
| Gzip, large expansion | 1.14 / 157.10 | 256 / 256 / 1024 | 9.40 [9.39, 9.41] | 9.43 [9.40, 9.45] | 4.79 [4.75, 4.84] | Hit |
| Gzip, matching head, limited expansion | 1.24 / 1.74 | 256 / 256 / 256 | 0.19 [0.19, 0.19] | 0.19 [0.19, 0.19] | 0.22 [0.22, 0.22] | False cue |
| Streaming control | 295.02 / 295.02 | 256 / 256 / 256 | 9.04 [9.03, 9.05] | 9.03 [8.99, 9.07] | 11.45 [11.43, 11.48] | Quiet |


Each timing is a two-run median in seconds with its observed range. A cue is a
hit when starting a fresh Analyze saves at least 0.5 seconds in both matched
rounds compared with the preview-informed Run. Analyze + Run includes its extra
scan. The baseline and candidate both use the production bounded preview during
setup, outside the Run clock. Run time covers execution, final destination
writing, completion-marker verification and workspace cleanup.

All 44 complete jobs verified record fields and conservation, partition
membership and stable order where applicable, manifest agreement, strict 4 MiB
serialized output limits, and completion. The same WASM and production workers
ran in disposable Chromium contexts on WSL with same-origin OPFS destinations.
The preview-informed candidate simulates its estimate using a numeric budget in
a fresh isolated engine. Its allowance remains subject to actual allocation
admission. The raw evidence tracks OPFS and working reservations separately.
These are synthetic shapes with two observed rounds per arm. Other hardware,
browser processes under contention, user-selected disk destinations and larger
order-of-magnitude jumps need separate qualification.

### Replay

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
node scripts/benchmark-browser-auto-resources.mjs preview-large
node scripts/benchmark-browser-auto-resources.mjs preview-large-shuffle-control
```

The raw records pin fixture, WASM, worker, driver and harness hashes. The exact
large main harness before adding the two controls is retained in
`scratch/chopper-preview-calibration/large-harness.mjs`. The current harness
preserves the main panel's recipe.
