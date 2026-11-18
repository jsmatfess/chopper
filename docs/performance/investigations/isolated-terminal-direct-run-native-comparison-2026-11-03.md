## Isolated terminal direct Run: native comparison (2026-11-03)

Decision: **retain the unapplied terminal-output prototype for persistent-browser
and further acceptance evaluation; no production promotion**. The
[paired native record](../../evidence-originals.md#sha256-83df964f8ee42773a8699d65945f207b21309b292a81993362811f138c046bcd) implements
the seam identified by the [source audit](../../performance.md#direct-final-output-cost-audit-2026-11-03).
Both opposite-order pairs preserve exact outputs and remove the predicted encoded
snapshot traffic. Small favorable timing differences in this development case do
not establish a generally faster policy.

The [prototype patch](../../benchmarks/terminal-direct-prototype-2026-11-03.patch) is
applied only in isolated source. Eligibility is seeded Run, plain output, explicit
one worker and exactly partition -> probabilistic assignment. It leaves all other
Run jobs, explicit Prepare and flexible snapshot replay on their existing paths.
A distinct internal result returns either Prepared or admitted direct publication;
there is no dummy snapshot. The shared PlanWriter retains exact CSV caps, lineage,
order and empty allocations. An immutable admitted Header clone supplies indexed
partition filenames until publication ends. The larger synchronous result stays
on the stack rather than introducing a separately admitted heap box.

The [common observation patch](../../benchmarks/terminal-direct-traffic-instrument-2026-11-03.patch)
adds the same atomic-counter getter and best-effort stderr write to both builds,
after successful native publication. Its overhead is inside CLI timing. These
are Context DiskFile/DiskReader counters, including metadata and buffered read-ahead;
they exclude source reads, final normal-file output writes and physical device I/O.
Returned Analysis diagnostics retain their original pre-publication boundary.

Both builds are fresh default release Windows/MSVC Rust 1.99.1 artifacts with
frozen sources, vendors and embedded UI, using copies of an existing dependency
cache in separate target roots. Original binaries/caches remain unchanged.
The fixture is the prior 20,000-row narrow events case: four event types,
independent categorical/numeric-looking text, partition -> 80/20 allocation,
no child shuffle or final caps. Each job has 64 MiB, one worker and a 32-MiB shared
ceiling. This development case spends none of the reserved performance holdouts.

| Opposite-order native pair | Prepared baseline seconds | Direct candidate seconds | Candidate minus baseline |
| --- | ---: | ---: | ---: |
| Baseline then candidate | 0.255595 | 0.250796 | -0.004800 |
| Candidate then baseline | 0.135116 | 0.129605 | -0.005511 |

Each cell has two observations. Baseline median/range is 0.195356 /
0.135116..0.255595 seconds; candidate is 0.190200 / 0.129605..0.250796 seconds.
CLI launch-through-Run/publication/result emission is timed; preflight, builds
and independent verification are separate. Cache/load are uncontrolled. The large
between-pair spread and small absolute differences rule out significance, tail,
other-device or general speed claims. Do not pool these with older uninstrumented
or differently rooted measurements.

Both pairs report 1,299,213 fewer temporary read bytes and 1,147,811 fewer written
bytes after publication. Required final CSV output remains 1,148,385 bytes in eight
files. The written reduction is slightly smaller than the payload because metadata
changes; the read reduction includes removed read-ahead and catalog work. Each
candidate removes one reported temporary file. Pre-publication read diagnostics
are identical at 5,429,492 bytes in both cells, demonstrating why those returned
counters alone miss the publication saving. These are logical traffic observations,
not an RSS or physical-I/O census.

All four jobs pass independent exact field/ID, partition/allocation lineage, order,
size/inventory and temporary/staging cleanup checks. Both pairs match exact CSV
bytes/names/lineage and logical Analysis fields, including seed/version, digest,
headers/previews/summaries and stage counts. Native integration controls also cover
indexed/headerless names, UTF-16/BOM, row/byte caps, empty named allocations, late
encoding/file-limit errors, finalization cancellation and a raced destination.
A real admitted competitor during resident emission still permits completion as
rows release their grants; injection at finalization causes typed shared denial
after private output exists, with no input replay/publication and zero remaining
grants. These controls do not prove arbitrary admission-domain inclusion.

Final isolated formatting, workspace/all-target Clippy and full locked workspace
tests pass. Postflight checks 659 native build file identities, exact paired CSV
hashes and six-file layered patch replay. Earlier compile/lint/test-observation
failures remain separate: private Reservation visibility, stack enum size,
progress updates mistaken for scans, a mid-emission denial assumption, and helper
placement. A baseline-only formatting control reports one extra blank line in the
observational helper; its tested source/binary provenance stays unchanged, while
the layered candidate replay is formatted. No failed complete-job measurement is
omitted.

Raw manifests, sources, targets, tested artifacts and all logs remain private in
`scratch/todo-unattended-20261103/terminal-*` on WSL and
`scratch/todo-unattended-20261103-terminal/` in the Windows checkout. A transparent
planning amendment extended the task-chosen study cap to twenty cumulative Runs
and two candidate revisions under the continuing TODO authorization; the original
08:27:43 start, 10:27:43 UTC deadline and 20-GiB envelope were not reset. Sixteen
measured Runs are now charged including prior attempts. No upload, deletion,
deployment, browser acceptance or production selector/default change is claimed.
