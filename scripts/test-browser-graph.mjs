// Public page Run; real processing/storage workers, WASI and OPFS.
import {withHostedBrowser,revealFormControl,installGraphWorkerProbe,freshDirectRunTerminal} from './browser-acceptance.mjs';
import {browserChannel,smallContractPacket} from './browser-launch.mjs';
import {codecFixture as runCodecFixture} from './browser-graph-codec.mjs';
import assert from 'node:assert/strict';
import {gzipSync,gunzipSync} from 'node:zlib';
const codecFixture=(mode,payload)=>runCodecFixture(mode,payload,smallContractPacket);
const reports=[];
const terminalDirect=process.argv.includes('--terminal-direct');
await withHostedBrowser({port:8423},async({context,url,browserVersion})=>{
 const page=await context.newPage();
 await page.addInitScript(installGraphWorkerProbe);
 await page.addInitScript(()=>{
  window.graphParent='graph-'+crypto.randomUUID();window.observationDisabled=false;
  window.graphSource='id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n';
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([window.graphSource],'fixture.csv')}];
  window.showDirectoryPicker=async()=> (await navigator.storage.getDirectory()).getDirectoryHandle(window.graphParent,{create:true});
 });
 await page.goto(url+'/');await page.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
 await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();await page.locator('#browse-output').click();
 const pending=page.waitForEvent('download');await page.locator('#export').click();const stream=await(await pending).createReadStream(),chunks=[];for await(const chunk of stream)chunks.push(chunk);
 const base=JSON.parse(Buffer.concat(chunks));
 const p={type:'partition',columns:['key']},u={type:'shuffle',strategy:'uniform'},fy={type:'shuffle',strategy:'fisher_yates'};
 const fixtures=[{name:'direct',operations:[],expected:/Write CSV/},{name:'partition',operations:[p],expected:/Group and materialize rows/},{name:'uniform',operations:[u],expected:/(?:Fused resident|Resident) random-key sort/},{name:'fisher-yates',operations:[fy],expected:/Resident Fisher/},{name:'fusion',operations:[p,u],expected:/(?:Fused resident|Resident) random-key sort.*operations 1, 2/},{name:'elision',operations:[u,u],expected:/Shuffle elided/},{name:'partition children',operations:[p,fy],expected:/Resident Fisher/},{name:'later elision',operations:[fy,p,u,u],expected:/Shuffle elided/}];
 const external=[{family:'external',name:'external spill',operations:[u],expected:/Traverse final merge/,source:'external',rows:80000,bytes:20000,max_record_bytes:1048576},{family:'external',name:'grouping fallback reuse',operations:[p],expected:/Reuse already ordered grouping files/,source:'fallback',rows:40000,bytes:20000,max_record_bytes:1048576},{family:'external',name:'hierarchical merge',operations:[p],expected:/Materialize hierarchical merge passes/,source:'hierarchy',rows:12,bytes:2097152,max_record_bytes:2097152,grouping:'sort'}];
 const groups=[{name:'treatment',percent:'50'},{name:'control',percent:'50'},{name:'zero',percent:'0'}];
 const exact=(strata=[])=>({type:'assign',groups,strata}),prob=(strata=[])=>({type:'assign_probabilistic',groups,strata});
 const allocation=[
  {family:'allocation',name:'exact allocation',operations:[exact()],expected:/Exact allocation/,quotas:{treatment:3,control:3,zero:0}},
  {family:'allocation',name:'exact strata',operations:[exact(['key'])],expected:/Strata ·.*Group and materialize strata/,quotas:{treatment:4,control:2,zero:0}},
  {family:'allocation',name:'probabilistic allocation',operations:[prob()],expected:/Probabilistic allocation/},
  {family:'allocation',name:'probabilistic strata',operations:[prob(['key'])],expected:/Probabilistic allocation/},
  {family:'allocation',name:'exact fused shuffle',operations:[exact(),u],expected:/(?:Fused resident|Resident) random-key sort.*operations 1, 2/,quotas:{treatment:3,control:3,zero:0}},
  {family:'allocation',name:'parent exact strata fused shuffle',operations:[p,exact(['key']),u],expected:/(?:Fused resident|Resident) random-key sort.*operations 2, 3/,quotas:{treatment:4,control:2,zero:0}},
  {family:'allocation',name:'parent probabilistic strata shuffle',operations:[p,prob(['key']),u],expected:/Probabilistic allocation/}
 ];
 const balanced=files=>({type:'balanced',files}),interleaved=files=>({type:'interleaved',files});
 const codecSource=Buffer.from('id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n');
 const corruptGzip=gzipSync(codecSource);corruptGzip[corruptGzip.length-8]^=1;
 fixtures.push({family:'codec',name:'gzip input',input:Array.from(gzipSync('id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n')),operations:[],expected:/Decode gzip input/},{family:'codec',name:'gzip output',compression:'gzip',operations:[],expected:/Compress gzip CSV/},{family:'codec',name:'Zstandard input',input:Array.from(codecFixture('zstd-input',Buffer.from('id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n'))),operations:[],expected:/Decode Zstandard input/},{family:'codec',name:'ZIP input',input:Array.from(codecFixture('zip-input',Buffer.from('id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n'))),operations:[],expected:/Read selected ZIP member/},{family:'codec',name:'Zstandard output',compression:'zstd',operations:[],expected:/Compress Zstandard CSV/},{family:'codec',name:'ZIP output',compression:'zip',operations:[],expected:/Build and finalize ZIP archive/},{family:'codec',name:'selected ZIP member',zip_member:'selected.csv',input:Array.from(codecFixture('zip-selected-input',codecSource)),operations:[],expected:/Read selected ZIP member/},
 {family:'codec',name:'gzip UTF-16 input',input_encoding:'utf-16le',input_decoded_bytes:64,input:Array.from(gzipSync(Buffer.concat([Buffer.from([255,254]),Buffer.from(codecSource.toString(),'utf16le')]))),operations:[],expected:/Decode gzip input/},
 {family:'codec',name:'gzip prepared output',compression:'gzip',operations:[p,u],expected:/Compress gzip CSV.*operations 3/},
 {family:'codec',name:'corrupt gzip input',input:Array.from(corruptGzip),operations:[],error:/checksum|corrupt/i},
 {family:'codec',name:'ambiguous ZIP input',input:Array.from(codecFixture('zip-selected-input',codecSource)),operations:[],error:/multiple CSV members/},...allocation,
  {family:'split',name:'shared balanced ranges',row_limit:3,operations:[balanced(2),fy],expected:/Share balanced row ranges/},
  {family:'split',name:'interleaved parts',operations:[interleaved(3)],expected:/Interleaved membership/},
  {family:'split',name:'balanced parts',operations:[balanced(3)],expected:/Emit consecutive balanced groups/},
  {family:'split',name:'nested balanced',operations:[balanced(2),balanced(2)],expected:/Share balanced row ranges/},
  {family:'split',name:'parent shared ranges',operations:[p,balanced(2),fy],expected:/Share balanced row ranges.*operations 2/},
  {family:'split',name:'parent balanced',operations:[p,balanced(2)],expected:/Emit consecutive balanced groups/},
  {family:'split',name:'parent interleaved',operations:[p,interleaved(2)],expected:/Interleaved membership/},
  {family:'split',name:'uniform split control',control:'uniform balanced fusion',seed:'graph-uniform balanced fusion',operations:[u],expected:/(?:Fused resident|Resident) random-key sort/},
  {family:'split',name:'uniform balanced fusion',operations:[u,balanced(3)],expected:/Split balanced groups during sorted traversal.*operations 2/},
  {family:'split',name:'parent split control',control:'parent uniform balanced fusion',seed:'graph-parent uniform balanced fusion',operations:[p,fy,u],expected:/(?:Fused resident|Resident) random-key sort/},
  {family:'split',name:'parent uniform balanced fusion',operations:[p,fy,u,balanced(2)],expected:/Split balanced groups during sorted traversal.*operations 4/},
  {family:'split',name:'balanced cap failure',operations:[balanced(2)],error:/balanced group cannot satisfy final row\/byte limits/},
  {family:'split',name:'balanced insufficient rows',operations:[p,balanced(4)],error:/cannot split 3 rows into 4/}
 );
 if(!process.argv.includes('--small-only'))fixtures.push(...external);
 const selectedFamily=process.argv.find(arg=>arg.startsWith('--family='))?.slice(9);
 if(process.argv.includes('--external')){for(let i=fixtures.length-1;i>=0;i--)if(fixtures[i].family!=='external')fixtures.splice(i,1);}
 if(selectedFamily){for(let i=fixtures.length-1;i>=0;i--)if(fixtures[i].family!==selectedFamily)fixtures.splice(i,1);}
 const splitControls=new Map();
 for(const fixture of fixtures){
  const exports=[];let observedGraph='';
  if(fixture.input){await page.evaluate(bytes=>window.graphSource=new Uint8Array(bytes),fixture.input);await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();}
  else if(fixture.source){await page.evaluate(kind=>{
   if(kind==='hierarchy'){const key='k'.repeat(1800000);window.graphSource='id,key\n'+Array.from({length:12},(_,id)=>`${id},${key}${String(id).padStart(2,'0')}\n`).join('');}
   else{const rows=kind==='fallback'?40000:80000;window.graphSource='id,key,payload\n'+Array.from({length:rows},(_,id)=>`${id},${kind==='fallback'&&id>=32000?id%96:id%3},${'x'.repeat(256)}\n`).join('');}
  },fixture.source);await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();}else{await page.evaluate(()=>window.graphSource='id,key\n1,a\n2,b\n3,a\n4,b\n5,a\n6,b\n');await revealFormControl(page,'#browse-input');await page.locator('#browse-input').click();}

  for(const disabled of [false,true]){
   const job={...base,compression:fixture.compression??base.compression,zip_member:fixture.zip_member??null,input_csv:{...base.input_csv,encoding:fixture.input_encoding??base.input_csv.encoding},operations:fixture.operations,limits:{rows:fixture.row_limit??(fixture.source?1000:2),bytes:fixture.bytes??20,compressed_bytes:null},resources:{...base.resources,memory_mb:32,workers:1,max_record_bytes:fixture.max_record_bytes??1048576,grouping:fixture.grouping??base.resources.grouping}};
   await page.evaluate(()=>document.getElementById('input').value='pending-import');
   await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});
   await page.waitForFunction(({input,count})=>document.getElementById('input').value===input&&document.querySelectorAll('#operations > .step').length===count,{input:job.input,count:job.operations.length});
   await page.evaluate(disabled=>window.observationDisabled=disabled,disabled);
   const serial=await page.evaluate(()=>window.graphRunSerial+1);await page.locator('#run-direct').click();
   const completion=await(await page.waitForFunction(freshDirectRunTerminal,serial,{timeout:180000})).jsonValue();
   if(fixture.error){assert.equal(completion.status,'failed');assert.match(completion.error,fixture.error);assert.equal(await page.locator('#status').textContent(),'FAILED');await page.waitForFunction(()=>window.graphWorkers.size===0);const error=await page.locator('#error').textContent();assert.match(error,fixture.error);if(fixture.family==='codec'){if(!disabled){const text=await page.locator('.execution-list').textContent();assert.match(text,/Failed/);assert.doesNotMatch(text,/partial row visits|partial rows/);}await page.evaluate(async()=>{const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.graphParent);for await(const [,handle]of parent.entries()){if(handle.kind!=='directory')continue;try{await handle.getFileHandle('CHOPPER-COMPLETE.json');throw Error('failed Run published a marker');}catch(error){if(error.name!=='NotFoundError')throw error;}}});}exports.push(error);continue;}
   assert.equal(completion.status,'complete');
   assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());
   if(!disabled){
    const panel=page.locator('#execution-history');const text=await panel.locator('.execution-list button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')).join(' '));assert.match(text,fixture.expected);observedGraph=text;
    if(fixture.operations.length){assert.match(text,new RegExp(`Serialize CSV \\[operations ${fixture.operations.length+1}\\]`));if((!fixture.compression||fixture.compression==='none')&&((fixture.operations.length===1&&fixture.operations[0].type==='balanced')||(terminalDirect&&fixture.operations.length===2&&fixture.operations[0].type==='shuffle'&&['auto','uniform'].includes(fixture.operations[0].strategy??'auto')&&fixture.operations[1].type==='balanced')))assert.doesNotMatch(text,/Materialize private results/);else assert.match(text,/Materialize private results/);assert.doesNotMatch(text,/Write CSV \[operation 1\]/);}
    assert.match(text,/confirmed/);if(fixture.input)assert.match(text,new RegExp(`${fixture.input_decoded_bytes??31} decoded CSV bytes`));
    if(fixture.compression==='zip'){const archive=(await panel.locator('.execution-list li>button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')))).find(text=>text.startsWith('Build and finalize ZIP archive'));assert.match(archive,/receives data from Deflate CSV members/);assert.doesNotMatch(archive,/receives data from Write CSV/);}
    if(fixture.source==='fallback'){assert.ok(await panel.locator('[data-step][data-status="handed_off"]').count()>0);assert.match(text,/Handed Off/);assert.match(text,/receives data from .*Reuse already ordered grouping files/);assert.match(text,/no re-sort/);}
    if(fixture.source){assert.match(text,/sorted runs/);assert.ok(await panel.locator('.execution-list li').count()<32,'external summaries must not grow per group/file');}
    if(fixture.family==='allocation'){const nodes=await panel.locator('.execution-list li>button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')));const strata=nodes.filter(text=>text.startsWith('Strata ·'));if(fixture.name.includes('probabilistic'))assert.equal(strata.length,0);for(const node of strata)assert.doesNotMatch(node,/operations \d+,/);
      const allocationNode=nodes.find(text=>text.startsWith('Exact allocation')||text.startsWith('Probabilistic allocation'));assert.ok(allocationNode?.includes('receives data from'),'membership input source must be observed');
      if(fixture.name.startsWith('parent'))assert.ok(nodes.some(text=>text.startsWith('Stage intermediate rows')&&/receives data from (Group and materialize rows|Read and materialize routed groups)/.test(text)),'partition artifact producer edge');
      if(fixture.name==='parent probabilistic strata shuffle')assert.ok(nodes.some(text=>text.startsWith('Resident random-key sort [operations 3]')&&text.includes('receives data from Stage intermediate rows')),'downstream sort consumes allocation artifact');
    }
    assert.match(await panel.locator('.execution-flow button').evaluateAll(buttons=>buttons.map(button=>button.getAttribute('aria-label')).join(' ')),new RegExp(`${fixture.operations.length+1}\\. CSV output`));
   }
   const result=await page.evaluate(async({bytes,rows,folder})=>{
    const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(window.graphParent);
    const directory=await parent.getDirectoryHandle(folder),csvs={},artifacts={};let manifest,marker,savedFiles=0;
    for await(const [name,handle]of directory.entries()){
     const file=await handle.getFile(),text=await file.text();if(name!=='CHOPPER-COMPLETE.json')savedFiles++;if(/\.(gz|zst|zip)$/.test(name))artifacts[name]=Array.from(new Uint8Array(await file.arrayBuffer()));
     if(name.endsWith('.csv')){if(file.size>bytes)throw Error('CSV byte cap');if(text.trimEnd().split('\n').length-1>rows)throw Error('CSV row cap');csvs[name]=text;}
     if(name==='manifest.jsonl')manifest=text.split('\n').filter(Boolean).map(line=>JSON.parse(line));
     if(name==='CHOPPER-COMPLETE.json')marker=JSON.parse(text);
    }
    await parent.removeEntry(folder,{recursive:true});return {csvs,manifest,marker,artifacts,savedFiles};
   },{bytes:fixture.bytes??20,rows:fixture.row_limit??(fixture.source?1000:2),folder:completion.folder});
   for(const [name,bytes]of Object.entries(result.artifacts)){
    if(name.endsWith('.gz'))result.csvs[name]=gunzipSync(Buffer.from(bytes)).toString('utf8');
    else if(name.endsWith('.zst'))result.csvs[name]=codecFixture('zstd-output',Buffer.from(bytes)).toString('utf8');
    else if(name.endsWith('.zip')){const members=JSON.parse(codecFixture('zip-output',Buffer.from(bytes)));for(const [path,member]of Object.entries(members)){if(path.endsWith('.csv'))result.csvs[path]=member.text;else if(path==='manifest.jsonl')assert.deepEqual(member.text.trim().split('\n').map(line=>JSON.parse(line)),result.manifest);}for(const record of result.manifest.filter(r=>r.type==='output'))assert.equal(record.stored_bytes,members[record.path].stored_bytes);}
   }
   for(const record of result.manifest.filter(r=>r.type==='output')){
    const csv=result.csvs[record.path];assert.equal(Buffer.byteLength(csv),record.csv_bytes);assert.ok(record.csv_bytes<=(fixture.bytes??20));assert.equal(csv.trimEnd().split('\n').length-1,record.rows);assert.ok(record.rows<=(fixture.row_limit??(fixture.source?1000:2)));if(result.artifacts[record.path])assert.equal(record.stored_bytes,result.artifacts[record.path].length);
   }
   if(fixture.compression&&!disabled){const csvBytes=Object.values(result.csvs).reduce((total,csv)=>total+Buffer.byteLength(csv),0);assert.ok(observedGraph.includes(`${csvBytes.toLocaleString()} encoded CSV bytes consumed`));if(fixture.compression==='zip'){const archiveBytes=result.artifacts['outputs.zip'].length;assert.ok(observedGraph.includes(`${archiveBytes.toLocaleString()} archive bytes`));assert.ok(observedGraph.includes(`${Object.keys(result.csvs).length+1} entries (manifest included)`));}}
   const records=Object.values(result.csvs).flatMap(csv=>csv.trimEnd().split('\n').slice(1));
   if(fixture.source){const ids=records.map(row=>Number(row.slice(0,row.indexOf(',')))).sort((a,b)=>a-b);assert.equal(ids.length,fixture.rows);assert.ok(ids.every((id,index)=>id===index));}
   else assert.deepEqual(records.sort(),['1,a','2,b','3,a','4,b','5,a','6,b']);
   if(fixture.family==='allocation'){
    const counts={treatment:0,control:0,zero:0};
    for(const record of result.manifest.filter(r=>r.type==='output')){const label=record.lineage.find(entry=>entry.allocation)?.allocation;if(label!=null)counts[label]+=result.csvs[record.path].trimEnd().split('\n').length-1;}
    assert.equal(counts.zero,0);assert.equal(counts.treatment+counts.control,6);if(fixture.quotas)assert.deepEqual(counts,fixture.quotas);
    if(!disabled)for(const [label,count]of Object.entries(counts))assert.ok(observedGraph.includes(`${label}: ${count}`),'observed membership count '+label);
   }
   if(fixture.family==='split'){
    const outputs=result.manifest.filter(record=>record.type==='output');
    if(['balanced parts','interleaved parts','shared balanced ranges'].includes(fixture.name)){
     const actual=outputs.map(record=>result.csvs[record.path].trimEnd().split('\n').slice(1).map(row=>Number(row.split(',')[0])));
     const expected=fixture.name==='balanced parts'?[[1,2],[3,4],[5,6]]:fixture.name==='interleaved parts'?[[1,4],[2,5],[3,6]]:[[1,2,3],[4,5,6]];
     if(fixture.name==='shared balanced ranges')actual.forEach(rows=>rows.sort((a,b)=>a-b));assert.deepEqual(actual,expected);
    }
    if(['nested balanced','parent balanced','parent interleaved','parent shared ranges'].includes(fixture.name)){
     const actual=outputs.map(record=>({parts:record.lineage.filter(entry=>entry.part).map(entry=>[entry.operation,entry.part]),ids:result.csvs[record.path].trimEnd().split('\n').slice(1).map(row=>Number(row.split(',')[0]))}));
     const ids=fixture.name==='nested balanced'?[[1,2],[3],[4,5],[6]]:['parent balanced','parent shared ranges'].includes(fixture.name)?[[1,3],[5],[2,4],[6]]:[[1,5],[3],[2,6],[4]];
     const parts=fixture.name==='nested balanced'?[[[0,1],[1,1]],[[0,1],[1,2]],[[0,2],[1,1]],[[0,2],[1,2]]]:[[[1,1]],[[1,2]],[[1,1]],[[1,2]]];
     if(fixture.name==='parent shared ranges')actual.forEach(group=>group.ids.sort((a,b)=>a-b));
     assert.deepEqual(actual,ids.map((value,index)=>({parts:parts[index],ids:value})));
    }
    const orderedRows=outputs.flatMap(record=>result.csvs[record.path].trimEnd().split('\n').slice(1));
    if(fixture.control)splitControls.set(fixture.control,orderedRows);
    if(fixture.name.includes('balanced fusion')){
     assert.deepEqual(orderedRows.toSorted(),splitControls.get(fixture.name).toSorted(),'fused split preserves independently verified parent records');
     const balancedStep=fixture.operations.length-1;
     assert.deepEqual(outputs.map(record=>record.lineage.find(entry=>entry.operation===balancedStep)?.part),fixture.name.startsWith('parent')?[1,2,1,2]:[1,2,3]);
     assert.deepEqual(outputs.map(record=>result.csvs[record.path].trimEnd().split('\n').length-1),fixture.name.startsWith('parent')?[2,1,2,1]:[2,2,2]);
    }
    if(!disabled&&!fixture.control){assert.match(observedGraph,/logical groups/);assert.match(observedGraph,/part 1:/);if(fixture.name==='shared balanced ranges'){assert.match(observedGraph,/6 frame lengths scanned/);assert.match(observedGraph,/0 framed rows written/);}}
   }
   assert.deepEqual(result.marker,{complete:true,files:result.savedFiles,engine:'chopper-browser',version:1});exports.push(result);
  }
  if(fixture.error){assert.equal(exports[0],exports[1]);reports.push({fixture:fixture.name,observed_disabled_semantics:true});continue;}
  // Independent randomized Runs need not share membership or order. Each export
  // above checks conservation, fields, lineage, quotas, caps and completion.
  if(!fixture.operations.some(op=>['shuffle','assign','assign_probabilistic'].includes(op.type))){
   assert.deepEqual(exports[0].csvs,exports[1].csvs);
   assert.deepEqual(exports[0].manifest[0].analysis.stages,exports[1].manifest[0].analysis.stages);
  }
  reports.push({fixture:fixture.name,observed_disabled_semantics:true});
 }
 await page.evaluate(async()=>{await(await navigator.storage.getDirectory()).removeEntry(window.graphParent,{recursive:true});});
 console.log(JSON.stringify({browserVersion,browserChannel,reports},null,2));
});
