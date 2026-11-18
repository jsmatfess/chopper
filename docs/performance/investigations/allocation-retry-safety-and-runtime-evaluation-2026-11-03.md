## Allocation retry safety and runtime evaluation (2026-11-03)

Decision: **retain the materialized-parent retry candidate for targeted broader
workload evaluation, with no production or selector promotion**. The
[derived record](../../benchmarks/allocation-retry-evaluation-2026-11-03.json) extends the
[earlier native fitting result](../../performance.md#materialized-parent-allocation-retry-2026-11-03)
with shared-admission and emission-boundary controls, observed complete-job retry
costs and measurements of the candidate in persistent Chrome. It does not establish
an admission-domain inclusion proof or a generally calibrated execution rule.

The algorithm remains the original unapplied patch. Fresh isolated snapshots use
source base `41333789ca73f14f946438c5de0587146f896c2b`; a native-only stderr marker
identifies each actual retry and its overhead stays in native timing. An identical
study-only module/bin in the two pressured builds invokes public engine Run and
uses the existing admitted Reservation implementation. These additions provide
observation and pressure injection; no candidate algorithm revision was made.
Native runs use Windows/MSVC Rust 1.99.1; WASI builds use SDK 33 and Node
22.23.4 on the same host. The record includes a post-run CPU/memory/filesystem
snapshot, without physical-device or cache attribution.
Retained baseline builds are reused with their original provenance and matching
artifact hashes after byte comparisons of 325 native and 359 browser source/driver
files. Fresh builds cover both vendors and applicable native UI, SDK and hosted
assets. Old binaries, attempts and terminal controllers remain intact.

All measured cases use the same 3,002,728-byte, 20,000-row `entity-list-v1` fixture:
eight possible regions, a 30% hot-region draw, independent 24..128-byte
notes, and region partition -> probabilistic 80/20 allocation -> child uniform
shuffle. The job requests 64 MiB, one worker and the original seeded-v1 recipe.
These are development cases; reserved correlated-width/skew, late-key/fanout and
sorted-tie performance holdouts remain untouched.

| Separate comparison / pair order | Baseline seconds | Candidate seconds | Candidate minus baseline |
| --- | ---: | ---: | ---: |
| Native CLI, shared 32 MiB; baseline then candidate | 0.234495 | 0.151963 | -0.082533 |
| Native CLI, shared 32 MiB; candidate then baseline | 0.230695 | 0.154265 | -0.076430 |
| Native CLI, shared 2 MiB; baseline then candidate | 0.309976 | 0.336062 | +0.026085 |
| Native API, competing pressure; baseline then candidate | 0.268409 | 0.260351 | -0.008058 |
| Native API, competing pressure; candidate then baseline | 0.254666 | 0.263374 | +0.008708 |
| Persistent Chrome, fitting; baseline then candidate | 0.478835 | 0.399820 | -0.079015 |
| Persistent Chrome, fitting; candidate then baseline | 0.471155 | 0.384320 | -0.086835 |

Each two-pair panel has two observations per cell; the shared-2-MiB panel has one.
Individual values, median/range and exact scope are retained in the record. Native
CLI clocks include process launch through successful Run/publication. The pressure
driver's API clock surrounds Run, including the competing admission/release,
failed optional work, rereads and publication, but excludes process startup,
configuration decoding and caller result serialization. Browser clocks cover
Run-direct through completed OPFS export, excluding setup, host extraction and
independent verification. These populations are not pooled. Cache and host load
are uncontrolled; subsecond differences do not establish significance, tails,
other-workload gains or an Auto threshold.

In both fitting runtimes the candidate removes eight allocation route groups,
4,702,179 engine-reported logical bytes both written and read, and 16 temporary
files per job; resident sorts change from 17 to 25. The elapsed differences favor
the candidate in both opposite-order pairs in each runtime. At shared 2 MiB both
CLI cells succeed, with no observed typed admission retry: the candidate removes
3,295,788 logical bytes each written/read and 14 files while doing additional sort
work. That single slower observation describes a constrained case, not retry cost
or a repeatable regression. A separately retained shared-1-MiB baseline fails
admission during ingestion; its candidate never launches and its failed measured
attempt is excluded from paired comparisons. Cleanup passes.

To measure actual retry, a separate admitted competitor in an 8-MiB pool leaves
600,000 bytes of shared headroom at the allocation-stage callback and releases its
grant before child shuffle. Both candidate API jobs record eight parent retries;
both immediate-routing baselines complete. Each candidate adds 2,097,152 logical
bytes read, 8,868 written and eight temporary files. Failed-attempt traffic is
retained in the counters. Elapsed differences have opposite signs and are
inconclusive. All shared grants return to zero and temporary files are absent at
exit. This is controlled admitted competition, not a measurement of real pressure
frequency, total RSS or physical storage behavior. Logical temporary diagnostics
are snapshots, not a complete publication/export I/O census; shared-pool peaks
include the competitor and cannot be treated as job-only memory.

A diagnostic with the output writer created *after* preparation exposes one
emission denial where immediate routing succeeds. It does not reproduce current
dispatch, whose writer already exists. Repeating all six matched headroom cases
with that production lifetime completes in both cells; two candidate cases retry
before emission. Three local and three genuine shared-pool parent comparisons
retain exact metadata/row-frame parity, including observed recovery. Pre-cancel,
malformed record-limit, first/eighth sink-row denial, sink I/O and sink-finalization
failure each perform one scan with cleanup. Partial output is never replayed.
These scaled controls do not prove arbitrary later pressure or emission admission.

All fourteen successful measured jobs pass independent field/ID/group checks;
all native pairs and every browser job retain exact seeded lineage and CSV bytes
against their reference. Logical Analysis fields, including stage counts, digest,
seed/version, summaries and output sizes, match within all seven pairs. Native
formatting, workspace/all-target Clippy and full locked default workspace checks
pass for the isolated safety and instrumented snapshots; auxiliary pressure
binaries pass their own format/build/Clippy gates. Repository CI checks retained
evidence; it does not compile the unapplied experimental snapshots. Installed Chrome
156.0.8078.48 passes 35 default contracts, bridge/peer cleanup, temporary/persistent
interruption, persistent process-kill/direct recovery and base/shuffle-partition
resource reactors. The final isolated candidate package contains the seven default-
feature, test-free assets. Earlier tested asset copies are retained separately.
The browser destination is an OPFS-backed picker, not native File System Access
throughput or arbitrary browser quota/device-fault coverage.

Postflight verifies 22,138 distinct recorded source/vendor/SDK/harness/fixture/
binary/asset/result identities, using exact retained tested copies for older
browser asset references. Failed command, compilation, preparation, storage-census
race and child-cwd attempts remain separate from successful replacements. The
session uses 15 of 16 permitted measured attempts, including the failed baseline,
within the original two-hour/20-GiB planning envelope and without expanding the
scientific panel. Storage checks sample declared roots; they are not a filesystem
quota or complete transient/RSS peak. Native correctness-test OS temporary roots
were not fully censused. Raw manifests, logs, sources, binaries, profiles and replay
material remain private under `scratch/allocation-retry-evaluation-20261103/` in
the retained Windows checkout, with WSL operational records under the same relative
path. No raw publication, cleanup, new R2 upload or deployment is claimed.

The next useful question is whether the observed pass reduction earns meaningful
whole-job benefit on an independent eligible workload, while accounting for retry
cost and the unresolved post-preparation pressure/emission boundary. These small
cells justify that investigation; they do not justify production activation,
selector tuning, broad success guarantees or an unconditional scale matrix.
