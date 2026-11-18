import {finishBrowserObservation} from './browser-small-observer.mjs';
// Chromium rejects TextDecoder input backed by SharedArrayBuffer; Node does not.
import {createServer} from 'node:http';
import assert from 'node:assert/strict';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {browserChannel,launchContractBrowser,observeContractBrowser,smallContractPacket} from './browser-launch.mjs';
const bundle=await build({stdin:{contents:`import {DiskBridge} from './ui/src/browser/fs';
  window.bridgeError=()=>{
    const shared=new SharedArrayBuffer(1024), control=new Int32Array(shared,0,4);
    const bytes=new Uint8Array(shared,16), expected='Storage failed: quota exceeded — fixture';
    const port={postMessage(){const data=new TextEncoder().encode(expected);bytes.set(data);control[1]=data.length;Atomics.store(control,0,-1);}};
    try{new DiskBridge(port,shared).call('write');return 'no error';}catch(error){return error.message;}
  };`,resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false});
const server=createServer((req,res)=>{res.writeHead(200,{'Content-Type':'text/html','Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'});res.end('<!doctype html>');});
let browser,context,observer,primary;
try{
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(smallContractPacket?Number(new URL(smallContractPacket.origin).port):0,'127.0.0.1',resolve);});
  browser=await launchContractBrowser(chromium);context=await browser.newContext();const page=await context.newPage();
  observer=await observeContractBrowser(browser,context,`http://127.0.0.1:${server.address().port}`);
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.addScriptTag({content:bundle.outputFiles[0].text});
  assert.equal(await page.evaluate(()=>window.bridgeError()),'Storage failed: quota exceeded — fixture');
  console.log(JSON.stringify({contract:'browser-storage-error-bridge-v1',browserChannel,browserVersion:browser.version(),utf8_storage_error_preserved:true}));
}catch(error){primary=error;}finally{await finishBrowserObservation(observer,[()=>context?.close(),()=>browser?.close(),()=>server.listening?new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve())):undefined],primary);}
