// Development-only storage-context diagnostic; writes at most 1.5 GiB per context.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,rm} from 'node:fs/promises';
const server=createServer((req,res)=>{res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.end('<!doctype html>');});
await new Promise(ok=>server.listen(0,'127.0.0.1',ok));
try{for(const persistent of [false,true]){
 let browser,context;const profile=await mkdtemp('/tmp/chopper-opfs-profile-');
 try{
  if(persistent)context=await chromium.launchPersistentContext(profile);else{browser=await chromium.launch();context=await browser.newContext();}
  const page=await context.newPage();await page.goto(`http://127.0.0.1:${server.address().port}`);
  const result=await page.evaluate(()=>new Promise((ok,fail)=>{
   const worker=new Worker(URL.createObjectURL(new Blob([`onmessage=async()=>{
    const root=await navigator.storage.getDirectory();const directory=await root.getDirectoryHandle('probe',{create:true});
    const block=new Uint8Array(1024*1024);let total=0,result;
    try{for(let file=0;file<6&&!result;file++){
     const handle=await(await directory.getFileHandle(String(file),{create:true})).createSyncAccessHandle();
     try{for(let offset=0;offset<256*1024*1024;offset+=block.length){
      const count=handle.write(block,{at:offset});
      if(count!==block.length){result={ok:false,count,offset,total,size:handle.getSize()};break;}total+=count;
     }}finally{handle.close();}
    }}catch(error){result={ok:false,error:String(error),total};}
    finally{await root.removeEntry('probe',{recursive:true});}
    postMessage(result??{ok:true,total});
   }`],{type:'text/javascript'})));
   const timeout=setTimeout(()=>{worker.terminate();fail(new Error('OPFS probe timed out'));},60000);
   worker.onmessage=event=>{clearTimeout(timeout);worker.terminate();ok(event.data);};
   worker.onerror=error=>{clearTimeout(timeout);worker.terminate();fail(error);};worker.postMessage({});
  }));console.log(JSON.stringify({persistent,browser:context.browser().version(),...result}));
  if(persistent)assert.equal(result.ok,true,'persistent OPFS storage probe failed');
 }finally{await context?.close();await browser?.close();await rm(profile,{recursive:true,force:true});}
}}finally{await new Promise(ok=>server.close(ok));}
