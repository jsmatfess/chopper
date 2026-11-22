import {stagedDestinationWorker} from './browser-destination-fixtures.mjs';
// Public hosted Run with production workers/WASI/OPFS; scoped test-only faults.
import {withHostedBrowser,revealFormControl} from './browser-acceptance.mjs';
import {browserChannel} from './browser-launch.mjs';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {gzipSync,gunzipSync} from 'node:zlib';
const composed=process.argv.includes('--composed');
import {createHash} from 'node:crypto';
import {assertProductionWasm} from './browser-artifacts.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const production=await readFile(root+'ui/dist/engine-worker.js','utf8');
const storageProduction=await readFile(root+'ui/dist/storage-worker.js','utf8');
const stagedWorker=await stagedDestinationWorker();
const wasm=await readFile(root+'ui/dist/engine.wasm');assertProductionWasm(wasm);
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const wrapper=`
import '/engine-worker-production.js';
let mode='success',observed=false,readbacks=0,closedCsv=0,prepared=false;
const send=globalThis.postMessage.bind(globalThis),receive=globalThis.onmessage;
function pause(phase){send({graphPaused:phase});Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0);}
globalThis.onmessage=event=>{if(event.data.type==='init'||event.data.type==='run-direct')mode=event.data.graphMode;if(event.data.type==='run-direct')prepared=!!event.data.job?.operations?.length;if(event.data.graphCrash){setTimeout(()=>{throw Error('fixture worker failure');},0);return;}return receive.call(globalThis,event);};
globalThis.postMessage=(message,...args)=>{
 if(message.observation){if(mode==='transport_throw')throw Error('fixture observation transport failure');if(mode==='loss_after_active'&&observed)return;observed=true;}
 if(mode==='loss_after_active'&&message.observationFinal){const {observationFinal,...rest}=message;message=rest;}
 if(mode==='marker_confirmed'&&(message.observation??message.observationFinal)?.marker?.status==='completed'){
  if(message.observationFinal)send({observationFinal:message.observationFinal,observationRun:message.observationRun,graphReadbacks:readbacks});else send({...message,graphReadbacks:readbacks},...args);
  pause('marker-confirmed');return;
 }
 send({...message,graphReadbacks:readbacks},...args);
 if(['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(mode)&&(!prepared&&message.progress?.rows>=65536||prepared&&message.observation?.physical?.some(step=>step.kind==='spill'&&step.status==='completed')))pause(prepared?'processing-spill':'processing');
};
const create=FileSystemFileHandle.prototype.createWritable;
FileSystemFileHandle.prototype.createWritable=async function(...args){
 const writer=await Reflect.apply(create,this,args),name=this.name;
 return new Proxy(writer,{get(target,key){const value=Reflect.get(target,key,target);
  if(key==='write')return async(...args)=>{
   if(mode==='marker_write'&&name==='CHOPPER-COMPLETE.json')throw Error('fixture marker write failure');
   if(mode==='worker_error'&&(name.endsWith('.csv')||name.endsWith('.gz'))&&closedCsv>0){send({graphPaused:'worker-ready'});return new Promise(()=>{});}
   return Reflect.apply(value,target,args);
  };
  if(key==='close')return async(...args)=>{
   if(mode==='result_close'&&(name.endsWith('.csv')||name.endsWith('.gz')))throw Error('fixture result close failure');
   if(mode==='marker_close'&&name==='CHOPPER-COMPLETE.json')throw Error('fixture marker close failure');
   const result=await Reflect.apply(value,target,args);if((name.endsWith('.csv')||name.endsWith('.gz')))closedCsv++;
   if(mode==='marker_closed'&&name==='CHOPPER-COMPLETE.json')pause('marker-closed');
   return result;
  };
  return typeof value==='function'?value.bind(target):value;
 }});
};
const get=FileSystemFileHandle.prototype.getFile;
FileSystemFileHandle.prototype.getFile=async function(...args){if(this.name==='CHOPPER-COMPLETE.json'){readbacks++;if(mode==='marker_read')throw Error('fixture marker readback failure');}return Reflect.apply(get,this,args);};
`;
const storageWrapper=`
import '/storage-worker-production.js';
const send=globalThis.postMessage.bind(globalThis),receive=globalThis.onmessage;
let failCleanup=false;
globalThis.onmessage=event=>{if(event.data.type==='cleanup')failCleanup=!!event.data.graphFailCleanup;return receive.call(globalThis,event);};
globalThis.postMessage=(message,...args)=>send(failCleanup&&message.cleaned?{error:'fixture temporary cleanup failure'}:message,...args);
`;
const reports=[],owned=[];
await withHostedBrowser({port:8425},async({context,url,browserVersion})=>{
 const headers={'Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'};
 await context.route('**/engine-worker-production.js',route=>route.fulfill({contentType:'application/javascript',headers,body:stagedWorker}));
 await context.route('**/engine-worker.js',route=>route.fulfill({contentType:'application/javascript',headers,body:wrapper}));
 await context.route('**/storage-worker-production.js',route=>route.fulfill({contentType:'application/javascript',headers,body:storageProduction}));
 await context.route('**/storage-worker.js',route=>route.fulfill({contentType:'application/javascript',headers,body:storageWrapper}));
 const page=await context.newPage();await page.addInitScript(()=>{
  window.graphParent='graph-lifecycle-'+crypto.randomUUID();window.graphMode='success';window.graphSource='id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n';window.graphWorkers=new Set();window.graphPaused=null;window.graphRunStarted=false;window.graphReadbacks=0;
  const Native=window.Worker,handler=Object.getOwnPropertyDescriptor(Native.prototype,'onmessage');window.Worker=class extends Native{
   constructor(url,options){super(url,options);this.graphMode=window.graphMode;this.graphEngine=String(url).endsWith('/engine-worker.js');window.graphWorkers.add(this);if(this.graphEngine)window.graphEngine=this;this.addEventListener('message',({data})=>{if(data.graphPaused)window.graphPaused=data.graphPaused;if(data.graphReadbacks!=null)window.graphReadbacks=data.graphReadbacks;});}
   set onmessage(callback){this.graphHandler=callback;handler.set.call(this,callback?event=>{if(this.graphEngine&&this.graphMode==='marker_late'&&(event.data.observation??event.data.observationFinal)?.marker?.status==='completed'){window.graphLate={handler:callback,data:event.data};window.graphPaused='marker-late';return;}callback(event);}:null);}
   get onmessage(){return this.graphHandler;}
   postMessage(data,transfer=[]){if(data.type==='run-direct')window.graphRunStarted=true;const message=data.type==='init'||data.type==='run-direct'?{...data,graphMode:window.graphMode}:data.type==='cleanup'?{...data,graphFailCleanup:window.graphRunStarted&&window.graphMode.startsWith('cleanup_error')}:data;super.postMessage(message,transfer);}
   terminate(){super.terminate();window.graphWorkers.delete(this);}
  };
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([window.graphSource],'fixture.csv')}];
  window.showDirectoryPicker=async()=> (await navigator.storage.getDirectory()).getDirectoryHandle(window.graphParent,{create:true});
 });
 await page.goto(url+'/');await page.waitForFunction(()=>document.getElementById('status').textContent==='IDLE');
 await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();await page.locator('#browse-output').click();owned.push(await page.evaluate(()=>window.graphParent));
 const download=page.waitForEvent('download');await page.locator('#export').click();const stream=await(await download).createReadStream(),chunks=[];for await(const chunk of stream)chunks.push(chunk);const base=JSON.parse(Buffer.concat(chunks));
 const modes=process.argv.find(arg=>arg.startsWith('--case='))?.slice(7).split(',')??['success','result_close','worker_error','marker_write','marker_close','marker_read','processing_cancel','marker_closed','marker_confirmed','marker_late','new_generation_cancel','transport_throw','loss_after_active','render_throw','cleanup_error_success','cleanup_error_cancel'];
 if(modes.includes('new_generation_cancel')&&!modes.slice(0,modes.indexOf('new_generation_cancel')).includes('marker_late'))modes.splice(modes.indexOf('new_generation_cancel'),0,'marker_late');
 for(const mode of modes){
  const parent='graph-lifecycle-'+crypto.randomUUID();owned.push(parent);
  await page.evaluate(({mode,parent})=>{window.graphMode=mode;window.graphParent=parent;window.graphPaused=null;window.graphLate=null;window.graphRunStarted=false;window.graphReadbacks=0;window.graphSource=['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(mode)?'id,key\n'+Array.from({length:100000},(_,i)=>`${i},a\n`).join(''):'id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n';}, {mode,parent});
  if(composed){await page.evaluate(()=>{if(['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(window.graphMode))window.graphSource='id,key,payload\n'+Array.from({length:100000},(_,id)=>`${id},a,${'x'.repeat(256)}\n`).join('');});const compressed=gzipSync(Buffer.from(await page.evaluate(()=>window.graphSource)));await page.evaluate(bytes=>window.graphSource=new Uint8Array(bytes),Array.from(compressed));}
  await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();await page.locator('#browse-output').click();
  const job={...base,operations:composed?[{type:'partition',columns:['key']},{type:'shuffle',strategy:'uniform'}]:[],compression:composed?'gzip':base.compression,limits:{rows:['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(mode)?10000:2,bytes:['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(mode)?1048576:20,compressed_bytes:null},resources:{...base.resources,memory_mb:32,workers:1,max_record_bytes:1048576}};
  await page.evaluate(()=>document.getElementById('input').value='pending-import');await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(input=>document.getElementById('input').value===input,job.input);
  if(mode==='render_throw')await page.evaluate(()=>{const original=Element.prototype.querySelector;window.graphRenderThrew=false;Element.prototype.querySelector=function(selector){if(window.graphRunStarted&&this.id==='execution-history'&&selector==='.execution-note'&&Reflect.apply(original,this,['.execution-list'])?.children.length>0&&!window.graphRenderThrew){window.graphRenderThrew=true;throw Error('fixture render failure');}return Reflect.apply(original,this,[selector]);};});
  await page.locator('#run-direct').click();
  let before=[],cancellationMs=null;
  if(['processing_cancel','new_generation_cancel','cleanup_error_cancel','marker_closed','marker_confirmed','marker_late','worker_error'].includes(mode)){
   await page.waitForFunction(()=>window.graphPaused!=null,{},{timeout:30000});before=await page.locator('.execution-list li>button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')));
   if(mode==='new_generation_cancel'){const unchanged=await page.evaluate(()=>{const before=document.getElementById('execution-history').textContent;for(let i=0;i<3;i++)window.graphPriorLate.handler({data:window.graphPriorLate.data});return before===document.getElementById('execution-history').textContent;});assert.equal(unchanged,true,'old real-worker confirmations cannot change the active new Run');}
   if(mode==='worker_error')await page.evaluate(()=>window.graphEngine.postMessage({graphCrash:true}));
   else{const start=Date.now();await page.locator('#cancel').click();await page.waitForFunction(()=>document.getElementById('status').textContent==='CANCELLED',{},{timeout:20000});cancellationMs=Date.now()-start;if(mode==='marker_late')await page.evaluate(()=>window.graphLate.handler({data:window.graphLate.data}));}
  }
  const expected=['result_close','marker_write','marker_close','marker_read','worker_error'].includes(mode)?'FAILED':['processing_cancel','new_generation_cancel','cleanup_error_cancel','marker_closed','marker_confirmed','marker_late'].includes(mode)?'CANCELLED':'COMPLETE';
  await page.waitForFunction(expected=>document.getElementById('status').textContent===expected&&(!['FAILED'].includes(expected)||!document.getElementById('error').hidden),expected,{timeout:30000});await page.waitForFunction(()=>window.graphWorkers.size===0);
  const nodes=await page.locator('.execution-list li>button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label'))),text=nodes.join(' '),note=await page.locator('.execution-note').textContent();
  const find=title=>nodes.find(node=>node.startsWith(title));
  for(const node of before.filter(node=>node.includes(' · Completed'))){const title=node.split(' · Completed')[0];assert.ok(nodes.some(after=>after.startsWith(title+' · Completed')),'confirmed work survives shutdown: '+title);}
  if(mode==='result_close'){assert.match(find('Save destination files'),/ · Failed/);assert.match(find(composed?'Serialize CSV':'Write CSV'),/ · Completed/);assert.equal(find('Confirm completion marker'),undefined);}
  if(mode==='worker_error'){assert.ok(!find('Save destination files')||/ · Unknown/.test(find('Save destination files')));assert.doesNotMatch(text,/Save destination files · Failed/);}
  if(['marker_write','marker_close'].includes(mode)){assert.match(find('Save destination files'),/ · Completed/);assert.match(find('Confirm completion marker'),/ · Failed/);}
  if(mode==='marker_read'){assert.match(find('Confirm completion marker'),/ · Failed/);assert.match(await page.locator('#error').textContent(),/verify completion marker/);assert.equal(await page.evaluate(()=>window.graphReadbacks),1);}
  if(mode==='marker_confirmed'||mode==='marker_late')assert.match(find('Confirm completion marker'),/ · Completed · confirmed/);
  if(mode==='marker_closed'){const marker=find('Confirm completion marker');if(marker){assert.match(marker,/interrupted|unknown/);assert.doesNotMatch(marker,/ · confirmed/);}assert.match(await page.locator('#execution-history summary').textContent(),/export unconfirmed/);}
  if(mode==='processing_cancel'||mode==='new_generation_cancel'||mode==='cleanup_error_cancel'){assert.match(text,/Interrupted/);assert.match(text,/last observed/);}
  if(mode==='transport_throw'||mode==='render_throw')assert.match(note,/unavailable/i);
  if(mode==='loss_after_active'){assert.match(note,/unavailable/i);assert.match(text,/Unknown.*last observed/);assert.ok(nodes.every(node=>!node.includes(' · Completed')));}
  if(mode==='render_throw')assert.equal(await page.evaluate(()=>window.graphRenderThrew),true);
  if(mode.startsWith('cleanup_error')){await page.waitForFunction(()=>document.getElementById('error').textContent.includes('fixture temporary cleanup failure'),{},{timeout:5000});assert.match(await page.locator('#error').textContent(),/fixture temporary cleanup failure/);if(mode==='cleanup_error_success')assert.match(find('Confirm completion marker'),/ · Completed · confirmed/);else assert.doesNotMatch(await page.locator('#result-path').textContent(),/temporary files cleaned/);}
  const snapshot=await page.evaluate(async parent=>{
   const root=await navigator.storage.getDirectory(),directory=await root.getDirectoryHandle(parent),folders=[];
   for await(const [name,handle]of directory.entries()){
    if(handle.kind!=='directory')continue;const files={};
    for await(const [fileName,fileHandle]of handle.entries()){if(fileHandle.kind!=='file')continue;try{const file=await fileHandle.getFile();files[fileName]={size:file.size,text:fileName.endsWith('.gz')?'':await file.text(),...(fileName.endsWith('.gz')?{bytes:Array.from(new Uint8Array(await file.arrayBuffer()))}:{})};}catch(error){if(error.name!=='NotFoundError')throw error;}}
    let marker;try{marker=JSON.parse(files['CHOPPER-COMPLETE.json']?.text);}catch{}
    const saved=Object.keys(files).filter(name=>name!=='CHOPPER-COMPLETE.json'&&!name.endsWith('.crswap')).length;
    const valid=files['CHOPPER-COMPLETE.json']?.size<=256&&marker?.complete===true&&marker.files===saved&&marker.engine==='chopper-browser'&&marker.version===1&&Object.keys(marker).length===4;
    folders.push({name,files,valid:!!valid});
   }return folders;
  },parent);
  const valid=['success','marker_read','marker_closed','marker_confirmed','marker_late','transport_throw','loss_after_active','render_throw','cleanup_error_success'].includes(mode);
  assert.equal(snapshot.some(folder=>folder.valid),valid,'independent marker validity for '+mode);
  if(['result_close','marker_write','marker_close'].includes(mode))assert.deepEqual(snapshot,[],'failed export folder removed');
  if(valid){
   const csvs=snapshot.flatMap(folder=>Object.entries(folder.files).filter(([name])=>name.endsWith('.csv')||name.endsWith('.gz')).map(([,file])=>{if(!file.bytes)return file;const decoded=gunzipSync(Buffer.from(file.bytes));return {size:decoded.length,text:decoded.toString('utf8')};}));assert.equal(csvs.length,composed?4:3);assert.ok(csvs.every(file=>file.size<=20&&file.text.trimEnd().split('\n').length-1<=2));assert.deepEqual(csvs.flatMap(file=>file.text.trimEnd().split('\n').slice(1)).sort(),['1,a','2,b','3,a','4,b','5,a','6,b']);
   const manifest=snapshot.flatMap(folder=>(folder.files['manifest.jsonl']?.text??'').trim().split('\n').filter(Boolean).map(line=>JSON.parse(line))).filter(record=>record.type==='output');assert.equal(manifest.length,composed?4:3);assert.equal(manifest.reduce((sum,record)=>sum+record.rows,0),6);
  }
  if(mode==='marker_late')await page.evaluate(()=>window.graphPriorLate=window.graphLate);
  if(composed&&mode==='success'){assert.match(text,/Decode gzip input/);assert.match(text,/Compress gzip CSV/);assert.match(text,/operations 1, 2/);}
  if(composed&&['processing_cancel','new_generation_cancel','cleanup_error_cancel'].includes(mode))assert.match(text,/Sort and write spill runs.*completed/);
  reports.push({mode,state:expected,marker_valid:valid,cancellation_ms:cancellationMs,confirmed_work_retained:true,...(mode==='new_generation_cancel'?{real_prior_generation_updates_rejected:true}:{})});
  await page.evaluate(async parent=>(await navigator.storage.getDirectory()).removeEntry(parent,{recursive:true}),parent);
 }
 for(const parent of owned)await page.evaluate(async parent=>{try{await(await navigator.storage.getDirectory()).removeEntry(parent,{recursive:true});}catch(error){if(error.name!=='NotFoundError')throw error;}},parent);
 console.log(JSON.stringify({binary_sha256:{engine:sha(wasm),worker:sha(production),storage:sha(storageProduction),app:sha(await readFile(root+'ui/dist/app.js'))},harness_sha256:sha(await readFile(fileURLToPath(import.meta.url))),staged_worker_sha256:sha(stagedWorker),worker_wrapper_sha256:sha(wrapper),storage_wrapper_sha256:sha(storageWrapper),browserVersion,browserChannel,composed,scope:'real hosted Run, production engine/workers, test-only faults; no reload persistence, scale or RSS claim',reports},null,2));
});
