import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const bundle=await build({stdin:{contents:"export * from './src/browser/execution-history';export {PhysicalHistory} from './src/browser/physical-history';export * from './src/browser/execution-dag';export * from './src/browser/execution-timing';",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node'});
const {ExecutionHistory,ObservationDelivery,PhysicalHistory,ExecutionDag,edgePath,MAX_DAG_NODES,MAX_DAG_EDGES,DAG_PADDING,DAG_NODE_WIDTH,observedSources,displayStepStatus,describeStep,summarizeStep,measurementParts,observedStrategy,ExecutionTiming,MAX_TIMING_WINDOWS,TIMING_GAPS_PER_BLOCK,TimingGapWriter,TimingGapLog}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const job={operations:[],compression:'none',output_csv:{encoding:'utf-8',headers:true},limits:{rows:2,bytes:null,compressed_bytes:null}};
test('timeline retains first start and latest attempt end without drifting on duplicate terminals',(t)=>{
 let ms=100;t.mock.method(performance,'now',()=>ms);const gaps=[],timing=new ExecutionTiming((...gap)=>gaps.push(gap));
 timing.record(1000,'active',1);ms=1100;timing.record(1000,'completed',1);
 ms=3100;timing.record(1000,'active',2);ms=5100;timing.record(1000,'completed',2);
 assert.deepEqual(timing.snapshot(),[{step:1000,start:0,last:5,status:'completed'}]);
 assert.deepEqual(gaps,[[1000,1,3]]);
 ms=8100;timing.record(1000,'active',1);timing.record(1000,'completed',2);timing.record(1000,'active',2);
 assert.equal(timing.snapshot()[0].last,5);
 timing.record(1001,'completed',3);assert.equal(timing.snapshot()[1].start,null);
 timing.record(1001,'active',4);assert.equal(timing.snapshot()[1].start,null,'a later attempt cannot invent the first start');
 timing.record(0,'active');ms=9100;timing.record(0,'completed');ms=10100;timing.record(0,'completed');timing.record(0,'active');assert.equal(timing.snapshot()[2].last,9);
});
test('timeline retains every pause in fixed-size shared blocks even with observation credit held',t=>{
 let ms=0;t.mock.method(performance,'now',()=>ms);
 const credit=new Int32Array(new SharedArrayBuffer(4));Atomics.store(credit,0,1);
 const h=new ExecutionHistory(860,job),messages=[];
 const delivery=new ObservationDelivery(h.run,credit,value=>{messages.push(value);h.addTimingGapBlock(value.observationRun,value.timingGapBlock);});
 const count=TIMING_GAPS_PER_BLOCK+10;
 for(let attempt=1;attempt<=count+1;attempt++){
  const fact={id:1000,kind:'resident_sort',operations:[1,0],rows:0,seconds:0,attempt};
  delivery.recordPhysical({...fact,status:'active'});ms+=1000;
  delivery.recordPhysical({...fact,status:'completed'});ms+=1000;
 }
 assert.equal(messages.length,2);
 assert(messages.every(message=>message.timingGapBlock.byteLength===messages[0].timingGapBlock.byteLength));
 h.interrupt('interrupted');
 const gaps=h.timingGaps.byStep.get(1000);
 assert.equal(gaps.length,count);
 assert.deepEqual(gaps[0],[1,2]);assert.deepEqual(gaps.at(-1),[2*count-1,2*count]);
 assert.equal(h.timingGaps.read(Infinity),true);assert.equal(gaps.length,count);
});
test('paused readers consume entries only through the matching observation clock',()=>{
 const log=new TimingGapLog(),writer=new TimingGapWriter(buffer=>assert(log.add(buffer)));
 writer.record(1000,1,2);writer.record(1001,2,3);
 assert(log.read(2));assert.deepEqual(log.byStep.get(1000),[[1,2]]);assert.equal(log.byStep.has(1001),false);
 assert(log.read(3));assert.deepEqual(log.byStep.get(1001),[[2,3]]);
 assert.equal(log.add(new SharedArrayBuffer(8)),false);
});
test('timeline records an observed pause after an unknown start without inferring missing boundaries',t=>{
 let ms=0;t.mock.method(performance,'now',()=>ms);const gaps=[],timing=new ExecutionTiming((...gap)=>gaps.push(gap));
 timing.record(1000,'completed',1);ms=1000;timing.record(1000,'active',2);
 ms=2000;timing.record(1000,'active',3); // The preceding attempt's end was not observed.
 assert.deepEqual(timing.snapshot(),[{step:1000,start:null,last:2,status:'active'}]);
 assert.deepEqual(gaps,[[1000,0,1]]);
});
test('timeline has its own bounded capture beyond event saturation',(t)=>{
 let ms=0;t.mock.method(performance,'now',()=>ms);const d=new ObservationDelivery(850,new Int32Array(new SharedArrayBuffer(4)),()=>{});
 for(let id=1000;id<2152;id++){d.recordPhysical({id,kind:'resident_sort',operations:[1,0],status:'active',rows:0,seconds:0,attempt:id});ms++;d.recordPhysical({id,kind:'resident_sort',operations:[1,0],status:'completed',rows:1,seconds:.001,attempt:id});}
 for(const key of ['read','write','export','marker'])d.update({[key]:{status:'completed',seconds:1}});
 const snapshot=d.snapshot();assert.equal(snapshot.events.length,128);assert.equal(snapshot.timeline.length,MAX_TIMING_WINDOWS);assert(snapshot.timeline.some(w=>w.step===2151));assert(snapshot.timeline.every(w=>w.last<=snapshot.timeline_seconds));
 snapshot.timeline[0].last=999999;assert.notEqual(d.snapshot().timeline[0].last,999999);
});
test('timeline freezes on interruption or confirmed completion and rejects invalid coordinates',(t)=>{
 let ms=1000;t.mock.method(performance,'now',()=>ms);
 const h=new ExecutionHistory(851,job);h.accept(851,{read:{status:'active',rows:1,seconds:1},timeline:[{step:0,start:0,last:1,status:'active'}],timeline_seconds:1});
 ms=2000;assert.equal(h.timelineNow(),2);
 h.accept(851,{read:{status:'active',rows:1,seconds:1.5},timeline:[{step:0,start:0,last:1.5,status:'active'}],timeline_seconds:1.5});assert.equal(h.timelineNow(),2,'delivery latency does not move the live axis backward');
 h.interrupt('interrupted');ms=9000;assert.equal(h.timelineNow(),2);
 h.accept(851,{read:{status:'completed',rows:1,seconds:1.5},timeline:[{step:0,start:0,last:1.5,status:'completed'}],timeline_seconds:1.5});assert.equal(h.timelineNow(),2);assert.equal(h.unavailable,false,'late confirmation uses worker time, not the frozen page clock');
 const complete=new ExecutionHistory(852,job);complete.accept(852,{marker:{status:'completed'},timeline:[{step:3,start:2,last:3,status:'completed'}],timeline_seconds:3});ms=19000;assert.equal(complete.timelineNow(),3);
 complete.accept(999,{timeline:[],timeline_seconds:1000});assert.equal(complete.timelineNow(),3);
 const invalid=new ExecutionHistory(853,job);invalid.accept(853,{read:{status:'active'},timeline:[{step:0,start:2,last:1,status:'active'}],timeline_seconds:1});assert(invalid.unavailable);assert.equal(invalid.timeline.size,0);
});
test('the first live timeline window starts on the worker clock',t=>{
 let ms=30000;t.mock.method(performance,'now',()=>ms);
 const h=new ExecutionHistory(854,job);
 h.accept(854,{read:{status:'active'},timeline:[{step:0,start:0,last:1,status:'active'}],timeline_seconds:1});
 assert.equal(h.timelineNow(),1,'page time before Run must not count toward the timeline');
 ms+=500;assert.equal(h.timelineNow(),1.5);
});
test('observed strategies distinguish pending, mixed parents, fallback and fused operations',()=>{
 const h=new ExecutionHistory(800,{...job,operations:[{type:'shuffle',strategy:'auto'},{type:'partition',columns:['key']}]});
 const add=(id,kind,operations=[1])=>h.accept(800,{physical:[{id,kind,operations,status:'active',rows:0,seconds:0}]});
 assert.equal(observedStrategy(h,1),'Awaiting strategy');assert.equal(observedStrategy(h,3),null);
 add(1040,'resident_sort');assert.equal(observedStrategy(h,1),'Random-key sort · in memory');
 add(1041,'spill');assert.equal(observedStrategy(h,1),'Random-key sort · memory + external');
 add(1042,'spill',[1,2]);assert.equal(observedStrategy(h,2),'Fused random-key sort · external');
 const g=new ExecutionHistory(801,{...job,operations:[{type:'partition',columns:['key']}]});
 const feed=(id,kind)=>g.accept(801,{physical:[{id,kind,operations:[1],status:'active',rows:0,seconds:0}]});
 feed(1040,'routed_grouping');assert.equal(observedStrategy(g,1),'Bounded routing');
 feed(1041,'fallback');assert.equal(observedStrategy(g,1),'Routing → sorting');
 feed(1042,'spill');assert.equal(observedStrategy(g,1),'Routing → comparison sort · external');
 g.unavailable=true;assert.match(observedStrategy(g,1),/partial observation$/);
 for(const [kind,expected] of [['fisher_yates','Fisher–Yates · in memory'],['elided','Elided by later shuffle'],['reuse','Reused ordered groups']]){
  const x=new ExecutionHistory(802,{...job,operations:[{type:'shuffle',strategy:'auto'}]});x.accept(802,{physical:[{id:1040,kind,operations:[1],status:'active',rows:0,seconds:0}]});assert.equal(observedStrategy(x,1),expected);
 }
});
test('history freezes output flow, preserves confirmed work and ignores old generations',()=>{
  const h=new ExecutionHistory(7,job);job.limits.rows=99;
  h.accept(7,{read:{status:'completed',rows:3,seconds:1},write:{status:'active',rows:2,seconds:1}});
  assert.match(h.flow,/rows: 2/);assert.doesNotMatch(h.flow,/bytes/);
  h.accept(6,{write:{status:'completed',rows:999,seconds:2}});
  h.interrupt('interrupted');
  assert.equal(h.steps[0].status,'completed');assert.equal(h.steps[1].status,'interrupted');
  h.accept(7,{export:{status:'completed',files:3},marker:{status:'completed'}});
  h.interrupt('unknown');assert.equal(h.steps[3].status,'completed');
  assert.equal(h.steps[2].files,3);
});
test('delivery retains exactly one outstanding message and one coalesced snapshot',()=>{
  const sent=[],credit=new Int32Array(new SharedArrayBuffer(4));
  const d=new ObservationDelivery(8,credit,message=>sent.push(message));
  for(let i=0;i<10000;i++)d.update({read:{status:'active',rows:i,seconds:1}});
  assert.equal(sent.length,1);
  Atomics.store(credit,0,0);d.flush();assert.equal(sent.length,2);
  assert.equal(sent[1].observation.read.rows,9999);
  assert.equal(sent[1].observation.deliveryCoalesced,true);
  d.update({marker:{status:'completed'}});Atomics.store(credit,0,0);d.flush();
  assert.equal(sent[2].observation.read.rows,9999);assert.equal(sent[2].observation.marker.status,'completed');
});
test('ordinary delivery failure disables observation without throwing',()=>{
  const d=new ObservationDelivery(1,new Int32Array(new SharedArrayBuffer(4)),()=>{throw Error('closed');});
  assert.doesNotThrow(()=>d.update({read:{status:'active',rows:1,seconds:1}}));
  assert.equal(d.disabled,true);assert.equal(d.snapshot().unavailable,true);
});

test('unknown marker does not invent an unstarted step and preserves frozen flow',()=>{
  const h=new ExecutionHistory(3,job);
  h.accept(3,{export:{status:'completed',files:3},marker:{status:'unknown'},unavailable:true});
  assert.equal(h.steps.find(s=>s.id===3),undefined);
  assert.match(h.flow,/CSV output/);
});

test('retained physical history rejects reordered snapshots and stays interrupted after shutdown',()=>{
 const physical=new PhysicalHistory();const f={id:1033,kind:'resident_sort',operations:[1,0],rows:1,seconds:0.2,status:'active',source_omitted:true,attempt:7};physical.accept(f);const active=physical.snapshot();
 const h=new ExecutionHistory(9,{...job,operations:[{type:'shuffle',strategy:'uniform'}]});h.accept(9,{physical:active});h.interrupt('interrupted');h.accept(9,{physical:active});assert.equal(h.steps.find(s=>s.id===1033).status,'interrupted');
 physical.accept({...f,status:'completed',rows:3,seconds:0.5});h.accept(9,{physical:physical.snapshot()});assert.equal(h.steps.find(s=>s.id===1033).status,'completed');
 h.accept(9,{physical:active});const retained=h.steps.find(s=>s.id===1033);assert.equal(retained.status,'completed');assert.equal(retained.rows,3);assert.equal(retained.completed_attempts,1);
 h.accept(8,{physical:physical.snapshot().map(s=>({...s,rows:999}))});assert.equal(retained.rows,3);
});
test('direct observations remain last observed after shutdown until explicit confirmation',()=>{
 const h=new ExecutionHistory(12,job);h.accept(12,{read:{status:'completed',rows:3,seconds:1},write:{status:'active',rows:2,seconds:1}});h.interrupt('unknown');
 h.accept(12,{write:{status:'active',rows:2,seconds:1}});assert.equal(h.steps.find(s=>s.id===1).status,'unknown');assert.equal(h.steps.find(s=>s.id===0).status,'completed');
 h.accept(12,{write:{status:'completed',rows:3,seconds:1}});assert.equal(h.steps.find(s=>s.id===1).status,'completed');
});
test('ending with lost or absent observations reports unavailable without inventing completion',()=>{
 for(const observation of [{},{read:{status:'active',rows:3,seconds:1}}]){const h=new ExecutionHistory(13,job);h.accept(13,observation);h.interrupt('unknown');assert.equal(h.unavailable,true);assert.ok(h.steps.every(step=>step.status!=='completed'));}
 const confirmed=new ExecutionHistory(14,job);confirmed.accept(14,{read:{status:'completed',rows:3,seconds:1},write:{status:'completed',rows:3,seconds:1}});confirmed.interrupt('unknown');assert.equal(confirmed.unavailable,false);
});
test('direct unsafe measurements and invalid statuses degrade without fabricating completed work',()=>{
 const h=new ExecutionHistory(15,job);h.accept(15,{read:{status:'active',rows:3,seconds:1}});
 h.accept(15,{read:{status:'completed',rows:Number.MAX_SAFE_INTEGER+1,seconds:1}});assert.equal(h.unavailable,true);assert.equal(h.steps[0].rows,3);assert.equal(h.steps[0].status,'unknown');
 h.accept(15,{export:{status:'completed',files:-1},marker:{status:'invented'}});assert.equal(h.steps.length,1);
});
test('page retention saturates its fixed summaries and four direct categories',()=>{
 const physical=new PhysicalHistory();for(let i=0;i<1152;i++)physical.accept({id:1000+i,role:Math.floor(i/576),kind:'resident_sort',operations:[Math.floor((i%576)/32),0],rows:0,seconds:0,status:'completed',source_omitted:true,attempt:i+1});
 const snapshot=physical.snapshot(),h=new ExecutionHistory(16,{...job,operations:Array.from({length:16},()=>({type:'shuffle',strategy:'uniform'}))});h.accept(16,{physical:snapshot,read:{status:'completed',rows:0,seconds:0},write:{status:'completed',rows:0,seconds:0},export:{status:'completed',files:1},marker:{status:'completed'}});assert.equal(h.steps.length,1156);
 h.accept(16,{physical:[{...snapshot[0],id:2152}]});assert.equal(h.steps.length,1156);assert.equal(h.unavailable,true);
});

test('significant events survive collapsed and blocked delivery without per-row history',()=>{
 const credit=new Int32Array(new SharedArrayBuffer(4)),sent=[],d=new ObservationDelivery(20,credit,message=>sent.push(message));
 d.update({read:{status:'active',rows:0,seconds:0}});
 for(let rows=1;rows<=10000;rows++)d.update({read:{status:'active',rows,seconds:1}});
 d.update({read:{status:'completed',rows:10000,seconds:1}});
 assert.deepEqual(d.snapshot().events.map(e=>[e.step,e.kind]),[[0,'active'],[0,'completed']]);assert.equal(sent.length,1);
 const h=new ExecutionHistory(20,job);h.accept(20,d.snapshot());assert.deepEqual(h.events.map(e=>e.kind),['active','completed']);
});

test('significant event saturation is fixed, deduplicated and explicit on the page',()=>{
 const d=new ObservationDelivery(21,new Int32Array(new SharedArrayBuffer(4)),()=>{});
 for(let id=1000;id<2152;id++)for(const status of ['active','completed'])d.recordPhysical({id,kind:'resident_sort',operations:[1,2],status,rows:1,seconds:1,source_omitted:true});
 const snapshot=d.snapshot();assert.equal(snapshot.events.length,128);assert.ok(snapshot.eventsOmitted>0);assert.ok(Buffer.byteLength(JSON.stringify({events:snapshot.events,eventsOmitted:snapshot.eventsOmitted}))<=32768);
 const omitted=snapshot.eventsOmitted;for(let i=0;i<10000;i++)d.recordPhysical({id:2151,kind:'resident_sort',operations:[1,2],status:'completed',rows:1,seconds:1,source_omitted:true});assert.equal(d.snapshot().eventsOmitted,omitted);
 const h=new ExecutionHistory(21,job);h.accept(21,snapshot);h.accept(21,snapshot);assert.equal(h.events.length,128);assert.equal(h.eventsOmitted,omitted);assert.ok(h.events.every((event,index)=>!index||event.seconds>=h.events[index-1].seconds));
 h.accept(20,{events:[],eventsOmitted:999});assert.equal(h.eventsOmitted,omitted);
});
test('configuration projection labels omitted detail without retaining the submitted job',()=>{
 const columns=Array.from({length:20},(_,index)=>'column-'+index),config={...job,operations:[{type:'partition',columns}],output_csv:{headers:null,delimiter:null},limits:{rows:null,bytes:null,compressed_bytes:null}};
 const h=new ExecutionHistory(22,config);columns[0]='edited';assert.equal(h.configurationOmitted,true);assert.match(h.flow,/column-0/);assert.doesNotMatch(h.flow,/edited|column-19|rows:|bytes:|headers:|delimiter:/);assert.equal(h.configured.at(-1).id,2);
});


test('DAG layers follow real fork/join dependencies rather than observation order',()=>{
 const frame=new ExecutionDag().update([{id:4,sources:[2,3]},{id:2,sources:[1]},{id:3,sources:[1]},{id:1,sources:[]}]);
 assert.equal(frame.edges.length,4);
 for(const edge of frame.edges)assert(frame.positions.get(edge.source).column<frame.positions.get(edge.target).column);
 assert.notEqual(frame.positions.get(2).row,frame.positions.get(3).row);
 assert.match(edgePath(frame.positions.get(1),frame.positions.get(2)),/^M [0-9 ]+ L [0-9 ]+ C /);
});

test('DAG retains live positions, resolves late producers and rejects aggregate cycles',()=>{
 const dag=new ExecutionDag(),initial=dag.update([{id:2,sources:[1]}]),position={...initial.positions.get(2)};
 assert.equal(initial.missing,1);assert.equal(initial.edges.length,0);
 assert.equal(dag.update([{id:2,sources:[1]}]),initial,'metric-only updates reuse layout');
 const complete=dag.update([{id:2,sources:[1]},{id:1,sources:[]},{id:3,sources:[2]}]);
 assert.equal(complete.positions.get(2).column,position.column);assert(complete.positions.get(1).x<complete.positions.get(2).x,'late producer precedes its consumer');assert.equal(complete.edges.length,2);
 const cyclic=new ExecutionDag().update([{id:1,sources:[2]},{id:2,sources:[1]},{id:3,sources:[3]}]);
 assert.equal(cyclic.cycles,2);assert.equal(cyclic.edges.length,1);assert.equal(cyclic.positions.size,3);
});

test('DAG node and edge storage stays bounded at the observation envelope',()=>{
 const dag=new ExecutionDag(),nodes=Array.from({length:MAX_DAG_NODES+20},(_,id)=>({id,sources:id<4?[]:[0,1,2,3]}));
 const frame=dag.update(nodes);
 assert.equal(frame.positions.size,MAX_DAG_NODES);assert(frame.edges.length<=MAX_DAG_EDGES);assert.equal(frame.cycles,0);
 assert(Number.isFinite(frame.width)&&Number.isFinite(frame.height));
 for(const edge of frame.edges)assert(!edgePath(frame.positions.get(edge.source),frame.positions.get(edge.target)).includes('NaN'));
});

test('observed edges preserve explicit sources and never invent missing prepared input or elision work',()=>{
 const direct=new ExecutionHistory(200,{...job,operations:[]});
 assert.deepEqual(observedSources(direct,{id:1,status:'completed',title:'Write CSV'}),[0]);
 assert.deepEqual(observedSources(direct,{id:2,status:'completed',title:'Save destination files'}),[1]);
 const prepared=new ExecutionHistory(201,{...job,operations:[{type:'partition',columns:[0]}]});
 assert.deepEqual(observedSources(prepared,{id:2,status:'completed',title:'Save destination files',source_omitted:true}),[]);
 assert.deepEqual(observedSources(prepared,{id:1033,status:'completed',title:'Elided',kind:'elided',sources:[1000]}),[]);
 assert.deepEqual(observedSources(prepared,{id:1034,status:'completed',title:'Merge',kind:'merge',sources:[1000,1001],source_omitted:true}),[1000,1001]);
});


test('configured-stage hints place related physical work across lanes while publication flows downward',()=>{
 const frame=new ExecutionDag().update([{id:0,sources:[],stage:0},{id:1000,sources:[0],stage:1},{id:1001,sources:[1000],stage:1},{id:1002,sources:[1001],stage:2},{id:2,sources:[1002],stage:3},{id:3,sources:[2],stage:4}]);
 assert.equal(frame.positions.get(1000).column,frame.positions.get(1001).column);
 assert(frame.positions.get(1000).row<frame.positions.get(1001).row);
 assert(frame.positions.get(2).column>frame.positions.get(1002).column);
 assert(frame.positions.get(2).y>frame.positions.get(1002).y);
 assert(frame.positions.get(1001).x>frame.positions.get(1000).x);
 assert.equal(frame.positions.get(1000).y,frame.positions.get(1001).y);
 const path=edgePath(frame.positions.get(1000),frame.positions.get(1001));
 assert.match(path,/^M /);assert(!path.includes('NaN'));
});


test('repeated attempts keep one aggregate In Progress status until processing ends',()=>{
 const h=new ExecutionHistory(300,{...job,operations:[{type:'shuffle',strategy:'uniform'}]}),physical=new PhysicalHistory();
 const observed=[];
 for(const [attempt,status] of [[1,'active'],[1,'completed'],[2,'active'],[2,'completed']]){
  physical.accept({id:1040,kind:'spill',operations:[1,0],rows:10,seconds:.1,status,source_omitted:true,attempt,runs:1});
  h.accept(h.run,{physical:physical.snapshot()});observed.push(displayStepStatus(h,h.steps[0]));
 }
 assert.deepEqual(observed,['in_progress','in_progress','in_progress','in_progress']);
 assert.equal(h.steps[0].completed_attempts,2,'attempt measurements are retained');
 h.accept(h.run,{physical:physical.snapshot(),processingComplete:true});
 assert.equal(displayStepStatus(h,h.steps[0]),'completed');
});


test('stopped repeating work does not claim full completion without a phase boundary',()=>{
 for(const status of ['interrupted','unknown']){
  const h=new ExecutionHistory(301,{...job,operations:[{type:'shuffle',strategy:'uniform'}]}),physical=new PhysicalHistory();
  physical.accept({id:1040,kind:'spill',operations:[1,0],rows:10,seconds:.1,status:'completed',source_omitted:true,attempt:1,runs:1});
  h.accept(h.run,{physical:physical.snapshot()});h.interrupt(status);
  assert.equal(displayStepStatus(h,h.steps[0]),status);assert.equal(h.steps[0].completed_attempts,1);
 }
});


test('missing aggregate observations do not invent completion, while late marker uncertainty preserves it',()=>{
 const make=()=>new ExecutionHistory(303,{...job,operations:[{type:'shuffle',strategy:'uniform'}]});
 const physical=new PhysicalHistory();physical.accept({id:1040,kind:'spill',operations:[1,0],rows:10,seconds:.1,status:'completed',source_omitted:true,attempt:1,runs:1});
 const unknown=make();unknown.accept(unknown.run,{physical:physical.snapshot(),processingComplete:true,unavailable:true});unknown.interrupt('unknown');
 assert.equal(displayStepStatus(unknown,unknown.steps[0]),'unknown');
 const known=make();known.accept(known.run,{physical:physical.snapshot(),processingComplete:true});known.accept(known.run,{marker:{status:'unknown'},unavailable:true});
 assert.equal(displayStepStatus(known,known.steps[0]),'completed');
});

test('growing card content expands activity rows and moves dependency endpoints',()=>{
 const dag=new ExecutionDag(),input=[{id:1,sources:[],stage:0,height:500},{id:2,sources:[1],stage:1,height:250}];
 const frame=dag.update(input);assert(frame.positions.get(2).y>frame.positions.get(1).y+500);
 assert(frame.height>frame.positions.get(2).y+250);
 assert(edgePath(frame.positions.get(1),frame.positions.get(2)).startsWith(`M ${DAG_PADDING+DAG_NODE_WIDTH/2} ${frame.positions.get(1).y+500}`));
 const grown=dag.update(input.map(n=>({...n,height:700})));assert(grown.height>frame.height);
 const shorter=dag.update(input.map(n=>({...n,height:150})));assert.equal(shorter.positions.get(1).height,700);assert.equal(shorter.height,grown.height);
});
test('spill rows and allocation memberships use comma-separated thousands',()=>{
 const h=new ExecutionHistory(900,{...job,operations:[{type:'assign',groups:[{name:'test',percent:'100'}]}]});
 assert.match(describeStep(h,{id:1040,title:'Spill',kind:'spill',status:'completed',rows:25000000,runs:1,seconds:1}),/25,000,000 sorted rows/);
 assert.match(describeStep(h,{id:1041,title:'Allocate',kind:'exact_membership',status:'completed',rows:25000000,groups:1,empty_groups:0,memberships:[25000000],operations:[1],seconds:1}),/test: 25,000,000/);
});

const estimateBundle=await build({entryPoints:['src/browser/client.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {temporarySpaceEstimate}=await import(`data:text/javascript;base64,${Buffer.from(estimateBundle.outputFiles[0].text).toString('base64')}`);
test('source-size temporary storage guidance is advisory and handles compressed inputs',()=>{
 assert.match(temporarySpaceEstimate({name:'test.csv',size:2*1024**3}),/4.0 GiB–16.0 GiB/);
 assert.match(temporarySpaceEstimate({name:'test.csv',size:1}),/not an upper bound/);
 assert.match(temporarySpaceEstimate({name:'test.csv.gz',size:2*1024**3}),/exceed the compressed file size/);
});

test('activity rows share peak height and reduce only redundant links',()=>{
 const dag=new ExecutionDag(),frame=dag.update([{id:3,sources:[1,2],stage:1,height:150},{id:1,sources:[],stage:1,height:400},{id:2,sources:[1],stage:1,height:200}]);
 assert.deepEqual([...frame.positions.values()].map(p=>p.height),[400,400,400]);assert(frame.positions.get(1).x<frame.positions.get(2).x);assert(frame.positions.get(2).x<frame.positions.get(3).x);
 assert.deepEqual(frame.edges,[{source:2,target:3},{source:1,target:2}]);assert.match(edgePath(frame.positions.get(1),frame.positions.get(2)),/^M [0-9 ]+ L [0-9 ]+$/);
});
test('measurement tokens keep counts, seconds, byte units and rates together',()=>{
 const text='25,000,000 rows · 34.03 s · average 734,607 framed rows written/s · 1 completed attempt(s)';const parts=measurementParts(text);assert.equal(parts.map(p=>p.text).join(''),text);assert.deepEqual(parts.filter(p=>p.measurement).map(p=>p.text),['25,000,000 rows','34.03 s','734,607 framed rows written/s','1 completed attempt(s)']);
});

test('coalesced start events retain genuinely started steps with unknown terminal measurements',()=>{
 const h=new ExecutionHistory(1001,job);h.accept(1001,{events:[{index:0,step:3,kind:'active',seconds:0}],marker:{status:'unknown'}});assert.equal(h.steps.find(step=>step.id===3).status,'unknown');
});


test('card metrics keep one cumulative scope as spill and allocation attempts repeat',()=>{
 for(const kind of ['spill','probabilistic_membership']){
  const p=new PhysicalHistory(),h=new ExecutionHistory(600,{...job,operations:[{type:'shuffle',strategy:'uniform'}]});
  const feed=(attempt,status,rows,seconds,runs=1)=>{p.accept({id:1040,kind,operations:[1,0],rows,seconds,status,attempt,runs,source_omitted:true});h.accept(h.run,{physical:p.snapshot()});return summarizeStep(h.steps[0]);};
  assert.match(feed(1,'active',1000,1),/^1,000 rows/);
  const completed=feed(1,'completed',1000,1);
  assert.equal(feed(2,'active',0,0,0),completed,'starting the next attempt does not replace totals with waiting text');
  assert.match(feed(2,'active',500,0.5),/^1,500 rows/);
  assert.equal(feed(2,'completed',500,0.5),summarizeStep(h.steps[0]));
  assert.doesNotMatch(summarizeStep(h.steps[0]),/awaiting|attempt|membership|average/);
 }
});

test('cumulative cards preserve last observed work when a running attempt is interrupted',()=>{
 for(const status of ['interrupted','unknown']){
  const p=new PhysicalHistory(),h=new ExecutionHistory(601,{...job,operations:[{type:'shuffle',strategy:'uniform'}]});
  const fact={id:1043,kind:'merge_traversal',operations:[1,0],source_omitted:true};
  p.accept({...fact,attempt:1,status:'completed',rows:10,seconds:0.1});
  p.accept({...fact,attempt:2,status:'active',rows:1000,seconds:1});h.accept(h.run,{physical:p.snapshot()});
  const before=summarizeStep(h.steps[0]);assert.equal(before,'1,010 row visits · 1.10 s · avg 918 row visits/s');
  h.interrupt(status);assert.equal(summarizeStep(h.steps[0]),before);
  p.accept({...fact,attempt:2,status:'interrupted',rows:2000,seconds:2});h.accept(h.run,{physical:p.snapshot()});
  assert.equal(summarizeStep(h.steps[0]),'2,010 row visits · 2.10 s · avg 957 row visits/s');
  assert.equal(h.steps[0].completed_attempts,1,'partial work is not confirmed as complete');
 }
});

test('card throughput uses cumulative scopes, binary codec units and valid measured time',()=>{
 const step={id:1040,kind:'spill',status:'active',rows:1000,seconds:2,runs:1,active_rows:500,active_seconds:1};
 assert.match(summarizeStep(step),/avg 500 rows\/s$/);
 assert.equal(summarizeStep({...step,status:'completed',rows:1500,seconds:3}),summarizeStep({...step,active_runs:0}));
 for(const [bytes,rate] of [[500,'250 B/s'],[4096,'2 KiB/s'],[10485760,'5 MiB/s'],[2147483648,'1 GiB/s']]){
  const text=summarizeStep({id:1041,kind:'gzip_input',status:'completed',bytes,seconds:2});
  assert(text.endsWith('avg '+rate),text);
  assert(measurementParts(text).some(part=>part.measurement&&part.text===rate));
 }
 for(const seconds of [0,undefined,Number.MIN_VALUE])assert.doesNotMatch(summarizeStep({id:0,status:'active',rows:1000,seconds}),/avg|Infinity|NaN/);
 assert.match(summarizeStep({id:0,status:'active',rows:1,seconds:4}),/avg 0.25 rows\/s$/);
 for(const sample of [{id:2,status:'active',files:4,seconds:2},{id:3,status:'completed',seconds:2},{id:1042,kind:'materialize',status:'completed',seconds:2},{id:1042,kind:'reuse',status:'completed',runs:4,seconds:2}])assert.doesNotMatch(summarizeStep(sample),/\/s/);
});

test('resident sort titles distinguish random-key and comparison work from frozen operations',()=>{
 const h=new ExecutionHistory(901,{...job,operations:[{type:'shuffle',strategy:'auto'},{type:'partition',columns:['key']}]});
 for(const [id,operations] of [[1040,[1]],[1041,[1,2]],[1042,[2]]])h.accept(901,{physical:[{id,operations,kind:'resident_sort',status:'active',rows:0,seconds:0}]});
 assert.deepEqual(h.steps.map(step=>step.title),['Resident random-key sort','Fused resident random-key sort','Resident comparison sort']);
});

test('completed and interrupted attempts keep In Progress while more groups may still run',()=>{
 const h=new ExecutionHistory(902,{...job,operations:[{type:'partition',columns:['key']}]});
 h.accept(902,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'completed',rows:10,seconds:1}]});
 assert.equal(displayStepStatus(h,h.steps[0]),'in_progress');
 h.accept(902,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'active',rows:0,seconds:0}]});
 assert.equal(displayStepStatus(h,h.steps[0]),'in_progress');
 h.accept(902,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'interrupted',rows:0,seconds:0}]});
 assert.equal(displayStepStatus(h,h.steps[0]),'in_progress');
 h.interrupt('interrupted');
 assert.equal(displayStepStatus(h,h.steps[0]),'interrupted');
});

test('attempt, stage and processing completion are separate boundaries',()=>{
 const h=new ExecutionHistory(990,{...job,operations:[{type:'partition',columns:['key']},{type:'shuffle',strategy:'uniform'}]});
 h.accept(990,{physical:[{id:1033,kind:'grouping',operations:[1],status:'completed',rows:10,seconds:1},{id:1064,kind:'resident_sort',operations:[2],status:'completed',rows:10,seconds:1}]});
 assert.equal(displayStepStatus(h,h.steps[0]),'in_progress');
 h.accept(990,{completedStages:[0,1]});assert.equal(displayStepStatus(h,h.steps[0]),'completed');assert.equal(displayStepStatus(h,h.steps[1]),'in_progress');assert.equal(h.processingComplete,false);
 h.accept(990,{completedStages:[2]});assert.equal(displayStepStatus(h,h.steps[1]),'completed');
 h.accept(990,{completedStages:[1]});assert.deepEqual([...h.completedStages].sort(),[0,1,2]);
 h.accept(990,{completedStages:[99]});assert.equal(h.unavailable,true);
});

test('a finalized stage cannot silently begin another attempt',()=>{
 const h=new ExecutionHistory(991,job);h.accept(991,{completedStages:[1]});
 h.accept(991,{physical:[{id:1033,kind:'resident_sort',operations:[1],status:'active',rows:0,seconds:0,last_attempt:9,last_terminal:8}]});
 assert.equal(h.unavailable,true);assert.equal(h.steps.length,0);
});

test('serialization finalization does not finalize later publication or compression work',()=>{
 const h=new ExecutionHistory(992,{...job,operations:[],compression:'gzip'});
 h.accept(992,{completedStages:[0,1]});
 h.accept(992,{physical:[{id:1058,kind:'gzip_output',operations:[1],status:'active',bytes:0,rows:0,seconds:0}]});
 assert.equal(h.unavailable,false);assert.equal(h.steps.length,1);
 h.accept(992,{physical:[{id:1058,kind:'gzip_output',operations:[1],status:'completed',bytes:100,rows:0,seconds:1}]});assert.equal(displayStepStatus(h,h.steps[0]),'in_progress');
 h.accept(992,{processingComplete:true});assert.equal(displayStepStatus(h,h.steps[0]),'completed');
});
