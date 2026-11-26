import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createReadStream, createWriteStream} from 'node:fs';
import {appendFile, mkdir, readFile, readdir, rm, stat} from 'node:fs/promises';
import {createServer} from 'node:http';
import {cpus, release, totalmem} from 'node:os';
import {join, resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {build, stop} from '../../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../../ui/node_modules/playwright/index.mjs';

const [configPath, outputPath] = process.argv.slice(2);
assert(configPath && outputPath, 'Usage: node bench.mjs CONFIG.json NEW_OUTPUT_DIRECTORY');
const configBytes = await readFile(configPath);
const options = JSON.parse(configBytes);
const output = resolve(outputPath);
await mkdir(output);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const fileHash = async path => {
  const hash = createHash('sha256');
  for await (const block of createReadStream(path)) hash.update(block);
  return hash.digest('hex');
};
const emit = value => appendFile(join(output, 'runs.jsonl'), JSON.stringify(value) + '\n');

let driver = await readFile('ui/tests/benchmark-swarm.ts', 'utf8');
function replaceDriver(from, to) {
  assert(driver.includes(from), 'Benchmark driver changed: '+from);
  driver = driver.replace(from, to);
}
replaceDriver(
  "    const response = await fetch('/input.csv');\n    check(response.ok, 'Fixture fetch failed');\n    const input = new File([await response.arrayBuffer()], 'input.csv');",
  '    const input: File = (window as any).fixtureFile;',
);
replaceDriver(
  'diagnostics.workspace_reserved_bytes === owners.reduce',
  "diagnostics.workspace_reserved_bytes === Number((done.analysis as any).auto_plan.physical_plan === 'private_terminal') * (8192 + '/results'.length) + owners.reduce",
);
replaceDriver('  swarmCollect:', [
  '  importFixture: async () => {',
  "    const source = await (await navigator.storage.getDirectory()).getFileHandle('fixture.csv', {create:true});",
  "    const response = await fetch('/input.csv');",
  "    check(response.ok, 'Fixture fetch failed');",
  '    await response.body!.pipeTo(await source.createWritable());',
  '    (window as any).fixtureFile = await source.getFile();',
  '  },',
  '  sendExport: async () => {',
  '    for (const {name} of files) {',
  '      const file = await (await folder.getFileHandle(name)).getFile();',
  "      const response = await fetch('/collected/'+encodeURIComponent(name), {method:'POST',body:file});",
  "      check(response.ok, 'Sending export '+name+' failed: '+await response.text());",
  '    }',
  '  },',
  '  swarmCollect:',
].join('\n'));
const assets = new Map();
for (const asset of (await build({
  entryPoints: ['ui/src/browser/engine-worker.ts','ui/src/browser/storage-worker.ts'],
  bundle:true, format:'esm', outdir:output, write:false,
})).outputFiles) assets.set(asset.path.split('/').at(-1),asset.contents);
const compiled = await build({
  stdin:{contents:driver,resolveDir:'ui/tests',loader:'ts'},
  bundle:true,format:'iife',define:{__HOSTED__:'true'},write:false,
});
assets.set('driver.js',compiled.outputFiles[0].contents);
await stop();

const engines = new Map(await Promise.all(Object.entries(options.engines)
  .map(async ([name,path]) => [name,await readFile(path)])));
const variants = [...engines.keys()];
assert.equal(variants[0], 'baseline');
assert(variants.length >= 2);
let active, input, capture;
const server = createServer(async (req,res) => {
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('Cache-Control','no-store');
  try {
    const path = req.url.slice(1);
    if (path === '') {
      res.setHeader('Content-Type','text/html');
      res.end('<!doctype html><main class="editor"></main><script src="/driver.js"></script>');
    } else if (path === 'engine.wasm') {
      res.setHeader('Content-Type','application/wasm');
      res.end(engines.get(active));
    } else if (path === 'input.csv') {
      res.setHeader('Content-Length',input.bytes);
      await pipeline(createReadStream(input.path),res);
    } else if (assets.has(path)) {
      res.setHeader('Content-Type','application/javascript');
      res.end(assets.get(path));
    } else if (req.method === 'POST' && path.startsWith('collected/') && capture) {
      const name = decodeURIComponent(path.slice('collected/'.length));
      assert(capture.files.has(name) && /^[a-zA-Z0-9_.-]+$/.test(name));
      const expected = capture.files.get(name);
      assert.equal(Number(req.headers['content-length']),expected);
      const target = join(capture.directory,name);
      await pipeline(req,createWriteStream(target,{flags:'wx'}));
      assert.equal((await stat(target)).size,expected);
      capture.files.delete(name);
      res.end();
    } else {
      res.statusCode=404;
      res.end();
    }
  } catch(error) {
    console.error(error);
    res.statusCode=500;
    res.end(String(error));
  }
});
const header = 'id,key,payload';
function keyFor(id, fixture) {
  if (!fixture.skewEvery) return 'g'+(id % fixture.keys).toString().padStart(4,'0');
  return id % fixture.skewEvery === 0
    ? 'g'+(1+Math.floor(id/fixture.skewEvery)%(fixture.keys-1)).toString().padStart(4,'0')
    : 'g0000';
}
const payloadFor = (id,width) => String.fromCharCode(97+id%26).repeat(width);
function* csv(fixture) {
  const widths = fixture.widths;
  const payloads = widths.map(width => Array.from({length:26},(_,id)=>payloadFor(id,width)));
  yield header+'\n';
  for(let offset=0;offset<fixture.rows;offset+=1024) {
    const block = [];
    for(let id=offset;id<Math.min(offset+1024,fixture.rows);id++) {
      block.push(id+','+keyFor(id,fixture)+','+payloads[id%widths.length][id%26]+'\n');
    }
    yield block.join('');
  }
}
function jobFor(fixture) {
  return {
    operations:[{type:'partition',columns:['key']},{type:'shuffle',strategy:fixture.shuffle??'uniform'}],
    compression:'none',
    resources:{memory_mb:fixture.memory,workers:1,max_record_bytes:fixture.recordCap??1048576,grouping:'auto',
      max_files:fixture.maxFiles??8192,temp_bytes:fixture.tempBytes??null},
    limits:{rows:fixture.rowCap??null,bytes:fixture.byteCap??null,compressed_bytes:null},
  };
}
async function verify(directory, result, fixture, job) {
  const [head,...entries] = (await readFile(join(directory,'manifest.jsonl'),'utf8')).trimEnd().split('\n').map(line=>JSON.parse(line));
  const marker = JSON.parse(await readFile(join(directory,'CHOPPER-COMPLETE.json'),'utf8'));
  assert.deepEqual(marker,{complete:true,files:entries.length+1,engine:'chopper-browser',version:1});
  assert.equal(head.type,'job');
  assert.equal(head.analysis.rows,fixture.rows);
  assert.deepEqual(head.analysis.stages.map(stage=>[stage.operation,stage.input_groups,stage.output_groups]),
    [[1,1,fixture.keys],[2,fixture.keys,fixture.keys]]);
  const expectedFiles = ['manifest.jsonl','CHOPPER-COMPLETE.json',...entries.map(entry=>entry.path)].sort();
  assert.deepEqual((await readdir(directory)).sort(),expectedFiles);
  assert.deepEqual(result.files.map(file=>file.name).sort(),expectedFiles);
  const seen = new Uint8Array(fixture.rows);
  const membership = new Set();
  const hashes = createHash('sha256');
  const byteCap = job.limits.bytes??Infinity, rowCap = job.limits.rows??Infinity;
  let rows=0, bytes=0, descents=0, previous=-1, previousKey='', previousChunk;
  const payloads = fixture.widths.map(width=>Array.from({length:26},(_,id)=>payloadFor(id,width)));
  for (const [index,entry] of entries.entries()) {
    assert.equal(entry.type,'output');
    const key = entry.lineage[0].values[0];
    assert.equal(entry.path,'key-'+key+'-part-'+String(index+1).padStart(8,'0')+'.csv');
    assert.deepEqual(entry.lineage,[{operation:0,values:[key]}]);
    assert.equal(entry.compressed_target_exceeded,false);
    assert(entry.rows>0 && entry.rows<=rowCap && entry.csv_bytes<=byteCap);
    const path = join(directory,entry.path);
    const size = (await stat(path)).size;
    assert.equal(size,entry.csv_bytes);
    assert.equal(size,entry.stored_bytes);
    const current = createHash('sha256');
    const contents = createReadStream(path);
    contents.on('data',chunk=>current.update(chunk));
    let fileRows=0, fileBytes=0;
    if (key!==previousKey) {
      assert(key>previousKey);
      previous=-1;
    }
    for await (const line of createInterface({input:contents,crlfDelay:Infinity})) {
      if (fileBytes===0) {
        assert.equal(line,header);
      } else {
        if (fileRows===0 && key===previousKey && previousChunk.rows<rowCap) {
          assert(previousChunk.csv_bytes+line.length+1>byteCap);
        }
        const [idText,fieldKey,payload,extra] = line.split(',');
        const id = Number(idText);
        assert(Number.isSafeInteger(id) && id>=0 && id<fixture.rows && !seen[id]);
        assert.equal(idText,String(id));
        assert.equal(fieldKey,key);
        assert.equal(fieldKey,keyFor(id,fixture));
        assert.equal(extra,undefined);
        assert.equal(payload,payloads[id%payloads.length][id%26]);
        seen[id]=1;
        descents += Number(id<previous);
        previous=id;
        fileRows++;
      }
      fileBytes+=line.length+1;
    }
    assert.equal(fileRows,entry.rows);
    assert.equal(fileBytes,size);
    membership.add(key);
    rows+=fileRows;
    bytes+=fileBytes;
    hashes.update(current.digest());
    previousKey=key;
    previousChunk=entry;
  }
  assert.equal(rows,fixture.rows);
  assert.equal(membership.size,fixture.keys);
  assert(descents>0);
  assert.equal(result.analysis.output_files,entries.length);
  assert.equal(result.analysis.output_csv_bytes,bytes);
  return {rows,groups:membership.size,files:entries.length,csv_bytes:bytes,descents,
    ordered_csv_sha256:hashes.digest('hex'),logical_digest:result.analysis.logical_digest,marker};
}

let browser;
try {
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const origin='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launchPersistentContext(join(output,'profile'),{
    headless:true,executablePath:options.browser,
    args:['--no-zygote','--disable-breakpad','--disable-crash-reporter'],
  });
  const page=await browser.newPage();
  page.on('pageerror',error=>console.error(error));
  await page.addInitScript(()=>{
    class MeasuredWorker extends Worker {
      constructor(...args) {
        super(...args);
        this.addEventListener('message',({data})=>{
          if(data.observationFinal) window.finalObservation=data.observationFinal;
        });
      }
    }
    window.Worker=MeasuredWorker;
  });
  await emit({kind:'environment',browser:browser.browser().version(),
    source_and_destination:'OPFS on WSL ext4 with warm uncontrolled caches',
    scope:'Request through verified output marker and workspace retirement including worker startup. Fixture import, verification, and successful result removal outside timing.',
    os:release(),cpu:cpus()[0].model,cpus:cpus().length,memory_bytes:totalmem(),node:process.version,
    config_sha256:sha(configBytes),script_sha256:await fileHash(new URL(import.meta.url)),
    executable_sha256:await fileHash(options.browser),
    assets:Object.fromEntries([...engines,...assets].map(([name,bytes])=>[name,sha(bytes)]))});
  for (const fixture of options.cases) {
    assert(/^[a-z0-9-]+$/.test(fixture.name));
    active='baseline';
    const fixturePath=join(output,fixture.name+'.csv');
    await pipeline(Readable.from(csv(fixture)),createWriteStream(fixturePath,{flags:'wx'}));
    input={path:fixturePath,bytes:(await stat(fixturePath)).size};
    const job=jobFor(fixture);
    await page.goto(origin);
    await page.waitForFunction(()=>typeof window.swarmRun==='function');
    await page.evaluate(()=>window.importFixture());
    await emit({kind:'fixture',...fixture,bytes:input.bytes,sha256:await fileHash(fixturePath),job});
    const arms=fixture.variants??variants;
    for(let pair=fixture.warmup ? -1 : 0;pair<fixture.pairs;pair++) for (const index of arms.keys()) {
      active=arms[(index+pair+arms.length)%arms.length];
      const name=fixture.name+'-'+pair+'-'+active;
      const directory=join(output,name);
      await mkdir(directory);
      try {
        const result=await page.evaluate(([job,timeout])=>window.swarmRun(job,timeout),[job,options.runTimeout]);
        const observed=await page.evaluate(()=>window.finalObservation);
        capture={directory,files:new Map(result.files.map(({name,size})=>[name,size]))};
        await page.evaluate(()=>window.sendExport());
        assert.equal(capture.files.size,0);
        capture=null;
        const checks=await verify(directory,result,fixture,job);
        const {physical_plan,measurements,effective_memory_bytes,memory_plan}=result.analysis.auto_plan;
        const expected=fixture.expect?.[active]??(active==='baseline'?'snapshot':'private_terminal');
        const physical=observed.physical.map(({kind,operations,status,rows,runs,seconds})=>({kind,operations,status,rows,runs,seconds}));
        assert.equal(physical_plan,expected);
        assert.equal(physical.some(step=>step.kind==='materialize'),expected==='snapshot');
        assert(physical.some(step=>step.kind==='serialize' && step.status==='completed' && step.rows===fixture.rows));
        assert.deepEqual(observed.completedStages,[0,1,2,3]);
        assert.equal(observed.export.status,'completed');
        assert.equal(observed.marker.status,'completed');
        assert.equal(observed.unavailable,false);
        await page.evaluate(()=>window.swarmCleanup());
        await rm(directory,{recursive:true});
        const {sort_runs,merge_operations,resident_sorts}=result.analysis.diagnostics;
        const row={kind:'measurement',cell:fixture.name,pair,variant:active,seconds:result.elapsed_seconds,
          checks,physical_plan,measurements,effective_memory_bytes,memory_plan:{...memory_plan},
          peak_temp_bytes:result.analysis.peak_temp_bytes,storage:result.diagnostics.storage,
          bridge:{destination_write:result.diagnostics.execute.destination_write,source_read:result.diagnostics.execute.source_read},
          sort:{sort_runs,merge_operations,resident_sorts},physical,marker:observed.marker};
        await emit(row);
        console.log(JSON.stringify({cell:row.cell,pair,variant:active,seconds:row.seconds,placement:physical_plan,sort_runs}));
      } catch(error) {
        const failure=await page.evaluate(()=>window.swarmFailure()).catch(()=>null);
        await emit({kind:'failure',cell:fixture.name,pair,variant:active,error:String(error),stack:error.stack,failure});
        throw error;
      }
    }
  }
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise(ok=>server.close(ok));
}
