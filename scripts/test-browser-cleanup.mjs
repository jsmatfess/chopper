import {serverLifetime} from './browser-acceptance.mjs';
import {finishBrowserObservation} from './browser-small-observer.mjs';
// Real same-origin peer tab/worker locks and OPFS; no WASM or memory-ledger claim.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {browserChannel,launchContractBrowser,observeContractBrowser} from './browser-launch.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const bundle=await build({stdin:{contents:`import {clearAbandonedWorkspaces,inspectAbandonedWorkspaces} from './ui/src/browser/cleanup';import {configureCleanupControls} from './ui/src/browser/cleanup-controls';Object.assign(window,{clearAbandonedWorkspaces,inspectAbandonedWorkspaces,configureCleanupControls});`,resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false});
const server=spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:'8423'},stdio:['ignore','pipe','inherit']});
const serverOwner=serverLifetime(server,'http://127.0.0.1:8423',15000,5000);
let browser,observer,primary;
try{
  await serverOwner.ready;
  browser=await launchContractBrowser(chromium);
  const context=await browser.newContext();
  observer=await observeContractBrowser(browser,context,'http://127.0.0.1:8423');
  const owner=await context.newPage(),cleaner=await context.newPage();
  await context.route('**/cleanup-page.html',route=>route.fulfill({contentType:'text/html',headers:{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Content-Security-Policy':"default-src 'self'; script-src 'self'; worker-src 'self'"},body:'<!doctype html><title>Workspace cleanup contract</title>'}));
  await context.route('**/cleanup-fixture.js',route=>route.fulfill({contentType:'application/javascript',headers:{'Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'},body:bundle.outputFiles[0].text}));
  await context.route('**/cleanup-lock-worker.js',route=>route.fulfill({contentType:'application/javascript',headers:{'Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'},body:`onmessage=async({data:id})=>{await navigator.locks.request('chopper-'+id,async()=>{const root=await navigator.storage.getDirectory();const folder=await(await root.getDirectoryHandle('chopper-workspaces')).getDirectoryHandle(id);const handle=await(await folder.getFileHandle('sentinel')).createSyncAccessHandle();postMessage({held:true});await new Promise(()=>{});handle.close();});};`}));
  for(const page of [owner,cleaner])await page.goto('http://127.0.0.1:8423/cleanup-page.html');
  await cleaner.addScriptTag({url:'http://127.0.0.1:8423/cleanup-fixture.js'});
  assert.deepEqual(await cleaner.evaluate(()=>window.inspectAbandonedWorkspaces()),{removed:0,remaining:0},'an unused origin has nothing to clean');
  const fixture=await owner.evaluate(async()=>{
    const ids={tab:crypto.randomUUID(),worker:crypto.randomUUID(),abandoned:crypto.randomUUID(),unrelatedFile:crypto.randomUUID(),unrelatedDirectory:'cleanup-unrelated-'+crypto.randomUUID(),exported:'cleanup-exported-'+crypto.randomUUID()};
    const root=await navigator.storage.getDirectory(),workspaces=await root.getDirectoryHandle('chopper-workspaces',{create:true});
    async function sentinel(directory){const writer=await(await directory.getFileHandle('sentinel',{create:true})).createWritable();await writer.write('preserved');await writer.close();}
    for(const id of [ids.tab,ids.worker,ids.abandoned,ids.unrelatedDirectory])await sentinel(await workspaces.getDirectoryHandle(id,{create:true}));
    const unrelated=await(await workspaces.getFileHandle(ids.unrelatedFile,{create:true})).createWritable();await unrelated.write('unrelated');await unrelated.close();
    await sentinel(await root.getDirectoryHandle(ids.exported,{create:true}));
    await new Promise(resolve=>{void navigator.locks.request('chopper-'+ids.tab,async()=>{await new Promise(release=>{window.releaseTab=release;resolve();});});});
    const worker=new Worker('/cleanup-lock-worker.js');window.cleanupWorker=worker;
    await new Promise((resolve,reject)=>{worker.onmessage=()=>resolve();worker.onerror=event=>reject(new Error('Lock worker: '+event.message+' '+event.filename+':'+event.lineno));worker.postMessage(ids.worker);});
    return ids;
  });
  const inspect=()=>cleaner.evaluate(async ids=>{
    const root=await navigator.storage.getDirectory(),workspaces=await root.getDirectoryHandle('chopper-workspaces');
    const found={};
    for(const key of ['tab','worker','abandoned','unrelatedDirectory']){
      try{const dir=await workspaces.getDirectoryHandle(ids[key]);found[key]=await(await(await dir.getFileHandle('sentinel')).getFile()).text();}
      catch(error){if(error.name!=='NotFoundError')throw error;found[key]=null;}
    }
    found.unrelatedFile=await(await(await workspaces.getFileHandle(ids.unrelatedFile)).getFile()).text();
    found.exported=await(await(await(await root.getDirectoryHandle(ids.exported)).getFileHandle('sentinel')).getFile()).text();
    return found;
  },fixture);
  // query() is a diagnostic snapshot, not a lock-release barrier: after a peer
  // closes it can report no held lock before ifAvailable will grant it. Queue
  // one real acquisition/release before asserting the nonblocking cleanup count.
  const waitForWorkspaceRelease=id=>cleaner.evaluate(async id=>{
    await navigator.locks.request('chopper-'+id,{signal:AbortSignal.timeout(10000)},()=>{});
  },id);
  const first=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());
  assert.equal(first,1);
  assert.deepEqual(await inspect(),{tab:'preserved',worker:'preserved',abandoned:null,unrelatedDirectory:'preserved',unrelatedFile:'unrelated',exported:'preserved'});
  const automatic=await cleaner.evaluate(async()=>{
    const root=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces');
    const disposable=crypto.randomUUID(),retry=crypto.randomUUID();
    await root.getDirectoryHandle(disposable,{create:true});await root.getDirectoryHandle(retry,{create:true});
    const remove=FileSystemDirectoryHandle.prototype.removeEntry;window.blockCleanup=true;
    FileSystemDirectoryHandle.prototype.removeEntry=function(name,options){if(name===retry&&window.blockCleanup)return Promise.reject(new DOMException('Fixture deletion denied','NoModificationAllowedError'));return remove.call(this,name,options);};
    const footer=document.createElement('footer');document.body.append(footer);window.configureCleanupControls(footer);
    return {disposable,retry};
  });
  const clear=cleaner.getByRole('button',{name:'Clear temporary data',exact:true});
  await clear.waitFor({state:'visible'});
  assert.match(await cleaner.getByRole('status').innerText(),/1 unused workspace remains/);
  assert.equal(await cleaner.evaluate(async id=>{try{await(await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces')).getDirectoryHandle(id);return true;}catch(error){if(error.name==='NotFoundError')return false;throw error;}},automatic.disposable),false,'startup sweep removes abandoned data automatically');
  assert.equal((await inspect()).tab,'preserved');assert.equal((await inspect()).worker,'preserved');
  await cleaner.evaluate(()=>window.blockCleanup=false);await clear.click();await clear.waitFor({state:'hidden'});
  assert.equal(await cleaner.locator('footer').isHidden(),true,'successful cleanup leaves no footer/link');
  const later=await cleaner.evaluate(async()=>{const id=crypto.randomUUID();await(await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces')).getDirectoryHandle(id,{create:true});window.dispatchEvent(new Event('focus'));return id;});
  await clear.waitFor({state:'visible'});
  assert.equal(await cleaner.evaluate(async id=>{await(await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces')).getDirectoryHandle(id);return true;},later),true,'returning to the tab checks without deleting');
  await clear.click();await clear.waitFor({state:'hidden'});
  await cleaner.evaluate(()=>window.dispatchEvent(new Event('focus')));
  assert.deepEqual(await cleaner.evaluate(()=>window.inspectAbandonedWorkspaces()),{removed:0,remaining:0},'active owners alone do not expose the link');
  await owner.evaluate(()=>window.cleanupWorker.terminate());
  await waitForWorkspaceRelease(fixture.worker);
  const afterWorkerExit=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());
  assert.equal(afterWorkerExit,1);
  assert.equal((await inspect()).tab,'preserved');assert.equal((await inspect()).worker,null);
  await owner.close();
  await waitForWorkspaceRelease(fixture.tab);
  const afterTabExit=await cleaner.evaluate(()=>window.clearAbandonedWorkspaces());
  assert.equal(afterTabExit,1);
  assert.deepEqual(await inspect(),{tab:null,worker:null,abandoned:null,unrelatedDirectory:'preserved',unrelatedFile:'unrelated',exported:'preserved'});
  await cleaner.evaluate(async ids=>{
    const root=await navigator.storage.getDirectory(),workspaces=await root.getDirectoryHandle('chopper-workspaces');
    await workspaces.removeEntry(ids.unrelatedFile);await workspaces.removeEntry(ids.unrelatedDirectory,{recursive:true});await root.removeEntry(ids.exported,{recursive:true});
    let entries=0;for await(const _ of workspaces.entries())entries++;
    if(entries!==0)throw new Error('Test-owned workspace entries survived cleanup');
  },fixture);
  console.log(JSON.stringify({type:'contract',contract:'peer-tab-worker-workspace-cleanup-v1',browserChannel,browserVersion:browser.version(),context:'two pages and one dedicated worker in a fresh shared browser context; real OPFS',initial_abandoned_removed:first,after_worker_termination_removed:afterWorkerExit,after_tab_close_removed:afterTabExit,startup_sweep_verified:true,failed_deletion_retry_verified:true,conditional_link_verified:true,focus_detection_verified:true,active_tab_preserved:true,active_worker_sync_handle_preserved:true,unrelated_file_preserved:true,unrelated_directory_preserved:true,exported_results_preserved:true,test_owned_entries_removed:true,scope:'workspace deletion coordination only; no aggregate memory, engine cancellation or external-destination claim'},null,2));
}catch(error){primary=error;}finally{await finishBrowserObservation(observer,[()=>browser?.close(),()=>serverOwner.stop()],primary);}
