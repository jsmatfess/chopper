## Allocation routing storage audit (2026-11-02)

**Decision: the existing eight-region panel already identifies an additional
serialized temporary pass in allocation routing. Do not repeat its timings or
attribute the elapsed difference to sorting.** The next bounded challenger question
is whether retaining allocation rows while they fit can avoid this pass without
changing membership, order, admission or fallback. This is a development hypothesis,
not a selector, implementation authorization from evidence, or default promotion.

The [derived audit](../../benchmarks/routing-storage-analysis-2026-11-02.json) reuses
exactly the four complete native Windows Runs in `cost-attribution-001` above;
it adds **zero** measured Runs. Each sample references `/elapsed_seconds` in its
`run.json` and the named `/diagnostics` counters in its `run.stdout.log`, with exact
source hashes. Two pairs are retained separately. Logical traffic is cumulative
at returned Analysis, not a separate complete-publication I/O census. Original
whole-job timers include CLI launch through successful Run/publication.

| Counter, identical within each strategy across both pairs | Sort | Auto |
| --- | ---: | ---: |
| Temporary bytes written | 12,095,993 | 16,798,172 |
| Temporary bytes read | 9,788,045 | 14,490,224 |
| Temporary files created | 6 | 22 |
| Routed groupings | 0 | 8 |
| Resident sorts | 25 | 17 |
| Rows sorted | 60,000 | 40,000 |

The auto-minus-sort delta is **4,702,179 bytes written and the same bytes read**,
plus 16 files in each pair. `apply_parent` sends probabilistic allocation through
`StreamingGroups`, whose `Sorter::streaming` immediately installs `Router` under
auto. `Router::push_parts` writes bucket spill files; `finish` flushes them and
`RoutedRows::next_decoded` reopens/reads them before emitting allocation children.
Forced sort retains these allocation rows in memory in this panel. The initial
region grouping also fits: the eight avoided resident sorts correspond to the
eight allocation parents, not a changed region-partition routing path. Neither
strategy reports sort runs, merges, routing fallback or reused routing runs.

The decoded fixture independently predicts the delta exactly. `PackedRow::write`
serializes u64 ID, ordinal, key length, the eight-byte allocation index, and field
count (40 fixed bytes), followed by each field's u64 byte length and UTF-8 payload.
Summing `40 + sum(8 + utf8_length(field))` over the 20,000 source rows gives
4,702,179. Two nonempty allocation buckets in each of eight region parents explain
the 16 extra files. Temporary counters count successful logical file transfers;
this does not measure physical SSD traffic, system calls, RSS or exclusive storage
time. Matching the bytes and source path identifies added work, not the fraction
of elapsed cost caused by that work, file lifecycle, decoding or admission checks.
Auto's sort clocks are smaller (.0035008/.0038775 versus .0052915/.0050493 seconds);
these nested clocks cannot explain the complete-job regression causally.

Before interpretation, a fresh native validation-runner audit rehashed every
recorded build and both batch inputs/artifacts, reran the independent verifier
on all four outputs, and checked algorithm version, ordered lineage and exact CSV
hash parity within each pair. Current owning source files match the recorded
build inputs. This rechecks conserved fields/IDs, group metadata and sizes; the
verifier is not an independent seeded membership oracle or a uniformity proof.
Cache/host load remain uncontrolled; no cross-build, browser or scale inference
is made. Raw historical bytes and the terminal controller remain untouched.

The audit manifest/self-review and full logs are retained in the same Windows
checkout under `scratch/routing-storage-20261102-attempt2/`, with its passing
`batch/status.json` and `analysis.json`. Estimate: 30 seconds/10 MiB; deadlines:
120-second command/180-second batch within session deadline 2026-11-03 00:17 UTC.
This analysis uses the native runner; the controller/cycle require measurement
steps and the original controller is terminal, so no fake measurement or
unsupported runtime was introduced. The first audit attempt at
`scratch/routing-storage-20261102/` failed because its parity call used a helper
requiring a browser completion marker for native output; it is preserved with
its script, manifest and traceback. The separately declared second attempt uses
native signatures after native verification. No engine execution was retried.

Browser prerequisites remain unresolved: the old persistent-context launch error
and copied-manifest artifact-path failure have no original trees in this checkout.
A supported browser controller is also absent. No browser measurements were
attempted or inferred from this audit. Before any browser follow-up, locate those
originals, verify native Node/Chromium/SDK/build identities and regenerate a plan
with output paths owned by its fresh directory; do not copy and resume the failed
manifest. Local raw records remain pending private archival selection, with no
upload, publication or cleanup in this investigation.
