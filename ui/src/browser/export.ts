import {DestinationPublication,publicationResult} from './publication';
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
  const publication=new DestinationPublication(parent,name);
  const progress=()=>callbacks.postMessage({progress:{phase:`Saving results (${publication.closedFiles}/${results.contents.size})`,rows:0,temp_bytes:0}});
  try {
    const destination=await publication.open();
    observe({export:{status:'active',files:0}});
    progress();
    callbacks.postMessage({exporting:name});
    for(const [name,node] of results.contents){
      if(!(node instanceof DiskFile))throw new Error('Unexpected output entry');
      const writer=await (await destination.getFileHandle(name,{create:true})).createWritable();
      try {
        for(let offset=0;offset<node.size;){const bytes=node.read(offset,1024*1024);if(!bytes.length)throw new Error('Truncated output');const start=callbacks.profiling()?performance.now():0;await writer.write(bytes as Uint8Array<ArrayBuffer>);callbacks.accountExport(bytes.length,start);offset+=bytes.length;}
        await publication.closeFile(writer);
      }catch(e){await writer.abort().catch(()=>{});throw e;}
      observe({export:{status:'active',files:publication.closedFiles}});progress();
    }
    phase='marker';
    observe({export:{status:'completed',files:publication.closedFiles},marker:{status:'active'}});
    const files=await publication.finish(results.contents.size,callbacks.accountExport);
    observe({marker:{status:'completed'}});
    return publicationResult(parent,name,files);
  }catch(error){
    observe(phase==='export'?{export:{status:'failed',files:publication.closedFiles}}:{marker:{status:'failed'}});
    try{if(await publication.cleanup()===null)callbacks.postMessage({outputRemoved:true});}
    catch(cleanup){throw new Error(`${error}. ${cleanup}`,{cause:error});}
    throw error;
  }
}
