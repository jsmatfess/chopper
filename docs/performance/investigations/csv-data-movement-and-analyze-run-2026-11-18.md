## CSV data movement and Analyze Run (2026-11-18)

This implements the owner-authorized Analyze/Run simplification in issue #28 and
screens three data-movement hypotheses from the cross-tool comparison. These are
new matched experiments, not extra repetitions of the earlier DuckDB/qsv cells.

### Interface and execution changes

Analyze returns bounded full-file input statistics and pipeline estimates without
applying the output pipeline, creating output CSVs or retaining an executable
result. Run always accepts the current configuration and validates the input it
consumes independently. The hosted Prepare action, prepared-result state and
execute-after-approval request/ABI are removed. CLI Analyze replaces the old exact
planning behavior; its former Profile command is removed. CLI Run's ordinary
pre-execution path confirmation remains (`--yes` for noninteractive use).

Internal engine snapshot construction remains for unsupported Run pipelines and
explicit engine/test consumers. Its exact bytes, strict caps and admission owners
are preserved. Removal of the hosted approval feature therefore does not imply
that every Run avoids a snapshot.

Fisher–Yates followed immediately by Balanced now passes the realized resident
permutation directly through the existing balanced traversal, both at root and
after a retained parent. It avoids an intermediate Dataset write/read without
changing the permutation, quotas, downstream ordering or original stage indices.
It does not add a resident/external selector or revisit rejected adaptive FY.

Single-step, uncompressed Balanced Run uses grouped private direct publication.
It retains its input Dataset to establish exact group sizes, and removes only the
encoded output snapshot and subsequent copy. All other nonempty pipelines keep
the snapshot path. Header-aware naming shares admitted immutable header payloads;
output names/metadata, serialization, Analysis and staging retain existing grants.
There is no admission-error retry of raw input. Native atomic no-replacement
commit and browser export/completion-marker lifetimes remain distinct.

### Experiment design

The unchanged baseline binary was copied only after its SHA-256 and all source
hashes matched the earlier cross-tool provenance. The FY-only and terminal-direct
binaries are separately pinned with dirty-source manifests, vendor inputs, patch
snapshots and harness hashes. The terminal candidate includes the FY change,
which cannot match the single-Balanced workloads. One worker for FY; one, automatic (resolved four) or eight for plain Balanced. Plain UTF-8 CSV,
warm uncontrolled WSL2/ext4, Ryzen 5800X, 62 GiB host RAM. No native Windows timing,
cold-cache or physical-device throughput claim follows.

Each cell has an excluded warmup per binary and three alternating complete-job
pairs, except the small plain-Balanced confirmation which has five pairs. The clock includes launch, validation/digesting, all intermediate/output
writes, native publication and product cleanup. Fixture generation, independent
verification and successful output deletion are outside the clock. Report median
and min/max; three repetitions do not establish tail latency or confidence bounds.
Every output field, unique ID, parent membership, balanced quota, lineage, output
order where deterministic, byte/row cap and manifest count is checked independently.
Quoting, Unicode, embedded newlines and nondivisible counts are included; wide
fixtures have 33 columns and a late 768 KiB field.

The approximately 2 GiB fixture (1,986.26 MiB) exceeds the 256 MiB configured working budget, not host RAM.
Reservations are not an RSS cap. GNU-time process CPU/RSS/filesystem counters,
logical spool traffic and returned Analysis temporary counters have different
scopes; none is substituted for physical-device I/O.

### Complete Run results

Elapsed seconds are median [minimum–maximum]. Positive percentages mean lower
elapsed time, with each cell’s baseline as denominator. The rows are separate
populations and are not pooled.

| Workload | Input MiB | Workers | Pairs | Baseline seconds | Candidate seconds | Elapsed reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FY → Balanced, root | 123.60 | 1 | 3 | 0.871 [0.845–0.978] | 0.767 [0.759–0.767] | 11.99% |
| Balanced(4) → FY → Balanced(8) | 123.60 | 1 | 3 | 1.013 [1.013–1.032] | 0.901 [0.900–0.906] | 11.08% |
| FY → Balanced, 33 columns | 66.96 | 1 | 3 | 0.853 [0.849–0.875] | 0.673 [0.668–0.685] | 21.00% |
| Uniform → Balanced, unchanged control | 123.60 | 1 | 3 | 0.811 [0.802–0.811] | 0.796 [0.795–0.810] | 1.85% |
| Balanced, small confirmation | 123.60 | 1 | 5 | 0.495 [0.491–0.503] | 0.448 [0.438–0.464] | 9.51% |
| Balanced, large | 1986.26 | 1 | 3 | 9.218 [9.135–9.334] | 7.936 [7.690–8.049] | 13.91% |
| Balanced, 33 columns | 66.96 | 1 | 3 | 0.601 [0.600–0.602] | 0.589 [0.588–0.589] | 1.98% |
| Balanced, automatic workers | 123.60 | 4 | 3 | 0.501 [0.456–0.507] | 0.466 [0.440–0.499] | 7.04% |
| Balanced, large / 8 workers | 1986.26 | 8 | 3 | 9.462 [8.195–9.554] | 8.124 [8.072–8.193] | 14.14% |

The FY primary cells meet the predeclared ≥10% median gate with every paired
sign favorable; the additional wide shape improves 21%. The unchanged Uniform
control has overlapping elapsed ranges and is near neutral, not a new speedup.
Plain Balanced meets its ≥5% primary small/large gate with all primary paired
signs favorable. Its wide-row gain is only about 2%; automatic workers have
overlapping ranges and one reversed pair (−2.04%), so the 7% median is a scoped
observation rather than a precision claim. No worker control has a material
median regression. No cost-based selector or broader terminal eligibility is added.

The small-cell confirmation follows a mixed three-pair result: its median was
10.00% lower, but paired changes were +10.20%, −9.52% and +10.13%. A separately
frozen, one-time five-pair confirmation required all five signs favorable and a
≥5% median gain, with no further retries on failure. It achieved 9.51%, with
paired reductions from 7.66% to 12.04%. The first three-pair screen (9.61%) and
the mixed cohort remain reported separately; they are not pooled or silently
discarded as timing outliers.

An initial large attempt was manually interrupted because the generic verifier
spent most of its time hashing per-row JSON metadata and assumed one worker.
The replacement streaming verifier checks every field and exact consecutive ID
sequence, which proves conservation, parent membership and encounter order with
constant auxiliary space. Negative controls reject reordered multiline records,
incorrect worker metadata, cap violations, unsafe paths and unlisted files.
Its verification remains outside the clock. A subsequent orchestrator received
SIGTERM before sealing a completed large cell. That unsealed cell and its runner
lock remain retained, and its observations are excluded from adoption. A fresh
bounded large batch completed and sealed its measurement and verification steps.

### Removed traffic and retained requirements

Single plain Balanced avoids one encoded payload write and its later read:
approximately 247 MiB of logical payload traffic for the small fixture and
3.88 GiB for the large fixture, plus small catalog effects. GNU-time `%O`
filesystem output counts fall about 31.1% in both large worker settings and
the small cells. Wide rows show about 25.6% fewer filesystem output counts
but only 2% less elapsed time, indicating that removing traffic is insufficient
to explain or solve all row-shape costs. These are filesystem accounting and
logical-traffic observations, not physical-device bandwidth measurements.

Large single-worker peak RSS is about 5.75 MiB baseline and 5.73 MiB candidate;
eight-worker values are about 5.73/5.67 MiB. The change retains bounded accounting
and does not promise a lower RSS cap or lower total peak filesystem footprint:
private output can overlap the retained input Dataset earlier. Returned Analysis
temporary counters are not whole-job filesystem traffic.

Exact balanced membership/remainders, strict decoded CSV/UTF-8 validation,
serialized byte/row caps, logical digesting, admitted ownership, atomic native
publication and hosted completion-marker verification remain. The earlier
[requirements cost table](cross-tool-csv-split-and-shuffle-comparison-2026-11-18.md#requirements-avoidable-costs-and-rough-impact)
estimates digest work at roughly 0.0665 s per 128 MiB and 1.064 s per 2 GiB
(component measurements, roughly 8–13% of those earlier Chopper times).
Individual strict-validation/admission costs remain unisolated. Exact remainder
arithmetic itself is negligible; qsv’s ceil-sized chunks are a semantic difference
and do not justify a large balancing tax. Atomic publication does not inherently
require the extra encoded snapshot copy. The observed terminal-path gains include
associated buffering/metadata differences and are not a pure device-I/O ablation.

Analyze no longer computes an exact final output snapshot or guarantees its
counts/caps before execution. It returns clearly labeled input observations and
pipeline estimates. Run reports the exact result after successful validation
and publication, and can reject a cap or feasibility constraint during processing.
This is the owner-requested feature tradeoff, not relaxed execution validation.

### Digest screen rejected

Removing the compact-record batching copy and feeding each encoded record directly
into BLAKE3 roughly doubled the digest-only probe time: 0.0665 to 0.1372 seconds
for 524,288 rows, and 1.0727 to 2.1974 seconds for 8,388,608 rows (medians).
These component timings establish rejection of that implementation, not a
whole-job regression or potential whole-job speedup. The existing batched digest
is unchanged. Rejected radix/bucket/copied-parallel-parser/adaptive-FY experiments
remain rejected; upstream algorithm names alone do not satisfy reopen criteria.

### Correctness, delivery and remaining scope

Implemented in this unmerged worktree’s default native/WASI build; no release,
merge or deployment is asserted. Linux workspace/default and all-feature tests,
Clippy and formatting passed. Native Windows workspace tests passed in a fresh
NTFS validation clone with complete source/vendor identity, leaving the existing
checkout intact. Final CLI ownership/interface/automatic-memory checks passed
again on Linux and Windows after correcting source-before-grant destruction.
The all-feature terminal competing-owner control and Clippy passed on final source.

The hosted UI unit and workspace tests passed. Bundled Chromium 156 passed the
full processing/graph/lifecycle/inspection/theme/motion/value-share/bounds/bridge,
cleanup and interruption sequence, including persistent-session restart and forced
process-kill variants. Both WASI resource-contract variants passed, including the
experimental shuffle/partition resource suite. Default production artifacts were
restored. After the final CLI-only teardown correction changed rebuilt WASM bytes,
core hosted and full graph acceptance were rerun against the final default bytes;
the final receipt records before/after asset hashes. This is small-fixture
correctness coverage, not Windows/browser throughput or arbitrary scale acceptance.

The new tests cover exact realized FY permutation cuts and downstream ranges,
root/retained parents, quoted Unicode/multiline data, stages, caps, insufficient
rows, resident denial, late output/encoding failure, cancellation, destination
races, native private/temp cleanup and final competing-owner denial/cancellation.
Analyze/Run tests cover current source/configuration edits, obsolete protocol
rejection, independent/repeated Runs, permission waits and marker/export cleanup.

The [compact summary](../../benchmarks/data-movement-summary-2026-11-18.json)
contains exact source pointers/hashes, paired samples, medians/ranges, resource
settings, process counters and exclusions. The local ignored
provenance packet (local `data-movement-provenance-2026-11-18.json`)
retains full crate/vendor manifests, patch/harness snapshots, fixtures, per-job
receipts, component diagnostics, Windows source identities, validation logs and
failed/interrupted attempts. Successful synthetic output payloads were independently
verified and removed after timing; their names/bytes/hashes remain in receipts.

This advances the data-movement proposal in the
[cross-tool investigation](cross-tool-csv-split-and-shuffle-comparison-2026-11-18.md)
and implements [#28](https://github.com/jsmatfess/chopper/issues/28).
[#19](https://github.com/jsmatfess/chopper/issues/19) retains broader terminal
pipeline/codec eligibility; [#20](https://github.com/jsmatfess/chopper/issues/20)
owns the remaining workload-led execution investigation. The next useful work is
an admitted batching/row-traversal candidate justified by current CPU measurements,
with the same complete-job and ownership/publication gates. Existing rejected
radix/bucket/copied-parser/adaptive-FY work is not reopened unchanged.

No 40 GiB/physical-RAM-exhaustion, cold-cache, durability or physical-drive result
has been reproduced. New fixtures differ from the earlier four-column cross-tool
inputs, so these gains do not establish a new DuckDB/qsv ranking. Performance is
qualified only on the recorded warm WSL2 workloads. Historical archive hydration
still rejects a duplicate-member TAR bundle; complete evidence-index regeneration
remains blocked by missing historical originals. New evidence and failed refresh
attempts are preserved without weakening the archive validator.
