// Matched complete hosted jobs using persistent disposable Chromium and OPFS.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createWriteStream} from 'node:fs';
import {appendFile, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {cpus, release} from 'node:os';
import {basename, join, resolve} from 'node:path';
import {pipeline} from 'node:stream/promises';
import {parseArgs} from 'node:util';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {browserChannel, browserLaunchOptions} from './browser-launch.mjs';

const {values:{run:runPath, fixtures:fixturePath, baseline, candidate, across, repeats, cases, workers, codecs, labels}} = parseArgs({options:{
  run:{type:'string'}, fixtures:{type:'string'}, baseline:{type:'string'}, candidate:{type:'string'},
  across:{type:'string'}, codecs:{type:'string',multiple:true}, labels:{type:'string'}, repeats:{type:'string',default:'3'}, cases:{type:'string',multiple:true}, workers:{type:'string',default:'0'},
}});
assert(runPath && fixturePath && baseline && candidate && cases?.length);
const run = resolve(runPath), fixtures = resolve(fixturePath);
const fixtureIndex = JSON.parse(await readFile(join(fixtures,'fixtures.json'),'utf8'));
const output = join(run,'runs.jsonl');
await mkdir(run);
const hashes = bytes=>createHash('sha256').update(bytes).digest('hex');
const emit = record=>appendFile(output, JSON.stringify(record)+'\n');
const panel = new Map([
  ['single',[]],['capped',[]],
  ['many',[{type:'balanced', files:8}]],
  ['hundreds',[{type:'balanced', files:256}]],
  ['heavy',[{type:'partition',columns:['region']},{type:'balanced',files:2}]],
]);
const driver = await build({
  entryPoints:['ui/tests/parallel-compression-benchmark.ts'],
  bundle:true, format:'esm', write:false,
});
const html = '<!doctype html><meta charset=utf-8><input id=fixture type=file><script type=module src="/driver.js"></script>';
const assets = ['engine-worker.js','storage-worker.js','engine.wasm'];
async function server(dist) {
  const files = new Map(await Promise.all(assets.map(async name=>['/'+name,await readFile(join(dist,name))])));
  files.set('/',Buffer.from(html));
  files.set('/driver.js',driver.outputFiles[0].contents);
  const owner = {output:undefined};
  const server = createServer(async (req,res)=>{
    res.setHeader('Cross-Origin-Opener-Policy','same-origin');
    res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
    res.setHeader('Cache-Control','no-store');
    const path = new URL(req.url,'http://loopback').pathname;
    if (req.method==='PUT' && path.startsWith('/result/') && owner.output) {
      try {
        const name = decodeURIComponent(path.slice('/result/'.length));
        assert(name && name===basename(name) && !/[\\/]/.test(name) && name!=='.' && name!=='..');
        await pipeline(req,createWriteStream(join(owner.output,name),{flags:'wx'}));
        res.writeHead(201);
      } catch { res.writeHead(500); }
      res.end();
      return;
    }
    const data = files.get(path);
    if (req.method!=='GET' || !data) {res.writeHead(404).end();return;}
    res.setHeader('Content-Type',path.endsWith('.wasm')?'application/wasm':path.endsWith('.js')?'text/javascript':'text/html');
    res.end(data);
  });
  await new Promise((done,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',done);});
  return Object.assign(owner,{
    url:'http://127.0.0.1:'+server.address().port,
    hashes:Object.fromEntries([...files].map(([name,data])=>[name,hashes(data)])),
    close:()=>new Promise(done=>server.close(done)),
  });
}
let browser;
const lanes = new Map();
try {
  const [baselineLabel,candidateLabel] = labels?.split(',') ?? ['baseline','blocks'];
  assert(baselineLabel && candidateLabel && baselineLabel!==candidateLabel);
  lanes.set(baselineLabel,await server(baseline));
  lanes.set(candidateLabel,await server(candidate));
  if (across) lanes.set('across',await server(across));
  browser = await chromium.launchPersistentContext(join(run,'profile'),browserLaunchOptions);
  await emit({kind:'environment',runtime:'hosted-chromium',browser:browser.browser()?.version(),channel:browserChannel,
    cpu:cpus()[0]?.model,kernel:release(),context:'persistent disposable bundled Chromium; OPFS-backed destination and scratch; warm uncontrolled',
    timer:'browser Run request through complete export and completion marker; picker setup and result extraction excluded',
    source:'Playwright-selected local File',worker_request:Number(workers),
    assets_sha256:Object.fromEntries([...lanes].map(([label,lane])=>[label,lane.hashes])),
    harness_sha256:hashes(await readFile(new URL(import.meta.url)))});
  for (const fixture of Object.values(fixtureIndex)) await emit(fixture);
  for (const cell of cases) {
    const [size, shape] = cell.split('/');
    const fixture = fixtureIndex[size], operations = panel.get(shape);
    assert(fixture && operations,cell);
    for (const codec of codecs ?? ['gzip','zip']) for (let repeat=0;repeat<Number(repeats);repeat++) {
      const labels = [...lanes.keys()];
      const start = repeat % labels.length;
      const order = labels.slice(start).concat(labels.slice(0,start));
      for (const label of order) {
        const lane = lanes.get(label);
        const dir = join(run,[size,shape,codec,repeat,label].join('-'));
        await mkdir(dir);
        lane.output = join(dir,'output');
        await mkdir(lane.output);
        const row = {kind:'run',label,codec,fixture:size,shape,repeat};
        const page = await browser.newPage();
        const failures = [];
        page.on('pageerror',error=>failures.push(String(error)));
        try {
          const job = {compression:codec,operations,resources:{workers:Number(workers),memory_mb:'auto'},
            limits:{bytes:shape==='single'?fixture.bytes+256:shape==='capped'?2**20:null}};
          await writeFile(join(dir,'job.json'),JSON.stringify(job)+'\n');
          row.job_sha256=hashes(await readFile(join(dir,'job.json')));
          await page.goto(lane.url);
          await page.waitForFunction(()=>typeof window.compressionBenchmark==='function');
          await page.locator('#fixture').setInputFiles(join(fixtures,size+'.csv'));
          const measured = await page.evaluate(config=>window.compressionBenchmark(config),job);
          const verifier = spawnSync('python3',['scripts/benchmark-parallel-compression.py','verify-output',lane.output,fixtures,size,shape,codec],{encoding:'utf8'});
          await writeFile(join(dir,'verify.log'),(verifier.stdout??'')+(verifier.stderr??''));
          if (verifier.error) throw verifier.error;
          assert.equal(verifier.status,0,verifier.stderr);
          const {manifest,...verification} = JSON.parse(verifier.stdout);
          if (shape==='single') assert(verification.csv_bytes<=job.limits.bytes);
          assert.deepEqual(failures,[]);
          Object.assign(row,{...verification,seconds:measured.seconds,status:'verified',
            workers:measured.analysis.workers,hardware_concurrency:measured.hardware_concurrency,
            cross_origin_isolated:measured.cross_origin_isolated,memory_budget_bytes:measured.analysis.memory_budget_bytes,
            diagnostics:measured.analysis.diagnostics,auto_plan:measured.analysis.auto_plan,marker:measured.marker,
            logical_digest:manifest.analysis.logical_digest});
          await writeFile(join(dir,'manifest.jsonl'),await readFile(join(lane.output,'manifest.jsonl')));
          await rm(lane.output,{recursive:true});
        } catch(error) {
          Object.assign(row,{status:'failed',error:String(error),page_errors:failures});
          throw error;
        } finally {
          await emit(row);
          console.log(size,shape,codec,repeat,label,row.seconds,row.status);
          await page.close();
          lane.output=undefined;
        }
      }
    }
  }
} finally {
  await browser?.close();
  for (const lane of lanes.values()) await lane.close();
}
