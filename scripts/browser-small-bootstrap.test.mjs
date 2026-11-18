import test from 'node:test';
import assert from 'node:assert/strict';
import {handshake} from './browser-small-bootstrap.mjs';
import {smallLimits} from './browser-small-observer.mjs';
const packet={reservation:'held',batch_started_ms:9000,limits:smallLimits,volumes:['C:/']};
const guard=()=>({schema:'chopper-small-contract-guard-v1',allowed:true,sampled_ms:10000,last_progress_ms:9000,runner_pid:10,child_pid:20,owned_pids:[10,20],reservation:'held',reservation_held:true,windows_job_kill_on_close:true,batch_started_ms:9000,cumulative_owned_bytes:0,volumes:[{path:'C:/',free_bytes:200*1024**3,sampled_ms:10000}]});
test('same Node handshake waits for actual own PID heartbeat after pre-spawn null',async()=>{
 let reads=0,clock=10000;
 await handshake(packet,{pid:20,parent:10,now:()=>clock,pause:async ms=>{clock+=ms;},read:async()=>JSON.stringify({...guard(),child_pid:++reads<3?null:20})});
 assert.equal(reads,3);
});
test('handshake fails immediately for wrong PID/parent/census/Job/denial/stale/error',async()=>{
 for(const edit of [{child_pid:30},{runner_pid:30},{owned_pids:[10]},{windows_job_kill_on_close:false},{allowed:false},{error:'failed'},{sampled_ms:1},{reservation_held:false}]){
  await assert.rejects(handshake(packet,{pid:20,parent:10,now:()=>10000,read:async()=>JSON.stringify({...guard(),...edit})}));
 }
 for(const edit of [{windows_job_kill_on_close:false},{owned_pids:[]},{reservation:'wrong'},{sampled_ms:1}]){
  await assert.rejects(handshake(packet,{pid:20,parent:10,now:()=>10000,read:async()=>JSON.stringify({...guard(),child_pid:null,...edit})}));
 }
});
test('bounded startup denies absence, malformed JSON and blocked read',async()=>{
 let clock=10000;
 await assert.rejects(handshake(packet,{pid:20,parent:10,now:()=>clock,pause:async ms=>{clock+=ms;},read:async()=>{throw Object.assign(new Error('missing'),{code:'ENOENT'});}}),/five seconds/);
 await assert.rejects(handshake(packet,{read:async()=>'{'}));
 // A short fake clock deadline keeps this fake-only control fast.
 let times=0;
 await assert.rejects(handshake(packet,{now:()=>times++===0?0:4999,read:()=>new Promise(()=>{})}),/timed out/);
});
