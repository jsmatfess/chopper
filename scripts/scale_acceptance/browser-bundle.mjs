// Source-only preparation. No product build, WASM compilation or browser launch.
import {readFile, writeFile, mkdir, lstat, realpath} from 'node:fs/promises';
import {resolve, relative, dirname, sep} from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
export const root = fileURLToPath(new URL('../../', import.meta.url));
export const sha = bytes => createHash('sha256').update(bytes).digest('hex');
export async function ownedPath(value) {
  assert(!value.split(/[\\/]/).includes('..'), 'Parent traversal');
  const path = resolve(value), scratch = resolve(root, 'scratch');
  assert(path.startsWith(scratch + sep), 'Owned path must stay under repository scratch');
  for (let parent = path;; parent = dirname(parent)) {
    const info = await lstat(parent).catch(error => {if (error.code !== 'ENOENT') throw error;});
    assert(!info?.isSymbolicLink(), 'Symlink ancestry');
    if (parent === resolve(root)) break;
  }
  return path;
}
export async function bundle(directory) {
  const output = await ownedPath(directory);
  await mkdir(output, {recursive: false}); // Fresh only. Retain partial preparation on error.
  const {build, version} = await import('../../ui/node_modules/esbuild/lib/main.js');
  const consumed = {};
  const entry = `
import './ui/src/app';
import {browserApi, executionHistory} from './ui/src/browser/client';
import {installPageAdapter} from './scripts/scale_acceptance/browser-page.mjs';
installPageAdapter(browserApi, () => executionHistory);
`;
  const result = await build({stdin: {contents: entry, resolveDir: root, loader: 'ts'},
    bundle: true, write: false, metafile: true, define: {__HOSTED__: 'true'},
    plugins: [{name: 'capture-consumed-source', setup(build) {
      build.onLoad({filter: /\.(?:ts|mjs|js)$/}, async ({path}) => {
        const bytes = await readFile(path);
        consumed[path] = sha(bytes);
        return {contents: bytes, loader: path.endsWith('.ts') ? 'ts' : 'js'};
      });
    }}]});
  const inputs = {};
  for (const name of Object.keys(result.metafile.inputs).filter(name => name !== '<stdin>')) {
    const path = resolve(root, name);
    assert((await realpath(path)).startsWith(resolve(root) + sep), 'Bundle input outside source');
    assert.equal(sha(await readFile(path)), consumed[path], 'Bundle source changed during compilation');
    inputs[relative(root, path).split(sep).join('/')] = consumed[path];
  }
  const bytes = result.outputFiles[0].contents;
  await writeFile(resolve(output, 'bridge.js'), bytes, {flag: 'wx'});
  await writeFile(resolve(output, 'bundle-provenance.json'), JSON.stringify({
    bundle_sha256: sha(bytes), inputs, entry_sha256: sha(entry), esbuild_version: version,
    hosted: true, scope: 'external production client bridge; no launch receipt'
  }, null, 2) + '\n', {flag: 'wx'});
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await bundle(process.argv[2]);
