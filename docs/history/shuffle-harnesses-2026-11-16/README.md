# Historical shuffle harness sources

These nine harnesses target the recorded pre-removal engines, including removed
`full_shuffle_policy` / `flexible_v1`, partition-first, random-bucket and RNG
experiments. They are **not supported commands for current main**. Archival does
not rerun a benchmark, restore a removed policy or establish a performance result.

[The inventory](manifest.json) pins every original path, byte count and SHA-256
at `de93a7a728fd8652f01627b1d1483409ed499455`. All nine source files are unchanged
(1,038 lines). `benchmark_storage.py` and `diagnose-shuffle.py` are unchanged copies
of their sibling dependencies, so source inspection and `--help` work here. This
is source organization, not a net repository line-count saving.

Use the owning historical investigation's exact binary, source, features,
harness and fixture identities for replay. Run from the repository root; the
archived script path replaces the old `scripts/` path only when using these same
source bytes. Fenced commands in immutable narratives retain their original path
spellings and refer to the recorded checkout. Narrative source hyperlinks and
catalog navigation route here through reversible relocation metadata; their
original section hashes, prose and raw evidence stay unchanged.

For current commands, start with [the script guide](../../../scripts/README.md)
and [benchmark rules](../../benchmarks/README.md). Historical sources remain
available for interpretation; do not substitute today's engine into an old
comparison merely because its harness can start.
