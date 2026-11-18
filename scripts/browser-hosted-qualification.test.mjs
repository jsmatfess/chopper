// Fake-only admission/outcome controls. No Playwright import, fixtures or Run.
import assert from 'node:assert/strict';
import test from 'node:test';
import {validateScaleFixture, qualifyFailure} from './scale_acceptance/browser-scale-driver.mjs';
const GiB=1024**3;

test('full-controller qualification changes only explicit fixture counts',()=>{
 for(const [shape,width] of [['D',100],['G',1000]]){
  const p={mode:'qualify',shape,fixture:{width,rows:127,bytes:128*width,sha256:'synthetic'}};
  const f={...p.fixture,shape,runtime:'browser',tiny:true,generator:'release-acceptance-v1'};
  validateScaleFixture(f,p);
  for(const mutate of [p=>p.mode='scale',p=>p.fixture.rows=128,p=>p.fixture.bytes=1_000_000_000]){
   const changed=structuredClone(p);mutate(changed);assert.throws(()=>validateScaleFixture(f,changed));
  }
  assert.throws(()=>validateScaleFixture({...f,tiny:false},p));
 }
});

test('controlled failure traverses public Run and cancellation before the empty-output census',async()=>{
 const calls=[],records=[];
 const page={async evaluate(fn,arg){
  calls.push(arg?'run':fn.toString().includes('incomplete')?'census':'cancel');
  if(arg){assert.equal(arg.limits.bytes,1);return;}
  if(fn.toString().includes('incomplete'))return {entries:[],workspaces:[],locks:[]};
 }};
 const sample=async()=>({sampled_unix:Date.now()/1000,usable_bytes:16*GiB,status:'failed',error:'header/BOM exceeds output byte limit'});
 const result=await qualifyFailure(page,{limits:{bytes:10_000_000,rows:1_000_000}},sample,async(name,value)=>records.push(name));
 assert.deepEqual(calls,['run','cancel','census']);
 assert.deepEqual(records,['controlled-failure.json','controlled-failure-cleanup.json']);
 assert.equal(result.expected_status,'failed');
});

for(const fault of ['wrong-error','complete','marker','workspace','lock'])test('failure qualification denies '+fault,async()=>{
 const cleanup={entries:[],workspaces:[],locks:[]};
 if(fault==='marker')cleanup.entries.push('CHOPPER-COMPLETE.json');
 if(fault==='workspace')cleanup.workspaces.push('unfinished');
 if(fault==='lock')cleanup.locks.push('chopper-held');
 const page={async evaluate(fn,arg){if(!arg&&fn.toString().includes('incomplete'))return cleanup;}};
 const sample=async()=>({sampled_unix:Date.now()/1000,usable_bytes:16*GiB,
  status:fault==='complete'?'complete':'failed',error:fault==='wrong-error'?'other failure':'header/BOM exceeds output byte limit'});
 await assert.rejects(qualifyFailure(page,{limits:{bytes:100}},sample,async()=>{}));
});
