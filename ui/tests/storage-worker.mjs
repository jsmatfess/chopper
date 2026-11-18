import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const bundle=await build({entryPoints:['src/browser/storage-worker.ts'],bundle:true,write:false,format:'esm',platform:'node'});

test('storage cache bounds handles, reuses merge inputs, tolerates lower quotas and cleans up',async()=>{
  const previous={navigator:Object.getOwnPropertyDescriptor(globalThis,'navigator'),onmessage:globalThis.onmessage,postMessage:globalThis.postMessage};
  let active=0,peak=0,limit=Infinity,removed=false,denied=false,readResult=0,writeResult;
  const sizes=new Map();
  const directory={
    async getDirectoryHandle(){return directory;},
    async removeEntry(id,options){if(options?.recursive)removed=true;else sizes.delete(id);},
    async getFileHandle(id){return {async createSyncAccessHandle(){
      if(denied)throw new DOMException('denied','NotAllowedError');
      if(active>=limit)throw new DOMException('quota','QuotaExceededError');
      active++;peak=Math.max(peak,active);
      return {flush(){},close(){active--;},getSize(){return sizes.get(id)||0;},
        truncate(n){sizes.set(id,n);},read(){return readResult;},write(b,{at}){sizes.set(id,Math.max(sizes.get(id)||0,at+b.length));return writeResult??b.length;}};
    }};}
  };
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{storage:{getDirectory:async()=>directory}}});
  const messages=[];globalThis.postMessage=message=>messages.push(message);
  const shared=new SharedArrayBuffer(16+1024),control=new Int32Array(shared,0,4),port={};
  try {
    await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
    await globalThis.onmessage({data:{type:'init',jobId:'test',available:100000,shared,port}});
    async function call(op,id,args={}){
      Atomics.store(control,0,0);port.onmessage({data:{op,id,...args}});
      while(!Atomics.load(control,0))await new Promise(resolve=>setImmediate(resolve));
      return {status:control[0],bytes:control[1],opened:control[2],evicted:control[3]};
    }
    for(let i=0;i<43;i++)assert.equal((await call('create',String(i))).opened,1);
    for(let pass=0;pass<3;pass++)for(let i=0;i<43;i++)assert.equal((await call('read',String(i),{offset:0,length:1})).opened,0);
    for(let i=43;i<80;i++)assert.equal((await call('create',String(i))).status,1);
    assert.equal(peak,64);assert.equal(active,64);
    limit=2;
    const constrained=await call('create','quota');
    assert.equal(constrained.status,1);assert.equal(active,2);assert.ok(constrained.evicted>=62);
    assert.equal((await call('write','quota',{offset:0,length:7})).bytes,7);
    for(const invalid of [-8,8,4294967288,2**64-8,0.5,NaN]){
      writeResult=invalid;
      assert.equal((await call('write','quota',{offset:0,length:7})).status,-1,'invalid write count');
      readResult=invalid;
      assert.equal((await call('read','quota',{offset:0,length:7})).status,-1,'invalid read count');
    }
    writeResult=3;readResult=2;
    assert.equal((await call('write','quota',{offset:0,length:7})).bytes,3);
    assert.equal((await call('read','quota',{offset:0,length:7})).bytes,2);
    assert.equal((await call('truncate','quota',{size:11})).status,1);
    const exported=await call('account_export','ignored',{length:5});
    assert.equal(exported.status,1);assert.equal(exported.opened,0);assert.equal(exported.evicted,0);
    assert.equal((await call('truncate','quota',{size:3})).status,1);
    assert.equal((await call('account_export','ignored',{length:13})).status,1);
    assert.equal((await call('account_export','ignored',{length:-1})).status,-1);
    denied=true;
    assert.equal((await call('create','denied')).status,-1);
    assert.equal(active,2,'permission errors must not be treated as quota errors');
    await globalThis.onmessage({data:{type:'cleanup'}});
    assert.equal(active,0);assert.equal(removed,true);
    const storage=messages.find(message=>message.cleaned).storage;
    assert.equal(storage.workspace_peak_bytes,11);
    assert.equal(storage.workspace_bytes_before_cleanup,3);
    assert.equal(storage.workspace_bytes_after_cleanup,0);
    assert.equal(storage.profiled_destination_bytes,18);
    assert.equal(storage.workspace_and_destination_peak_bytes,21);
    assert.equal(storage.peak_open_handles,64);
  } finally {
    if(previous.navigator)Object.defineProperty(globalThis,'navigator',previous.navigator);else delete globalThis.navigator;
    globalThis.onmessage=previous.onmessage;globalThis.postMessage=previous.postMessage;
  }
});
