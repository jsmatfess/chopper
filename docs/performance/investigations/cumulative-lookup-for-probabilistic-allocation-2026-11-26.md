## Cumulative lookup for probabilistic allocation (2026-11-26)

[Issue #103](https://github.com/jsmatfess/chopper/issues/103) ·
[Run samples](../../benchmarks/probabilistic-allocation-cumulative-2026-11-26.jsonl) ·
[Lookup component samples](../../benchmarks/probabilistic-lookup-wasm-component-2026-11-26.json) ·
[Measured patch](../../benchmarks/probabilistic-allocation-cumulative-2026-11-26.patch)

Starting at 64 configured groups, convert validated weights in place to
cumulative thresholds. The first interval keeps a constant-time test. For
other intervals, binary search finds the first threshold strictly above the
original draw. Repeated thresholds skip zero weights. Small fanouts retain the
subtractive lookup. Both paths use the existing keyed stratum framing, bounded
draw, group order, and admitted vector size.

### Measured result

Alternating pairs ran in persistent bundled Chromium on WSL2 with 128 MiB,
one worker, Auto grouping, eight strata and a plain 4 MiB CSV cap. Timing starts
at Run and ends after verified marker publication and workspace retirement.
Three included pairs follow one excluded warmup per arm and cell. Every export
verified fields, conservation, configured order, within-group subsequences,
zero weights, sizes, caps and marker. Independent Run entropy means these
exports can differ in membership. The internal seeded oracle and threshold
boundary test verify exact agreement for a fixed draw.

| Workload | Baseline median [min–max], s | Candidate median [min–max], s | Paired milliseconds saved [min–max] |
| --- | ---: | ---: | ---: |
| Near-uniform 64 groups, 450,000 rows | 1.458 [1.456–1.472] | 1.445 [1.434–1.454] | 19 [13–21] |
| Near-uniform 512 groups, 900,000 rows | 4.794 [4.772–6.181] | 4.724 [4.636–5.820] | 136 [70–361] |
| 512 groups, 90% in the first, 450,000 rows | 3.644 [3.632–3.645] | 3.647 [3.623–3.648] | −4 [−4–9] |
| 80/20, 240,000 rows | 0.628 [0.626–0.630] | 0.636 [0.636–0.646] | −10 [−18–−6] |

The 512-group near-uniform outer range includes a slow pair in both arms.
All three pairs favor the candidate. Early-heavy complete Runs are near even,
and the small 80/20 case adds about eight milliseconds at the medians.
The lookup selector does not change tracked temporary traffic in these cells.

A separate WASM lookup component in Node V8 uses the same two lookup loops and
identical preplanned draw generation for both arms. Its five 500,000-draw medians
move from 9.28 to 3.38 ms at 64 groups, from 46.06 to 4.69 ms at 512 near-uniform
groups, and from 6.47 to 2.36 ms at 512 early-heavy groups. The probe excludes
per-row blake3 hashing, routing, sorting and publication. These component times
cannot be subtracted from the complete Run measurements. The observed benefit at
64 groups supports retaining that threshold. Lower fanouts were outside this
crossover screen.

### Provenance

Build feature-free WASI at `ab8e1519afd15d6c22d42ee2b2ec4a5e4deca393` using
`node scripts/build-browser.mjs` and the measured patch for the candidate.
The samples pin the WASM, worker, driver, recipe, and verifier identities.
The hosted driver derives from
[`benchmark-swarm.ts`](../../../ui/tests/benchmark-swarm.ts) with an
OPFS-backed input and capture of the final worker observation. Initial harness
attempts reached Run completion but failed observation and verifier assertions,
respectively. They were excluded without substituting durations.
