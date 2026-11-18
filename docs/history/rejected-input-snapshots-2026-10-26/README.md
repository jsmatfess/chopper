# Rejected direct parsed-input sources

These are byte-for-byte R25 pre-removal snapshots, including the E3 R1-R17
construction, admission, corruption and lifecycle corrections. They are historical,
not active engine modules. `source-identities.json` maps every exclusive module
back to its original path with SHA256. The complete current integration tree is
`.tools/e3-removal-20261026-r25/baseline/`, with full tracked/nonignored-untracked
and vendor identity manifest `baseline.json`, Git worktree/index patches and status.
It includes all manifests, Cargo.lock, shared consumers, tests, scripts and docs.
The pre-rebuild hosted package is `hosted-before/`, sealed by `extra-identities.json`.

Replay must use a separate matching historical source tree and its original lockfile,
complete ZIP/Zstandard vendors, Rust/Arrow versions, features and native/WASM pins.
Restore the archived files to their original paths in that tree. Do not restore
snapshot feature wiring into the current checkout to run old commands. Historical
command blocks and raw JSON remain unchanged. In particular, R19/R20 task-driver
path dependencies point into the old root: building them against today's checkout
fails because `experimental-input-snapshots` and `engine::snapshots` are removed.
Use the matching preserved source layout/build inputs or retained pinned executable.

R25 `replay-inputs/` and `replay-identities.json` retain original R19/R20 drivers,
lockfiles, experiment generators and fixtures. `prior-handoff-identities.json`
retains prior ledgers/reports and pin identities, without claiming unknown IDs.
The R23 approved review is copied into `replay-inputs/`; its 6059 pins reference
retained old source/binary/artifact paths. Old target trees are not duplicated.
Those pinned immutable paths and their matching source/vendor/toolchain/feature
records are required for binary replay. R19/R20 generator originals remain
creation provenance; the R23 UTF8-keyword-modified copy is not the original.
R24 raw/report copies are navigable from the maintained performance decision and
source map; relative links in those exact-byte copies resolve at their original
`.tools/e3-measure-20261026-r24/` origin, not at the copy location.

Migration: use ordinary direct CSV Job input and preparation/execution. Removed
Rust imports fail at compilation; native/browser Cargo feature requests and browser
build wrappers reject the removed control explicitly. No runtime selector existed.
Shared CSV parsing, decoded/compact intermediate storage, spill-block codecs,
comparison sorting/external merge, generic resource/cancellation/publication tests
and all Analysis/shared-payload ownership remain live and unchanged.

See [decision and limits](../../performance.md#direct-input-snapshot-rejection-and-removal-2026-10-26).
