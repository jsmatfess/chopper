// Real observed Auto shuffle -> country partition, matching the reported job.
import {withHostedBrowser} from './browser-acceptance.mjs';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const production=await readFile(new URL('../ui/dist/engine-worker.js',import.meta.url),'utf8');
// Pause on the producer fact before credit/coalescing can hide its ordering.
const wrapper=`import '/start-engine-production.js';const receive=globalThis.onmessage,send=globalThis.postMessage.bind(globalThis),parse=JSON.parse;let control=null,paused=false,serializationSeen=false;globalThis.onmessage=e=>{if(e.data.type==='run-direct')control=e.data.startControl;return receive.call(globalThis,e);};JSON.parse=(text,...args)=>{const value=parse(text,...args),fact=value?.physical;if(control&&fact?.kind==='serialize')serializationSeen=true;if(control&&!paused&&fact?.kind==='grouping'&&fact.status==='active'){paused=true;send({startPaused:true,serializationSeen});Atomics.wait(new Int32Array(control),0,0);}return value;};`;
await withHostedBrowser({port:8432},async({context,url,browserVersion})=>{
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 const headers={'Cross-Origin-Resource-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'};
 await page.route('**/start-engine-production.js',r=>r.fulfill({contentType:'application/javascript',headers,body:production}));
 await page.route('**/engine-worker.js',r=>r.fulfill({contentType:'application/javascript',headers,body:wrapper}));
 await page.addInitScript(()=>{
  window.startControl=new SharedArrayBuffer(4);window.startPaused=false;
  const Native=window.Worker;window.Worker=class extends Native{constructor(...args){super(...args);this.addEventListener('message',({data})=>{if(data.startPaused){window.startPaused=true;window.startSerializationSeen=data.serializationSeen;}});}postMessage(data,transfer=[]){super.postMessage(data.type==='run-direct'?{...data,startControl:window.startControl}:data,transfer);}};
  const input=new File(['id,country,payload\n'+Array.from({length:100003},(_,i)=>`${i},country${i%12},${'x'.repeat(512)}\n`).join('')],'fixture.csv');
  window.startParent='step-start-'+crypto.randomUUID();
  window.showOpenFilePicker=async()=>[{getFile:async()=>input}];
  window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle(window.startParent,{create:true});
 });
 await page.goto(url);await page.waitForFunction(()=>document.getElementById('status').textContent==='IDLE').catch(async error=>{throw new Error(`${error}\n${JSON.stringify({errors,status:await page.locator('#status').textContent(),connection:await page.locator('#connection').textContent()})}`);});
 await page.locator('#browse-input').click();await page.locator('#browse-output').click();
 const download=page.waitForEvent('download');await page.locator('#export').click();const chunks=[];for await(const chunk of await(await download).createReadStream())chunks.push(chunk);const base=JSON.parse(Buffer.concat(chunks));
 const job={...base,operations:[{type:'shuffle',strategy:'auto'},{type:'partition',columns:['country']}],resources:{...base.resources,memory_mb:128,workers:0}};
 await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});
 await page.locator('#run-direct').click();await page.waitForFunction(()=>window.startPaused);
 try{
  await page.waitForFunction(()=>document.querySelector('.execution-node-title')?.textContent==='Read input');
  const titles=await page.locator('.execution-node-title').allTextContents();
  assert.equal(await page.evaluate(()=>window.startSerializationSeen),false,'serialization must not be announced before grouping supplies output');
  assert(!titles.includes('Serialize CSV snapshot'),'writer setup must not display serialization before grouping supplies its first output row');
 }finally{await page.evaluate(()=>{Atomics.store(new Int32Array(startControl),0,1);Atomics.notify(new Int32Array(startControl),0);});}
 await page.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status').textContent),null,{timeout:120000});assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());
 assert(await page.locator('.execution-flow-strategy').filter({hasText:'external'}).count()>0,'fixture must exercise external sorting');
 const verified=await page.evaluate(async()=>{
  const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(startParent),name=document.getElementById('result-path').textContent.match(/chopper-results-[a-z0-9-]+/)[0],dir=await parent.getDirectoryHandle(name),seen=new Set();let marker=false,files=0;
  for await(const [name,h]of dir.entries()){
   if(name==='CHOPPER-COMPLETE.json'){if(!JSON.parse(await(await h.getFile()).text()).complete)throw Error('invalid marker');marker=true;}
   if(!name.endsWith('.csv'))continue;files++;let country;
   const lines=(await(await h.getFile()).text()).trimEnd().split('\n');if(lines.shift()!=='id,country,payload')throw Error('header changed');
   for(const line of lines){const [id,key,payload]=line.split(','),n=Number(id);if(!Number.isInteger(n)||n<0||n>=100003||seen.has(n)||key!==`country${n%12}`||payload!=='x'.repeat(512))throw Error('row corruption');if(country&&country!==key)throw Error('partition mixing');country=key;seen.add(n);}
  }
  if(!marker||seen.size!==100003||files!==12)throw Error('incomplete output');await root.removeEntry(startParent,{recursive:true});return {rows:seen.size,files};
 });assert.deepEqual(errors,[]);console.log(JSON.stringify({browserVersion,...verified,writer_setup_hidden:true,paused_at_group_input:true,external_sort:true},null,2));
});
