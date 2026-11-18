## Linux revalidation of the published lineage build (2026-10-22)

The [six-command Linux pass](../../evidence-originals.md#sha256-bf0482b801f04f956041d5664c66dbf72b5c1c958c01cfa596cb68fa3c5efe7e "Original: docs/benchmarks/current-linux-revalidation-2026-10-22.json")
checks the same source inventory as the nested-lineage final-source record,
including patched vendor sources. WSL Ubuntu with the retained Linux Rust
toolchain passes formatting, default and combined-feature Clippy, default
workspace tests and combined-feature Chopper tests. Source identities remain
unchanged across the pass. Tests use Linux temporary/output fixtures; this adds
Linux correctness coverage for that source snapshot. It does not validate macOS,
physical storage effects, additional scale or later child-lineage changes.
