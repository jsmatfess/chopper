// Production client/WASI workers with test-only pauses at actual lifecycle edges.
// Routes exist only in this fresh test context; no production artifacts are edited.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {browserChannel,browserLaunchOptions} from './browser-launch.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname,basename,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {assertProductionWasm} from './browser-artifacts.mjs';
import {blockProof} from '../ui/tests/e1-followup-verifier.mjs';
import {shutdown,deadline} from './e1-followup-controller.mjs';
import {captureRuntime,closeOwnedRuntime,stopServer} from './e1-followup-runtime.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
for(const key of ['TEMP','TMP','TMPDIR'])assert(process.env[key]&&resolve(process.env[key])===process.env[key],'absolute task-owned '+key+' required');
assert(process.env.TEMP===process.env.TMP&&process.env.TMP===process.env.TMPDIR,'one task-owned temporary root required');
// E1-only variant: fat tiny fixtures prove real block execution at every pause.
const blockLifecycle=true;
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const wasm=await readFile(root+'ui/dist/engine.wasm');
assertProductionWasm(wasm);
const engineSource=await readFile(root+'ui/dist/engine-worker.js');
const storageSource=await readFile(root+'ui/dist/storage-worker.js');
const bundle=await build({stdin:{contents:`
import {browserApi} from './ui/src/browser/client';
import {clearAbandonedWorkspaces} from './ui/src/browser/cleanup';
import {blockProof} from './ui/tests/e1-followup-verifier.mjs';
const w=window as any;
const blockLifecycle=${blockLifecycle};
w.workerErrors=[];
w.clearAbandonedWorkspaces=clearAbandonedWorkspaces;
let mode='none',selected:File,parent:FileSystemDirectoryHandle;
let retainedAnalysis:any=null;
const records:any[]=[];
const utf8=async(file:File)=>new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
const NativeWorker=window.Worker;
class TrackedWorker extends NativeWorker {
  record:any;
  constructor(url:string|URL,options?:WorkerOptions){
    super(url,options);
    this.record={url:String(url),jobId:null,cleaned:false};records.push(this.record);
    this.addEventListener('message',({data})=>{
      if(data.contractPaused)w.contractPaused=data.contractPaused;
      if(data.cleaned)this.record.cleaned=true;
    });
    this.addEventListener('error',event=>w.workerErrors.push({message:event.message,file:event.filename,line:event.lineno}));
  }
  postMessage(message:any,transfer:any=[]){
    if(message.type==='init'&&this.record.url.endsWith('/storage-worker.js'))this.record.jobId=message.jobId;
    super.postMessage(message.type==='init'?{...message,contractMode:mode}:message,transfer);
  }
}
w.Worker=TrackedWorker;
const rows=Array.from({length:17},(_,i)=>i+','+(i<8?'a':'x'.repeat(2000000))+'\\n');
w.lifecycle={
  api:browserApi,
  async debug(){return {state:await browserApi('state'),records,workerErrors:w.workerErrors,input_bytes:selected?.size,input_head:selected?await utf8(selected.slice(0,80) as File):null};},
  async begin(pauseMode:string,parentName:string){
    mode=pauseMode;w.contractPaused=null;
    retainedAnalysis=null;
    const root=await navigator.storage.getDirectory();
    parent=await root.getDirectoryHandle(parentName);
    selected=new File([pauseMode==='prepare'?'id,key\\n'+Array.from({length:128},(_,i)=>i+','+(i<8?'a':'x'.repeat(262144))+'\\n').join(''):'id,key\\n'+rows.join('')],'fixture.csv');
    Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>selected}],showDirectoryPicker:async()=>parent});
    const defaults:any=await browserApi('defaults');
    await browserApi('pick-path',{mode:'input'});await browserApi('pick-path',{mode:'output'});
    const job={...defaults,input:'fixture.csv',output:'results',seed:'termination-contract',
      operations:[{type:'shuffle',strategy:'uniform'}],
      limits:{rows:pauseMode==='prepare'?25000:4,bytes:null,compressed_bytes:null},
      resources:{...defaults.resources,memory_mb:32,workers:1,max_record_bytes:2097152,temp_dir:null}};
    await browserApi('analyze',job);
  },
  jobId(){const live=records.filter(r=>r.jobId&&!r.cleaned);return live.at(-1)?.jobId;},
  async retainReady(){const state:any=await browserApi('state');if(state.error||w.workerErrors.length)throw new Error('Ready lifecycle error');retainedAnalysis=state.analysis;blockProof(retainedAnalysis);return retainedAnalysis;},
  async inspectSuccess(){
    const state:any=await browserApi('state');
    if(state.error||w.workerErrors.length)throw new Error('Terminal/worker lifecycle error');
    const analysis=state.analysis??retainedAnalysis,proof=blockProof(analysis);
    if(state.status==='complete'&&records.filter(r=>r.jobId).some(r=>!r.cleaned))throw new Error('Complete lifecycle worker owner retained');
    const folder=await parent.getDirectoryHandle(state.output.split('/').at(-1));
    const files:File[]=[];for await(const [,handle] of (folder as any).entries())files.push(await handle.getFile());
    const marker=JSON.parse(await utf8(files.find(f=>f.name==='CHOPPER-COMPLETE.json')!));
    const csv=files.filter(f=>f.name.endsWith('.csv')).sort((a,b)=>Number(a.name.match(/part-(\\d+)/)![1])-Number(b.name.match(/part-(\\d+)/)![1]));
    if(csv.length!==5)throw new Error('Wrong CSV count');
    const hashes=[],seen=new Set<number>();
    for(let i=0;i<csv.length;i++){
      const lines=(await utf8(csv[i])).split('\\n');if(lines.shift()!=='id,key'||lines.pop()!=='')throw new Error('CSV framing changed');
      if(lines.length!==Math.min(4,17-4*i))throw new Error('CSV quota changed');
      for(const line of lines){const fields=line.split(','),id=Number(fields[0]);if(fields.length!==2||!Number.isSafeInteger(id)||id<0||id>=17||String(id)!==fields[0]||seen.has(id)||fields[1]!==(id<8?'a':'x'.repeat(2000000)))throw new Error('CSV field/conservation failure');seen.add(id);}
      const digest=await crypto.subtle.digest('SHA-256',await csv[i].arrayBuffer());
      hashes.push(Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join(''));
    }
    if(seen.size!==17)throw new Error('Missing IDs');
    return {status:state.status,error:state.error??null,worker_errors:w.workerErrors,analysis,block_proof:proof,owner_records:records,marker,csv_files:csv.length,result_files:files.length,csv_sha256:hashes,jobId:records.filter(r=>r.jobId).at(-1).jobId};
  }
};`,resolveDir:root,loader:'ts'},bundle:true,write:false});

const workerWrapper=`
import '/engine-worker-production.js';
let mode='none',paused=false,closedCsv=0,proof=null,retainedAnalysis=null;
const assert=(condition,message)=>{if(!condition)throw new Error(message);};
const validateProof=${blockProof.toString()};
const send=globalThis.postMessage.bind(globalThis);
function pause(details){proof=validateProof(retainedAnalysis);paused=true;send({contractPaused:{...details,analysis:retainedAnalysis,block_proof:proof}});Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0);}
const receive=globalThis.onmessage;
globalThis.onmessage=event=>{if(event.data.type==='init')mode=event.data.contractMode;return receive.call(globalThis,event);};
globalThis.postMessage=(message,...args)=>{
  const analysis=message.result?.analysis;
  if(analysis){retainedAnalysis=analysis;proof=validateProof(analysis);}
  send(message,...args);
  if(paused)return;
  if(mode==='prepare'&&analysis)pause({phase:'prepare',engine_phase:'prepared-before-ready-consumption',rows:analysis.rows,temp_bytes:analysis.temp_bytes});
  const p=message.progress;
  // Preparation pause follows the completed real block-producing prepare.
  if(mode==='export_closed'&&closedCsv>0&&p?.phase?.startsWith('Saving results ('))pause({phase:'export_closed',engine_phase:p.phase,closed_csv_files:closedCsv});
};
const create=FileSystemFileHandle.prototype.createWritable;
FileSystemFileHandle.prototype.createWritable=async function(...args){
  const writer=await Reflect.apply(create,this,args),name=this.name;let writerBytes=0;
  return new Proxy(writer,{get(target,key){
    const value=Reflect.get(target,key,target);
    if(key==='write')return async(...args)=>{
      const result=await Reflect.apply(value,target,args);writerBytes+=args[0].byteLength??0;
      if(!paused&&mode==='export_write'&&name.endsWith('.csv')&&args[0].byteLength<1048576)pause({phase:'export_write',file:name,bytes:writerBytes,writer_closed:false});
      if(!paused&&mode==='marker_write'&&name==='CHOPPER-COMPLETE.json')pause({phase:'marker_write',file:name,bytes:args[0].length,writer_closed:false});
      return result;
    };
    if(key==='close')return async(...args)=>{
      const result=await Reflect.apply(value,target,args);if(name.endsWith('.csv'))closedCsv++;
      if(!paused&&mode==='marker_closed'&&name==='CHOPPER-COMPLETE.json')pause({phase:'marker_closed',file:name,writer_closed:true,closed_csv_files:closedCsv});
      return result;
    };
    return typeof value==='function'?value.bind(target):value;
  }});
};`;
const persistent=process.argv.includes('--persistent');
const processKill=process.argv.includes('--process-kill');
assert(!processKill||persistent,'--process-kill requires --persistent');
const server=spawn(process.execPath,[root+'scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8424'},stdio:['ignore','pipe','inherit']});
let browser,context,profileDirectory,activeOwner,runtimeOwner;
const report={type:'contract',contract:'e1-block-engine-termination-and-export-v1',block_specific:true,fixture_rows:{prepare:128,export:17},
  context:persistent?'disposable persistent Chromium profile, same-origin OPFS, production workers; browser process restart and test-only pause hooks':'fresh temporary Chromium context, same-origin OPFS destinations, production client/WASI/storage workers; test-only pause hooks',
  persistent_profile:persistent,
  restart_method:persistent?(processKill?'forced-browser-process-kill':'normal-browser-shutdown'):null,
  binary_sha256:{'ui/dist/engine.wasm':sha(wasm),'ui/dist/engine-worker.js':sha(engineSource),'ui/dist/storage-worker.js':sha(storageSource)},
  harness_sha256:sha(await readFile(fileURLToPath(import.meta.url))),jobs_started:0,temp_locations:{TEMP:process.env.TEMP,TMP:process.env.TMP,TMPDIR:process.env.TMPDIR},
  fixture_bundle_sha256:sha(bundle.outputFiles[0].contents),worker_pause_source_sha256:sha(workerWrapper),cases:[]};
async function openRuntime(){
  if(persistent){context=await chromium.launchPersistentContext(profileDirectory,browserLaunchOptions);browser=context.browser();}
  else{browser=await chromium.launch(browserLaunchOptions);context=await browser.newContext();}
  report.browserVersion=browser.version();
  report.browserChannel=browserChannel;
  runtimeOwner=await captureRuntime(context,browser,profileDirectory);
  (report.runtime_ownership??=[]).push({pid:runtimeOwner.pid,identity:runtimeOwner.identity,profile:profileDirectory??null});
}
async function closeRuntime(){
  if(!runtimeOwner){const errors=[];await shutdown([['unverified-context-close',()=>deadline(10000).run(()=>context?.close())],['unverified-browser-close',()=>deadline(10000).run(()=>browser?.close())]],errors);if(errors.length)throw new Error(JSON.stringify(errors));return;}
  if(runtimeOwner.exit_observed)return;
  try{const result=await closeOwnedRuntime(runtimeOwner);(report.runtime_shutdown??=[]).push(result);}
  finally{if(runtimeOwner.exit_observed){context=null;browser=null;}}
}
async function browserProcessId(){
  const session=await browser.newBrowserCDPSession();
  try{const info=await session.send('SystemInfo.getProcessInfo');const process=info.processInfo.find(p=>p.type==='browser');assert(process);return process.id;}
  finally{await session.detach();}
}
async function killRuntime(pid){
  // The PID comes from this test-owned browser's CDP session, never a process
  // name search or a user-supplied value. SIGKILL uses TerminateProcess on Windows.
  assert(persistent&&profileDirectory&&browser.isConnected());
  assert(Number.isSafeInteger(pid)&&pid>0&&pid!==process.pid);
  assert.equal(dirname(resolve(profileDirectory)),resolve(tmpdir()));
  assert(basename(profileDirectory).startsWith('chopper-termination-profile-'));
  const killed=browser;
  report.process_termination={pid,pid_source:'CDP SystemInfo.getProcessInfo browser entry',platform:process.platform,signal:'SIGKILL',graceful_shutdown_requested:false};
  process.kill(pid,'SIGKILL');
  report.process_termination.kill_returned=true;
  const deadline=Date.now()+15000;
  let exited=false;
  while(Date.now()<deadline){
    try{process.kill(pid,0);}catch(error){if(error.code==='ESRCH')exited=true;else throw error;}
    if(exited&&!killed.isConnected())break;
    await new Promise(resolve=>setTimeout(resolve,25));
  }
  assert(exited,'Killed browser process is still live');
  assert.equal(killed.isConnected(),false,'Killed browser remained connected');
  Object.assign(report.process_termination,{process_exit_observed:true,browser_disconnected:true});
  runtimeOwner.exit_observed=true;runtimeOwner.context=null;runtimeOwner.browser=null;
  context=null;browser=null;
}
async function removeProfile(){if(profileDirectory){report.profile_directory_retained=profileDirectory;report.profile_directory_removed=false;}}

try{
  await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',code=>reject(new Error('Server exited: '+code)));});
  if(persistent)profileDirectory=await mkdtemp(join(tmpdir(),'chopper-termination-profile-'));
  await openRuntime();let cleaner=await context.newPage();
  const headers={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin',
    'Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'"};
  async function routes(){
    await context.route('**/termination-page.html',route=>route.fulfill({contentType:'text/html',headers,body:'<!doctype html><title>Engine termination contract</title>'}));
    await context.route('**/termination-fixture.js',route=>route.fulfill({contentType:'application/javascript',headers,body:bundle.outputFiles[0].text}));
    await context.route('**/engine-worker-production.js',route=>route.fulfill({contentType:'application/javascript',headers,body:engineSource}));
    await context.route('**/engine-worker.js',route=>route.fulfill({contentType:'application/javascript',headers,body:workerWrapper}));
  }
  await routes();
  const url='http://127.0.0.1:8424/termination-page.html';
  async function page(){const p=await context.newPage();await p.goto(url);await p.addScriptTag({url:'http://127.0.0.1:8424/termination-fixture.js'});return p;}
  await cleaner.goto(url);await cleaner.addScriptTag({url:'http://127.0.0.1:8424/termination-fixture.js'});
  async function waitState(owner,predicate,description){
    const bound=deadline(90000);
    while(bound.remaining()>0){
      const snapshot=await bound.run(()=>owner.evaluate(async()=>({state:await window.lifecycle.api('state'),pause:window.contractPaused,workerErrors:window.workerErrors})));
      if(snapshot.state.status==='failed'||snapshot.state.error||snapshot.workerErrors.length)throw new Error(JSON.stringify(snapshot));
      if(predicate(snapshot)){if(snapshot.state.status==='ready')await bound.run(()=>owner.evaluate(()=>window.lifecycle.retainReady()));if(snapshot.pause)blockProof(snapshot.pause.analysis);return snapshot;}
      await new Promise(resolve=>setTimeout(resolve,25));
    }
    throw new Error('Timed out waiting for '+description);
  }
  const fixture=await cleaner.evaluate(async()=>{
    const id=crypto.randomUUID(),parentName='chopper-termination-tests-'+id,unrelated='termination-unrelated-'+id;
    const root=await navigator.storage.getDirectory(),workspaces=await root.getDirectoryHandle('chopper-workspaces',{create:true});
    const parent=await root.getDirectoryHandle(parentName,{create:true}),other=await workspaces.getDirectoryHandle(unrelated,{create:true});
    for(const directory of [parent,other]){const w=await(await directory.getFileHandle('sentinel',{create:true})).createWritable();await w.write('preserved');await w.close();}
    return {parentName,unrelated};
  });
  async function workspace(id){return await cleaner.evaluate(async id=>{
    const root=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces');
    let directory;try{directory=await root.getDirectoryHandle(id);}catch(e){if(e.name==='NotFoundError')return {exists:false,files:0,locked:false};throw e;}
    let files=0;for await(const [,entry] of directory.entries())if(entry.kind==='file')files++;
    return {exists:true,files,locked:(await navigator.locks.query()).held.some(lock=>lock.name==='chopper-'+id)};
  },id);}
  async function destination(folder){return await cleaner.evaluate(async({parentName,folder})=>{
    const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(parentName);
    const dir=await parent.getDirectoryHandle(folder),files=[];let marker=null;
    for await(const [name,entry] of dir.entries())if(entry.kind==='file'){
      const file=await entry.getFile(),digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
      files.push({name,bytes:file.size,sha256:Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('')});
      if(name==='CHOPPER-COMPLETE.json'){try{marker=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()));}catch{}}
    }
    files.sort((a,b)=>a.name.localeCompare(b.name));
    const entry=files.find(file=>file.name==='CHOPPER-COMPLETE.json');
    const valid=marker?.complete===true&&marker?.engine==='chopper-browser'&&marker?.version===1&&Number.isSafeInteger(marker?.files)&&marker.files===files.length-1;
    return {exists:true,marker_entry:!!entry,marker_bytes:entry?.bytes??null,valid_marker:valid,marker_record:marker,files};
  },{parentName:fixture.parentName,folder});}
  async function preserved(){await cleaner.evaluate(async({parentName,unrelated})=>{
    const root=await navigator.storage.getDirectory(),spaces=await root.getDirectoryHandle('chopper-workspaces');
    for(const dir of [await root.getDirectoryHandle(parentName),await spaces.getDirectoryHandle(unrelated)])
      if(new TextDecoder('utf-8',{fatal:true}).decode(await(await(await dir.getFileHandle('sentinel')).getFile()).arrayBuffer())!=='preserved')throw new Error('Cleanup changed unrelated/exported entries');
  },fixture);}
  for(const phase of ['prepare','export_write','export_closed','marker_write','marker_closed'])for(const action of ['cancel','tab_close']){
    const owner=await page();activeOwner=owner;report.jobs_started++;await owner.evaluate(({phase,parentName})=>window.lifecycle.begin(phase,parentName),{phase,parentName:fixture.parentName});
    if(phase!=='prepare'){
      await waitState(owner,s=>s.state.status==='ready','prepared outputs');
      await owner.evaluate(()=>window.lifecycle.api('run',{}));
    }
    await waitState(owner,s=>!!s.pause,'engine pause at '+phase);
    const paused=await owner.evaluate(async()=>({pause:window.contractPaused,id:window.lifecycle.jobId(),state:await window.lifecycle.api('state')}));
    assert.equal(paused.pause.phase,phase);assert.match(paused.id,/^[0-9a-f-]{36}$/);
    const before=await workspace(paused.id);assert.equal(before.exists,true);assert.equal(before.locked,true);assert(before.files>0,'Actual engine created no workspace files');
    if(phase==='prepare'){assert(paused.pause.temp_bytes>0);assert.equal(paused.pause.rows,128);}
    const skipped=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());assert.equal(skipped,0);assert.deepEqual(await workspace(paused.id),before);
    const folder=phase==='prepare'?null:paused.state.output.split('/').at(-1);
    let committed=null,committedFiles=null;
    if(folder){
      const partial=await destination(folder);assert.equal(partial.valid_marker,phase==='marker_closed');
      if(phase==='marker_write'){assert.equal(partial.marker_entry,true);assert.equal(partial.marker_bytes,0);assert.equal(paused.pause.writer_closed,false);}
      if(phase==='export_closed')assert(partial.files.some(file=>file.name.endsWith('.csv')&&file.bytes>0));
      if(phase==='marker_closed'){
        assert.equal(paused.state.status,'running');assert.equal(paused.pause.closed_csv_files,5);
        committed=await owner.evaluate(()=>window.lifecycle.inspectSuccess());assert.equal(committed.marker.complete,true);assert.equal(committed.csv_files,5);
        committedFiles=partial.files;
      }
    }
    let retry=null;
    if(action==='cancel'){
      await owner.evaluate(()=>window.lifecycle.api('cancel',{}));
      const state=await owner.evaluate(()=>window.lifecycle.api('state'));assert.equal(state.status,'cancelled');assert.equal(state.analysis,null);
      if(phase!=='prepare')assert(state.error.includes('valid CHOPPER-COMPLETE.json record'),'Cancellation guidance treats a bare marker name as complete');
      const rejected=await owner.evaluate(async()=>{try{await window.lifecycle.api('run',{});return false;}catch{return true;}});assert.equal(rejected,true);
      assert.equal((await workspace(paused.id)).exists,false);
      // Reuse this client/module after rejecting its pending request, checking
      // that cancellation does not corrupt the next job.
      report.jobs_started++;await owner.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
      await waitState(owner,s=>s.state.status==='ready','fresh retry preparation');
      await owner.evaluate(()=>window.lifecycle.api('run',{}));
      await waitState(owner,s=>s.state.status==='complete','fresh retry publication');
      retry=await owner.evaluate(()=>window.lifecycle.inspectSuccess());
      assert.equal(retry.marker.complete,true);assert.equal(retry.marker.files,6);assert.equal((await workspace(retry.jobId)).exists,false);
      await owner.close();
    }else{
      await owner.close();
      const deadline=Date.now()+10000;
      while(await cleaner.evaluate(async id=>(await navigator.locks.query()).held.some(lock=>lock.name==='chopper-'+id),paused.id)){
        if(Date.now()>deadline)throw new Error('Closed tab retained its workspace lock');
        await new Promise(resolve=>setTimeout(resolve,25));
      }
      assert.equal((await workspace(paused.id)).exists,true,'Tab close unexpectedly exercised graceful cleanup');
    }
    const removed=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());assert.equal(removed,action==='tab_close'?1:0);assert.equal((await workspace(paused.id)).exists,false);
    const partial=folder?await destination(folder):null;if(partial)assert.equal(partial.valid_marker,phase==='marker_closed');
    if(committedFiles)assert.deepEqual(partial.files,committedFiles,'Termination or cleanup changed committed output bytes');
    await preserved();
    report.cases.push({phase,action,pause:paused.pause,workspace_files_before:before.files,active_owner_locked:true,active_cleanup_removed:skipped,abandoned_cleanup_removed:removed,workspace_absent_after:true,
      cancelled_cannot_run:action==='cancel'?true:null,same_client_fresh_retry:retry,completed_before_reply:committed,export_after_cleanup:partial,unrelated_and_exported_entries_preserved:true});
  }
  const success=await page();activeOwner=success;report.jobs_started++;await success.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
  await waitState(success,s=>s.state.status==='ready','success preparation');
  await success.evaluate(()=>window.lifecycle.api('run',{}));
  await waitState(success,s=>s.state.status==='complete','successful publication');
  report.success_control=await success.evaluate(()=>window.lifecycle.inspectSuccess());
  const successfulFolder=(await success.evaluate(()=>window.lifecycle.api('state'))).output.split('/').at(-1);
  const successfulExport=await destination(successfulFolder);
  assert.equal(report.success_control.marker.complete,true);assert.equal(report.success_control.marker.files,6);assert.equal(report.success_control.result_files,7);
  assert.equal((await workspace(report.success_control.jobId)).exists,false);await success.close();await preserved();
  if(persistent){
    // Leave real jobs paused across shutdown. Restart uses the same disposable
    // on-disk profile and origin, but a new Chromium process and page instances.
    const checkpoints=[];
    const phases=processKill?['prepare','export_write','export_closed','marker_write','marker_closed']:['prepare','marker_write','marker_closed'];
    // Keep observed checkpoints in failed reports as well as successful ones.
    report.restart={checkpoint_phases:phases,checkpoints};
    for(const phase of phases){
      const owner=await page();activeOwner=owner;
      report.jobs_started++;await owner.evaluate(({phase,parent})=>window.lifecycle.begin(phase,parent),{phase,parent:fixture.parentName});
      if(phase!=='prepare'){await waitState(owner,s=>s.state.status==='ready','restart preparation');await owner.evaluate(()=>window.lifecycle.api('run',{}));}
      await waitState(owner,s=>!!s.pause,'restart pause at '+phase);
      const snapshot=await owner.evaluate(async()=>({id:window.lifecycle.jobId(),state:await window.lifecycle.api('state'),pause:window.contractPaused}));
      const before=await workspace(snapshot.id);assert(before.exists&&before.locked&&before.files>0);
      const folder=phase==='prepare'?null:snapshot.state.output.split('/').at(-1);
      const exported=folder?await destination(folder):null;
      if(exported)assert.equal(exported.valid_marker,phase==='marker_closed');
      if(phase==='marker_closed')await owner.evaluate(()=>window.lifecycle.inspectSuccess());
      checkpoints.push({phase,id:snapshot.id,folder,pause:snapshot.pause,files_before:before.files,export_before:exported});
    }
    assert.equal(await cleaner.evaluate(()=>window.clearAbandonedWorkspaces()),0);
    const processBefore=await browserProcessId(),previousBrowser=browser;
    if(processKill)await killRuntime(processBefore);else await closeRuntime();
    assert.equal(previousBrowser.isConnected(),false);
    await openRuntime();const processAfter=await browserProcessId();assert.notEqual(processAfter,processBefore);
    await routes();cleaner=await page();
    assert.deepEqual(await destination(successfulFolder),successfulExport,'Restart changed the earlier success control');
    function stableExport(item,snapshot){
      if(processKill&&(item.phase==='export_write'||item.phase==='marker_write')){
        // An open FSA transaction is not committed data. Account for exactly its
        // known payload and its empty target entry, which may disappear on kill.
        const target=item.phase==='marker_write'?'CHOPPER-COMPLETE.json':item.pause.file;
        const pending=target+'.crswap';
        const marker=JSON.stringify(report.success_control.marker)+'\n';
        const expected=item.phase==='marker_write'?{bytes:Buffer.byteLength(marker),sha256:sha(marker)}:successfulExport.files.find(file=>file.name===target);
        assert(expected);assert.equal(item.pause.writer_closed,false);
        const transient=snapshot.files.filter(file=>file.name===pending);assert(transient.length<=1);
        for(const file of transient){assert.equal(file.bytes,expected.bytes);assert.equal(file.sha256,expected.sha256);}
        for(const file of snapshot.files.filter(file=>file.name===target)){assert.equal(file.bytes,0);assert.equal(file.sha256,sha(''));}
        assert.equal(snapshot.valid_marker,false);
        return {exists:snapshot.exists,valid_marker:snapshot.valid_marker,marker_record:snapshot.marker_record,files:snapshot.files.filter(file=>file.name!==pending&&file.name!==target)};
      }
      if(item.phase!=='marker_write')return snapshot;
      // Chromium can expose the still-open marker writer's transaction file in
      // a persistent profile. It is not a committed export and can be aborted
      // at shutdown. Accept only this exact known pending marker payload.
      const pending=JSON.stringify(report.success_control.marker)+'\n';
      const transient=snapshot.files.filter(file=>file.name==='CHOPPER-COMPLETE.json.crswap');
      assert(transient.length<=1);
      for(const file of transient){assert.equal(file.bytes,Buffer.byteLength(pending));assert.equal(file.sha256,sha(pending));}
      return {...snapshot,files:snapshot.files.filter(file=>file.name!=='CHOPPER-COMPLETE.json.crswap')};
    }
    for(const item of checkpoints){
      const after=await workspace(item.id);assert.equal(after.exists,true);assert.equal(after.locked,false);assert.equal(after.files,item.files_before);
      if(item.folder){
        item.export_after_restart=await destination(item.folder);
        assert.deepEqual(stableExport(item,item.export_after_restart),stableExport(item,item.export_before),'Restart changed committed result files/marker');
      }
    }
    const removed=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());assert.equal(removed,checkpoints.length);
    for(const item of checkpoints){
      assert.equal((await workspace(item.id)).exists,false);
      if(item.folder){
        item.export_after_cleanup=await destination(item.folder);
        assert.deepEqual(item.export_after_cleanup,item.export_after_restart,'Restart cleanup changed exported files');
      }
    }
    await preserved();
    report.restart={new_browser_process:true,same_profile_and_origin:true,active_jobs_before:checkpoints.length,workspaces_retained_until_cleanup:checkpoints.length,locks_released:true,abandoned_cleanup_removed:removed,
      browser_process_before:processBefore,browser_process_after:processAfter,
      closed_result_files_byte_identical:true,completed_exports_byte_identical:true,earlier_success_control_byte_identical:true,invalid_marker_stays_invalid:true,completed_marker_stays_complete:true,unrelated_entries_preserved:true,
      checkpoints:checkpoints.map(({phase,pause,files_before,export_before,export_after_restart,export_after_cleanup})=>({phase,pause,workspace_files:files_before,export_before,export_after_restart,export_after_cleanup}))};
    if(processKill){
      const recovered=await page();activeOwner=recovered;
      report.jobs_started++;await recovered.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
      await waitState(recovered,s=>s.state.status==='ready','post-kill preparation');
      await recovered.evaluate(()=>window.lifecycle.api('run',{}));
      await waitState(recovered,s=>s.state.status==='complete','post-kill publication');
      const result=await recovered.evaluate(()=>window.lifecycle.inspectSuccess());
      assert.deepEqual(result.csv_sha256,report.success_control.csv_sha256);
      assert.deepEqual(result.marker,report.success_control.marker);
      assert.equal(result.result_files,7);assert.equal((await workspace(result.jobId)).exists,false);
      report.restart.fresh_job_after_recovery={...result,csv_bytes_equal_to_control:true,workspace_removed:true};
      await recovered.close();await preserved();
      for(const item of checkpoints)if(item.folder)assert.deepEqual(await destination(item.folder),item.export_after_cleanup,'Recovery job changed an interrupted export');
      assert.deepEqual(await destination(successfulFolder),successfulExport,'Recovery job changed the earlier success control');
      report.restart.fresh_job_preserves_existing_exports=true;
    }
  }
  await cleaner.evaluate(async({parentName,unrelated})=>{
    const root=await navigator.storage.getDirectory(),spaces=await root.getDirectoryHandle('chopper-workspaces');
    await root.removeEntry(parentName,{recursive:true});await spaces.removeEntry(unrelated,{recursive:true});
    let count=0;for await(const _ of spaces.entries())count++;if(count!==0)throw new Error('Test workspaces survived final cleanup');
  },fixture);
  report.test_owned_entries_removed=true;
  assert.equal(report.jobs_started,persistent?(processKill?22:19):16,'fixed lifecycle job count changed');
  assert.equal(sha(await readFile(root+'ui/dist/engine-worker.js')),report.binary_sha256['ui/dist/engine-worker.js']);
  assert.equal(sha(await readFile(root+'ui/dist/storage-worker.js')),report.binary_sha256['ui/dist/storage-worker.js']);
  assert.equal(sha(await readFile(root+'ui/dist/engine.wasm')),report.binary_sha256['ui/dist/engine.wasm']);
  report.production_worker_artifacts_unchanged=true;
  await closeRuntime();await removeProfile();
  console.log(JSON.stringify(report,null,2));
}catch(error){report.error=String(error);if(activeOwner&&!activeOwner.isClosed())report.failure_state=await deadline(5000).run(()=>activeOwner.evaluate(()=>window.lifecycle.debug())).catch(String);console.log(JSON.stringify(report,null,2));throw error;}
finally{const errors=[];await shutdown([['runtime',()=>closeRuntime()],['profile',()=>removeProfile()],['server',async()=>{report.server_shutdown=await stopServer(server);}]],errors);report.runtime_exit_observed=runtimeOwner?.exit_observed??null;if(errors.length){report.secondary_shutdown_errors=errors;process.exitCode=1;}console.error(JSON.stringify({shutdown:report},null,2));}
