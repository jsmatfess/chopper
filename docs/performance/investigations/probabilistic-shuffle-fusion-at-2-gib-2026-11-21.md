## Probabilistic shuffle fusion at 2 GiB (2026-11-21)

Keep the prepared-spill fusion as a Linux opt-in for plain
Partition → probabilistic assignment → explicit Uniform. Across three
paired 2 GiB jobs under a hard 1 GiB cgroup without swap, median elapsed
fell from 51.25 to 41.82 seconds. Both directions of managed temporary
traffic fell 32.21%. The original stages and fusion published exact
seeded output in every pair. [Raw observations and identities](../../benchmarks/probabilistic-shuffle-fusion-2gib-2026-11-21.json)

| Complete-job median | Original stages | Prepared-spill fusion |
| --- | ---: | ---: |
| Elapsed | 51.247 s | 41.819 s |
| CPU | 25.60 s | 22.65 s |
| Process peak RSS | 45,104 KiB | 44,392 KiB |
| Peak shared reservations | 34,039,369 bytes | 34,039,360 bytes |
| Managed temporary reads | 15,628,611,086 bytes | 10,595,238,098 bytes |
| Managed temporary writes | 15,627,987,234 bytes | 10,594,820,902 bytes |
| Temporary files created | 118 | 136 |
| Initial runs | 100 | 128 |
| Merge operations | 8 | 4 |

The fixture has 8,388,608 rows, four partition parents, and stratified 80/20/0
probabilistic assignment. Jobs use one worker, a 128 MiB engine setting, a
256 MiB shared ledger, and strict row and byte caps. All three pairs improved.
Elapsed spans the optimized engine API through publication with fixture setup,
startup and correctness checks outside the clock. Backing cache state was
uncontrolled. Independent verification covers every ID and field, partition
membership, file inventory and caps. Ordered records, named empty children,
CSV hashes and logical Analysis match within all pairs. The retained candidate
trades higher run and file counts for fewer passes and merges.

The sort preserves original parent probabilistic membership and per-child
Uniform domains. Each tentative parent owns a real 64 KiB spill writer before
accumulation. Typed memory denial during preparation drops the tentative
owners and runs the original assignment and child shuffle on that retained
parent once, after cancellation and cleanup checks. A rejecting sink
establishes terminal handling after the first emitted row. Observed spill
facts map original operations 2 and 3. Membership facts map operation 2.
A separate 70,003-row test checks actual draws and shuffle keys using the
original RNG and domain framing.

Three held-peer pairs request exactly 24, 28 or 30 MiB in the same 32 MiB
ledger at operation 2 entry. The original jobs return typed shared denials
while preparing operation 3. Fusion completes at all three points with
the same grants held, exact verified output and zero retries. Separate
injections verify successful pre-emission retry and cancellation when the
writer admission denies. Both paths clean all owned output and reservations.
These synchronized controls establish three specific completion points.
Native Linux qualification of the integrated variant and earlier scoped
Windows and Chrome prototype evidence remain separate.
[Earlier actual prepared writer controls](probabilistic-shuffle-fusion-prepared-spill-owner-control-2026-11-05.md)

The first all-feature build enlarged every sorter's fixed allocation by
holding both spill and router owners inline. Four existing tiny-budget
controls failed. The final implementation uses a single slot for the
mutually exclusive owners. A size guard and all four original controls
pass at the original limits. In a separately pinned 2 GiB transfer pair
using the corrected layout, elapsed falls from 49.44 to 36.70 seconds.
Temporary reads and writes retain the 32.21% reduction and exact output
matches. This pair stays separate from the three-pair median above.
