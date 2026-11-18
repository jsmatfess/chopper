## Probabilistic shuffle fusion: peer after buffer observation (2026-11-05)

**Decision: block promotion of the unchanged observation-only storage revision.**
The [four-job counterexample](../../evidence-originals.md#sha256-41956c94620846e64ec55441a1e33df5d4bf6a19447ede6779b69833e50cd8b0)
and [test-only instrumentation](../../benchmarks/probabilistic-shuffle-after-observation-2026-11-05.patch)
close a named gap left by the
[available-buffer control](../../performance.md#probabilistic-shuffle-fusion-available-buffer-storage-control-2026-11-03).
Both Linux and native Windows complete when the peer arrives immediately before
target observation and return typed Shared admission denial when it arrives
immediately after. All owner-lifetime and cleanup checks pass. Production remains
unchanged; this is a scientific falsifier, not a command failure or physical OOM.

Both jobs use the same retained candidate, 20,000 original probe-v1 rows in one
R0 parent, 50/50/0 probabilistic groups and uniform shuffle. The original seed,
one worker, 32-MiB job/pool and 1,024-row/65,536-byte caps stay fixed. A caller-local
hook acquires the same 28-MiB peer grant either just before or just after the
alternative Sorter constructor, after membership/domain construction and before
packed-row traversal. Per runtime, pool ownership before and after injection is
identical between the two cases; only the observed sort target changes. The
peer remains live through each outcome. No capacity/shape sweep or elapsed panel
runs, and no earlier samples are counted again.

The before case observes reduced headroom and completes with independent fields,
unique IDs, group count and cap checks. The after case keeps the larger target
selected before the peer existed. Its Linux backtrace reaches
`Sorter::flush` at `io.resize(65536)` through `push_packed` during fused
accumulation, before `sorter.finish` or the first child sink row. Windows confirms
the typed outcome and identical exposure; its optimized stack labels do not
independently locate the Rust call site. There is no completed after-case output,
so this is not a successful paired CSV-parity comparison.

Every job visits input once, removes owned temporary/private staging files,
retains only the deliberate peer after job destruction, then returns the pool
to zero after peer release. Reading headroom does not acquire a future spill
writer or temporary-construction grant. A separately bounded storage remedy can
prepare those owners before retaining rows; extra live files/buffers and earlier
admission would need their own acceptance. Retry or execution graph integration
remains separate.

Fresh Linux formatting/all-target Clippy, the focused control, native MSVC release
control/verifier, complete 326-input matching and exact appended-patch replay pass.
Only test hooks, a target getter and the private research helper change; non-test
runtime logic is unchanged. Earlier workspace/browser evidence is historical
coverage, not a fresh pass for this instrumented test build. Diagnostic clocks
are excluded from speed inference; reservations are not RSS. Full source,
plans, binaries, errors/backtraces and logs remain under private
`scratch/prob-shuffle-late-owner-20261105T0354/` in both checkouts. No production,
execution graph, default or Auto changes or archive upload are claimed.
