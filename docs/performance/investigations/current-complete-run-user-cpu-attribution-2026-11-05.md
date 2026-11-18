## Current complete-Run user CPU attribution (2026-11-05)

**Decision: investigate fixed-size spool-key decoding next; do not infer a speedup
from sampled CPU shares.** The [two-job record](../../evidence-originals.md#sha256-708e7a725bac8d3177f4e75a3f967ecd9f9d47d87f3658bbe174affe787b20c3)
pins the default source at `e5edceabcc94362893d6bf0e9cf798e9bfe56d00`, before the
local CI changes in PR #77. No engine source changes follow from this study.
The [original harness](../../evidence-originals.md#sha256-24e1303cbe56989c6c6e6dbe24b1d930ccf20a7a93c40bcd2d7b4139e58391ac),
[recovery harness](../../evidence-originals.md#sha256-8168f834edd23dbcbcb0f70adf00ad23f605c86884b56ece0adb4b2868229cf8),
[independent verifier](../../benchmarks/current-cpu-attribution-2026-11-05-verifier.py) and
[recovery/provenance record](../../evidence-originals.md#sha256-35235a74fc74682c23c580375834782179f7c2365264c2cd1f66193b0616979a)
retain the exact capture code and reviewed recovery. These are task-layout
reproducers requiring the recorded fixtures, tool identity and reference JSON;
they are not standalone benchmark commands or a new CI pipeline.

One fresh Linux release CLI uses Rust 1.99.1 with release debug metadata level 1,
unchanged default features and complete source/vendor/embedded-asset hashes.
Task-local SHA-verified Ubuntu packages provide perf 7.0.14 and its libraries;
WSL kernel 6.18.33.1 and `perf_event_paranoid=2` are unchanged. Both complete CLI
Runs use `cpu-clock:u`, 499 Hz and 16,384-byte DWARF stacks. The fixed probe-v1
plain fixture contains one million rows and 94,776,853 bytes. Each job uses four
workers, 32-MiB job/shared admission limits, a 1-MiB record limit, 1-GiB temporary
ceiling, fixed seed `strict-csv-serial-v1` and strict million-row/128-MiB output
caps. Cache state is uncontrolled. Profiling overhead is included; elapsed values
are excluded from throughput comparisons.

| Self CPU symbol | Ordered export, 118 samples | Partition/allocation/shuffle, 832 samples |
| --- | ---: | ---: |
| Direct consume | 19.49% | See full record |
| memchr single-byte search | 12.71% | See full record |
| memchr three-byte search | 11.86% | See full record |
| BLAKE3 SSE compression | 11.02% | 11.54% |
| UTF-8 validation | 10.17% | 7.21% |
| Output PlanWriter row | 8.47% | See full record |
| Reservation resize | 1.69% | 9.38% |
| Packed-row field decoding | See full record | 5.89% |
| Buffered exact read | See full record | 4.93% |
| ReusingRows next | See full record | 4.33% |
| Header decoding | See full record | 2.04% |

Percentages are reported self sample-period shares, rounded by perf. Each column
has its own denominator; these are different recipes, not before/after variants.
Both captures report zero lost samples. The short ordered capture is coarse;
finite samples, unresolved frames and bounded stack capture limit caller attribution.
Inclusive callgraph percentages overlap and must not be summed. BLAKE3 callers
are not fully separated, so its full share cannot be assigned to shuffle keys.
User CPU excludes kernel work and cannot establish wall-time, physical I/O, RSS,
Windows/browser performance or a general bottleneck hierarchy.

The pipeline is partition(region) -> probabilistic 80/20/0 allocation -> uniform
child shuffle. Both jobs independently verify fields, unique IDs, membership,
lineage, strict caps, inventory and cleanup. Raw CSV hash maps, output records
and 17 logical Analysis fields exactly match the pinned native Windows oracles;
those old timing observations are not reused. Ordered output also equals input
bytes. Reported Analysis timings and reservations precede final publication and
remain separate from complete-Run accounting.

Setup failures remain recorded: an epoch-encoded package filename mismatch,
a dangling package-documentation symlink in an overbroad input declaration, and
a report regex that read zero lost samples as zero total samples. One actual
tiny sampler control captured 206 samples with zero loss; a separate read-only
parser verification accepted those bytes without repeating capture.

The original ordered Run exited successfully and passed all functional checks,
but its coordinator invalidated the step when perf's build-ID cache created a
hard link and changed the ELF's ctime. A new read-only audit verifies all declared
content, inode, mtime and size plus the actual same-inode cache link; only ctime
changed. The original invalidated status remains intact. The unused pipeline
capture uses `--no-buildid-cache` in a separately reviewed recovery, whose three
steps pass. No ordered Run or build was repeated. The one-build/two-Run caps are
consumed. Private raw profiles, logs, manifests, frozen sources and binaries stay
under `scratch/current-cpu-attribution-20261105T0920/`; published hashes identify
them without adding derived records as observations.

Source inspection identifies a concrete next hypothesis: spool headers allocate
and admit a Vec for common 16-byte random keys before packed decoding converts
them to an existing inline key. A private inline-header representation could
remove that transient allocation and grant churn. It needs separate owned-row
conversion, variable-key capacity/boxing overlap, field/grant destruction ordering,
metadata-layout and corruption/denial cleanup controls before complete-Run tests.
This does not attribute all reservation cost to keys or authorize promotion.
An alternative suspected per-row owned-parser shrink was rejected by source
inspection: shrinking occurs only above the aggregate workspace threshold.
