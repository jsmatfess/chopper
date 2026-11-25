import {DESTINATION_BLOCK,SOURCE_WINDOW,STREAMING_IO_BYTES} from './streaming-io';
import {DestinationPublication} from './publication';
type Access={getSize():number;read(b:Uint8Array,o:{at:number}):number;write(b:Uint8Array,o:{at:number}):number;truncate(n:number):void;flush():void;close():void};
type Handle=FileSystemFileHandle & {createSyncAccessHandle():Promise<Access>};
const scope=globalThis as unknown as {onmessage:(e:MessageEvent)=>void;postMessage:(v:unknown)=>void};
let directory:FileSystemDirectoryHandle;
let root:FileSystemDirectoryHandle;
let jobId='';
let queue=Promise.resolve();
let streamWrite=Promise.resolve();
let stopping=false,streamingIoPeakBytes=0;
let maximum=0,used=0,peakUsed=0,destinationBytes=0,peakCombined=0,peakFiles=0,peakHandles=0;
function observeSpace(){peakUsed=Math.max(peakUsed,used);peakCombined=Math.max(peakCombined,used+destinationBytes);peakFiles=Math.max(peakFiles,sizes.size);}
const sizes=new Map<string,number>();
const handles=new Map<string,Access>();
let opened=0,evicted=0;
function evict(){
  const [key,old]=handles.entries().next().value!;
  old.flush();old.close();handles.delete(key);evicted++;
}
async function access(id:string){
  let h=handles.get(id);if(h){handles.delete(id);handles.set(id,h);return h;}
  if(handles.size>=64)evict();
  const file=await directory.getFileHandle(id,{create:true}) as Handle;
  // Some browsers impose a lower handle quota. Release cached handles and retry;
  // locks, permission errors and failures with an empty cache still fail the job.
  for(;;){
    try {h=await file.createSyncAccessHandle();break;}
    catch(e){if(!(e instanceof DOMException&&e.name==='QuotaExceededError')||!handles.size)throw e;evict();}
  }
  handles.set(id,h);opened++;peakHandles=Math.max(peakHandles,handles.size);
  if(!sizes.has(id)){const actual=h.getSize();sizes.set(id,actual);used+=actual;observeSpace();}
  return h;
}
let destination:DestinationPublication|undefined;
const writers=new Map<string,FileSystemWritableFileStream>();
let block:{bytes:Uint8Array<ArrayBuffer>;id:string;offset:number;length:number}|undefined;
async function flushBlock(){
  if(!block?.length)return;
  const writer=writers.get(block.id);
  if(!writer)throw new Error('Destination writer is closed');
  await writer.write({type:'write',position:block.offset,data:block.bytes.subarray(0,block.length)});
  destinationBytes+=block.length;observeSpace();
  block.length=0;
}
async function bufferWrite(m:{id:string;offset:number;length:number},bytes:Uint8Array){
  if(!destination||!writers.has(m.id)||m.length<1||m.length>DESTINATION_BLOCK)
    throw new Error('Invalid buffered destination write');
  if(!block)block={bytes:new Uint8Array(DESTINATION_BLOCK),id:m.id,offset:m.offset,length:0};
  if(block.length&&(block.id!==m.id||block.offset+block.length!==m.offset||block.length+m.length>block.bytes.length))
    await flushBlock();
  if(!block.length){block.id=m.id;block.offset=m.offset;}
  block.bytes.set(bytes.subarray(0,m.length),block.length);
  block.length+=m.length;
  return m.length;
}
async function destinationOperation(m:any,bytes:Uint8Array):Promise<number>{
  if(m.op==='destination_init'){
    if(destination)throw new Error('Destination already configured');
    destination=new DestinationPublication(m.parent,m.folder);
    return 0;
  }
  const target=destination;
  if(!target)throw new Error('Destination is unavailable');
  if(block?.length)await flushBlock();
  const writer=writers.get(m.id);
  switch(m.op){
    case 'destination_create': {
      if(writers.size>=64)throw new Error('Too many open destination writers');
      const folder=await target.open(()=>scope.postMessage({exporting:target.name}));
      const file=await folder.getFileHandle(m.name,{create:true});
      writers.set(m.id,await file.createWritable());
      return 0;
    }
    case 'destination_delete':
      if(writer){await writer.abort();writers.delete(m.id);}
      await target.removeFile(m.name);
      return 0;
    case 'destination_finish':
      if(writers.size)throw new Error('Destination files are still open or missing');
      return await target.finish(m.files,bytes=>{destinationBytes+=bytes;observeSpace();});
  }
  if(!writer)throw new Error('Destination writer is closed');
  switch(m.op){
    case 'destination_write':
      // Writable filesystem streams require an ordinary buffer. The bridge permits one in-flight write.
      await writer.write({type:'write',position:m.offset,data:bytes.slice(0,m.length) as Uint8Array<ArrayBuffer>});
      destinationBytes+=m.length;observeSpace();
      return m.length;
    case 'destination_truncate': await writer.truncate(m.size);return 0;
    case 'destination_flush': return 0; // The writable commits when the last engine descriptor closes.
    case 'destination_close': await target.closeFile(writer);writers.delete(m.id);return 0;
    default: throw new Error('Unsupported destination operation');
  }
}
async function cleanup(){
  try{
    for(const writer of writers.values())await writer.abort().catch(()=>{});
    writers.clear();
    return await destination?.cleanup();
  }finally{
    for(const h of handles.values())h.close();
    handles.clear();if(root&&jobId)await root.removeEntry(jobId,{recursive:true});used=0;sizes.clear();
  }
}
scope.onmessage=async({data})=>{
  try {
    if(data.type==='init'){
      jobId=data.jobId;maximum=data.available;root=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces',{create:true});directory=await root.getDirectoryHandle(jobId,{create:true});
      const control=new Int32Array(data.shared,0,4),bytes=new Uint8Array(data.shared,16);
      const port=data.port as MessagePort;
      // Fast lanes own their acknowledgements and leave the synchronous buffer alone.
      port.onmessage=({data:m})=>{
        if(stopping)return;
        if(m.op==='stream_prefetch'){
          streamingIoPeakBytes=STREAMING_IO_BYTES;
          void (async()=>{
            const reply=new Int32Array(m.slot,0,2);
            try{
              const data=await m.blob.arrayBuffer() as ArrayBuffer;
              if(data.byteLength>SOURCE_WINDOW)throw new Error('Source window exceeds its slot');
              new Uint8Array(m.slot,8).set(new Uint8Array(data));
              Atomics.store(reply,1,data.byteLength);Atomics.store(reply,0,1);
            }catch{Atomics.store(reply,0,-1);}
            Atomics.notify(reply,0);
          })();
          return;
        }
        if(m.op==='stream_write'){
          streamingIoPeakBytes=STREAMING_IO_BYTES;
          streamWrite=(async()=>{
            const reply=new Int32Array(m.slot,0,4),payload=new Uint8Array(m.slot,16);
            try{
              Atomics.store(reply,1,await bufferWrite(m,payload));Atomics.store(reply,0,1);
            }catch(error){
              const message=new TextEncoder().encode(String(error));
              payload.set(message.subarray(0,payload.length));
              Atomics.store(reply,1,Math.min(message.length,payload.length));Atomics.store(reply,0,-1);
            }
            Atomics.notify(reply,0);
          })();
          return;
        }
        queue=queue.then(async()=>{
          opened=0;evicted=0;
          try {
            let n=0;
            if(m.op.startsWith('destination_'))n=await destinationOperation(m,bytes);
            else if(m.op==='account_export'){
              if(!Number.isSafeInteger(m.length)||m.length<0||!Number.isSafeInteger(destinationBytes+m.length))throw new Error('Invalid profiled export byte count');
              destinationBytes+=m.length;observeSpace();
            }
            else if(m.op==='delete'){handles.get(m.id)?.close();handles.delete(m.id);await directory.removeEntry(m.id);used-=sizes.get(m.id)||0;sizes.delete(m.id);}
            else {const h=await access(m.id);
              if(m.op==='read')n=h.read(bytes.subarray(0,m.length),{at:m.offset});
              else if(m.op==='write'||m.op==='truncate'){
                const old=sizes.get(m.id)||0;
                const next=m.op==='write'?Math.max(old,m.offset+m.length):m.size;
                if(used-old+next>maximum)throw new Error('Browser storage budget exhausted, including staged output. Free storage or reduce the job size.');
                if(m.op==='write')n=h.write(bytes.subarray(0,m.length),{at:m.offset});else h.truncate(m.size);
                const actual=h.getSize();used+=actual-old;sizes.set(m.id,actual);observeSpace();
              }
              else if(m.op==='flush')h.flush();
              else if(m.op!=='create')throw new Error('Unknown storage operation');
            }
            if((m.op==='read'||m.op==='write')&&(!Number.isSafeInteger(n)||n<0||n>m.length))
              throw new Error(`Browser storage returned an invalid ${m.op} byte count (${n} for ${m.length} bytes).`);
            Atomics.store(control,2,opened);Atomics.store(control,3,evicted);
            Atomics.store(control,1,n);Atomics.store(control,0,1);
          } catch(e){const message=new TextEncoder().encode(String(e));bytes.set(message.subarray(0,bytes.length));Atomics.store(control,1,Math.min(message.length,bytes.length));Atomics.store(control,0,-1);}
          Atomics.notify(control,0);
        });
      };
      scope.postMessage({ready:true});
    } else if(data.type==='cleanup'){
      stopping=true;
      // The speculative source read owns only its Blob and reply buffer.
      await streamWrite;
      await queue;
      const snapshot={version:'opfs-workspace-and-profiled-export-v1',maximum_workspace_bytes:maximum,workspace_peak_bytes:peakUsed,workspace_bytes_before_cleanup:used,workspace_peak_files:peakFiles,profiled_destination_bytes:destinationBytes,workspace_and_destination_peak_bytes:peakCombined,peak_open_handles:peakHandles,streaming_io_buffer_limit_bytes:streamingIoPeakBytes,scope:'Logical file sizes from successful workspace operations and profiled destination writes; metadata and implementation buffers excluded; destination may be on another volume'};
      const retainedDestination=await cleanup();
      scope.postMessage({cleaned:true,retainedDestination,storage:{...snapshot,workspace_bytes_after_cleanup:used}});
    }
  } catch(e){scope.postMessage({error:String(e)});}
};
