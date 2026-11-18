// Diagnostic only: isolate OPFS sync writes from the engine in a temporary profile.
import {createServer} from 'node:http';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
const persistent=process.argv.includes('--persistent');
const limitMiB=Number(process.argv.find(v=>v.startsWith('--limit-mib='))?.split('=')[1]??2048);
if(!Number.isSafeInteger(limitMiB)||limitMiB<1||limitMiB>8192)throw new Error('Use a 1–8192 MiB probe limit');
const profile=await mkdtemp(join(tmpdir(),'chopper-opfs-probe-'));
const server=createServer((req,res)=>{
  res.writeHead(200,{'Content-Type':'text/html','Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'});res.end('<!doctype html>');
});
let browser;
try{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=persistent?await chromium.launchPersistentContext(profile):await chromium.launch();
  const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}`);
  const result=await page.evaluate(limit=>new Promise((resolve,reject)=>{
    const source=`onmessage=async({data:limit})=>{
      const root=await navigator.storage.getDirectory(),name='probe-'+crypto.randomUUID();
      let handle;const before=await navigator.storage.estimate();let offset=0,failure=null;
      try{
        handle=await(await root.getFileHandle(name,{create:true})).createSyncAccessHandle();
        const bytes=new Uint8Array(new SharedArrayBuffer(1024*1024));
        for(;offset<limit*1024*1024;offset+=bytes.length){const n=handle.write(bytes,{at:offset});if(n!==bytes.length){failure={returned:n,requested:bytes.length};break;}}
        handle.flush();
      }catch(error){failure=String(error);}
      finally{handle?.close();}
      const after=await navigator.storage.estimate();await root.removeEntry(name);
      postMessage({before,after,offset,failure});
    };`;
    const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'})),worker=new Worker(url);
    worker.onmessage=event=>{worker.terminate();URL.revokeObjectURL(url);resolve(event.data);};
    worker.onerror=event=>{worker.terminate();URL.revokeObjectURL(url);reject(new Error(event.message));};
    worker.postMessage(limit);
  }),limitMiB);
  console.log(JSON.stringify({browser:browser.version?await browser.version():browser.browser().version(),session:persistent?'temporary persistent disk profile':'private',limit_mib:limitMiB,...result}));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));await rm(profile,{recursive:true,force:true});}
