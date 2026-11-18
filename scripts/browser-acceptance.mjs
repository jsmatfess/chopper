// One owned, disposable hosted-browser lifetime. Fixtures/assertions stay local.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {launchContractBrowser,observeContractBrowser} from './browser-launch.mjs';

// Engine contracts reveal only the controls they configure. User-facing
// disclosure/focus behavior is covered by the workspace interaction suite.
export async function revealFormControl(page,selector){
 if(await page.locator(selector).evaluate(control=>!!control.closest('.editor')&&document.body.dataset.workspaceView==='execution')){
  await page.locator('.workspace-view-controls [data-workspace-view="configuration"]').click();
  await page.waitForFunction(()=>document.body.dataset.workspaceView==='configuration');
 }
 await page.locator(selector).evaluate(control=>{
  for(let parent=control.parentElement;parent;parent=parent.parentElement){
   if(parent.tagName==='DETAILS')parent.open=true;
  }
 });
}

// Test-only request correlation; processing, storage and observation messages
// still reach the real workers unchanged apart from the existing credit control.
export function installGraphWorkerProbe(host=window){
 const RealWorker=host.Worker;
 host.graphWorkers=new Set();host.graphRunSerial=0;host.graphRunTerminal=null;
 host.Worker=class extends RealWorker{
  #runs=new Map();
  constructor(...args){
   super(...args);host.graphWorkers.add(this);
   this.addEventListener('message',({data})=>{
    if(!data||(!Object.hasOwn(data,'result')&&!Object.hasOwn(data,'error')))return;
    const run=this.#runs.get(data.id);if(!run)return;
    this.#runs.delete(data.id);
    if(run.serial===host.graphRunSerial)host.graphRunTerminal={...run,error:data.error?String(data.error):null};
   });
  }
  postMessage(data,transfer=[]){
   if(data.type==='run-direct'){
    if(this.#runs.size)throw new Error('Overlapping direct Run requests in one worker');
    const serial=++host.graphRunSerial;host.graphRunTerminal=null;
    this.#runs.set(data.id,{serial,folder:data.folder});
   }
   super.postMessage(host.observationDisabled&&data.type==='run-direct'?{...data,observationCredit:undefined}:data,transfer);
  }
  terminate(){super.terminate();this.#runs.clear();host.graphWorkers.delete(this);}
 };
}

// Self-contained so Playwright can evaluate the same predicate in the page.
export function freshDirectRunTerminal(serial,doc=document,terminal=globalThis.graphRunTerminal){
 if(!terminal||terminal.serial!==serial)return false;
 const status=doc.getElementById('status')?.textContent;
 if(terminal.error!==null){
  const error=doc.getElementById('error');
  return status==='FAILED'&&error&&!error.hidden&&error.textContent.includes(terminal.error)
   ?{status:'failed',error:terminal.error}:false;
 }
 const folder=doc.getElementById('result-path')?.textContent?.match(/chopper-results-[a-z0-9-]+/)?.[0];
 return status==='COMPLETE'&&folder===terminal.folder&&!!folder?{status:'complete',folder}:false;
}

export function serverLifetime(child,url,startupMs,stopMs){
 let readyDone=false,closed=false,stopping=false,unexpected=null,runtimeError=null,buffer='';
 let resolveReady,rejectReady,resolveClosed;
 const ready=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
 const exited=new Promise(resolve=>{resolveClosed=resolve;});
 const settle=error=>{
  if(readyDone)return;readyDone=true;clearTimeout(startupTimer);child.stdout.off('data',onData);
  error?rejectReady(error):resolveReady();
 };
 const onData=chunk=>{
  buffer+=chunk.toString();let end;
  while((end=buffer.indexOf('\n'))>=0){
   const line=buffer.slice(0,end).replace(/\r$/,'');buffer=buffer.slice(end+1);
   if(line===`Chopper browser engine: ${url}/`){settle();return;}
  }
  // The owned server prints one ready line; bound unexpected startup output.
  buffer=buffer.slice(-8192);
 };
 const exitError=(code,signal)=>new Error(`Hosted server exited unexpectedly (code ${code}, signal ${signal})`);
 const onError=error=>{if(readyDone)runtimeError=error;else settle(error);};
 const onExit=(code,signal)=>{if(!stopping)unexpected=exitError(code,signal);settle(unexpected??exitError(code,signal));};
 const onClose=(code,signal)=>{
  closed=true;if(!stopping)unexpected??=exitError(code,signal);
  settle(unexpected??exitError(code,signal));resolveClosed();
 };
 const startupTimer=setTimeout(()=>settle(new Error(`Hosted server readiness timed out after ${startupMs}ms`)),startupMs);
 child.stdout.on('data',onData);child.on('error',onError);child.once('exit',onExit);child.once('close',onClose);
 async function waitForExit(){
  if(closed)return true;let timer;
  try{return await Promise.race([exited.then(()=>true),new Promise(resolve=>{timer=setTimeout(()=>resolve(false),stopMs);})]);}
  finally{clearTimeout(timer);}
 }
 return {ready,async stop(){
  const failures=[];stopping=true;
  try{
   if(!closed){
    try{child.kill('SIGTERM');}catch(error){failures.push(error);}
    if(!await waitForExit()){
     try{child.kill('SIGKILL');}catch(error){failures.push(error);}
     if(!await waitForExit())failures.push(new Error('Hosted server did not exit after forced termination'));
    }
   }
   if(unexpected)failures.push(unexpected);
   if(runtimeError)failures.push(runtimeError);
  }finally{
   clearTimeout(startupTimer);child.stdout.off('data',onData);
   child.off('error',onError);child.off('exit',onExit);child.off('close',onClose);
  }
  if(failures.length===1)throw failures[0];
  if(failures.length)throw new AggregateError(failures,'Hosted server cleanup failed');
 }};
}

// Internal dependency seam: real child/browser effects and controlled adapters
// use the same scope. No routes, fault controls or output interpretation live here.
export function createHostedBrowserScope({spawnServer,launchBrowser,observeBrowser=async()=>null,startupMs=15000,stopMs=5000}){
 return async function withHostedBrowser({port,viewport},run){
  let server,browser,context,observer,result;const failures=[];
  try{
   const url=`http://127.0.0.1:${port}`;
   server=serverLifetime(spawnServer(port),url,startupMs,stopMs);
   await server.ready;
   browser=await launchBrowser();context=await browser.newContext(viewport?{viewport}:{});
   observer=await observeBrowser(browser,context,url);
   result=await run({context,url,browserVersion:browser.version()});
  }catch(error){failures.push(error);}
  for(const close of [()=>observer?.stop(),()=>context?.close(),()=>browser?.close(),()=>server?.stop()]){
   try{await close();}catch(error){if(!failures.includes(error))failures.push(error);}
  }
  if(failures.length===1)throw failures[0];
  if(failures.length)throw new AggregateError(failures,'Hosted acceptance failed; cleanup errors retained');
  return result;
 };
}
export const withHostedBrowser=createHostedBrowserScope({
 spawnServer:port=>spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:String(port)},stdio:['ignore','pipe','inherit']}),
 launchBrowser:async()=>launchContractBrowser((await import('../ui/node_modules/playwright/index.mjs')).chromium),
 observeBrowser:observeContractBrowser,
});
