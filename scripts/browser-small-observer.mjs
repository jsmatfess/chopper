// Opt-in SMALL installed-contract observation. No product hooks or scale policy.
import assert from 'node:assert/strict';
import {validateGraphCodecPacket,verifyGraphCodecInputs} from './browser-graph-codec.mjs';
import {readFile,appendFile,realpath,readdir} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import {isAbsolute,dirname,basename,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {assertProductionWasm} from './browser-artifacts.mjs';
const repository=fileURLToPath(new URL('../',import.meta.url));
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const execute=promisify(execFile);
const GiB=1024**3;
export const smallLimits=Object.freeze({batch_seconds:7200,owned_bytes:64*GiB,stop_owned_bytes:56*GiB,start_free_bytes:192*GiB,stop_free_bytes:128*GiB,start_quota_bytes:4*GiB,stop_quota_bytes:2*GiB,sample_ms:1000,stale_ms:5000,disk_stale_ms:90000});
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function bounded(promise,ms=4000){
 let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('SMALL observation timed out')),ms);})]);}finally{clearTimeout(timer);}
}
export function validatePacket(packet,channel,argv=process.argv.slice(1)){
 assert.equal(packet.schema,'chopper-small-contract-observation-v1');
 assert(['chrome','msedge'].includes(channel));assert.equal(packet.channel,channel);
 assert.equal(packet.approved,true,'Parent approval required');
 assert(Number.isFinite(packet.batch_started_ms),'Frozen channel batch start required');
 assert(Array.isArray(packet.volumes)&&packet.volumes.length>0);
 for(const path of packet.volumes)assert(isAbsolute(path));
 for(const key of ['source_commit','source_tree'])assert(/^[a-f0-9]{40}$/.test(packet[key]));
 assert(/^[a-f0-9]{64}$/.test(packet.package_receipt_sha256));
 assert.deepEqual(packet.limits,smallLimits,'Explicit SMALL limits required');
 assert.deepEqual(packet.argv,argv,'Harness/variant mismatch');
 const name=basename(argv[0]??'');const flags=argv.slice(1);
 const variants={
  'test-browser.mjs':[[],['--resource-contracts'],['--resource-contracts','--shuffle-partition']],
  'test-browser-graph.mjs':[[]],
  'test-browser-graph-lifecycle.mjs':[[],['--composed']],
  'test-browser-graph-inspection.mjs':[[]],
  'test-browser-graph-bounds.mjs':[[]],
  'test-browser-bridge.mjs':[[]],
  'test-browser-cleanup.mjs':[[]],
  'test-browser-termination.mjs':[[],['--persistent'],['--persistent','--process-kill'],['--persistent','--process-kill','--direct'],['--persistent','--process-kill','--composed']],
 };
 assert(variants[name]?.some(variant=>JSON.stringify(variant)===JSON.stringify(flags)),'Unsupported protected SMALL harness/variant');
 assert.equal(packet.features,'default-product; separately declared test reactor');
 for(const key of ['executable','guard','runner_lock','receipt'])assert(isAbsolute(packet[key]),`Absolute ${key} required`);
 assert(/^[a-f0-9]{64}$/.test(packet.executable_sha256));
 assert.equal(typeof packet.browser_version,'string');assert(packet.browser_version.length>0);
 const origin=new URL(packet.origin);assert.equal(origin.origin,packet.origin);assert.equal(origin.hostname,'127.0.0.1');assert.equal(origin.protocol,'http:');assert(origin.port);
 assert(Array.isArray(packet.inputs)&&packet.inputs.length>0,'Exact asset/harness sources required');
 for(const input of packet.inputs){assert(isAbsolute(input.path));assert(/^[a-f0-9]{64}$/.test(input.sha256));assert.notEqual(resolve(input.path),resolve(packet.receipt));}
 if(name==='test-browser-graph.mjs')validateGraphCodecPacket(packet);
 for(const key of ['executable','guard','runner_lock'])assert.notEqual(resolve(packet.receipt),resolve(packet[key]));
 assert.equal(typeof packet.reservation,'string');assert(packet.reservation.length>0);
}
export function validateGuard(value,packet,{now=Date.now(),initial=false,pid=process.pid,parent=process.ppid}={}){
 assert.equal(value.schema,'chopper-small-contract-guard-v1');
 assert(!value.error&&value.allowed===true,'Parent guard denied');
 assert(Number.isFinite(value.sampled_ms)&&now-value.sampled_ms>=-1000&&now-value.sampled_ms<=smallLimits.stale_ms,'Stale parent guard');
 assert.equal(value.runner_pid,parent);assert.equal(value.child_pid,pid);
 assert(Array.isArray(value.owned_pids)&&value.owned_pids.every(id=>Number.isSafeInteger(id)&&id>0)&&value.owned_pids.includes(pid),'Child absent from owned Windows Job census');
 assert(Number.isFinite(value.last_progress_ms)&&now>=value.last_progress_ms&&now-value.last_progress_ms<600000,'No contract progress for ten minutes');
 assert.equal(value.reservation,packet.reservation);assert.equal(value.reservation_held,true);
 assert.equal(value.windows_job_kill_on_close,true,'Owned Windows Job required');
 assert.equal(value.batch_started_ms,packet.batch_started_ms,'Batch clock drift');
 assert(Number.isFinite(value.batch_started_ms)&&now>=value.batch_started_ms&&now-value.batch_started_ms<7200000,'Channel deadline');
 assert(Number.isFinite(value.cumulative_owned_bytes)&&value.cumulative_owned_bytes>=0&&value.cumulative_owned_bytes<smallLimits.stop_owned_bytes,'Owned storage ceiling');
 assert(Array.isArray(value.volumes)&&value.volumes.length>0);
 assert.deepEqual(value.volumes.map(volume=>volume.path).sort(),[...packet.volumes].sort(),'Physical volume inventory mismatch');
 for(const volume of value.volumes){assert(Number.isFinite(volume.sampled_ms)&&now-volume.sampled_ms>=-1000&&now-volume.sampled_ms<=smallLimits.disk_stale_ms,'Stale disk capacity');assert.equal(typeof volume.path,'string');assert(Number.isFinite(volume.free_bytes)&&volume.free_bytes>=(initial?smallLimits.start_free_bytes:smallLimits.stop_free_bytes),'Physical capacity floor');}
}
export function validateQuota(value,origin,{now=Date.now(),initial=false}={}){
 assert(!value.error,'Quota sampling failed');assert.equal(value.origin,origin,'Origin mismatch');
 assert.equal(value.secure,true);assert.equal(value.isolated,true);
 assert(Number.isFinite(value.sampled_ms)&&now-value.sampled_ms>=-1000&&now-value.sampled_ms<=smallLimits.disk_stale_ms,'Stale quota');
 assert(Number.isFinite(value.quota)&&value.quota>=0&&Number.isFinite(value.usage)&&value.usage>=0&&value.quota>=value.usage,'Invalid quota');
 // Observer-only 20% headroom for bounded test runs; the product has no
 // automatic quota reserve. Keep this test admission separate from reported quota.
 assert(Math.floor((value.quota-value.usage)*0.8)>=(initial?smallLimits.start_quota_bytes:smallLimits.stop_quota_bytes),'Usable origin quota floor');
 assert.equal(typeof value.persisted,'boolean');
 assert(['granted','denied','prompt'].includes(value.persistence_permission),'Persistence permission unavailable');
}
export function validateBinding(actual,packet,profile){
 assert(Number.isSafeInteger(actual.pid)&&actual.pid>0&&actual.pid!==process.pid);
 assert.equal(actual.executable.toLowerCase(),packet.executable.toLowerCase(),'Running executable mismatch');
 assert.equal(actual.parentPid,process.pid,'Browser is not a direct child of this harness');
 assert.equal(actual.sha256,packet.executable_sha256,'Running executable hash mismatch');
 assert.equal(actual.version,packet.browser_version,'Running browser version mismatch');
 assert.equal(actual.argv[0].toLowerCase(),packet.executable.toLowerCase(),'CDP executable mismatch');
 assert(actual.argv.some(arg=>arg===`--user-data-dir=${profile}`),'Owned profile missing in actual command line');
 assert(actual.commandLine.includes(profile),'OS command line does not bind owned profile');
 assert.equal(typeof actual.started,'string');assert(actual.started.length>0);
}
export async function windowsProcess(pid){
 assert.equal(process.platform,'win32','Protected SMALL installed acceptance requires Windows Job containment');
 assert(Number.isSafeInteger(pid)&&pid>0);
 // PID is from this owned browser's CDP session; no process-name enumeration.
 const script=`$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $p=Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}'; if (!$p) { throw 'Owned browser missing' }; @{parentPid=$p.ParentProcessId;executable=$p.ExecutablePath;commandLine=$p.CommandLine;started=$p.CreationDate.ToString('o')} | ConvertTo-Json -Compress`;
 const {stdout}=await execute('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{timeout:4000,maxBuffer:65536,windowsHide:true});
 return JSON.parse(stdout.replace(/^\uFEFF/,''));
}
export async function launchedIdentity(browser,profile,packet,inspect=windowsProcess){
 const session=await browser.newBrowserCDPSession();
 try{
  const processes=await session.send('SystemInfo.getProcessInfo');
  const owned=processes.processInfo.filter(value=>value.type==='browser');assert.equal(owned.length,1);
  const pid=Number(owned[0].id),os=await inspect(pid);
  const command=await session.send('Browser.getBrowserCommandLine');
  if(!profile){
   const profiles=command.arguments.filter(arg=>arg.startsWith('--user-data-dir='));assert.equal(profiles.length,1);
   profile=profiles[0].slice('--user-data-dir='.length);
   assert.equal(resolve(dirname(profile)),resolve(tmpdir()),'Temporary profile outside owned temp root');
   assert(basename(profile).startsWith('playwright_chromiumdev_profile-'),'Unknown temporary profile owner');
  }
  const actual={...os,pid,argv:command.arguments,version:browser.version(),sha256:digest(await readFile(os.executable))};
  validateBinding(actual,packet,profile);return {...actual,profile};
 }finally{await session.detach();}
}
export async function readPacket(path,channel){
 const bytes=await readFile(path);const packet=JSON.parse(bytes);validatePacket(packet,channel);
 Object.defineProperty(packet,'packetIdentity',{value:{path:resolve(path),sha256:digest(bytes)}});
 return packet;
}
export async function verifyInputs(packet){
 if(basename(packet.argv[0])==='test-browser-graph.mjs')verifyGraphCodecInputs(packet);
 if(packet.packetIdentity)assert.equal(digest(await readFile(packet.packetIdentity.path)),packet.packetIdentity.sha256,'Observation packet drift');
 const paths=new Set(packet.inputs.map(input=>resolve(input.path)));
 // Pin every served asset and every inline-bundled TypeScript source, plus the
 // observing scripts. No claim is made about package custody from a label alone.
 async function covered(directory){
  for(const entry of await readdir(directory,{withFileTypes:true})){
   const path=resolve(directory,entry.name);assert(!entry.isSymbolicLink(),'Input symlink rejected');
   if(entry.isDirectory())await covered(path);else assert(paths.has(path),`Undeclared source/asset: ${path}`);
  }
 }
 for(const directory of ['ui/dist','ui/src'])await covered(resolve(repository,directory));
 assertProductionWasm(await readFile(resolve(repository,'ui/dist/engine.wasm')));
 for(const name of ['browser-launch.mjs','browser-small-contract.mjs','browser-small-observer.mjs','browser-graph-codec.mjs','browser-acceptance.mjs','browser-artifacts.mjs','serve-hosted.mjs'])assert(paths.has(resolve(repository,'scripts',name)),`Undeclared observer dependency: ${name}`);
 assert(paths.has(resolve(process.argv[1])),'Undeclared owning harness');
 for(const input of [...packet.inputs,{path:packet.executable,sha256:packet.executable_sha256}]){
  assert.equal(digest(await readFile(input.path)),input.sha256,`Input drift: ${input.path}`);
 }
 assert.equal(await realpath(packet.executable),packet.executable,'Canonical executable path required');
 assert.equal(Number(await readFile(packet.runner_lock,'utf8')),process.ppid,'Live validation-runner parent required');
}
// Dependencies are deliberately narrow, used by fake controls without Playwright.
export async function observeSmall({packet,browser,context,profile,origin,write,sample,guard,identity,interval=smallLimits.sample_ms}){
 const failures=[];let page,timer,hotTimer,hotPending,pending,stopping=false,expectedPid=null,closed=false,lastOwned=0,actualPid,quotaStarted=null;
 const monitorUrl=origin+'/__chopper-small-observer-'+randomUUID()+'.html';
 const monitorRoute=route=>route.fulfill({contentType:'text/html',headers:{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'},body:'<!doctype html><title>SMALL quota observer</title>'});
 const record=async(type,value)=>bounded(write({type,sampled_ms:Date.now(),...value}));
 const fail=error=>{if(!failures.includes(error))failures.push(error);};
 const disconnect=()=>{if(!stopping&&expectedPid===null)fail(new Error('Unexpected owned browser disconnect'));};
 browser.on('disconnected',disconnect);
 const tick=async(initial=false)=>{
  const started=Date.now();
  assert(quotaStarted===null||started-quotaStarted>=0&&started-quotaStarted<=45000,'Quota sampling start cadence exceeded');
  quotaStarted=started;
  await record('quota-start',{observation_started_ms:started});
  const quota=await bounded(sample(page),Math.max(1,30000-(Date.now()-started)));validateQuota(quota,origin,{initial});
  const capacity=await bounded(guard());validateGuard(capacity,packet,{initial});
  if(actualPid!==undefined)assert(capacity.owned_pids.includes(actualPid),'Browser absent from owned Windows Job census');
  assert(capacity.cumulative_owned_bytes>=lastOwned,'Cumulative owned storage regressed');lastOwned=capacity.cumulative_owned_bytes;
  await record('sample',{capacity,quota});
 };
 try{
  assert.equal(origin,packet.origin,'Harness origin differs from approved packet');
  await tickGuard(true);
  const actual=await bounded(identity(),10000);actualPid=actual.pid;await record('binding',{actual,profile:actual.profile??profile,origin,inputs:packet.inputs});
  await context.route(monitorUrl,monitorRoute);
  page=await context.newPage();await page.goto(monitorUrl,{timeout:10000});
  await tick(true);
  // Hot Job/identity guard stays live while an origin estimate is in flight.
  hotTimer=setInterval(()=>{
   if(hotPending||stopping)return;
   hotPending=tickGuard().catch(async error=>{
    fail(error);clearInterval(timer);clearInterval(hotTimer);
    try{await record('monitor-error',{error:String(error)});}catch(error){fail(error);}
    try{await bounded(context.close());}catch(error){fail(error);}
   }).finally(()=>{hotPending=null;});
  },interval);
  timer=setInterval(()=>{
   if(pending||stopping)return;
   pending=tick().catch(async error=>{
    clearInterval(timer);clearInterval(hotTimer);fail(error);try{await record('monitor-error',{error:String(error)});}catch(error){fail(error);}
    // Closing only the acquired owned context interrupts blocked contract waits.
    try{await bounded(context.close());}catch(error){fail(error);}
   }).finally(()=>{pending=null;});
  },interval);
 }catch(error){
  fail(error);stopping=true;clearInterval(timer);clearInterval(hotTimer);browser.off('disconnected',disconnect);
  try{await page?.close();}catch(error){fail(error);}
  try{await context.unroute(monitorUrl,monitorRoute);}catch(error){fail(error);}
  try{await record('initialization-error',{errors:failures.map(String)});}catch(error){fail(error);}
  throw new AggregateError(failures,'SMALL monitor initialization failed');
 }
 async function tickGuard(initial=false){const value=await bounded(guard());validateGuard(value,packet,{initial});if(actualPid!==undefined)assert(value.owned_pids.includes(actualPid),'Browser absent from owned Windows Job census');}
 async function halt(){stopping=true;clearInterval(timer);clearInterval(hotTimer);await hotPending;await pending;}
 return {
  async beforeKill(pid){
   assert.equal(pid,(await identity()).pid,'Kill PID differs from observed owned browser');
   await halt();if(failures.length)throw new AggregateError(failures,'Monitor failed before deliberate kill');
   await tick();expectedPid=pid;stopping=false;
   await record('deliberate-process-kill-armed',{pid});
  },
  async afterKill(){assert(expectedPid!==null);assert.equal(browser.isConnected(),false);await record('deliberate-process-kill-observed',{pid:expectedPid});},
  async stop(){
   if(closed)return;closed=true;
   await halt();
   try{if(expectedPid===null)await tick();else assert.equal(browser.isConnected(),false,'Deliberate kill did not disconnect');}catch(error){fail(error);}
   browser.off('disconnected',disconnect);
   if(expectedPid===null)for(const close of [()=>page.close(),()=>context.unroute(monitorUrl,monitorRoute)])try{await close();}catch(error){fail(error);}
   try{await record('monitor-cleanup',{errors:failures.map(String),deliberate_pid:expectedPid});}catch(error){fail(error);}
   if(failures.length)throw new AggregateError(failures,'SMALL observation failed (separate from contract assertions)');
  }
 };
}
export async function startSmallObservation({packet,browser,context,profile,origin}){
 if(!packet)return null;
 const write=value=>appendFile(packet.receipt,JSON.stringify(value)+'\n');
 try{await verifyInputs(packet);}catch(error){await write({type:'input-error',sampled_ms:Date.now(),error:String(error)});throw error;}
 const observation=await observeSmall({packet,browser,context,profile,origin,write,
  guard:async()=>JSON.parse(await readFile(packet.guard,'utf8')),
  identity:()=>launchedIdentity(browser,profile,packet),
  sample:page=>page.evaluate(async()=>{
   const sampled_ms=Date.now();const estimate=await navigator.storage.estimate();return {sampled_ms,origin:location.origin,secure:isSecureContext,isolated:crossOriginIsolated,...estimate,persisted:await navigator.storage.persisted(),persistence_permission:(await navigator.permissions.query({name:'persistent-storage'})).state};
  }),
 });
 return {...observation,async stop(){const errors=[];for(const action of [()=>observation.stop(),()=>verifyInputs(packet)])try{await action();}catch(error){errors.push(error);}if(errors.length)throw new AggregateError(errors,'Observation/input finalization failed');}};
}
export async function finishBrowserObservation(observer,closers,primary){
 const errors=primary?[primary]:[];
 for(const close of [()=>observer?.stop(),...closers])try{await close();}catch(error){errors.push(error);}
 if(errors.length===1)throw errors[0];if(errors.length)throw new AggregateError(errors,'Contract/monitor/cleanup failures retained');
}
