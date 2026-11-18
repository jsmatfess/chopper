## Resident allocation prepared-router control (2026-11-02)

A fresh instrumented copy of the retained admission probe identifies the denial
at **router bucket reservation**, reached while converting the retained buffer.
The immediate-routing path still completes. This establishes the site for this
local-workspace counterexample; it does not estimate occurrence in full Jobs.
The diagnostic source and logs remain separate from the original evidence.

The [new isolated patch](../../benchmarks/resident-transition-prototype-2026-11-02.patch)
prepares the known allocation index routes before retaining rows. Actual bucket
buffers, tree/key allowances, temporary paths and empty files retain their grants.
On overflow, buffered rows write to those existing writers, then row storage and
its grant are released. A fitting parent sorts in memory and drops the unused
empty router. Known allocation keys are eight-byte indices with nondecreasing
ordinals; random membership, seed/domain and downstream order are unchanged.
This patch replaces the earlier resident prototype; do not apply both patches.

Alternatives reviewed: a numeric construction-headroom reservation would need
transactional transfer into route/path owners, including constructor overlap;
catching denial after retaining rows can leave insufficient spill headroom.
Preparing actual owners avoids that transfer. If preparation cannot be admitted
or exceeds existing routing bounds, its partial empty files are dropped before
selecting immediate routing, with no consumed input to replay. Other I/O errors
and cancellation remain terminal. Retention targets at most half remaining local
workspace as well as the existing sorter limit; this observation grants nothing.
This is an experimental feasibility target, not a calibrated cost selector.

The [derived control](../../evidence-originals.md#sha256-ee2d0aac8fd1bc6fb9c1b4efad1f18646cfbb141b67abef17a83254f7ae82843)
records the original 2,500-row/128-byte/two-preassigned-key occupied-workspace case
completing through the prepared router with exact key/ordinal ID order. Separate
cases check a fitting 64-row parent, overflow, partial preparation denial with
eight possible indices but only two actual keys, cancellation on the next
resident/routed ingestion call, and a 100-byte-headroom denial. Every case asserts
zero temporary bytes/live files and return to the held workspace baseline.
The first cancellation test failed because it expected the resident iterator to
check cancellation; the revised control enters the next ingestion checkpoint.
Both attempts and full logs are preserved. This is test correction, not a newly
implemented cancellation behavior.

The narrow retained counterexample is addressed. This does **not** prove inclusion
of immediate routing's entire success domain: unused keys now consume empty
files and buffers, and later shared pressure, decode, metadata or I/O admission
can still deny. Preparation adds construction/rollback work even on fit and may
move I/O failure earlier. Prior speedups do not apply to this changed candidate.
No new performance panel is warranted before deciding whether those costs and
broader compatibility merit another separately bounded experiment. No complete
job timing samples, RSS or physical-I/O conclusions are added.

The isolated default-feature native snapshot passes formatting, workspace/all-target
Clippy with warnings denied, and the full locked workspace suite. Existing
integration tests cover seeded probabilistic parity across routing/sorting/budgets,
strict caps and publication/cancellation cleanup. These checks do not establish
arbitrary concurrent feasibility, WASI or browser execution.

Production Rust/defaults remain unchanged; apply the patch only to a fresh
matching source copy with `git apply --unidiff-zero`. Native validation belongs
to the isolated snapshot, not the repository CI build. The source snapshots,
complete vendor/native embedded UI identities (including HTML/CSS/app.js), plans,
self-reviews, failed attempt and full runner logs remain beneath
`scratch/resident-transition-20261102/` in the retained native Windows checkout;
the WSL directory of the same name holds dispatch/session/review records.
The previous session and terminal timing controller were not resumed or edited.
A preservation limitation remains: compilation reused the earlier build cache,
so Cargo replaced its debug test executable. Separate release comparison binaries,
source snapshots and raw records remain intact; preservation of every prior
cache binary cannot be claimed. The final candidate test binary is now copied
to `retained-v2-test-binaries/` beneath the new native session.
