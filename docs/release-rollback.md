# Release rollback

Do not replace a release until its predecessor's exact assets have been retained
in the approved private R2 archive, downloaded and verified. Retain that archive
through publication smoke tests; completed snapshots have no automatic deletion.
The separate evidence-reader site is retired; it is not part of app rollback.

## Current next-release predecessor: 0.1.0

For [the current 0.2 release](releases/0.2.0.md), restore **released
0.1.0** using [its publication record](releases/0.1.0-publication.json) and
[artifact receipt](releases/0.1.0-candidate.json). The receipt's historical
candidate status is superseded by the publication record. The sections below
about the first native release and older hosted package describe the completed
0.1.0 rehearsal; they do not waive next-release predecessor acceptance.

The current hosted predecessor is Pages project `chopper`, production branch
`master`, deployment `8d497a07-be6e-43e2-abae-67f05f097ae2` at
`https://8d497a07.chopper-1rx.pages.dev`. Release source is
`7d78706c432f34742bbc29c17be9261002a6816a`; recover exact published assets,
not a rebuild from that commit or today's source. Published Windows executable
SHA-256 is
`771a33f8cc34e6bf871bdbe1349669251adc30d48c4fa51d4a585cf75a12409b`.
There is no published 0.1.0 Linux package; do not relabel a new Linux build as a
retrieved predecessor or infer Linux runtime rollback coverage.

Preparation on 2026-11-05 retrieved all four v0.1.0 GitHub assets: Windows ZIP,
hosted ZIP, artifact receipt and SHA256SUMS. API SHA-256 digests, ZIP CRC/member
sizes/hashes, receipt and SHA256SUMS match. Parent retains the read-only local
record at `scratch/release-next-20261105/predecessor/retrieval-verification.json`.
This records the original local GitHub retrieval.
Parent subsequently located private operations `release-publication-2026-10-29.md`,
which records the retained 98-member, 11,120,640-byte archive of exact published
0.1.0 assets and source/control records with historical independent reader
readback. On 2026-11-12, a fresh private scoped reader downloaded and safely
restored that existing archive. Outer identity and all 98 members verified; the
four release assets match the retained GitHub identities, both ZIPs pass CRC and
exact member checks, and the receipt and SHA256SUMS agree. The
[sanitized readback record](releases/0.1.0-private-readback-2026-11-12.json) omits
private locators and credentials. No remote objects changed. Do not create a
replacement archive or repeat uploads.
The isolated native Windows two-row strict-cap runtime rehearsal passed with
that executable, exact CSV parity and three manifest records; local receipt is
`scratch/release-next-20261105/predecessor/native-runtime-receipt.json`.
This is a narrow native runtime check, not real-dialog, Linux or device-fault
recovery.

The [isolated hosted rehearsal](releases/0.1.0-hosted-rollback-2026-11-07.json)
subsequently passed on Linux/WSL with bundled Chromium 156.0.8078.4. It served all
seven exact retained GitHub assets with verified hashes and COOP/COEP, then used
the public Run action to export two exact 33-byte CSVs under a 40-byte cap and
read back the valid completion marker. Input File and output OPFS handles were
injected; this is not actual system-dialog or installed Windows acceptance.
The browser/server closed, capture readers reached EOF and joined, and the
original Linux reservation closed after quiescence. Completed exports remain
retained. An earlier controller cleanup assertion failed on a SIGTERM exit; its
failed result and administrative owner recovery remain separate.

Fresh private scoped-reader readback is complete. The restored assets match
the exact bytes used by the isolated rehearsals, so their recorded runtime
coverage remains applicable. Neither readback nor rehearsal establishes
production restoration or approval to deploy.

Before replacing 0.1.0, recover those exact four assets and required restoration
metadata from the existing approved private R2 archive under the existing
[storage policy](evidence-storage.md#no-domain-reader-and-retention-decision).
Use a separate scoped reader to download into a fresh owned directory; verify
outer SHA-256, ZIP CRC, safe expected member names, sizes/hashes and receipt/
SHA256SUMS consistency. Keep private locators and credentials in private
operations. No new archive deletion, history cleanup or visibility change is
part of next-release preparation.

For native restoration, extract the verified Windows ZIP, retain its licenses
and README, stop the current app and keep both versions/receipts. Run the old
executable from an isolated directory against a small CSV, verify exact fields,
strict row/byte caps and manifest before returning it to use. Do not overwrite
an active executable. For hosted restoration, extract the exact seven-file ZIP,
verify every member against the 0.1.0 receipt, serve with COOP/COEP in isolation,
and verify a real successful small export plus committed completion marker.
The native rehearsal above does not satisfy this hosted step.

Production restoration requires separate approval for the concrete old bytes
and confirmed current app project/branch. Follow the deploy command below with
the verified restored 0.1.0 folder, record the new deployment ID, verify every
served body and effective headers, then repeat export/marker smoke. It creates
a new deployment of the old bytes. Do not restore the pre-0.1.0 package by
mistaking the historical deployment below for the current predecessor.

Retain the 0.1.0 recovery archive and older historical archives through publication
smoke and the retention review; completed snapshots have no automatic deletion.
Rollback does not reverse saved configurations or previously written outputs.
No isolated rehearsal establishes power-loss or device durability guarantees.

## Historical pre-0.1.0 hosted predecessor

The retained predecessor is Pages project `chopper`, production branch
`master`, deployment `31da2710-941c-4e0c-8e5d-a21ee3646315` at
`https://31da2710.chopper-1rx.pages.dev/`. Its source record names commit
`9f3d408918002d7fd8d9d7122ffd3751374621b6` **with uncommitted changes**: that commit
alone cannot rebuild the deployed package.

The seven-file package identities are retained in
[the deployment record](evidence-originals.md#sha256-554746247a9c6f78a9a76095e31f95c4e67f98f765151e550d2f1bec68adab64 "Original: docs/benchmarks/current-build-pages-deployment-2026-10-22.json").
Preparation downloaded the six served files from the pinned deployment and
verified their full sizes and SHA-256 hashes. `_headers` was reconstructed from
the retained build recipe and matched its pinned hash. The private operations
repository holds the archive locator, retrieval receipt and restoration tools.

To restore, retrieve that immutable private archive into a fresh directory,
verify the outer SHA-256 and every member, and serve the restored hosted folder
in isolation with COOP/COEP headers. Verify asset hashes and a small export before
touching production. Never rebuild the previous package from today's source.

After release review, upload the restored seven-file folder using the existing
authenticated Wrangler installation:

```sh
node PATH_TO_WRANGLER_JS pages deploy RESTORED_HOSTED_FOLDER --project-name chopper --branch master
```

Record the new deployment ID, verify every served asset against the predecessor's
receipt, and repeat the publication smoke test. This creates a new deployment of
the old bytes; it does not change the separate evidence site.

## Historical first-native-release context

For 0.1.0, the owner confirmed it was the first native release. There was no
previously distributed native version to restore. An incumbent local executable was
preserved before the new build, with its exact hash, as an unverified local
reference; it is not a previously distributed release.

For future releases with an established predecessor, retrieve and hash-check the archived executable
and any required assets, close the current app, restore those exact files to the
installation location, and run an isolated small job before returning to use.
Retain both versions and their receipts. Do not replace an active executable.

## Historical rehearsal limits

The predecessor predates subsequent direct-Run, resource/reproducibility and
ownership work. Preserve its recorded limitations and test scope. A rollback
does not undo saved-configuration changes or CSV/output changes. Do not claim
device-fault, power-loss or other-platform recovery from an isolated rehearsal.
The owner completed real-picker acceptance and approved 0.1.0. Its verified
[publication record](releases/0.1.0-publication.json) identifies the current release.
Repeat acceptance/review for later releases; retain this predecessor archive.
