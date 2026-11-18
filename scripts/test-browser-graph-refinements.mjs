// Real hosted Run for shuffle → partition → probabilistic allocation.
import {withHostedBrowser,revealFormControl} from './browser-acceptance.mjs';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
await withHostedBrowser({port:8431,viewport:{width:1280,height:900}},async({context,url,browserVersion})=>{
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(String(error)));
 await page.addInitScript(()=>{
  window.refinementParent='refinements-'+crypto.randomUUID();
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File(['id,country,segment\n'+Array.from({length:10003},(_,i)=>`${i},country${i%12},segment${Math.floor(i/12)%5}\n`).join('')],'fixture.csv')}];
  window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle(window.refinementParent,{create:true});
 });
 await page.goto(url);await page.waitForFunction(()=>document.getElementById('status').textContent==='IDLE');const theme=process.argv.find(arg=>arg.startsWith('--theme='))?.slice(8);if(theme&&await page.locator('.theme-control button').getAttribute('data-resolved')!==theme)await page.locator('.theme-control button').click();await page.locator('#browse-input').click();await page.locator('#browse-output').click();await page.waitForFunction(()=>document.getElementById('source-facts').textContent.includes('3 columns'));assert.match(await page.locator('#source-facts').textContent(),/KiB · 3 columns/);assert.equal(await page.locator('#source #preview-card').isVisible(),true);
 const download=page.waitForEvent('download');await page.locator('#export').click();const chunks=[];for await(const chunk of await(await download).createReadStream())chunks.push(chunk);const job=JSON.parse(Buffer.concat(chunks));
 job.operations=[{type:'shuffle',strategy:'auto'},{type:'partition',columns:['country','segment']},{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:[]}];
 await page.evaluate(()=>document.getElementById('input').value='pending-import');await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(input=>document.getElementById('input').value===input,job.input);
 await page.locator('#profile').click();await page.waitForFunction(()=>['PROFILED','FAILED'].includes(document.getElementById('status').textContent),null,{timeout:30000});
 assert.equal(await page.locator('#status').textContent(),'PROFILED',await page.locator('#error').textContent());assert.match(await page.locator('#input-profile').innerText(),/10,003/);assert.equal(await page.locator('#source #input-values').isVisible(),true);
 const inspectionCaptures=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);if(inspectionCaptures){await mkdir(inspectionCaptures,{recursive:true});await page.locator('#source').screenshot({path:inspectionCaptures+'/source-analysis.png'});await page.locator('#run-results').screenshot({path:inspectionCaptures+'/input-analysis.png'});}
 await page.locator('#max-bytes-unit').selectOption('MB');await page.locator('#max-bytes').fill('0.001');
 await revealFormControl(page,'#memory-unit');await page.locator('#memory-unit').selectOption('GiB');assert.equal(await page.locator('#memory').inputValue(),'0.25');await page.locator('#memory').evaluate(el=>el.closest('details').open=false);
 await page.locator('#run-direct').click();await page.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status').textContent),null,{timeout:120000});assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());
 const layout=await page.evaluate(()=>{
  const cards=[...document.querySelectorAll('.execution-graph li')],groups=new Map();
  for(const card of cards){const box=card.getBoundingClientRect(),heights=groups.get(box.top)||[];heights.push(box.height);groups.set(box.top,heights);}
  const find=title=>cards.find(card=>card.querySelector('.execution-node-title').textContent.startsWith(title));
  const allocation=find('Probabilistic allocation'),routing=cards.filter(card=>card.querySelector('.execution-node-title').textContent==='Bounded value grouping'&&card.querySelector('button').dataset.planTargets==='step-2')[0];
  return {legible:cards.every(card=>[...card.querySelectorAll('.execution-node-title,.execution-node-detail,.execution-node-status')].every(node=>parseFloat(getComputedStyle(node).fontSize)>=13)),rows:[...groups.values()],allocationX:allocation.getBoundingClientRect().left,routingX:routing.getBoundingClientRect().left,units:[...document.querySelectorAll('.execution-measurement')].map(node=>({text:node.textContent,lines:node.getClientRects().length,nowrap:getComputedStyle(node).whiteSpace})),sameRowPaths:[...document.querySelectorAll('.execution-edge')].filter(path=>{const a=findById(path.dataset.source),b=findById(path.dataset.target);return a&&b&&a.getBoundingClientRect().top===b.getBoundingClientRect().top;}).map(path=>path.getAttribute('d'))};
  function findById(id){return cards.find(card=>card.dataset.step===id);}
 });
 assert(layout.units.some(unit=>/ rows\/s$/.test(unit.text)),'row-processing cards show average throughput');
 assert(layout.legible,'graph labels and measurements are at least 13px');assert(layout.allocationX<layout.routingX,'membership precedes its bounded grouping consumer');for(const heights of layout.rows)assert(Math.max(...heights)-Math.min(...heights)<1,'cards within each activity row share height');assert.equal(await page.locator('.execution-node-percentage').count(),0);assert(layout.units.some(unit=>/\d\.\d\d s$/.test(unit.text)));assert(layout.units.every(unit=>unit.nowrap==='nowrap'&&unit.lines===1));assert(layout.sameRowPaths.length>0);assert(layout.sameRowPaths.every(path=>/^M [\d. ]+ L [\d. ]+$/.test(path)),'within-row links are straight');
 for(const width of [390,760,1280]){await page.setViewportSize({width,height:900});const heights=await page.locator('.inspection-actions button').evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().height));assert.equal(heights[0],heights[1],`action button heights at ${width}`);}
 for(const width of [1920,2560]){
  await page.setViewportSize({width,height:1000});
  await page.waitForFunction(()=>document.body.dataset.workspaceView==='execution');
  const graph=await page.locator('#execution-history').boundingBox(),plan=await page.locator('#output-plan').boundingBox();
  assert(plan.x>=graph.x+graph.width,'output plan sits beside the wide graph');
  await page.locator('.workspace-view-controls [data-workspace-view="configuration"]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='configuration');
  const sizes=await page.locator('#job-form').evaluate(form=>({form:form.getBoundingClientRect().width,count:document.getElementById('max-rows').getBoundingClientRect().width}));
  assert(sizes.form<=1041,'configuration editor stops growing on wide screens');assert(sizes.count<=193,'small numeric settings remain compact');
  await page.locator('.workspace-view-controls [data-workspace-view="execution"]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='execution');
 }
 const exported=await page.evaluate(async()=>{
  const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.refinementParent),folder=document.getElementById('result-path').textContent.match(/chopper-results-[a-z0-9-]+/)[0],dir=await parent.getDirectoryHandle(folder),ids=[];
  for await(const [name,handle] of dir.entries())if(name.endsWith('.csv')){const file=await handle.getFile();if(file.size>1000)throw Error('CSV exceeds the 0.001 MB limit');const rows=(await file.text()).trimEnd().split('\n').slice(1).map(row=>row.split(','));if(new Set(rows.map(row=>row.slice(1).join(','))).size!==1)throw Error('mixed partition membership');ids.push(...rows.map(row=>Number(row[0])));}
  await root.removeEntry(window.refinementParent,{recursive:true});return ids.sort((a,b)=>a-b);
 });assert.deepEqual(exported,Array.from({length:10003},(_,i)=>i));assert.deepEqual(errors,[]);
 await page.locator('[data-view="timeline"]').click();
 assert.equal(await page.locator('button[data-timeline-step]').count(),await page.locator('.execution-list li').count());
 assert.equal(await page.locator('.execution-timeline-empty').isVisible(),false);
 assert.equal(await page.locator('.execution-timeline table').evaluate(table=>[...table.querySelectorAll('th,td')].every(cell=>getComputedStyle(cell).color===getComputedStyle(table).color)),true,'timeline cells must retain the light foreground on their dark surface');
 assert.doesNotMatch(await page.locator('.execution-timeline').innerText(),/Timing unavailable|Start not observed/);
 const captured=await page.locator('.execution-timeline-elapsed').textContent();await page.waitForTimeout(300);assert.equal(await page.locator('.execution-timeline-elapsed').textContent(),captured,'completed timeline must freeze');
 const timelineScreenshot=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);
 if(timelineScreenshot){await mkdir(timelineScreenshot,{recursive:true});await page.setViewportSize({width:1280,height:1000});await page.locator('#execution-history').screenshot({path:timelineScreenshot+'/timeline.png'});await writeFile(timelineScreenshot+'/timeline-content.html',await page.locator('.execution-timeline').evaluate(el=>el.innerHTML));}
 await page.locator('[data-view="graph"]').click();
 const screenshot=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);if(screenshot){await mkdir(screenshot,{recursive:true});await page.locator('#execution-history').screenshot({path:screenshot+'/graph-refinements.png'});for(const width of [390,1280,1920]){await page.setViewportSize({width,height:1000});await page.locator('.results').screenshot({path:screenshot+`/results-${width}.png`});}await page.setViewportSize({width:1280,height:1000});await page.locator('.workspace-view-controls [data-workspace-view=configuration]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='configuration');await revealFormControl(page,'#memory-unit');await page.locator('#review').screenshot({path:screenshot+'/resource-units.png'});await page.locator('#output-settings').screenshot({path:screenshot+'/output-units.png'});}
 const captures=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);
 if(captures){
  await page.setViewportSize({width:1920,height:1100});await page.locator('.workspace-view-controls [data-workspace-view=execution]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='execution');await page.locator('.results').evaluate(el=>el.scrollTop=0);await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(350);await page.screenshot({path:captures+'/execution-desktop.png'});
  await page.locator('.workspace-view-controls [data-workspace-view=configuration]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='configuration');
  await page.locator('#execution-history').evaluate(el=>el.open=false);
  await page.locator('#job-form details').evaluateAll(nodes=>nodes.forEach(node=>node.open=false));
  for(const [name,width,height] of [['workbench-desktop',1920,1100],['workbench-mobile',390,844]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));
   await page.screenshot({path:captures+'/'+name+'.png',fullPage:true});
   await page.screenshot({path:captures+'/'+name+'-viewport.png',fullPage:false});
  }
 }
 console.log(JSON.stringify({browserVersion,rows:exported.length,activityRows:layout.rows.length,allocationBeforeRouting:true,equalHeights:true,unitsWrapTogether:true,linearRowLinks:true,friendlyUnitCsvCapBytes:1000},null,2));
});
