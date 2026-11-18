import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {closeOwnedRuntime,stopServer} from './e1-followup-runtime.mjs';
let passed=0;async function test(name,fn){await fn();passed++;console.log(JSON.stringify({passed:name}));}
const identity={ProcessId:12345,CreationDate:'original',ExecutablePath:'owned',CommandLine:'profile'};
await test('close timeout preserves identity through verified stop and observed exit',async()=>{
 let connected=true,killed=false,retained;
 const owner={pid:12345,identity,context:{close:()=>new Promise(()=>{})},browser:{isConnected:()=>connected,close:async()=>{connected=false;}}};
 await assert.rejects(closeOwnedRuntime(owner,{milliseconds:5,inspect:()=>{retained=owner.context;return killed?null:identity;},kill:pid=>{assert.equal(pid,12345);assert(retained);killed=true;},pause:async()=>{}}),e=>{assert.equal(e.secondary[0].stage,'context-close');assert.equal(e.ownership.exit_observed,true);return true;});
 assert(killed);assert.equal(owner.exit_observed,true);assert.equal(owner.context,null);
});
await test('PID reuse refuses kill and preserves ownership handles',async()=>{
 const context={close:async()=>{}},owner={pid:12345,identity,context,browser:{isConnected:()=>false}};let killed=false;
 await assert.rejects(closeOwnedRuntime(owner,{inspect:()=>({...identity,CreationDate:'new'}),kill:()=>{killed=true;}}),/identity changed/);assert(!killed);assert.equal(owner.context,context);assert(!owner.exit_observed);
});
await test('owned server stop records observed close independently',async()=>{
 const server=new EventEmitter();Object.assign(server,{pid:12346,exitCode:null,signalCode:null,kill(){queueMicrotask(()=>{server.exitCode=0;server.emit('close',0,null);});return true;}});
 const record=await stopServer(server,{milliseconds:5});assert.equal(record.exit_observed,true);assert.equal(record.code,0);
});
await test('server stop timeout retains primary failure after bounded fallback exit',async()=>{
 const server=new EventEmitter();Object.assign(server,{pid:12346,exitCode:null,signalCode:null,kill(signal){if(signal==='SIGKILL')queueMicrotask(()=>{server.signalCode=signal;server.emit('close',null,signal);});return true;}});
 await assert.rejects(stopServer(server,{milliseconds:5}),e=>{assert.match(e.message,/deadline/);assert.equal(e.shutdown.exit_observed,true);assert.equal(e.shutdown.fallback_stop_requested,true);return true;});
});
console.log(JSON.stringify({passed,browser_jobs:0}));
