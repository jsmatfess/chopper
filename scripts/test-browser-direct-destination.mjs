import assert from 'node:assert/strict';
import {asyncDestinationStorage,compileDestinationWorker,compileAsyncDestinationEngine,batchDestinationStorage} from './browser-async-destination.mjs';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {serverLifetime} from './browser-acceptance.mjs';
import {launchContractBrowser,launchContractPersistentContext} from './browser-launch.mjs';

const largeCsv='id,key\n'+Array.from({length:2600},(_,index)=>`${index},${'x'.repeat(1024)}\n`).join('');
const asyncBatched=process.argv.includes('--async-batched');
const asyncVariant=asyncBatched||process.argv.includes('--async');
const asyncEngine=asyncVariant?await compileAsyncDestinationEngine():null;
const asyncStorage=asyncVariant?await compileDestinationWorker('storage-worker',source=>asyncDestinationStorage(asyncBatched?batchDestinationStorage(source):source)):null;

const origin='http://127.0.0.1:8422';
const server=serverLifetime(spawn(process.execPath,['scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8422'},stdio:['ignore','pipe','inherit']}),origin,15000,5000);
async function waitFor(page,check,arg){
  const deadline=Date.now()+10000;
  while(Date.now()<deadline){
    if(await page.evaluate(check,arg))return;
    await new Promise(resolve=>setTimeout(resolve,25));
  }
  throw new Error('Browser storage checkpoint did not become ready');
}

function useFixture({parent,csv}){
  window.parentName=parent??'direct-contract-'+crypto.randomUUID();
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([csv],'fixture.csv')}];
  window.showDirectoryPicker=async()=>(await navigator.storage.getDirectory()).getDirectoryHandle(window.parentName,{create:true});
}

async function startRun(page,{split=false,zip=false}={}){
  await page.goto(origin);
  await page.waitForFunction(()=>['IDLE','FAILED'].includes(document.getElementById('status')?.textContent));
  assert.equal(await page.locator('#status').textContent(),'IDLE',await page.locator('#error').textContent());
  await page.locator('#browse-input').click();
  await page.locator('#browse-output').click();
  if(split)await page.locator('#max-rows').fill('1');
  if(zip)await page.locator('#compression').selectOption('zip');
  await page.locator('#run-direct').click();
}

async function checkProcessKill(){
  const worker=await readFile(new URL('../ui/dist/storage-worker.js',import.meta.url),'utf8');
  for(const closed of [false,true]){
    const profile=await mkdtemp(join(tmpdir(),'chopper-direct-termination-'));
    let context;
    try{
      context=await launchContractPersistentContext(chromium,profile);
      await context.route('**/storage-worker.js',route=>route.fulfill({
        contentType:'text/javascript',
        headers:{'Cross-Origin-Embedder-Policy':'require-corp','Cross-Origin-Resource-Policy':'same-origin'},
        body:`
const create=FileSystemFileHandle.prototype.createWritable;
FileSystemFileHandle.prototype.createWritable=async function(...args){
  const stream=await create.apply(this,args);
  if(this.name==='CHOPPER-COMPLETE.json'){
    const close=stream.close.bind(stream);
    stream.close=async()=>{
      if(${closed})await close();
      await (await navigator.storage.getDirectory()).getFileHandle('direct-termination-ready',{create:true});
      await new Promise(()=>{});
    };
  }
  return stream;
};
`+worker}));
      const parent='direct-termination-output';
      const page=await context.newPage();
      await page.addInitScript(useFixture,{parent,csv:'id,key\n1,a\n2,b\n'});
      await startRun(page);
      await waitFor(page,async()=>!!(await(await navigator.storage.getDirectory()).getFileHandle('direct-termination-ready').catch(()=>null)));
      const before=await page.evaluate(async parent=>{
        const root=await navigator.storage.getDirectory(),destination=await root.getDirectoryHandle(parent);
        const workspaces=await root.getDirectoryHandle('chopper-workspaces');
        const folders=[],jobs=[];
        for await(const folder of destination.values())folders.push(folder.name);
        for await(const job of workspaces.values())jobs.push(job.name);
        return {folders,jobs};
      },parent);
      assert.equal(before.folders.length,1);
      assert.ok(before.jobs.length>0);
      const browser=context.browser();
      const cdp=await browser.newBrowserCDPSession();
      const {processInfo}=await cdp.send('SystemInfo.getProcessInfo');
      await cdp.detach();
      // Only kill the browser whose PID comes from this disposable profile's CDP session.
      const pid=processInfo.find(entry=>entry.type==='browser')?.id;
      assert(Number.isSafeInteger(pid)&&pid>0&&pid!==process.pid);
      const disconnected=new Promise(resolve=>browser.once('disconnected',resolve));
      process.kill(pid,'SIGKILL');
      await disconnected;

      context=await launchContractPersistentContext(chromium,profile);
      const reopened=await context.newPage();
      await reopened.goto(origin);
      await reopened.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
      await waitFor(reopened,async jobs=>{
        const workspaces=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces');
        for await(const job of workspaces.values())if(jobs.includes(job.name))return false;
        return true;
      },before.jobs);
      const published=await reopened.evaluate(async({parent,folder})=>{
        const root=await navigator.storage.getDirectory(),destination=await root.getDirectoryHandle(parent);
        const output=await destination.getDirectoryHandle(folder);
        const marker=await output.getFileHandle('CHOPPER-COMPLETE.json').then(handle=>handle.getFile()).catch(error=>{
          if(error.name==='NotFoundError')return null;
          throw error;
        });
        const csv=await(await(await output.getFileHandle('part-00000001.csv')).getFile()).text();
        return {marker:marker?.size?JSON.parse(await marker.text()):null,csv};
      },{parent,folder:before.folders[0]});
      assert.deepEqual(published.marker,closed?{complete:true,files:2,engine:'chopper-browser',version:1}:null);
      assert.equal(published.csv,'id,key\n1,a\n2,b\n');
      console.log(`process kill ${closed?'after':'before'} marker close passed`);
    }finally{
      try{await context?.close();}finally{await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:200});}
    }
  }
}

let browser;
try{
  await server.ready;browser=await launchContractBrowser(chromium);
  const modes=['success','late-input-error','write-error','close-error','marker-error','marker-mismatch-error','readback-error','cancel','marker-closed-cancel'];
  if(!asyncVariant)modes.push('staged-marker-mismatch-error','buffer-boundary','source-rejection','source-cancel','buffer-flush-error','buffer-flush-cancel');
  for(const mode of modes){
    const large=['buffer-boundary','source-rejection','source-cancel','buffer-flush-error','buffer-flush-cancel'].includes(mode);
    const context=await browser.newContext();
    try{
      const page=await context.newPage();
      if(asyncVariant)await context.route('**/engine-worker.js',async route=>{
        const original=await route.fetch();
        const headers=original.headers();delete headers['content-length'];
        await route.fulfill({headers,contentType:'text/javascript',body:asyncEngine});
      });
      const staged=mode==='staged-marker-mismatch-error';
      if(staged||asyncVariant||large||['write-error','close-error','marker-error','marker-mismatch-error','readback-error','cancel','marker-closed-cancel'].includes(mode))await context.route(staged?'**/engine-worker.js':'**/storage-worker.js',async route=>{
        const source=await route.fetch();
        const headers=source.headers();delete headers['content-length'];
        await route.fulfill({headers,contentType:'text/javascript',body:`
const mode=${JSON.stringify(mode)};
const sourceRead=Blob.prototype.arrayBuffer;
let firstRead=true,firstOutput=true;
async function signalInflight(){
  await (await navigator.storage.getDirectory()).getFileHandle('direct-contract-inflight',{create:true});
}
Blob.prototype.arrayBuffer=async function(){
  if(firstRead&&['source-rejection','source-cancel'].includes(mode)&&this.size===256*1024){
    firstRead=false;
    await signalInflight();
    if(mode==='source-rejection')throw new Error('Injected speculative read failure');
    await new Promise(()=>{});
  }
  return sourceRead.call(this);
};
const original=FileSystemFileHandle.prototype.createWritable;
FileSystemFileHandle.prototype.createWritable=async function(...args){
  const stream=await original.apply(this,args),name=this.name;
  const write=stream.write.bind(stream),close=stream.close.bind(stream);
  stream.write=async data=>{
    if(firstOutput&&name.endsWith('.csv')&&['buffer-flush-error','buffer-flush-cancel'].includes(mode)){
      firstOutput=false;
      if(data.data.byteLength<=512*1024)throw new Error('Expected a coalesced write');
      if(mode==='buffer-flush-error')throw new Error('Injected buffered write error');
      await signalInflight();
      await new Promise(resolve=>setTimeout(resolve,2500));
    }
    if(mode==='write-error' && name.endsWith('00000002.csv'))throw new DOMException('Injected destination write error','QuotaExceededError');
    if(mode==='marker-error' && name==='CHOPPER-COMPLETE.json')throw new Error('Injected marker write error');
    if(mode.endsWith('marker-mismatch-error')&&name==='CHOPPER-COMPLETE.json'){
      const text=new TextDecoder().decode(data);
      const wrongCount=text.replace(/("files":)([0-9])/,(_,field,digit)=>field+(digit==='9'?'8':'9'));
      const bytes=new TextEncoder().encode(wrongCount);
      if(wrongCount===text||bytes.length!==data.byteLength)throw new Error('Expected a same-length marker mismatch');
      return write(bytes);
    }
    if(mode==='cancel' && name.endsWith('00000002.csv')){
      await (await navigator.storage.getDirectory()).getFileHandle('direct-contract-inflight',{create:true});
      await new Promise(resolve=>setTimeout(resolve,2500));
    }
    return write(data);
  };
  stream.close=async()=>{
    if(mode==='close-error' && name.endsWith('00000002.csv'))throw new Error('Injected destination close error');
    await close();
    if(mode==='marker-closed-cancel'&&name==='CHOPPER-COMPLETE.json')await new Promise(resolve=>setTimeout(resolve,2500));
  };
  return stream;
};
const getFile=FileSystemFileHandle.prototype.getFile;
FileSystemFileHandle.prototype.getFile=async function(...args){
  if(mode==='readback-error'&&this.name==='CHOPPER-COMPLETE.json')throw new Error('Injected marker readback error');
  return getFile.apply(this,args);
};
`+(asyncStorage??await source.text())});
      });
      const csv=large?largeCsv:mode==='late-input-error'
        ?'id,key\n'+Array.from({length:40},(_,i)=>i+',a\n').join('')+'41,d,extra\n'
        :'id,key\n1,a\n2,b\n3,c\n4,d\n';
      await page.addInitScript(useFixture,{csv});
      await startRun(page,{split:!large,zip:staged});
      if(mode.endsWith('cancel')){
        await waitFor(page,async marker=>{
          const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.parentName);
          if(!marker&&!(await root.getFileHandle('direct-contract-inflight').catch(()=>null)))return false;
          for await(const folder of parent.values()){
            if(!marker)return true;
            for await(const entry of folder.values()){
              if(marker&&entry.name==='CHOPPER-COMPLETE.json'&&(await entry.getFile()).size>0)return true;
            }
          }
          return false;
        },mode==='marker-closed-cancel');
        await page.locator('#cancel').click();
      }
      const status=['success','buffer-boundary','source-rejection'].includes(mode)?'COMPLETE':mode.endsWith('cancel')?'CANCELLED':'FAILED';
      await page.waitForFunction(()=>['COMPLETE','CANCELLED','FAILED'].includes(document.getElementById('status')?.textContent),{},{timeout:20000});
      assert.equal(await page.locator('#status').textContent(),status,mode+': '+await page.locator('#error').textContent());
      if((mode==='success'&&!asyncVariant)||staged){
        await page.getByRole('button',{name:'Timeline view',exact:true}).click();
        const save=page.locator('[data-timeline-row="2"] .execution-timeline-times');
        assert.match(await save.innerText(),/^\d[\d,.]* s – \d[\d,.]* s · Completed$/,mode+': destination start and completion were observed');
      }
      if(status==='FAILED'&&mode!=='readback-error')await waitFor(page,async()=>{
        const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.parentName);
        for await(const _ of parent.values())return false;
        return true;
      });
      if(mode.endsWith('error')&&mode!=='late-input-error')assert.match(await page.locator('#error').textContent(),/Injected|Could not verify completion marker/);
      if(mode.endsWith('marker-mismatch-error'))assert.match(await page.locator('#error').textContent(),/Could not verify completion marker: content did not match/);
      const result=await page.evaluate(async()=>{
        const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(window.parentName);
        const folders=[];
        for await(const folder of parent.values()){
          const files={};
          for await(const file of folder.values())files[file.name]=await(await file.getFile()).text();
          folders.push({name:folder.name,files});
        }
        await root.removeEntry(window.parentName,{recursive:true});
        return folders;
      });
      if(['source-rejection','source-cancel','buffer-flush-cancel'].includes(mode)){
        assert(await page.evaluate(async()=>!!(await (await navigator.storage.getDirectory()).getFileHandle('direct-contract-inflight'))));
      }
      if(['buffer-boundary','source-rejection'].includes(mode)){
        assert.equal(result.length,1);
        const {files}=result[0],csv=Object.keys(files).filter(name=>name.endsWith('.csv'));
        assert.equal(csv.length,1);
        assert.equal(files[csv[0]],largeCsv);
        assert.equal(JSON.parse(files['CHOPPER-COMPLETE.json']).files,2);
      }else if(['success','readback-error','marker-closed-cancel'].includes(mode)){
        assert.equal(result.length,1);
        const {files}=result[0],csv=Object.keys(files).filter(name=>name.endsWith('.csv')).sort();
        assert.deepEqual(csv.map(name=>files[name]),['id,key\n1,a\n','id,key\n2,b\n','id,key\n3,c\n','id,key\n4,d\n']);
        assert.equal(JSON.parse(files['CHOPPER-COMPLETE.json']).files,5);
      }else assert.deepEqual(result,[]);
      if(mode==='marker-closed-cancel'){
        const folder=await page.evaluate(()=>window.parentName);
        assert.ok((await page.locator('#error').textContent()).includes(folder+'/'+result[0].name));
      }else if(status==='CANCELLED')assert.equal(await page.locator('#error').textContent(),'');
      console.log(mode+' passed');
    }finally{await context.close();}
  }
  await browser.close();browser=null;
  if(!asyncVariant)await checkProcessKill();
}finally{try{await browser?.close();}finally{await server.stop();}}
