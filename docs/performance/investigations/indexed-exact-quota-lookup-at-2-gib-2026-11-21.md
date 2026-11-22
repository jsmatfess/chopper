## Indexed exact quota lookup at 2 GiB (2026-11-21)

Keep `experimental-exact-quota-index` as a Linux opt-in. In the
standalone exact-assignment job with 1,000 destinations, the indexed
cursor cuts median elapsed from 44.76 to 41.56 seconds. Two of three
matched pairs improve. Process CPU falls 5.2% and both directions of
temporary traffic are identical.
[Matched observations and validation](../../benchmarks/indexed-exact-quota-lookup-2026-11-21.json)

| Complete-job median | Linear scan | In-place quota index |
| --- | ---: | ---: |
| Elapsed | 44.762 s | 41.555 s |
| Process CPU | 19.66 s | 18.64 s |
| Peak RSS | 50,480 KiB | 50,444 KiB |
| Peak tracked reservations | 33,935,509 bytes | 33,935,580 bytes |
| Managed temporary reads | 9,300,047,442 bytes | 9,300,047,442 bytes |
| Managed temporary writes | 9,284,884,424 bytes | 9,284,884,424 bytes |
| Temporary files created | 104 | 104 |

The 2 GiB fixture contains 8,388,608 rows. Exactly 608 destinations
receive 8,389 rows and the remaining 392 receive 8,388. One worker
uses a 128 MiB engine setting, 256 MiB shared ledger and a hard 1 GiB
Linux/WSL2 cgroup without swap. The same optimized executable and
private seed compare both cursors through native publication. Input
setup, process startup and verification are outside elapsed. Run
order alternates and backing cache state is uncontrolled. The
median elapsed difference is 7.16%, with no calibrated crossover
or generalized throughput estimate.

For groups of 32 or more, the cursor builds a Fenwick tree in the
admitted quota array. The same bounded draw selects the same group,
then the cursor decrements that group across the ancestor counts.
This reduces the group lookup from a linear scan to logarithmic
traversal without a second quota allocation. Smaller lists use the
flat scan. Existing quota calculation, random streams, row routing
and serialized output limits keep their contracts.

Differential tests check sparse and uneven weights, non-power-of-two
lengths, all draws for a small exhausted sequence and an unsigned
maximum total. Small complete pairs cover eight groups, 1,000 groups,
and 1,000 groups across seven strata. Every large pair passes
independent complete field, ID, encounter order, quota and encoded
cap checks. Logical Analysis, ordered manifest output records and
CSV hashes are exact within each pair. The 32-group cutoff is an
experiment bound selected to preserve the small flat path.
