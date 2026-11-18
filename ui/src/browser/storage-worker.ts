export {};
type Access={getSize():number;read(b:Uint8Array,o:{at:number}):number;write(b:Uint8Array,o:{at:number}):number;truncate(n:number):void;flush():void;close():void};
type Handle=FileSystemFileHandle & {createSyncAccessHandle():Promise<Access>};
const scope=globalThis as unknown as {onmessage:(e:MessageEvent)=>void;postMessage:(v:unknown)=>void};
let directory:FileSystemDirectoryHandle;
let root:FileSystemDirectoryHandle;
let jobId='';
let queue=Promise.resolve();
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
async function cleanup(){for(const h of handles.values())h.close();handles.clear();if(root&&jobId)await root.removeEntry(jobId,{recursive:true});used=0;sizes.clear();}
scope.onmessage=async({data})=>{
  try {
    if(data.type==='init'){
      jobId=data.jobId;maximum=data.available;root=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces',{create:true});directory=await root.getDirectoryHandle(jobId,{create:true});
      const control=new Int32Array(data.shared,0,4),bytes=new Uint8Array(data.shared,16);
      const port=data.port as MessagePort;
      port.onmessage=({data:m})=>{queue=queue.then(async()=>{
        opened=0;evicted=0;
        try {
          let n=0;
          if(m.op==='account_export'){
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
      });};
      scope.postMessage({ready:true});
    } else if(data.type==='cleanup'){
      await queue;
      const snapshot={version:'opfs-workspace-and-profiled-export-v1',maximum_workspace_bytes:maximum,workspace_peak_bytes:peakUsed,workspace_bytes_before_cleanup:used,workspace_peak_files:peakFiles,profiled_destination_bytes:destinationBytes,workspace_and_destination_peak_bytes:peakCombined,peak_open_handles:peakHandles,scope:'Logical file sizes from successful workspace operations and profiled destination writes; metadata and implementation buffers excluded; destination may be on another volume'};
      await cleanup();scope.postMessage({cleaned:true,storage:{...snapshot,workspace_bytes_after_cleanup:used}});
    }
  } catch(e){scope.postMessage({error:String(e)});}
};
