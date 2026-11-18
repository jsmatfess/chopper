## Plain publication overlap: unchanged production Run transfer (2026-11-05)

**Decision: retain publication overlap as a separable candidate after favorable
scoped production-pipeline transfer; no promotion.** The
[ten-job record](../../benchmarks/plain-publication-production-transfer-2026-11-05.json)
and [single-file replay](../../benchmarks/plain-publication-production-transfer-2026-11-05.patch)
remove the preceding study's dependency on unpublished fusion. A clean archive
of production commit `1931376c246256215e8f2af29e8d443923d7ab79` supplies all
crates, vendors and native embedded assets. Only `output.rs` changes, adding the
same test-only publication switch/statistics and new controls. Engine, core,
storage and dispatch remain byte-identical; no experimental pipeline is enabled.

The fixture keeps 200,000 probe-v1 ASCII rows, four regions, seeded 80/20/0
probabilistic allocation followed by uniform shuffle, 128-MiB job/shared memory
and 1,024-row/65,536-byte caps. Four-worker serial/parallel jobs run in two
opposite-order pairs. A final one-worker serial/parallel pair is a functional
control, excluded from speed inference. All six use the actual library
`run_with_memory_pool` entry point. Nonempty operations select its unchanged
prepared fallback; CLI startup, fixture/hash creation, verification and cleanup
assertions remain outside the Run clock.

Four-worker Run seconds, n=2 per variant:

| Publication | Median | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Serial | 1.32820 | 1.30394 | 1.35245 |
| Bounded parallel | 1.07019 | 1.06187 | 1.07852 |

Candidate-minus-serial paired differences are -0.29058 and -0.22542 seconds;
the median reduction relative to serial is 19.42%. Successful parallel jobs
reach four overlapping chunk lifetimes, while serial and both one-worker jobs
peak at one. This establishes a scoped whole-Run benefit independent of fusion,
not general speed advice, CPU utilization, tails or CLI/browser transfer. Do not
pool these observations with earlier prepared/fused comparisons.

Exact CSV bytes are retained in raw byte maps and compared across all six jobs,
with output records and 16 resource-invariant Analysis fields. Requested/effective
workers are checked separately, completing the 17-field checks within matched
settings. Independent IDs/fields/groups/caps and temporary/private-staging cleanup
pass. Output order and logical metadata replay across the worker settings.
Whole-Run aggregate reservation peaks are 28,559,245 bytes in all six jobs;
earlier processing can dominate that peak, so it does not isolate publication
ownership or imply equal publication memory. Reservations are not RSS.

Returned Analysis diagnostics are preparation snapshots. Their temporary counters
are explicitly labeled prepublication in the artifact and are not presented as
complete-job traffic; this Run API does not expose the postpublication Context.
Each pool is sampled after Run and releases to zero after Analysis destruction.
Four separate 2,000-row prepared limits-only controls cover mid-publication
cancellation and one competing-owner point leaving 200 KiB free after preparation.
Both pressure variants deny with typed memory errors and clean all owned state,
retaining only the competitor until release. This proves cleanup, not admission
parity or safe arbitrary-pressure fallback. No capacity sweep follows.

Fresh native context records Windows/MSVC Rust 1.99.1, hardware/background
programs and warm/uncontrolled cache. One process, one machine and short samples
do not establish scale, physical I/O or other-platform gains. All ten jobs,
fresh Linux formatting/all-target Clippy/locked workspace tests and exact patch
replay pass. The suite excludes the research module; actual native controls run
separately. Full source identities, clean Git archive, release executable, plans
and logs remain under private
`scratch/plain-publication-production-transfer-20261105T0039/` in the respective
checkouts; no archive upload is claimed. Broader admission, other output shapes
and browser acceptance remain open. Production/defaults and execution graph
code/diagrams, glossary, ADRs, prototype and concurrent root edits are unchanged.
