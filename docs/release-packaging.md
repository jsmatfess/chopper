# Local release packaging

`scripts/package-release.py` assembles supplied artifacts without building,
launching Chopper, using the network, publishing or changing archive storage.
It requires Python 3.11+, Git and Node; Node runs the existing production WASM
export guard in `scripts/browser-artifacts.mjs`. Final release readiness belongs to the
[release record](https://github.com/jsmatfess/chopper/releases), exact-source validation/publication receipts
and [GitHub Issues](https://github.com/jsmatfess/chopper/issues). The
[focused candidate review](releases/0.2.0-review.md) and
[its acceptance plan](release-acceptance-plan.md) are historical records, not
approval for current-source builds. [Rollback](release-rollback.md) and
[evidence access](evidence-storage.md) remain separate contracts.

## Inputs and source identity

Create an owned local input manifest with `schema_version: 1`,
`packaging_schema_version: 1` and the release `version`. The retained
[candidate JSON](releases/0.2.0-candidate.json) describes the superseded focused
build; do not copy its source or artifact identities into a new release attempt.
Fill these assembly inputs from the actual frozen source and supplied bytes:

- `release_source_commit`, `release_source_tree`: full identities of the clean
  versioned source checkout; `dirty_source`: false. The command checks HEAD,
  tree, tracked and nonignored untracked status, and workspace/Cargo lock/UI
  package/UI lock version parity. It never chooses or freezes source itself.
- `native.windows_x86_64` and `native.linux_x86_64`: actual executable `bytes`,
  `sha256` and `target` (`x86_64-pc-windows-msvc` or
  `x86_64-unknown-linux-gnu`, respectively).
- `hosted`: actual `bytes` and `sha256` for every one of the seven production
  members. `packaging_inputs.hosted_directory` is an absolute directory path
  containing exactly those seven regular files, with no subdirectories or test
  assets. `packaging_inputs.windows_x86_64` and `linux_x86_64` are absolute paths
  to the supplied executable files. Symlink file inputs are rejected.

Input paths are local operational data; do not commit private locators. Hashes
are independently checked against bytes read, including WASM validation. Paths,
platform labels and hashes alone do **not** establish compiler/target identity,
executable version, successful validation or a build-to-source relationship.
Bind each supplied executable and hosted asset to exact runner build inputs,
commands, environment, toolchains and validation attempts under the
[runner contract](validation-runner.md) before approving any final receipt.
The executing assembler and shared browser guard must byte-match their tracked
files in the frozen source; their hashes are recorded as `packaging_tools`.
Source/vendor assets require complete inventories there. The assembler
checks source identity but does not derive transitive build provenance.

Each native ZIP includes `LICENSE`, `licenses/zip-2.4.2/LICENSE`, a versioned
`README.txt` from the [quickstart template](releases/native-quickstart.txt),
`THIRD-PARTY-NOTICES.txt`, `quickstart/customers.csv` and `quickstart/job.json`.
The assembler renders the README version and documentation tag from the release
manifest's version, after checking the source version metadata. Windows adds
`chopper.exe`. Linux adds `chopper` with Unix mode 0755.
The hosted build carries the same [retained notices](releases/native-usage.txt) in
its HTML source. The historical dependency inventory and source pins describe
the recorded 0.3.0 source. When refreshing dependency or toolchain notices,
preserve upstream texts, including their original whitespace.
Other files use mode 0644. ZIP paths match the predecessor root layout; no wrapper
directory is added. Hosted members are exactly `_headers`, `app.js`,
`engine-worker.js`, `engine.wasm`, `index.html`, `storage-worker.js`, `style.css`.
The hosted bundle is a separate package from native CLI artifacts. Final browser builds
must restore default production output per [browser guidance](browser.md).

## Commands and outputs

Use new output directories outside the source checkout or in its ignored scratch
area. No implicit builds occur and existing output directories are rejected.
The example requires a completed local manifest, not the null-filled template:

```sh
python3 scripts/package-release.py assemble --source /absolute/frozen/source --manifest /absolute/local-input.json --output /absolute/new-package-directory
python3 scripts/test-package-release.py
```

Assembly emits Windows/Linux/hosted ZIPs, `chopper-VERSION-artifact-receipt.json`
and `SHA256SUMS`. Receipt schema 1 retains candidate `native`, `hosted`,
`packages`, source and version fields; `packaging_schema_version: 1` adds exact
`package_members` sizes/hashes and the input manifest identity. It explicitly
leaves toolchains, build input inventories and validation attempts null rather
than copying unverified build assertions. Version/publication approval remain
false. `candidate_revision: 1` describes this new assembly attempt, not acceptance
or supersession of any earlier candidate. Each attempt needs a fresh directory.

ZIPs use fixed timestamps, sorted members and explicit Unix permissions. Identical
inputs on the same Python/zlib implementation yield stable bytes; cross-toolchain
compressed-byte reproducibility is not promised. All supplied bytes are captured
and checked before writing; source is rechecked after reading. Keep sources and
artifact inputs frozen throughout the command. Failed output directories are
retained for inspection, never reused or deleted automatically.

Assembly immediately reopens all archives, checks CRCs, exact unique safe member
inventories, regular-file modes, sizes/hashes and production WASM. It also checks
cross-references between native/hosted entries and member receipts and verifies
SHA256SUMS, which covers ZIPs and the artifact receipt. The JSON stdout records
receipt and SHA256SUMS identities for the external review record; SHA256SUMS does
not recursively hash itself. Preserve that stdout with the attempt.

For independent local rechecking, supply the trusted receipt SHA-256 from that
external record (do not derive it from an untrusted downloaded receipt):

```sh
python3 scripts/package-release.py verify --directory /absolute/package-directory --receipt-sha256 FULL_TRUSTED_RECEIPT_SHA256
```

Verification fails on extra output files, stale checksums, changed packages,
member/permission/CRC mismatches or forbidden production exports. It reads ZIP
members in place and supports earlier schema 1 receipts with two four-member
native archives.

## Extracted native smoke

On x86-64 Linux and native x86-64 Windows, run the actual release ZIP through
the [documented quickstart](../README.md#native-quickstart). Save each platform's
commands and results against the exact archive SHA-256. For a repeatable check
from the source checkout, give the smoke command the platform ZIP, its trusted
hash from `SHA256SUMS` and a fresh extraction path with an existing parent.
On Windows, use `python` and the Windows ZIP.

```sh
python3 scripts/package-release.py smoke --archive chopper-0.5.0-linux-x86_64.zip --sha256 FULL_TRUSTED_ARCHIVE_SHA256 --output /absolute/fresh-extraction
```

Smoke checks the checksum, archive inventory, executable version, exact CSV
records and order, and manifest counts and sizes. It also runs the saved Job
again with a fresh destination. The extraction and both Run reports stay on
disk for review. Record build provenance and actual host validation separately.
This small fixture establishes the quickstart journey. Scale acceptance and
publication approval require their own records.
