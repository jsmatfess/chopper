## Terminal direct output: Chrome and working-set transfer (2026-11-03)

Decision: **retain the unapplied prototype as scoped I/O evidence; withhold general
activation and stop this elapsed-time panel**. The
[browser/working-set record](../../evidence-originals.md#sha256-5c353ffd5b943bf86aa53a990f4033a1789bec23b8f754f2ba80a97e4d76103c)
extends the [native study](../../performance.md#isolated-terminal-direct-run-native-comparison-2026-11-03)
without changing its algorithm, production code or defaults.

Fresh default WASI packages use the same frozen baseline/candidate sources and
SDK 33. Installed Chrome 156.0.8078.48 runs fresh persistent profiles with an
OPFS-backed picker. A second, fixed 200,000-row events case uses the same addressed
generator, schema, seed, four event types and resources. Its 11,673,222-byte input
fits the existing 16-MiB verifier/driver ceiling. No reserved correlated-width,
late-key/fanout or sorted-tie performance holdout is consumed.

| Separate panel / pair order | Baseline seconds | Direct seconds | Direct minus baseline |
| --- | ---: | ---: | ---: |
| Chrome 20k; baseline then direct | 0.302940 | 0.296590 | -0.006350 |
| Chrome 20k; direct then baseline | 0.292140 | 0.293485 | +0.001345 |
| Native 200k; baseline then direct | 0.491130 | 0.481927 | -0.009203 |
| Native 200k; direct then baseline | 0.489631 | 0.474196 | -0.015434 |
| Chrome 200k; baseline then direct | 1.105580 | 1.095625 | -0.009955 |
| Chrome 200k; direct then baseline | 1.108460 | 1.107185 | -0.001275 |

Each cell has two observations; the record retains medians and ranges. Native
clocks include CLI launch through publication/result emission. Browser clocks
cover Run-direct through completed export; setup, extraction, verification and an
additional workspace-cleanup assertion are outside that clock. Cache/load are
uncontrolled. The small Chrome effects and mixed 20k signs do not support a stable
speedup, tails, a device rule or pooling across runtimes/working sets.

The 20k Chrome cells remove 1,172,966 engine temporary read bytes and 1,147,811
written bytes. At 200k, native removes 11,836,003 read bytes and Chrome removes
11,696,688; both remove 11,673,039 written bytes. Required final CSV bytes remain
1,148,385 and 11,673,614 respectively, in eight files. These post-engine-publication
Context counters include metadata/read-ahead, exclude source reads and final
normal-file writes, and do not count browser external export or physical I/O.
Different backend read-ahead explains why runtime counters need separate strata.

The larger case crosses an observed plan boundary: resident sorts change from one
to zero and routed groupings from four to five in both plans. Nominal job memory
remains 64 MiB/one worker; native shared admission is 32 MiB and WASI is 128 MiB.
This is a bounded working-set check, not a general full-scale certification.

Charged temporary peaks also fall: native 200k is 44,150,137 versus 34,141,695
bytes, and Chrome 200k is 44,088,020 versus 34,141,695. **These are not complete
owned-filesystem peaks.** The retained direct target creates private final files
while the materialized parent is still live; ordinary prepared publication starts
later. Moving bytes out of charged intermediates can change temp-budget feasibility
without proving lower combined temp/staging/output space. Do not add independent
peaks or infer physical free-space/RSS guarantees. This shifted overlap is the
next specific storage question before a promotion proposal.

All twelve new measured jobs pass exact fields/IDs/order, native CSV/name/lineage
parity, logical Analysis checks and cleanup. Browser exports have valid completion
markers and zero remaining engine workspaces. Cross-runtime metadata verification
requires the exact established browser-only non-atomic-export warning in addition
to native warnings; it does not ignore arbitrary warnings. Within each pair all
logical Analysis fields, including warnings, match.

The first 20k baseline passed CSV/native parity but its metadata verifier rejected
that documented warning. Its original batch remains failed. A fresh verifier
checked the warning rule and reused the valid timed baseline, then launched the
previously unstarted candidate. The first pair was interrupted by that repair;
it is not an uninterrupted alternating control. No timed observation was repeated
or silently discarded to fix the verifier.

Both packages pass the 35 standard contracts plus two targeted terminal contracts
(indexed/headerless names, caps, empty allocations, UTF-16/BOM bytes and late encoding
cleanup). Candidate bridge, peer cleanup, temporary/persistent interruption,
persistent process-kill and direct recovery pass, as do base and shuffle-partition
resource reactors. Default seven-asset, test-free packages are rebuilt and checked
after those test builds; shared UI/worker hashes match. Browser input/output pickers
are controlled, not actual dialog/native File System Access throughput acceptance.

Raw build/SDK/dependency identities, sources, reports, profiles and output remain
private under `scratch/todo-unattended-20261103-terminal-browser/` and
`scratch/todo-unattended-20261103-terminal-scale/` in Windows, with WSL operational
records under `scratch/todo-unattended-20261103/`. Native historical identities stay
unchanged. Planning amendments preserve the original start, launch cutoff, deadline
and 20-GiB envelope. Totals are 28 actual measured attempts and 29 conservative
admissions, retaining one never-launched reservation. No old controller was resumed,
and no upload, deletion, deployment or production promotion is claimed.
