// Bounded hosted complete-job observation experiment. Not a public Job option.
import {readFile,writeFile,mkdir,open,readdir,stat,statfs,readlink} from 'node:fs/promises';
import {createReadStream,openSync,writeSync,fsyncSync,closeSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join,resolve,relative} from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import {platform,release,arch,cpus,totalmem} from 'node:os';
import assert from 'node:assert/strict';
const root=process.cwd(),option=name=>process.argv.find(arg=>arg.startsWith('--'+name+'='))?.slice(name.length+3),planPath=resolve(option('plan')),out=resolve(option('out')),phase=option('phase'),plan=JSON.parse(await readFile(planPath,'utf8'));
assert.equal(plan.root,root);assert.ok(relative(root,out)&&!relative(root,out).startsWith('..'));await mkdir(out,{recursive:true});
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
async function hashFile(path){const h=createHash('sha256');for await(const chunk of createReadStream(path))h.update(chunk);return h.digest('hex');}
async function treeBytes(path){let bytes=0;for(const entry of await readdir(path,{withFileTypes:true})){const name=join(path,entry.name);if(entry.isDirectory())bytes+=await treeBytes(name);else if(entry.isFile())bytes+=(await stat(name)).size;}return bytes;}
function append(file,record){const fd=openSync(join(out,file),'a');try{writeSync(fd,JSON.stringify(record)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
async function guard(){let used=await treeBytes(out);for(const path of plan.additional_owned_roots??[])used+=await treeBytes(resolve(root,path));const disk=await statfs(out);if(used>plan.storage_limit_bytes||Number(disk.bavail)*Number(disk.bsize)<plan.free_reserve_bytes)throw Error('Owned storage/free-space guard failed');return used;}
if(phase==='prepare'){
 const fixtures={};await mkdir(join(out,'fixtures'),{recursive:true});
 for(const w of plan.workloads){
  const path=join(out,'fixtures',w.id+'.csv'),file=await open(path,'wx');let chunk='id,key,payload\n';const payload='x'.repeat(w.payload);
  try{for(let id=0;id<w.rows;id++){chunk+=`${id},${id%w.groups},${payload}\n`;if(chunk.length>=1048576){await file.write(chunk);chunk='';}}if(chunk)await file.write(chunk);await file.sync();}finally{await file.close();}
  fixtures[w.id]={path:relative(root,path),sha256:await hashFile(path),bytes:(await stat(path)).size,rows:w.rows,payload:w.payload,groups:w.groups};await guard();
 }
 await writeFile(join(out,'fixtures.json'),JSON.stringify(fixtures,null,2)+'\n');process.exit(0);
}
if(phase!=='measure')throw Error('Expected prepare or measure phase');
await(await open(join(out,'raw.jsonl'),'wx')).close();
const fixtureRoot=resolve(option('fixtures')),fixtures=JSON.parse(await readFile(join(fixtureRoot,'fixtures.json'),'utf8'));
for(const w of plan.workloads)assert.equal(await hashFile(resolve(root,fixtures[w.id].path)),fixtures[w.id].sha256);
const {chromium}=await import(pathToFileURL(join(root,'ui/node_modules/playwright/index.mjs'))),{browserChannel,browserLaunchOptions}=await import(pathToFileURL(join(root,'scripts/browser-launch.mjs'))),{assertProductionWasm}=await import(pathToFileURL(join(root,'scripts/browser-artifacts.mjs')));
assert.equal(platform(),'linux','This benchmark currently attests browser executables through Linux/WSL process identities.');
assert.equal(browserChannel,'bundled-chromium','This benchmark requires bundled Chromium for exact executable provenance.');
assertProductionWasm(await readFile(join(root,'ui/dist/engine.wasm')));
const assets={};for(const name of ['engine.wasm','engine-worker.js','storage-worker.js','app.js','style.css','index.html'])assets[name]=await hashFile(join(root,'ui/dist',name));
const evidenceContext={kind:'context',date:new Date().toISOString(),plan_sha256:await hashFile(planPath),harness_sha256:await hashFile(new URL(import.meta.url)),assets,fixtures,environment:{platform:platform(),release:release(),arch:arch(),logical_cpus:cpus().length,memory_bytes:totalmem(),node:process.version,browserChannel,browser_launcher_reported_executable:chromium.executablePath(),browser_identity_method:'CDP browser PID and /proc/PID/exe',storage:'fresh persistent Chromium profile per matched block; OPFS input/workspace/destination',cache:'input copied before block; no OS cache flush; mode order balanced; no cross-platform or physical-I/O claim',timer:'primary page performance.now from public Run click through authoritative successful Run reply after destination export/marker; public COMPLETE after cleanup/polling recorded separately',memory_scope:'no browser RSS or working-reservation inference from page data'}};
const server=spawn(process.execPath,[join(root,'scripts/serve-hosted.mjs')],{env:{...process.env,PORT:String(plan.port)},stdio:['ignore','pipe','inherit']});let context,selectedBrowserIdentity;const started=Date.now();
try{
 await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);});
 for(const block of plan.blocks){
  if(Date.now()-started>plan.deadline_seconds*1000)throw Error('Batch deadline before block');await guard();
  const w=plan.workloads.find(w=>w.id===block.workload),fixture=fixtures[w.id];assert.ok(w);
  const profile=join(out,'profiles',block.id);await mkdir(profile,{recursive:true});context=await chromium.launchPersistentContext(profile,{...browserLaunchOptions,viewport:{width:1280,height:900}});const page=context.pages()[0]??await context.newPage();
  const cdp=await context.browser().newBrowserCDPSession();let browserPid;
  try{browserPid=(await cdp.send('SystemInfo.getProcessInfo')).processInfo.find(process=>process.type==='browser')?.id;}finally{await cdp.detach();}
  assert.ok(Number.isSafeInteger(browserPid)&&browserPid>0&&browserPid!==process.pid);
  const executable=await readlink('/proc/'+browserPid+'/exe'),browserIdentity={executable,sha256:await hashFile(executable),version:context.browser().version()};
  if(!selectedBrowserIdentity){selectedBrowserIdentity=browserIdentity;Object.assign(evidenceContext.environment,{browser_executable:executable,browser_executable_sha256:browserIdentity.sha256,browser_version:browserIdentity.version});append('raw.jsonl',evidenceContext);}else assert.deepEqual(browserIdentity,selectedBrowserIdentity,'Selected browser executable changed between matched blocks');
  append('raw.jsonl',{kind:'browser_identity',block:block.id,pid:browserPid,...browserIdentity});
  await page.addInitScript(()=>{
   window.benchDisabled=false;window.benchExpanded=false;window.benchStart=null;window.benchEnd=null;window.benchExportEnd=null;window.benchRunning=false;window.benchViewportSet=false;window.benchParent='graph-benchmark-'+crypto.randomUUID();
   const Native=window.Worker;window.Worker=class extends Native{constructor(...args){super(...args);this.addEventListener('message',({data})=>{if(window.benchStart!==null&&data.id&&data.result?.output)window.benchExportEnd=performance.now();});}postMessage(data,transfer=[]){super.postMessage(window.benchDisabled&&data.type==='run-direct'?{...data,observationCredit:undefined}:data,transfer);}};
   window.showOpenFilePicker=async()=>[{getFile:async()=>{const dir=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.benchParent);return await(await dir.getFileHandle('input.csv')).getFile();}}];window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle(window.benchParent);
   new MutationObserver(()=>{const panel=document.getElementById('execution-history');if(panel&&window.benchExpanded){panel.open=true;if(!window.benchViewportSet){panel.querySelector('.execution-viewport')?.scrollIntoView({block:'center'});window.benchViewportSet=true;}}const status=document.getElementById('status')?.textContent;if(window.benchStart!==null){if(status==='RUNNING')window.benchRunning=true;if(window.benchRunning&&['COMPLETE','FAILED'].includes(status)&&window.benchEnd===null)window.benchEnd=performance.now();}}).observe(document,{subtree:true,childList:true,characterData:true});
  });
  await page.goto(`http://127.0.0.1:${plan.port}/`);await page.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
  await page.evaluate(async()=>{const dir=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.benchParent,{create:true});window.benchWriter=await(await dir.getFileHandle('input.csv',{create:true})).createWritable();});
  // Transfer bounded chunks outside the measured Run. The picker returns an OPFS-backed File.
  for await(const chunk of createReadStream(resolve(root,fixture.path),{highWaterMark:1048576}))await page.evaluate(async base64=>{const text=atob(base64),bytes=new Uint8Array(text.length);for(let i=0;i<text.length;i++)bytes[i]=text.charCodeAt(i);await window.benchWriter.write(bytes);},chunk.toString('base64'));
  await page.evaluate(async()=>{await window.benchWriter.close();delete window.benchWriter;});await page.locator('#browse-input').click();await page.locator('#browse-output').click();
  const download=page.waitForEvent('download');await page.locator('#export').click();const chunks=[];for await(const chunk of await(await download).createReadStream())chunks.push(chunk);const base=JSON.parse(Buffer.concat(chunks));
  for(const mode of block.modes){
   const sample=block.id+'-'+mode,job={...base,seed:'execution-graph-overhead-'+w.id,operations:w.operations,compression:'none',limits:{rows:null,bytes:plan.csv_byte_cap,compressed_bytes:null},resources:{...base.resources,memory_mb:w.memory_mb,workers:1,max_record_bytes:1048576,max_files:100000,temp_bytes:plan.temp_bytes??base.resources.temp_bytes}};
   append('raw.jsonl',{kind:'attempt',sample,block:block.id,workload:w.id,mode,state:'started',job,job_sha256:sha(JSON.stringify(job)),input_sha256:fixture.sha256,browserVersion:context.browser().version(),storage_estimate_before:await page.evaluate(async()=>await navigator.storage.estimate()),owned_bytes_before:await guard()});
   try{
    await page.evaluate(()=>document.getElementById('seed').value='pending-benchmark-import');await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(seed=>document.getElementById('seed').value===seed,job.seed);
    await page.evaluate(mode=>{window.benchDisabled=mode==='disabled';window.benchExpanded=mode==='expanded';const panel=document.getElementById('execution-history');if(panel){panel.open=window.benchExpanded;const advanced=panel.querySelector('[data-advanced]');if(advanced?.getAttribute('aria-pressed')==='true')advanced.click();const graph=panel.querySelector('[data-view="graph"]');if(graph?.getAttribute('aria-pressed')==='false')graph.click();}window.benchViewportSet=false;window.benchRunning=false;window.benchEnd=null;window.benchExportEnd=null;window.benchStart=performance.now();document.getElementById('run-direct').click();},mode);
    await page.waitForFunction(()=>window.benchEnd!==null,{},{timeout:plan.job_deadline_seconds*1000});
    const measurement=await page.evaluate(()=>{const viewport=document.querySelector('.execution-viewport')?.getBoundingClientRect();return ({elapsed_seconds:window.benchExportEnd===null?null:(window.benchExportEnd-window.benchStart)/1000,public_complete_seconds:(window.benchEnd-window.benchStart)/1000,status:document.getElementById('status').textContent,error:document.getElementById('error').textContent,graph:document.querySelector('.execution-list')?.textContent??'',cards:document.querySelectorAll('.execution-list [data-step]').length,events:document.querySelectorAll('.execution-events li').length,expanded:document.getElementById('execution-history')?.open??false,viewport_visible:!!viewport&&viewport.width>0&&viewport.top>=0&&viewport.bottom<=innerHeight,viewport_top:viewport?.top,viewport_bottom:viewport?.bottom});});
    append('raw.jsonl',{kind:'measurement',sample,block:block.id,workload:w.id,mode,...measurement});assert.equal(measurement.status,'COMPLETE',measurement.error);assert.ok(measurement.elapsed_seconds>0&&measurement.elapsed_seconds<=measurement.public_complete_seconds,'authoritative export completion precedes public cleanup/poll completion');if(mode!=='disabled'){assert.match(measurement.graph,new RegExp(w.expected));assert.ok(measurement.cards<=1156);assert.ok(measurement.events<=128);assert.equal(measurement.expanded,mode==='expanded');if(mode==='expanded')assert.equal(measurement.viewport_visible,true,'expanded graph viewport must be visible during the measured Run');}
    const verification=await page.evaluate(async({w,cap})=>{
     const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.benchParent),folder=document.getElementById('result-path').textContent.match(/chopper-results-[a-z0-9-]+/)[0],dir=await parent.getDirectoryHandle(folder),seen=new Uint8Array(Math.ceil(w.rows/8)),groupCounts=Array(w.groups).fill(0),files=[];let rows=0,saved=0,marker,manifest;
     const hex=buffer=>Array.from(new Uint8Array(buffer),byte=>byte.toString(16).padStart(2,'0')).join('');
     for await(const [name,handle]of dir.entries()){
      if(handle.kind!=='file')throw Error('Unexpected output directory');if(files.length>8192)throw Error('Verification file bound');const file=await handle.getFile();if(name!=='CHOPPER-COMPLETE.json')saved++;
      if(name==='CHOPPER-COMPLETE.json'){if(file.size>256)throw Error('Marker size');marker=JSON.parse(await file.text());}
      else if(name==='manifest.jsonl'){if(file.size>8*1024*1024)throw Error('Manifest verification bound');manifest=(await file.text()).trim().split('\n').map(JSON.parse);}
      else if(name.endsWith('.csv')){
       if(file.size>cap)throw Error('Strict CSV cap');let pending='',header=true,count=0,group=null,part=null;const reader=file.stream().pipeThrough(new TextDecoderStream()).getReader();
       function row(line){if(header){if(line!=='id,key,payload')throw Error('Header');header=false;return;}const first=line.indexOf(','),second=line.indexOf(',',first+1),id=Number(line.slice(0,first)),key=Number(line.slice(first+1,second)),payload=line.slice(second+1);if(!Number.isSafeInteger(id)||id<0||id>=w.rows||key!==id%w.groups||payload.length!==w.payload||/[^x]/.test(payload))throw Error('Fixture field mismatch');const mask=1<<(id%8);if(seen[id>>3]&mask)throw Error('Duplicate ID');seen[id>>3]|=mask;groupCounts[key]++;rows++;count++;if(w.partitioned){if(group!==null&&group!==key)throw Error('Mixed partition output');group=key;}if(w.balanced_after_partition){const expectedPart=Math.floor(Math.floor(id/w.groups)/(w.rows/w.groups/w.balanced_after_partition))+1;if(part!==null&&part!==expectedPart)throw Error('Mixed balanced child membership');part=expectedPart;}}
       while(true){const {done,value}=await reader.read();if(done)break;pending+=value;let at;while((at=pending.indexOf('\n'))>=0){row(pending.slice(0,at));pending=pending.slice(at+1);}if(pending.length>w.payload+128)throw Error('Record verification bound');}if(pending)row(pending);
       files.push({name,bytes:file.size,rows:count,group,part,sha256:hex(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))});
      }else throw Error('Unexpected output '+name);
     }
     if(rows!==w.rows||!manifest||manifest.filter(record=>record.type==='output').reduce((sum,record)=>sum+record.rows,0)!==w.rows)throw Error('Row conservation');for(let key=0;key<w.groups;key++)if(groupCounts[key]!==Math.floor((w.rows-1-key)/w.groups)+1)throw Error('Group conservation');
     if(!marker||marker.version!==1||marker.engine!=='chopper-browser'||marker.complete!==true||marker.files!==saved||Object.keys(marker).length!==4)throw Error('Completion marker');
     const outputs=manifest.filter(record=>record.type==='output').sort((a,b)=>a.path.localeCompare(b.path));for(const record of outputs){const file=files.find(file=>file.name===record.path);if(!file||file.rows!==record.rows)throw Error('Manifest file agreement');if(w.balanced_after_partition&&record.lineage.find(entry=>entry.operation===1)?.part!==file.part)throw Error('Balanced lineage agreement');}if(outputs.length!==files.length)throw Error('Manifest file count');
     return {folder,rows,files:files.sort((a,b)=>a.name.localeCompare(b.name)),outputs,logical_digest:manifest[0].analysis.logical_digest,marker,groupCounts};
    },{w,cap:plan.csv_byte_cap});
    append('raw.jsonl',{kind:'verification',sample,block:block.id,workload:w.id,mode,...verification,ordered_artifact_sha256:sha(JSON.stringify({files:verification.files,outputs:verification.outputs,digest:verification.logical_digest}))});
    await page.evaluate(async folder=>{const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.benchParent);await parent.removeEntry(folder,{recursive:true});window.benchStart=null;},verification.folder);await guard();
   }catch(error){append('raw.jsonl',{kind:'failure',sample,block:block.id,workload:w.id,mode,message:String(error),stack:error.stack,profile,state:'failed; profile retained; dependent jobs stopped'});throw error;}
  }
  await page.evaluate(async()=>(await navigator.storage.getDirectory()).removeEntry(window.benchParent,{recursive:true}));await context.close();context=null;
 }
 append('raw.jsonl',{kind:'batch_complete',elapsed_seconds:(Date.now()-started)/1000,owned_bytes:await guard()});
}finally{await context?.close();server.kill();}
