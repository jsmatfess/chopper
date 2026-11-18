// Dependency-injected orchestration; this module launches no browser itself.
import assert from 'node:assert/strict';
import {schedule} from '../ui/tests/e1-followup-verifier.mjs';

export function deadline(milliseconds,{now=()=>performance.now(),set=setTimeout,clear=clearTimeout}={}){
  const expires=now()+milliseconds;
  return {expires,remaining:()=>Math.max(0,expires-now()),async run(call){
    const remaining=expires-now();assert(remaining>0,'attempt deadline expired');
    let timer;
    try{return await Promise.race([Promise.resolve().then(call),new Promise((_,reject)=>{timer=set(()=>reject(new Error('attempt deadline expired')),remaining);})]);}
    finally{clear(timer);}
  }};
}

export async function shutdown(actions,errors){
  for(const [stage,action] of actions)try{await action();}catch(error){errors.push({stage,error:String(error)});}
}

// A started/failed attempt is charged before execution. No replacement loop.
export async function executeSchedule({admitted=false,dependencies:d,ledger,ceiling=44,sessionMilliseconds=1800000,attemptMilliseconds=300000}){
  assert(admitted===true,'full-size schedule not admitted');
  assert(Number.isSafeInteger(ledger.attempts)&&ledger.attempts>=0&&ledger.attempts<=ceiling);
  assert(ledger.attempts===0,'interrupted fixed schedule cannot restart');
  const session=deadline(sessionMilliseconds,d.clock);
  let client,previous;
  for(const spec of schedule()){
    let attempt=null,charged=false;
    try{
    await session.run(()=>d.admit(spec));assert(ledger.attempts<ceiling,'attempt ceiling exhausted');
    if(spec.phase==='cap-retry'){
      assert(previous?.phase==='cap-rejection'&&previous.variant===spec.variant&&previous.mode==='MINIMAL'&&spec.mode==='MINIMAL','cap/retry adjacency changed');
      assert(client&&await session.run(()=>d.identity())===client,'cap/retry client identity changed');
    }else{await session.run(()=>d.navigate(spec));client=await session.run(()=>d.identity());}
    attempt=++ledger.attempts;charged=true;
    await deadline(10000,d.clock).run(()=>d.record({type:'attempt-start',attempt,spec,client}));
    const bound=deadline(Math.min(attemptMilliseconds,session.remaining()),d.clock);
      const result=await bound.run(()=>d.invoke({...spec,cap:spec.phase==='cap-rejection'?1000000:undefined},client));
      assert(result?.ok,result?.error||'attempt failed');
      assert(await bound.run(()=>d.identity())===client,'client identity changed');
      // Saving and acknowledging are controller transport, outside browser clocks.
      await deadline(10000,d.clock).run(()=>d.save(attempt,result));
      await deadline(10000,d.clock).run(()=>d.ack(attempt,result));
      await deadline(10000,d.clock).run(()=>d.record({type:'attempt-return',attempt,spec,client,ok:true}));
    }catch(error){
      ledger.failed=true;
      const secondary=[];let retained;
      await shutdown([['retrieve',async()=>{retained=await deadline(5000,d.clock).run(()=>d.retrieve());}]],secondary);
      await shutdown([['stop',()=>deadline(10000,d.clock).run(()=>d.stop())]],secondary);
      const record={attempt,charged,spec,client,error:String(error),retained,secondary};
      await shutdown([['retain-failure',()=>deadline(10000,d.clock).run(()=>d.failure(record))]],secondary);
      // A failed save cannot include its own failure. Emit a separate durable/raw
      // fallback after every secondary error has been collected.
      if(secondary.length){try{await deadline(10000,d.clock).run(()=>d.fallback?d.fallback(record):console.error(JSON.stringify(record)));}catch(fallback){secondary.push({stage:'fallback',error:String(fallback)});console.error(JSON.stringify(record));}}
      const failure=new Error(String(error));failure.secondary=secondary;failure.record=record;throw failure;
    }
    previous=spec;
  }
  return ledger;
}

export async function saveAcknowledged({invoke,retrieve,save,ack,fail,fallback=record=>console.error(JSON.stringify(record)),transportMilliseconds=10000,clock}){
  let result;
  const transport=call=>deadline(transportMilliseconds,clock).run(call);
  try{result=await invoke();await transport(()=>save(result));await transport(()=>ack(result));return result;}
  catch(primary){
    const secondary=[];
    try{result=await transport(()=>retrieve());}catch(error){secondary.push({stage:'retrieve',error:String(error)});}
    const record={primary:String(primary),secondary,retained:result,failed:true,transport_policy:{milliseconds:transportMilliseconds,scope:'raw-save/retrieve/ack/failure-save; outside browser clocks'}};
    try{await transport(()=>fail(record));}catch(error){secondary.push({stage:'failure-save',error:String(error)});}
    if(secondary.length)try{await transport(()=>fallback(record));}catch(error){secondary.push({stage:'fallback',error:String(error)});console.error(JSON.stringify(record));}
    const error=new Error(String(primary));error.secondary=secondary;error.record=record;throw error;
  }
}
