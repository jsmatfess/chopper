// Optional harness-only compilation against the separately frozen product source.
// No product build/launch; the parent prepares and approves the resulting hashes.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, relative, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {release, version as osVersion} from 'node:os';
import {ownedPath, root, sha} from './browser-bundle.mjs';
export async function bundleScale(productRoot, directory) {
  productRoot = resolve(productRoot);
  assert.notEqual(productRoot, resolve(root), 'Separate immutable product source required');
  const output = await ownedPath(directory);
  await mkdir(output);
  const {build, version, stop} = await import('../../ui/node_modules/esbuild/lib/main.js');
  try {
  const entry = `import ${JSON.stringify(resolve(productRoot, 'ui/src/app.ts'))};
import {browserApi, executionHistory} from ${JSON.stringify(resolve(productRoot, 'ui/src/browser/client.ts'))};
import {installPageAdapter} from ${JSON.stringify(resolve(root, 'scripts/scale_acceptance/browser-page.mjs'))};
installPageAdapter(browserApi, () => executionHistory);`;
  const consumed = new Map();
  const result = await build({stdin: {contents: entry, resolveDir: root, loader: 'ts'}, bundle: true,
    write: false, metafile: true, define: {__HOSTED__: 'true'}, plugins: [{name: 'freeze-inputs', setup(build) {
      build.onLoad({filter: /\.(ts|js|mjs)$/}, async ({path}) => {
        const bytes = await readFile(path); consumed.set(path, sha(bytes));
        return {contents: bytes, loader: path.endsWith('.ts') ? 'ts' : 'js'};
      });
    }}]});
  const inputs = {product: {}, harness: {}};
  for (const name of Object.keys(result.metafile.inputs).filter(name => name !== '<stdin>')) {
    const path = resolve(root, name);
    const part = path.startsWith(productRoot + sep) ? 'product' : 'harness';
    const base = part === 'product' ? productRoot : resolve(root);
    assert(path.startsWith(base + sep), 'Bridge input escaped frozen roots');
    assert.equal(sha(await readFile(path)), consumed.get(path), 'Bridge source drift');
    inputs[part][relative(base, path).split(sep).join('/')] = consumed.get(path);
  }
  const bytes = result.outputFiles[0].contents;
  await writeFile(resolve(output, 'bridge.js'), bytes, {flag: 'wx'});
  await writeFile(resolve(output, 'bundle-provenance.json'), JSON.stringify({inputs,
    bundle_sha256: sha(bytes), esbuild_version: version, hosted: true, entry_sha256: sha(entry),
    node_version: process.version, node_os_release: release(), node_os_version: osVersion()}, null, 2) + '\n', {flag: 'wx'});
  } finally { stop(); }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await bundleScale(process.argv[2], process.argv[3]);
