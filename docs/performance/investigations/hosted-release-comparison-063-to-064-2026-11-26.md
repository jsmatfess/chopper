## Hosted release comparison 0.6.3 to 0.6.4 (2026-11-26)

The [release charts](../../releases/0.6.4.md#performance-compared-with-v063)
use v0.6.3's published hosted ZIP and the v0.6.4 production assets. The
[release observations](../../benchmarks/0.6.4-performance-data.json) pin both
asset sets, Chromium, the fixture recipes and hashes, and the source lines
for each sample. The original capture, paired driver, and verifier are
retained locally. The same [Run driver](../../../ui/tests/benchmark-swarm.ts)
loads both builds' own WASM and workers. The fixture is moved into OPFS
before the clock starts. A persistent profile per workload provides the same
storage context for both arms. Cache state was uncontrolled.

Each of 13 workloads has an excluded warmup per release, followed by three
alternating pairs. The clock includes export and worker retirement.
Independent verification after the clock checks record conservation, exact CSV
byte caps, lineage, and the applicable membership and order contracts.
The retained deterministic routing, Balanced, and calculated cases match
across the comparison. Allocation and Uniform use fresh entropy. Every Run
completed with an export marker and clean workspace retirement.

The aggregate release changes saved the most time and temporary I/O on the
two large calculated Partition workloads. The routed identifier keys and
Balanced fixtures also improved in every pair. The high-skew allocation
control took longer in every pair. The small calculated control's paired
changes straddled zero. This comparison measures the combined release
changes on one hosted runtime. The linked change investigations in the
release notes give the isolated experiments and promotion decisions.
