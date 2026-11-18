## Bounded plain prepared-publication overlap control (2026-11-04)

**Decision: retain the isolated overlap prototype after a favorable scoped native
comparison; no promotion.** The
[twelve-job record](../../benchmarks/plain-publication-overlap-2026-11-04.json) and
[replay patch](../../benchmarks/plain-publication-overlap-2026-11-04.patch)
test the prepared-publication cost identified by the attribution controls. Plain output currently
forces one task despite an available worker pool; compressed publication already
uses bounded batches. The prototype enables that existing worker/memory ceiling
for plain files under a test-only switch. Per-file flush/sync, independent reader
offsets, admitted slot/name/path/I/O owners, ordered manifest collection and atomic
directory publication stay intact. Production remains unchanged.

Both variants explicitly request four workers and 128-MiB job/shared capacity.
The fixed 200,000-row probe runs ordered export and the previously isolated
storage-revised probabilistic/shuffle fusion, with 1,024-row/65,536-byte caps.
Each recipe has two opposite-order pairs. Exact CSV/output-record/17-field
Analysis parity, independent IDs/fields/groups/caps and cleanup pass in all
eight measured jobs. Successful parallel jobs reach four overlapping chunk
lifetimes; serial jobs peak at one. This measures active tasks, not CPU use or
simultaneous file-sync calls.

Total API Prepare plus Execute seconds, median [minimum, maximum], n=2 each:

| Prepared recipe | Serial publication | Parallel publication |
| --- | ---: | ---: |
| Ordered export | 0.78161 [0.77778, 0.78544] | 0.62966 [0.61456, 0.64476] |
| Revised fusion | 1.16966 [1.16839, 1.17092] | 0.92033 [0.90969, 0.93097] |

Median reductions relative to serial publication are 19.44% and 21.32%.
Execute-only medians are 0.70558 versus 0.56383 seconds for ordered export and
0.71795 versus 0.48284 seconds for fusion. Every paired total difference favors
parallel publication. CLI startup, fixture generation/hash, independent
verification and cleanup assertions are outside the clocks. These short,
same-process, warm/uncontrolled-cache samples do not establish general speed,
tails, physical I/O or transfer to other platforms.

Logical temporary traffic is unchanged within each recipe: ordered reads/writes
18,830,688/18,816,075 bytes, fusion 79,085,408/78,392,909 bytes. Ordered export's
tracked workspace peak rises from 275,410 to 666,346 bytes. Fusion's global peak
stays 28,559,245 bytes; earlier processing dominates that counter, so it does not
measure the publication increase. Reservations are not RSS. Do not pool these
128-MiB/four-worker jobs with earlier 32-MiB/one-worker comparisons.

Four separate 2,000-row controls cover mid-publication cancellation after ordered
collection and one fixed competing grant leaving 200 KiB free after preparation,
for both variants. Cancellation cleans all private results. Both pressure cases
return typed memory denial, retain only the competitor after teardown, then
release the pool to zero. This is failure-cleanup coverage, not a successful
admission-domain comparison; no capacity sweep follows. Extra concurrent owners
remain a promotion concern.

The first native build failed on a pressure-helper integer conversion before any
job ran. A fresh snapshot uses a checked conversion. Linux Clippy then rejected
the test's manual range predicate; a fresh source changes only that assertion
to the equivalent inclusive-range form. Native source-v2 is byte matched to its
Linux counterpart; replay/validated source-v3 differs only in that assertion.
Output/core/vendor/embedded-asset inputs are identical. Fresh formatting and
all-target Clippy pass. A workspace run left successful logs but no terminal
runner status after a process/time discontinuity; it remains incomplete.
The separately recorded recovery suite passes with exit zero. Research helpers
run separately in the twelve native controls. Exact replay passes.

Native context is Windows/MSVC Rust 1.99.1 with captured hardware, background
processes and cache limits. Full source identities, both release-build attempts,
binary, samples and validation/recovery logs remain under private
`scratch/plain-publication-20261104T0019/` in the respective checkouts; no archive
upload is claimed. Prepared ordered export differs from current direct Run,
which already streams eligible limits-only jobs. Transfer to the unchanged
production allocation/shuffle pipeline, broader admission and browser acceptance
remain open. No execution graph code/diagrams, glossary, ADRs, prototype or
concurrent root edits change.
