## Reading guide

Independent-parent batching/materialization/replay and
`experimental-parallel-groups` were removed after Astra's E2 rejection on
2026-10-25. Dated group measurements and commands below describe historical
builds. Replay requires pinned old artifacts and preserved sources, including
the archived `scripts/benchmark-parallel-groups-windows.py`; it is no longer an
active harness. See the [decision](../../performance.md#independent-parent-batching-removal-2026-10-25).

Partition-first and dormant Parquet feature/dependency wiring are removed as of
2026-10-24. All dated descriptions, commands and exclusions below retain their
historical build meaning. Partition-first reproduction requires pinned old
binaries and historical harnesses; current multi-engine cases reject the removed
`flex_reverse_*` cases. Python Parquet/CSV adapter evidence is separate from the
subsequently rejected direct Rust compact/Arrow IPC APIs. No measurement is revised.

Radix-sort and prefix-distribution descriptions, feature names and commands below
are historical for their dated builds. Both executable experiments and feature
forwarding were removed on 2026-10-24; see [validation](../../validation.md#radix-and-prefix-distribution-removal-2026-10-24).
Raw evidence and original source identities are preserved. Shared harnesses now
cover surviving operations; historical command lines require their original build.

Use the [generated benchmark index](../../benchmarks/INDEX.md) to find every top-level evidence section, its artifacts and reproduction scripts. The [benchmark guide](../../benchmarks/README.md) explains provenance, comparison limits and record export for future analysis. [Completed checklist entries](../../history/completed-work-2026-10-20.md) preserve implementation status; [decision priorities](../../performance-opportunities.md) explain what merits further work.

The sections below retain their original anchors and dated conclusions. Remaining-work notes inside a dated section describe that pass, not the current backlog. Consult [TODO](../../../TODO.md) before scheduling work.
