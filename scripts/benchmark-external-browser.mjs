// Development-only complete-job native/WASI A/B benchmark. Build both WASM variants
// and native binaries from identical sources; see docs/performance.md for commands.
import assert from 'node:assert/strict';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {mkdtemp, writeFile, readFile, rm} from 'node:fs/promises';
import {tmpdir, cpus, totalmem} from 'node:os';
import {join, resolve} from 'node:path';
import {spawn, execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';

const exec = promisify(execFile);
assert(process.argv.length >= 6,
  'Usage: node scripts/benchmark-external-browser.mjs MERGE PREFIX MERGE.wasm PREFIX.wasm [ROWS] [REPEATS] [SHAPES] [CASES] [BASELINE_LABEL,CANDIDATE_LABEL] [NATIVE_WORKERS]');
const [baseline, candidate, baselineWasm, candidateWasm] = process.argv.slice(2, 6).map(p => resolve(p));
const rows = Number(process.argv[6] ?? 100000), repeats = Number(process.argv[7] ?? 3);
const selectedShapes = (process.argv[8] ?? 'narrow,columns,rare_wide').split(',');
const selectedCases = (process.argv[9] ?? 'global,grouped,balanced,multistage').split(',');
const chainCases = ['chain_probability', 'chain_parents', 'chain_downstream', 'chain_interleaved', 'chain_last_probability', 'chain_both_probability'];
const streamControls = ['stream_probability', 'stream_interleaved'];
const tripleCases = ['partition_balanced', 'partition_balanced_parents', 'partition_balanced_downstream', 'partition_balanced_repeat'];
const consecutiveCases = ['consecutive', 'consecutive_parents', 'consecutive_downstream', 'consecutive_chain'];
const constantCases = ['constant_repeat', 'constant_partial', 'constant_downstream', 'constant_empty'];
const nestedCases = ['nested', 'nested_downstream', 'nested_parents', 'nested_deep', 'shuffled_nested'];
const fusionCases = ['shuffle_partition', 'parent_shuffle_partition', 'shuffle_partition_balanced',
  'repeated_shuffle_partition', 'shuffle_partition_assign', 'shuffle_partition_key'];
assert(Number.isSafeInteger(rows) && rows >= 100 && rows <= 2000000);
assert(Number.isSafeInteger(repeats) && repeats >= 1);
assert(selectedShapes.every(s => ['narrow', 'columns', 'rare_wide', 'independent', 'independent_wide'].includes(s)));
assert(selectedCases.every(s => ['global', 'grouped', 'balanced', 'multistage', ...fusionCases, ...nestedCases, ...constantCases, ...consecutiveCases, ...tripleCases, ...chainCases, ...streamControls].includes(s)));
assert(!selectedCases.some(s => fusionCases.includes(s)) || rows >= 1000);
assert(!selectedCases.some(s => chainCases.includes(s)) || rows >= 4000);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const emit = value => console.log(JSON.stringify(value));
const labels = (process.argv[10] ?? 'merge,prefix').split(',');
assert(labels.length === 2 && labels[0] !== labels[1] && labels.every(label => /^[a-z0-9-]+$/.test(label)));
const nativeWorkers = (process.argv[11] ?? '1').split(',').map(Number);
assert(nativeWorkers.length > 0 && new Set(nativeWorkers).size === nativeWorkers.length
  && nativeWorkers.every(n => Number.isSafeInteger(n) && n >= 1 && n <= 256));
// Keep historical names when the optional worker matrix is omitted.
const nativeName = (label, workers) => 'native-' + label + (process.argv[11] ? '-w' + workers : '');
const nativeVariants = nativeWorkers.flatMap(workers => labels.map(label => nativeName(label, workers)));
const variants = nativeVariants.concat(labels.map(label => 'browser-' + label));
const binaries = Object.fromEntries(nativeWorkers.flatMap(workers => labels.map((label, i) =>
  [nativeName(label, workers), i === 0 ? baseline : candidate])));
const workersByVariant = Object.fromEntries(nativeWorkers.flatMap(workers => labels.map(label =>
  [nativeName(label, workers), workers])));
const wasm = {['browser-' + labels[0]]: await readFile(baselineWasm), ['browser-' + labels[1]]: await readFile(candidateWasm)};
const enginePath = 'ui/dist/engine.wasm', originalWasm = await readFile(enginePath);
const root = await mkdtemp(join(tmpdir(), 'chopper-external-browser-'));
const generated = ['benchmark.csv', 'benchmark.js', 'benchmark.html', 'engine-worker.js', 'storage-worker.js'];
// Preserve pre-existing development artifacts as well as the production WASM.
const originals = await Promise.all(generated.map(async name => {
  try { return await readFile('ui/dist/' + name); } catch (e) { if (e.code !== 'ENOENT') throw e; return null; }
}));
let browser, server;
function fields(row, shape) {
  return [String(row), ['rare_wide', 'independent_wide'].includes(shape) && row === 0 ? 'x'.repeat(1800000) : 'duplicate payload',
    ...(shape === 'narrow' ? [] : Array.from({length: 31}, (_, col) => String(['independent', 'independent_wide'].includes(shape) && col === 1 ? Math.floor(row / 10) % 10 : (row + col) % 10)))];
}
function outputs(manifest) {
  return manifest.trim().split('\n').map(line => JSON.parse(line)).filter(e => e.type === 'output')
    .map(({path, rows, csv_bytes, lineage}) => ({path, rows, csv_bytes, lineage})).sort((a, b) => a.path.localeCompare(b.path));
}
function identity(result) {
  const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value;
  return JSON.stringify(canonical([result.analysis.logical_digest, result.analysis.rows, result.analysis.output_csv_bytes,
    result.analysis.stages, outputs(result.manifest), Object.entries(result.hashes).sort()]));
}
try {
  await build({entryPoints: ['ui/tests/benchmark.ts'], bundle: true, format: 'esm', outfile: 'ui/dist/benchmark.js'});
  await writeFile('ui/dist/benchmark.html', '<!doctype html><script type="module" src="/benchmark.js"></script>');
  server = spawn(process.execPath, ['scripts/serve-hosted.mjs'], {env: {...process.env, PORT: '8424'}, stdio: ['ignore', 'pipe', 'inherit']});
  await new Promise((ok, fail) => {
    server.stdout.once('data', ok); server.once('error', fail);
    server.once('exit', code => fail(new Error('Benchmark server exited: ' + code)));
  });
  browser = await chromium.launchPersistentContext(join(root,'browser-profile'));
  for(const name of ['engine-worker','storage-worker'])
    await build({entryPoints: ['ui/src/browser/'+name+'.ts'], bundle: true, format: 'esm', outfile: 'ui/dist/'+name+'.js'});
  const page = await browser.newPage();
  emit({type: 'environment', browser_context: 'persistent disk-backed profile', platform: process.platform, architecture: process.arch, cpu: cpus()[0]?.model,
    logical_cpus: cpus().length, memory_bytes: totalmem(), browser: browser.browser().version(), rows, repeats,
    memory_mb: 32, workers: 1, native_workers: nativeWorkers, comparison_labels: labels, seed: 'external-comparison-v1', storage: 'warm uncontrolled local filesystem / browser OPFS',
    binary_sha256: Object.fromEntries(await Promise.all(Object.entries(binaries).map(async ([k, p]) => [k, sha(await readFile(p))]))),
    wasm_sha256: Object.fromEntries(Object.entries(wasm).map(([k, bytes]) => [k, sha(bytes)])),
    script_sha256: sha(await readFile(new URL(import.meta.url))),
    browser_sources_sha256: Object.fromEntries(await Promise.all(['fs','engine-worker','storage-worker','client'].map(async name=>[name,sha(await readFile('ui/src/browser/'+name+'.ts'))]))),
    note: 'Source creation, browser startup, defaults, verification and output cleanup excluded. Browser time includes analyze/run/export and per-job WASM restart. Native time includes CLI startup and publication. Logical temporary I/O is not physical I/O. Browser CPU/allocations/RSS/physical I/O are unavailable.'});
  for (const shape of selectedShapes) {
    const header = ['id', 'payload', ...(shape === 'narrow' ? [] : Array.from({length: 31}, (_, col) => 'c' + col))];
    // These fixtures contain no CSV quotes, commas or embedded newlines. Validation below
    // deliberately applies only to this generator, not to arbitrary user CSV input.
    const source = join(root, 'input.csv');
    await writeFile(source, header.join(',') + '\n');
    for (let start = 0; start < rows; start += 10000) {
      const lines = Array.from({length: Math.min(10000, rows - start)}, (_, i) => fields(start + i, shape).join(',') + '\n').join('');
      await writeFile(source, lines, {flag: 'a'});
    }
    await writeFile('ui/dist/benchmark.csv', await readFile(source));
    for (const name of selectedCases) {
      const shuffle = {type: 'shuffle', strategy: 'uniform'};
      const partition = {type: 'partition', columns: [shape === 'narrow' || name === 'shuffle_partition_key' ? 'payload' : 'c0']};
      const constantColumn = shape === 'narrow' ? 'payload' : 'c0';
      const knownColumns = Array.from({length: 31}, (_, i) => 'c' + i);
      const constantPartition = {type: 'partition', columns: [constantColumn]};
      const probability = (last = false) => ({type: 'assign_probabilistic', groups: [
        {name: 'treatment', percent: '60'}, {name: 'control', percent: '40'}, {name: 'empty', percent: '0'}],
        strata: [shape === 'narrow' ? 'payload' : last ? 'c1' : 'c0']});
      const operations = {
        chain_probability: [probability(), partition, {type: 'interleaved', files: 3}],
        chain_parents: [{type: 'balanced', files: 4}, probability(), partition, {type: 'interleaved', files: 3}],
        chain_downstream: [probability(), partition, {type: 'interleaved', files: 3}, shuffle, {type: 'balanced', files: 2}],
        chain_interleaved: [{type: 'interleaved', files: 3}, partition, {type: 'interleaved', files: 3}],
        chain_last_probability: [{type: 'interleaved', files: 3}, partition, probability(true)],
        chain_both_probability: [probability(), partition, probability(true)],
        stream_probability: [probability()],
        stream_interleaved: [{type: 'interleaved', files: 3}],
        partition_balanced: [partition, shuffle, {type: 'balanced', files: 3}],
        partition_balanced_parents: [{type: 'balanced', files: 4}, partition, shuffle, {type: 'balanced', files: 3}],
        partition_balanced_downstream: [partition, shuffle, {type: 'balanced', files: 3}, shuffle, {type: 'interleaved', files: 2}],
        partition_balanced_repeat: [partition, shuffle, shuffle, {type: 'balanced', files: 3}],
        consecutive: [constantPartition, {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c1']}],
        consecutive_parents: [{type: 'balanced', files: 4}, constantPartition, {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c1']}],
        consecutive_downstream: [constantPartition, {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c1']}, shuffle, {type: 'balanced', files: 2}],
        consecutive_chain: [constantPartition, {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c1']}, {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c2']}],
        constant_repeat: [constantPartition, constantPartition],
        constant_partial: [{type: 'partition', columns: knownColumns}, {type: 'partition', columns: [...knownColumns, 'payload']}, shuffle],
        constant_downstream: [constantPartition, {type: 'balanced', files: 2}, constantPartition, shuffle, {type: 'balanced', files: 2}],
        constant_empty: [constantPartition, {type: 'assign_probabilistic', groups: [
          {name: 'keep', percent: '100'}, {name: 'empty', percent: '0'}]}, constantPartition, shuffle],
        shuffled_nested: [shuffle, ...[1, 3, 4].map(files => ({type: 'balanced', files}))],
        nested: [{type: 'balanced', files: 3}, {type: 'balanced', files: 4}],
        nested_downstream: [{type: 'balanced', files: 3}, {type: 'balanced', files: 4}, shuffle],
        nested_parents: [{type: 'partition', columns: ['c0']}, {type: 'balanced', files: 3}, {type: 'balanced', files: 4}],
        nested_deep: [3, 4, 2, 2].map(files => ({type: 'balanced', files})),
        global: [shuffle], grouped: [{type: 'balanced', files: 4}, shuffle],
        balanced: [shuffle, {type: 'balanced', files: 4}],
        multistage: [shuffle, {type: 'balanced', files: 4}, shuffle, {type: 'balanced', files: 3}],
        shuffle_partition: [shuffle, partition],
        parent_shuffle_partition: [{type: 'balanced', files: 4}, shuffle, partition],
        shuffle_partition_balanced: [shuffle, partition, {type: 'balanced', files: 2}, shuffle],
        repeated_shuffle_partition: [shuffle, shuffle, partition, shuffle,
          {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c1']}],
        shuffle_partition_assign: [shuffle, partition, {type: 'assign', groups: [
          {name: 'a', percent: '60'}, {name: 'b', percent: '40'}]}, shuffle,
          {type: 'partition', columns: [shape === 'narrow' ? 'payload' : 'c2']}],
        shuffle_partition_key: [shuffle, partition],
      }[name];
      const config = {seed: 'external-comparison-v1', operations, compression: 'none',
        resources: {memory_mb: 32, workers: 1, max_record_bytes: 2097152}};
      const samples = Object.fromEntries(variants.map(v => [v, []]));
      let reference;
      for (let repeat = 0; repeat < repeats; repeat++) {
        for (const variant of repeat % 2 ? [...variants].reverse() : variants) {
          console.error(`${shape}/${name}/${variant}/${repeat + 1}`);
          let result, resourceUsage;
          if (variant.startsWith('browser')) {
            await writeFile(enginePath, wasm[variant]);
            await page.goto('http://127.0.0.1:8424/benchmark.html');
            await page.waitForFunction(() => typeof window.benchmark === 'function');
            result = await page.evaluate(config => window.benchmark(config), config);
          } else {
            const output = join(root, 'output'), path = join(root, 'job.json'), stats = join(root, 'time.txt');
            await writeFile(path, JSON.stringify({...config,
              resources: {...config.resources, workers: workersByVariant[variant]}, input: source, output}));
            const start = performance.now();
            const {stdout} = await exec('/usr/bin/time', ['-f', '%U %S %M %I %O', '-o', stats,
              binaries[variant], 'run', '--config', path, '--yes'], {maxBuffer: 8 * 1024 * 1024, timeout: 600000});
            result = {analysis: JSON.parse(stdout), elapsed_seconds: (performance.now() - start) / 1000,
              manifest: await readFile(join(output, 'manifest.jsonl'), 'utf8'), hashes: {}};
            const [user, system, rss, reads, writes] = (await readFile(stats, 'utf8')).trim().split(/\s+/).map(Number);
            resourceUsage = {cpu_seconds: user + system, peak_rss_kib: rss, filesystem_input_blocks: reads, filesystem_output_blocks: writes};
            const seen = new Uint8Array(rows), entries = outputs(result.manifest);
            const partitions = shape === 'narrow' ? 1 : 10;
            const expectedOutputs = streamControls.includes(name) ? 3
              : chainCases.includes(name) ? partitions * 3 * (['chain_interleaved', 'chain_last_probability'].includes(name) ? 3 : 2)
                * (name === 'chain_parents' ? 4 : name === 'chain_downstream' ? 2 : 1)
              : tripleCases.includes(name)
              ? partitions * 3 * (name === 'partition_balanced_parents' ? 4 : name === 'partition_balanced_downstream' ? 2 : 1)
              : consecutiveCases.includes(name)
              ? (shape === 'narrow' ? 1 : ['independent', 'independent_wide'].includes(shape) ? 100 : 10) * (name === 'consecutive_parents' ? 4 : name === 'consecutive_downstream' ? 2 : 1)
              : constantCases.includes(name)
              ? (name === 'constant_partial' ? (shape === 'rare_wide' ? 11 : 10) : partitions * (name === 'constant_downstream' ? 4 : 1))
              : nestedCases.includes(name) ? (name === 'nested_parents' ? 120 : name === 'nested_deep' ? 48 : 12)
              : name === 'shuffle_partition_key' ? (shape === 'rare_wide' ? 2 : 1)
              : fusionCases.includes(name) ? partitions * (name === 'parent_shuffle_partition' ? 4
                : ['shuffle_partition_balanced', 'shuffle_partition_assign'].includes(name) ? 2 : 1)
              : name === 'global' ? 1 : name === 'multistage' ? 12 : 4;
            assert.equal(entries.length, expectedOutputs);
            const scopePositions = new Map();
            for (const [group, entry] of entries.entries()) {
              const bytes = await readFile(join(output, entry.path));
              assert.equal(bytes.length, entry.csv_bytes);
              result.hashes[entry.path] = sha(bytes);
              const records = bytes.toString('utf8').trimEnd().split('\n');
              assert.equal(records.shift(), header.join(','));
              assert.equal(records.length, entry.rows);
              let previousId = -1;
              for (const record of records) {
                const id = Number(record.split(',', 1)[0]);
                assert(Number.isSafeInteger(id) && id >= 0 && id < rows && !seen[id]);
                assert.equal(record, fields(id, shape).join(','));
                if (chainCases.includes(name) || streamControls.includes(name)) {
                  if (name !== 'chain_downstream') { assert(id > previousId, 'routing encounter order changed'); previousId = id; }
                  const values = record.split(',');
                  for (const step of entry.lineage) if ('values' in step)
                    assert.deepEqual(step.values, operations[step.operation].columns.map(c => values[header.indexOf(c)]));
                  if (name === 'chain_parents') {
                    const parent = entry.lineage[0].part - 1;
                    const start = parent * Math.floor(rows / 4) + Math.min(parent, rows % 4);
                    assert(id >= start && id < start + Math.floor(rows / 4) + Number(parent < rows % 4));
                  }
                  if (['chain_interleaved', 'chain_last_probability', 'stream_interleaved'].includes(name))
                    assert.equal(entry.lineage[0].part - 1, id % 3);
                  if (chainCases.includes(name)) {
                    const step = name === 'chain_parents' ? 3 : 2;
                    if (operations[step].type === 'interleaved') {
                      const scope = JSON.stringify(entry.lineage.filter(s => s.operation < step));
                      const part = entry.lineage.find(s => s.operation === step).part;
                      const positions = scopePositions.get(scope) ?? [];
                      positions.push([id, part]); scopePositions.set(scope, positions);
                    }
                  }
                }
                if (nestedCases.includes(name)) {
                  let start = 0, length = rows;
                  for (const step of entry.lineage) {
                    const logical = operations[step.operation];
                    if (logical.type === 'balanced' && !['nested_parents', 'shuffled_nested'].includes(name)) {
                      const part = step.part - 1, files = logical.files;
                      start += part * Math.floor(length / files) + Math.min(part, length % files);
                      length = Math.floor(length / files) + Number(part < length % files);
                    }
                    if ('values' in step) assert.deepEqual(step.values, [record.split(',')[header.indexOf('c0')]]);
                  }
                  if (!['nested_parents', 'shuffled_nested'].includes(name)) assert(id >= start && id < start + length);
                }
                if (consecutiveCases.includes(name) && name !== 'consecutive_downstream') {
                  assert(id > previousId, 'partition encounter order changed'); previousId = id;
                }
                if (name === 'consecutive_parents') {
                  const parent = entry.lineage[0].part - 1;
                  const start = parent * Math.floor(rows / 4) + Math.min(parent, rows % 4);
                  assert(id >= start && id < start + Math.floor(rows / 4) + Number(parent < rows % 4));
                }
                if (constantCases.includes(name) || consecutiveCases.includes(name)) {
                  const values = record.split(',');
                  for (const step of entry.lineage)
                    if ('values' in step) assert.deepEqual(step.values, operations[step.operation].columns.map(c => values[header.indexOf(c)]));
                }
                if (fusionCases.includes(name) || tripleCases.includes(name)) {
                  const values = record.split(',');
                  for (const step of entry.lineage) {
                    if ('values' in step) {
                      const logical = operations[step.operation];
                      assert.equal(logical.type, 'partition');
                      assert.deepEqual(step.values, logical.columns.map(c => values[header.indexOf(c)]));
                    }
                  }
                  if (['parent_shuffle_partition', 'partition_balanced_parents'].includes(name)) {
                    const parent = entry.lineage[0].part - 1;
                    const start = parent * Math.floor(rows / 4) + Math.min(parent, rows % 4);
                    assert(id >= start && id < start + Math.floor(rows / 4) + Number(parent < rows % 4));
                  }
                }
                if (name === 'grouped') {
                  const start = group * Math.floor(rows / 4) + Math.min(group, rows % 4);
                  assert(id >= start && id < start + Math.floor(rows / 4) + Number(group < rows % 4));
                }
                seen[id] = 1;
              }
            }
            for (const positions of scopePositions.values())
              positions.sort((a, b) => a[0] - b[0]).forEach(([, part], encounter) => assert.equal(part, encounter % 3 + 1));
            assert(seen.every(Boolean));
            await rm(output, {recursive: true});
          }
          assert.equal(result.analysis.rows, rows);
          assert.equal(result.analysis.workers, workersByVariant[variant] ?? 1);
          const retainedOwners=['temporary_path_reserved_bytes','directory_path_reserved_bytes','prepared_job_reserved_bytes',
            'input_header_reserved_bytes','analysis_preview_reserved_bytes','analysis_warnings_reserved_bytes',
            'analysis_timings_reserved_bytes','analysis_text_reserved_bytes','stage_stats_reserved_bytes',
            'column_values_reserved_bytes','analysis_diagnostics_reserved_bytes'];
          assert.equal(result.analysis.diagnostics.workspace_reserved_bytes,
            retainedOwners.reduce((bytes,key)=>bytes+(result.analysis.diagnostics[key]??0),0),
            'retained workspace matches every admitted owner after processing');
          const actual = identity(result);
          reference ??= actual;
          assert.equal(actual, reference, 'v1 byte/order/metadata parity changed');
          samples[variant].push(result.elapsed_seconds);
          const {preview, header: ignored, ...analysis} = result.analysis;
          emit({type: 'measurement', shape, case: name, variant, workers: workersByVariant[variant] ?? 1,
            repeat: repeat + 1, seconds: result.elapsed_seconds,
            analysis_wall_seconds: result.analysis_wall_seconds, execution_seconds: result.execution_seconds,
            ...resourceUsage, browser_diagnostics: result.diagnostics, analysis, fingerprint: sha(actual), verified: true});
        }
      }
      const median = a => { const b = [...a].sort((x, y) => x - y); return (b[Math.floor(b.length / 2)] + b[Math.floor((b.length - 1) / 2)]) / 2; };
      const medians = Object.fromEntries(Object.entries(samples).map(([k, values]) => [k, median(values)]));
      const nativeRatios = Object.fromEntries(nativeWorkers.map(workers => [workers,
        medians[nativeName(labels[1], workers)] / medians[nativeName(labels[0], workers)]]));
      emit({type: 'summary', shape, case: name, median_seconds: medians,
        [labels.join(',') === 'merge,prefix' ? 'prefix_over_merge' : 'candidate_over_baseline']: {
          native: process.argv[11] ? nativeRatios : nativeRatios[1],
          browser: medians['browser-' + labels[1]] / medians['browser-' + labels[0]]},
        range_seconds: Object.fromEntries(Object.entries(samples).map(([k, values]) => [k, [Math.min(...values), Math.max(...values)]])), verified: true});
    }
  }
} finally {
  await browser?.close(); server?.kill();
  await writeFile(enginePath, originalWasm);
  await rm(root, {recursive: true, force: true});
  for (const [index, name] of generated.entries()) {
    if (originals[index] !== null) await writeFile('ui/dist/' + name, originals[index]);
    else await rm('ui/dist/' + name, {force: true});
  }
}
