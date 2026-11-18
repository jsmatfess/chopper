
'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {exercise,run}=require('./hosted.cjs'),{validateConfig}=require('./driver.cjs');
const cfg={phase:'hosted-tiny-qualification',case:'success',channel:'chrome',parentReviewed:true,layoutReviewComplete:true,job:{limits:{bytes:40},operations:[],seed:'synthetic'}};
function page(){const values={input:'',output:'',status:'IDLE'},calls=[],waits=[];return {values,calls,waits,on(){},
 evaluate:async()=>({kind:'FAKE DOM',output:values.output,acceptance:false}),waitForFunction:async(...args)=>{waits.push(args);},
 locator(s){const id=s.slice(1);return {inputValue:async()=>values[id]||'',textContent:async()=>values[id]||'',isVisible:async()=>false,setInputFiles:async()=>Object.assign(values,{'max-bytes':'40',seed:cfg.job.seed,memory:'32',workers:'1',compression:'none'}),
 click:async()=>{calls.push(id);if(id==='run-direct'){values.status='COMPLETE';values['result-path']='✓ Complete. Results saved to output/chopper-results-00000000-0000-4000-8000-000000000000';}}};}};}
async function act(p,fail,emitted=[]){return exercise(p,cfg,v=>emitted.push(v),async mode=>{
 if(mode===fail)throw Error('gate failed');
 if(mode==='input'){p.values.input='tiny.csv';return {selected:'input'};}
 if(mode==='input-verified')return {inputVerified:true};
 if(mode==='output')return {postClickObserved:true};
 if(mode==='post-click-dom'){p.values.output='output';return {permissionInvoked:true};}if(mode==='run')return {runApproved:true};throw Error('unknown mode');});}
test('two public Browse clicks; one exact permission, public output selection and one Run',async()=>{const p=page(),emitted=[];const r=await act(p,null,emitted);assert.deepEqual(p.calls,['browse-input','browse-output','run-direct']);assert.equal(p.waits.length,4);assert.equal(r.kind,'tiny-export-complete');assert.equal(r.runs,1);assert.equal(r.acceptance,false);assert.equal(p.values.output,'output');assert.equal(emitted.find(v=>v.kind==='post-click-dom').dom.output,'');});
for(const mode of ['input','input-verified','output','post-click-dom','run'])test(mode+' failure cannot Run or add another click',async()=>{const p=page();await assert.rejects(act(p,mode));assert.equal(p.calls.includes('run-direct'),false);assert.ok(p.calls.length<=2);if(mode.startsWith('input'))assert.equal(p.calls.includes('browse-output'),false);});
test('wrong public filename denies output',async()=>{const p=page();await assert.rejects(exercise(p,cfg,()=>{},async()=>({selected:'input'})));assert.deepEqual(p.calls,['browse-input']);});
test('wrong phase stops before UI',async()=>{const p=page();await assert.rejects(exercise(p,{...cfg,phase:'tiny-export'},()=>{},async()=>{}));assert.deepEqual(p.calls,[]);});
test('unreviewed browser cannot launch',async()=>{let calls=0;await assert.rejects(run({launchPersistentContext:async()=>{calls++;}},{channel:'msedge',freshProfile:false,continuedIssue105Profile:true,freshOrigin:true},()=>{},async()=>{}));assert.equal(calls,0);});
test('entry dispatch accepts only reviewed exact diagnostic phase',()=>{validateConfig(cfg);for(const change of [{phase:'observe-input'},{phase:'tiny-export'},{phase:'export'},{channel:'unknown'},{case:'unknown'},{parentReviewed:false},{layoutReviewComplete:false}])assert.throws(()=>validateConfig({...cfg,...change}));});
test('inaccessible postclick DOM is recorded unavailable, never fabricated',async()=>{const p=page(),rows=[];let reads=0;p.evaluate=async()=>{if(reads++)throw Error('unavailable');return {kind:'FAKE input DOM'};};await act(p,null,rows);assert.equal(rows.find(v=>v.kind==='post-click-dom').dom.kind,'hosted-browse-dom-unavailable');assert.deepEqual(p.calls,['browse-input','browse-output','run-direct']);});

for(const status of ['FAILED','CANCELLED'])test(status+' terminal UI cannot claim export completion',async()=>{const p=page();const original=p.locator;p.locator=s=>{const x=original(s);if(s==='#status')x.textContent=async()=>status;return x;};await assert.rejects(act(p));assert.equal(p.calls.filter(v=>v==='run-direct').length,1);});
test('pending output permission cannot reach Run',async()=>{const p=page();await assert.rejects(exercise(p,cfg,()=>{},async mode=>{if(mode==='input'){p.values.input='tiny.csv';return{selected:'input'};}if(mode==='input-verified')return{inputVerified:true};if(mode==='output')return{postClickObserved:true};return{permissionInvoked:false};}));assert.equal(p.calls.includes('run-direct'),false);});
test('incomplete public completed-path cannot claim a successful export',async()=>{const p=page();const original=p.locator;p.locator=s=>{const x=original(s);if(s==='#result-path')x.textContent=async()=>'';return x;};await assert.rejects(act(p));assert.equal(p.calls.filter(v=>v==='run-direct').length,1);});

for(const channel of ['chrome','msedge'])test(channel+' failure uses actual Browse and public Run without a picker replacement',async()=>{
 const p=page();p.locator=(original=>s=>{const x=original(s);
  if(s==='#max-bytes')x.fill=async value=>{p.values['max-bytes']=value;};
  if(s==='#status')x.textContent=async()=> 'FAILED';
  if(s==='#error'){x.isVisible=async()=>p.calls.includes('run-direct');x.textContent=async()=> 'header/BOM exceeds output byte limit';}
  return x;
 })(p.locator);
 p.evaluate=async(fn,args)=>args?{kind:'FAKE DOM',output:p.values.output}:{workspaces:[],locks:[]};
 const r=await exercise(p,{...cfg,channel,case:'failure'},()=>{},async mode=>{
  if(mode==='input'){p.values.input='tiny.csv';return {selected:'input'};}
  if(mode==='input-verified')return {inputVerified:true};
  if(mode==='output')return {postClickObserved:true};
  if(mode==='post-click-dom'){p.values.output='output';return {permissionInvoked:true};}
  if(mode==='run')return {runApproved:true};throw Error('unexpected gate');
 });
 assert.equal(r.kind,'controlled-failure-complete');assert.equal(p.values['max-bytes'],'1');
 assert.deepEqual(p.calls,['browse-input','browse-output','run-direct']);
});
test('both channels close their owned context on actual version mismatch',async()=>{
 for(const channel of ['chrome','msedge']){let closed=0;
  const context={browser:()=>({version:()=> 'wrong'}),close:async()=>{closed++;}};
  await assert.rejects(run({launchPersistentContext:async()=>context},{channel,profileChannel:channel,case:'success',freshProfile:true,continuedIssue105Profile:false,freshOrigin:true,parentReviewed:true,expectedVersion:'expected',profile:'synthetic-profile',url:'http://127.0.0.1:12345',browser:channel==='chrome'?'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe':'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'},()=>{},async()=>{}));
  assert.equal(closed,1);
 }
});
for(const phase of ['observe-input','observe-output','observe-permission'])test(phase+' stops at the actual observation gate with zero Runs',async()=>{
 const p=page();
 const result=await exercise(p,{...cfg,case:phase},()=>{},async mode=>{
  if(mode==='input'){
   if(phase==='observe-input')return {inputObserved:true};
   p.values.input='tiny.csv';return {selected:'input'};
  }
  if(mode==='input-verified')return {inputVerified:true};
  if(mode==='output')return phase==='observe-output'?{outputObserved:true}:{postClickObserved:true};
  if(mode==='post-click-dom')return {permissionObserved:true};
  throw Error('Unexpected action after diagnostic boundary');
 });
 assert.equal(result.kind,'picker-observation-complete');assert.equal(result.runs,0);
 assert(!p.calls.includes('run-direct'));
});

test('cancellation observation distinguishes processing, actual export and terminal races',()=>{
 const {cancellationObservation:check}=require('./hosted.cjs');
 assert.equal(check({status:'RUNNING',phase:'Reading CSV',rows:65536},'processing-cancel').rows,65536);
 assert.equal(check({status:'RUNNING',phase:'Saving results (1/1101)',rows:0},'export-cancel').status,'RUNNING');
 for(const status of ['COMPLETE','FAILED','CANCELLED'])assert.throws(()=>check({status,phase:'Saving results (1/2)',rows:1},'export-cancel'));
 for(const phase of ['Writing output','Saving results (1/2)'])assert.throws(()=>check({status:'RUNNING',phase,rows:2},'processing-cancel'));
 assert.throws(()=>check({status:'RUNNING',phase:'Reading CSV',rows:0},'processing-cancel'));
 assert.throws(()=>check({status:'RUNNING',phase:'Writing output',rows:2},'export-cancel'));
});
test('public Cancel checks the actual trusted click state and cleans its passive observer',async()=>{
 const {cancelCurrent}=require('./hosted.cjs');
 for(const progress of [{phase:'Reading CSV',rows:65536},{phase:'Preparing operation 6 of 17',rows:0}])for(const wrongAtClick of [false,true]){
  let reads=0,clicks=0,taken=0;const emitted=[];
  const active={status:'RUNNING',...progress,unixMs:1,monotonicMs:1};
  const p={waitForFunction:async()=>{},evaluate:async fn=>{
   if(fn.name==='installCancelCapture')return {unixMs:2,monotonicMs:2};
   if(fn.name==='takeCancelCapture'){taken++;return {installed:{unixMs:2,monotonicMs:2},events:[{...active,phase:wrongAtClick?'Saving results (1/2)':active.phase,trusted:true,type:'click',eventTimeStamp:4,monotonicMs:4}],taken:{unixMs:5,monotonicMs:5}};}
   return {...active,monotonicMs:++reads===1?1:3};
  },locator:selector=>{assert.equal(selector,'#cancel');return {click:async()=>clicks++};}};
  if(wrongAtClick)await assert.rejects(cancelCurrent(p,'processing-cancel',v=>emitted.push(v)));
  else await cancelCurrent(p,'processing-cancel',v=>emitted.push(v));
  assert.equal(clicks,1);assert.equal(taken,1);assert.equal(emitted.at(-1).kind,'cancel-click-observed');
 }
});
test('passive capture reads public DOM at the click without preventing or changing it',()=>{
 const vm=require('node:vm');const {installCancelCapture,takeCancelCapture}=require('./hosted.cjs');let listener,options,removed=false,clock=0;
 const nodes={status:{textContent:'RUNNING'},phase:{textContent:'Reading CSV'},'progress-detail':{textContent:'65,536 rows'}};
 nodes.cancel={addEventListener(type,fn,value){assert.equal(type,'click');listener=fn;options=value;},removeEventListener(type,fn,capture){assert.equal(type,'click');assert.equal(fn,listener);assert.equal(capture,true);removed=true;}};
 const context={document:{querySelector:s=>nodes[s.slice(1)]},performance:{now:()=>++clock},Date:{now:()=>10}};vm.createContext(context);
 vm.runInContext('('+installCancelCapture.toString()+')()',context);
 assert.equal(options.capture,true);assert.equal(options.passive,true);assert.equal(options.once,true);
 nodes.phase.textContent='Saving results (1/2)';listener({type:'click',isTrusted:true,timeStamp:2,preventDefault(){throw Error('must remain passive');}});
 const captured=vm.runInContext('('+takeCancelCapture.toString()+')()',context);
 assert.equal(captured.events[0].phase,'Saving results (1/2)');assert.equal(captured.events[0].rows,65536);assert(removed);assert.equal(context.__chopper105CancelCapture,undefined);
});

test('same page baseline, malformed failure and valid retry use three actual input gates and one output gate',async()=>{
 for(const wrongFailure of [false,true]){
  const p=page();let runs=0;const emitted=[],gates=[];const locator=p.locator;
  p.locator=selector=>{const value=locator(selector);
   if(selector==='#run-direct')value.click=async()=>{p.calls.push('run-direct');runs++;p.values.status=runs===2&&!wrongFailure?'FAILED':'COMPLETE';p.values['result-path']='✓ Complete. Results saved to output/chopper-results-00000000-0000-4000-8000-00000000000'+(runs===3?'1':'0');};
   if(selector==='#error'){value.isVisible=async()=>runs===2&&!wrongFailure;value.textContent=async()=>runs===2?'CSV record 4 has 2 fields, expected 3':'';}
   return value;
  };
  p.evaluate=async(fn,args)=>args?{kind:'FAKE DOM',output:p.values.output}:{workspaces:[],locks:[]};
  const action=exercise(p,{...cfg,case:'malformed-retry',inputName:'tiny.csv',malformedName:'malformed.csv'},v=>emitted.push(v),async mode=>{
   gates.push(mode);
   if(mode==='input'||mode==='repeat-input'){p.values.input=runs===1?'malformed.csv':'tiny.csv';return{selected:'input'};}
   if(mode==='input-verified'||mode==='repeat-input-verified')return{inputVerified:true};
   if(mode==='output')return{postClickObserved:true};
   if(mode==='post-click-dom'){p.values.output='output';return{permissionInvoked:true};}
   if(mode==='run'||mode==='repeat-run')return{runApproved:true};
   if(mode==='baseline')return{baselineVerified:true};
   if(mode==='malformed')return{malformedVerified:true};
   throw Error('unexpected gate '+mode);
  });
  if(wrongFailure){await assert.rejects(action);assert.equal(runs,2);}
  else{const result=await action;assert.equal(result.kind,'retry-export-complete');assert.equal(result.runs,3);assert.equal(gates.filter(x=>x==='output').length,1);assert.equal(gates.filter(x=>x==='input'||x==='repeat-input').length,3);assert(emitted.some(x=>x.kind==='malformed-failure-complete'));}
 }
});

test('repeat Run ignores the previous terminal DOM while its new acknowledgement is pending',async()=>{
 const vm=require('node:vm'),{repeatInput}=require('./hosted.cjs');
 for(const stage of ['malformed','retry']){
  const wanted=stage==='malformed'?'FAILED':'COMPLETE',name=stage==='malformed'?'malformed.csv':'tiny.csv';
  const values={input:name,output:'output',status:stage==='malformed'?'COMPLETE':'FAILED'};
  let clicked=false,terminalWait=false;
  const p={locator(selector){return{click:async()=>{if(selector==='#run-direct')clicked=true;},inputValue:async()=>values[selector.slice(1)]};},
   async waitForFunction(fn,arg){
    const evaluate=()=>vm.runInNewContext('('+fn.toString()+')(arg)',{arg,document:{querySelector:selector=>({value:values[selector.slice(1)],textContent:values[selector.slice(1)],disabled:false})}});
    if(clicked){terminalWait=true;assert.equal(evaluate(),false,'old terminal must not finish the new Run');values.status=wanted;}
    assert.equal(evaluate(),true);
   }};
  await repeatInput(p,stage,name,stage==='malformed'?1:2,()=>{},async mode=>mode==='repeat-input'?{selected:'input'}:mode==='repeat-input-verified'?{inputVerified:true}:{runApproved:true});
  assert(terminalWait);assert.equal(values.status,wanted);
 }
});
