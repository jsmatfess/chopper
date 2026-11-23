import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const [requested, ...extra] = process.argv.slice(2);
const stableTag = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
if (!stableTag.test(requested) || extra.length) {
  throw new Error('Usage: npm run build:published -- vMAJOR.MINOR.PATCH');
}

const releases = JSON.parse(execFileSync('gh', [
  'api', '--paginate', '--slurp', 'repos/jsmatfess/chopper/releases?per_page=100',
], { encoding: 'utf8' })).flat();
const tags = releases.filter(({ draft, prerelease, published_at, tag_name }) =>
  published_at && !draft && !prerelease && stableTag.test(tag_name) && !/^v0\.[0-4]\./.test(tag_name)
).map(release => release.tag_name);
if (!tags.includes(requested)) throw new Error('Choose a published stable Chopper release at v0.5.0 or later.');

const result = spawnSync(process.execPath, [
  fileURLToPath(new URL('./build.mjs', import.meta.url)),
  ...tags.map(tag => `${tag.slice(1)}=refs/tags/${tag}`),
], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
