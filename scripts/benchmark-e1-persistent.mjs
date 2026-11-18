// Dedicated, bounded E1 round. No native matrix; historical callers are unchanged.
import assert from 'node:assert/strict';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {readFile,writeFile,mkdir,copyFile,cp,stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import http from 'node:http';
import {resolve,join} from 'node:path';
import {cpus,totalmem} from 'node:os';

assert(process.argv.length===3,'Usage: node scripts/benchmark-e1-persistent.mjs TASK_DIRECTORY');
const task=resolve(process.argv[2]),assets=join(task,'static');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const save=async(name,value)=>writeFile(join(task,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
const emit=async record=>writeFile(join(task,'attempts.jsonl'),JSON.stringify(record)+'\n',{flag:'a'});
// Refuse evidence reuse and require successful current-build gates.
await writeFile(join(task,'attempts.jsonl'),'',{flag:'wx'});
for(const name of ['candidate-build','baseline-build','candidate-standard','native-codec','candidate-resource','candidate-bridge','candidate-cleanup','candidate-termination-persistent','candidate-termination-kill-pinned']){
  const result=JSON.parse(await readFile(join(task,name+'.result.json'),'utf8'));
  assert.equal(result.exit_code,0,'missing/failed gate '+name);
}
await mkdir(assets);await cp('ui/dist',assets,{recursive:true});
await build({entryPoints:['ui/tests/e1-persistent.ts'],bundle:true,format:'esm',outfile:join(assets,'e1.js')});
await writeFile(join(assets,'e1.html'),'<!doctype html><title>E1 bounded experiment</title><script type="module" src="/e1.js"></script>');
// Sample the existing logical file-size ledger after completed storage operations.
// At most one sample per 25 ms of operation activity; idle gaps produce no sample.
// This avoids opening competing sync handles or scanning the profile during jobs.
await build({entryPoints:['ui/src/browser/storage-worker.ts'],bundle:true,format:'esm',outfile:join(assets,'storage-worker.js'),plugins:[{
  name:'e1-logical-space-sampling',setup(b){b.onLoad({filter:/storage-worker\.ts$/},async({path})=>{
    let contents=await readFile(path,'utf8');
    const needle='function observeSpace(){';assert(contents.includes(needle),'storage sampling seam changed');
    contents=contents.replace(needle,"let e1LastSample=-Infinity;\nfunction observeSpace(){const now=performance.now();if(now-e1LastSample>=25){e1LastSample=now;scope.postMessage({e1Space:{timestamp_epoch_ms:performance.timeOrigin+now,workspace_bytes:used,export_bytes:destinationBytes,total_bytes:used+destinationBytes,workspace_files:sizes.size}});}");
    return {contents,loader:'ts'};
  });}
}]});
await build({entryPoints:['ui/src/browser/engine-worker.ts'],bundle:true,format:'esm',outfile:join(assets,'engine-worker.js')});
const header=['id','payload',...Array.from({length:31},(_,k)=>'c'+k)].join(',');
const fixtures={};
for(const shape of ['columns','rare_wide']){
  let text=header+'\n';
  for(let id=0;id<100000;id++)text+=[String(id),shape==='rare_wide'&&id===0?'x'.repeat(1800000):'duplicate payload',...Array.from({length:31},(_,k)=>String((id+k)%10))].join(',')+'\n';
  const bytes=Buffer.from(text);await writeFile(join(assets,shape+'.csv'),bytes,{flag:'wx'});fixtures[shape]={rows:100000,bytes:bytes.length,sha256:sha(bytes)};
}
const wasm={};for(const variant of ['baseline','candidate'])wasm[variant]=await readFile(join(task,variant+'.wasm'));
assert.notEqual(sha(wasm.baseline),sha(wasm.candidate),'identical artifacts');
const artifacts={};for(const name of ['e1.js','engine-worker.js','storage-worker.js','columns.csv','rare_wide.csv'])artifacts[name]=sha(await readFile(join(assets,name)));
const server=http.createServer(async(req,res)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cache-Control','no-store');
  try{const name=new URL(req.url,'http://localhost').pathname.slice(1);assert(/^[a-zA-Z0-9_.-]+$/.test(name));const bytes=await readFile(join(assets,name));res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.wasm')?'application/wasm':'text/html');res.end(bytes);}catch{res.statusCode=404;res.end('Not found');}
});
let context;const measurements=[];const references={};let current;
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
function identity(r){
  const entries=r.manifest.trim().split('\n').map(JSON.parse);
  return JSON.stringify(canonical({rows:r.analysis.rows,seed:r.analysis.seed,logical_digest:r.analysis.logical_digest,stages:r.analysis.stages,output_csv_bytes:r.analysis.output_csv_bytes,
    outputs:entries.filter(e=>e.type==='output'),hashes:r.hashes}));
}
try{
  await new Promise(ok=>server.listen(0,'127.0.0.1',ok));const origin='http://127.0.0.1:'+server.address().port;
  context=await chromium.launchPersistentContext(join(task,'profile'));
  const page=await context.newPage();
  await copyFile(join(task,'baseline.wasm'),join(assets,'engine.wasm'));await page.goto(origin+'/e1.html');await page.waitForFunction(()=>typeof window.e1Run==='function');
  const storage=await page.evaluate(async()=>({estimate:await navigator.storage.estimate(),persisted:await navigator.storage.persisted()}));
  assert(storage.estimate.quota-storage.estimate.usage>1024**3,'insufficient origin quota for planned scratch');
  await save('environment.json',{type:'environment',platform:process.platform,arch:process.arch,node:process.version,cpu:cpus()[0]?.model,logical_cpus:cpus().length,memory_bytes:totalmem(),browser:context.browser().version(),browser_channel:'bundled-chromium',context:'one retained persistent profile',origin,storage,fixtures,artifacts,
    wasm_sha256:Object.fromEntries(Object.entries(wasm).map(([k,v])=>[k,sha(v)])),features:{baseline:[],candidate:['experimental-spill-blocks']},
    source_sha256:{harness:sha(await readFile(new URL(import.meta.url))),page:sha(await readFile('ui/tests/e1-persistent.ts')),storage_worker:sha(await readFile('ui/src/browser/storage-worker.ts')),engine_worker:sha(await readFile('ui/src/browser/engine-worker.ts'))},
    cache:'warm/uncontrolled',timing:'immediately before analyze through complete including marker close and required worker/workspace cleanup; fixture load/defaults/pickers, verification and successful disposal excluded',
    sampling:{cadence_ms:25,trigger:'successful operation activity; no timer samples while idle',scope:'existing storage-worker logical file-size ledger plus accounted destination writes for the one current job; fixture/profile/metadata/implementation buffers excluded',limits:'non-atomic sampled lower bound, not exact peak or physical I/O; throttling/postMessage/collection overhead applies equally; no profile directory scans during jobs'},cpu_seconds:null,rss_bytes:null,allocator_bytes:null,physical_io_bytes:null});
  async function run(shape,variant,phase,repeat){
    const attempt=`${shape}-${phase}-${repeat}-${variant}`;current={attempt,shape,variant,phase,repeat};
    console.log(attempt);await writeFile(join(assets,'engine.wasm'),wasm[variant]);
    await page.goto(origin+'/e1.html');await page.waitForFunction(()=>typeof window.e1Run==='function');
    const result=await page.evaluate(({shape,attempt})=>window.e1Run(shape,attempt),{shape,attempt});
    // Save complete raw result BEFORE assertions and any successful disposal.
    await save(attempt+'.json',result);
    if(!result.ok){await emit({type:'failure',...current,error:result.error,raw:attempt+'.json'});throw new Error(result.error);}
    const d=result.analysis.diagnostics;assert(d.sort_runs>0,'no external sort');
    if(variant==='candidate'){assert(d.compact_spill_files>0&&d.compact_spill_rows>=100000,'candidate block path absent');assert.equal(d.compact_spill_fallbacks,0,'unintended fallback');}
    else assert.equal(d.compact_spill_files,0,'baseline not feature-off');
    const actual=identity(result);references[shape]??=actual;assert.equal(actual,references[shape],'seeded order/metadata/membership mismatch');
    const record={type:phase==='timed'?'measurement':'parity-control',...current,seconds:phase==='timed'?result.elapsed_seconds:null,raw:attempt+'.json',fingerprint:sha(actual),verified:true,
      merge_depth:null,merge_depth_note:'aggregate counters retained; no exact depth trace collected',analysis:result.analysis,space_sampled_lower_bound_bytes:Math.max(0,...result.space_samples.map(s=>s.total_bytes)),export_bytes:result.after.reduce((n,f)=>n+f.bytes,0),cpu_seconds:null,rss_bytes:null,allocator_bytes:null,physical_io_bytes:null};
    await emit(record);if(phase==='timed')measurements.push(record);
    const after=await page.evaluate(attempt=>window.e1Dispose(attempt),attempt);await save(attempt+'-disposed.json',{inventory_after_disposal:after});
  }
  // Both exact selected shapes pass parity before any timed job is admitted.
  for(const shape of ['columns','rare_wide'])for(const variant of ['baseline','candidate'])await run(shape,variant,'parity',0);
  for(const variant of ['baseline','candidate']){
    const attempt='rare_wide-cap-rejection-'+variant;current={attempt,variant,phase:'cap-control'};
    await writeFile(join(assets,'engine.wasm'),wasm[variant]);await page.goto(origin+'/e1.html');await page.waitForFunction(()=>typeof window.e1Run==='function');
    const result=await page.evaluate(attempt=>window.e1Run('rare_wide',attempt,true),attempt);await save(attempt+'.json',result);
    assert(result.ok&&result.expected_rejection,'wide cap rejection/cleanup failed');await emit({type:'cap-control',...current,raw:attempt+'.json',verified:true});
    const after=await page.evaluate(attempt=>window.e1Dispose(attempt),attempt);await save(attempt+'-disposed.json',{inventory_after_disposal:after});
  }
  await save('parity-gate.json',{passed:true,cells:['columns/global/100000','rare_wide/balanced/100000'],timings_admitted:false});
  for(const shape of ['columns','rare_wide'])for(let repeat=1;repeat<=3;repeat++)for(const variant of repeat%2?['baseline','candidate']:['candidate','baseline'])await run(shape,variant,'timed',repeat);
  const cells=[];for(const shape of ['columns','rare_wide'])for(const variant of ['baseline','candidate']){
    const values=measurements.filter(r=>r.shape===shape&&r.variant===variant).map(r=>r.seconds).sort((a,b)=>a-b);assert.equal(values.length,3);cells.push({shape,variant,n:3,median_seconds:values[1],range_seconds:[values[0],values[2]]});
  }
  await save('summary.json',{type:'summary',cells,timed_jobs:measurements.length,disposition:'pending Astra review'});
}catch(e){await emit({type:'failure',...current,error:String(e),remaining_jobs_stopped:true});await save('stopped.json',{error:String(e),current,accepted_timed_jobs:measurements.length});throw e;}
finally{await context?.close();await new Promise(ok=>server.close(ok));}
