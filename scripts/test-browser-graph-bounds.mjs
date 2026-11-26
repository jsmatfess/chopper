// Public Run correctness/cancellation plus synthetic observation-boundary saturation.
import {withHostedBrowser,revealFormControl} from './browser-acceptance.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {browserChannel} from './browser-launch.mjs';
import {assertProductionWasm} from './browser-artifacts.mjs';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=fileURLToPath(new URL('../',import.meta.url)),production=await readFile(root+'ui/dist/engine-worker.js','utf8');assertProductionWasm(await readFile(root+'ui/dist/engine.wasm'));
const adapter=(await build({stdin:{contents:"import './ui/src/app';export {executionHistory} from './ui/src/browser/client';export {ExecutionHistory,ObservationDelivery,renderExecutionHistory} from './ui/src/browser/execution-history';export {PhysicalHistory,reasons} from './ui/src/browser/physical-history';export {TimingGapWriter} from './ui/src/browser/execution-timing';",resolveDir:root},bundle:true,write:false,format:'iife',globalName:'GraphBounds',define:{__HOSTED__:'true'}})).outputFiles[0].text;
const wrapper=`import '/bounds-engine-production.js';const send=globalThis.postMessage.bind(globalThis);globalThis.postMessage=(message,...args)=>{send(message,...args);if(message.progress?.rows>=65536){send({boundsPaused:true});Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0);}};`;
await withHostedBrowser({port:8431,viewport:{width:1280,height:900}},async({context,url,browserVersion})=>{
 const page=await context.newPage(),headers={'Cross-Origin-Resource-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'};
 await page.route('**/app.js',route=>route.fulfill({contentType:'application/javascript',headers,body:adapter}));await page.route('**/bounds-engine-production.js',route=>route.fulfill({contentType:'application/javascript',headers,body:production}));await page.route('**/engine-worker.js',route=>route.fulfill({contentType:'application/javascript',headers,body:wrapper}));
 await page.addInitScript(()=>{
  window.boundsParent='bounds-'+crypto.randomUUID();window.boundsSource='id,key,payload\n0,0,x\n1,0,x\n';window.boundsPaused=false;window.holdCredit=false;window.heldAcks=0;
  const store=Atomics.store;Atomics.store=function(view,index,value){if(window.holdCredit&&view instanceof Int32Array&&view.length===1&&index===0&&value===0){window.heldAcks++;return 1;}return Reflect.apply(store,Atomics,[view,index,value]);};
  const Native=window.Worker;window.Worker=class extends Native{constructor(...args){super(...args);this.addEventListener('message',({data})=>{if(data.boundsPaused)window.boundsPaused=true;});}};
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([window.boundsSource],'fixture.csv')}];window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle(window.boundsParent,{create:true});
 });
 await page.goto(url);await page.waitForFunction(()=>document.getElementById('status').textContent==='IDLE');await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();await page.locator('#browse-output').click();
 const download=page.waitForEvent('download');await page.locator('#export').click();const chunks=[];for await(const chunk of await(await download).createReadStream())chunks.push(chunk);const base=JSON.parse(Buffer.concat(chunks));
 async function configure(operations,seed){const job={...base,operations,limits:{rows:null,bytes:1048576,compressed_bytes:null},resources:{...base.resources,memory_mb:32,workers:1,max_record_bytes:1048576}};await page.evaluate(()=>document.getElementById('input').value='pending-import');await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(input=>document.getElementById('input').value===input,job.input);}
 await configure([],'bounds-success');await page.locator('#run-direct').click();await page.waitForFunction(()=>document.getElementById('status').textContent==='COMPLETE');
 const initial=await page.evaluate(async()=>{window.boundsModule=window.GraphBounds;const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.boundsParent),folder=document.getElementById('result-path').textContent.match(/chopper-results-[a-z0-9-]+/)[0],dir=await parent.getDirectoryHandle(folder);let csv,manifest,marker,saved=0;for await(const [name,handle]of dir.entries()){if(name!=='CHOPPER-COMPLETE.json')saved++;const text=await(await handle.getFile()).text();if(name.endsWith('.csv'))csv=text;else if(name==='manifest.jsonl')manifest=text.trim().split('\n').map(JSON.parse);else if(name==='CHOPPER-COMPLETE.json')marker=JSON.parse(text);}await parent.removeEntry(folder,{recursive:true});return {csv,manifestRows:manifest.filter(r=>r.type==='output').reduce((n,r)=>n+r.rows,0),marker,saved};});
 assert.equal(initial.csv,'id,key,payload\n0,0,x\n1,0,x\n');assert.equal(initial.manifestRows,2);assert.deepEqual(initial.marker,{complete:true,files:initial.saved,engine:'chopper-browser',version:1});
 const lastObserved=await page.evaluate(base=>{
  const {ExecutionHistory,PhysicalHistory,renderExecutionHistory}=window.boundsModule,results=[];
  for(const [index,status] of ['interrupted','unknown'].entries()){
   const history=new ExecutionHistory(999990+index,{...base,operations:[{type:'shuffle',strategy:'uniform'}]}),physical=new PhysicalHistory();
   physical.accept({id:1043,kind:'merge_traversal',operations:[1,0],rows:10,seconds:.1,status:'completed',attempt:1,source_omitted:true});
   physical.accept({id:1043,kind:'merge_traversal',operations:[1,0],rows:65536,seconds:1,status:'active',attempt:3,source_omitted:true});
   physical.accept({id:1023,kind:'gzip_input',operations:[0,0],rows:0,bytes:5,seconds:.1,status:'completed',attempt:2,source_omitted:true});
   physical.accept({id:1023,kind:'gzip_input',operations:[0,0],rows:0,bytes:1048576,seconds:1,status:'active',attempt:4,source_omitted:true});
   history.accept(history.run,{physical:physical.snapshot()});renderExecutionHistory(history);const before=document.querySelector('.execution-list').textContent;
   history.interrupt(status);renderExecutionHistory(history);const after=document.querySelector('.execution-list').textContent,afterDescription=[...document.querySelectorAll('.execution-list li>button')].map(node=>node.getAttribute('aria-label')).join(' ');
   physical.accept({id:1043,kind:'merge_traversal',operations:[1,0],rows:131072,seconds:2,status:'interrupted',attempt:3,source_omitted:true});
   physical.accept({id:1023,kind:'gzip_input',operations:[0,0],rows:0,bytes:2097152,seconds:2,status:'failed',attempt:4,source_omitted:true});
   history.accept(history.run,{physical:physical.snapshot()});renderExecutionHistory(history);results.push({status,before,after,afterDescription,afterTerminal:[...document.querySelectorAll('.execution-list li>button')].map(node=>node.getAttribute('aria-label')).join(' '),confirmedAttempts:history.steps.map(step=>step.completed_attempts)});
  }return results;
 },base);
 for(const result of lastObserved){assert.match(result.before,/65,546 row visits/);assert.match(result.before,/1,048,581 bytes/);assert.match(result.after,/65,546 row visits/,'shutdown preserves cumulative last observed physical rows');assert.match(result.after,/1,048,581 bytes/,'shutdown preserves cumulative last observed physical bytes');assert.match(result.afterDescription,/last observed/);assert.match(result.afterDescription,/10 row visits confirmed completed/);assert.match(result.afterDescription,/5 decoded CSV bytes confirmed completed/);assert.deepEqual(result.confirmedAttempts,[1,1]);assert.match(result.afterTerminal,/Interrupted · 131,072 row visits/);assert.match(result.afterTerminal,/Failed · 2,097,152 decoded CSV bytes/);}
 const saturation=await page.evaluate(base=>{
  const {ExecutionHistory,ObservationDelivery,PhysicalHistory,renderExecutionHistory,TimingGapWriter,reasons}=window.boundsModule,max=Number.MAX_SAFE_INTEGER;
  const columns=Array.from({length:16},(_,i)=>'c'.repeat(62)+String(i).padStart(2,'0')),groups=Array.from({length:16},(_,i)=>({name:'g'.repeat(62)+String(i).padStart(2,'0'),percent:'6.25'}));
  const history=new ExecutionHistory(1000000,{...base,operations:Array.from({length:16},()=>({type:'assign',groups,strata:columns})),limits:{rows:max,bytes:max,compressed_bytes:null}}),physical=new PhysicalHistory(),credit=new Int32Array(new SharedArrayBuffer(4)),sent=[],delivery=new ObservationDelivery(history.run,credit,message=>sent.push(message));
  for(let i=0;i<1152;i++)for(const [outcome,status] of ['completed','interrupted','failed','handed_off'].entries()){
   const fact={id:1000+i,role:Math.floor(i/576),kind:'exact_membership',operations:[i%17+1,0],rows:max,bytes:max,seconds:1e-292,status,source_omitted:false,sources:[0,1,2,3],attempt:10000+i*4+outcome,groups:16,empty_groups:0,membership_len:16,memberships:Array(16).fill(max),omitted_memberships:max};physical.accept(fact);delivery.recordPhysical(fact);
  }
  // Conservatively charge all reason counters on every retained identity.
  const summaries=physical.snapshot().map(summary=>({...summary,reasons:Object.fromEntries(reasons.map(reason=>[reason,max]))}));
  const full={physical:summaries,read:{status:'completed',rows:max,seconds:1e-292},write:{status:'completed',rows:max,seconds:1e-292},export:{status:'completed',files:max},marker:{status:'completed'}};delivery.update(full);for(let i=0;i<10000;i++)delivery.update({read:{status:'active',rows:i,seconds:1}});delivery.update(full);
  const payload=delivery.snapshot();
  // Fill the fixed identity envelope and exercise separately delivered gaps.
  const gaps=new TimingGapWriter(buffer=>history.addTimingGapBlock(history.run,buffer));
  for(const window of payload.timeline)if(window.step>=1000){window.start=0;window.last=7;}
  for(let i=0;i<6;i++)for(const window of payload.timeline)if(window.step>=1000){
   gaps.record(window.step,i+.123456789012345,i+.987654321098765);
  }
  payload.timeline_seconds=Math.max(payload.timeline_seconds,7);
  history.accept(history.run,structuredClone(payload));history.interrupt('unknown');renderExecutionHistory(history);const panel=document.getElementById('execution-history');panel.open=true;
  // Logical values only: numeric8, bool1, UTF16 text; fixed schema/code and JS
  // container/allocator overhead are excluded, so this is not a heap/RSS claim.
  function values(value){if(value===null||value===undefined)return 0;if(typeof value==='number')return 8;if(typeof value==='boolean')return 1;if(typeof value==='string')return value.length*2;if(Array.isArray(value))return value.reduce((n,x)=>n+values(x),0);return Object.values(value).reduce((n,x)=>n+values(x),0);}
  const graphPaths=[...panel.querySelectorAll('.execution-edge')],graphAttributeBytes=graphPaths.reduce((n,path)=>n+(path.getAttribute('d')||'').length*2,0);
  // Additional bounded layout/edge keys and DOM path strings, excluding allocator overhead.
  const graphLogical=256*history.steps.length+1024*graphPaths.length+graphAttributeBytes;
  panel.querySelector('[data-view="timeline"]').click();
  const serialized=new TextEncoder().encode(JSON.stringify(payload)).length,domText=panel.textContent.length*2,configuration=values(history.configured)+history.flow.length*2+values(history.allocationLabels)+values(history.explanationSettings),logical=graphLogical+5*values(payload)+domText+configuration+2048*history.steps.length+32768+8192+1024+2312;
  const result={serialized_bytes:serialized,event_serialized_bytes:new TextEncoder().encode(JSON.stringify({events:payload.events,eventsOmitted:payload.eventsOmitted})).length,logical_payload_bytes:logical+384*history.steps.length,dom_text_bytes:domText,dag_edges:graphPaths.length,dag_logical_bytes:graphLogical,cards:panel.querySelectorAll('.execution-list li').length,timeline_rows:panel.querySelectorAll('button[data-timeline-step]').length,timeline_windows:history.timeline.size,timeline_bars:panel.querySelectorAll('.execution-timeline-bar').length,timeline_gaps:[...history.timingGaps.byStep.values()].reduce((count,row)=>count+row.length,0),events:panel.querySelectorAll('.execution-events li').length,omitted:history.eventsOmitted,queued_messages:sent.length,credit:Atomics.load(credit,0),physical:history.steps.length};window.boundsPayload=payload;
  history.accept(history.run,{physical:[{...payload.physical[0],id:2152}],events:[...payload.events,{index:128,step:1000,seconds:1,kind:'completed'}]});renderExecutionHistory(history);result.after_overflow=panel.querySelectorAll('.execution-list li').length;result.unavailable=history.unavailable;return result;
 },base);
 assert.equal(saturation.timeline_rows,1156);assert.equal(saturation.timeline_windows,1156);assert.equal(saturation.timeline_gaps,1152*6);assert.equal(saturation.timeline_bars,1156+saturation.timeline_gaps);
 assert.equal(saturation.cards,1156);assert.ok(saturation.dag_edges<=1156*4);assert.equal(saturation.after_overflow,1156);assert.equal(saturation.events,0);assert.ok(saturation.omitted>0);assert.equal(saturation.queued_messages,1);assert.equal(saturation.credit,1);assert.equal(saturation.unavailable,true);assert.ok(saturation.serialized_bytes<=4*1024*1024);assert.ok(saturation.event_serialized_bytes<=32768);assert.ok(saturation.logical_payload_bytes<=32*1024*1024,JSON.stringify(saturation));
 // A real 32MiB Run continues with observation credit deliberately withheld.
 await page.evaluate(()=>{window.boundsSource='id,key,payload\n'+Array.from({length:100000},(_,i)=>`${i},0,${'x'.repeat(16)}\n`).join('');window.holdCredit=true;window.boundsPaused=false;});await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();await configure([],'bounds-cancel');await page.locator('#run-direct').click();await page.waitForFunction(()=>window.boundsPaused);
 const active=await page.evaluate(()=>{const h=window.boundsModule.executionHistory;h.accept(h.run,{physical:window.boundsPayload.physical.map(step=>({...step,status:'active',last_attempt:step.last_attempt+100000,last_terminal:0})),events:[...h.events,...window.boundsPayload.events.map((event,index)=>({...event,index:h.events.length+index,seconds:(h.events.at(-1)?.seconds??0)+event.seconds+1}))].slice(0,128),eventsOmitted:window.boundsPayload.eventsOmitted});window.boundsModule.renderExecutionHistory(h);document.getElementById('execution-history').open=true;return {steps:h.steps.length,heldAcks:window.heldAcks};});assert.ok(active.steps>=1152);assert.ok(active.heldAcks>0);
 const start=performance.now();await page.locator('#cancel').click();await page.waitForFunction(()=>document.getElementById('status').textContent==='CANCELLED',{},{timeout:5000});const cancellationMs=performance.now()-start;assert.ok(cancellationMs<5000);assert.match(await page.locator('.execution-list li>button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')).join(' ')),/interrupted.*last observed/);
 const remaining=await page.evaluate(async()=>{window.holdCredit=false;const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.boundsParent),names=[];for await(const [name,handle]of parent.entries())names.push(name);await(await navigator.storage.getDirectory()).removeEntry(window.boundsParent,{recursive:true});return names;});assert.deepEqual(remaining,[],'processing cancellation published no destination marker/output');
 const hashes={};for(const name of ['engine.wasm','engine-worker.js','storage-worker.js','app.js'])hashes[name]=createHash('sha256').update(await readFile(root+'ui/dist/'+name)).digest('hex');console.log(JSON.stringify({browserVersion,browserChannel,hashes,adapter_sha256:createHash('sha256').update(adapter).digest('hex'),harness_sha256:createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex'),scope:'real Run/output and cancellation; synthetic focused state/render saturation supplements production strategy fixtures; no heap/RSS cap',saturation,cancellationMs,held_observation_acknowledgement:true},null,2));
});
