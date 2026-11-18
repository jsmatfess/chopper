// Test-only evidence lifetime shared by the page and fixture-free fault tests.
export function records(){
  const pending=new Map();
  return {
    retain(id,record){if(pending.has(id))throw new Error('unacknowledged attempt record');pending.set(id,record);return record;},
    get(id){return pending.get(id);},
    acknowledge(id){if(!pending.has(id))throw new Error('unknown acknowledgement');pending.delete(id);}
  };
}
export async function disposeVerified(record,{dispose,inventory,workspace,check,now=()=>performance.now()}){
  record.disposal={state:'not-started'};
  record.secondary_errors??=[];
  try{
    record.disposal.state='in-progress-uncertain';
    await dispose();record.disposal.state='removed-inventory-unverified';
    record.post_disposal_inventory=await inventory();
    await check(record.post_disposal_inventory,await workspace());
    record.disposal.state='removed-verified';record.destination_retained=false;
    record.outer_finished_epoch_ms=performance.timeOrigin+now();
    record.outer_complete_job_seconds=(record.outer_finished_epoch_ms-record.primary_started_epoch_ms)/1000;
    return record;
  }catch(error){
    record.ok=false;record.error=String(error);record.destination_retained=null;
    try{record.failure_inventory=await inventory();}catch(secondary){record.secondary_errors.push({stage:'failure-inventory',error:String(secondary)});}
    return record;
  }
}
export function attemptDeadline(milliseconds,{now=()=>performance.now(),set=setTimeout,clear=clearTimeout}={}){
  const expires=now()+milliseconds;
  return {expires,async run(call){
    const remaining=expires-now();if(remaining<=0)throw new Error('attempt deadline expired');
    let timer;
    try{return await Promise.race([Promise.resolve().then(call),new Promise((_,reject)=>{timer=set(()=>reject(new Error('attempt deadline expired')),remaining);})]);}
    finally{clear(timer);}
  }};
}
