## Hosted release comparison 0.6.4 to 0.6.5 (2026-11-26)

The [release charts](../../releases/0.6.5.md#performance-compared-with-v064)
compare the WASM and two workers from the published v0.6.4 hosted ZIP with
the v0.6.5 production assets. The [sample data](../../benchmarks/0.6.5-performance-data.json)
pins both asset sets, the Chromium executable, the fixture recipes and hashes,
and each sample's position in the retained capture.

The clock starts at the hosted Run request and stops after export and worker
retirement. Each workload used its own disposable persistent bundled Chromium
profile on WSL2 ext4. Input was copied to OPFS before timing, and caches were
uncontrolled. The benchmark alternated order for three matched pairs after
one excluded warmup per release. Each Run used one worker, plain CSV and
the memory and strict CSV byte caps listed in its fixture recipe.

The independent output check verified all fields and unique source rows,
partition membership or Balanced quotas, lineage, operation statistics, byte
caps and the completion marker. Both deterministic Balanced workloads matched
in exact CSV order across releases. Shuffle workloads use fresh Run entropy.
The harness checked the expected publication route, read-ahead use, shared
Balanced traversal and workspace retirement.

The release measures the combined changes in one runtime. See the
[guarded Partition then Shuffle](guarded-hosted-partition-shuffle-publication-2026-11-26.md),
[Shuffle then Partition](hosted-shuffle-then-partition-buffered-output-2026-11-26.md),
and [read-ahead, Shuffle then Balanced and adjacent Balanced](hosted-data-movement-follow-ups-2026-11-26.md)
investigations for separate implementation experiments and holdouts.

To replay, extract both hosted release ZIPs and install the locked UI
dependencies and bundled Chromium from this revision. Pass a local JSON
file to the [paired harness](../../benchmarks/hosted-release-comparison-064-to-065.mjs). Use absolute
paths for the baseline and candidate `engine.wasm` files and the
[verifier](../../benchmarks/hosted-release-comparison-064-to-065.py), assigned to `baseline`,
`candidate` and `verifier`. Set `out` to a fresh output directory and
`cases` to each workload's `recipe` from the sample data, in document order.
Run `node docs/benchmarks/hosted-release-comparison-064-to-065.mjs CONFIG.json` from the repository root.
