## Current retained-parent Windows calibration attempt (2026-10-21)

The [current-build attempt](../../evidence-originals.md#sha256-703d1a7e341b75eea9908be6d6f459008bd50b096bb4d63532eb0e0e285e127f "Original: docs/benchmarks/windows-retained-parent-audit-current-2026-10-21.jsonl"),
[fresh build provenance](../../evidence-originals.md#sha256-0c020f8fa1af01d5b6b8eba68e3db7e6567bebe73c6646a91dd6d40524e782cf "Original: docs/benchmarks/windows-retained-parent-current-builds-2026-10-21.json")
and [validation record](../../evidence-originals.md#sha256-e19fc4b47af620a49f17c9021d4c6ee5618ba7822c58d8c191fc9bf71b442f81 "Original: docs/benchmarks/windows-retained-parent-current-validation-2026-10-21.json")
preserve a stopped calibration pass: **zero complete jobs and zero timing
measurements**. Windows Application Control rejected the first fresh baseline
process with WinError4551 before execution. The harness stopped immediately;
no path/executable/policy workaround, repeated launch or matrix expansion was
attempted. The temporary run directory was removed. This is an execution
prerequisite gap, not evidence of a performance effect or an engine failure.

A subsequent [read-only policy diagnosis](../../evidence-originals.md#sha256-f02b8310d5f5466a0a39155c045ac2e9b40704dda5ad18138be2f5cea6cd9f5f "Original: docs/benchmarks/windows-app-control-diagnosis-2026-10-21.json")
identifies Smart App Control: state `1` (On), Code Integrity event 3077 under
`VerifiedAndReputableDesktop`, status `0xc0e90002`, requested signing level 2
versus validated level 1. The blocked baseline is unsigned and has no
`Zone.Identifier` stream; even `--version` is rejected before process execution.
No security settings were changed and no successful native rerun is implied.

The intended decision was whether current exact fusion plus its bounded audit
preserves benefit around one historical near-flat workload and one external
winner. The planned two cells were 17,000 and 300,000 rows, 33 columns, ten cycling
partition keys and `balanced(1) -> uniform -> partition(c0)`, at 32 MiB/four
workers with a 128 MiB shared ceiling, three alternating pairs each. Only the
17,000-row fixture was generated before rejection. Historical row brackets
selected workloads; this added retained boundary/current accounting is a new
stratum and cannot inherit historical crossover plans or medians. The pass would
measure the combined feature, not isolate audit overhead.

The Windows harness now has `--retained-parent`: legacy `uniform -> partition`
cells use ingestion fusion and never initialize the retained-parent audit. The
new mode requires one complete charged decision record with original stage and
parent identity, complete decoded/keyed observations, fused commit, no retries
and no selector/calibration. Baseline must have no candidate audit. The shared
verifier still checks exact live-owner equality, now including a validated audit
charge; it does not erase the previous reservation assertion. Existing ID/field,
membership, metadata, CSV fingerprint and successful-cleanup checks are reused.
Ten portable harness tests pass, including rejection of missing/malformed audit,
wrong mode and owner mismatch. These tests are not successful CLI acceptance.

Fresh source inventory includes tracked and nonignored untracked `crates`/`ui`
inputs and manifests, including the new audit/export code. Both release binaries
were built from the same verified 102-file inventory, with toolchain, commands,
features, transcripts and binary hashes recorded. Before/between/after build and
attempt checks match. Fresh read-only hardware discovery maps C: to NTFS/NVMe;
cache was planned warm/uncontrolled and no physical-device counters were used.
No CPU, RSS, reservation, logical-traffic or physical-I/O comparison follows
from an unstarted process.

Exact [Windows harness](../../benchmarks/windows-retained-harness-attempt-2026-10-21.py)
and [shared verifier](../../benchmarks/external-retained-verifier-attempt-2026-10-21.py)
snapshots match the attempt's harness hashes. To replay, copy them under their
original `scripts/benchmark-windows.py` and `benchmark-external-shuffle.py` names
in an isolated scratch layout and use the pinned builds and recorded command;
the Windows execution prerequisite must first be resolved. Earlier raw artifacts
remain unchanged. Current-build performance and selector calibration stay open
in [TODO](../../../TODO.md).
