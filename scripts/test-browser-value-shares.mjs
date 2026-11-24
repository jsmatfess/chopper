// Real WASI input analysis and completed Run: bounded frequencies and ranked shares.
import {withHostedBrowser} from './browser-acceptance.mjs';
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
await withHostedBrowser({port:8434,viewport:{width:1440,height:1050}},async({context,url})=>{
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(String(error)));
 await page.addInitScript(()=>{
  window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle('value-shares-fixture',{create:true});
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File(['id,cohort\n'+Array.from({length:120},(_,i)=>`${i},${i<80?'B':i<110?'A':''}\n`).join('')],'value-shares.csv')}];
 });
 await page.goto(url);await page.waitForFunction(()=>document.getElementById('status').textContent==='IDLE');await page.locator('#browse-input').click();await page.locator('#browse-output').click();
 const download=page.waitForEvent('download');await page.locator('#export').click();const chunks=[];for await(const chunk of await(await download).createReadStream())chunks.push(chunk);const job=JSON.parse(Buffer.concat(chunks));job.operations=[{type:'partition',columns:['cohort']}];
 await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(()=>document.querySelector('.step'));
 await page.locator('#profile').click();await page.waitForFunction(()=>['PROFILED','FAILED'].includes(document.getElementById('status').textContent));assert.equal(await page.locator('#status').textContent(),'PROFILED',await page.locator('#error').textContent());
 const cohort=page.locator('.column-values-row[data-column="1"]');
 async function checkShares(){
  await cohort.evaluate(el=>el.open=true);
  await cohort.locator('.value-share').first().waitFor();
  assert.deepEqual(await cohort.locator('.value-label').allTextContents(),['B','A','(empty)']);
  assert.deepEqual(await cohort.locator('.value-frequency').allTextContents(),['80','30','10']);
  assert.deepEqual(await cohort.locator('.value-share').allTextContents(),['66.7%','25%','8.3%']);
  assert.match(await cohort.innerText(),/Exact row counts and shares/);
 }
 await checkShares();assert.equal(await page.locator('.column-values-row[data-column="0"] .value-distribution').count(),0,'120 unique IDs omit shares');
 await page.locator('#run-direct').click();await page.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status').textContent));assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());await page.locator('.workspace-view-controls [data-workspace-view=configuration]').click();await page.waitForFunction(()=>document.body.dataset.workspaceView==='configuration');await checkShares();
 const captures=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);if(captures)await mkdir(captures,{recursive:true});
 await cohort.evaluate(el=>el.open=true);
 for(const theme of ['light','dark']){
  if(await page.locator('.theme-control button').getAttribute('data-resolved')!==theme)await page.locator('.theme-control button').click();
  for(const width of [390,1440]){await page.setViewportSize({width,height:1050});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);if(captures)await page.locator('#input-values').screenshot({path:`${captures}/values-${theme}-${width}.png`});}
 }
await page.evaluate(async()=>(await navigator.storage.getDirectory()).removeEntry('value-shares-fixture',{recursive:true}));assert.deepEqual(errors,[]);
 console.log('Real hosted value shares: Analyze + completed Run counts, descending order, empty values, high-cardinality omission, both themes and mobile passed.');
});
