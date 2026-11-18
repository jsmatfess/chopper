import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';

test('worker publishes a newly started merge before synchronous processing finishes',async()=>{
 const compiled=await build({entryPoints:['src/browser/engine-worker.ts'],bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'worker-effects',setup(b){
  b.onResolve({filter:/browser_wasi_shim|^\.\/fs$|^\.\/export$/},a=>({path:a.path,namespace:'effects'}));
  b.onLoad({filter:/.*/,namespace:'effects'},a=>({contents:a.path.includes('shim')?`export class WASI {constructor(a,b,f){globalThis.workerStdout=f[1];this.wasiImport={};} initialize(){}};export class File {path_open(){return {fd_obj:{}}}};export const ConsoleStdout={lineBuffered:callback=>({callback})};`:a.path==='./fs'?`export class DiskBridge {constructor(){globalThis.workerBridge=this}};export class DiskDirectory {contents=new Map()};export class DiskFile {};export class RootFd {};`:`export async function exportResults(){return {}};`}));
 }}]});
 const original={performance:globalThis.performance,WebAssembly:globalThis.WebAssembly,fetch:globalThis.fetch,postMessage:globalThis.postMessage,onmessage:globalThis.onmessage};
 const sent=[],credit=new Int32Array(new SharedArrayBuffer(4));
 const fact=(kind,id,attempt,status)=>({physical:{kind,id,operations:[1,0],rows:0,seconds:0,status,source_omitted:true,attempt}});
 try{
  globalThis.performance={now:()=>1000};globalThis.fetch=()=>null;globalThis.postMessage=m=>sent.push(m);
  globalThis.WebAssembly={instantiateStreaming:async()=>({instance:{exports:{chopper_defaults(){},chopper_run(){
   workerStdout.callback(JSON.stringify(fact('spill',1040,1,'completed')));Atomics.store(credit,0,0);
   workerStdout.callback(JSON.stringify(fact('merge',1041,2,'active')));
   assert.ok(sent.some(m=>m.observation?.physical?.some(s=>s.kind==='merge'&&s.status==='active')),'active merge must reach page before merge completes');
   workerStdout.callback(JSON.stringify(fact('hierarchical_merge',1042,3,'active')));
   Atomics.store(credit,0,0);workerBridge.onActivity();
   assert.ok(sent.some(m=>m.observation?.physical?.some(s=>s.kind==='hierarchical_merge'&&s.status==='active')),'storage activity flushes a start queued behind page credit');
   throw new Error('probe complete');
  }}}})};
  await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
  await globalThis.onmessage({data:{id:1,type:'init',available:1e9}});
  await globalThis.onmessage({data:{id:2,type:'run-direct',file:{name:'test.csv'},job:{resources:{}},observationCredit:credit.buffer,observationRun:1}});
  assert.equal(sent.find(m=>m.id===2)?.error,'probe complete');
 }finally{Object.assign(globalThis,original);delete globalThis.workerStdout;delete globalThis.workerBridge;}
});
