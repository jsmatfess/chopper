## Allocation post-preparation pressure boundary (2026-11-03)

Decision: **block promotion of the unchanged materialized-parent retry candidate**.
A [focused Linux native control](../../benchmarks/allocation-post-prepare-pressure-2026-11-03.json)
resolves the [previously open emission-pressure question](../../performance.md#allocation-retry-safety-and-runtime-evaluation-2026-11-03):
a genuine admitted competitor arriving after preparation can deny the resident
candidate while immediate routing completes. This rejects admission-domain
inclusion for this boundary. Earlier fitting-case pass reductions remain valid;
they do not establish safe general activation.

The original candidate is unapplied and unchanged. The
[additional test-only patch](../../benchmarks/allocation-post-prepare-pressure-control-2026-11-03.patch)
applies after the original retry patch. In all three cells, the real DatasetWriter
exists before preparation, matching current dispatch. A 2,500-row materialized
parent has three fields: ID, a 128-byte payload and ID modulo seven. The existing
35/65 probabilistic helper, original domain and strata are unchanged. The context
has a 16-MiB working budget and an 8-MiB shared pool. These are scaled synthetic
native controls, not complete-job performance or independent workload transfer.

Preparation succeeds without retry in each cell. The unpressured candidate
retains 846,129 shared bytes. The declared rule derives one 7,542,223-byte
competitor grant, admitted in a separate workspace only after preparation in
both pressured cells and retained through emission. Routing retains 139,639 bytes
and completes all 2,500 rows with 706,746 bytes initially free. The candidate has
256 bytes free and fails typed shared admission before any sink row. It scans
once and does not replay emission. Source inspection locates the remaining
admission work in `ReadyGroups::emit`, including `ClonedGroup::begin_child`;
preparing SortedRows does not pre-admit child metadata or every later read.

The unpressured candidate and pressured routing output match exact serialized
group metadata and row frames, with all IDs exactly once and every field checked.
All cells release their working grants and temporary directories; no final CSV
publication is exercised. This deterministic transition injects an admitted
competitor, not OS pressure, and says nothing about how often it occurs in real
jobs. No elapsed-time comparison, RSS cap, physical-I/O, Windows, WASI or new
browser claim follows.

The first 64-row attempt does not show this counterexample: routing retains more
than the tiny resident parent, so the proposed competitor cannot be admitted in
that cell. Its failure and the separate Cargo/compiler/manifest setup failures
are preserved, excluded from the successful matched control, and explained in
the record. The separately declared 2,500-row attempt uses a previously studied
fixture size without sweeping thresholds or touching reserved performance holdouts.

Replay from an isolated copy of source base `409a017625aa856ecfd73263bc11a0a3a61cb18e`:
apply `resident-parent-retry-prototype-2026-11-03.patch`, then the new test patch,
and run `cargo test --locked -p chopper --lib parent_retry_ -- --nocapture --test-threads=1`.
Formatting, workspace/all-target Clippy and the three focused parent-retry tests
pass, as do full locked workspace tests. Complete source/vendor/native-UI
identities, tested binary, plans, status and full logs
remain private under `scratch/allocation-emission-20261103/`; no raw upload or
cleanup is claimed. Repository CI does not compile the unapplied patch.

Before a promotion proposal, resolve this boundary with a separately reviewed
feasibility remedy or an explicitly authorized narrower success contract.
Independent eligible workload transfer and complete retry costs remain open in
TODO; this finding does not authorize another matrix or promotion.
