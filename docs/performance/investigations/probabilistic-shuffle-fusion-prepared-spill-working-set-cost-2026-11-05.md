## Probabilistic shuffle fusion: prepared spill working-set cost (2026-11-05)

**Decision: retain the prepared-spill variant after a favorable bounded native
cost comparison; no promotion.** The [four-job record](../../evidence-originals.md#sha256-6dfef6e55af954491dbd57cb55cde67cf041b34ed2d060c6d8172eb001872c7e)
and [appended panel](../../benchmarks/probabilistic-shuffle-spill-cost-2026-11-05.patch)
check whether the [new real-owner remedy](../../performance.md#probabilistic-shuffle-fusion-prepared-spill-owner-control-2026-11-05)
preserves useful complete-job benefit despite its added live/unused files. Earlier
observation-only timings do not answer this changed-owner question and are not
pooled with these samples.

The fixed development case retains 200,000 probe-v1 rows, four regions,
probabilistic 80/20/0 groups followed by uniform shuffle, the original seed,
32-MiB job/shared pool, one worker, Auto grouping and 1,024-row/65,536-byte caps.
There is no peer. Exactly four jobs run baseline/candidate/candidate/baseline
in one optimized native Windows process, n=2 each. Auto is the stronger prior
simple baseline; no extra Sort, size, capacity, worker or repetition panel follows.
Both variants exercise external sorting, with eight runs and four merges each.

Seconds cover explicit API Prepare plus Execute through publication, excluding
CLI startup, fixture generation/input hashing, verification and cleanup assertions:

| Variant | Median seconds | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Prepared Auto baseline | 1.44615 | 1.38009 | 1.51221 |
| Prepared-spill fusion | 1.36845 | 1.28276 | 1.45414 |

Candidate-minus-baseline paired differences are -0.09733 and -0.05807 seconds.
The median reduction relative to this baseline is 0.07770 seconds, or 5.37%.
These short same-process samples have overlapping ranges, warm/uncontrolled
cache and retained background programs; they establish no tails, threshold,
physical SSD claim, general speed advice or comparison with earlier source versions.

Complete Context counters, read after publication, remain deterministic within
each variant. Logical temporary reads are 165,707,649 versus 119,662,607 bytes;
writes 164,806,072 versus 118,970,108 bytes; files created 26 versus 20, baseline
versus candidate. Candidate tracked workspace peak is higher: 8,560,865 versus
7,460,502 bytes. The spare's file/buffer ownership and unused files remain real
costs even while total traffic/files fall. These are working reservations and
logical traffic, not RSS or physical I/O. Fixture/verifier heaps sit outside the
engine ledger and timer.

All four jobs pass one exact within-panel CSV/output-record/17-field logical
Analysis reference and independent fields/IDs/group-count/cap/cleanup checks.
Only the private test helper is appended; runtime/core/storage/vendor/embedded
bytes and existing helper prefix match the accepted owner prototype. Fresh Linux
formatting/all-target Clippy compiles the helper, while the previous full default
workspace pass applies only to that unchanged runtime with the research module
excluded. Native MSVC Rust 1.99.1 source matching covers all 326 inputs, the new
release panel/verifier pass, and exact appended-patch replay passes.

The native context is Windows 11 build 26200, Ryzen 7 5800X and 16 logical CPUs;
actual hardware/process/toolchain/cache context, full source, binary, plans and
logs remain under private `scratch/prob-shuffle-spill-cost-20261105T0422/` in both
checkouts. No own Linux build runs during native measurement. No archive upload
or production/graph/retry/default/Auto changes are claimed. Broader pressure/temp
failures, external wide shapes and changed-owner browser acceptance remain separate;
this positive point does not establish their feasibility or authorize integration.
