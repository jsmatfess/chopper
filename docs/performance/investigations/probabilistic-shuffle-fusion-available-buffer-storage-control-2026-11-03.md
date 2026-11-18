## Probabilistic shuffle fusion: available-buffer storage control (2026-11-03)

**Decision: retain a storage-only revision for further evaluation.** The
[fixed control](../../benchmarks/probabilistic-shuffle-available-buffer-2026-11-03.json)
and [replay patch](../../benchmarks/probabilistic-shuffle-available-buffer-2026-11-03.patch)
restore completion at the preceding live-owner counterexample on Linux and
native Windows. Production remains unchanged. The original candidate's failure
is preserved; this result covers a different, isolated storage variant.

The variant adds an alternative Sorter constructor used only by fused
probabilistic allocation/shuffle. It caps the original buffer target at half the
observed minimum of local and shared remaining admission capacity. This leaves
room for spill construction in this case. Observing capacity acquires no grant;
all allocations retain ordinary admission. The observations are separate reads,
so the target does not guarantee capacity against later competing owners.
Existing default construction and dispatch remain unchanged.

The fixed point is unchanged: 20,000 probe-v1 rows, one R0 partition parent,
50/50/0 probabilistic allocation followed by uniform shuffle, 32-MiB job/pool,
one worker and 1,024-row/65,536-byte output caps. An independent 28-MiB grant is
acquired after root materialization at `Preparing operation 2 of 3` and held
through completion. Both runtimes now complete both variants. Independent
fields/unique IDs/groups/caps, exact CSV/output records and 17 logical Analysis
fields pass. Each job visits its input once, cleans owned temporary/private
staging files, retains only the competitor after destruction, then releases the
pool to zero. All 326 declared source/vendor/embedded-asset inputs match between
the Linux and Windows snapshots.

The storage tradeoff is explicit. Baseline versus revised candidate counters
match across both runtimes:

| Counter | Prepared baseline | Revised fusion |
| --- | ---: | ---: |
| Logical temporary bytes read | 10,759,791 | 8,759,642 |
| Logical temporary bytes written | 10,694,803 | 8,757,358 |
| Temporary files created | 8 | 7 |
| External sort runs / merges | 0 / 0 | 3 / 1 |

One additional Linux fitting pair uses the original four-region, 80/20/0 case
without a competing grant. Exact output and cleanup pass. It retains the earlier
logical traffic: read 11,502,681 versus 5,346,652 bytes; written 10,697,389 versus
4,741,736 bytes, with no external runs in either variant. These are complete-job
logical counters, not physical device traffic. API/test clocks are retained but
excluded from performance inference; no timing panel or capacity sweep ran.

A small target contract checks the nominal cap, shrinking shared headroom,
observation without reservation and release to zero. New Linux formatting,
all-target Clippy and locked workspace tests pass; the workspace suite excludes
the research module, whose new fixed/fitting controls run separately. The initial
plan was rejected before execution for omitting a verify phase. The first compile
then failed on helper visibility; a fresh source fixes visibility only. Both
attempts and logs remain separate. No buffering formula was retuned.

Full plans, complete vendor/source identities, failed attempts, successful logs
and source-matched Windows records remain under private
`scratch/prob-shuffle-available-buffer-20261103T1927/` in each checkout. Six
research jobs ran; the separately reviewed Windows confirmation extends the
initial four-job study limit. No archive upload is claimed. Earlier browser
acceptance covers the original candidate, not this changed storage variant.
Wide rows, competition after constructor observation and browser acceptance
remain unproved. This supplies storage evidence without changing execution graph
code, decision diagrams, glossary, ADRs or the graph prototype.
