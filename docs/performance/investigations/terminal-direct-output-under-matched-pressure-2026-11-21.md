## Terminal direct output under matched pressure (2026-11-21)

Retain the cancellation-corrected terminal-direct experiment for
plain Partition → probabilistic assignment. Defer a delivery specification.
One fixed peer reservation lets terminal-direct publish where snapshot
materialization fails. A second fixed request shows that terminal-direct can
exclude a competing owner that the snapshot path admits while both jobs can
otherwise publish. The latter occurs after row emission, where target changes
would require replay. Current Run dispatch stays outside the experiment.
[Matched requests and raw evidence identities](../../benchmarks/terminal-direct-matched-pressure-2026-11-21.json)

The current Linux native release engine runs both paths via the same private
processing seam. The 70,003-row plain fixture has four parents and named
80/20/0 probabilistic outputs, an internal fixed seed, one worker, a 32 MiB job
and shared ledger, and strict 4,000-row and 65,536-byte caps. A separate workspace
requests the same fixed grant in each arm at terminal selection, serialized row
65,536, or the finalization callback. It holds any successful grant until the
job finishes. The pressure controls retain live parent and child metadata at
emission. The input and output paths match exactly between arms.

| Boundary | Left for Chopper by the request | Snapshot | Terminal direct |
| --- | ---: | --- | --- |
| Target selection | 256 KiB | Both owners admit the peer request; job denied | Both owners admit the peer request; job denied |
| Target selection | 512 KiB | Peer admitted; job published | Peer admitted; job published |
| Row 65,536, where the writer is live | 289,344 bytes | Peer admitted; job published | Peer denied; job published |
| Publication | 256 KiB | Peer admitted; job denied | Peer admitted; job published |
| Publication | 384 KiB | Peer admitted; job published | Peer admitted; job published |

At row 65,536, the two output targets and their overlapping owners charge
289,196 and 289,491 bytes respectively. The exact 33,265,088-byte peer request
fits with snapshot, and that job still publishes with 148 bytes of peak ledger
headroom. Direct returns a typed shared-admission denial to the peer and
publishes in its absence. It has already emitted private CSV, so a safe
pre-emission fallback cannot restore this admitted request at that boundary.
At publication, both jobs admit the 33,292,288-byte peer. The direct path
publishes with 4,406 bytes of peak ledger headroom, while materializing the
snapshot needs a further allocation that is denied. These are working ledger
observations from real reservations, separate from process RSS or physical I/O.

The 26-pair primary test and a two-pair edge follow-up check one input open per
job, exact seeded CSV names, hashes and order, output records, logical Analysis,
independent field and ID conservation, partition membership, named empty
children, encoded caps and cleanup. Injected cancellation during row emission
and at finalization takes precedence, and a late nonempty destination survives
both publication attempts. The Linux Rust tests pass. Earlier unsupported pilot
assertions counted progress updates as input opens and assumed one-based lineage
indices. The final primary test passed while its log extractor missed the Rust
test runner's prefix on the first observation. An independent pass recovered
that row from the original log and verified all 52 outcomes without repeating
those jobs. The follow-up and its extraction pass with the exact same binary.

The existing small Windows and browser runs, temporary-ownership gains, and
cancellation remedy retain their original scope. These synchronized tests
establish a concrete admission trade-off and no complete-job elapsed estimate.
A broader codec or runtime would add owners before resolving the native plain
counterexample. Reopen delivery only with a concrete change to live writer
admission and a same-request test that preserves the competing completion.
[Earlier cancellation control](terminal-direct-output-dynamic-owner-and-cancellation-control-2026-11-03.md)
