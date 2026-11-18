## Buffered random final transfer (2026-11-16)

Retain buffering for repeated bounded draws, keep categorical allocation's original
single-use draw, and remove public seed inputs independently. This supplements the
[initial screen](buffered-random-draws-and-seed-removal-2026-11-16.md), rather than
replacing its observations. The final build supports a modest native resident
Fisher–Yates improvement. The initial browser improvement did not transfer at its
original magnitude; no substantial general hosted or external-shuffle gain is
claimed.

The [comparison receipt](../../evidence-originals.md#sha256-6a959c77feb7ee1d7612ebb10980c89ebf5e9a720c3673f6a1236a74d06ef1fb)
retains the initial screen, larger direct control, first integrated transfer,
probabilistic control and final transfer as separate cohorts. It includes all
samples/ranges, binary/WASM/source identities, verification receipts and final
validation log locations. Their effects are not pooled. Raw originals and frozen
source forests remain in ignored `scratch/random-source-20261116`; no remote
archive upload, public evidence publication or main delivery occurred.

### Why narrow the source change

The first seed-free integrated transfer retained the native Fisher–Yates effect
but gave a neutral browser Fisher–Yates result. Its separate probabilistic browser
control had a slower median, with overlapping ranges. Categorical membership
constructs a random cursor for one draw per row, so constructing a buffered cursor
there discards its other words. Restore that call's original unbuffered draw and
rejection sequence; only long-lived Fisher–Yates and exact-allocation cursors
consume four words per keyed block. No additional algorithm selector, dependency,
heap buffer or fallback is introduced. The engine identity remains
`chopper-v2-blake3-words-1`; block/domain construction and collision refinement are
unchanged. This structural simplification is not a claim that differences between
separate benchmark batches isolate its causal effect.

### Final complete-job transfer

Each native cell has one excluded warmup per variant and five alternating pairs;
each persistent bundled Chromium cell has one excluded warmup and three pairs.
The final baseline and candidate both receive seed-free Job inputs. The old
baseline's null input seed is omitted only when comparing its canonical generated
configuration; the engine records its internal entropy normally. Native clocks
cover CLI launch through exit/publication/cleanup. Browser clocks cover prepare,
confirmation, file export/marker close and worker retirement. Collection and
independent verification are outside both clocks. Native and WASI clocks and
separate recipe cells are not combined.

The native and browser harnesses are
[`benchmark-random-draws.py`](../../../scripts/benchmark-random-draws.py) and
[`benchmark-random-draws-browser.mjs`](../../../scripts/benchmark-random-draws-browser.mjs).
They reuse the existing independent CSV/manifest verifier for exact cases.
The additional probabilistic verifier checks exact fields, unique IDs, configured
allocation names/order, named-zero membership, stable within-allocation encounter
order, actual row/byte metadata, caps and conservation. It does not require exact
percentage quotas or pretend a finite diagnostic proves distribution quality.
Successful verified CSV payloads are removed with their hashes/receipts retained;
failed attempts and earlier unfavorable observations remain separate.

Elapsed reduction is `(baseline median - candidate median) / baseline median`.
Ranges are observed minimum/maximum, not confidence intervals or tail estimates.

| Runtime / final cell | Baseline median [range], s | Final median [range], s | Elapsed reduction |
| --- | --- | --- | --- |
| WSL native / 120,003-row resident Fisher–Yates | 0.17553 [0.17274, 0.18106] | 0.16442 [0.16238, 0.16627] | 6.3% |
| Persistent Chromium / same resident Fisher–Yates | 0.53557 [0.53487, 0.56738] | 0.52450 [0.50338, 0.53706] | 2.1% |
| WSL native / 250,003-row probabilistic control | 0.43659 [0.42327, 0.43867] | 0.44382 [0.42774, 0.46108] | -1.7% |
| Persistent Chromium / same probabilistic control | 1.89681 [1.86688, 1.89698] | 1.86694 [1.86644, 1.92798] | 1.6% |

The native Fisher–Yates ranges are separated in this final small cell and its
modest effect agrees with the earlier native passes. Browser ranges overlap,
so its small favorable median does not establish a robust hosted gain. The
probabilistic controls have overlapping ranges and small mixed effects, including
the retained native slowdown; no probabilistic speedup is claimed. The earlier
external-uniform controls showed no benefit. The larger direct confirmation did
not reproduce the initial direct regression, without establishing a direct gain.
Do not substitute the initial browser screen's 9.3% result for this final result.

These are warm WSL2/ext4 and disposable persistent OPFS development cells on the
recorded Rust/Node/WASI/bundled-Chromium builds. They do not establish native
Windows/macOS, installed-browser, physical SSD throughput, browser RSS,
25-million-row or scale performance. Analysis working reservations and logical
traffic, GNU-time RSS/CPU/OS I/O counters and elapsed clocks retain their distinct
scopes in the receipt.

### Product and verification boundaries

Seed input is removed from CLI, guided editing, UI and strict Job JSON. Both
`seed` and the skipped internal `random_seed` slot are rejected as wire inputs;
older saved jobs must remove those fields. Exported Job JSON contains neither.
The engine generates internal entropy under existing ownership admission and
keeps diagnostic identifiers without promising replay. Prepared confirmation
continues to execute its exact retained encoded snapshot. Resources contains one
expandable resource-budget section.

Current browser tests verify independently randomized Runs through conservation,
fields, group membership, quotas, lineage, caps and completion rather than shared
seeded bytes. Fixed internal test oracles remain for unchanged algorithms and the
new buffered-word/Fisher–Yates path. Process-kill checks bind an uncommitted writer
swap to the actual paused write's bytes/hash; a previous successful Run is not its
payload oracle. Already committed files and completion markers must still remain
byte-identical across restart and cleanup. Fresh recovered randomized jobs receive
independent semantic verification. Earlier failures are retained in validation
logs; this changes the obsolete cross-Run assumption without weakening committed
export preservation.

The receipt records the final same-source native/UI, real-worker browser graph,
lifecycle, interruption, base/shuffle-partition resource-contract and production
restore checks. Validation coverage remains local Linux/WSL and bundled Chromium;
no Windows local-CI receipt, merge or deployment acceptance is implied. The local
Tailscale preview is a development service, not a public release publication.
