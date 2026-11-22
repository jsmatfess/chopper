import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile,writeFile,readdir,mkdir,mkdtemp,rm} from 'node:fs/promises';
import {basename,join,resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {release} from 'node:os';
import {serverLifetime} from './browser-acceptance.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {destinationFixture} from './browser-destination-fixtures.mjs';
import {compileDestinationWorker,compileAsyncDestinationEngine,compileSynchronousDestinationEngine,asyncDestinationStorage,batchDestinationStorage} from './browser-async-destination.mjs';

const source=await readFile('ui/tests/benchmark.ts','utf8');
const patched=source.replace('  const root=await navigator.storage.getDirectory();','  const root=(window as unknown as {selectedBenchmarkFolder:FileSystemDirectoryHandle}).selectedBenchmarkFolder;');
assert.notEqual(source,patched);
const dist='ui/dist/';
await build({stdin:{contents:patched,resolveDir:'ui/tests',loader:'ts'},bundle:true,format:'esm',outfile:dist+'picker-benchmark.js'});
const rows=196608;
const csv=destinationFixture(rows);
const scratch=resolve('scratch');
await mkdir(scratch,{recursive:true});
const folder=await mkdtemp(join(scratch,'desktop-write-output-'));
const folderName=basename(folder);
await writeFile(dist+'benchmark.csv',csv);
await writeFile(dist+'picker-benchmark.html',`<!doctype html><meta charset="utf-8"><title>Chopper desktop write benchmark</title>
  <h1>Chopper desktop write benchmark</h1><p>Select the empty ${folderName} folder. The trials start after you grant write access.</p>
  <button id="pick">Select benchmark folder</button> <output id="status"></output>
  <script src="/picker-probe.js" defer></script><script type="module" src="/picker-benchmark.js"></script>`);
await writeFile(dist+'picker-probe.js',`const result=document.querySelector('#status');
result.textContent=typeof showDirectoryPicker==='function'?'Ready to pick an empty test folder.':'Folder picker unavailable in this browser.';
document.querySelector('#pick').onclick=async()=>{
  try{window.selectedBenchmarkFolder=await showDirectoryPicker({mode:'readwrite'});result.textContent='Folder selected.';}
  catch(error){result.textContent=error.name+': '+error.message;}
};`);
const syncEngine=await compileSynchronousDestinationEngine();
const asyncEngine=await compileAsyncDestinationEngine();
const workers={
  batched:await compileDestinationWorker('storage-worker',batchDestinationStorage),
  async:await compileDestinationWorker('storage-worker',asyncDestinationStorage),
  'async-batched':await compileDestinationWorker('storage-worker',s=>asyncDestinationStorage(batchDestinationStorage(s)))
};
const headers={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'};
const sha=data=>createHash('sha256').update(data).digest('hex');
assert.deepEqual(await readdir(folder),[]);
const origin='http://127.0.0.1:8447';
const server=serverLifetime(spawn(process.execPath,['scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8447'},
  stdio:['ignore','pipe','inherit']}),origin,15000,5000);
let browser;
try{
  await server.ready;
  browser=await chromium.launch({headless:false,args:process.platform==='linux'?['--ozone-platform=x11']:[]});
  const context=await browser.newContext(),page=await context.newPage();
  const hashes=Object.fromEntries(Object.entries(workers).map(([mode,content])=>[mode,sha(content)]));
  console.log(JSON.stringify({type:'environment',browser:browser.version(),kernel:release(),harness_sha256:sha(await readFile(new URL(import.meta.url))),fixture_bytes:Buffer.byteLength(csv),
    fixture_sha256:sha(csv),engine_sha256:sha(await readFile(dist+'engine.wasm')),async_engine_sha256:sha(asyncEngine),sync_engine_sha256:sha(syncEngine),
    workers:hashes,rows,destination:'Native desktop picker, local filesystem folder',clock:'complete Run including marker verification and workspace cleanup'}));
  await page.goto(origin+'/picker-benchmark.html');
  await page.waitForFunction(()=>typeof window.benchmark==='function');
  console.error('Select the benchmark folder in the opened browser: '+folder);
  await page.waitForFunction(expected=>window.selectedBenchmarkFolder?.name===expected,folderName,{timeout:150000});
  console.error('Desktop folder selected');
  const modes=['direct','batched','async','async-batched'];
  let fingerprint;
  for(let round=0;round<3;round++)for(const mode of (round%2?modes.slice().reverse():modes)){
    await context.unrouteAll({behavior:'wait'});
    await context.route('**/engine-worker.js',route=>route.fulfill({headers,body:mode.startsWith('async')?asyncEngine:syncEngine,contentType:'text/javascript'}));
    if(mode!=='direct')await context.route('**/storage-worker.js',route=>route.fulfill({headers,body:workers[mode],contentType:'text/javascript'}));
    const result=await page.evaluate(()=>window.benchmark({operations:[],limits:{rows:null,bytes:8*1024*1024,compressed_bytes:null}},true));
    assert(result.conservation_verified);
    assert(result.manifest.split('\n').filter(line=>line).map(JSON.parse).every(rec=>rec.type!=='output'||rec.csv_bytes<=8*1024*1024));
    const output=sha(JSON.stringify(Object.entries(result.hashes).sort()));
    assert.equal(output,fingerprint??output);
    fingerprint=output;
    assert.deepEqual(await readdir(folder),[]);
    console.log(JSON.stringify({type:'run',mode,round,elapsed_seconds:result.elapsed_seconds,verified:true,
      output_sha256:output,diagnostics:result.diagnostics}));
  }
}finally{
  try{await browser?.close();}finally{
    await server.stop();
    await rm(folder,{recursive:true,force:true});
  }
}
