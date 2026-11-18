## Probabilistic shuffle fusion: prepared spill owner control (2026-11-05)

**Decision: retain an isolated real-owner storage remedy after scoped acceptance;
no promotion.** The [ten-job record](../../evidence-originals.md#sha256-04bf720fcc13a5ec164d7d74842eef42c2bab2baa08caa48ef666558681911e4)
and [appended remedy](../../benchmarks/probabilistic-shuffle-prepared-spill-2026-11-05.patch)
restore completion on the
[after-observation counterexample](../../performance.md#probabilistic-shuffle-fusion-peer-after-buffer-observation-2026-11-05).
That failed variant remains preserved. This is a new private storage version,
with no production, execution graph, retry, default or Auto changes.

The alternative Sorter constructor now admits a real buffered spill file and
its 64-KiB buffer grant before retaining rows. The file/path keeps existing
admission and atomic-creation contracts. The owner stores writer before grant;
flush likewise declares the grant before the writer so error destruction keeps
the writer funded. It consumes that already-prepared writer, frees retained rows
and finishes run merging before preparing another spare. A resident return or
cancelled sorter drops the unused writer and its file. The prototype's default
constructor keeps no spare and retains its existing grant/sort/file order.

Fresh Linux and native Windows each run five declared research jobs. Both the
before- and after-observation cases now complete with exact within-runtime CSV,
output-record and logical Analysis parity, independent fields/IDs/group counts/
caps, one input visit and final cleanup. These keep the original 20k R0 probe,
50/50/0 allocation, uniform shuffle, 32-MiB job/pool, one worker, 28-MiB peer and
1,024-row/65,536-byte caps. This restores that fixed exposure; higher retained
ownership means it does not prove unchanged competitor admissibility or universal
completion under arbitrary pressure.

The original no-peer fitting baseline/candidate pair also passes exact CSV/
output-record/17-field Analysis and independent field/ID/group-count/cap checks
on each runtime. Its four-region 80/20/0 input is unchanged. Logical reads remain
11,502,681 versus 5,346,652 bytes and writes 10,697,389 versus 4,741,736 bytes,
baseline versus candidate. Those counters preserve the predicted pass reduction;
existing API seconds and sort clocks remain raw but are excluded from performance
inference. No new timing comparison or physical-I/O/RSS claim follows.

Two cancellation jobs stop immediately after the first spare is constructed,
before packed-row traversal, and release every private file/grant without
publication. Four additional unit owner controls leave either 65,535 or 65,536
bytes shared free before construction: the first denies buffer admission, the
second admits the buffer grant then denies path construction. Both release
partial ownership and preserve the peer/Context until their independent drops.
The ten-job count comprises eight successful prepared executions and two
cancellations; constructor unit edges are separate.

The remedy adds a live file/path owner and 64-KiB buffer; it can admit less work
at construction and creates unused temporary files on resident paths and after
the final flush. Its external-working-set cost, broader pressure/temp failures,
wide shapes and browser acceptance remain unproved. Earlier speed evidence for
the observation-only variant does not establish this changed owner's benefit.
Any cost follow-up needs a named decision and a separately frozen small panel.

Fresh Linux formatting/all-target Clippy, the focused five-job/owner-edge wrapper
and locked workspace tests excluding the research module pass. Native MSVC release
control/verifier, complete 326-input source matching and exact appended-patch
replay pass. Complete vendor/embedded inputs, source, plans, binary and logs remain
under private `scratch/prob-shuffle-prepared-spill-20261105T0409/` in both
checkouts; no archive upload is claimed. Test fixture/verifier heaps remain
outside the engine ledger. Broader browser/feature coverage is not inferred.
