// The owning CI command includes the independent SMALL fake controls.
import './browser-small-observer.test.mjs';
import './browser-small-bootstrap.test.mjs';
import './browser-launch-options.test.mjs';
import './browser-resource-routing.test.mjs';
import './browser-build.test.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {spawn} from 'node:child_process';
import http from 'node:http';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {createHostedBrowserScope,revealFormControl,installGraphWorkerProbe,freshDirectRunTerminal} from './browser-acceptance.mjs';

const port=14991;
function setup(options={}){
 const events=[];
 class Child extends EventEmitter {
  stdout=new PassThrough();exitCode=null;signalCode=null;
  end(code=0,signal=null){this.exitCode=code;this.signalCode=signal;this.emit('exit',code,signal);this.stdout.end();this.emit('close',code,signal);}
  kill(signal){events.push(signal);if(options.neverExit||options.ignoreTerm&&signal==='SIGTERM')return true;queueMicrotask(()=>this.end(null,signal));return true;}
 }
 const child=new Child();
 const context={close:async()=>{events.push('context.close');if(options.contextClose)throw options.contextClose;}};
 const browser={version:()=> 'controlled-browser',newContext:async config=>{events.push(['context',config]);if(options.contextFailure)throw options.contextFailure;return context;},close:async()=>{events.push('browser.close');if(options.browserClose)throw options.browserClose;}};
 const scope=createHostedBrowserScope({startupMs:10,stopMs:10,
  spawnServer:()=>{events.push('spawn');if(options.spawnFailure)throw options.spawnFailure;queueMicrotask(()=>{
   if(options.childError){child.emit('error',options.childError);child.end(1);}
   else if(options.earlyExit)child.end(3);
   else if(!options.noReady){child.stdout.write('diagnostic, not readiness\nChopper browser en');child.stdout.write(`gine: http://127.0.0.1:${port}/\r\n`);}
  });return child;},
  observeBrowser:options.observeBrowser,
  launchBrowser:async()=>{events.push('launch');if(options.launchFailure)throw options.launchFailure;return browser;},
 });
 return {scope,child,context,events};
}
function reasons(error){return error instanceof AggregateError?error.errors.flatMap(reasons):[error];}

test('split exact readiness and explicit viewport; cleanup finishes before returning result',async()=>{
 const h=setup();
 const value=await h.scope({port,viewport:{width:1280,height:900}},async scope=>{
  assert.equal(scope.context,h.context);assert.equal(scope.url,`http://127.0.0.1:${port}`);assert.equal(scope.browserVersion,'controlled-browser');h.events.push('callback');return 42;
 });
 assert.equal(value,42);assert.deepEqual(h.events,['spawn','launch',['context',{viewport:{width:1280,height:900}}],'callback','context.close','browser.close','SIGTERM']);assert.equal(h.child.signalCode,'SIGTERM');
 assert.equal(h.child.listenerCount('close'),0);assert.equal(h.child.stdout.listenerCount('data'),0);
});

test('arbitrary stdout is not readiness',async()=>{
 const h=setup({noReady:true});let called=false;
 const run=h.scope({port},async()=>{called=true;});h.child.stdout.write('some output\n');
 await assert.rejects(run,/readiness timed out/);assert.equal(called,false);assert.equal(h.events.includes('launch'),false);assert.equal(h.child.signalCode,'SIGTERM');
});

test('spawn exception never closes or kills unacquired resources',async()=>{
 const failure=new Error('spawn failed'),h=setup({spawnFailure:failure});await assert.rejects(h.scope({port},()=>{}),error=>error===failure);assert.deepEqual(h.events,['spawn']);
});

test('child error/early exit rejects startup without launching a browser',async()=>{
 for(const options of [{childError:new Error('child spawn error')},{earlyExit:true}]){
  const h=setup(options);await assert.rejects(h.scope({port},()=>{}),error=>reasons(error).some(e=>/spawn error|exited unexpectedly/.test(String(e))));assert.equal(h.events.includes('launch'),false);assert.equal(h.child.exitCode!==null,true);
 }
});

test('browser launch and context setup failures still observe server exit',async()=>{
 for(const field of ['launchFailure','contextFailure']){
  const failure=new Error(field),h=setup({[field]:failure});await assert.rejects(h.scope({port},()=>{}),error=>error===failure);
  assert.equal(h.child.signalCode,'SIGTERM');assert.equal(h.events.includes('context.close'),false);assert.equal(h.events.includes('browser.close'),field==='contextFailure');
 }
});

test('callback failure remains the original error after complete cleanup',async()=>{
 const failure=new Error('assertion failed'),h=setup();await assert.rejects(h.scope({port},()=>{throw failure;}),error=>error===failure);assert.equal(h.child.signalCode,'SIGTERM');assert.ok(h.events.includes('context.close'));assert.ok(h.events.includes('browser.close'));
});

test('context/browser close failures do not skip later resources and preserve all diagnostics',async()=>{
 const body=new Error('body failed'),contextClose=new Error('context close failed'),browserClose=new Error('browser close failed'),h=setup({contextClose,browserClose});
 await assert.rejects(h.scope({port},()=>{throw body;}),error=>{assert.deepEqual(reasons(error),[body,contextClose,browserClose]);return true;});assert.equal(h.child.signalCode,'SIGTERM');
});

test('successful callback cannot hide browser-close failure',async()=>{
 const failure=new Error('close failed'),h=setup({browserClose:failure});await assert.rejects(h.scope({port},()=>42),error=>error===failure);assert.equal(h.child.signalCode,'SIGTERM');
});

test('server ignoring graceful shutdown is forced to exit before scope returns',async()=>{
 const h=setup({ignoreTerm:true});await h.scope({port},()=>{});assert.deepEqual(h.events.slice(-2),['SIGTERM','SIGKILL']);assert.equal(h.child.signalCode,'SIGKILL');
});

test('failure to observe server exit is reported, not successful cleanup',async()=>{
 const h=setup({neverExit:true});await assert.rejects(h.scope({port},()=>{}),/did not exit after forced termination/);h.child.end();
});

test('unexpected post-readiness server exit cannot produce a successful scope',async()=>{
 const h=setup();await assert.rejects(h.scope({port},()=>{h.child.end(4);}),/exited unexpectedly/);assert.equal(h.events.includes('SIGTERM'),false);
});

async function freePort(){
 const socket=http.createServer();await new Promise((resolve,reject)=>{socket.once('error',reject);socket.listen(0,'127.0.0.1',resolve);});const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));return port;
}
test('real owned hosted server exits and its port can be reused',async()=>{
 const port=await freePort();let child;
 const scope=createHostedBrowserScope({
  spawnServer:port=>child=spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:String(port)},stdio:['ignore','pipe','inherit']}),
  launchBrowser:async()=>({version:()=> 'controlled-browser',newContext:async()=>({close:async()=>{}}),close:async()=>{}}),
 });
 await scope({port},async({url})=>{
  const response=await fetch(url+'/missing');assert.equal(response.status,404);assert.equal(response.headers.get('cross-origin-opener-policy'),'same-origin');assert.equal(response.headers.get('cross-origin-embedder-policy'),'require-corp');
 });
 assert.ok(child.exitCode!==null||child.signalCode!==null);
 const next=http.createServer();try{await new Promise((resolve,reject)=>{next.once('error',reject);next.listen(port,'127.0.0.1',resolve);});}finally{await new Promise(resolve=>next.close(resolve));}
});

test('real bind failure rejects startup and leaves the existing listener alone',async()=>{
 const listener=http.createServer((_,response)=>response.end('other scope'));
 await new Promise((resolve,reject)=>{listener.once('error',reject);listener.listen(0,'127.0.0.1',resolve);});
 const port=listener.address().port;let child,launched=false;
 const scope=createHostedBrowserScope({
  spawnServer:port=>{child=spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:String(port)},stdio:['ignore','pipe','pipe']});child.stderr.resume();return child;},
  launchBrowser:async()=>{launched=true;throw new Error('must not launch');},
 });
 try{
  await assert.rejects(scope({port},()=>{}),error=>reasons(error).some(reason=>/exited unexpectedly/.test(String(reason))));
  assert.equal(launched,false);assert.ok(child.exitCode!==null||child.signalCode!==null);assert.equal(await(await fetch(`http://127.0.0.1:${port}/`)).text(),'other scope');
 }finally{listener.closeAllConnections();await new Promise(resolve=>listener.close(resolve));}
});


test('observer initialization failure still closes owned browser/context/server',async()=>{
 const failure=new Error('observation initialization');
 const h=setup({observeBrowser:async()=>{throw failure;}});let invoked=false;
 await assert.rejects(h.scope({port},()=>{invoked=true;}),error=>error===failure);
 assert.equal(invoked,false);assert(h.events.includes('context.close'));assert(h.events.includes('browser.close'));assert.equal(h.child.signalCode,'SIGTERM');
});

test('observer failure remains separate from assertion and later cleanup failures',async()=>{
 const monitor=new Error('observation failed'),body=new Error('contract assertion'),close=new Error('context close');
 let stopped=false;
 const h=setup({contextClose:close,observeBrowser:async()=>({stop:async()=>{stopped=true;throw monitor;}})});
 await assert.rejects(h.scope({port},()=>{throw body;}),error=>{assert.deepEqual(reasons(error),[body,monitor,close]);return true;});
 assert(stopped);assert.equal(h.child.signalCode,'SIGTERM');
});

test('reveal one control opens all its disclosure ancestors only',async()=>{
 const unrelated={tagName:'DETAILS',open:false};
 const outer={tagName:'DETAILS',open:false,parentElement:null};
 const inner={tagName:'DETAILS',open:false,parentElement:outer};
 const control={closest:()=>null,parentElement:{tagName:'LABEL',parentElement:inner}};
 await revealFormControl({locator:selector=>{assert.equal(selector,'#memory-mode');return {evaluate:async run=>run(control)};}},'#memory-mode');
 assert.equal(outer.open,true);assert.equal(inner.open,true);assert.equal(unrelated.open,false);
});

test('reveal an editor control switches from execution before opening disclosures',async()=>{
 const document={body:{dataset:{workspaceView:'execution'}}},events=[];
 const details={tagName:'DETAILS',open:false,parentElement:null};
 const control={closest:selector=>{assert.equal(selector,'.editor');return {};},parentElement:details};
 const page={
  locator:selector=>selector==='#memory-mode'?{evaluate:async run=>vm.runInNewContext(`(${run})(control)`,{control,document})}:{click:async()=>{
   assert.equal(selector,'.workspace-view-controls [data-workspace-view="configuration"]');
   events.push('configuration');document.body.dataset.workspaceView='configuration';
  }},
  waitForFunction:async run=>assert.equal(vm.runInNewContext(`(${run})()`,{document}),true),
 };
 await revealFormControl(page,'#memory-mode');
 assert.deepEqual(events,['configuration']);assert.equal(details.open,true);
 await revealFormControl(page,'#memory-mode');assert.deepEqual(events,['configuration']);
});

function terminalDocument(status,text,error='',hidden=true){
 const elements={status:{textContent:status},'result-path':{textContent:text},error:{textContent:error,hidden}};
 return {getElementById:id=>elements[id]??null};
}
test('changed stale completion wording and old failures cannot finish a new request',()=>{
 const old={serial:1,folder:'chopper-results-old',error:null};
 const doc=terminalDocument('COMPLETE','Draft changed. Last completed result folder: parent/chopper-results-old.');
 assert.equal(freshDirectRunTerminal(2,doc,old),false);
 assert.equal(freshDirectRunTerminal(2,doc,null),false);
 assert.equal(freshDirectRunTerminal(2,doc,{serial:2,folder:'chopper-results-new',error:null}),false);
 const failed=terminalDocument('FAILED','','Error: old checksum failure',false);
 assert.equal(freshDirectRunTerminal(2,failed,{serial:1,folder:'chopper-results-old',error:'old checksum failure'}),false);
 assert.equal(freshDirectRunTerminal(2,failed,null),false);
});
test('current reply must match the displayed completed folder or failure',()=>{
 const success={serial:2,folder:'chopper-results-new',error:null};
 assert.deepEqual(freshDirectRunTerminal(2,terminalDocument('COMPLETE','Complete. parent/chopper-results-new'),success),{status:'complete',folder:'chopper-results-new'});
 assert.equal(freshDirectRunTerminal(2,terminalDocument('RUNNING','parent/chopper-results-new'),success),false);
 const failure={...success,error:'new checksum failure'};
 assert.equal(freshDirectRunTerminal(2,terminalDocument('FAILED','','Error: old failure',false),failure),false);
 assert.equal(freshDirectRunTerminal(2,terminalDocument('FAILED','','Error: new checksum failure',true),failure),false);
 assert.deepEqual(freshDirectRunTerminal(2,terminalDocument('FAILED','','Error: new checksum failure',false),failure),{status:'failed',error:'new checksum failure'});
});
function workerProbe(){
 class Worker{
  constructor(...args){this.args=args;this.sent=[];this.listeners=[];}
  addEventListener(type,listener){assert.equal(type,'message');this.listeners.push(listener);}
  postMessage(data,transfer){this.sent.push({data,transfer});}
  emit(data){for(const listener of this.listeners)listener({data});}
  terminate(){this.terminated=true;}
 }
 const host={Worker,observationDisabled:false};installGraphWorkerProbe(host);return host;
}
test('worker reply correlation ignores progress and stale replies with reused request IDs',()=>{
 const host=workerProbe(),first=new host.Worker('/engine-worker.js',{type:'module'}),second=new host.Worker('/engine-worker.js');
 assert.deepEqual(first.args,['/engine-worker.js',{type:'module'}]);
 first.postMessage({id:7,type:'run-direct',folder:'chopper-results-old'});
 second.postMessage({id:7,type:'run-direct',folder:'chopper-results-new'});
 first.emit({id:7,result:{}});assert.equal(host.graphRunTerminal,null);
 second.emit({id:7,progress:{rows:1}});assert.equal(host.graphRunTerminal,null);
 second.emit({id:7,result:{}});assert.deepEqual(host.graphRunTerminal,{serial:2,folder:'chopper-results-new',error:null});
 first.emit({id:7,error:'old failure'});assert.equal(host.graphRunTerminal.serial,2);
 first.terminate();second.terminate();assert.equal(host.graphWorkers.size,0);
});
test('probe retains credit control and ignores replies after owned worker termination',()=>{
 const host=workerProbe(),worker=new host.Worker('/engine-worker.js'),credit={},transfer=[];
 host.observationDisabled=true;
 const data={id:1,type:'run-direct',folder:'chopper-results-new',observationCredit:credit};worker.postMessage(data,transfer);
 assert.equal(data.observationCredit,credit);assert.equal(worker.sent[0].data.observationCredit,undefined);assert.equal(worker.sent[0].transfer,transfer);
 assert.throws(()=>worker.postMessage({id:2,type:'run-direct',folder:'chopper-results-extra'}),/Overlapping/);
 assert.equal(host.graphRunSerial,1);
 worker.terminate();worker.emit({id:1,error:'late'});assert.equal(host.graphRunTerminal,null);assert.equal(host.graphWorkers.size,0);
});
