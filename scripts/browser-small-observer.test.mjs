import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {mkdtemp,writeFile,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {symlink} from 'node:fs/promises';
import {codecFixture} from './browser-graph-codec.mjs';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {smallLimits,validatePacket,validateQuota,validateGuard,validateBinding,launchedIdentity,observeSmall,finishBrowserObservation} from './browser-small-observer.mjs';
const GiB=1024**3;
const origin='http://127.0.0.1:8422';
function packet(){return {schema:'chopper-small-contract-observation-v1',approved:true,channel:'chrome',limits:{...smallLimits},argv:['test-browser.mjs'],features:'default-product; separately declared test reactor',executable:'/browser.exe',executable_sha256:'a'.repeat(64),browser_version:'156',guard:'/guard.json',runner_lock:'/runner.lock',receipt:'/receipt.jsonl',origin,inputs:[{path:'/asset',sha256:'b'.repeat(64)}],reservation:'owned-test',volumes:['/volume'],batch_started_ms:Date.now()-1000,source_commit:'c'.repeat(40),source_tree:'d'.repeat(40),package_receipt_sha256:'e'.repeat(64)};}
function guard(p){return {schema:'chopper-small-contract-guard-v1',allowed:true,sampled_ms:Date.now(),last_progress_ms:Date.now(),runner_pid:process.ppid,child_pid:process.pid,owned_pids:[process.pid,12345],reservation:p.reservation,reservation_held:true,windows_job_kill_on_close:true,batch_started_ms:p.batch_started_ms,cumulative_owned_bytes:0,volumes:[{path:'/volume',free_bytes:200*GiB,sampled_ms:Date.now()}]};}
function quota(){return {origin,sampled_ms:Date.now(),secure:true,isolated:true,quota:10*GiB,usage:0,persisted:false,persistence_permission:'prompt'};}
function actual(p,profile){return {pid:12345,parentPid:process.pid,executable:p.executable,sha256:p.executable_sha256,version:p.browser_version,argv:[p.executable,'--user-data-dir='+profile],commandLine:p.executable+' --user-data-dir='+profile,started:'2026-11-05T00:00:00Z'};}
const reasons=error=>error instanceof AggregateError?error.errors.flatMap(reasons):[error];
function fake(options={}){
 const p=packet(),events=[],receipts=[],browser=new EventEmitter();let connected=true,calls=0;
 const profile='/owned-profile';browser.isConnected=()=>connected;
 const page={goto:async url=>{events.push(['goto',url]);if(options.gotoError)throw options.gotoError;},close:async()=>{events.push('page.close');if(options.closeError)throw options.closeError;}};
 const route={};const context={newPage:async()=>page,route:async(url,fn)=>{route.url=url;route.fn=fn;events.push('route');},unroute:async(url,fn)=>{assert.equal(url,route.url);assert.equal(fn,route.fn);events.push('unroute');},close:async()=>{events.push('context.close');if(options.contextError)throw options.contextError;}};
 return {p,events,receipts,browser,context,page,disconnect(){connected=false;browser.emit('disconnected');},start:()=>observeSmall({packet:p,browser,context,profile,origin,interval:options.interval??5,
  guard:async()=>({...guard(p),...options.guard}),identity:async()=>{if(options.identityError)throw options.identityError;return {...actual(p,profile),...options.identity};},
  sample:async()=>{calls++;if(options.sample)await options.sample(calls);if(options.sampleError&&(calls>1||options.initialError))throw options.sampleError;return {...quota(),...(calls>1?options.laterQuota:options.quota)};},
  write:async value=>{if(options.writeError)throw options.writeError;receipts.push(value);},
 })};
}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
test('explicit packet and limits; missing approval/configuration/variant denied',()=>{
 const p=packet();validatePacket(p,'chrome',['test-browser.mjs']);
 for(const edit of [{approved:false},{limits:{...smallLimits,start_quota_bytes:128*1024**2}},{argv:['wrong']},{features:'experimental'},{executable:'relative'},{argv:['test-browser-editor-submission.mjs']}])assert.throws(()=>validatePacket({...p,...edit},'chrome',['test-browser.mjs']));
 assert.throws(()=>validatePacket(p,'msedge',['test-browser.mjs']));
});
test('quota stale/error/low/invalid/exact-origin failures are closed',()=>{
 validateQuota(quota(),origin,{initial:true});
 for(const edit of [{sampled_ms:Date.now()-90001},{error:'failed'},{quota:GiB},{usage:-1},{quota:NaN},{origin:'http://localhost:8422'},{isolated:false},{persistence_permission:'unavailable'}])assert.throws(()=>validateQuota({...quota(),...edit},origin));
 assert.throws(()=>validateQuota({...quota(),quota:3*GiB},origin,{initial:true}));
 validateQuota({...quota(),quota:3*GiB},origin);
});
test('parent guard denies stale/capacity/ceiling/deadline/reservation/Job/PID and wrong volume',()=>{
 const p=packet();validateGuard(guard(p),p,{initial:true});
 for(const edit of [{allowed:false},{last_progress_ms:0},{sampled_ms:Date.now()-6000},{cumulative_owned_bytes:56*GiB},{reservation:'another'},{reservation_held:false},{windows_job_kill_on_close:false},{runner_pid:1},{child_pid:1},{owned_pids:[]},{batch_started_ms:0},{volumes:[{path:'/volume',free_bytes:7*GiB}]},{volumes:[{path:'/other',free_bytes:200*GiB,sampled_ms:Date.now()}]}])assert.throws(()=>validateGuard({...guard(p),...edit},p));
});
test('actual OS/CDP/profile/hash/version binding accepts evidence and rejects configured labels alone',()=>{
 const p=packet(),profile='/owned';validateBinding(actual(p,profile),p,profile);
 for(const edit of [{parentPid:1},{executable:'/other'},{sha256:'f'.repeat(64)},{version:'other'},{argv:['/other','--user-data-dir='+profile]},{argv:[p.executable]},{commandLine:'unrelated'},{pid:process.pid}])assert.throws(()=>validateBinding({...actual(p,profile),...edit},p,profile));
});
test('CDP PID to OS executable hash is observed, detach on success and mismatch',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'chopper-small-control-'));
 try{
  const executable=join(directory,'browser.exe');await writeFile(executable,'fake binary');
  const p={...packet(),executable,executable_sha256:createHash('sha256').update('fake binary').digest('hex')};let detached=0,inspected;
  const browser={version:()=>p.browser_version,newBrowserCDPSession:async()=>({send:async command=>command==='SystemInfo.getProcessInfo'?{processInfo:[{type:'renderer',id:99},{type:'browser',id:12345}]}:{arguments:[executable,'--user-data-dir=/owned']},detach:async()=>{detached++;}})};
  const inspect=async pid=>{inspected=pid;return {parentPid:process.pid,executable,commandLine:executable+' --user-data-dir=/owned',started:'now'};};
  assert.equal((await launchedIdentity(browser,'/owned',p,inspect)).sha256,p.executable_sha256);assert.equal(inspected,12345);
  await assert.rejects(launchedIdentity(browser,'/owned',{...p,executable_sha256:'0'.repeat(64)},inspect),/hash mismatch/);assert.equal(detached,2);
 }finally{await rm(directory,{recursive:true});}
});
test('monitor owns one exact route/page and removes only its own listener',async()=>{
 const h=fake();let unrelated=0;const listener=()=>unrelated++;h.browser.on('disconnected',listener);
 const observer=await h.start();await observer.stop();
 assert(h.receipts.some(x=>x.type==='binding'));assert(h.receipts.some(x=>x.type==='sample'));assert(h.events.includes('unroute'));
 assert.equal(h.events.filter(x=>x==='context.close').length,0);assert.equal(h.browser.listenerCount('disconnected'),1);
 h.disconnect();assert.equal(unrelated,1);h.browser.off('disconnected',listener);
});
test('initial guard/quota/navigation/write failures retain receipts and remove listeners',async()=>{
 for(const options of [{identityError:new Error('CDP failed')},{guard:{allowed:false}},{quota:{quota:GiB}},{gotoError:new Error('goto failed')},{writeError:new Error('receipt failed')},{sampleError:new Error('sample init failed'),initialError:true}]){
  const h=fake(options);await assert.rejects(h.start());assert.equal(h.browser.listenerCount('disconnected'),0);
  if(!options.writeError)assert(h.receipts.some(x=>x.type==='initialization-error'));
 }
});
test('periodic quota failures stop owned context, remain errors at cleanup',async()=>{
 for(const options of [{sampleError:new Error('sample failed')},{laterQuota:{sampled_ms:0}},{laterQuota:{quota:GiB}},{laterQuota:{error:'quota transport failed'}}]){
  const h=fake(options),observer=await h.start();await wait(25);await assert.rejects(observer.stop());assert(h.events.includes('context.close'));assert(h.receipts.some(x=>x.type==='monitor-error'));
 }
});
test('46-second quota start gap denies even while completed capacity is under 90 seconds old',async()=>{
 const clock=Date.now,started=clock();const h=fake(),observer=await h.start();
 try{
  Date.now=()=>started+46000;
  await wait(25);
  assert(h.events.includes('context.close'));
  assert(h.receipts.some(value=>value.type==='monitor-error'&&/start cadence/.test(value.error)));
  await assert.rejects(observer.stop());
 }finally{Date.now=clock;}
});
test('hot Job denial interrupts owned context while quota observation is pending',async()=>{
 let release,entered;const waiting=new Promise(resolve=>{release=resolve;});
 const started=new Promise(resolve=>{entered=resolve;});
 const options={sample:async calls=>{if(calls>1){entered();await waiting;}}};
 const h=fake(options),observer=await h.start();
 try{
  await started;options.guard={allowed:false};await wait(25);
  assert(h.events.includes('context.close'),'Hot denial must run before disk completion');
 }finally{release();}
 await assert.rejects(observer.stop());
});
test('deliberate process kill records armed/observed; unrelated monitor failure is retained',async()=>{
 const h=fake(),observer=await h.start();await assert.rejects(observer.beforeKill(999),/PID differs/);
 await observer.beforeKill(12345);h.disconnect();await observer.afterKill();await observer.stop();
 assert(h.receipts.some(x=>x.type==='deliberate-process-kill-observed'));assert.equal(h.browser.listenerCount('disconnected'),0);
 const bad=fake({sampleError:new Error('unrelated failure')}),monitor=await bad.start();await wait(25);
 await assert.rejects(monitor.beforeKill(12345));await assert.rejects(monitor.stop());
});
test('unexpected disconnect and uncompleted deliberate kill fail',async()=>{
 const h=fake(),observer=await h.start();h.disconnect();await assert.rejects(observer.stop(),error=>reasons(error).some(x=>/Unexpected/.test(String(x))));
 const k=fake(),armed=await k.start();await armed.beforeKill(12345);await assert.rejects(armed.stop(),error=>reasons(error).some(x=>/did not disconnect/.test(String(x))));
});
test('assertion, sampling, cleanup and later resource errors all survive',async()=>{
 const primary=new Error('actual assertion'),pageError=new Error('page close'),later=new Error('server cleanup');
 const h=fake({closeError:pageError}),observer=await h.start();let reached=false;
 await assert.rejects(finishBrowserObservation(observer,[async()=>{reached=true;throw later;}],primary),error=>{const all=reasons(error);assert(all.includes(primary));assert(all.includes(pageError));assert(all.includes(later));return true;});assert(reached);assert(h.events.includes('unroute'));
});
test('ordinary launch options remain bundled/channel defaults; protected missing configuration denies',()=>{
 const script="const m=await import('./scripts/browser-launch.mjs'); console.log(JSON.stringify(m.browserLaunchOptions))";
 const env={...process.env};delete env.CHOPPER_SMALL_CONTRACT_PACKET;delete env.CHOPPER_SMALL_CONTRACT_REQUIRED;delete env.CHOPPER_BROWSER_CHANNEL;
 for(const [channel,expected] of [[undefined,{}],['chrome',{channel:'chrome'}],['msedge',{channel:'msedge'}]]){
  const e={...env};if(channel)e.CHOPPER_BROWSER_CHANNEL=channel;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script],{env:e,encoding:'utf8'});assert.equal(result.status,0,result.stderr);assert.deepEqual(JSON.parse(result.stdout),expected);
 }
 const denied=spawnSync(process.execPath,['--input-type=module','-e',script],{env:{...env,CHOPPER_SMALL_CONTRACT_REQUIRED:'1'},encoding:'utf8'});assert.notEqual(denied.status,0);assert.match(denied.stderr,/requires monitor configuration/);
});
test('every selected owning path explicitly uses observer seam and kill arming stays local',async()=>{
 const standard=await readFile(new URL('./test-browser.mjs',import.meta.url),'utf8');assert.match(standard,/observeContractBrowser/);
 for(const name of ['graph','graph-lifecycle','graph-inspection','graph-bounds'])assert.match(await readFile(new URL(`./test-browser-${name}.mjs`,import.meta.url),'utf8'),/withHostedBrowser/);
 for(const name of ['bridge','cleanup','termination'])assert.match(await readFile(new URL(`./test-browser-${name}.mjs`,import.meta.url),'utf8'),/observeContractBrowser/);
 const termination=await readFile(new URL('./test-browser-termination.mjs',import.meta.url),'utf8');assert.match(termination,/beforeKill\(pid\)/);assert.match(termination,/afterKill\(\)/);
});

test('deadline releases timer and monitor initialization reports bounded failures',async()=>{
 const {bounded}=await import('./browser-small-observer.mjs');
 await assert.rejects(bounded(new Promise(()=>{}),5),/timed out/);
});

test('wrapper denies a packet pointing outside the owning scripts before importing a harness',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'chopper-small-wrapper-control-'));
 try{
  const path=join(directory,'packet.json');await writeFile(path,JSON.stringify({...packet(),argv:['/unrelated/test-browser.mjs']}));
  const result=spawnSync(process.execPath,['scripts/browser-small-contract.mjs',path],{encoding:'utf8'});
  assert.notEqual(result.status,0);assert.match(result.stderr,/Owning harness must be in this test checkout/);
 }finally{await rm(directory,{recursive:true});}
});

// Exercise the actual Graph spawn seam without importing the browser harness.
test('Graph codec pins Python/DLL/helper and preserves the original child context',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'chopper-graph-codec-'));
 const helper=fileURLToPath(new URL('./graph-codec-fixtures.py',import.meta.url));
 try{
  const python=join(directory,'python.exe'),dll=join(directory,'zstd.dll');
  await writeFile(python,'declared Python');await writeFile(dll,'declared DLL');
  const inputs=await Promise.all([python,dll,helper].map(async path=>({path,sha256:createHash('sha256').update(await readFile(path)).digest('hex')})));
  const p={...packet(),argv:[fileURLToPath(new URL('./test-browser-graph.mjs',import.meta.url))],python,zstd_dll:dll,inputs};
  validatePacket(p,'chrome',p.argv);
  const payload=Buffer.from('id\n1\n'),stdout=Buffer.from('codec output'),calls=[];
  const spawn=(...args)=>{calls.push(args);return {status:0,stdout};};
  for(const mode of ['zstd-input','zstd-output','zip-input','zip-output']){
   assert.equal(codecFixture(mode,payload,p,spawn),stdout);
   assert.deepEqual(calls.at(-1),[python,[helper,mode,...(mode.startsWith('zstd-')?[dll]:[])],{input:payload,maxBuffer:64*1024*1024}]);
  }
  codecFixture('zstd-input',payload,null,spawn);
  assert.deepEqual(calls.at(-1),['python3',[helper,'zstd-input'],{input:payload,maxBuffer:64*1024*1024}]);
  // No ambient alias or extra packet options can become child options.
  codecFixture('zip-input',payload,{...p,env:{PATH:'alias'},cwd:'/other',python_flags:['-I'],creationflags:8},spawn);
  assert.deepEqual(calls.at(-1),[python,[helper,'zip-input'],{input:payload,maxBuffer:64*1024*1024}]);
  const denied=changed=>{
   const before=calls.length;assert.throws(()=>codecFixture('zip-input',payload,changed,spawn));assert.equal(calls.length,before);
  };
  for(const key of ['python','zstd_dll']){
   const missing={...p};delete missing[key];denied(missing);
   denied({...p,[key]:'python3'});denied({...p,[key]:join(directory,'missing.exe')});
   denied({...p,inputs:inputs.filter(input=>input.path!==p[key])});
   denied({...p,inputs:inputs.map(input=>input.path===p[key]?{...input,sha256:'0'.repeat(64)}:input)});
  }
  denied({...p,inputs:inputs.filter(input=>input.path!==helper)});
  denied({...p,inputs:inputs.map(input=>input.path===helper?{...input,sha256:'0'.repeat(64)}:input)});
  const absent=join(directory,'absent-python.exe');
  denied({...p,python:absent,inputs:[...inputs,{path:absent,sha256:inputs[0].sha256}]});
  denied({...p,zstd_dll:absent,inputs:[...inputs,{path:absent,sha256:inputs[1].sha256}]});
  denied({...p,inputs:[...inputs,inputs[0]]});
  for(const key of ['python','zstd_dll']){
   const alias=join(directory,key+'-alias');await symlink(directory,alias,'junction');
   const aliasedPath=join(alias,basename(p[key]));
   const aliased={...p,[key]:aliasedPath,inputs:[...inputs,{path:aliasedPath,sha256:inputs.find(input=>input.path===p[key]).sha256}]};denied(aliased);
  }
  await writeFile(python,'');denied({...p,inputs:inputs.map(input=>input.path===python?{...input,sha256:createHash('sha256').update('').digest('hex')}:input)});
  await writeFile(python,'declared Python');
  await writeFile(dll,'changed DLL');denied(p);
  for(const key of ['python','zstd_dll']){const missing={...p};delete missing[key];assert.throws(()=>validatePacket(missing,'chrome',p.argv));}
  const error=new Error('spawn failed');
  assert.throws(()=>codecFixture('zip-input',payload,null,()=>({error})),value=>value===error);
  assert.throws(()=>codecFixture('zip-input',payload,null,()=>({status:1,stderr:Buffer.from('codec failed')})),/codec failed/);
  assert.throws(()=>codecFixture('zip-input',payload,null,()=>({status:null,signal:'SIGTERM'})));
 }finally{await rm(directory,{recursive:true});}
});
