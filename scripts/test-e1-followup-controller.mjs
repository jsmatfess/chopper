import assert from 'node:assert/strict';
import {executeSchedule,saveAcknowledged,shutdown,deadline} from './e1-followup-controller.mjs';
import {records,disposeVerified,attemptDeadline} from '../ui/tests/e1-followup-record.mjs';
import {schedule,blockProof,retainedOwners} from '../ui/tests/e1-followup-verifier.mjs';
let tests=0;
async function test(name,fn){await fn();tests++;console.log(JSON.stringify({passed:name}));}
function controller(failAt=Infinity){
 const calls=[],ledger={attempts:0};let identity=0;
 const dependencies={admit:async s=>calls.push(['admit',s]),navigate:async s=>{identity++;calls.push(['navigate',s]);},identity:async()=>identity,
 record:async x=>calls.push(['record',x]),invoke:async s=>{calls.push(['invoke',s,identity]);if(ledger.attempts===failAt)throw Error('injected invocation failure');return {ok:true};},
 save:async()=>{},ack:async()=>{},retrieve:async()=>({verified:true}),failure:async x=>calls.push(['failure',x]),stop:async()=>calls.push(['stop'])};
 return {calls,ledger,dependencies};
}
await test('admission refuses before side effects',async()=>{const c=controller();await assert.rejects(executeSchedule(c),/not admitted/);assert.equal(c.calls.length,0);});
await test('exact fixed order, counts, same-client adjacent MINIMAL cap retries',async()=>{
 const c=controller();await executeSchedule({...c,admitted:true});const invokes=c.calls.filter(x=>x[0]==='invoke');
 assert.equal(c.ledger.attempts,44);assert.equal(invokes.length,44);assert.equal(c.calls.filter(x=>x[0]==='navigate').length,42);
 for(let i=0;i<44;i++){const expected=schedule()[i];assert.deepEqual(invokes[i][1],{...expected,cap:expected.phase==='cap-rejection'?1000000:undefined});}
 for(const i of [8,10]){assert.equal(invokes[i][2],invokes[i+1][2]);assert.equal(invokes[i+1][1].mode,'MINIMAL');assert.equal(invokes[i+1][1].cap,undefined);assert.equal(invokes[i+1][1].shape,'rare_wide');}
 const measurement=invokes.slice(12).map(x=>[x[1].repetition,x[1].shape,x[1].mode,x[1].variant]);
 const expected=[];for(let r=1;r<=4;r++)for(const shape of r%2?['rare_wide','columns']:['columns','rare_wide'])for(const mode of r===1||r===4?['MINIMAL','FULL']:['FULL','MINIMAL'])for(const variant of r%2?['baseline','candidate']:['candidate','baseline'])expected.push([r,shape,mode,variant]);
 assert.deepEqual(measurement,expected);
});
await test('failed attempt charged, stop, no replacement or restart',async()=>{const c=controller(10);await assert.rejects(executeSchedule({...c,admitted:true}),/injected invocation/);assert.equal(c.ledger.attempts,10);assert.equal(c.calls.filter(x=>x[0]==='invoke').length,10);assert.deepEqual(c.calls.slice(-2).map(x=>x[0]),['stop','failure']);await assert.rejects(executeSchedule({...c,admitted:true}),/cannot restart/);});
await test('admission failure consumes no browser attempt',async()=>{const c=controller();c.dependencies.admit=async()=>{throw Error('budget refusal');};await assert.rejects(executeSchedule({...c,admitted:true}),/budget refusal/);assert.equal(c.ledger.attempts,0);});
for(const stage of ['return','save','ack'])await test(stage+' fault retains verified retrievable record and classifies failed',async()=>{
 const store=records(),record=store.retain('a',{verified:true,hashes:{csv:'exact'},primary_started_epoch_ms:1,primary_finished_epoch_ms:2,outer_finished_epoch_ms:3});let failure;
 await assert.rejects(saveAcknowledged({invoke:async()=>{if(stage==='return')throw Error('transport');return record;},retrieve:async()=>store.get('a'),save:async()=>{if(stage==='save')throw Error('save');},ack:async()=>{if(stage==='ack')throw Error('ack');store.acknowledge('a');},fail:async x=>{failure=x;}}));
 assert.equal(failure.failed,true);assert.deepEqual(store.get('a'),record);assert.deepEqual(failure.retained.hashes,{csv:'exact'});
});
await test('successful save precedes acknowledgement',async()=>{const store=records(),record=store.retain('a',{verified:true});let saved=false;await saveAcknowledged({invoke:async()=>record,retrieve:async()=>store.get('a'),save:async()=>{saved=true;},ack:async()=>{assert(saved);store.acknowledge('a');},fail:async()=>{throw Error('unexpected');}});assert.equal(store.get('a'),undefined);});
for(const stage of ['dispose','inventory','workspace','check'])await test(stage+' fault preserves verified metadata and uncertain disposal',async()=>{
 const store=records(),record=store.retain('a',{ok:true,hashes:{csv:'exact'},primary_started_epoch_ms:1});
 const fail=async()=>{throw Error('injected '+stage);};
 await disposeVerified(record,{dispose:stage==='dispose'?fail:async()=>{},inventory:stage==='inventory'?fail:async()=>[],workspace:stage==='workspace'?fail:async()=>[],check:stage==='check'?fail:async()=>{}});
 assert.equal(record.ok,false);assert.match(record.error,new RegExp(stage));assert.equal(record.destination_retained,null);assert.equal(store.get('a').hashes.csv,'exact');
 if(stage==='inventory')assert.equal(record.secondary_errors[0].stage,'failure-inventory');
});
await test('all shutdown actions run despite context close failure',async()=>{const errors=[],calls=[];await shutdown([['context',async()=>{calls.push('context');throw Error('context');}],['server',async()=>{calls.push('server');throw Error('server');}]],errors);assert.deepEqual(calls,['context','server']);assert.deepEqual(errors.map(x=>x.stage),calls);});
for(const make of [deadline,attemptDeadline]){
 await test('single deadline never resets between stages',async()=>{let now=0;const timers=[];const b=make(300000,{now:()=>now,set:(fn,ms)=>{timers.push(ms);return 0;},clear:()=>{}});await b.run(async()=>{now=299995;});await b.run(async()=>{now=300000;});await assert.rejects(b.run(async()=>{}),/deadline expired/);assert.deepEqual(timers,[300000,5]);});
 await test('hung awaited API times out',async()=>{await assert.rejects(make(5).run(()=>new Promise(()=>{})),/deadline expired/);});
}
await test('watchdog timeout consumes attempt and stops',async()=>{const c=controller();c.dependencies.invoke=()=>new Promise(()=>{});await assert.rejects(executeSchedule({...c,admitted:true,attemptMilliseconds:5}),/deadline expired/);assert.equal(c.ledger.attempts,1);assert.deepEqual(c.calls.slice(-2).map(x=>x[0]),['stop','failure']);});
for(const stage of ['admit','navigate','identity','record'])await test(stage+' setup fault stops and durably records charge',async()=>{
 const c=controller();const original=c.dependencies[stage];let calls=0;
 c.dependencies[stage]=async(...args)=>{calls++;if(calls===(stage==='admit'?2:1))throw Error('injected '+stage);return original(...args);};
 let failure;const originalFailure=c.dependencies.failure;c.dependencies.failure=async x=>{failure=structuredClone(x);await originalFailure(x);};
 await assert.rejects(executeSchedule({...c,admitted:true}),new RegExp('injected '+stage));
 assert.equal(c.calls.filter(x=>x[0]==='stop').length,1);assert.equal(failure.charged,stage==='record');
 assert.equal(c.ledger.attempts,stage==='record'||stage==='admit'?1:0);
});
await test('stop and failure-save secondary errors reach fallback',async()=>{
 const c=controller(1);let raw;c.dependencies.stop=async()=>{throw Error('stop failed');};c.dependencies.failure=async x=>{assert.equal(x.secondary[0].stage,'stop');throw Error('save failed');};c.dependencies.fallback=async x=>{raw=structuredClone(x);};
 await assert.rejects(executeSchedule({...c,admitted:true}),/injected invocation/);assert.deepEqual(raw.secondary.map(x=>x.stage),['stop','retain-failure']);
});
for(const stage of ['save','fail','ack'])await test('CLI transport '+stage+' hang/loss is bounded and retains exact record',async()=>{
 const store=records(),record=store.retain('a',{hashes:{csv:'exact'},memberships:[1],manifest:'raw',disposal:{state:'removed-verified'},primary_started_epoch_ms:1,outer_finished_epoch_ms:2});let raw;
 await assert.rejects(saveAcknowledged({transportMilliseconds:5,invoke:async()=>record,retrieve:async()=>store.get('a'),save:stage==='save'?()=>new Promise(()=>{}):async()=>{},ack:async()=>{if(stage==='fail'||stage==='ack')throw Error('acknowledgement lost');store.acknowledge('a');},fail:stage==='fail'?()=>new Promise(()=>{}):async x=>{raw=structuredClone(x);},fallback:async x=>{raw=structuredClone(x);}}));
 assert.deepEqual(store.get('a'),record);assert.deepEqual(raw.retained,record);if(stage==='fail')assert.equal(raw.secondary[0].stage,'failure-save');
});
await test('block proof safe integer schema including successes and pauses',async()=>{
 const d={compact_spill_files:1,compact_spill_blocks:1,compact_spill_rows:128,compact_spill_fallbacks:0,compact_spill_source_bytes:10,compact_spill_stored_bytes:8};blockProof({diagnostics:d});
 for(const key of Object.keys(d))for(const value of [undefined,null,NaN,Infinity,-1,0.5,'1',{},[]])assert.throws(()=>blockProof({diagnostics:{...d,[key]:value}}));
 for(const key of ['compact_spill_files','compact_spill_blocks','compact_spill_rows'])assert.throws(()=>blockProof({diagnostics:{...d,[key]:0}}));
 assert.throws(()=>blockProof({diagnostics:{...d,compact_spill_fallbacks:1}}));assert.throws(()=>blockProof(null));
});
await test('optional audit absent, valid present and malformed fixtures retain eleven-owner equation',async()=>{
 const keys=['temporary_path_reserved_bytes','directory_path_reserved_bytes','input_header_reserved_bytes','prepared_job_reserved_bytes','analysis_preview_reserved_bytes','column_values_reserved_bytes','stage_stats_reserved_bytes','analysis_text_reserved_bytes','analysis_warnings_reserved_bytes','analysis_timings_reserved_bytes','analysis_diagnostics_reserved_bytes'];
 const d=Object.fromEntries(keys.map(k=>[k,1]));d.workspace_reserved_bytes=11;retainedOwners(d);
 const audit={version:1,policy:'experiment_gate_v1',capacity:16,selector:null,calibration:null,initialized:true,collection_denied:false,reserved_bytes:64,records:[],omitted_attempts:0,completed_attempts:0};
 retainedOwners({...d,workspace_reserved_bytes:75,shuffle_partition_decisions:audit});
 for(const [key,value] of [['version',2],['policy','wrong'],['capacity',15],['selector',{}],['calibration',{}],['initialized',null],['collection_denied',null],['reserved_bytes',-1],['records',null],['omitted_attempts',NaN],['completed_attempts',1]])assert.throws(()=>retainedOwners({...d,workspace_reserved_bytes:75,shuffle_partition_decisions:{...audit,[key]:value}}));
 assert.throws(()=>retainedOwners({...d,shuffle_partition_decisions:audit}));
});
console.log(JSON.stringify({passed:tests,executed_browser_jobs:0,full_size_admitted:false}));
