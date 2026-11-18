// Historical reproduction only: requires matching pinned pre-removal native/WASI builds.
// Obsolete request fields and negative controls explain recorded evidence, not current support.
// Extend the predeclared resident corpus by exact native/WASI byte parity.
// Run after diagnose-shuffle.py; its null calibration and metrics are reused
// only after reproducing its native fingerprints and comparing every CSV hash.
import assert from 'node:assert/strict';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {spawn, execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';

assert(process.argv.length === 4,
  'Usage: node scripts/diagnose-shuffle-browser.mjs NATIVE_JSONL BINARY');
const referencePath = resolve(process.argv[2]), binary = resolve(process.argv[3]);
const referenceBytes = await readFile(referencePath);
const reference = referenceBytes.toString().trim().split('\n').map(JSON.parse);
assert(reference.at(-1).type === 'summary' && reference.at(-1).verified);
const design=reference.find(r=>r.type==='design');
const samples = reference.filter(r => r.type === 'sample');
assert(samples.length === 480);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const emit = value => console.log(JSON.stringify(value));
const exec = promisify(execFile);
const root = await mkdtemp(join(tmpdir(), 'chopper-diagnostic-browser-'));
const generated = ['benchmark.csv', 'benchmark.js', 'benchmark.html'];
const originals = await Promise.all(generated.map(async name => {
  try { return await readFile('ui/dist/' + name); }
  catch (e) { if (e.code !== 'ENOENT') throw e; return null; }
}));
// Match Python's sort_keys=True framing for the reference fingerprint.
const pythonJson = value => Array.isArray(value) ? '[' + value.map(pythonJson).join(', ') + ']'
  : value && typeof value === 'object'
    ? '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ': ' + pythonJson(value[k])).join(', ') + '}'
    : JSON.stringify(value);
const outputs = manifest => manifest.trim().split('\n').map(JSON.parse).filter(e => e.type === 'output')
  .map(({path, rows, csv_bytes, lineage}) => ({path, rows, csv_bytes, lineage}));
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value;
const identity = result => JSON.stringify(canonical([result.analysis.logical_digest,
  result.analysis.rows, result.analysis.groups, result.analysis.stages,
  outputs(result.manifest), result.hashes]));
let server, browser;
try {
  await build({entryPoints: ['ui/tests/benchmark.ts'], bundle: true, format: 'esm', outfile: 'ui/dist/benchmark.js'});
  await writeFile('ui/dist/benchmark.html', '<!doctype html><script type="module" src="/benchmark.js"></script>');
  server = spawn(process.execPath, ['scripts/serve-hosted.mjs'],
    {env: {...process.env, PORT: '8424'}, stdio: ['ignore', 'pipe', 'inherit']});
  await new Promise((ok, fail) => {
    server.stdout.once('data', ok); server.once('error', fail);
    server.once('exit', code => fail(new Error('Server exited: ' + code)));
  });
  browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:8424/benchmark.html');
  await page.waitForFunction(() => typeof window.benchmark === 'function');
  emit({type: 'environment', version: 'shuffle-diagnostic-browser-v1', browser: await browser.version(),
    reference_sha256: sha(referenceBytes), binary_sha256: sha(await readFile(binary)),
    wasm_sha256: sha(await readFile('ui/dist/engine.wasm')),
    engine_worker_sha256:sha(await readFile('ui/dist/engine-worker.js')),storage_worker_sha256:sha(await readFile('ui/dist/storage-worker.js')),benchmark_bundle_sha256:sha(await readFile('ui/dist/benchmark.js')),
    script_sha256: sha(await readFile(new URL(import.meta.url))),
    note: 'Exact parity extension of the resident diagnostic corpus; no new statistical family or timing claim.'});
  let previousPattern;
  for (const sample of samples) {
    const {pattern, algorithm, seed} = sample;
    if (pattern !== previousPattern) {
      const sizes = pattern === 'skewed' ? [192, 48, 16] : [256];
      let text = 'id,value,label,group\n', start = 0;
      for (const [group, size] of sizes.entries()) {
        for (let position = 0; position < size; position++) {
          const value = pattern === 'descending' ? size - position - 1 : position;
          const label = pattern === 'periodic' ? position % 4
            : pattern === 'skewed' ? Number(position >= size * 3 / 4) : Math.floor(position * 4 / size);
          text += [start + position, value, label, group].join(',') + '\n';
        }
        start += size;
      }
      await writeFile(join(root, 'input.csv'), text);
      await writeFile('ui/dist/benchmark.csv', text);
      previousPattern = pattern;
    }
    const config = {seed, operations: [
      ...(pattern === 'skewed' ? [{type: 'partition', columns: ['group']}] : []),
      {type: 'shuffle', strategy: algorithm, buffer_rows: 4}],
    resources: {memory_mb: 64, workers: 1, max_record_bytes: 2097152},
    limits: {rows: null, bytes: null, compressed_bytes: null}};
    if(design.partition_first)config.operations=[{type:'shuffle',strategy:algorithm,buffer_rows:4},{type:'partition',columns:['group']}];
    if(design.partition_first||design.independent_buckets||design.full_shuffle_rng==='blake3_xof_v1')config.full_shuffle_policy='flexible_v1';
    if(design.full_shuffle_rng==='blake3_xof_v1')config.full_shuffle_rng='blake3_xof_v1';
    if(design.independent_buckets)config.full_shuffle_algorithm='independent_buckets_v1';
    const output = join(root, 'output'), job = join(root, 'job.json');
    await writeFile(job, JSON.stringify({...config, input: join(root, 'input.csv'), output}));
    const {stdout} = await exec(binary, ['run', '--config', job, '--yes'], {timeout: 120000});
    const native = {analysis: JSON.parse(stdout), manifest: await readFile(join(output, 'manifest.jsonl'), 'utf8'), hashes: {}};
    const fingerprint = createHash('sha256');
    for (const entry of outputs(native.manifest)) {
      const bytes = await readFile(join(output, entry.path));
      assert(bytes.length === entry.csv_bytes);
      fingerprint.update(bytes); fingerprint.update(pythonJson(entry));
      native.hashes[entry.path] = sha(bytes);
    }
    assert.equal(fingerprint.digest('hex'), sample.fingerprint, 'native reference order/metadata changed');
    assert.equal(native.analysis.logical_digest, sample.logical_digest);
    const wasi = await page.evaluate(config => window.benchmark(config), config);
    assert.equal(identity(wasi), identity(native), `${pattern}/${algorithm}/${seed}: native/WASI parity`);
    assert.equal(wasi.analysis.diagnostics.workspace_reserved_bytes, (wasi.analysis.diagnostics.temporary_path_reserved_bytes ?? 0) + (wasi.analysis.diagnostics.input_header_reserved_bytes ?? 0));
    emit({type: 'sample', pattern, algorithm, seed, metrics: sample.metrics,
      reference_fingerprint: sample.fingerprint, logical_digest: sample.logical_digest,
      csv_sha256: native.hashes, verified: true});
    await rm(output, {recursive: true});
  }
  emit({type: 'summary', native_jobs: samples.length, browser_jobs: samples.length,
    reference_flags: reference.at(-1).flags, verified: true,
    note: 'Identical CSV bytes/order and metadata imply identical diagnostic metrics; no proof of uniformity.'});
} finally {
  await browser?.close(); server?.kill();
  for (const [index, name] of generated.entries()) {
    if (originals[index] === null) await rm('ui/dist/' + name, {force: true});
    else await writeFile('ui/dist/' + name, originals[index]);
  }
  await rm(root, {recursive: true, force: true});
}
