import {createDestination,completeDestination,removeIncompleteDestination,publicationResult} from './publication';
import type {Observation} from './execution-history';
import {DiskDirectory, DiskFile} from './fs';

type ExportCallbacks = {
  postMessage:(message:unknown)=>void;
  observe?:(observation:Observation)=>void;
  profiling:()=>boolean;
  accountExport:(bytes:number,start:number)=>void;
};

// The caller fixes a fresh random name before confirmation. This shared path
// keeps the completion marker after every result writer has closed successfully.
export async function exportResults(results:DiskDirectory,parent:FileSystemDirectoryHandle,name:string,callbacks:ExportCallbacks){
  const observe=(value:Observation)=>{try{callbacks.observe?.(value);}catch{/* Optional telemetry never fails export. */}};
  let phase:'export'|'marker'='export';
  let copied=0;
  const progress=()=>callbacks.postMessage({progress:{phase:`Saving results (${copied}/${results.contents.size})`,rows:0,temp_bytes:0}});
  let destination:FileSystemDirectoryHandle|undefined,preserveMarker=false;
  try {
    destination=await createDestination(parent,name);
    observe({export:{status:'active',files:0}});
    progress();
    callbacks.postMessage({exporting:name});
    for(const [name,node] of results.contents){
      if(!(node instanceof DiskFile))throw new Error('Unexpected output entry');
      const writer=await (await destination.getFileHandle(name,{create:true})).createWritable();
      try {
        for(let offset=0;offset<node.size;){const bytes=node.read(offset,1024*1024);if(!bytes.length)throw new Error('Truncated output');const start=callbacks.profiling()?performance.now():0;await writer.write(bytes as Uint8Array<ArrayBuffer>);callbacks.accountExport(bytes.length,start);offset+=bytes.length;}
        await writer.close();
      }catch(e){await writer.abort().catch(()=>{});throw e;}
      copied++;observe({export:{status:'active',files:copied}});progress();
    }
    phase='marker';
    observe({export:{status:'completed',files:copied},marker:{status:'active'}});
    await completeDestination(destination,copied,callbacks.accountExport,preserve=>{preserveMarker=preserve;});
    observe({marker:{status:'completed'}});
    return publicationResult(parent,name,copied);
  }catch(error){
    observe(phase==='export'?{export:{status:'failed',files:copied}}:{marker:{status:'failed'}});
    if(destination&&!preserveMarker){
      try{if(await removeIncompleteDestination(parent,name,destination,copied))callbacks.postMessage({outputRemoved:true});}
      catch(cleanup){throw new Error(`${error}. ${cleanup}`,{cause:error});}
    }
    throw error;
  }
}
