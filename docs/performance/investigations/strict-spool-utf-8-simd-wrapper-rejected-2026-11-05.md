## Strict spool UTF-8 SIMD wrapper rejected (2026-11-05)

**Decision: reject the unchanged wrapper for this pipeline and restore production
sources exactly; retain successful correctness evidence and the unapplied patch.**
The [six-job record](../../evidence-originals.md#sha256-91938e88778dc2ea8cee192606641117c7a5238569af220b54d933724521d41a), [prototype patch](../../benchmarks/spool-utf8-simd-2026-11-05.patch)
and [native harness](../../benchmarks/spool-utf8-simd-2026-11-05.py) test the next named cost from the
[current CPU attribution](../../performance.md#current-complete-run-user-cpu-attribution-2026-11-05).
Its 7.21% pipeline self share for standard UTF-8 validation was not fully separated
into spool callers; it justified a hypothesis, not a predicted gain.
The harness requires the recorded task layout and unchanged
[process CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py).

The private helper called safe `simdutf8::compat::from_utf8` and returned the
original concrete `std::str::Utf8Error` through scalar fallback on failure. Three
borrowed spool-validation sites changed: complete packed fields, the buffered
streaming fast path and ordinary split-field chunks. The tiny crossing-scalar
state machine, owned String decoding, CSV parser and all field/grant lifetimes
remained unchanged. No Chopper unsafe code, buffer, worker, RNG, execution graph,
retry or default policy was added. The direct dependency reused locked version
0.1.5 but newly enabled its std runtime-dispatch feature; encoding_rs already
used its direct platform implementations. Both resolved feature trees are
recorded. This was an intentional feature change, not an identical-feature pair.

Before measurement, the practical decision rule required both opposite-order
elapsed/CPU pairs to favor the candidate and at least 2% median elapsed reduction.
This was an experiment criterion, not a product selector. Four fresh native
Windows Runs use one million plain probe-v1 rows, partition(region) ->
probabilistic 80/20/0 allocation -> uniform child shuffle, in ABBA order.
Both variants use four workers, 32-MiB job/shared limits, a 1-MiB record limit,
1-GiB temporary ceiling, seed `strict-csv-serial-v1` and strict million-row/128-MiB
output caps. Wall time spans CLI startup through complete Run/publication,
Analysis JSON and exit; hashes, independent verification and post-exit CPU queries
are excluded. Cache/background apps remain uncontrolled; own builds finish first.

| Pipeline | Observations | Median elapsed seconds | Elapsed range | Median process CPU seconds | CPU range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing standard validation | 2 | 2.62395 | 2.56773–2.68017 | 2.23438 | 2.21875–2.25000 |
| SIMD wrapper | 2 | 2.68629 | 2.65228–2.72029 | 2.40625 | 2.34375–2.46875 |

Candidate-minus-baseline opposite-order elapsed differences are +0.04013 and
+0.08455 seconds; CPU differences are +0.09375 and +0.25000. Relative to baseline
medians, elapsed increases 2.38% and process CPU 7.69%. Both pairs reject the
candidate under the frozen rule. Overlapping elapsed ranges, short samples and
coarse CPU counters still prohibit significance, tail or general device claims.
The separate unreplicated ordered control has elapsed 0.35826/0.34178 seconds
and identical 0.296875-second process CPU; it is not pooled with the pipeline.
No causal component attribution, older timing reuse or summed historical gains
follows. This does not show SIMD cannot help other workloads; no shape/threshold
retuning or additional matrix follows from the rejection.

All six jobs independently verify fields, unique IDs, groups/lineage, strict caps,
inventory and cleanup. CSV hash maps, output records and 17 logical Analysis
fields match exactly per cohort; ordered output equals the 94,776,853-byte input.
Pipeline prepublication snapshots retain the same 36 sort runs/eight merges and
logical traffic. Workspace peaks are 7,461,081/7,461,090 bytes for pipeline and
202,250/202,256 for ordered export, with variant path/name charges. Returned
snapshots are separate from complete-Run I/O, physical traffic and RSS.

The measured head passes the full selected local Linux workflow: native UI/Rust,
combined features, core WASM target, browser/WASI resource/cleanup/termination,
evidence, tooling, site and aggregate checks. Native Windows native/tooling and
planner/result also pass. The new normative control checks 524,288 adjacent-byte
cases at vector boundaries plus 576 explicit Unicode/malformed/truncated cases,
including concrete standard error diagnostics and borrowed-pointer preservation.
Existing split-refill, corruption, admitted growth/ownership and cleanup controls
remain passing. The native experiment batch passes 5/5 gates without failures.

The existing [inline-key candidate](../../performance.md#inline-fixed-size-spool-header-keys-2026-11-05)
is the actual baseline artifact. All 330 maintained compilation/vendor/embedded
files and exact file-set match the current base; original file/directory hashes,
binary, Cargo executable, compiler and complete build environment are rechecked.
The prior CPU self-control is reused only with matching helper/interpreter bytes.
Exact patch replay matches the measured native candidate. A prelaunch context
review replaces inherited free-memory/volume observations with a fresh snapshot;
earlier prepared manifests remain preserved, and no engine job was repeated.
The wrapper/direct dependency/lock change is reverted before evidence delivery.
Fresh final-tree/head/base local checks and `local-ci.py land` gate that delivery;
local receipts record the actual final result. Hosted CI is not dispatched and
macOS remains deferred.

Context is Windows 11 build 26200, Ryzen 7 5800X, NTFS and Rust 1.99.1. Frozen
sources/binaries, complete outputs, resolved feature trees, plans and full logs
remain under `scratch/spool-utf8-20261105T1225/` in both checkouts. The one-build/
six-Run budget is consumed; source attempt one of three was sufficient. No
component scans, measurement repeats, retuning or expansion ran. Continue from a
different named cost; preserve this rejection rather than promoting an equivalent
wrapper through a new filename or branch.
