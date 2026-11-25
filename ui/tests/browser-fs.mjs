import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Worker} from 'node:worker_threads';
import {build} from 'esbuild';
const bundle=await build({entryPoints:['src/browser/fs.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {DiskFile,DiskBridge}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);

test('source read-ahead bounds physical reads and preserves seeks, partial reads and EOF',()=>{
  const bytes=Uint8Array.from({length:3*1024*1024+17},(_,i)=>i%251);
  const reads=[];
  const original=globalThis.FileReaderSync;
  globalThis.FileReaderSync=class {readAsArrayBuffer(part){reads.push(part.length);return part.slice().buffer;}};
  try {
    const source={size:bytes.length,slice:(start,end)=>bytes.subarray(start,end)};
    const bridge=new DiskBridge({},new SharedArrayBuffer(16+1024*1024));
    bridge.profiling=true;
    const file=new DiskFile(bridge,source);
    for(let offset=0;offset<bytes.length;){
      const got=file.read(offset,8192);
      assert.deepEqual(got,bytes.subarray(offset,offset+8192));offset+=got.length;
    }
    assert.ok(reads.length<=13,`expected bounded read-ahead, got ${reads.length} physical reads`);
    assert.ok(reads.every(n=>n<=256*1024));
    for(const [offset,length] of [[7,41],[262140,8192],[bytes.length-3,100],[bytes.length,100],[0,0],[500000,700000],[0,4]]){
      const got=file.read(offset,length);
      assert.deepEqual(got,bytes.subarray(offset,offset+got.length));
      assert.equal(got.length,Math.min(length,bytes.length-offset));
    }
    assert.equal(bridge.metrics.source_read.calls,reads.length);
    assert.equal(bridge.metrics.source_read.bytes,reads.reduce((a,b)=>a+b,0));
    const first=file.path_open(0,0n,0).fd_obj,second=file.path_open(0,0n,0).fd_obj;
    assert.deepEqual(first.fd_read(7).data,bytes.subarray(0,7));
    assert.deepEqual(second.fd_read(4).data,bytes.subarray(0,4));
    assert.equal(first.fd_tell().offset,7n);
    assert.equal(second.fd_tell().offset,4n);
    first.fd_close();second.fd_close();
    const count=reads.length;
    file.path_open(0,0n,0).fd_obj.fd_read(4);
    assert.equal(reads.length,count+1,'closing the last descriptor releases read-ahead');
  } finally {globalThis.FileReaderSync=original;}
});

for(const status of [1,-1]) test(`storage bridge waits for completion before ${status===1?'returning bytes':'reporting storage errors'}`,async()=>{
  const shared=new SharedArrayBuffer(16+1024);
  const control=new Int32Array(shared,0,4);
  // The previous request completed before the engine waited, but its notify is
  // delayed until the engine is waiting for this request. Counts stay stale.
  control[1]=65536;
  const worker=new Worker(`
    const {parentPort,workerData}=require('node:worker_threads');
    const control=new Int32Array(workerData.shared,0,4);
    parentPort.once('message',()=>{
      while(Atomics.notify(control,0)===0)Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,1);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,30);
      if(workerData.status===-1)new Uint8Array(workerData.shared,16).set(new TextEncoder().encode('failure!'));
      Atomics.store(control,1,8);
      Atomics.store(control,0,workerData.status);
      Atomics.notify(control,0);
    });
  `,{eval:true,workerData:{shared,status}});
  const bridge=new DiskBridge({postMessage(){worker.postMessage('request');}},shared);
  try {
    if(status===1)assert.equal(bridge.call('write',{length:8},new Uint8Array(8)),8);
    else assert.throws(()=>bridge.call('write',{length:8},new Uint8Array(8)),/failure!/);
    assert.equal(Atomics.load(control,0),status);
  } finally {await worker.terminate();}
});


const exportBundle=await build({entryPoints:['src/browser/export.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {exportResults}=await import(`data:text/javascript;base64,${Buffer.from(exportBundle.outputFiles[0].text).toString('base64')}`);
for(const rejection of ['existing','create-denied'])test(`export ${rejection} rejects before start observations or progress`,async()=>{
  const events=[];
  const parent={getDirectoryHandle:async(_name,options)=>{
    if(options?.create){events.push('create');throw new Error('create denied');}
    events.push('lookup');
    if(rejection==='existing')return {};
    throw new DOMException('absent','NotFoundError');
  }};
  await assert.rejects(exportResults({contents:new Map()},parent,'result',{
    observe:value=>events.push(value.export?.status),
    postMessage:()=>events.push('message'),profiling:()=>false,accountExport:()=>{},
  }),rejection==='existing'?/already exists/:/create denied/);
  assert.deepEqual(events,rejection==='existing'?['lookup','failed']:['lookup','create','failed']);
});

const publicationBundle=await build({entryPoints:['src/browser/publication.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {DestinationPublication}=await import(`data:text/javascript;base64,${Buffer.from(publicationBundle.outputFiles[0].text).toString('base64')}`);

test('publication counts only successful closes and validates the count before creating a marker',async()=>{
  const directory={getFileHandle:()=>assert.fail('must reject before opening the marker')};
  const parent={getDirectoryHandle:async(_name,options)=>{
    if(options?.create)return directory;
    throw new DOMException('absent','NotFoundError');
  }};
  const publication=new DestinationPublication(parent,'result');
  await publication.open();
  await publication.closeFile({close:async()=>{}});
  await assert.rejects(publication.closeFile({close:async()=>{throw new Error('close denied');}}),/close denied/);
  assert.equal(publication.closedFiles,1);
  await assert.rejects(publication.finish(2,()=>{}),/still open or missing/);
});

test('publication cleanup leaves a replacement folder in place',async()=>{
  const replacement={getFileHandle:()=>assert.fail('must only inspect the owned folder')};
  const directory={isSameEntry:async entry=>entry===directory};
  let current;
  const parent={
    async getDirectoryHandle(_name,options){
      if(options?.create)current=directory;
      if(!current)throw new DOMException('absent','NotFoundError');
      return current;
    },
    removeEntry:()=>assert.fail('must only remove the owned folder'),
  };
  const publication=new DestinationPublication(parent,'result');
  await publication.open();
  current=replacement;
  assert.equal(await publication.cleanup(),'result');
});
