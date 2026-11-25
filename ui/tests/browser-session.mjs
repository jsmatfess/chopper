import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const compiled=await build({entryPoints:['src/browser/session.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {BrowserLifecycle}=await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const job=()=>({operations:[],compression:'none',output_csv:{encoding:'utf-8',headers:true},resources:{temp_dir:null},limits:{rows:2,bytes:30}});
function harness(options={}){
  const workers=[],timers=new Map();let locks=0,serial=0,history=null;
  class FakeWorker {
    constructor(path){this.path=path;this.messages=[];workers.push(this);if(options.constructFailure?.(path))throw new Error('worker construction failed');}
    terminate(){this.stopped=true;}
    postMessage(data){
      if(options.sendFailure?.(this,data))throw new Error('send failed');
      this.messages.push(data.job?{...data,job:structuredClone(data.job)}:data);
      if(data.type==='init'&&!options.deferInit?.(this))queueMicrotask(()=>this.reply(this.path.includes('storage')?{ready:true}:{id:data.id,result:{}}));
      if(data.type==='cleanup'&&!this.deferCleanup)queueMicrotask(()=>this.reply({cleaned:true}));
    }
    published(data){
      const request=this.messages.find(message=>message.id===data.id),output=request.output.name+'/'+request.folder;
      this.reply({...data,result:{...data.result,output,publication:{kind:'browser-completion-marker',version:1,folder:request.folder,files:2,marker:'CHOPPER-COMPLETE.json'}}});
    }
    reply(data){this.onmessage({data});}
  }
  const effects={supported(){},estimate:async()=>({quota:1024**3,usage:0}),
    lock:async(name,hold)=>{if(options.lockGate)await options.lockGate.promise;locks++;try{await hold();}finally{locks--;}},
    worker:path=>new FakeWorker(path),channel:()=>({port1:{},port2:{}}),shared:n=>new SharedArrayBuffer(n),uuid:()=>String(++serial),
    timeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),diagnostic(){},historyChanged:value=>{history=value;},...options.effects};
  const lifecycle=new BrowserLifecycle(effects),file={name:'source.csv'},output={name:'destination'};
  lifecycle.selectInput(file);lifecycle.selectOutput(output);
  return {lifecycle,api:(...args)=>lifecycle.execute(...args),file,output,workers,timers,get locks(){return locks;},get history(){return history;}};
}

test('Analyze and Run lifecycle preserve results, late facts and overlapping cleanup',async()=>{
  const h=harness(),{api,file,output,workers}=h;
    const job={operations:[],compression:'none',output_csv:{encoding:'utf-8',headers:true},resources:{temp_dir:null},limits:{rows:2,bytes:30}};
    output.requestPermission=async()=> 'denied';
    await assert.rejects(api('run-direct',job),/permission was not granted/);
    assert.equal(workers.length,0);
    let grantPermission;
    output.requestPermission=()=>new Promise(resolve=>{grantPermission=resolve;});
    const waitingForPermission=api('run-direct',job);
    await api('cancel',{});grantPermission('granted');await waitingForPermission;
    assert.equal(workers.length,0);assert.equal((await api('state')).status,'cancelled');
    output.requestPermission=async()=> 'granted';
    const submitted=api('run-direct',job);job.limits.rows=77;await submitted;job.limits.rows=2;
    assert.equal((await api('state')).status,'running');
    let engine=workers.at(-1),request=engine.messages.at(-1);
    assert.equal(request.type,'run-direct');assert.equal(request.file,file);assert.equal(request.output,output);assert.deepEqual(request.job,job);
    engine.published({id:request.id,result:{analysis:{rows:3,output_files:2,warnings:[]},output:'destination/results'}});await tick();
    let state=await api('state');assert.equal(state.status,'complete');assert.equal(state.analysis.rows,3);assert.equal(h.locks,0);assert.ok(engine.stopped);
    await assert.rejects(api('analyze',job),/Unknown browser operation/);
    await assert.rejects(api('run',{}),/Unknown browser operation/);
    await api('profile',job);engine=workers.at(-1);request=engine.messages.at(-1);
    engine.reply({id:request.id,result:{rows:3}});await tick();assert.equal((await api('state')).status,'profiled');
    assert.equal((await api('state')).output,null);
    await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);
    engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/fresh'}});await tick();assert.equal((await api('state')).status,'complete');
    await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);
    engine.reply({exporting:request.folder});engine.reply({id:request.id,error:'marker close failed'});await tick();
    state=await api('state');assert.equal(state.status,'failed');assert.match(state.error,/marker close failed.*CHOPPER-COMPLETE/);assert.equal(state.analysis,null);assert.equal(h.locks,0);
    await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);await api('cancel',{});
    engine.published({id:request.id,result:{analysis:{rows:99,warnings:[]},output:'stale'}});await tick();
    state=await api('state');assert.equal(state.status,'cancelled');assert.equal(state.analysis,null);assert.equal(h.locks,0);
    const previousRun=request.observationRun;
    engine.reply({observationRun:previousRun,observationFinal:{export:{status:'completed',files:3},marker:{status:'completed'}}});assert.equal(h.history.steps.find(step=>step.id===3)?.status,'completed');assert.equal((await api('state')).status,'cancelled');
    const previousEngine=engine;await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);
    previousEngine.reply({observationRun:previousRun,observationFinal:{export:{status:'completed',files:999},marker:{status:'completed'}}});assert.equal(h.history.steps.find(step=>step.id===3),undefined);

    previousEngine.onerror({message:'late prior-generation worker error'});await tick();assert.equal((await api('state')).status,'running');
    previousEngine.reply({progress:{phase:'stale',rows:999,temp_bytes:0}});assert.notEqual((await api('state')).progress.rows,999);
    engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/fresh'}});await tick();assert.equal((await api('state')).status,'complete');assert.equal(h.locks,0);
    await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);const oldStorage=workers.at(-2);oldStorage.deferCleanup=true;
    engine.reply({id:request.id,error:'old Run failed'});await tick();assert.equal((await api('state')).status,'failed');
    await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);oldStorage.reply({error:'late cleanup failure'});await tick();state=await api('state');assert.equal(state.status,'running');assert.equal(state.error,null);
    engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/after-cleanup-race'}});await tick();assert.equal((await api('state')).status,'complete');assert.equal(h.locks,0);
    for(const sourceMode of ['direct','analyzed'])for(const cleanupError of [false,true]){
      await api(sourceMode==='direct'?'run-direct':'profile',job);engine=workers.at(-1);request=engine.messages.at(-1);
      if(sourceMode==='analyzed'){engine.reply({id:request.id,result:{rows:3}});await tick();await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);}
      const heldStorage=workers.at(-2);heldStorage.deferCleanup=true;
      engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/old-completed'}});await tick();assert.equal((await api('state')).status,'running');
      await api('cancel',{});await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);
      heldStorage.reply(cleanupError?{error:'old successful cleanup failed'}:{cleaned:true});await tick();state=await api('state');assert.equal(state.status,'running');assert.equal(state.error,null);assert.equal(state.analysis,null);
      engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/new-completed'}});await tick();assert.equal((await api('state')).status,'complete');assert.equal(h.locks,0);
    }
    for(const cleanupError of [false,true]){
      await api('run-direct',job);const heldStorage=workers.at(-2);heldStorage.deferCleanup=true;
      const firstCancel=api('cancel',{}).then(()=>null,error=>error);await tick();await api('cancel',{});assert.equal((await api('state')).status,'cancelled');
      await api('run-direct',job);engine=workers.at(-1);request=engine.messages.at(-1);heldStorage.reply(cleanupError?{error:'old cancellation cleanup failed'}:{cleaned:true});assert.equal(await firstCancel,null);state=await api('state');assert.equal(state.status,'running');assert.equal(state.error,null);
      engine.published({id:request.id,result:{analysis:{rows:3,warnings:[]},output:'destination/after-double-cancel'}});await tick();assert.equal((await api('state')).status,'complete');assert.equal(h.locks,0);
    }

});

for(const stage of ['lock','storage-construction','storage-init','engine-construction','engine-init','engine-send']){
  test(`startup ${stage} failure releases owned resources and allows retry`,async()=>{
    let fail=true;
    const h=harness({
      effects:{estimate:async()=>{if(fail&&stage==='quota')throw new Error('quota failed');return {quota:1024**3};},
        ...(stage==='lock'?{lock:async(_,hold)=>{if(fail)throw new Error('lock failed');return hold();}}:{})},
      constructFailure:path=>fail&&stage=== (path.includes('storage')?'storage-construction':'engine-construction'),
      deferInit:worker=>{
        if(fail&&stage===(worker.path.includes('storage')?'storage-init':'engine-init')){
          queueMicrotask(()=>worker.reply({id:worker.messages[0].id,error:'initialization failed'}));return true;
        }return false;
      },
      sendFailure:(worker,data)=>fail&&stage==='engine-send'&&worker.path.includes('engine')&&data.type==='init',
    });
    await assert.rejects(h.api('run-direct',job()),/failed/);await tick();
    assert.equal(h.lifecycle.snapshot().status,'failed');assert.equal(h.locks,0);assert.equal(h.timers.size,0);
    assert.ok(h.workers.every(w=>w.stopped||!w.messages.length));
    fail=false;await h.api('run-direct',job());assert.equal(h.lifecycle.snapshot().status,'running');
    await h.api('cancel');assert.equal(h.locks,0);
  });
}

for(const stage of ['lock','storage','engine']){
  test(`cancellation during ${stage} startup cannot resume into a replacement session`,async()=>{
    const gate=deferred();let deferredOnce=true;
    const h=harness({lockGate:stage==='lock'?gate:null,
      effects:stage==='quota'?{estimate:()=>{if(deferredOnce){deferredOnce=false;return gate.promise;}return Promise.resolve({quota:1024**3});}}:{},
      deferInit:worker=>deferredOnce&&worker.path.includes(stage),
    });
    const first=h.api('run-direct',job()).then(()=>null,error=>error);await tick();
    const oldWorkers=[...h.workers];
    await h.api('cancel');assert.equal(h.lifecycle.snapshot().status,'cancelled');assert.equal(h.locks,0);
    assert.match(String(await first),/Cancelled/);
    deferredOnce=false;
    // Lock acquisition may finish later, after cancel has already returned.
    gate.resolve({quota:1024**3});
    await h.api('run-direct',job());await tick();
    assert.equal(h.lifecycle.snapshot().status,'running');assert.equal(h.locks,1);
    for(const worker of oldWorkers){
      worker.reply(worker.path.includes('storage')?{ready:true}:{id:worker.messages[0].id,result:{}});
      if(worker.onerror)worker.onerror({message:'old startup error'});
    }
    await tick();assert.equal(h.lifecycle.snapshot().status,'running');assert.equal(h.locks,1);
    await h.api('cancel');assert.equal(h.locks,0);
  });
}

test('request send failure retires the failed Run; cancellation rejects every pending inspection',async()=>{
  let fail=true;
  const h=harness({sendFailure:(_,data)=>fail&&data.type==='run-direct'});
  assert.deepEqual(await h.api('run-direct',job()),{dispatched:false});await tick();
  assert.equal(h.lifecycle.snapshot().status,'failed');assert.match(h.lifecycle.snapshot().error,/send failed/);assert.equal(h.locks,0);
  fail=false;
  const a=h.api('columns',job()),b=h.api('sniff',job());
  const settled=Promise.allSettled([a,b]);await tick();
  assert.equal(h.workers.at(-1).messages.filter(m=>['columns','sniff'].includes(m.type)).length,2);
  await h.api('cancel');
  for(const result of await settled){assert.equal(result.status,'rejected');assert.match(String(result.reason),/Cancelled/);}
  assert.equal(h.locks,0);
});

test('cleanup timeout keeps its workspace locked until its own worker is terminated',async()=>{
  const h=harness();await h.api('run-direct',job());const storage=h.workers.at(-2);storage.deferCleanup=true;
  const cancelled=h.api('cancel');await tick();assert.equal(h.locks,1);assert.equal(storage.stopped,undefined);
  const timer=[...h.timers.values()][0];assert.equal(timer.ms,15000);timer.fn();await cancelled;await tick();
  assert.equal(h.locks,0);assert.equal(storage.stopped,true);assert.equal(h.timers.size,0);
  assert.equal(h.lifecycle.snapshot().status,'cancelled');assert.match(h.lifecycle.snapshot().error,/cleanup timed out/);
  await h.api('run-direct',job());const replacement=h.workers.at(-1);storage.reply({error:'late old cleanup'});
  assert.equal(h.lifecycle.snapshot().status,'running');assert.equal(replacement.stopped,undefined);
  await h.api('cancel');assert.equal(h.locks,0);
});

test('retired same-Run facts enrich retained history without acknowledging a replacement credit',async()=>{
  const h=harness();await h.api('run-direct',job());
  const old=h.workers.at(-1),run=old.messages.at(-1).observationRun;
  await h.api('cancel');await h.api('run-direct',job());
  const engine=h.workers.at(-1),request=engine.messages.at(-1),credit=new Int32Array(request.observationCredit);Atomics.store(credit,0,1);
  old.reply({observationRun:run,observation:{marker:{status:'completed'}}});assert.equal(Atomics.load(credit,0),1);
  old.reply({observationRun:request.observationRun,observation:{marker:{status:'completed'}}});assert.equal(Atomics.load(credit,0),1);
  assert.equal(h.lifecycle.snapshot().status,'running');
  engine.reply({observationRun:request.observationRun,observation:{read:{status:'active',rows:1}}});assert.equal(Atomics.load(credit,0),0);
  await h.api('cancel');
});

test('defaults, inspection and profiling reuse a session and invalidate profile cache for a new file',async()=>{
  const h=harness();await h.api('defaults');assert.equal(h.workers.length,2);
  const inspect=h.api('columns',job());await tick();let request=h.workers.at(-1).messages.at(-1);
  h.workers.at(-1).reply({id:request.id,result:{columns:['a']}});assert.deepEqual(await inspect,{columns:['a']});
  for(const reset of [true,false,true]){
    if(reset&&h.lifecycle.snapshot().status==='profiled')h.lifecycle.selectInput({name:'new.csv'});
    await h.api('profile',job());request=h.workers.at(-1).messages.at(-1);assert.equal(request.resetProfile,reset);
    h.workers.at(-1).reply({id:request.id,result:{rows:4}});await tick();assert.equal(h.lifecycle.snapshot().status,'profiled');
  }
  assert.equal(h.workers.length,2);assert.equal(h.locks,1);await h.api('cancel');assert.equal(h.locks,0);
});

for(const type of ['profile','columns','preview','sniff']){
  test(`${type} freezes submitted settings across startup waits`,async()=>{
    const gate=deferred(),h=harness({effects:{estimate:()=>gate.promise}}),submitted=job();
    const pending=h.api(type,submitted);submitted.limits.rows=999;gate.resolve({quota:1024**3});await tick();
    const engine=h.workers.at(-1),request=engine.messages.at(-1);assert.equal(request.job.limits.rows,2);
    engine.reply({id:request.id,result:{rows:3}});await pending;await tick();await h.api('cancel');assert.equal(h.locks,0);
  });
}

for(const workerType of ['storage','engine']){
  test(`post-start ${workerType} death fails outstanding work and retains lock until cleanup`,async()=>{
    const h=harness();await h.api('run-direct',job());
    const storage=h.workers.at(-2),engine=h.workers.at(-1);storage.deferCleanup=true;
    (workerType==='storage'?storage:engine).onerror({message:`${workerType} died`});await tick();
    assert.equal(h.lifecycle.snapshot().status,'failed');assert.match(h.lifecycle.snapshot().error,/died/);
    assert.equal(engine.stopped,true);assert.equal(h.locks,1);
    [...h.timers.values()][0].fn();await tick();assert.equal(storage.stopped,true);assert.equal(h.locks,0);
    await h.api('run-direct',job());assert.equal(h.lifecycle.snapshot().status,'running');await h.api('cancel');assert.equal(h.locks,0);
  });
}

for(const phase of ['idle','profiled'])for(const workerType of ['storage','engine']){
  test(`${workerType} failure while ${phase} retires the session without a pending request`,async()=>{
    const h=harness();await h.api('defaults');
    if(phase!=='idle'){
      await h.api('profile',job());
      const engine=h.workers.at(-1),request=engine.messages.at(-1);
      engine.reply({id:request.id,result:{rows:3}});await tick();
    }
    assert.equal(h.lifecycle.snapshot().status,phase);
    const storage=h.workers.at(-2),engine=h.workers.at(-1);storage.deferCleanup=true;
    (workerType==='storage'?storage:engine).onerror({message:`${workerType} died while ${phase}`});await tick();
    assert.equal(h.lifecycle.snapshot().status,'failed');assert.match(h.lifecycle.snapshot().error,/died while/);
    assert.equal(engine.stopped,true);assert.equal(h.locks,1);
    storage.reply({cleaned:true});await tick();assert.equal(storage.stopped,true);assert.equal(h.locks,0);
    await h.api('run-direct',job());const replacement=h.workers.at(-1);
    engine.onerror({message:'late retired engine failure'});await tick();
    assert.equal(h.lifecycle.snapshot().status,'running');assert.equal(replacement.stopped,undefined);
    await h.api('cancel');assert.equal(h.locks,0);
  });
}

for(const type of ['columns','sniff'])for(const workerType of ['storage','engine']){
  test(`${workerType} failure during ${type} rejects inspection and permits a replacement`,async()=>{
    const h=harness();await h.api('defaults');
    const pending=h.api(type,job()),rejection=assert.rejects(pending,/inspection worker died/);await tick();
    const storage=h.workers.at(-2),engine=h.workers.at(-1);
    (workerType==='storage'?storage:engine).onerror({message:'inspection worker died'});
    await rejection;await tick();
    assert.equal(h.lifecycle.snapshot().status,'failed');assert.equal(engine.stopped,true);assert.equal(storage.stopped,true);assert.equal(h.locks,0);
    await h.api('run-direct',job());assert.equal(h.workers.length,4);assert.equal(h.lifecycle.snapshot().status,'running');
    await h.api('cancel');assert.equal(h.locks,0);
  });
}

for(const type of ['columns','sniff']){
  test(`${type} send failure retires its session`,async()=>{
    const h=harness({sendFailure:(_,data)=>data.type===type});await h.api('defaults');
    await assert.rejects(h.api(type,job()),/send failed/);await tick();
    assert.equal(h.lifecycle.snapshot().status,'failed');assert.equal(h.locks,0);assert.ok(h.workers.every(w=>w.stopped));
    await h.api('run-direct',job());assert.equal(h.workers.length,4);assert.equal(h.lifecycle.snapshot().status,'running');
    await h.api('cancel');assert.equal(h.locks,0);
  });
}

test('Run permission denial preserves input analysis; cancellation invalidates a pending grant',async()=>{
  const h=harness();await h.api('profile',job());const engine=h.workers.at(-1),request=engine.messages.at(-1);
  engine.reply({id:request.id,result:{rows:3}});await tick();
  h.output.requestPermission=async()=> 'denied';await assert.rejects(h.api('run-direct',job()),/permission was not granted/);
  assert.equal(h.lifecycle.snapshot().status,'profiled');assert.equal(engine.stopped,undefined);assert.equal(h.locks,1);
  const permission=deferred();h.output.requestPermission=()=>permission.promise;
  const pending=h.api('run-direct',job());await tick();await h.api('cancel');permission.resolve('granted');await pending;
  assert.equal(h.lifecycle.snapshot().status,'cancelled');assert.equal(engine.messages.filter(m=>m.type==='run-direct').length,0);assert.equal(h.locks,0);
});

test('a delayed Run permission cannot replace profiling admitted during the wait',async()=>{
  const h=harness(),permission=deferred();h.output.requestPermission=()=>permission.promise;
  const waiting=h.api('run-direct',job());await h.api('profile',job());
  const engine=h.workers.at(-1),request=engine.messages.at(-1);permission.resolve('granted');
  await assert.rejects(waiting,/A job is active/);assert.equal(h.lifecycle.snapshot().status,'profiling');assert.equal(engine.stopped,undefined);
  engine.reply({id:request.id,result:{rows:3}});await tick();assert.equal(h.lifecycle.snapshot().status,'profiled');await h.api('cancel');assert.equal(h.locks,0);
});

test('a superseded permission-pending Run reports that it never dispatched',async()=>{
  const h=harness(),first=deferred(),second=deferred();
  h.output.requestPermission=()=>first.promise;
  const original=h.api('run-direct',job());
  h.output.requestPermission=()=>second.promise;
  const edited={...job(),limits:{rows:17}};
  const replacement=h.api('run-direct',edited);
  first.resolve('granted');
  assert.deepEqual(await original,{dispatched:true});
  second.resolve('granted');
  assert.deepEqual(await replacement,{dispatched:false});
  const requests=h.workers.flatMap(worker=>worker.messages.filter(message=>message.type==='run-direct'));
  assert.equal(requests.length,1);
  assert.notDeepEqual(requests[0].job,edited);
  await h.api('cancel');
});

test('Run freezes source and destination before permissions and never reuses analysis settings',async()=>{
  const h=harness(),permission=deferred();h.output.requestPermission=()=>permission.promise;
  const waiting=h.api('run-direct',job());
  h.lifecycle.selectInput({name:'replacement.csv'});h.lifecycle.selectOutput({name:'replacement folder'});permission.resolve('granted');await waiting;
  let engine=h.workers.at(-1),request=engine.messages.at(-1);assert.equal(request.file,h.file);assert.equal(request.output,h.output);
  engine.reply({exporting:request.folder});assert.equal(h.lifecycle.snapshot().output,'destination/'+request.folder);
  await h.api('cancel');
  h.lifecycle.selectInput(h.file);h.lifecycle.selectOutput(h.output);h.output.requestPermission=async()=> 'granted';
  await h.api('profile',job());engine=h.workers.at(-1);request=engine.messages.at(-1);
  engine.reply({id:request.id,result:{rows:3}});await tick();
  const fresh={name:'new selection'};h.lifecycle.selectOutput(fresh);
  const changed={...job(),limits:{rows:17}};
  await h.api('run-direct',changed);engine=h.workers.at(-1);request=engine.messages.at(-1);
  assert.equal(request.output,fresh);assert.deepEqual(request.job,changed);await h.api('cancel');assert.equal(h.locks,0);
});

for(const type of ['columns','preview'])test(`${type} freezes its selected source before startup`,async()=>{
  const gate=deferred(),h=harness({effects:{estimate:()=>gate.promise}});
  const pending=h.api(type,job());h.lifecycle.selectInput({name:'new.csv'});gate.resolve({quota:1024**3});await tick();
  const engine=h.workers.at(-1),request=engine.messages.at(-1);assert.equal(request.file,h.file);
  engine.reply({id:request.id,result:{columns:[]}});await pending;await h.api('cancel');assert.equal(h.locks,0);
});

 test('startup does not turn a quota estimate into a default temporary-space cap',async()=>{
  const h=harness({effects:{estimate:async()=>{throw Error('estimate unavailable');}}});
  await h.api('run-direct',job());
  for(const worker of h.workers)assert.equal(worker.messages[0].available,Number.MAX_SAFE_INTEGER);
  assert.equal(h.lifecycle.snapshot().status,'running');await h.api('cancel');
 });

test('completion rejects missing and mismatched publication receipts',async()=>{
 for(const publication of [undefined,{kind:'browser-completion-marker',version:1,folder:'older-run',files:2,marker:'CHOPPER-COMPLETE.json'}]){
  const h=harness();await h.api('run-direct',job());const engine=h.workers.at(-1),request=engine.messages.at(-1);
  engine.reply({id:request.id,result:{analysis:{rows:3,warnings:[]},output:request.output.name+'/'+request.folder,publication}});await tick();
  assert.equal(h.lifecycle.snapshot().status,'failed');assert.match(h.lifecycle.snapshot().error,/publication receipt/);assert.equal(h.locks,0);
 }
});
test('input analysis survives draft edits but a replacement input rejects its pending result',async()=>{
 const h=harness();await h.api('profile',job());let engine=h.workers.at(-1),request=engine.messages.at(-1);
 h.lifecycle.invalidateDraft();engine.reply({id:request.id,result:{rows:3}});await tick();
 assert.equal(h.lifecycle.snapshot().status,'profiled');assert.equal(h.lifecycle.snapshot().profile.rows,3);
 assert.equal(h.lifecycle.snapshot().origins.profile.revision,0);
 await h.api('profile',job());request=engine.messages.at(-1);h.lifecycle.selectInput({name:h.file.name});
 engine.reply({id:request.id,result:{rows:99}});await tick();assert.equal(h.lifecycle.snapshot().profile,null);assert.equal(h.lifecycle.snapshot().status,'idle');await h.api('cancel');
});
test('Analyze resets the row count before processing its input',async()=>{
 const h=harness();
 await h.api('profile',job());
 const engine=h.workers.at(-1),request=engine.messages.at(-1);
 engine.reply({progress:{phase:'Profiling all input records',rows:16384,temp_bytes:0}});
 engine.reply({id:request.id,result:{rows:16384}});await tick();
 assert.equal(h.lifecycle.snapshot().progress.rows,16384);
 await h.api('profile',job());
 assert.equal(h.lifecycle.snapshot().progress.rows,0);
 await h.api('cancel');
});
test('Run and cancellation keep source statistics until the input changes',async()=>{
 const h=harness();
 await h.api('profile',job());
 const engine=h.workers.at(-1),request=engine.messages.at(-1);
 const profile={rows:3,column_values:[{column:0,frequencies:{a:3}}]};
 engine.reply({id:request.id,result:profile});await tick();
 const changed={...job(),operations:[{type:'balanced',files:3}]};
 h.lifecycle.invalidateDraft();
 await h.api('run-direct',changed);
 assert.deepEqual(h.lifecycle.snapshot().profile,profile);
 await h.api('cancel');
 assert.deepEqual(h.lifecycle.snapshot().profile,profile);
 h.lifecycle.selectInput({name:h.file.name});
 assert.equal(h.lifecycle.snapshot().profile,null);
});
test('Run after analysis submits current source and revision, with no prepared handle',async()=>{
 const h=harness();await h.api('profile',job());let engine=h.workers.at(-1),request=engine.messages.at(-1);
 engine.reply({id:request.id,result:{rows:3}});await tick();
 const replacement={name:'replacement.csv'};h.lifecycle.selectInput(replacement);h.lifecycle.invalidateDraft();
 const changed={...job(),operations:[{type:'balanced',files:3}]};
 await h.api('run-direct',changed);engine=h.workers.at(-1);request=engine.messages.at(-1);
 assert.equal(request.file,replacement);assert.deepEqual(request.job,changed);
 assert.equal(h.lifecycle.snapshot().status,'running');assert.equal(h.lifecycle.snapshot().profile,null);
 await h.api('cancel');
});
