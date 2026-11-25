## Standalone Uniform direct publication (2026-11-25)

The shipped Linux terminal merge saved time on an 8 GiB Uniform Shuffle
followed by Balanced. This follow-up tests standalone explicit Uniform
Shuffle. It also separates the larger merge from the removal of the final
encoded snapshot.
[Issue #20](https://github.com/jsmatfess/chopper/issues/20) ·
[Related shipped comparison](automatic-native-execution-bounds-2026-11-22.md) ·
[Samples and receipt identities](../../benchmarks/standalone-uniform-publication-summary-2026-11-25.json)

### Complete verified 8 GiB jobs

The fixture has 16,777,216 rows of 512 bytes, eight key values and
8,589,934,607 input bytes. Both release executables use the same native
Linux WSL2 ext4 storage, explicit 256 MiB working memory, one worker,
Auto grouping, a 128 KiB record ceiling, an eight-file ceiling and a
strict 1,200 MiB CSV byte cap. Each complete Run publishes seven CSVs
and its manifest and clears the managed temporary workspace. Independent
verification checks each original ID and field, nonidentity order,
singleton stage and empty lineage, actual serialized sizes, inventory,
manifest and cleanup. The clock runs from CLI launch through
publication, cleanup and exit. Input generation and verification are
outside the clock.

The wide challenger combines direct terminal publication and a
256-reader ceiling. All three alternating pairs favor it. The median
paired saving is 12.079 seconds, with a range of 9.231–12.321 seconds.

| Complete Run metric | Snapshot | Wide merge and direct publication |
| --- | ---: | ---: |
| Wall seconds, median [min–max] | 56.869 [56.413–62.829] | 47.637 [44.092–50.750] |
| Process CPU seconds, median | 51.73 | 41.62 |
| Initial runs / merge operations | 164 / 3 | 164 / 1 |
| Managed temporary reads, bytes | 25,976,805,129 | 9,747,563,595 |
| Managed temporary writes, bytes | 25,976,802,147 | 9,747,563,595 |
| Peak workspace reservations, bytes | 67,397,514 | 67,427,852 |
| Peak temporary files | 68 | 167 |

The timing cohort uses ordinary host headroom and uncontrolled warm
cache. The first baseline attempt under a hard 1 GiB Linux cgroup with
swap disabled stopped on a shared admission denial before publication
and cleaned up. Its receipt is separate from the timing pairs. Managed
temporary counters cover spill and snapshot traffic. RSS, working
reservations and physical device I/O have separate scopes.

### Late shared admission

A Linux component control generates 96 tiny sorted spill runs at
fixed 256 MiB job and 512 MiB shared capacity. Just after both final
cursors are prepared, each arm admits the same 530,512,996-byte peer
request. The snapshot cursor holds 2,174,330 tracked bytes at that
boundary and the widened cursor holds 6,325,148. The snapshot arm
encodes all 96 rows. The wide arm returns a typed shared-memory error
during encoding. The peer grant remains live and both arms verify
temporary and staging cleanup.

A separate control keeps the existing merge width and uses direct
publication. It holds 2,174,330 bytes at cursor preparation and encodes
all 96 rows under that same peer request. Retain the existing merge
hierarchy for this standalone path. The synthetic control isolates
the cursor and writer overlap. Complete-job timings and native
publication are covered by their own receipts.

### Direct publication with the existing merge width

The second screen changes only the retained publication route and stops
after the reversed pair under its declared timing rule.

| Pair order | Snapshot, s | Direct, s | Seconds saved |
| --- | ---: | ---: | ---: |
| Snapshot then direct | 53.904 | 50.052 | 3.852 |
| Direct then snapshot | 53.804 | 54.154 | −0.349 |

Each arm creates 164 initial runs, performs three merges and reaches a
peak fan-in of 64. Direct publication saves about 8.59 GB each of managed
temporary reads and writes. Process CPU falls from 48.10–48.14 seconds
to 43.29–44.01 seconds. The median paired elapsed saving is 1.751
seconds, below the three-second gate. The second pair also misses the
all-pairs rule. Both arms complete with independently verified output
and cleanup. Keep the existing standalone snapshot policy. A future
default needs repeatable wall-time savings and a matched admission
control through final encoding.

### Replay

Use the feature-free native CLI from
`61c488d04a41dff4696e3bf0bc02dc4371f541d8`. The wide snapshot changes
`native_terminal_merge` in [the Auto selector](../../../crates/chopper/src/engine/auto.rs)
to also admit a single explicit Uniform operation with plain UTF-8
input and output at an explicit 256 MiB. Keep the existing size,
worker, grouping, descriptor and shared-headroom checks. Keep the
96 MiB merge tier for Uniform followed by Balanced. The direct-only
snapshot applies the same standalone criteria through
[`RetainedPublication::PrivateTerminal`](../../../crates/chopper/src/engine/run_route.rs)
with the ordinary fan-in. For direct-only selection, the existing
64-way sorter supplies the descriptor bound.

Use the fixture and complete Run helpers in
[`benchmark-auto-contention.py`](../../../scripts/benchmark-auto-contention.py).
Build separate release snapshots and select only Uniform from the
`terminal-wide` workload. Use a 32 GiB managed temporary cap, verify
the seven standalone chunks and keep publication verification outside
the clock. The independent verifier preserves each identifier's eight
digits, each key's four digits, each payload and the full manifest
inventory. The summary pins the input, executable, harness, per-attempt
and workspace-control receipt identities. Each CLI Run draws its own
permutation.
