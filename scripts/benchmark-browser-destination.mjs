import {compileDestinationWorker as compile,compileAsyncDestinationEngine,compileSynchronousDestinationEngine,asyncDestinationStorage,batchDestinationStorage} from './browser-async-destination.mjs';
import {createHash} from 'node:crypto';
import {spawn,execFileSync} from 'node:child_process';
import {readFile,writeFile} from 'node:fs/promises';
import {platform,release,cpus} from 'node:os';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {serverLifetime} from './browser-acceptance.mjs';
import {stagedDestinationWorker,destinationFixture} from './browser-destination-fixtures.mjs';

// Run from a disposable hosted build. This script adds benchmark-only assets to ui/dist.
const dist='ui/dist/';
const asyncPanel=process.argv.includes('--async');
const sha=value=>createHash('sha256').update(value).digest('hex');
const staged=await stagedDestinationWorker();
const batched=await compile('storage-worker',batchDestinationStorage);
const syncEngine=await compileSynchronousDestinationEngine();
const asyncEngine=asyncPanel?await compileAsyncDestinationEngine():null;
const asyncStorage=asyncPanel?await compile('storage-worker',asyncDestinationStorage):null;
const asyncBatched=asyncPanel?await compile('storage-worker',source=>asyncDestinationStorage(batchDestinationStorage(source))):null;
const rows=asyncPanel?196608:32768;
const csv=destinationFixture(rows);
await writeFile(dist+'benchmark.csv',csv);
await writeFile(dist+'benchmark.html','<!doctype html><script type="module" src="/benchmark.js"></script>');
await build({entryPoints:['ui/tests/benchmark.ts'],bundle:true,format:'esm',outfile:dist+'benchmark.js'});
const fixture={bytes:Buffer.byteLength(csv),sha256:sha(csv),rows};
const origin='http://127.0.0.1:8424';
const server=spawn(process.execPath,['scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8424'},stdio:['ignore','pipe','inherit']});
const lifetime=serverLifetime(server,origin,15000,5000);
const buildHashes=Object.fromEntries(await Promise.all(['engine.wasm','engine-worker.js','storage-worker.js','benchmark.js'].map(async file=>[file,sha(await readFile(dist+file))])));
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),os:platform(),kernel:release(),cpu:cpus()[0]?.model,
  benchmark_sha256:sha(await readFile('scripts/benchmark-browser-destination.mjs')),
  fixture_worker_sha256:sha(await readFile('scripts/browser-destination-fixtures.mjs')),
  async_fixture_sha256:asyncPanel?sha(await readFile('scripts/browser-async-destination.mjs')):undefined,node:process.version,
  storage:'Same-origin OPFS parent in disposable Chromium contexts',fixture,builds:{...buildHashes,staged:sha(staged),sync_engine:sha(syncEngine),batched:sha(batched),
    ...(asyncPanel?{async_engine:sha(asyncEngine),async_storage:sha(asyncStorage),async_batched:sha(asyncBatched)}:{})},
  runs:[]};
const headers={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'};
const modes=asyncPanel?['direct','batched','async','async-batched']:['staged','direct','batched'];
const cap=asyncPanel?8*1024*1024:1024*1024;
const configs=[
  ['streaming',{operations:[],limits:{rows:null,bytes:cap,compressed_bytes:null}}],
  ...(asyncPanel?[['gzip',{compression:'gzip',operations:[],limits:{rows:null,bytes:cap,compressed_bytes:null}}]]:[]),
  ['partition',{operations:[{type:'partition',columns:[1]}],limits:{rows:null,bytes:cap,compressed_bytes:null}}],
];
let browser;
try{
  await lifetime.ready;browser=await chromium.launch({headless:true});report.browser=browser.version();
  const hashes=new Map();
  for(const [job,config] of configs)for(let rep=0;rep<(asyncPanel?4:5);rep++)for(let step=0;step<modes.length;step++){
    const mode=modes[(rep+step)%modes.length],context=await browser.newContext(),page=await context.newPage();
    const record={job,rep,mode,config,requested_memory:'auto'};report.runs.push(record);
    try{
      await context.route('**/engine-worker.js',route=>route.fulfill({contentType:'text/javascript',headers,
        body:mode==='staged'?staged:mode.startsWith('async')?asyncEngine:syncEngine}));
      if(mode==='batched')await context.route('**/storage-worker.js',route=>route.fulfill({contentType:'text/javascript',headers,body:batched}));
      if(mode.startsWith('async')){
        await context.route('**/storage-worker.js',route=>route.fulfill({contentType:'text/javascript',headers,body:mode==='async'?asyncStorage:asyncBatched}));
      }
      await page.goto(origin+'/benchmark.html');
      await page.waitForFunction(()=>typeof window.benchmark==='function');
      const result=await page.evaluate(config=>window.benchmark(config,true),config);
      const {analysis,diagnostics,hashes:outputs,elapsed_seconds}=result;
      const fingerprint=JSON.stringify(Object.entries(outputs).sort());
      if(hashes.has(job)&&hashes.get(job)!==fingerprint)throw new Error('Output hashes differ from matched run');
      hashes.set(job,fingerprint);
      const manifest=result.manifest.trim().split('\n').map(line=>JSON.parse(line));
      if(!manifest.filter(item=>item.type==='output').every(item=>Number(item.csv_bytes)<=cap))throw new Error('CSV byte cap exceeded');
      Object.assign(record,{elapsed_seconds,analysis_seconds:analysis.analysis_seconds,effective_memory_bytes:analysis.memory_budget_bytes,workers:analysis.workers,peak_working_reserved_bytes:analysis.diagnostics?.peak_workspace_reserved_bytes??null,output_files:analysis.output_files,output_csv_bytes:analysis.output_csv_bytes,diagnostics,output_sha256:sha(fingerprint),conservation_verified:result.conservation_verified});
      console.error(job,rep,mode,elapsed_seconds);
    }catch(error){record.error=String(error);console.error(job,rep,mode,record.error);}
    finally{await context.close();}
  }
}finally{
  try{await browser?.close();}finally{await lifetime.stop();}
  console.log(JSON.stringify(report,null,2));
}
if(report.runs.some(record=>record.error))process.exitCode=1;
