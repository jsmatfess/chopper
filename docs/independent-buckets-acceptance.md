# Independent-bucket diagnostic family

Current status (2026-10-24): XOF and independent buckets are removed. The dated
preregistration, original diagnostic flags and follow-ups below are historical;
reproduction requires matching pre-removal artifacts.

Declared 2026-10-19 before running or inspecting this family's metric corpus.
This extends the [original fixed protocol](shuffling-research.md), with its same
32 literal seeds, five 256-row input patterns, six metrics, 1,024-pilot center,
2,047 Monte Carlo corpora and independently fixed ideal null. Do not select
seeds/metrics, tune thresholds or pool observations with earlier families.

Family identity: **independent-buckets-full-shuffle-v1**. Use the flexible policy,
`full_shuffle_algorithm: "independent_buckets_v1"`, counter-v1 leaf source,
64 MiB, one worker and four buffer rows. The strategies are `auto` (the new
explicit bucket algorithm), `uniform` (its unchanged full-key exclusion control)
and `buffer` (unchanged negative control). Preserve the original per-parent
partition-before-shuffle setup for the skewed fixture and its 192/48/16 groups.

Run 480 complete native jobs, with 60 primary comparisons at 0.05/60 and 30
negative comparisons at 0.05/30. Require exact fields/unique IDs, original tuple
membership/canonical order, logical counts and released workspaces. Verify that
`auto` actually records one completed routing pass per expected parent and
resident, independently shuffled leaves; these tiny fixtures need no overflow.
Verify explicit uniform/buffer do not silently invoke buckets. Reuse the frozen
null cache only after checking its function/source/shape/Python contracts and
recording its hash. The mathematical null is unchanged: independent uniform
permutations inside each existing logical parent.

Replay all 480 configurations in native and WASI, matching every CSV hash,
order and output metadata against the native corpus. Matching bytes imply the
same diagnostic values; this is a parity extension, not another statistical
family. Counter/XOF combinations, depth/pass/key fallback and adversarial input
remain invariant/byte-replay controls, with no unregistered combined p-value
claim. The adversarial routing fixture is explicitly excluded from this corpus.

These are finite regression diagnostics, not proof of PRNG independence,
literal uniformity over all permutations, external-scale behavior, resource
caps or performance. Keep the [construction proof and bounded-failure controls](independent-buckets-experiment.md),
complete-job timings/censuses and broader platform/device acceptance separate.

## Preregistered window-label follow-up (2026-10-19)

The original family flags ascending/auto/window_labels and
 descending/auto/window_labels, both mean 8.57670998632011 with empirical
p=1/2048. Ascending/descending share source IDs and labels, so these are the same
underlying ordering/label observation; the blocks fixture also shares those
labels. Preserve all original observations and flags without changing seeds,
metrics, thresholds, algorithm identities or null data.

Before running additional observations, declare sixteen new cohorts of 32 seeds:
`independent-buckets-window-followup-v1/cCC/sSS`, with CC=00…15 and SS=00…31.
They are disjoint from the original seeds. Use only the original ascending
fixture and the flagged `window_labels` metric. Each cohort compares three
separately reported constructions: the candidate auto/bucket algorithm, existing
explicit uniform-v1 and an independent Python ideal-bucket sampler. The ideal
sampler derives routing and each bucket's leaf RNG seeds from separately named
SHA-256 domains and uses `random.Random.randrange(16)` plus independent leaf
`shuffle`; it is a simulation control, not BLAKE3 code or a PRNG-quality proof.

There are 48 cohort comparisons, at 0.05/48, using the same frozen 32-sample
ascending null calibration with its validated source/shape/Python contract.
Report all 512 observations per construction and every cohort p-value/flag.
Do not compare the 512-sample aggregate to the 32-sample null or pool these
results with the original family. Aggregate means/ranges are descriptive only.
The analytical ideal expectation for this three-window/four-label Pearson
statistic is `6*256/255 = 6.023529411764706`; it is context, not an extra test.

Ranked explanations to distinguish are an extreme original finite-seed corpus,
correlation introduced by routing/leaf domain use, or a metric/null/fixture
problem. A systematic bucket-specific departure should persist relative to both
controls across new cohorts. A calibration problem should affect the ideal
control as well. Absence of a systematic departure in this finite follow-up does
not erase the original flags or prove generator independence/uniformity.

## Recorded diagnostic results

The [original 480-job family](evidence-originals.md#sha256-b86c1e27ce2ba6d8089cc2a1eb49e99ca2c6a8746cff6715fe10924828e6aea9 "Original: docs/benchmarks/random-buckets-diagnostics-native-2026-10-19.jsonl")
retains both primary flags described above. All 30 bounded-buffer negative
comparisons flag. The [32-seed focused reproduction](evidence-originals.md#sha256-7a18e0a858d9558222d690f84be9a78d3a1273336cce4e310ebc29b6b0961cfe "Original: docs/benchmarks/random-buckets-window-reproduction-2026-10-19.jsonl")
matches the original candidate fingerprints and statistic; its script deliberately
returns failure when that original flag reproduces.

The [preregistered follow-up](evidence-originals.md#sha256-3ba5e8be7389f112352a00a7e6b43da563a875e91db7006e9c81ba5a9e7f1f5f "Original: docs/benchmarks/random-buckets-window-followup-2026-10-19.jsonl")
completes 1,024 native jobs and 512 ideal-bucket observations. None of its 48
cohort comparisons flags at 0.05/48. Descriptive 512-observation means are
6.02329215116 (buckets), 5.94670613885 (uniform-v1) and 6.14276462038 (ideal
buckets), against ideal expectation 6.02352941176. These observations are
consistent with an extreme original cohort and do not show a systematic
bucket-specific departure in the new cohorts. They do not establish the cause
of the original flags, erase them or certify uniformity. The construction,
seeds, metrics, null calibration and thresholds remain unchanged.

The [exact replay extension](evidence-originals.md#sha256-4d833ce91672a2027217fa811c7fdd6f4405f02d7941f38b8380f555cb5d1da4 "Original: docs/benchmarks/random-buckets-diagnostics-engines-2026-10-19.jsonl")
completes all 480 native and 480 Chromium/WASI jobs. Every CSV hash/order,
logical digest and output metadata matches the original native corpus; the
summary explicitly retains both primary flags and all 30 negative-control
flags. This extends implementation parity, not the statistical family or its
interpretation.
