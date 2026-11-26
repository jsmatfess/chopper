import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile, writeFile, mkdir, rm, appendFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {cpus, release, totalmem} from 'node:os';
import {join, resolve} from 'node:path';
import {build, stop} from '../../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../../ui/node_modules/playwright/index.mjs';

const [baseline, direct256, direct512, destination, mode, browserExecutable] = process.argv.slice(2);
assert(baseline && direct256 && direct512 && destination && browserExecutable && ['smoke', 'measure', 'faults', 'quota'].includes(mode));
const output = resolve(destination);
const script = new URL(import.meta.url);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
await mkdir(output);
const emit = value => appendFile(join(output, 'runs.jsonl'), JSON.stringify(value) + '\n');
const stockDriver = await readFile('ui/tests/benchmark-swarm.ts', 'utf8');
const driver = stockDriver
  .replace('const input = new File([await response.arrayBuffer()], \'input.csv\');', `const source = await root.getFileHandle('fixture.csv', {create: true});
    const writer = await source.createWritable();
    await response.body!.pipeTo(writer);
    const input = await source.getFile();`)
  .replace('diagnostics.workspace_reserved_bytes === owners.reduce', "diagnostics.workspace_reserved_bytes === (done.analysis as any).auto_plan.physical_plan.startsWith('private_terminal') * (8192 + '/results'.length) + owners.reduce")
  .replace("if (state.status === 'failed' || state.error)", "if (state.status === 'cancelled' || state.status === 'failed' || state.error)")
  .replace('  swarmCollect:', `  swarmInspect: async () => {
    const entries = [];
    for await (const [name] of (destination as any).entries()) entries.push(name);
    return {entries, state: await api('state'), diagnostics: structuredClone(browserDiagnostics)};
  },
  swarmCancel: () => api('cancel', {}),
  swarmCollect:`);
assert(driver.includes('response.body!.pipeTo(writer)') && driver.includes('swarmInspect'));
const compiled = await build({stdin:{contents:driver,resolveDir:'ui/tests',loader:'ts'},bundle:true,format:'iife',define:{__HOSTED__:'true'},write:false});
const workers = await build({entryPoints:['ui/src/browser/engine-worker.ts','ui/src/browser/storage-worker.ts'],bundle:true,format:'esm',outdir:output,write:false});
const assets = Object.fromEntries(workers.outputFiles.map(file=>[file.path.split('/').at(-1),file.contents]));
assets['driver.js'] = compiled.outputFiles[0].contents;
await stop();
const engines = {baseline:await readFile(baseline),direct256:await readFile(direct256),direct512:await readFile(direct512)};
const variants = Object.keys(engines);
const storageWrapper = `import '/storage-worker-production.js';
const open = FileSystemFileHandle.prototype.createWritable;
let triggered = false, closedCsv = 0;
const openFiles = new Set();
FileSystemFileHandle.prototype.createWritable = async function (...args) {
  const writer = await Reflect.apply(open, this, args);
  const name = this.name;
  if (name === 'CHOPPER-COMPLETE.json') {
    postMessage({markerOpened:{openFiles:[...openFiles],closedCsv}});
  }
  openFiles.add(name);
  return new Proxy(writer, {get(target, key) {
    const value = Reflect.get(target, key, target);
    if (key === 'close') return async (...args) => {
      const result = await Reflect.apply(value, target, args);
      openFiles.delete(name);
      if (name.endsWith('.csv')) closedCsv++;
      return result;
    };
    if (key === 'write') return async (...args) => {
      if (!triggered && ((MODE === 'marker' && name === 'CHOPPER-COMPLETE.json')
        || (MODE !== 'marker' && name.endsWith('.csv') && closedCsv > 0))) {
        triggered = true;
        postMessage({faultReached:{name,closedCsv}});
        if (MODE === 'cancel') await new Promise(resolve => setTimeout(resolve, 350));
        else throw new Error('Injected ' + MODE + ' write failure');
      }
      return Reflect.apply(value, target, args);
    };
    return typeof value === 'function' ? value.bind(target) : value;
  }});
};`;
let active = 'baseline', fixture, fault = null;
const server = createServer((req,res) => {
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('Cache-Control','no-store');
  const path = req.url.slice(1);
  if (!path) return res.end('<!doctype html><main class="editor"></main><script src="/driver.js"></script>');
  if (path.endsWith('.js')) res.setHeader('Content-Type','application/javascript');
  if (path === 'engine.wasm') {
    res.setHeader('Content-Type','application/wasm');
    return res.end(engines[active]);
  }
  if (path === 'input.csv') return res.end(fixture);
  if (path === 'storage-worker.js' && fault) return res.end('const MODE = '+JSON.stringify(fault)+';\n'+storageWrapper);
  if (path === 'storage-worker-production.js') return res.end(assets['storage-worker.js']);
  if (assets[path]) return res.end(assets[path]);
  res.statusCode=404;
  res.end();
});
const keys = 8, rowCap = 4000, byteCap = 512 * 1024;
const keyFor = id => 'g' + id % keys;
const payloadFor = (id, width) => String.fromCharCode(97 + id % 26).repeat(width);
const rowsFor = (count, width) => {
  const blocks = ['id,key,payload\n'];
  for (let i = 0; i < count; i += 4096) {
    blocks.push(Array.from({length:Math.min(4096,count-i)}, (_,j) => {
      const id = i + j;
      return id+','+keyFor(id)+','+payloadFor(id,width)+'\n';
    }).join(''));
  }
  return Buffer.from(blocks.join(''));
};
function config(memory, limits = {}) {
  return {operations:[{type:'partition',columns:['key']},{type:'shuffle',strategy:'uniform'}],
    compression:'none', resources:{memory_mb:memory,workers:1,max_record_bytes:1048576, grouping:'auto'},
    limits:{rows:rowCap,bytes:byteCap,compressed_bytes:null,...limits}};
}
async function verify(page, result, rows, width, limits) {
  const read = async name => {
    const size = result.files.find(file=>file.name===name).size;
    const blocks = [];
    for(let offset=0;offset<size;offset+=1024*1024) {
      const data = await page.evaluate(([name,offset]) => window.swarmCollect(name,offset),[name,offset]);
      blocks.push(Buffer.from(data,'base64'));
    }
    return Buffer.concat(blocks);
  };
  const manifestBytes = await read('manifest.jsonl');
  const [head,...entries] = manifestBytes.toString('utf8').trimEnd().split('\n').map(line=>JSON.parse(line));
  const marker = JSON.parse((await read('CHOPPER-COMPLETE.json')).toString('utf8'));
  assert.deepEqual(marker,{complete:true,files:entries.length+1,engine:'chopper-browser',version:1});
  assert.equal(head.type, 'job');
  assert.equal(head.analysis.rows, rows);
  assert.deepEqual(head.analysis.stages.map(stage=>[stage.operation,stage.input_groups,stage.output_groups]), [[1,1,keys],[2,keys,keys]]);
  assert.equal(result.analysis.groups, keys);
  assert.equal(result.analysis.output_files, entries.length);
  assert.deepEqual(result.files.map(file=>file.name).sort(), ['manifest.jsonl','CHOPPER-COMPLETE.json', ...entries.map(entry=>entry.path)].sort());
  const seen = new Uint8Array(rows);
  const membership = new Map();
  const hashes = [];
  let count = 0, bytes = 0, descents = 0, groupsOutOfEncounterOrder = 0;
  let previous = -1, previousKey = '', groupDescents = 0, rowLimitedChunks = 0, byteLimitedChunks = 0;
  let previousChunk;
  // Fixture fields deliberately contain no delimiters, quote escapes, or newlines.
  for (const [index, entry] of entries.entries()) {
    assert.equal(entry.type,'output');
    const key = entry.lineage[0].values[0];
    const digits = String(index+1).padStart(8,'0');
    assert.equal(entry.path,'key-'+key+'-part-'+digits+'.csv');
    assert.deepEqual(entry.lineage,[{operation:0,values:[key]}]);
    const buffer = await read(entry.path);
    assert.equal(buffer.length,entry.csv_bytes);
    assert.equal(buffer.length,entry.stored_bytes);
    assert.equal(entry.compressed_target_exceeded,false);
    assert(buffer.length <= limits.bytes && buffer.at(-1) === 10);
    const [header,...lines] = buffer.toString('utf8').slice(0,-1).split('\n');
    assert.equal(header,'id,key,payload');
    assert.equal(lines.length,entry.rows);
    assert(lines.length > 0 && lines.length <= limits.rows);
    rowLimitedChunks += Number(lines.length === limits.rows);
    if (key === previousKey && previousChunk.rows < limits.rows) {
      assert(previousChunk.csv_bytes + lines[0].length + 1 > limits.bytes);
      byteLimitedChunks++;
    }
    if (key !== previousKey) {
      assert(key > previousKey);
      groupsOutOfEncounterOrder += Number(groupDescents > 0);
      previous = -1;
      groupDescents = 0;
      previousKey = key;
    }
    for (const line of lines) {
      const [idText, fieldKey, payload, ...rest] = line.split(',');
      const id = Number(idText);
      assert(Number.isSafeInteger(id) && id >= 0 && id < rows && !seen[id] && !rest.length);
      assert.equal(idText,String(id));
      assert.equal(fieldKey,key);
      assert.equal(fieldKey,keyFor(id));
      assert.equal(payload,payloadFor(id,width));
      seen[id] = 1;
      groupDescents += Number(id < previous);
      descents += Number(id < previous);
      previous = id;
    }
    previousChunk = entry;
    membership.set(key,(membership.get(key)??0)+lines.length);
    count += lines.length;
    bytes += buffer.length;
    hashes.push(sha(buffer));
  }
  groupsOutOfEncounterOrder += Number(groupDescents > 0);
  assert.equal(count,rows);
  assert.equal(membership.size,keys);
  assert.equal(groupsOutOfEncounterOrder,keys);
  assert.equal(result.analysis.output_csv_bytes,bytes);
  return {rows:count,groups:membership.size,files:entries.length,csv_bytes:bytes,
    row_limited_chunks:rowLimitedChunks,byte_limited_chunks:byteLimitedChunks,
    descents,groups_out_of_encounter_order:groupsOutOfEncounterOrder,
    logical_digest:result.analysis.logical_digest,ordered_csv_sha256:sha(hashes.join('\n')),
    marker};
}

let browser;
try {
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const origin = 'http://127.0.0.1:'+server.address().port;
  browser = await chromium.launchPersistentContext(join(output,'profile'),{headless:true,executablePath:browserExecutable,args:['--no-zygote','--disable-breakpad','--disable-crash-reporter']});
  const page = await browser.newPage();
  page.on('pageerror', error=>console.error(error));
  await page.addInitScript(() => {
    window.faultReached = null;
    window.runEvents = [];
    class CapturedWorker extends Worker {
      constructor(...args) {
        super(...args);
        this.addEventListener('message', ({data}) => {
          if (data.faultReached) window.faultReached = data.faultReached;
          if (data.markerOpened) window.markerOpened = data.markerOpened;
          const {observation,observationFinal,exporting,error,storage} = data;
          if (observationFinal) window.finalObservation = observationFinal;
          if (observation?.export?.status === 'active' && !window.runEvents.includes('export-active'))
            window.runEvents.push('export-active');
          if (observation?.marker?.status === 'active' && !window.runEvents.includes('marker-active'))
            window.runEvents.push('marker-active');
          if (exporting) window.runEvents.push('destination-opened');
          if (error && storage) window.runEvents.push('storage-error');
        });
      }
    }
    window.Worker = CapturedWorker;
  });
  await emit({kind:'environment',browser:browser.browser().version(),context:'persistent disposable bundled Chromium on local warm uncontrolled OPFS',
    os:release(),cpu:cpus()[0].model,cpus:cpus().length,memory_bytes:totalmem(),node:process.version,
    browser_executable_sha256:sha(await readFile(browserExecutable)),
    harness_sha256:sha(await readFile(script)),stock_driver_sha256:sha(stockDriver),
    assets:Object.fromEntries(Object.entries({...engines,...assets}).map(([name,bytes])=>[name,sha(bytes)])),
    scope:'Run request through verified completion marker and worker retirement. Excludes fixture import, output verification and successful-result removal.'});
  if (mode === 'faults') {
    const source = rowsFor(30001, 240);
    for (const variant of variants) for (const test of ['write','marker','cancel','file-limit','byte-cap','malformed']) {
      fixture = test === 'malformed' ? Buffer.concat([source,Buffer.from('30001,g1\n')]) : source;
      active = variant;
      fault = ['write','marker','cancel'].includes(test) ? test : null;
      await page.goto(origin);
      await page.waitForFunction(()=>typeof window.swarmRun === 'function');
      const job = config(32, test === 'byte-cap' ? {bytes:64} : {});
      if (test === 'file-limit') job.resources.max_files = 2;
      const running = page.evaluate(async job => {
        try { await window.swarmRun(job, 20); return {success:true}; }
        catch(error) { return {error:String(error)}; }
      },job);
      if (test === 'cancel') {
        await page.waitForFunction(()=>!!window.faultReached, null, {timeout:15000});
        await page.evaluate(()=>window.swarmCancel());
      }
      const result = await running;
      await page.waitForFunction(async()=> (await window.swarmInspect()).diagnostics.storage?.workspace_bytes_after_cleanup === 0);
      const inspect = await page.evaluate(()=>window.swarmInspect());
      const {faultReached:reached,markerOpened,runEvents} = await page.evaluate(()=>({faultReached:window.faultReached,markerOpened:window.markerOpened,runEvents:window.runEvents}));
      await emit({kind:'fault',variant,test,result,inspect,reached,markerOpened,runEvents});
      assert.equal(inspect.entries.length,0);
      assert.equal(inspect.diagnostics.storage.workspace_bytes_after_cleanup,0);
      assert.equal(inspect.state.status,test === 'cancel' ? 'cancelled' : 'failed');
      if (fault) assert(reached?.closedCsv > 0);
      if (test === 'marker') assert.deepEqual(markerOpened,{openFiles:[],closedCsv:16});
      else assert.equal(markerOpened,undefined);
      if (test === 'malformed') assert(!runEvents.includes('destination-opened'));
      assert(!result.success);
      if (test === 'write' || test === 'marker') assert.match(result.error,/Injected (write|marker) write failure/);
      if (test === 'file-limit') assert.match(result.error,/max_files/);
      if (test === 'byte-cap') assert.match(result.error,/byte|cap/i);
      if (test === 'malformed') assert.match(result.error,/expected|column|field/i);
      await page.evaluate(()=>window.swarmCleanup());
    }
  } else {
    const cases = mode === 'smoke'
      ? [{cell:'smoke',rows:2049,width:48,memory:32,pairs:1}]
      : mode === 'quota'
      ? [{cell:'quota',rows:420003,width:240,memory:32,pairs:0,tempBytes:190*1024*1024}]
      : [{cell:'resident',rows:32771,width:48,memory:128,pairs:3},
         {cell:'external',rows:420003,width:240,memory:128,pairs:3},
         {cell:'tight',rows:420003,width:240,memory:32,pairs:3},
         {cell:'wider-cap',rows:180003,width:576,memory:128,pairs:3,limits:{bytes:2*1024*1024}}];
    for (const cell of cases) {
      const {rows,width,memory,pairs,tempBytes,limits} = cell;
      const job = config(memory, limits);
      if (tempBytes) job.resources.temp_bytes = tempBytes;
      fixture = rowsFor(rows,width);
      await emit({kind:'fixture',...cell,sha256:sha(fixture),bytes:fixture.length,job});
      for (let pair = -1; pair < pairs; pair++) for (const index of variants.keys()) {
        const variant = variants[(index + pair + variants.length) % variants.length];
        active = variant;
        await page.goto(origin);
        await page.waitForFunction(()=>typeof window.swarmRun === 'function');
        try {
          if (tempBytes && variant === 'baseline') {
            const error = await page.evaluate(async job => {
              try { await window.swarmRun(job, 120); return null; }
              catch (error) { return String(error); }
            },job);
            await page.waitForFunction(async()=> (await window.swarmInspect()).diagnostics.storage?.workspace_bytes_after_cleanup === 0);
            const inspect = await page.evaluate(()=>window.swarmInspect());
            const runEvents = await page.evaluate(()=>window.runEvents);
            await emit({kind:'quota-denial',cell:cell.cell,variant,error,inspect,runEvents});
            assert.match(error,/temp|space/i);
            assert.equal(inspect.state.status,'failed');
            assert.equal(inspect.entries.length,0);
            assert(!runEvents.includes('destination-opened'));
            await page.evaluate(()=>window.swarmCleanup());
            continue;
          }
          const result = await page.evaluate(job=>window.swarmRun(job,120),job);
          const {finalObservation,runEvents} = await page.evaluate(()=>({finalObservation:window.finalObservation, runEvents:window.runEvents}));
          const checks = await verify(page,result,rows,width,job.limits);
          const physical = finalObservation.physical.map(({kind,operations,status,sources,rows,bytes,seconds,runs})=>({kind,operations,status,sources,rows,bytes,seconds,runs}));
          const {physical_plan,measurements} = result.analysis.auto_plan;
          const resources = result.analysis.diagnostics;
          const sample = {kind:'measurement',cell:cell.cell,pair,variant,seconds:result.elapsed_seconds,checks,physical_plan,measurements,
            peak_temp_bytes:result.analysis.peak_temp_bytes,
            peak_storage:result.diagnostics.storage,
            bridge:{destination_write:result.diagnostics.execute.destination_write,source_read:result.diagnostics.execute.source_read},
            resources:{sort_runs:resources.sort_runs,merge_operations:resources.merge_operations,resident_sorts:resources.resident_sorts},
            physical,runEvents,marker:finalObservation.marker,export:finalObservation.export,completedStages:finalObservation.completedStages,unavailable:finalObservation.unavailable};
          await emit(sample);
          assert.equal(physical_plan,variant === 'baseline'?'snapshot':'private_terminal');
          assert.equal(physical.some(p=>p.kind==='materialize'),variant === 'baseline');
          assert(physical.some(p=>p.kind==='serialize' && p.status==='completed' && p.rows===rows));
          assert.equal(finalObservation.marker.status,'completed');
          assert.equal(finalObservation.export.status,'completed');
          assert.equal(finalObservation.processingComplete,true);
          assert.equal(finalObservation.unavailable,false);
          if (tempBytes) assert(sample.peak_temp_bytes <= tempBytes);
          await page.evaluate(()=>window.swarmCleanup());
          console.log(JSON.stringify({cell:cell.cell,pair,variant,seconds:sample.seconds,temp:sample.peak_temp_bytes,measurements}));
        } catch(error) {
          const inspect = await page.evaluate(()=>window.swarmInspect()).catch(()=>null);
          await emit({kind:'failure',cell:cell.cell,pair,variant,error:String(error),stack:error.stack,inspect});
          throw error;
        }
      }
    }
  }
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise(ok=>server.close(ok));
}
