# Operator documentation release

The [user guide](../user/README.md) is the entry point for the operator site.
VitePress reads the explicit source allowlist in [the site builder](../../docs-site/build.mjs).
Quickstart and browser guidance come from designated sections of the existing
Markdown. Links outside the site point to the matching release tag in GitHub.
The generated [CLI reference](../cli-reference.md) still has its native drift
check. The native binary exports the structured flag descriptions and accepted
values used by the docs tables and the hosted selectors. The site retains the
original terminal output under each command. Regenerate both files with
`python3 scripts/cli-reference.py PATH_TO_CHOPPER` after CLI changes. The site build needs Node.js 22, Git and
Chromium for smoke tests.

## Qualify the candidate

From a clean, frozen release candidate checkout, use its committed revision.
The site build checks local links and anchors and emits `dist/versions.json`
with the commit that supplied each release version. The browser smoke test
checks the landing page, version navigation, an export-recovery deep link,
and search within each version.

```sh
npm --prefix docs-site ci
npm --prefix docs-site exec -- playwright install chromium
npm --prefix docs-site run build -- 0.5.0=HEAD
npm --prefix docs-site run smoke
```

Record the candidate commit and the smoke result. Browser app packaging uses
the same version from `ui/package.json`. After building the default WASI
engine and installing UI dependencies, build and serve the release app in one
terminal. In PowerShell set `$env:CHOPPER_DOCS_ORIGIN` before invoking npm.

```sh
CHOPPER_DOCS_ORIGIN=https://chopper-docs.pages.dev npm --prefix ui run build:hosted
npm --prefix ui run serve:hosted
```

In another terminal, check the app link and seven-file build inventory.

```sh
node scripts/test-hosted-docs-link.mjs http://127.0.0.1:8421 https://chopper-docs.pages.dev
```

Development builds use the repository user guide when `CHOPPER_DOCS_ORIGIN`
is unset. The release build must set the origin explicitly. Retain existing
source, platform, package and publication approvals. The docs candidate smoke
is part of pre-tag qualification. The live site and app link are part of
post-publication acceptance.

## Publish after approval and public release

The docs ship separately to the Cloudflare Pages Direct Upload project
`chopper-docs`, production branch `main`. A version lands at
`https://chopper-docs.pages.dev/versions/VERSION/`. The homepage lists all
published docs versions and `/latest` points to the highest stable version.

GitHub Actions is disabled at the repository level. Use the local publication
path for 0.5. Log in to Wrangler for the account that owns the docs project
or supply an account-scoped Pages Edit token through the environment.
From the approved checkout, fetch the public tags and run the following.
`build:published` verifies the requested release against GitHub, then bundles
every published stable release at v0.5.0 or later and validates it before upload.
The checkout and toolchain used for publishing should match the qualified
candidate. Use the same commands for a retry, with the intended release tag.
Keep only one local docs deployment in progress at a time.

```sh
git fetch --tags origin &&
test "$(git rev-parse HEAD)" = "$(git rev-parse 'v0.5.0^{commit}')" &&
npm --prefix docs-site run build:published -- v0.5.0 &&
npm --prefix docs-site run smoke &&
(cd docs-site && npm exec -- wrangler pages deploy dist --project-name chopper-docs --branch main)
```

Keep the previous deployment ID and the new deployment output with the
qualified build's `docs-site/dist/versions.json`. Verify the live manifest bytes,
version landing page, deep link, search and release app link before marking
the release complete.

```sh
curl --fail --silent --show-error https://chopper-docs.pages.dev/versions.json -o /tmp/chopper-docs-live.json
cmp docs-site/dist/versions.json /tmp/chopper-docs-live.json
npm --prefix docs-site run smoke -- https://chopper-docs.pages.dev
node scripts/test-hosted-docs-link.mjs https://chopper-1rx.pages.dev/ https://chopper-docs.pages.dev
```

If a build fails, leave the current deployment in place. If a new deployment
fails its live checks and needs immediate rollback, restore the previous
production deployment in the docs project's Cloudflare Pages dashboard. Verify
the restored manifest and deep links, then retry from the approved public tags.
A rollback temporarily restores the set of versions in the selected deployment.

## Automatic publication

The [docs publish workflow](../../.github/workflows/docs-publish.yml) runs on
published stable GitHub releases when Actions is enabled. Its manual retry runs
from `main` with an existing public stable tag. It serializes deployments and
rebuilds the full live version set each time, so retrying an older tag keeps
newer versions and the latest pointer. The [docs check workflow](../../.github/workflows/docs-check.yml)
builds the candidate without a browser engine or deployment credentials.

The repository settings are `CLOUDFLARE_DOCS_ACCOUNT_ID` and
`CLOUDFLARE_DOCS_PROJECT` in Actions variables and
`CLOUDFLARE_DOCS_API_TOKEN` in Actions secrets. Create a custom token with
**Account → Cloudflare Pages → Edit**, scoped to the owning account.
[Cloudflare Pages Direct Upload with CI](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)
