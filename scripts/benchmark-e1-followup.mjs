// Premeasurement E1 harness. Full-size execution is deliberately not admitted.
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir,copyFile,readdir} from 'node:fs/promises';
import {resolve,join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import http from 'node:http';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {schedule,header} from '../ui/tests/e1-followup-verifier.mjs';
import {roots,budget,census,priorAttempts} from './e1-followup-roots.mjs';
import {deadline,saveAcknowledged,shutdown} from './e1-followup-controller.mjs';
import {sourceIdentity,ownedFile} from './e1-followup-inputs.mjs';
import {captureRuntime,closeOwnedRuntime} from './e1-followup-runtime.mjs';
const decoder=new TextDecoder('utf-8',{fatal:true});
const text=async f=>decoder.decode(await readFile(f));
const sha=b=>createHash('sha256').update(b).digest('hex');
const argv=process.argv.slice(2);
if(argv.length===1&&argv[0]==='--plan'){console.log(JSON.stringify({admitted:false,full_size_attempts:44,jobs:schedule()},null,2));process.exit(0);}
assert(argv[0]==='--selftest'&&argv.length===2,'Usage: --plan OR --selftest <absolute-config.json>; full-size execution unavailable');
assert(resolve(argv[1])===argv[1],'absolute configuration path required');
const config=JSON.parse(await text(argv[1]));
const r=await roots(config),root=r.source,task=r.invocation,output=r.output;
const baseline=await ownedFile(task,config.baseline),candidate=await ownedFile(task,config.candidate);
const previous=await priorAttempts(config.priorAttemptLedgers);
assert.equal(previous.attempts,0,'partial tiny session cannot restart or replace');
const usage=async path=>(await census([path])).bytes;
const space=async()=>budget(r,{evidenceExpansion:128*1024**2,scratchExpansion:128*1024**2});
await space();
const temp=join(r.scratch[0],'tiny-temp');await mkdir(temp);
for(const key of ['TEMP','TMP','TMPDIR'])process.env[key]=temp;
await mkdir(output);const assets=join(output,'assets');await mkdir(assets);
const save=async(name,value)=>writeFile(join(output,name),JSON.stringify(value,null,2)+'\n',{encoding:'utf8',flag:'wx'});
const ledger=async value=>writeFile(join(output,'attempts.jsonl'),JSON.stringify(value)+'\n',{encoding:'utf8',flag:'a'});
await space();
const wasm={baseline:await readFile(baseline),candidate:await readFile(candidate)};assert.notEqual(sha(wasm.baseline),sha(wasm.candidate),'identical variants');
const pin=()=>sourceIdentity(root);
const source=await pin();await save('source-before.json',source);
// Both tiny fixtures are distinctly named and deliberately fat to exercise external runs.
const fixtures={};for(const shape of ['columns','rare_wide']){
  const name='tiny-followup-'+shape+'.csv';let csv=header.join(',')+'\n';
  for(let id=0;id<128;id++)csv+=[id,'x'.repeat(262144),...Array.from({length:31},(_,k)=>(id+k)%10)].join(',')+'\n';
  const bytes=Buffer.from(csv,'utf8');await writeFile(join(assets,name),bytes,{flag:'wx'});fixtures[shape]={name,rows:128,tiny_payload_bytes:262144,bytes:bytes.length,sha256:sha(bytes)};
}
await build({entryPoints:[join(root,'ui/tests/e1-followup.ts')],bundle:true,format:'esm',outfile:join(assets,'e1-followup.js')});
await writeFile(join(assets,'e1-followup.html'),'<!doctype html><title>E1 r02 tiny harness self-test</title><script type="module" src="/e1-followup.js"></script>',{encoding:'utf8',flag:'wx'});
await build({entryPoints:[join(root,'ui/src/browser/engine-worker.ts')],bundle:true,format:'esm',outfile:join(assets,'engine-worker.js')});
for(const mode of ['MINIMAL','FULL'])await build({entryPoints:[join(root,'ui/src/browser/storage-worker.ts')],bundle:true,format:'esm',outfile:join(assets,'storage-worker-'+mode+'.js'),plugins:mode==='MINIMAL'?[]:[{
  name:'e1-logical-space-sampling',setup(b){b.onLoad({filter:/storage-worker\.ts$/},async({path})=>{
    let contents=await text(path);const seam='function observeSpace(){';assert.equal(contents.split(seam).length,2,'sampler seam changed');
    contents=contents.replace(seam,"let e1LastSample=-Infinity;\nfunction observeSpace(){const now=performance.now();if(now-e1LastSample>=25){e1LastSample=now;scope.postMessage({e1Space:{timestamp_epoch_ms:performance.timeOrigin+now,workspace_bytes:used,export_bytes:destinationBytes,total_bytes:used+destinationBytes,workspace_files:sizes.size}});}");return {contents,loader:'ts'};
  });}
}]});
let selected={variant:'baseline',mode:'MINIMAL'};
const server=http.createServer(async(req,res)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cache-Control','no-store');
  try{let name=new URL(req.url,'http://localhost').pathname.slice(1);assert(/^[a-zA-Z0-9_.-]+$/.test(name));if(name==='storage-worker.js')name='storage-worker-'+selected.mode+'.js';const bytes=name==='engine.wasm'?wasm[selected.variant]:await readFile(join(assets,name));res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.wasm')?'application/wasm':'text/html');res.end(bytes);}catch{res.statusCode=404;res.end('Not found');}
});
let context,current,runtimeOwner,attempts=0;const references={};const started=new Date().toISOString(),startedAt=performance.now();
try{
  await new Promise(ok=>server.listen(0,'127.0.0.1',ok));const origin='http://127.0.0.1:'+server.address().port;
  context=await chromium.launchPersistentContext(join(r.scratch[0],'tiny-profile'),{headless:true,env:{...process.env}});
  runtimeOwner=await captureRuntime(context,context.browser(),join(r.scratch[0],'tiny-profile'));const page=await context.newPage();
  await page.goto(origin+'/e1-followup.html?mode=MINIMAL');await page.waitForFunction(()=>typeof window.e1FollowupRun==='function');
  const storage=await page.evaluate(async()=>({estimate:await navigator.storage.estimate(),persisted:await navigator.storage.persisted()}));assert(storage.estimate.quota-storage.estimate.usage>1024**3,'insufficient origin quota');
  const artifacts={};for(const name of await readdir(assets)){const b=await readFile(join(assets,name));artifacts[name]={bytes:b.length,sha256:sha(b)};}
  await save('environment.json',{type:'tiny-selftest-environment',started,origin,browser:context.browser().version(),browser_executable:{path:chromium.executablePath(),sha256:sha(await readFile(chromium.executablePath()))},profile:join(r.scratch[0],'tiny-profile'),storage,fixtures,artifacts,wasm_sha256:Object.fromEntries(Object.entries(wasm).map(([k,v])=>[k,sha(v)])),features:{baseline:[],candidate:['experimental-spill-blocks']},mode_scope:'overall profiling plus operation-triggered 25ms sampler sensitivity; common polling/verifier cost remains; no subtraction',limits:{attempts:8,rows:128,task_bytes:25*1024**3,browser_scratch_bytes:1024**3},full_size_jobs_admitted:false});
  for(const shape of ['columns','rare_wide'])for(const mode of ['MINIMAL','FULL'])for(const variant of ['baseline','candidate']){
    await space();const quota=await page.evaluate(()=>navigator.storage.estimate());assert(quota.quota-quota.usage>128*1024**2,'origin quota headroom exhausted');assert(previous.attempts+attempts<8,'cumulative tiny ceiling exhausted');selected={variant,mode};const fixture=fixtures[shape];
    const attempt='tiny-'+String(++attempts).padStart(2,'0')+'-'+shape+'-'+mode+'-'+variant;current={attempt,shape,mode,variant};
    await ledger({type:'attempt-start',...current,utc:new Date().toISOString()});const jobStarted=performance.now();
    await page.goto(origin+'/e1-followup.html?mode='+mode);await page.waitForFunction(()=>typeof window.e1FollowupRun==='function');
    const bound=deadline(300000);
    const result=await saveAcknowledged({invoke:()=>bound.run(()=>page.evaluate(spec=>window.e1FollowupRun(spec),{...current,fixture:fixture.name,rows:128,tiny_payload_bytes:fixture.tiny_payload_bytes,expected_parity:references[shape]})),retrieve:()=>deadline(5000).run(()=>page.evaluate(id=>window.e1FollowupRetrieve(id),attempt)),save:record=>save(attempt+'.json',record),ack:()=>deadline(5000).run(()=>page.evaluate(id=>window.e1FollowupAcknowledge(id),attempt)),fail:failure=>save(attempt+'-failed-transport.json',{...failure,attempt:current,utc:new Date().toISOString(),evidence_loss_limitation:'Process/transport loss after disposal may make page record unretrievable; failed attempt, stop without replacement.'})});
    await ledger({type:'attempt-return',...current,utc:new Date().toISOString(),wrapper_seconds:(performance.now()-jobStarted)/1000,ok:result.ok,raw:attempt+'.json'});
    assert(result.ok,result.error);const identity=JSON.stringify(result.parity);references[shape]??=identity;assert.equal(identity,references[shape],'exact seeded CSV/order/metadata parity mismatch');
    await space();
  }
  const after=await pin();await save('source-after.json',after);assert.deepEqual(after,source,'source identity changed');
  await save('selftest-result.json',{passed:true,attempts,full_size_jobs:0,measurements:0,started,finished:new Date().toISOString(),wrapper_session_seconds:(performance.now()-startedAt)/1000,task_bytes:await usage(task)});
}catch(error){try{await save('stopped.json',{error:String(error),secondary:error.secondary,current,attempts,utc:new Date().toISOString(),restart_authorized:false});}catch(secondary){console.error(JSON.stringify({primary:String(error),secondary:String(secondary)}));}throw error;}
finally{const errors=[];let runtimeShutdown;
await shutdown([['context',async()=>{if(runtimeOwner)runtimeShutdown=await closeOwnedRuntime(runtimeOwner);else await deadline(10000).run(()=>context?.close());}],['server',()=>deadline(10000).run(()=>new Promise((ok,fail)=>server.close(e=>e?fail(e):ok())))]],errors);
const record={runtime:runtimeShutdown??null,identity:runtimeOwner?.identity??null,exit_observed:runtimeOwner?.exit_observed??null,server_closed:!server.listening,errors,utc:new Date().toISOString()};
try{await save('shutdown.json',record);}catch(error){errors.push({stage:'shutdown-save',error:String(error)});}console.error(JSON.stringify(record));if(errors.length)process.exitCode=1;}
