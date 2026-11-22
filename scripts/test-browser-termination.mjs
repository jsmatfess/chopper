import {stagedDestinationWorker} from './browser-destination-fixtures.mjs';
import {serverLifetime} from './browser-acceptance.mjs';
import {finishBrowserObservation} from './browser-small-observer.mjs';
// Production client/WASI workers with test-only pauses at actual lifecycle edges.
// Routes exist only in this fresh test context; no production artifacts are edited.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {browserChannel,launchContractBrowser,launchContractPersistentContext,observeContractBrowser,smallContractPacket} from './browser-launch.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname,basename,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {assertProductionWasm} from './browser-artifacts.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const composed=process.argv.includes('--composed');
const direct=process.argv.includes('--direct')||composed;
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const stagedWorker=await stagedDestinationWorker();
const wasm=await readFile(root+'ui/dist/engine.wasm');
assertProductionWasm(wasm);
const engineSource=await readFile(root+'ui/dist/engine-worker.js');
const storageSource=await readFile(root+'ui/dist/storage-worker.js');
const bundle=await build({stdin:{contents:`
import {browserApi} from './ui/src/browser/client';
import {clearAbandonedWorkspaces} from './ui/src/browser/cleanup';
const w=window as any;
const direct=${JSON.stringify(direct)};
const composed=${JSON.stringify(composed)};
w.workerErrors=[];
w.clearAbandonedWorkspaces=clearAbandonedWorkspaces;
let mode='none',selected:File,parent:FileSystemDirectoryHandle;
const records:any[]=[];
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
const rows=Array.from({length:17},(_,i)=>i+','+(i%2?'\u754c':'a')+'\\n');
w.lifecycle={
  api:browserApi,
  async debug(){return {state:await browserApi('state'),records,workerErrors:w.workerErrors,input_bytes:selected?.size,input_head:selected?await selected.slice(0,80).text():null};},
  async begin(pauseMode:string,parentName:string){
    mode=pauseMode;w.contractPaused=null;
    const root=await navigator.storage.getDirectory();
    parent=await root.getDirectoryHandle(parentName);
    selected=new File([pauseMode==='prepare'?'id,key\\n'+Array.from({length:100000},(_,i)=>i+','+(i%2?'b':'a')+'\\n').join(''):'id,key\\n'+rows.join('')],'fixture.csv');
    if(composed)selected=new File([await new Response(selected.stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer()],'fixture.csv.gz');
    Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>selected}],showDirectoryPicker:async()=>parent});
    const defaults:any=await browserApi('defaults');
    await browserApi('pick-path',{mode:'input'});await browserApi('pick-path',{mode:'output'});
    const job={...defaults,input:'fixture.csv',output:'results',
      compression:composed?'gzip':defaults.compression,
      operations:composed?[{type:'partition',columns:[1]},{type:'shuffle',strategy:'fisher_yates'}]:pauseMode==='prepare'&&!direct?[{type:'balanced',files:2},{type:'shuffle',strategy:'uniform'},{type:'partition',columns:[1]}]:[],
      limits:{rows:pauseMode==='prepare'?25000:4,bytes:null,compressed_bytes:null},
      resources:{...defaults.resources,memory_mb:32,workers:1,max_record_bytes:1024*1024,temp_dir:null}};
    await browserApi('run-direct',job);
  },
  jobId(){const live=records.filter(r=>r.jobId&&!r.cleaned);return live.at(-1)?.jobId;},
  async inspectSuccess(){
    const state:any=await browserApi('state');
    const folder=await parent.getDirectoryHandle(state.output.split('/').at(-1));
    const files:File[]=[];for await(const [,handle] of (folder as any).entries())files.push(await handle.getFile());
    const marker=JSON.parse(await files.find(f=>f.name==='CHOPPER-COMPLETE.json')!.text());
    const csv=files.filter(f=>f.name.endsWith('.csv')||composed&&f.name.endsWith('.gz')).sort((a,b)=>composed?a.name.localeCompare(b.name):Number(a.name.match(/part-(\\d+)/)![1])-Number(b.name.match(/part-(\\d+)/)![1]));
    if(csv.length!==5)throw new Error('Wrong CSV count');
    const hashes=[],allRows:string[]=[];
    const manifest=composed?(await files.find(f=>f.name==='manifest.jsonl')!.text()).trim().split('\\n').map(line=>JSON.parse(line)):[];
    for(let i=0;i<csv.length;i++){
      const decoded=composed?await new Response(csv[i].stream().pipeThrough(new DecompressionStream('gzip'))).text():await csv[i].text();
      if(!composed&&decoded!=='id,key\\n'+rows.slice(4*i,4*i+4).join(''))throw new Error('Success control changed rows/order/fields');
      if(composed){const lines=decoded.trimEnd().split('\\n');if(lines.shift()!=='id,key'||lines.length>4)throw new Error('Decoded CSV header/row cap');allRows.push(...lines);const record=manifest.find(record=>record.type==='output'&&record.path===csv[i].name);if(!record||record.rows!==lines.length)throw new Error('Manifest agreement');if(new Set(lines.map(line=>line.split(',')[1])).size!==1)throw new Error('Partition membership');}
      const digest=await crypto.subtle.digest('SHA-256',composed?new TextEncoder().encode(decoded):await csv[i].arrayBuffer());
      hashes.push(Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join(''));
    }
    if(composed&&JSON.stringify(allRows.sort((a,b)=>Number(a.split(',')[0])-Number(b.split(',')[0])))!==JSON.stringify(rows.map(row=>row.trimEnd())))throw new Error('Composed output conservation/fields');
    return {status:state.status,marker,csv_files:csv.length,result_files:files.length,csv_sha256:hashes,jobId:records.filter(r=>r.jobId).at(-1).jobId};
  }
};`,resolveDir:root,loader:'ts'},bundle:true,write:false});

const workerWrapper=`
import '/engine-worker-production.js';
let mode='none',paused=false,closedCsv=0;
const send=globalThis.postMessage.bind(globalThis);
function pause(details){paused=true;send({contractPaused:details});Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0);}
const receive=globalThis.onmessage;
globalThis.onmessage=event=>{if(event.data.type==='init')mode=event.data.contractMode;return receive.call(globalThis,event);};
globalThis.postMessage=(message,...args)=>{
  send(message,...args);
  if(paused)return;
  const p=message.progress;
  if(mode==='prepare'&&p?.rows>=65536)pause({phase:'prepare',engine_phase:p.phase,rows:p.rows,temp_bytes:p.temp_bytes});
  if(mode==='export_closed'&&closedCsv>0&&p?.phase?.startsWith('Saving results ('))pause({phase:'export_closed',engine_phase:p.phase,closed_csv_files:closedCsv});
};
const create=FileSystemFileHandle.prototype.createWritable;
FileSystemFileHandle.prototype.createWritable=async function(...args){
  const writer=await Reflect.apply(create,this,args),name=this.name;
  return new Proxy(writer,{get(target,key){
    const value=Reflect.get(target,key,target);
    if(key==='write')return async(...args)=>{
      const result=await Reflect.apply(value,target,args);
      if(!paused&&((mode==='export_write'&&(name.endsWith('.csv')||name.endsWith('.gz')))||(mode==='marker_write'&&name==='CHOPPER-COMPLETE.json'))){
        const payload=await new Blob([args[0]]).arrayBuffer();
        const digest=await crypto.subtle.digest('SHA-256',payload);
        pause({phase:mode,file:name,bytes:payload.byteLength,sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''),writer_closed:false});
      }
      return result;
    };
    if(key==='close')return async(...args)=>{
      const result=await Reflect.apply(value,target,args);if((name.endsWith('.csv')||name.endsWith('.gz')))closedCsv++;
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
const serverOwner=serverLifetime(server,'http://127.0.0.1:8424',15000,5000);
let browser,context,profileDirectory,activeOwner,observer,primary;
const report={type:'contract',contract:'production-engine-termination-and-export-v4',
  destination_snapshot_scope:'all observed entries; only disappearing recognized Chromium writer swap entries may be absent',
  context:persistent?'disposable persistent Chromium profile, same-origin OPFS, production workers; browser process restart and test-only pause hooks':'fresh temporary Chromium context, same-origin OPFS destinations, production client/WASI/storage workers; test-only pause hooks',
  persistent_profile:persistent,
  direct_run:direct,composed_operations_and_gzip:composed,
  restart_method:persistent?(processKill?'forced-browser-process-kill':'normal-browser-shutdown'):null,
  binary_sha256:{'ui/dist/engine.wasm':sha(wasm),'ui/dist/engine-worker.js':sha(engineSource),'ui/dist/storage-worker.js':sha(storageSource)},
  harness_sha256:sha(await readFile(fileURLToPath(import.meta.url))),
  fixture_bundle_sha256:sha(bundle.outputFiles[0].contents),worker_pause_source_sha256:sha(workerWrapper),cases:[]};
async function openRuntime(){
  if(persistent){context=await launchContractPersistentContext(chromium,profileDirectory);browser=context.browser();}
  else{browser=await launchContractBrowser(chromium);context=await browser.newContext();}
  observer=await observeContractBrowser(browser,context,'http://127.0.0.1:8424',profileDirectory);
  report.browserVersion=browser.version();
  report.browserChannel=browserChannel;
}
async function closeRuntime(){
  await finishBrowserObservation(observer,[async()=>{await context?.close();context=null;},async()=>{if(browser?.isConnected())await browser.close();browser=null;}]);observer=null;
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
  await observer?.beforeKill(pid);
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
  await observer?.afterKill();await observer?.stop();observer=null;
  context=null;browser=null;
}
async function removeProfile(){
  if(!profileDirectory)return;
  // Only delete the task-owned mkdtemp directory, never a supplied user profile.
  const target=resolve(profileDirectory);
  assert.equal(dirname(target),resolve(tmpdir()));assert(basename(target).startsWith('chopper-termination-profile-'));
  await rm(target,{recursive:true,force:true,maxRetries:5,retryDelay:100});profileDirectory=null;
  report.profile_directory_removed=true;
}
try{
  await serverOwner.ready;
  if(persistent)profileDirectory=await mkdtemp(join(tmpdir(),'chopper-termination-profile-'));
  await openRuntime();let cleaner=await context.newPage();
  const headers={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin',
    'Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'"};
  async function routes(){
    await context.route('**/termination-page.html',route=>route.fulfill({contentType:'text/html',headers,body:'<!doctype html><title>Engine termination contract</title>'}));
    await context.route('**/termination-fixture.js',route=>route.fulfill({contentType:'application/javascript',headers,body:bundle.outputFiles[0].text}));
    await context.route('**/engine-worker-production.js',route=>route.fulfill({contentType:'application/javascript',headers,body:stagedWorker}));
    await context.route('**/engine-worker.js',route=>route.fulfill({contentType:'application/javascript',headers,body:workerWrapper}));
  }
  await routes();
  const url='http://127.0.0.1:8424/termination-page.html';
  async function page(){const p=await context.newPage();await p.goto(url);await p.addScriptTag({url:'http://127.0.0.1:8424/termination-fixture.js'});return p;}
  await cleaner.goto(url);await cleaner.addScriptTag({url:'http://127.0.0.1:8424/termination-fixture.js'});
  async function waitState(owner,predicate,description){
    const deadline=Date.now()+90000;
    while(Date.now()<deadline){
      const snapshot=await owner.evaluate(async()=>({state:await window.lifecycle.api('state'),pause:window.contractPaused}));
      if(snapshot.state.status==='failed')throw new Error(snapshot.state.error);
      if(predicate(snapshot))return snapshot;
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
  async function destination(folder){return await cleaner.evaluate(async({parentName,folder,composed})=>{
    const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(parentName);
    const dir=await parent.getDirectoryHandle(folder),files=[];let marker=null;
    for await(const [name,entry] of dir.entries())if(entry.kind==='file'){
      try{
      const file=await entry.getFile(),digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
      files.push({name,bytes:file.size,sha256:Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('')});
      if(name==='CHOPPER-COMPLETE.json'){try{marker=JSON.parse(await file.text());}catch{}}
      }catch(error){
        // A terminated Chromium writer may remove its private swap between
        // enumeration and reading. Retain/read every observable swap so the
        // existing exact pending-payload assertions still run. Real result
        // errors and all other exception types remain failures.
        // The composed fixture has exactly the generated key-a/key-界 gzip names.
        const writerSwap=composed?/^(manifest[.]jsonl|part-[0-9]+[.]csv|key-(a|界)-part-[0-9]+[.]csv[.]gz|CHOPPER-COMPLETE[.]json)([.][0-9]+)?[.]crswap$/.test(name):/^(manifest[.]jsonl|part-[0-9]+[.]csv|CHOPPER-COMPLETE[.]json)([.][0-9]+)?[.]crswap$/.test(name);
        if(error.name!=='NotFoundError'||!writerSwap)throw error;
      }
    }
    files.sort((a,b)=>a.name.localeCompare(b.name));
    const entry=files.find(file=>file.name==='CHOPPER-COMPLETE.json');
    const valid=marker?.complete===true&&marker?.engine==='chopper-browser'&&marker?.version===1&&Number.isSafeInteger(marker?.files)&&marker.files===files.length-1;
    return {exists:true,marker_entry:!!entry,marker_bytes:entry?.bytes??null,valid_marker:valid,marker_record:marker,files};
  },{parentName:fixture.parentName,folder,composed});}
  async function preserved(){await cleaner.evaluate(async({parentName,unrelated})=>{
    const root=await navigator.storage.getDirectory(),spaces=await root.getDirectoryHandle('chopper-workspaces');
    for(const dir of [await root.getDirectoryHandle(parentName),await spaces.getDirectoryHandle(unrelated)])
      if(await(await(await dir.getFileHandle('sentinel')).getFile()).text()!=='preserved')throw new Error('Cleanup changed unrelated/exported entries');
  },fixture);}
  // Exercise the observer's error boundary without hiding real result loss.
  // Use real OPFS entries; only getFile's rejection is injected in this page.
  const observerFolder='snapshot-observer-control';
  await cleaner.evaluate(async({parentName,folder,composed})=>{
    const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(parentName);
    const dir=await parent.getDirectoryHandle(folder,{create:true});
    const names=['part-00000001.csv','CHOPPER-COMPLETE.json.crswap','unrelated.crswap'];if(composed)names.push('key-a-part-00000001.csv.gz','key-a-part-00000001.csv.gz.crswap');
    for(const name of names)await dir.getFileHandle(name,{create:true});
    const original=FileSystemFileHandle.prototype.getFile;
    window.observerFault=null;window.restoreObserver=()=>{FileSystemFileHandle.prototype.getFile=original;};
    FileSystemFileHandle.prototype.getFile=function(...args){
      if(this.name===window.observerFault?.name)return Promise.reject(new DOMException('Injected destination observer error',window.observerFault.error));
      return Reflect.apply(original,this,args);
    };
  },{parentName:fixture.parentName,folder:observerFolder,composed});
  try{
    await cleaner.evaluate(()=>{window.observerFault={name:'CHOPPER-COMPLETE.json.crswap',error:'NotFoundError'};});
    const observed=await destination(observerFolder);
    assert(observed.files.some(file=>file.name==='part-00000001.csv'));
    assert(!observed.files.some(file=>file.name==='CHOPPER-COMPLETE.json.crswap'));
    if(composed){await cleaner.evaluate(()=>{window.observerFault={name:'key-a-part-00000001.csv.gz.crswap',error:'NotFoundError'};});const compressed=await destination(observerFolder);assert(compressed.files.some(file=>file.name==='key-a-part-00000001.csv.gz'));assert(!compressed.files.some(file=>file.name==='key-a-part-00000001.csv.gz.crswap'));}
    for(const fault of [{name:'part-00000001.csv',error:'NotFoundError'},
      {name:'unrelated.crswap',error:'NotFoundError'},{name:'CHOPPER-COMPLETE.json.crswap',error:'NotReadableError'},...(composed?[{name:'key-a-part-00000001.csv.gz',error:'NotFoundError'},{name:'key-a-part-00000001.csv.gz.crswap',error:'NotReadableError'}]:[])]){
      await cleaner.evaluate(fault=>{window.observerFault=fault;},fault);
      await assert.rejects(destination(observerFolder),new RegExp(fault.error));
    }
    report.destination_observer_controls={disappearing_browser_swap_tolerated:true,real_result_loss_rejected:true,
      unrecognized_swap_loss_rejected:true,other_swap_errors_rejected:true};
  }finally{
    await cleaner.evaluate(async({parentName,folder})=>{
      window.restoreObserver();delete window.restoreObserver;delete window.observerFault;
      const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(parentName);
      await parent.removeEntry(folder,{recursive:true});
    },{parentName:fixture.parentName,folder:observerFolder,composed});
  }
  for(const phase of ['prepare','export_write','export_closed','marker_write','marker_closed'])for(const action of ['cancel','tab_close']){
    const owner=await page();activeOwner=owner;await owner.evaluate(({phase,parentName})=>window.lifecycle.begin(phase,parentName),{phase,parentName:fixture.parentName});

    await waitState(owner,s=>!!s.pause,'engine pause at '+phase);
    const paused=await owner.evaluate(async()=>({pause:window.contractPaused,id:window.lifecycle.jobId(),state:await window.lifecycle.api('state')}));
    assert.equal(paused.pause.phase,phase);assert.match(paused.id,/^[0-9a-f-]{36}$/);
    const before=await workspace(paused.id);assert.equal(before.exists,true);assert.equal(before.locked,true);assert(before.files>0,'Actual engine created no workspace files');
    if(phase==='prepare'){if(!direct)assert(paused.pause.temp_bytes>0);assert(paused.pause.rows>=65536);}
    const skipped=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());assert.equal(skipped,0);assert.deepEqual(await workspace(paused.id),before);
    const folder=phase==='prepare'?null:paused.state.output.split('/').at(-1);
    let committed=null,committedFiles=null;
    if(folder){
      const partial=await destination(folder);assert.equal(partial.valid_marker,phase==='marker_closed');
      if(phase==='marker_write'){assert.equal(partial.marker_entry,true);assert.equal(partial.marker_bytes,0);assert.equal(paused.pause.writer_closed,false);}
      if(phase==='export_closed')assert(partial.files.some(file=>(file.name.endsWith('.csv')||file.name.endsWith('.gz'))&&file.bytes>0));
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
      await owner.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
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
  const success=await page();await success.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
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
      await owner.evaluate(({phase,parent})=>window.lifecycle.begin(phase,parent),{phase,parent:fixture.parentName});
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
        // New Runs have independent entropy. Bind the pending transaction to its
        // own observed write payload, never to a previous successful Run.
        const expected={bytes:item.pause.bytes,sha256:item.pause.sha256};
        assert.ok(expected.bytes>0&&/^[a-f0-9]{64}$/.test(expected.sha256));assert.equal(item.pause.writer_closed,false);
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
      const pending={bytes:item.pause.bytes,sha256:item.pause.sha256};
      assert.ok(pending.bytes>0&&/^[a-f0-9]{64}$/.test(pending.sha256));
      const transient=snapshot.files.filter(file=>file.name==='CHOPPER-COMPLETE.json.crswap');
      assert(transient.length<=1);
      for(const file of transient){assert.equal(file.bytes,pending.bytes);assert.equal(file.sha256,pending.sha256);}
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
      await recovered.evaluate(parent=>window.lifecycle.begin('none',parent),fixture.parentName);
      await waitState(recovered,s=>s.state.status==='complete','post-kill publication');
      const result=await recovered.evaluate(()=>window.lifecycle.inspectSuccess());
      if(!composed)assert.deepEqual(result.csv_sha256,report.success_control.csv_sha256);
      // inspectSuccess independently verifies fresh randomized fields, membership and caps.
      assert.deepEqual(result.marker,report.success_control.marker);
      assert.equal(result.result_files,7);assert.equal((await workspace(result.jobId)).exists,false);
      report.restart.fresh_job_after_recovery={...result,csv_bytes_equal_to_control:!composed,independent_fields_membership_and_caps:true,workspace_removed:true};
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
  assert.equal(sha(await readFile(root+'ui/dist/engine-worker.js')),report.binary_sha256['ui/dist/engine-worker.js']);
  assert.equal(sha(await readFile(root+'ui/dist/storage-worker.js')),report.binary_sha256['ui/dist/storage-worker.js']);
  assert.equal(sha(await readFile(root+'ui/dist/engine.wasm')),report.binary_sha256['ui/dist/engine.wasm']);
  report.production_worker_artifacts_unchanged=true;
  report.destination_mode='staged copy fault fixture';
  report.staged_worker_sha256=sha(stagedWorker);
  await closeRuntime();await removeProfile();
  console.log(JSON.stringify(report,null,2));
}catch(error){primary=error;report.error=String(error);if(activeOwner&&!activeOwner.isClosed())report.failure_state=await activeOwner.evaluate(()=>window.lifecycle.debug()).catch(String);console.log(JSON.stringify(report,null,2));}
finally{await finishBrowserObservation(null,[closeRuntime,()=>primary&&smallContractPacket?undefined:removeProfile(),()=>serverOwner.stop()],primary);}
