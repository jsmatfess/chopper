## Probabilistic shuffle fusion: native external working-set comparison (2026-11-03)

**Decision: retain the isolated storage revision after a favorable bounded
native comparison; no promotion.** The
[eight-job record](../../evidence-originals.md#sha256-624edeac9dcf61f8141cf05551e32be1e15169bf66c9689645bf54b1b36a8abb)
and [appended panel](../../benchmarks/probabilistic-shuffle-working-set-2026-11-03.patch)
test whether the earlier small fitting benefit survives external sorting and
the existing explicit Sort option. This uses the preceding available-buffer
variant, with only a new diagnostic helper; production code stays unchanged.

The fixed development case increases the original probe to 200,000 unique rows
with four regions and 80/20/0 probabilistic groups followed by uniform shuffle.
Seed, 32-MiB job/shared budget, one worker and 1,024-row/65,536-byte caps are
unchanged. No competing grant is injected. Exactly two opposite-order pairs run
under each grouping policy, in one optimized native Windows test process.
All eight jobs compare one exact CSV/output-record/17-field logical Analysis
reference. Independent fields/IDs/groups/caps, private staging/temp cleanup and
final pool release pass. Both variants exercise external sorting; no size or
capacity adjustment follows the result.

Seconds are API Prepare plus Execute through publication, excluding CLI startup,
fixture generation, input hashing, verification and cleanup assertions. Each
variant/policy has two samples; median [minimum, maximum] is:

| Policy | Prepared baseline | Revised fusion |
| --- | ---: | ---: |
| Auto | 1.35435 [1.29238, 1.41633] | 1.25533 [1.21825, 1.29242] |
| Explicit Sort | 1.48240 [1.46928, 1.49552] | 1.39321 [1.37586, 1.41057] |

Candidate-minus-baseline paired differences are -0.12391/-0.07413 seconds for
Auto and -0.09342/-0.08495 seconds for Sort. The median reductions relative to
each baseline are 7.31% and 6.02%, respectively. These short same-process results
do not establish tails, general speed advice or CLI/platform transfer. The
stronger available Auto baseline remains part of the comparison; explicit Sort
alone does not recover the candidate's traffic saving here.

Logical temporary reads are 165,707,649 versus 119,662,607 bytes and writes
164,806,072 versus 118,970,108 bytes, baseline versus candidate under either
policy. Run/merge counts differ: Auto 8/4 versus 8/4; Sort 23/9 versus 15/5.
Files created are Auto 26 versus 16 and Sort 29 versus 19. Candidate tracked
workspace peak is higher: 8,593,550 bytes versus baseline Auto 7,460,390 and
Sort 7,349,043. These are logical counters and admitted working allocations,
not physical device traffic or RSS. Fixture and independent-verifier heaps
outside the timer also sit outside the engine's admitted memory ledger.

Fresh context records Windows 11 build 26200, Ryzen 7 5800X, 16 logical CPUs
and Rust/MSVC 1.99.1. Inputs are written immediately before reading; cache is
warm/uncontrolled. Background programs remain and the host is not claimed idle;
no compiler was present at the pre-build snapshot. No per-job CPU/RSS or physical
device/model measurement is available. The release test executable is retained
with SHA-256 `85acbcd29f65cc1270ff82fcef2ca14929a2cfbdc5371e41f11963fc87114203`.

All 326 frozen source/vendor/embedded-asset files match between Linux and Windows.
Fresh Linux formatting and all-target Clippy pass. The prior full workspace
suite is reused only for identical core inputs; the new helper runs the actual
eight native jobs. Patch replay is exact. Delivery evidence checks initially failed
for the fresh worktree's missing archive cache and legacy aliases. Both attempts
remain retained; exact local originals restore those prerequisites without
changing historical bytes. Full plans, context, input identities,
binary and logs remain under private
`scratch/prob-shuffle-working-set-20261103T1940/` in the respective checkouts;
no archive upload is claimed. Browser acceptance and arbitrary competition after
buffer-target observation remain open. Execution graph code, diagrams, glossary,
ADRs, prototype and concurrent research edits are untouched.
