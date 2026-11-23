# Durable evidence storage and publication boundaries

The separate public evidence website is retired for 0.2. Its source and CI job
have been removed; the Chopper hosted app is separate. Former reader URLs and
manifest identities in historical records describe past publication and are not
current retrieval instructions. Reader retirement does not authorize deletion
of R2 objects or the private archive. Preserve original bytes, hashes and
verified private-reader access under the archive contract below.

The 0.1 migration and history cutover were completed; see its
[release review](releases/0.1.0-review.md) and the
[fresh private predecessor readback](releases/0.1.0-private-readback-2026-11-12.json).
A new public repository release still requires its own content/history review.

The dated decision brief and inventory below preserve the 2026-10-28 proposal
and later provisioning observations. Statements such as “migration remains open”
in that historical material are not a current backlog. Track remaining work in
[GitHub Issues](https://github.com/jsmatfess/chopper/issues), preserve original
evidence bytes, and verify private-reader access before relying on an archive.

## Recommendation and observed scale

R2 Standard is selected for public evidence links and repeated retrieval. The
provider comparison below records the selection rationale. Account ownership,
domain, retention and backup configuration still need implementation. Use a
separate private R2 archive for material unsuitable for publication. All storage
destinations below are approved; individual artifacts still need classification
before public access is enabled.

## Approved storage destinations

The owner approved all of these recommendations on 2026-10-28. The resource names
are proposed implementation names, not claims that resources already exist.
Track implementation and pre-release gates in GitHub Issues.

- **Public R2 Standard bucket (`chopper-evidence-public`):** Store raw benchmark
  results, validation logs, failed/incomplete attempts, complete historical
  replay/source bundles and publishable review transcripts. Use content-addressed
  objects behind a stable evidence reader endpoint. Retain checksums, provenance,
  retrieval instructions and compact readable summaries in the main Git repo.
- **Private R2 bucket (`chopper-archive-private`):** Store unsanitized evidence,
  sensitive environment snapshots and confidential transcripts. Disable public
  access and use separate scoped credentials. Store verified repository backups
  here as distinct content-addressed snapshots alongside migrated private evidence.
- **Private GitHub documentation repository (`chopper-internal`):** Keep
  human-maintained operational notes, administrative decisions and private
  handoffs worth retaining. Store large attachments in private R2 and link them.
  Keep public technical decisions and architecture documentation in the main
  repo. This private archive does not create another active project backlog.
- **GitHub Issues:** Keep actionable issues and specs in `jsmatfess/chopper`
  as the sole active backlog and specification tracker. Keep confidential administrative notes in the private documentation
  repository rather than public issues.
- **Local ignored storage:** Keep Python bytecode, build caches, toolchains,
  generated graphs, scratch output and deployment state local. Discard disposable
  outputs; archive only files selected for evidence or replay before cleanup.
- **Password manager and GitHub Actions secrets:** Keep credentials and upload
  tokens in a password manager for human access and Actions secrets for
  automation. Do not put secrets in Git, documentation attachments or public R2.
  See [Actions secret storage](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).
- **Main Git repository:** Retain required vendor patches/licenses, lockfiles,
  small synthetic fixtures, harnesses, current documentation, public decision
  summaries, evidence manifests and the committed native UI bundle. Keep hosted
  deployment output generated under the existing build contract.

Approval of these destinations records the implementation direction; provisioning,
migration, verification and cleanup remain unfinished. No further provider
selection is required for this plan. Exact resource names, domain, account and
backup location are implementation details to record during setup.

### No-domain reader and retention decision

This subsection records the historical reader deployment, now retired.

The owner requested no custom domain and confirmed no automatic deletion.
Use a separate Cloudflare Pages evidence index with a `pages.dev` address and
a Pages Function bound only to `chopper-evidence-public` for large downloads.
The initial reader is deployed at https://chopper-evidence.pages.dev/; its
then-current repo-native source and commands (now retired) are independent
of the Chopper app. It publishes two reviewed originals and one explicitly synthetic
DOWNLOAD acceptance fixture (33,554,432 bytes), reproducible from the small
repo-native generator. The 2026-10-28 Pages/R2 acceptance passed 13 focused tests
and 29 unauthenticated HTTP checks, including a streamed full SHA-256 match,
HEAD, first/middle/suffix ranges, 416/304/405 and unknown/known-private-key 404.
Production configuration binds only the public bucket; both direct R2 development
URLs remain disabled. The fixture is not benchmark/timing/scientific evidence;
one 32 MiB transfer does not establish broader scale. Retained report/logs are in
`scratch/pages-large-2026-10-28`; no originals or remote objects were removed.
Pages static assets have a 25 MiB per-file limit, so store large evidence in R2
and stream it through the Function rather than packaging it into the site.
Keep the private archive unbound and inaccessible through the public reader.
[Pages limits](https://developers.cloudflare.com/pages/platform/limits/),
[R2 bindings](https://developers.cloudflare.com/pages/functions/bindings/#r2-buckets).

Do not configure expiration of completed evidence or backup snapshots. The
existing bucket lifecycle rule only aborts incomplete multipart uploads after
seven days; it does not expire completed objects. Retention lock settings and
manual deletion procedures remain separate from automatic expiration.

The owner subsequently selected **Cloudflare-only storage and backup**. Backblaze
and the unused restic/B2 wizard are outside the current plan; no additional
provider, device or client-side encryption password is required. Keep local
originals and upload a distinct repository/evidence backup to private R2, then
download and restore-check its complete selected contents before cleanup. R2
automatically encrypts stored objects with Cloudflare-managed keys and protects
transfers with TLS; this is not client-side password encryption.
[R2 data security](https://developers.cloudflare.com/r2/reference/data-security/).

Record the backup's exact source scope, Git history/refs, staged and dirty state,
untracked inputs, selected ignored evidence, exclusions and restore results.
Do not call a two-file pilot a full pre-cleanup backup. Deletion and history
cleanup remain deferred until the required private R2 restore verification and
migration/reference checks pass. Same-account backup does not provide protection
against losing the Cloudflare account; the owner has chosen that current scope.

A selected repository snapshot now passed actual private R2 upload, fresh
download and restore verification: 4,759 selected paths, Git integrity, refs,
index, status and staged/unstaged diffs matched. The 265,748,131-byte gzip
transport reproduced the exact 511,877,120-byte frozen TAR after decompression.
The snapshot includes current repository state and explicitly selected ignored
evidence; it excludes secret/local Git configuration, separate repositories,
unselected ignored caches/evidence and unavailable historical inputs. This is
not a claim of complete historical replay coverage or completed migration.
The exact locator, checksums, selection and recovery tool are retained in the
private operations repository; local receipts are under
`scratch/cloudflare-backup-2026-10-28/frozen-01/` and `compressed-transfer-01/`.
No originals, snapshots or history were deleted.

The first reviewed E5 public derivative is also served separately from its private
raw original; its then-current pinned manifest, recipe and public-only hydration (now retired)
make fresh site builds independent of private/scratch inputs. Four downloads now
pass full unauthenticated readback and the shared intended-reader verifier;
39 HTTP checks include private raw SHA denial. This derivative reuses existing
observations and closes no broader replay, migration or backup gate. Retained
acceptance is `scratch/pages-e5-derivative-20261028`; no originals were removed.

### Provisioning progress

R2 Standard buckets `chopper-evidence-public` and `chopper-archive-private` now
exist in the existing deployment account, with automatic placement reporting
ENAM. Both have `r2.dev` disabled and no custom domains; the future public bucket
is not public yet. The private `jsmatfess/chopper-internal` repository exists and
its bootstrap README was verified by exact downloaded bytes. Operational account
metadata and command logs stay in local/private records.

The separate Pages reader now serves two reviewed public originals (2,983 bytes)
through a public-bucket-only binding. Full unauthenticated downloads matched
their SHA-256 identities; GET/HEAD, conditional/range responses and denial of a
known private-archive SHA were checked. Cloudflare's downloaded production
configuration contains only the public R2 binding. Both buckets retain disabled
`r2.dev` access and no custom domains. See the
then-current versioned public manifest and reader README (now retired)
for exact identities and current coverage. This small pilot does not establish
large-object streaming acceptance or complete migration. Scoped automation/private
reader credentials and the verified private R2 repository backup remain pending.
No automatic deletion is the selected
retention policy. Initial
private transfer/readback work does not satisfy the separate intended-reader,
complete-migration or history-rewrite gates. Keep originals until every required
verification and reference check passes.

The first private pilot transferred two content-addressed originals and verified
their exact downloaded bytes, including all 7,000 regular members of the existing
replay ZIP. The same privileged uploader credentials performed readback; a
separately scoped reader remains unverified. Detailed operational receipts stay
in the private documentation repository and local retained logs. No original
was deleted, and no Git history was rewritten.

The local inventory observed at 2026-10-28T10:01:46Z found 101,000,031 logical
bytes in 667 benchmark-directory files, including 276 untracked files. Ignored
scratch held 641,771,843 bytes. A metadata-based classification found another
2,289,485,747 bytes of potential raw evidence in scoped `.tools` directories.
Together these are about 3.03 decimal GB before deduplication or compression,
not a verified migration set. Replay binaries, archives and source snapshots
need separate retention review; build caches are not automatically evidence.

The dated local inventory is
`scratch/evidence-storage-options-2026-10-28/inventory.json`, SHA-256
`22673565ae747021efa2b472782b79fc555461d063f187bef8642f44484143e4`.
It records paths, Git classification, exclusions and metadata heuristics; it does
not contain a content hash for every original. Its companion research draft
retains further operational sources. Active local work can change the sizes.
This brief preserves the compact findings; a migration must create a fresh,
content-verified manifest rather than depend on an ignored scratch directory.

Unique reachable Git blobs totaled 181,973,044 logical bytes at the inventory
snapshot. That differs from current-file size, compressed object storage and
clone traffic. Removing current files cannot remove reachable historical blobs.
Local and remote history cleanup is now included in the pre-release scope where
feasible; the sequence and limits are recorded below.

## Provider comparison

USD list prices checked 2026-10-28; allowances are account-wide, may already be
used, and exclude optional services, taxes, extra versions and replicas.

- **R2 Standard:** $0.015/GB-month, with 10 GB-month free. Includes one million
  Class A and ten million Class B operations monthly; excess costs $4.50/million
  writes and $0.36/million reads. Internet egress and Standard retrieval are free.
  At roughly 3 GB, unused allowances could cover storage and modest requests.
  Standard has no minimum retention duration. Use scoped credentials for private
  objects or a custom domain for durable public links. Bucket locks are
  administrator-removable; do not assume S3 versioning parity. Maintenance is
  bucket/credential management, optional DNS, billing and retrieval checks.
  [Pricing](https://developers.cloudflare.com/r2/pricing/),
  [public access](https://developers.cloudflare.com/r2/buckets/public-buckets/),
  [locks](https://developers.cloudflare.com/r2/buckets/bucket-locks/),
  [compatibility](https://developers.cloudflare.com/r2/api/s3/api/).
- **B2 pay-as-you-go:** starts at $6.95/TB-month with no minimum file size or
  storage duration. Free egress covers up to three times stored data; additional
  transfer costs $0.01/GB. Ordinary A/B/C transactions are free; event-notification
  transactions have separate charges. Public/private buckets, scoped keys,
  version lifecycle and Object Lock support archival use. Review retention and
  version deletion carefully; compliance locks impose irreversible retention.
  Maintenance includes access, lifecycle and download-budget review. Confirm the
  actual account offer because some secondary documentation retains older rates.
  [Pricing](https://www.backblaze.com/cloud-storage/pricing),
  [transactions](https://www.backblaze.com/cloud-storage/transaction-pricing),
  [access](https://www.backblaze.com/docs/cloud-storage-buckets),
  [retention](https://www.backblaze.com/docs/cloud-storage-object-lock).
- **S3 Standard:** regional storage, request and internet-transfer charges apply.
  The researched us-east-1 offer was $0.023/GiB-month, about $0.065/month for
  3.03 decimal GB before requests. Writes cost $0.005/1,000 and reads
  $0.0004/1,000. Internet transfer can dominate repeated downloads; confirm the
  shared free allowance and regional rate when provisioning. Private IAM access,
  deliberate public policies, versioning and Object Lock provide flexible
  retention at greater configuration cost. Prefer Standard initially over tiers
  with restore workflows or minimum-duration charges.
  [Pricing](https://aws.amazon.com/s3/pricing/),
  [regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/us-east-1/index.json),
  [access and lifecycle](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html),
  [Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html).

## Authorized migration contract

Keep methodology, harnesses, workload definitions, acceptance criteria, compact
findings and small regression fixtures in Git. Keep compact replay instructions
and source identity manifests in Git; complete historical replay/source packages
may move to verified R2 objects. Inventory
existing evidence as well as new runs, including failed and incomplete attempts.
Do not use expiring CI artifacts as the durable copy.

A versioned Git manifest must retain original path aliases, run/artifact IDs,
byte lengths and SHA-256, stable bucket/key/version locations, access method,
source/build/vendor/features/harness identities, workload/configuration/commands,
outcome and exclusions. Record original-file and archive-container hashes
separately, including member identities. Unknown metadata stays unknown. Store
stable private locators rather than expiring signed URLs; never store secrets.

Freeze the selected originals, upload under content-addressed keys, then download
every object independently through the intended reader access path. Verify full
bytes and every archive member against the manifest; upload success, HEAD and
ETag alone are insufficient. Preserve originals until retrieval, catalog/link
adaptation and reference checks pass. Keep the verified private R2 backup through
cutover. Review lifecycle rules so they cannot silently expire failed evidence.

The historical no-custom-domain deployment used the separate
`chopper-evidence.pages.dev` reader; that reader is retired. Retain disabled direct
`r2.dev` access. R2 documents direct access modes in its
[public bucket guide](https://developers.cloudflare.com/r2/buckets/public-buckets/).
Separate public evidence from private originals at the bucket/access boundary;
never upload credentials or private inputs to the public bucket. Record account
ownership, placement, retention and private R2 backup settings during setup.
Migration is complete only when catalog/export/audit consumers can resolve and
verify external artifacts, documented replay remains possible, and new runs use
the same storage contract. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the
active release gates.

## Local manifest tooling (schema version 1)

### Archived-original alias resolution

[The versioned alias registry](evidence-registry.v1.json) maps selected benchmark
originals to exact members of private, content-addressed TAR bundles. It records
original bytes/SHA-256 separately from bundle bytes/SHA-256. It does not replace
the source/build/provenance manifests retained inside the private archive.
Current local originals remain in place: independent scoped-reader verification,
reference migration and history cutover are still open.

`scripts/evidence-resolver.py` supports explicit authenticated hydration through
an existing Wrangler installation:

```sh
python scripts/test-evidence-resolver.py
python scripts/evidence-resolver.py check
python scripts/evidence-resolver.py hydrate --wrangler PATH_TO_WRANGLER_JS
```

For the separate bucket-scoped S3 reader, install the optional SDK and supply
`R2_ENDPOINT`, `R2_READ_ACCESS_KEY_ID` and `R2_READ_SECRET_ACCESS_KEY` privately in
the process environment, then run:

```sh
python -m pip install -r scripts/requirements-evidence.txt
python scripts/evidence-resolver.py hydrate --s3
```

The explicitly dispatched `Private evidence retrieval` Actions workflow uses
`CHOPPER_R2_ENDPOINT`, `CHOPPER_R2_READ_ACCESS_KEY_ID` and
`CHOPPER_R2_READ_SECRET_ACCESS_KEY` repository secrets. It has read-only repository
permissions, no pull-request trigger and no evidence-artifact upload. Configure
only a bucket-scoped read-only private-reader credential there. Uploader keys
remain separate. An unconfigured or unrun workflow does not establish retrieval.

Hydration verifies the complete downloaded bundle and rejects nonregular or
unsafe member names. Every copy of a repeated content-addressed member must
match its SHA-256 address. Hydration verifies each selected original's size and
SHA-256 before caching it under ignored `scratch/evidence-cache`. Existing mismatches
fail rather than being replaced. Interrupted writes can leave a rejected partial
cache entry; retain that failure and use a reviewed fresh cache/recovery procedure.
The catalog, lossless exporter and corpus audit resolve missing aliases from
that verified cache without implicit network access. `--restore-aliases` after
`hydrate` additionally restores exact files for older consumers, including the
decision-table analysis; it refuses differing existing originals. Never commit
hydrated confidential originals to a cleaned public repository.

The initial transfers used privileged Wrangler OAuth. A separate S3 reader now
passed live private-write denial, public-bucket read denial, exact bundle/member
verification and all 7,000 nested replay-ZIP member hashes. The three repository
reader secrets are configured; the new Actions workflow itself has not run.
The separate scoped uploader also passed authenticated access to both approved
buckets and a retained synthetic private write with independent-reader readback.
Cloudflare object-only R2 credentials use the S3 API, whereas Wrangler uses the
Cloudflare REST API; they cannot simply be substituted in that command.
[Cloudflare authentication](https://developers.cloudflare.com/r2/api/tokens/)
documents that boundary. Final migration/reference and history cutover remain
separate release gates. The selected current source/Git snapshot passed fresh
scoped-reader download and full restoration, including refs/index/status/diffs;
its exact scope, exclusions and locator remain in the private operations record.

The regular evidence CI job restores originals only when they are absent, then
runs the same full checks. Forks do not receive private-reader credentials:
their historical-evidence check is blocked rather than silently passed and needs
trusted maintainer validation. Native/core/UI builds do not depend on private
historical evidence. Review that access limitation before public cutover.

### Local scan and receipt commands

`scripts/evidence-migration.py` uses Python 3.10+ and the standard library. It
does not upload, download, delete, configure accounts or change the historical
catalog/exporter. Select and classify originals explicitly; the dated inventory
is navigation, not a migration selection. Migration and release gates remain open.

Create `scratch/evidence-plan.json`; this synthetic example demonstrates the
format, not a decision to migrate the fixture:

```json
{"schema_version":1,"artifacts":[{
  "id":"example-fixture","aliases":["examples/customers.csv"],"kind":"file",
  "metadata":{"run_id":null,"outcome":null,"failure":null,"incomplete":null,
    "exclusions":null,"source":null,"build":null,"vendor":null,"features":null,
    "harness":null,"workload":null,"configuration":null,"commands":null},
  "storage":null
}]}
```

```sh
python scripts/evidence-migration.py prepare --root . --plan scratch/evidence-plan.json --output scratch/evidence-manifest.json
python scripts/test-evidence-migration.py
```

The frozen v1 manifest has exactly `schema_version` and `artifacts`. Each artifact
has `id`, exact original `aliases`, `original: {bytes, sha256}`, `metadata`,
`container: {kind, identity: {bytes, sha256}, members: [{path, bytes, sha256}]}`
and `storage`. `kind` is `file`, `zip` or `tar` (including compressed TAR).
Container identity equals original identity: archives are scanned as originals,
never repacked or normalized. Plain files have no members. Directory entries,
links, devices, sparse files, traversal, case/Unicode collisions and duplicate
archive names are rejected without extraction. Rejected originals remain intact
and need a separately reviewed format extension. Scans read every member; provide
enough local memory/time. Use frozen inputs: ordinary concurrent changes are
checked, but scanning is not a snapshot or defense against a hostile writer.

All fourteen metadata keys above are required; unknown values stay null.
`outcome` is null, `passed`, `failed`, `incomplete` or `excluded`; `incomplete`
is null or Boolean (an incomplete outcome requires true). Retain explicit failure
details, exclusions, workload, configuration, features and exact commands as
reviewed JSON values; nothing is inferred. Source, build, vendor and harness are
null or nonempty lists of `{path, bytes, sha256}` references to selected original
aliases. Include the original identity record or complete replay/source bundle
as another artifact. References must resolve to matching manifest bytes. Original
commit/build identities remain in those preserved records after any future
rewrite; today's checkout cannot substitute for missing historical provenance.
Aliases share an artifact only if their complete identities match. Same-hash
artifacts may retain separate metadata/IDs; no automatic dedupe or pooling occurs.
Sanitized derivatives need separate IDs and explicit relationships in retained
provenance records, never replacement original checksums.

`storage` is null until an actual destination is recorded. Otherwise it has exactly
`bucket`, `key`, `version`, `access`, `reader`: bucket is the approved
`chopper-evidence-public` or `chopper-archive-private`; key is `sha256/<full original
SHA256>`; version is that SHA256 (a content version, not an R2 versioning claim).
Public access is `public-https` with an HTTPS reader URL at `/<key>`; the historical
reader was `https://chopper-evidence.pages.dev` under the no-custom-domain decision.
That URL remains valid as historical manifest metadata, not a live service promise.
Private access is `private-authenticated` with reader
`r2://chopper-archive-private/<key>`. Queries, fragments, URL credentials and
public `r2.dev` readers are forbidden. Different actual bucket names need a
reviewed schema update. Review free-text metadata and raw contents for secrets
before Git/publication; syntax validation is not a secret scan.

After independently obtaining objects, write a receipt listing **every** artifact
ID. For a local rehearsal copy the fixture to a separate
`scratch/evidence-downloads/customers.csv`, then create `scratch/evidence-receipt.json`:

```json
{"schema_version":1,"manifest_sha256":"<SHA256 of exact manifest file bytes>",
 "reader":"local","objects":{"example-fixture":{"path":"customers.csv","reader":null}}}
```

```sh
python scripts/evidence-migration.py verify --manifest scratch/evidence-manifest.json --downloads scratch/evidence-downloads --receipt scratch/evidence-receipt.json --output scratch/evidence-verification.json
```

For real retrieval use `reader: "intended-reader"` and each object's exact manifest
storage reader instead of null. This is the operator's access-path attestation;
the local verifier cannot prove how a file was downloaded. Retain independent
download/access logs privately as appropriate. Verification rehashes every object
and archive member, validates provenance references and rejects missing objects,
stale manifest receipts and reader mismatches. The separate report records
`manifest_sha256`, canonical parsed `receipt_sha256`, UTC verification time,
scope, result and per-object results. Only a complete successful check creates a
report. Errors return nonzero; preserve exit codes/failure logs separately.
Outputs must be new paths, preserving earlier attempts. Rerun after any manifest,
receipt or downloaded-byte change: old reports are historical observations, not
proof of current retrieval. Local reports do not establish external retrieval,
upload success, reference adaptation or migration completion. Catalog/export and
reference integration remain a separate migration step.

External prerequisites remain the owning R2 account, actual buckets, stable
custom domain, scoped credentials, retention, classification and independent
verified backup. This tool neither requires nor handles credentials.

## Local and remote history cleanup

Migrate and verify first. Inventory historical path aliases, branches, tags,
worktrees and owned remote refs before preparing a path-filtered rewrite in a
disposable mirror. Preserve the dirty working tree independently; do not run a
destructive rewrite in the active checkout. Retain a verified private pre-rewrite
backup and an old-to-new commit map. Historical build/source hashes stay original:
rewritten commit IDs are aliases, not newly measured builds. Audit pinned commit
links, release tags, archived replay inputs and tooling before remote cutover.

Coordinate the write freeze, affected PRs, branch protections and updates to
owned remote branches/tags. Replace or clean local clones/worktrees and stale
refs/reflogs so old history cannot be accidentally pushed back. Reclaim local
unreachable objects only after fresh-clone, retrieval and provenance checks and
the backup retention checkpoint. Record reachable blob sizes separately from
compressed local storage and observed remote clone size.

GitHub's [history-removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
describes changed commit IDs/signatures, collaborator coordination and references
that a force push cannot remove. Host-owned PR refs, caches, forks and other
clones may retain objects; remote garbage collection is host-controlled. Request
host assistance where supported and record unresolved retention. If secrets are
found, revoke/rotate them first. Cleanup is not a guarantee of erasure from other
people's copies. If an in-place rewrite cannot meet the publication requirement,
use a clean public import with the original history retained privately, recording
the loss of public history and how provenance is resolved. Resolve that choice
before release rather than treating current-tree deletion as history cleanup.

## Public repository review

This is a scoped working-tree and Git-index review on 2026-10-28, including
nonignored untracked files. It is not a complete secret scan or historical
content audit. Counts are snapshots and can change during active local work.
The actions below are approved recommendations tracked in GitHub Issues, not completed
removals or additional checklists.

A limited text-pattern pass found local-path matches in 82 files, including
validation records such as `analysis-diagnostics-linux-validation-2026-10-23.json`.
It found no matches for the checked AWS access-key, GitHub token and private-key
header patterns. This does not establish that the repository or its history is
free of secrets. Email-pattern matches were confined to vendor metadata/source
in this pass; preserve upstream attribution rather than removing it as personal
project data.

### Generated files and local tools

Current-tree cleanup completed after the inventory: 28 tracked bytecode files
were removed from the Git index with their local bytes preserved. Root ignore
rules now cover `__pycache__/`, `*.py[cod]` and generated `/output/`. This does
not remove historical blobs or complete the broader hygiene/migration review.

`scripts/__pycache__/` contains 35 bytecode files totaling 509,242 bytes; 28 are
tracked. Remove them from the index/history cleanup set and ignore Python caches.
They are disposable local build output and need no durable storage. `output/`
exists locally but is neither tracked nor covered by the current root ignore
rules; inspect its contents and ignore generated job output before broad staging.
Retain an output only if it is deliberately selected as evidence, then use R2.

`.tools/`, `scratch/`, `.wrangler/`, `target/`, `ui/dist/` and `graphify-out/` are
already ignored. Keep caches, toolchains, deployment state and local graphs local;
select irreplaceable logs, binaries, source snapshots and replay fixtures for the
verified archive before cleaning them. Ignored does not mean backed up. The
earlier inventory's roughly 2.29 GB of potential `.tools` evidence needs content
review, not wholesale upload of build caches.

`.codex/hooks.json` invokes optional RTK for Bash and contains no absolute path or
credential in the inspected file. It can remain if it is a shared project
convention; personal overrides belong in user-local configuration. `RTK.md` and
the Graphify/Context Mode setup docs are useful contributor guidance when kept
portable. Tool-specific names alone are not a reason to remove them.

### Evidence, replay packages and operational records

`docs/benchmarks/` currently contains 668 files totaling 101,457,619 bytes, with
277 untracked. Large raw JSON/JSONL/log records, repeated validation snapshots and
review ledgers belong in R2 with manifests and compact findings in Git. For
example, `e3-direct-r24-2026-10-26-history-before.json` alone is about 4.62 MB.
Preserve failed and incomplete records; storage cleanup must not select only
successful evidence.

`docs/history/` contains 17 files totaling 320,850 bytes, including rejected source
snapshots and replay identities. These are not inherently inappropriate for a
public repo. Keep short decisions/replay instructions and identity maps; move
complete rejected implementations and large future replay bundles to R2
when their integration inputs are preserved and verified too. Existing replay
instructions reference ignored `.tools` baselines, drivers, binaries and lockfiles;
archiving only the visible source fragments would leave replay incomplete.

`docs/maintainer/current-state.md` contains dated operational handoffs, and portions of
`docs/performance.md` contain detailed execution/review chronology. Keep current
behavior, limitations, methodology and compact decision rationale public in Git.
Move redundant handoffs and raw review transcripts to public R2 if suitable, or
to a private documentation repository/archive if they expose personal or
administrative context. Retain stable pointers and source identities. Do not
discard research or resource-ownership contracts merely because they are long.
Use GitHub Issues for actionable issues/specs under the existing project policy;
[GitHub Issues](https://github.com/jsmatfess/chopper/issues) is the sole active tracker.

### Privacy and material that should remain in Git

Review raw environment/validation records and local setup notes for user names,
absolute paths, hostnames, account/project identifiers, emails and session data
before making either Git history or R2 objects public. Public deployment URLs
and synthetic paths can be intentional; classify contents rather than blindly
redacting every identifier. Retain sensitive original evidence in a separate
private R2 bucket, with an independent encrypted backup where required above.
Publish a sanitized derivative
only with its own hash and an explicit relationship to the original; never
silently alter historical raw evidence or claim its original checksum still fits.
Credentials belong in a secret manager/CI secret store, not Git or public R2.

Keep `vendor/zip-2.4.2`, its license and patch notes,
Cargo/npm lockfiles, source/harnesses, small synthetic examples such as
`examples/customers.csv`, and hosted UI source in Git. The ZIP patch is a native and WASI build input. Historical Zstandard build inputs remain in the source revisions that used them. Native CLI builds contain no UI bundle; hosted
`ui/dist` remains generated deployment output under the hosted build contract. The root
[LICENSE](../LICENSE) now records the MIT project license with the owner's
confirmed copyright wording; vendor licenses retain their separate attribution.
