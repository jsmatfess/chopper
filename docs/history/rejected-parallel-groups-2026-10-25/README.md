# Rejected independent-parent batching sources

These are byte-for-byte r8 pre-removal snapshots, preserved for historical replay.
They are not active engine modules or supported benchmark entry points. Restore
each to its original path in a separate copy of the matching preserved source
tree before replay; use its original lockfile, vendor, features and binary pins.
Do not run them against the current feature-free engine.

- `parallel_groups.rs`: `crates/chopper/src/engine/parallel_groups.rs`
- `validate-parallel-groups.py`: `scripts/validate-parallel-groups.py`
- `benchmark-parallel-groups-windows.py`: `scripts/benchmark-parallel-groups-windows.py`

The full r8 pre-removal tree, including exclusive helper/counter definitions in
other files, is `.tools/e2-removal-20261025-r8/source-before/`; its SHA256 manifest
is `raw/baseline.json`. Prior original E2 sources/binaries/raw/failed evidence and
the immutable bundle remain at the paths recorded in the
[removal decision](../../performance.md#independent-parent-batching-removal-2026-10-25).
No historical raw measurement or numerical synthesis is changed.
