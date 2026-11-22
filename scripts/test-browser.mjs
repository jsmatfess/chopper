import {serverLifetime,revealFormControl} from './browser-acceptance.mjs';
import {finishBrowserObservation} from './browser-small-observer.mjs';
// CI runner. The same contracts can be inspected interactively at /tests.html.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {browserChannel,launchContractBrowser,observeContractBrowser} from './browser-launch.mjs';
if(process.argv.slice(2).some(arg=>arg.includes('experimental-parallel-groups')||arg==='--parallel-groups')){
  throw new Error('Independent-parent batching/replay was removed; experimental-parallel-groups is unsupported.');
}
const server=spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:'8422'},stdio:['ignore','pipe','inherit']});
const serverOwner=serverLifetime(server,'http://127.0.0.1:8422',15000,5000);
let browser,context,observer,primary;
try {
  await serverOwner.ready;
  browser=await launchContractBrowser(chromium);context=await browser.newContext();const page=await context.newPage();
  observer=await observeContractBrowser(browser,context,'http://127.0.0.1:8422');
  const resources=process.argv.includes('--resource-contracts');
  const shufflePartition=process.argv.includes('--shuffle-partition');
  const spillBlocks=process.argv.includes('--spill-blocks');
  if(process.argv.includes('--random-buckets'))throw new Error('Removed independent bucket suite');
  if(shufflePartition&&!resources)throw new Error('--shuffle-partition requires --resource-contracts');
  if(spillBlocks&&!resources)throw new Error('--spill-blocks requires --resource-contracts');
  const query=new URLSearchParams();if(shufflePartition)query.set('shuffle-partition','1');if(spillBlocks)query.set('spill-blocks','1');
  await page.goto('http://127.0.0.1:8422/'+(resources?'resource-contract-tests.html':'tests.html')+(query.size?'?'+query:''));
  await page.waitForFunction(()=>window.testDone===true,{},{timeout:300000});
  const result=await page.evaluate(()=>({error:window.testError,tests:window.testResults,resourceContracts:window.resourceContracts}));
  result.browserVersion=browser.version();
  result.browserChannel=browserChannel;
  if(resources)result.resourceVariant=shufflePartition?'shuffle-partition':'base';
  if(!resources&&!result.error){
    const started=performance.now(),app=await context.newPage(),errors=[];
    app.on('pageerror',error=>errors.push(String(error)));
    try{
      await app.addInitScript(()=>{
        window.directSmokeParent='direct-ui-'+crypto.randomUUID();
        // Baseline changes only observation admission at the real worker API;
        // workers, WASI, OPFS, CSV execution and destination export remain real.
        window.observationDisabled=false;
        const RealWorker=window.Worker;
        window.Worker=class extends RealWorker {
          postMessage(message,transfer=[]){super.postMessage(window.observationDisabled&&message.type==='run-direct'?{...message,observationCredit:undefined}:message,transfer);}
        };
        const input=new File(['id,key\n1,a\n2,b\n'],'fixture.csv');
        window.showOpenFilePicker=async()=>[{getFile:async()=>input}];
        window.showDirectoryPicker=async()=>{
          const root=await navigator.storage.getDirectory();
          return root.getDirectoryHandle(window.directSmokeParent,{create:true});
        };
      });
      await app.goto('http://127.0.0.1:8422/');
      await app.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
      assert.equal(await app.locator('#run-direct').getAttribute('type'),'submit');
      assert.equal(await app.locator('#profile').getAttribute('type'),'button');
      assert.equal(await app.locator('#require-reproducible').count(),0);
      assert.equal(await app.locator('#memory-mode').inputValue(),'manual');
      assert.equal(await app.locator('#memory').inputValue(),'256');
      await revealFormControl(app,'#memory-mode');
      await app.locator('#memory-mode').selectOption('auto');
      assert.equal(await app.locator('#memory').isDisabled(),true);
      await app.locator('#browse-input').click();
      await app.waitForFunction(()=>document.getElementById('input').value==='fixture.csv');
      await app.locator('#browse-output').click();
      await app.waitForFunction(()=>document.getElementById('output').value.startsWith('direct-ui-'));
      await app.locator('#max-rows').fill('1');
      await app.locator('#max-bytes').fill('11');
      await app.locator('#run-direct').click();
      await app.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status')?.textContent),{},{timeout:30000});
      assert.equal(await app.locator('#status').textContent(),'COMPLETE',await app.locator('#error').textContent());
      const exported=await app.evaluate(async()=>{
        const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.directSmokeParent);
        const entries=[];for await(const [,handle]of parent.entries())entries.push(handle);
        if(entries.length!==1)throw new Error('Run did not create one result folder');
        const files=[];for await(const [,handle]of entries[0].entries())files.push(await handle.getFile());
        const csvs=await Promise.all(files.filter(f=>f.name.endsWith('.csv')).sort((a,b)=>a.name.localeCompare(b.name)).map(f=>f.text()));
        const csv=csvs[0]+csvs.slice(1).map(text=>text.slice(text.indexOf('\n')+1)).join('');
        const marker=JSON.parse(await files.find(f=>f.name==='CHOPPER-COMPLETE.json').text());
        const manifest=JSON.parse((await files.find(f=>f.name==='manifest.jsonl').text()).split('\n')[0]);
        await parent.removeEntry(entries[0].name,{recursive:true});
        return {csv,csvs,marker,manifest};
      });
      assert.equal(exported.csv,'id,key\n1,a\n2,b\n');assert.equal(exported.marker.complete,true);assert.equal(exported.marker.files,3);
      assert.deepEqual(exported.csvs,['id,key\n1,a\n','id,key\n2,b\n']);
      const panel=app.locator('#execution-history');
      assert.equal(await panel.getAttribute('open'),'');
      const cards=panel.locator('.execution-list li');
      assert.equal(await cards.count(),4);
      assert.match(await cards.nth(0).getByRole('button').getAttribute('aria-label'),/Completed.*2 rows/);
      assert.match(await cards.nth(1).getByRole('button').getAttribute('aria-label'),/operation 1.*Completed.*2 rows/);
      assert.match(await cards.nth(2).textContent(),/3 saved and closed files/);
      assert.match(await cards.nth(3).getByRole('button').getAttribute('aria-label'),/Completed.*confirmed/);
      const firstStep=cards.nth(0).getByRole('button');await firstStep.focus();assert.equal(await firstStep.evaluate(el=>el===document.activeElement),true);
      await revealFormControl(app,'#max-rows');await app.locator('#max-rows').fill('9');assert.match(await panel.locator('.execution-flow button').evaluateAll(buttons=>buttons.map(button=>button.getAttribute('aria-label')).join(' ')),/rows: 1/);
      await app.locator('#max-rows').fill('1');
      assert.equal(await app.locator('#seed').count(),0);
      assert.equal(Object.hasOwn(exported.manifest.config,'seed'),false);
      assert.equal(exported.manifest.config.resources.memory_mb,'auto');
      assert.ok(exported.manifest.analysis.memory_budget_bytes>0&&exported.manifest.analysis.memory_budget_bytes<=256*1024*1024);
      assert.equal(exported.manifest.analysis.algorithm_version,exported.manifest.algorithm_version);
      assert.ok((await app.locator('#analysis').textContent()).includes(exported.manifest.algorithm_version));
      assert.equal(await app.locator('#run-direct').textContent(),'Run →');
      const previousResult=await app.locator('#result-path').textContent();
      await app.evaluate(()=>{window.observationDisabled=true;});
      await app.locator('#run-direct').click();
      await app.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status')?.textContent),{},{timeout:30000});
      assert.equal(await app.locator('#status').textContent(),'COMPLETE');
      await app.waitForFunction(previous=>document.getElementById('status')?.textContent==='COMPLETE'&&document.getElementById('result-path')?.textContent!==previous&&document.getElementById('result-path')?.textContent.includes('Results saved'),previousResult,{timeout:30000});
      const disabled=await app.evaluate(async()=>{
        const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.directSmokeParent);
        const folders=[];for await(const [,handle]of parent.entries())folders.push(handle);
        const files=[];for await(const [,handle]of folders[0].entries())files.push(await handle.getFile());
        const csvs=await Promise.all(files.filter(f=>f.name.endsWith('.csv')).sort((a,b)=>a.name.localeCompare(b.name)).map(f=>f.text()));
        const marker=JSON.parse(await files.find(f=>f.name==='CHOPPER-COMPLETE.json').text());
        const manifest=JSON.parse((await files.find(f=>f.name==='manifest.jsonl').text()).split('\n')[0]);
        await root.removeEntry(window.directSmokeParent,{recursive:true});
        return {csvs,marker,manifest};
      });
      assert.deepEqual(disabled.csvs,exported.csvs);assert.deepEqual(disabled.marker,exported.marker);
      assert.deepEqual(disabled.manifest.config,exported.manifest.config);
      assert.equal(disabled.manifest.analysis.logical_digest,exported.manifest.analysis.logical_digest);
      await app.evaluate(()=>{window.observationDisabled=false;});
      // Analyze reads input without retaining a prepared output result.
      await revealFormControl(app,'#profile');
      await app.locator('#profile').click();
      await app.waitForFunction(()=>['PROFILED','FAILED'].includes(document.getElementById('status')?.textContent),{},{timeout:30000});
      assert.equal(await app.locator('#status').textContent(),'PROFILED',await app.locator('#error').textContent());
      const exportJob=async()=>{
        await revealFormControl(app,'#export');
        const pending=app.waitForEvent('download');await app.locator('#export').click();
        const stream=await(await pending).createReadStream(),parts=[];
        for await(const part of stream)parts.push(part);
        return JSON.parse(Buffer.concat(parts).toString('utf8'));
      };
      const current=await exportJob();
      assert.equal(Object.hasOwn(current,'seed'),false);assert.equal(current.resources.memory_mb,'auto');
      assert.equal(Object.hasOwn(current,'full_shuffle_policy'),false);
      assert.deepEqual(errors,[]);
      result.tests.push({name:'hosted page Run action submits current settings and exports complete results',seconds:(performance.now()-started)/1000});
    }catch(error){result.error=String(error);result.tests.push({name:'hosted page Run action submits current settings and exports complete results',error:String(error),seconds:(performance.now()-started)/1000});}
    finally{await app.close();}
  }
  console.log(JSON.stringify(result,null,2));
  if(result.error||!result.tests?.length||result.tests.some(t=>t.error))throw new Error('Browser contracts failed');
} catch(error){primary=error;} finally {await finishBrowserObservation(observer,[()=>context?.close(),()=>browser?.close(),()=>serverOwner.stop()],primary);}
