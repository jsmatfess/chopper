## Independent random-bucket full-shuffle experiment (2026-10-19)

Harnesses: [complete jobs](../../history/shuffle-harnesses-2026-11-16/benchmark-random-buckets.py), [summary generation](../../../scripts/summarize-random-buckets.py), [window reproduction](../../history/shuffle-harnesses-2026-11-16/reproduce-bucket-window.py), [separate follow-up](../../history/shuffle-harnesses-2026-11-16/followup-bucket-window.py). Check each script's arguments and the recorded build identities before replaying.

The opt-in `experimental-random-buckets` feature implements
`full_shuffle_algorithm: "independent_buckets_v1"` under `flexible_v1`.
It changes requested `auto` full shuffles only. Omitted algorithm settings and
explicit uniform/Fisher–Yates/buffer strategies keep their existing behavior.
Unsupported builds reject the new setting before input I/O. Defaults remain
unchanged: the candidate generally trails the original seeded implementation
and has substantial small-parent overhead.

The [construction and ideal-permutation proof](../../independent-buckets-experiment.md)
specify sixteen independent routing buckets, fresh resident-leaf Fisher–Yates
randomness, fixed traversal order, at most two routing levels/seventeen routing
attempts per parent, and fresh full-key fallback. Routing uses the versioned
counter-source nibble; the requested counter/XOF source supplies leaf draws and
fallback keys. The audit records that mixed construction, logical parent,
bucket path, pass/depth bounds, actual choices and counters. Prepared-snapshot
replay remains the reproducibility guarantee.

Writers and decoder storage are charged and bounded. Writers are sealed before
leaf admission; shuffled resident leaves emit directly without another leaf
dataset. Owned routed sources are released before descent. Typed admission
denial discards tentative route files before fallback; errors during emission
abort rather than replaying already emitted rows. Tests cover small-case ideal
multiplicity and a failing input-order-leaf control, separated domains,
direct-emission file counts, forced skew/depth/pass fallback, local/shared
admission rollback, cache-size parity, group isolation, cancellation and cleanup.

### Complete native jobs

The first matrix contains 300 alternating timed complete jobs and 100 separate
allocator/storage censuses: ten fixtures, one/four workers, five variants and
three timing repetitions. All verify exact unique IDs/fields, tuple membership,
canonical lineage, logical stages, downstream quotas and strict output caps.
Matching v1 controls require identical bytes/metadata; matching pinned bucket
plans require repeat/census parity. Distribution-equivalent algorithms are not
required to produce the same order.

One-worker medians in seconds, with per-build ranges and resources retained in
the [machine summary](../../evidence-originals.md#sha256-45001bf961e5c9b1c5984844a889b6d77d1fd117b3ef736a9e39f7cb991efa92 "Original: docs/benchmarks/random-buckets-summary-2026-10-19.json"):

| Fixture | Original seeded | Flexible keys | Old prefix | Buckets counter | Buckets XOF/64 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Resident, 120,003 rows | 0.1275 | 0.1545 | 0.1462 | 0.1468 | 0.1353 |
| Narrow external, 400,003 | 0.4631 | 0.5338 | 0.7770 | 0.5039 | 0.4857 |
| Wide external/downstream, 180,003 | 0.4991 | 0.6122 | 0.8769 | 0.5946 | 0.5751 |
| Sixteen parents | 0.2232 | 0.2551 | 0.2645 | 0.3088 | 0.3046 |
| Skewed parents | 0.3019 | 0.3895 | 0.4465 | 0.3977 | 0.3840 |
| Presorted parents | 0.2183 | 0.2479 | 0.2469 | 0.3003 | 0.2955 |
| 128 small parents | 0.3793 | 0.4115 | 0.4215 | 0.6464 | 0.6580 |
| 32 extra columns | 0.1713 | 0.2133 | 0.2646 | 0.2009 | 0.1929 |
| Rare 1.8 MB row/downstream | 0.0766 | 0.0879 | 0.1017 | 0.0825 | 0.0791 |
| Forced routing overflow | 0.0543 | 0.0742 | 0.0793 | 0.0953 | 0.0940 |

These measurements show the cost of both explicit routing and flexible
materialization/audit. Directly emitted random leaves improve on the older
prefix path for external fixtures, but do not justify replacing the original
default. The many-parent fixture creates 4,105 temporary files versus nine for
flexible keys, explaining a material overhead that the algorithm cannot hide
behind its uniform-permutation argument.

Separate post-publication counters include CSV snapshot/manifest publication.
For narrow external input, flexible keys read/write 143.7/143.3 MB, old prefix
261.9/261.4 MB and counter buckets 137.3/136.9 MB. Charged temporary peak falls
143.2 → 107.3 MB from flexible keys to buckets. Wide/downstream traffic is
410.6/410.5 → 407.8/407.6 MB, versus 625.0/624.8 MB for prefix; temporary peak
falls 315.7 → 215.1 MB. The original seeded wide implementation writes about
201.9 MB and remains faster. Narrow file counts are 18/278/37 for flexible
keys/prefix/buckets; wide counts are 22/280/39.

The adversarial fixture chooses source IDs whose first two independently
computed routing nibbles are zero, placing twenty 600 KB records in one target
path. It is excluded from quality diagnostics. The target takes two routing
passes then a depth-bound full-key fallback, with the other parent independently
resident. Whole-job buckets read/write about 102/85 MB versus flexible keys
61/61 MB, and peak temporary space rises about 36.6 → 46.6 MB. Bounded fallback
is correctness protection, not a promised speedup for adversarial routing.

Allocator censuses and 10 ms filesystem samples are separate from timing.
The samples include intermediates plus publication staging/retained output and
are lower bounds; directory metadata is excluded. Linux filesystem counters
report zero on these warm WSL runs. Logical traffic and sampled allocated file
sizes do not establish physical SSD traffic or cold-device throughput.

### Browser parity and quality evidence

The first 90 complete native/Chromium-WASI jobs pass exact matching-plan output,
order and metadata parity over three repetitions, including all three XOF cache
sizes, sixteen-parent shuffles, downstream balanced output and the explicit
uniform exclusion control. On 100,000 rows with 128-byte payloads, browser
counter buckets take median 2.189 s versus flexible keys 2.198 s and old prefix
6.707 s. Sixteen-parent buckets take 4.434 s versus 3.217 s for flexible execution;
downstream buckets take 2.873 s versus 3.022 s. Small differences are not a
general browser speedup claim.

A separately recorded three-repetition original seeded control on the same
100,000-row fixture takes median 0.1284 s native and 1.4886 s Chromium/WASI,
versus buckets 0.162/2.189 s. The simpler seeded path therefore remains the
relevant default as well as the faster small-job reference.
[Matched small original control](../../evidence-originals.md#sha256-c1b8e312511bec01a425d21af1ddace85767c72a7031c319da17aaee858fa961 "Original: docs/benchmarks/random-buckets-default-engines-2026-10-19.jsonl").

Browser storage diagnostics now observe successful workspace file operations
and profiled export writes through workspace cleanup, including the completion
marker. They report logical workspace/combined destination peaks, peak live file
and open handle counts, and zero workspace bytes after cleanup. Metadata,
browser implementation buffers, other origins and physical storage are excluded;
a user-selected destination may live on another volume. Export accounting adds
RPCs only when profiling is enabled. Node coverage checks truncation, cumulative
export bytes, invalid accounting and cleanup; real-browser smoke checks pass.
Production cleanup is inside the browser completion clock; independent output
verification and benchmark-owned destination deletion are outside it.

The [preregistered quality family and follow-up](../../independent-buckets-acceptance.md)
retain two original window-label flags (ascending/descending share the same
source-ID/label observation). All 30 bounded-buffer negative comparisons flag.
The separate 48-comparison follow-up has no corrected flags, with descriptive
bucket mean 6.023292 against ideal expectation 6.023529. This does not identify
the cause of the original flags or certify independence/uniformity; no seeds,
thresholds or algorithm choices were changed to remove them. Broader flexible
acceptance remains open.

Raw evidence: [native timings/censuses](../../evidence-originals.md#sha256-518d7dd23178f298ae937e0ecc78a19e89d9aa32e6646601d8da54357c4bc255 "Original: docs/benchmarks/random-buckets-native-2026-10-19.jsonl"),
[native/WASI timings](../../evidence-originals.md#sha256-691a33488f78e6592457ffc10ad88857b3274c244d9258b9be3ee9865d6dcf0f "Original: docs/benchmarks/random-buckets-engines-2026-10-19.jsonl"),
[text/failure controls](../../evidence-originals.md#sha256-5f3cf69c34c34df582cfb845ea6f5706e5f27746899c260bfaf383cc356909f5 "Original: docs/benchmarks/random-buckets-controls-2026-10-19.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-95313eaedf2a866f75d7ed7d518beb1f247669c7f58b38be2958609e96b29aa3 "Original: docs/benchmarks/random-buckets-browser-2026-10-19.json"),
[browser storage smoke](../../evidence-originals.md#sha256-2e2a89e1fadcc40954bb35c949d392ef8c913c169ad9a4878ab7a2113359eda3 "Original: docs/benchmarks/random-buckets-browser-space-smoke-2026-10-19.jsonl").

### Multi-level native follow-up

A separately hashed 1.5-million-row/35-column fixture adds 30 timed jobs and ten
allocation/storage censuses at one/four workers. All pass the same exact v1 or
pinned-bucket checks and field/ID/cap validation. Medians (full ranges remain in
the raw artifact):

| Workers | Original seeded | Flexible keys | Old prefix | Buckets counter | Buckets XOF/64 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.203 | 5.475 | 7.511 | 5.664 | 5.441 |
| 4 | 4.393 | 5.584 | 7.842 | 5.754 | 5.644 |

Buckets complete seventeen routing passes over three million routed rows and
emit 256 independently shuffled resident leaves at depth two, without key
fallback. One-worker publication-inclusive logical read/write totals are about
1.824/1.725 GB, versus flexible keys 1.623/1.622 GB, prefix 2.460/2.460 GB and
original seeded 1.088/1.088 GB. Thus fewer bytes than prefix do not imply fewer
bytes than full-key merging. Charged temporary peaks are respectively
1.102/1.350/1.215/0.815 GB for buckets/flexible keys/prefix/original seeded.
The 10 ms bucket disk sample observes 1.102 GB and 69 live files; it remains a
lower bound rather than a physical-device claim.

The bucket census records about 1.78 million allocation calls versus 4.10
million for keys and 7.85 million for prefix; requested live peak is about
7.46 MB and observed RSS about 13 MB. These reductions do not produce a broad
complete-job win over the original default. Source preparation, independent
verification and allocator/storage observers are excluded from timing.
[Raw multi-level native jobs and censuses](../../evidence-originals.md#sha256-979a15b78954bddbc600e86704affc534b81129a2eb00e52ad646ada7fa56b16 "Original: docs/benchmarks/random-buckets-multilevel-native-2026-10-19.jsonl").

The separately hashed browser fixture has 1.5 million rows and 36 columns
(the common browser generator adds country/label fields). Its 24 alternating
native/WASI jobs pass exact matching-plan output/metadata parity, including
the two-level/17-pass/256-leaf bucket graph. Three later native/WASI repetitions
of the original seeded control use the identical fixture and runtime workers;
these controls are separate from the alternating flexible/prefix comparison.

| Plan | Native median (range), s | Chromium/WASI median (range), s | Browser logical workspace peak, GB |
| --- | ---: | ---: | ---: |
| Original seeded | 4.458 (4.091–4.468) | 19.395 (18.857–19.820) | 0.960 |
| Flexible full keys | 5.447 (5.413–5.602) | 23.285 (23.222–23.836) | 1.502 |
| Old prefix | 7.738 (7.575–7.847) | 42.629 (41.396–43.065) | 1.227 |
| Buckets counter | 6.069 (5.822–6.157) | 20.343 (20.225–21.048) | 1.118 |
| Buckets XOF/64 | 5.919 (5.721–6.082) | 21.459 (19.959–21.836) | 1.118 |

Browser buckets improve over flexible keys and prefix on this fixture, but the
original seeded control remains faster and smaller. The browser runs use a
temporary persistent disk profile because the independently reproduced private
profile storage limit is below these peaks. This does not change production
quota policy. All runs stay within 64 open handles, verify successful export
bytes against actual destination file sizes, and observe zero workspace bytes
after cleanup. Combined workspace/destination peak equals workspace peak on
these fixtures because the routing/merge phase dominates later export overlap.
[Multi-level native/WASI jobs](../../evidence-originals.md#sha256-766d69e4356db5065ef9d42b33223fc8dc91fcebc07f0a4e806d1d8a59ef5d9d "Original: docs/benchmarks/random-buckets-multilevel-engines-2026-10-19.jsonl"),
[matched original control](../../evidence-originals.md#sha256-5ed03be0f8d0411c246a97a805e513d88c290ae41d55f417399bf642e0b45cc6 "Original: docs/benchmarks/random-buckets-default-multilevel-engines-2026-10-19.jsonl").

The adversarial fixture adds 24 verified native/WASI jobs over counter and all
three XOF cache sizes, three repetitions each. Every target records two routing
passes, depth two and one explicitly identified `depth_bound` full-key fallback;
the 4,764-row other parent remains isolated. Matching source/cache plans retain
exact bytes/order/metadata, including sparse source IDs spanning XOF pages.
[Forced-overflow replay and space](../../evidence-originals.md#sha256-555a4284637e30fc55a79912f039f9baa7e38e5787f389ba74bef9daa93e74a5 "Original: docs/benchmarks/random-buckets-overflow-engines-2026-10-19.jsonl").

The final [26 browser contracts](../../evidence-originals.md#sha256-dd521ca3030f5bcb11e19516a89cf6796bc73234cbaecba27e35ccc8124f9971 "Original: docs/benchmarks/random-buckets-browser-final-2026-10-19.json")
include cancellation after at least 65,536 rows of actual bucket routing and
disk denial during routing under a 90 MiB temporary ceiling. Both release the
workspace and refuse publication. The native bucket integration target passes
seven tests, including new all-feature composition checks for exact allocation
ranges (named zero, quotas and output caps) and partition-first plus downstream
balanced output (logical/physical scopes and membership), at one/four workers
and all XOF cache sizes. The prior complete all-feature workspace run passed
283 tests; no runtime Rust implementation changed during these final additions.
UI tests/type checking, Clippy and formatting checks pass.

The [diagnostic replay](../../evidence-originals.md#sha256-4d833ce91672a2027217fa811c7fdd6f4405f02d7941f38b8380f555cb5d1da4 "Original: docs/benchmarks/random-buckets-diagnostics-engines-2026-10-19.jsonl")
matches all 480 native and 480 WASI CSV hashes/order and output metadata against
the original corpus, retaining its two primary and thirty negative-control flags.
This is parity evidence, not a second statistical family or a claim that the
original flags disappeared. The broader flexible acceptance/device/cold-storage
tasks remain open; this closes the bounded prototype evaluation without promotion.
The isolated OPFS probe is retained as `scripts/probe-browser-storage.mjs`;
`--persistent` selects a temporary disk profile and `--limit-mib` bounds writes.
