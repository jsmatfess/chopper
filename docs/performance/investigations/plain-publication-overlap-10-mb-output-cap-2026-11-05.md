## Plain publication overlap: 10 MB output cap (2026-11-05)

**Decision: retain the native opt-in candidate; the larger-cap gain is small in
absolute terms and establishes no Auto threshold.** The
[four-Run record](../../benchmarks/plain-publication-large-cap-2026-11-05.json) and
[appended control](../../benchmarks/plain-publication-large-cap-2026-11-05.patch)
test whether favorable tiny-chunk overlap depends on high file fanout. Runtime
publication code is unchanged. The same 200,000-row production allocation/shuffle
probe, 128-MiB job/shared budget, four workers and seed now request a 10,000,000-byte
cap with no row cap. This tests the agreed byte-cap setting, not a new corpus or
a matrix of thresholds.

Each job produces twelve CSV files totaling 18,777,415 bytes; logical groups
leave the individual files smaller than the requested cap. Two opposite-order
pairs give the following library Run seconds, n=2 per variant:

| Publication | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Serial | 0.59340 | 0.57992 | 0.60688 |
| Bounded parallel | 0.56332 | 0.56261 | 0.56402 |

Candidate-minus-serial paired differences are -0.04286 and -0.01731 seconds.
The median reduction is 0.03009 seconds, or 5.07% relative to serial. These short
same-process samples with warm/uncontrolled cache do not establish a selection
threshold, tails, physical I/O or general speed advice. Do not pool them with
the previous smaller-cap jobs or infer a calibrated cutoff from the two settings.

All four jobs preserve exact CSV bytes/output records and 16 resource-invariant
Analysis fields, with workers checked separately. Independent IDs/fields/groups,
requested caps, owned cleanup and final pool release pass. The private verifier
now checks requested limits; only that helper and the new test differ from the
previous source. Runtime publication, engine/core/storage/vendor/embedded inputs
remain identical. Returned diagnostics are preparation snapshots, not completed
job traffic, and aggregate pool peaks are not RSS or isolated publication memory.

Fresh native Windows/MSVC Rust 1.99.1 context, one release executable, complete
source identities and exact appended-patch replay are retained. New Linux
formatting and all-target Clippy pass. The prior terminal workspace pass applies
only to identical runtime inputs; its research module was excluded, while the
changed tests are compiled and the new control runs natively. Earlier cancellation
and pressure controls remain historical coverage of the same implementation,
not additional observations in this study. Full plans, reviews, binaries and logs
remain under private `scratch/plain-publication-large-cap-20261105T0105/` in the
respective checkouts; no archive upload is claimed. This supports pursuing a
native experimental option with serial defaults, bounded existing workers and
no unused task slots for small remaining file counts. Default/Auto promotion,
broader admission and browser acceptance remain separate. Execution graph work
and concurrent root edits are untouched.
