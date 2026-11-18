// Complete prepared jobs; CSV collection and independent verification are outside the clock.
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {readFile,writeFile,mkdir,copyFile,rm} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {createWriteStream} from 'node:fs';
import {pipeline} from 'node:stream/promises';
import http from 'node:http';
import assert from 'node:assert/strict';
const [baseline,candidate,output,mode]=process.argv.slice(2);
assert(baseline&&candidate&&output,'BASELINE.wasm CANDIDATE.wasm OUTPUT [pilot|paired|control|resident]');
assert(['pilot','paired','control','resident'].includes(mode));
const work=resolve(output);await mkdir(work);const assets=join(work,'assets');await mkdir(assets);
const save=(path,value)=>writeFile(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const source=await readFile('ui/src/browser/engine-worker.ts','utf8');
// Identical diagnostic instrumentation in both workers; linear memory only grows.
await build({stdin:{contents:source.replace('scope.postMessage({id,result,', 'scope.postMessage({benchmark_memory_bytes:instance.exports.memory instanceof WebAssembly.Memory?instance.exports.memory.buffer.byteLength:0});scope.postMessage({id,result,'),resolveDir:resolve('ui/src/browser'),loader:'ts'},bundle:true,format:'esm',outfile:join(assets,'engine-worker.js')});
await build({entryPoints:['ui/src/browser/storage-worker.ts'],bundle:true,format:'esm',outfile:join(assets,'storage-worker.js')});
await build({entryPoints:['ui/tests/benchmark-swarm.ts'],bundle:true,format:'iife',define:{__HOSTED__:'true'},outfile:join(assets,'driver.js')});
await copyFile(resolve(baseline),join(assets,'baseline.wasm'));await copyFile(resolve(candidate),join(assets,'candidate.wasm'));
const recipe={name:mode==='control'?'memory-control':'memory-shuffle',rows:mode==='control'?120003:1200003,payload_bytes:mode==='control'?64:192,wide:false,operations:[{type:'shuffle',strategy:mode==='resident'?'fisher_yates':'uniform'}]};
await save(join(work,'recipe.json'),recipe);
execFileSync('python3',['-c',"import importlib.util,json,pathlib,sys;s=importlib.util.spec_from_file_location('v','scripts/verify-shuffle-swarm.py');v=importlib.util.module_from_spec(s);s.loader.exec_module(v);p=pathlib.Path(sys.argv[1]);v.fixture(p/'input.csv',json.load(open(p/'recipe.json')))",work],{stdio:'pipe'});
let active='baseline',collectDirectory;const reports=[];let browser;
const server=http.createServer(async(req,res)=>{
 res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cache-Control','no-store');
 try{const name=new URL(req.url,'http://localhost').pathname.slice(1);
  if(req.method==='POST'){
   assert(collectDirectory&&name.startsWith('collect/')&&/^[a-zA-Z0-9_.-]+$/.test(name.slice(8)));
   await pipeline(req,createWriteStream(join(collectDirectory,name.slice(8)),{flags:'wx'}));res.end('saved');return;
  }
  if(!name){res.setHeader('Content-Type','text/html');res.end('<!doctype html><script>window.memorySamples=[];const W=Worker;window.Worker=class extends W{constructor(...args){super(...args);this.addEventListener("message",e=>{if(e.data.benchmark_memory_bytes)window.memorySamples.push(e.data.benchmark_memory_bytes);});}};</script><script src="/driver.js"></script>');return;}
  assert(['engine.wasm','engine-worker.js','storage-worker.js','driver.js','input.csv'].includes(name));
  res.setHeader('Content-Type',name.endsWith('.wasm')?'application/wasm':name.endsWith('.js')?'application/javascript':'text/csv');
  res.end(await readFile(name==='input.csv'?join(work,name):join(assets,name==='engine.wasm'?active+'.wasm':name)));
 }catch(e){res.statusCode=404;res.end(String(e));}
});
try{
 await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
 browser=await chromium.launchPersistentContext(join(work,'profile'),{headless:true});
 const page=await browser.newPage();page.on('pageerror',e=>console.error(e));
 await save(join(work,'environment.json'),{browser:browser.browser().version(),platform:process.platform,arch:process.arch,context:'persistent disposable Chromium; WSL2/ext4; warm uncontrolled cache/OPFS',clock:'prepare through confirmation, export, completion marker and session retirement; fixture fetch, collection and verification excluded',memory_metric:'WASM linear memory byteLength at worker replies; high-water because linear memory does not shrink; not browser RSS',harness_sha256:sha(await readFile(new URL(import.meta.url))),fixture_sha256:sha(await readFile(join(work,'input.csv'))),assets:Object.fromEntries(await Promise.all(['driver.js','engine-worker.js','storage-worker.js','baseline.wasm','candidate.wasm'].map(async n=>[n,sha(await readFile(join(assets,n)))])))});
 const variants=mode==='pilot'?[['baseline',256],['candidate',512],['candidate',1024],['candidate',2048]]:mode==='control'?[['baseline',256],['candidate',256]]:mode==='resident'?[['baseline',512],['candidate',2048]]:[['baseline',256],['candidate',2048]];
 const repeats=['pilot','resident'].includes(mode)?[0]:[-1,0,1,2];
 for(const repeat of repeats)for(const [variant,memory_mb] of repeat%2===0?variants:[...variants].reverse()){
  active=variant;const attempt=join(work,`${repeat+1}-${variant}-${memory_mb}`);await mkdir(attempt);
  await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>typeof window.swarmRun==='function');
  const config={operations:recipe.operations,resources:{memory_mb,workers:1,max_record_bytes:1048576},limits:{rows:100000,bytes:4194304,compressed_bytes:null}};
  try{
   const result=await page.evaluate(config=>window.swarmRun(config,300),config);result.wasm_memory_samples=await page.evaluate(()=>window.memorySamples);await save(join(attempt,'result.json'),result);
   const destination=join(attempt,'results');await mkdir(destination);collectDirectory=destination;
   for(const file of result.files){assert(/^[a-zA-Z0-9_.-]+$/.test(file.name));if(file.name==='CHOPPER-COMPLETE.json')continue;
    await page.evaluate(async({owned,output,name})=>{const root=await navigator.storage.getDirectory();const parent=await root.getDirectoryHandle(owned);const folder=await parent.getDirectoryHandle(output.split('/').at(-1));const file=await (await folder.getFileHandle(name)).getFile();const response=await fetch('/collect/'+name,{method:'POST',body:file});if(!response.ok)throw Error('CSV collection failed');},{owned:result.owned_destination,output:result.output,name:file.name});
   }
   execFileSync('python3',['-c',"import importlib.util,json,pathlib,sys;s=importlib.util.spec_from_file_location('v','scripts/verify-shuffle-swarm.py');v=importlib.util.module_from_spec(s);s.loader.exec_module(v);p=pathlib.Path(sys.argv[1]);r=json.load(open(p/'result.json'));m=json.loads((p/'results/manifest.jsonl').read_text().splitlines()[0]);a=dict(r['analysis']);assert a['warnings']==m['analysis']['warnings']+['Browser export is not atomic. A valid CHOPPER-COMPLETE.json record marks successful completion. Keep this tab open until saving finishes.'];a['warnings']=m['analysis']['warnings'];j=r['submitted'];assert j['input']=='input.csv' and j['output']=='results' and j['resources']['temp_dir'] is None;j={**j,'input':'/input.csv','output':'/results','resources':{**j['resources'],'temp_dir':'/tmp'}};x=v.verify(p/'results',json.load(open(p.parent/'recipe.json')),j,a);json.dump(x,open(p/'verification.json','x'))",attempt],{cwd:process.cwd(),stdio:'pipe'});
   await save(join(attempt,'cleanup.json'),await page.evaluate(()=>window.swarmCleanup()));await rm(destination,{recursive:true});
   const row={repeat,variant,memory_mb,seconds:result.elapsed_seconds,wasm_memory_bytes:Math.max(...result.wasm_memory_samples),diagnostics:result.analysis.diagnostics,storage:result.diagnostics.storage,attempt};reports.push(row);await save(join(attempt,'measurement.json'),row);console.log(JSON.stringify({repeat,variant,memory_mb,seconds:row.seconds,wasm_MiB:row.wasm_memory_bytes/1048576}));
  }catch(error){const details=await page.evaluate(()=>window.swarmFailure()).catch(()=>null);await save(join(attempt,'failure.json'),{error:String(error),stack:error.stack,details});
   if(mode!=='resident'||variant!=='baseline')throw error;
   assert.match(String(error),/memory|resident|admission/i);assert.equal(details.state.status,'failed');assert.equal(details.diagnostics.storage.workspace_bytes_after_cleanup,0);
   const empty=await page.evaluate(async owned=>{const root=await navigator.storage.getDirectory();const folder=await root.getDirectoryHandle(owned);const names=[];for await(const name of folder.keys())names.push(name);return names;},details.owned_destination);assert.deepEqual(empty,[]);
   await save(join(attempt,'cleanup.json'),await page.evaluate(()=>window.swarmCleanup()));reports.push({variant,memory_mb,expected_capacity_denial:true,attempt});console.log(JSON.stringify({variant,memory_mb,expected_capacity_denial:true}));
  }
 }
 await save(join(work,'summary.json'),reports);
}finally{if(browser)await browser.close();server.closeAllConnections();await new Promise(ok=>server.close(ok));}
