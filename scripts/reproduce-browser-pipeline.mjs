// Development-only pass/fail loop for a trapped browser pipeline. No timing claims.
import assert from 'node:assert/strict';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {readFile, writeFile, rm, mkdtemp} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';

assert(process.argv.length >= 4, 'Usage: node scripts/reproduce-browser-pipeline.mjs WASM ROWS [MEMORY_MB=32] [CASE=shuffle_partition] [COLUMNS=33] [CONTEXT=persistent]');
const wasm = await readFile(resolve(process.argv[2]));
const rows = Number(process.argv[3]), memory = Number(process.argv[4] ?? 32);
const selected = process.argv[5] ?? 'shuffle_partition', width = Number(process.argv[6] ?? 33);
assert(Number.isSafeInteger(rows) && rows > 0 && Number.isSafeInteger(width) && width >= 2);
const shuffle = {type: 'shuffle', strategy: 'uniform'};
const partition = {type: 'partition', columns: [width > 2 ? 'c0' : 'payload']};
const operations = {shuffle_partition: [shuffle, partition], global: [shuffle], partition: [partition], plain: []}[selected];
assert(operations);
const context = process.argv[7] ?? 'persistent';
assert(['persistent','temporary'].includes(context));
const generated = ['engine.wasm', 'engine-worker.js', 'storage-worker.js', 'benchmark.js', 'benchmark.html', 'benchmark.csv'];
const originals = await Promise.all(generated.map(async name => {
  try { return await readFile('ui/dist/' + name); } catch (e) { if (e.code !== 'ENOENT') throw e; return null; }
}));
let server, browser;
const profile = await mkdtemp('/tmp/chopper-pipeline-profile-');
const diagnostics = [];
try {
  await writeFile('ui/dist/engine.wasm', wasm);
  for(const name of ['engine-worker','storage-worker'])
    await build({entryPoints: ['ui/src/browser/'+name+'.ts'], bundle: true, format: 'esm', outfile: 'ui/dist/'+name+'.js'});
  await build({entryPoints: ['ui/tests/benchmark.ts'], bundle: true, format: 'esm', outfile: 'ui/dist/benchmark.js'});
  await writeFile('ui/dist/benchmark.html', '<!doctype html><script type="module" src="/benchmark.js"></script>');
  await writeFile('ui/dist/benchmark.csv', ['id', 'payload', ...Array.from({length: width - 2}, (_, i) => 'c' + i)].join(',') + '\n');
  for (let start = 0; start < rows; start += 10000) {
    const text = Array.from({length: Math.min(10000, rows - start)}, (_, i) => {
      const row = start + i;
      return [row, 'duplicate payload', ...Array.from({length: width - 2}, (_, c) => (row + c) % 10)].join(',') + '\n';
    }).join('');
    await writeFile('ui/dist/benchmark.csv', text, {flag: 'a'});
  }
  server = spawn(process.execPath, ['scripts/serve-hosted.mjs'], {env: {...process.env, PORT: '8425'}, stdio: ['ignore', 'pipe', 'inherit']});
  await new Promise((ok, fail) => { server.stdout.once('data', ok); server.once('error', fail); server.once('exit', c => fail(new Error('server exit ' + c))); });
  browser = context === 'persistent' ? await chromium.launchPersistentContext(profile) : await chromium.launch();
  const page = await browser.newPage();
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) diagnostics.push(message.text()); });
  page.on('pageerror', error => diagnostics.push(error.stack ?? String(error)));
  await page.goto('http://127.0.0.1:8425/benchmark.html');
  await page.waitForFunction(() => typeof window.benchmark === 'function');
  const result = await page.evaluate(async config => {
    try { return {ok: true, result: await window.benchmark(config)}; }
    catch (error) { return {ok: false, error: String(error), stack: error.stack}; }
  }, {seed: 'external-comparison-v1', operations, resources: {memory_mb: memory, workers: 1, max_record_bytes: Math.min(2097152, memory * 1024 * 1024 / 16)}});
  const record = {rows, memory_mb: memory, columns: width, case: selected, wasm_sha256: createHash('sha256').update(wasm).digest('hex'),
    browser_context: context, ok: result.ok, error: result.error, stack: result.stack, diagnostics,
    ...(result.ok ? {analysis: result.result.analysis, elapsed_seconds: result.result.elapsed_seconds, browser_diagnostics: result.result.diagnostics} : {})};
  console.log(JSON.stringify(record));
  if (!result.ok) process.exitCode = 1;
} finally {
  await browser?.close(); server?.kill();
  await rm(profile,{recursive:true,force:true});
  for (const [index, name] of generated.entries()) {
    if (originals[index] === null) await rm('ui/dist/' + name, {force: true});
    else await writeFile('ui/dist/' + name, originals[index]);
  }
}
