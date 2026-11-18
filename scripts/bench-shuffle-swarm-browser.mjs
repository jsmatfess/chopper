// Lead-managed WASI-only complete-job A/B adapter. Never writes ui/dist.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {open, mkdir, readFile, lstat, chmod} from 'node:fs/promises';
import {resolve, join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const ROOT = fileURLToPath(new URL('../', import.meta.url));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const hash = async path => sha(await readFile(path));
const save = async (path, bytes) => {
  const file = await open(path, 'wx');
  try { await file.writeFile(bytes); await file.sync(); } finally { await file.close(); }
};
const json = (path, value) => save(path, JSON.stringify(value, null, 2) + '\n');
async function fresh(path) {
  try { await lstat(path); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
  throw new Error('Refusing existing path: ' + path);
}
function argumentsFor(argv) {
  const options = {};
  const names = ['baseline', 'candidate', 'baseline-provenance', 'candidate-provenance', 'work', 'output',
    'recipes', 'timeout', 'cache-context', 'storage-context'];
  for (let i = 0; i < argv.length; i++) {
    const name = argv[i].slice(2);
    assert(argv[i].startsWith('--') && names.includes(name) && !(name in options), 'Unknown/duplicate option');
    if (name === 'recipes') {
      options[name] = []; while (argv[i + 1] && !argv[i + 1].startsWith('--')) options[name].push(argv[++i]);
    } else { assert(argv[i + 1] && !argv[i + 1].startsWith('--'), 'Missing option value'); options[name] = argv[++i]; }
  }
  for (const name of names.filter(n => n !== 'timeout')) assert(options[name], 'Required --' + name);
  options.timeout = Number(options.timeout ?? 300);
  assert(Number.isFinite(options.timeout) && options.timeout > 0, 'Invalid deadline');
  assert(options.recipes.length && new Set(options.recipes).size === options.recipes.length, 'Explicit unique recipes required');
  return options;
}
const helper = join(ROOT, 'scripts/verify-shuffle-swarm-browser.py');
async function python(request, logPath) {
  const child = spawn('python3', ['-B', helper], {cwd: ROOT, stdio: ['pipe', 'pipe', 'pipe']});
  let stdout = '', stderr = '';
  child.stdout.on('data', bytes => { stdout += bytes; }); child.stderr.on('data', bytes => { stderr += bytes; });
  const completed = once(child, 'close');
  child.stdin.end(JSON.stringify(request));
  const [code, signal] = await completed;
  if (logPath) await json(logPath, {request, code, signal, stdout, stderr});
  assert.equal(code, 0, 'Python bridge failed: ' + stderr);
  return JSON.parse(stdout);
}
async function main() {
  const args = argumentsFor(process.argv.slice(2));
  assert.equal(resolve(process.cwd()), resolve(ROOT), 'Run from the explicit swarm checkout root');
  const work = resolve(args.work), output = resolve(args.output);
  await fresh(work); await fresh(output);
  await mkdir(dirname(work), {recursive: true}); await mkdir(work); // exclusive owned namespace
  await mkdir(dirname(output), {recursive: true});
  const raw = await open(output, 'wx');
  const emit = async value => { await raw.writeFile(JSON.stringify(value) + '\n'); await raw.sync(); };
  let browser, server, consoleLog;
  let activeWasm, activeFixture;
  let attemptPath;
  const identities = {};
  const frozen = new Map();
  async function freeze(path, bytes) {
    await save(path, bytes); await chmod(path, 0o444); frozen.set(path, sha(bytes));
  }
  const sources = new Map();
  const capture = async path => { path = resolve(ROOT, path); sources.set(path, await hash(path)); };
  try {
    await emit({kind: 'start', schema: 'shuffle-swarm-browser-v1', recipes: args.recipes, work,
      warmups: 1, measured_pairs: 3, timeout_seconds: args.timeout,
      cache_context: args['cache-context'], storage_context: args['storage-context'],
      timing: 'After defaults/input/output pickers, before analyze through ready/confirmation/export marker/session retirement. Excludes startup/fixtures/collection/verification/export removal.',
      diagnostics: 'Profiling enabled identically for both; RPC/storage accounting overhead included. Analysis is pre-publication; no CPU/RSS/device I/O inference or native pooling.',
      node: process.version, platform: process.platform, architecture: process.arch});
    const recipes = await python({action: 'recipes'});
    assert(args.recipes.every(name => name in recipes), 'Unknown current native recipe');
    for (const variant of ['baseline', 'candidate']) {
      identities[variant] = await python({action: 'provenance', wasm: resolve(args[variant]),
        manifest: resolve(args[variant + '-provenance']), target: join(work, variant + '-build'), candidate: variant === 'candidate'},
      join(work, variant + '-provenance.json'));
    }
    const assets = join(work, 'assets'); await mkdir(assets);
    const {build} = await import('../ui/node_modules/esbuild/lib/main.js');
    const {chromium} = await import('../ui/node_modules/playwright/index.mjs');
    for (const name of ['benchmark-swarm', 'engine-worker', 'storage-worker']) {
      const input = name === 'benchmark-swarm' ? 'ui/tests/benchmark-swarm.ts' : 'ui/src/browser/' + name + '.ts';
      const result = await build({absWorkingDir: ROOT, entryPoints: [input], bundle: true, format: 'esm',
        write: false, metafile: true, outfile: join(assets, name + '.js')});
      for (const input of Object.keys(result.metafile.inputs)) await capture(input);
      for (const file of result.outputFiles) await freeze(file.path, file.contents);
      await json(join(work, name + '-metafile.json'), result.metafile);
    }
    await freeze(join(assets, 'index.html'), Buffer.from('<!doctype html><script type="module" src="/benchmark-swarm.js"></script>'));
    for (const variant of ['baseline', 'candidate']) {
      const path = join(assets, variant + '.wasm');
      await freeze(path, await readFile(resolve(args[variant])));
      assert.equal(frozen.get(path), identities[variant].binary_sha256, 'WASM changed during freeze');
    }
    for (const path of [fileURLToPath(import.meta.url), helper, 'scripts/bench-shuffle-swarm.py', 'scripts/verify-shuffle-swarm.py',
      'ui/package-lock.json', 'ui/node_modules/esbuild/package.json', 'ui/node_modules/playwright/package.json']) await capture(path);
    const fixtures = {};
    for (const name of args.recipes) {
      const cell = join(work, name); await mkdir(cell);
      fixtures[name] = await python({action: 'fixture', recipe: name, path: join(cell, 'input.csv')}, join(cell, 'fixture-bridge.json'));
      await chmod(join(cell, 'input.csv'), 0o444);
      frozen.set(join(cell, 'input.csv'), fixtures[name].sha256);
    }
    await json(join(work, 'identities.json'), {builds: identities, sources: Object.fromEntries(sources), frozen: Object.fromEntries(frozen)});
    await emit({kind: 'identities', builds: identities, sources: Object.fromEntries(sources), frozen: Object.fromEntries(frozen), fixtures});
    const types = {'.js': 'text/javascript', '.html': 'text/html; charset=utf-8', '.wasm': 'application/wasm', '.csv': 'text/csv'};
    server = createServer(async (req, res) => {
      res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
      res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
      res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'");
      try {
        assert.equal(req.method, 'GET');
        const name = new URL(req.url, 'http://localhost').pathname.slice(1) || 'index.html';
        assert(['index.html', 'benchmark-swarm.js', 'engine-worker.js', 'storage-worker.js', 'engine.wasm', 'input.csv'].includes(name));
        const path = name === 'engine.wasm' ? activeWasm : name === 'input.csv' ? activeFixture : join(assets, name);
        const bytes = await readFile(path);
        assert.equal(sha(bytes), frozen.get(path), 'Frozen served asset changed');
        res.setHeader('Content-Type', types[name.slice(name.lastIndexOf('.'))]); res.end(bytes);
      } catch (error) { res.statusCode = 404; res.end('Not found'); }
    });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    const url = 'http://127.0.0.1:' + server.address().port;
    consoleLog = await open(join(work, 'browser-log.jsonl'), 'wx');
    browser = await chromium.launchPersistentContext(join(work, 'browser-profile'), {headless: true});
    const page = await browser.newPage();
    page.on('console', message => { void consoleLog.writeFile(JSON.stringify({attempt: attemptPath, type: message.type(), text: message.text()}) + '\n'); });
    page.on('pageerror', error => { void consoleLog.writeFile(JSON.stringify({attempt: attemptPath, pageerror: String(error)}) + '\n'); });
    await emit({kind: 'browser', version: browser.browser()?.version(), url, profile: join(work, 'browser-profile'), context: 'persistent disposable bundled Chromium; warm uncontrolled OPFS'});
    for (const name of args.recipes) {
      const samples = {baseline: [], candidate: []};
      for (let repeat = -1; repeat < 3; repeat++) {
        for (const variant of repeat % 2 === 0 ? ['baseline', 'candidate'] : ['candidate', 'baseline']) {
          attemptPath = join(work, name, `${repeat + 1}-${variant}`); await mkdir(attemptPath);
          const sample = {recipe: name, variant, repetition: repeat, warmup: repeat === -1, attempt: attemptPath};
          await emit({...sample, kind: 'attempt-start'});
          try {
            activeWasm = join(assets, variant + '.wasm'); activeFixture = join(work, name, 'input.csv');
            await page.goto(url, {timeout: args.timeout * 1000});
            await page.waitForFunction(() => typeof window.swarmRun === 'function', undefined, {timeout: args.timeout * 1000});
            let timer;
            const result = await Promise.race([
              page.evaluate(({config, timeout}) => window.swarmRun(config, timeout), {config: fixtures[name].config, timeout: args.timeout}),
              new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Host per-job deadline exceeded')), args.timeout * 1000); }),
            ]).finally(() => clearTimeout(timer));
            await json(join(attemptPath, 'result.json'), result);
            const directory = join(attemptPath, 'verification-output'); await mkdir(directory);
            const names = new Set();
            for (const file of result.files) {
              assert(/^[a-zA-Z0-9_.-]+$/.test(file.name) && !file.name.startsWith('.') && !names.has(file.name), 'Unsafe/duplicate export path');
              assert(Number.isSafeInteger(file.size) && file.size >= 0, 'Invalid export size'); names.add(file.name);
              const path = file.name === 'CHOPPER-COMPLETE.json' ? join(attemptPath, file.name) : join(directory, file.name);
              const target = await open(path, 'wx');
              try {
                for (let offset = 0; offset < file.size; offset += 1024 * 1024) {
                  const encoded = await page.evaluate(({name, offset}) => window.swarmCollect(name, offset), {name: file.name, offset});
                  const bytes = Buffer.from(encoded, 'base64');
                  assert.equal(bytes.length, Math.min(1024 * 1024, file.size - offset)); await target.writeFile(bytes);
                }
                await target.sync();
              } finally { await target.close(); }
            }
            const receipt = await python({action: 'verify', recipe: name, directory, result}, join(attemptPath, 'verification-bridge.json'));
            await json(join(attemptPath, 'verification.json'), receipt);
            await emit({...sample, kind: 'verified-before-cleanup', receipt});
            const cleanup = await page.evaluate(() => window.swarmCleanup());
            await json(join(attemptPath, 'cleanup.json'), cleanup);
            await emit({...sample, kind: 'sample', ...result, verification_sha256: await hash(join(attemptPath, 'verification.json')), cleanup});
            if (repeat >= 0) samples[variant].push(result.elapsed_seconds);
          } catch (error) {
            let state;
            try { state = await Promise.race([page.evaluate(() => window.swarmFailure?.()), new Promise(resolve => setTimeout(() => resolve('unavailable after 2s'), 2000))]); } catch (e) { state = String(e); }
            const failure = {...sample, kind: 'failure', error: String(error), stack: error.stack, state, timed_out: /deadline|timed out|Timeout/i.test(String(error)), profile_preserved: true};
            await json(join(attemptPath, 'failure.json'), failure); await emit(failure); throw error;
          }
        }
      }
      await emit({kind: 'summary', recipe: name, wall_seconds: Object.fromEntries(Object.entries(samples).map(([variant, values]) =>
        [variant, {samples: values, median: [...values].sort((a, b) => a - b)[1], min: Math.min(...values), max: Math.max(...values)}]))});
    }
    for (const [path, digest] of [...sources, ...frozen]) assert.equal(await hash(path), digest, 'Source/asset changed during batch: ' + path);
    for (const variant of ['baseline', 'candidate']) assert.equal(await hash(resolve(args[variant])), identities[variant].binary_sha256, 'Original WASM changed');
    await emit({kind: 'complete'});
  } catch (error) { await emit({kind: 'batch-failure', error: String(error), stack: error.stack}); throw error; }
  finally {
    const errors = [];
    try { await browser?.close(); } catch (e) { errors.push(String(e)); }
    try { if (server) await new Promise((ok, fail) => { server.close(e => e ? fail(e) : ok()); server.closeAllConnections(); }); } catch (e) { errors.push(String(e)); }
    try { await consoleLog?.sync(); await consoleLog?.close(); } catch (e) { errors.push(String(e)); }
    await emit({kind: 'owned-resources-closed', errors, profile_and_local_exports_preserved: true}); await raw.close();
    assert.equal(errors.length, 0, 'Owned browser/server/log cleanup failed: ' + errors.join('; '));
  }
}
if (process.argv.includes('--help')) {
  console.log('Run from swarm root: node scripts/bench-shuffle-swarm-browser.mjs --baseline ABS.wasm --baseline-provenance ABS.json --candidate ABS.wasm --candidate-provenance ABS.json --work FRESH_DIR --output FRESH.jsonl --recipes NAME [NAME...] --cache-context TEXT --storage-context TEXT [--timeout 300]');
} else await main();
