import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {withHostedBrowser} from './browser-acceptance.mjs';
import {assertProductionWasm} from './browser-artifacts.mjs';
import {browserChannel} from './browser-launch.mjs';

const assets=new Map(await Promise.all(['engine.wasm','engine-worker.js','storage-worker.js'].map(async name=>
  [name,await readFile(new URL('../ui/dist/'+name,import.meta.url))])));
assertProductionWasm(assets.get('engine.wasm'));
const assetSha256=Object.fromEntries([...assets].map(([name,bytes])=>
  [name,createHash('sha256').update(bytes).digest('hex')]));
const driver=await build({entryPoints:[fileURLToPath(new URL('../ui/tests/browser-quota.ts',import.meta.url))],
  bundle:true,write:false});
const rows=2561,cap=102400;
const quotaSizes=[48*1024,220*1024];
const payload='Chopper01234'.repeat(18);
const csv='id,key,payload\n'+Array.from({length:rows},(_,id)=>`${id},${id%7},${payload}\n`).join('');

async function openProbe(context,url){
  const headers={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp',
    'Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'"};
  await context.route(url+'/quota.html',route=>route.fulfill({contentType:'text/html',headers,
    body:'<!doctype html><title>Origin quota contract</title><script src="/quota.js"></script>'}));
  await context.route(url+'/quota.js',route=>route.fulfill({contentType:'application/javascript',
    body:driver.outputFiles[0].text}));
  const page=await context.newPage();
  await page.goto(url+'/quota.html',{timeout:10000});
  await page.waitForFunction(()=>Boolean(window.quotaProbe),null,{timeout:10000});
  return page;
}

async function verifyRetry(page){
  const retry=await page.evaluate(()=>window.quotaProbe.run());
  assert.equal(retry.status,'complete',JSON.stringify(retry));
  assert.equal(retry.error,null);
  assert.equal(retry.publication?.kind,'browser-completion-marker');
  assert.deepEqual(retry.after,{workspaces:[],destination:[retry.publication.folder]});
  assert.equal(retry.workspaceBytes,0);
  return page.evaluate(({rows,payload,cap})=>window.quotaProbe.verify(rows,payload,cap),{rows,payload,cap});
}

async function disposeProbe(page){
  const cleanup=await page.evaluate(()=>window.quotaProbe.dispose());
  assert.deepEqual(cleanup,{workspaces:[],ownedDestination:false});
  return cleanup;
}

await withHostedBrowser({port:8448},async({context,url,browserVersion})=>{
  const page=await openProbe(context,url);
  const cdp=await context.newCDPSession(page);
  const usage=()=>cdp.send('Storage.getUsageAndQuota',{origin:url});
  const original=await usage();
  assert.equal(original.overrideActive,false);
  assert.ok(original.quota>=Buffer.byteLength(csv));
  await page.evaluate(({csv,cap})=>window.quotaProbe.prepare(csv,cap),{csv,cap});
  const failures=[];
  try{
    for(const quotaSize of quotaSizes){
      assert.ok(quotaSize<Buffer.byteLength(csv));
      await cdp.send('Storage.overrideQuotaForOrigin',{origin:url,quotaSize});
      const limited=await usage();
      assert.equal(limited.overrideActive,true);
      assert.equal(limited.quota,quotaSize);
      assert.ok(limited.usage<quotaSize);
      const failure=await page.evaluate(()=>window.quotaProbe.run());
      assert.equal(failure.status,'failed',JSON.stringify(failure));
      assert.match(failure.error,/QuotaExceededError/);
      assert.equal(failure.publication,undefined);
      assert.deepEqual(failure.after,{workspaces:[],destination:[]});
      assert.equal(failure.workspaceBytes,0);
      failures.push({quota_bytes:limited.quota,error:failure.error,destination_bytes:failure.destinationBytes});
    }
  }finally{
    await cdp.send('Storage.overrideQuotaForOrigin',{origin:url});
  }
  assert.equal(failures[0].destination_bytes,0);
  assert.ok(failures[1].destination_bytes>0,'Partial destination write was not reached');
  const restored=await usage();
  assert.equal(restored.overrideActive,false);
  assert.ok(restored.quota>=Buffer.byteLength(csv));
  const verified=await verifyRetry(page);
  const cleanup=await disposeProbe(page);
  console.log(JSON.stringify({type:'contract',contract:'chromium-opfs-quota-retry-v1',browserChannel,browserVersion,
    asset_sha256:assetSha256,quota_bytes:{original:original.quota,restored:restored.quota},failures,retry:verified,cleanup}));
});

if(browserChannel==='bundled-chromium')await withHostedBrowser({port:8448},async({context,url,browserVersion})=>{
  const page=await openProbe(context,url);
  const rootEntries=()=>page.evaluate(()=>window.quotaProbe.rootEntries());
  const removedParent=await page.evaluate(({csv,cap})=>window.quotaProbe.prepare(csv,cap),{csv,cap});
  assert.deepEqual(await rootEntries(),[removedParent]);
  assert.deepEqual(await page.evaluate(()=>window.quotaProbe.removeSelectedDestination()),[]);

  const failure=await page.evaluate(()=>window.quotaProbe.run());
  assert.equal(failure.status,'failed',JSON.stringify(failure));
  assert.match(failure.error,/NotFoundError/);
  assert.equal(failure.output,null);
  assert.equal(failure.publication,undefined);
  assert.equal(failure.destinationBytes,0);
  assert.deepEqual(failure.after,{workspaces:[],destination:null});
  assert.equal(failure.workspaceBytes,0);
  const rootAfterFailure=await rootEntries();
  assert.deepEqual(rootAfterFailure,['chopper-workspaces']);

  const retryParent=await page.evaluate(()=>window.quotaProbe.selectDestination());
  assert.notEqual(retryParent,removedParent);
  const retry=await verifyRetry(page);
  assert.deepEqual(await rootEntries(),['chopper-workspaces',retryParent].sort());
  const cleanup=await disposeProbe(page);
  assert.deepEqual(await rootEntries(),rootAfterFailure);
  console.log(JSON.stringify({type:'contract',contract:'chromium-opfs-selected-parent-removal-retry-v1',
    browserChannel,browserVersion,asset_sha256:assetSha256,removedParent,rootAfterFailure,failure,retryParent,retry,cleanup}));
});
