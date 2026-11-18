import type {PublicationReceipt} from './publication';
import type {Observation} from './execution-history';
import {DiskDirectory, DiskFile} from './fs';

type ExportCallbacks = {
  postMessage:(message:unknown)=>void;
  observe?:(observation:Observation)=>void;
  profiling:()=>boolean;
  accountExport:(bytes:number,start:number)=>void;
};
const encoder=new TextEncoder();

// The caller fixes a fresh random name before confirmation. This shared path
// keeps the completion marker after every result writer has closed successfully.
export async function exportResults(results:DiskDirectory,parent:FileSystemDirectoryHandle,name:string,callbacks:ExportCallbacks){
  const observe=(value:Observation)=>{try{callbacks.observe?.(value);}catch{/* Optional telemetry never fails export. */}};
  let phase:'export'|'marker'='export';
  let copied=0;
  const progress=()=>callbacks.postMessage({progress:{phase:`Saving results (${copied}/${results.contents.size})`,rows:0,temp_bytes:0}});
  try {
    try {await parent.getDirectoryHandle(name);throw new Error('Result folder already exists. Analyze again.');}
    catch(e){if(!(e instanceof DOMException&&e.name==='NotFoundError'))throw e;}
    const destination=await parent.getDirectoryHandle(name,{create:true});
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
    const markerHandle=await destination.getFileHandle('CHOPPER-COMPLETE.json',{create:true});
    const marker=await markerHandle.createWritable();
    const markerText=JSON.stringify({complete:true,files:copied,engine:'chopper-browser',version:1})+'\n';
    try {
      const markerStart=callbacks.profiling()?performance.now():0;await marker.write(markerText);
      if(callbacks.profiling())callbacks.accountExport(encoder.encode(markerText).length,markerStart);
      await marker.close();
    }catch(e){await marker.abort().catch(()=>{});throw e;}
    // Publication success requires exact marker readback, even without telemetry.
    try {
      const file=await markerHandle.getFile();
      if(file.size>256||await file.text()!==markerText)throw new Error('Completion marker content did not match');
    }catch(error){throw new Error('Could not verify completion marker', {cause:error});}
    observe({marker:{status:'completed'}});
    const publication:PublicationReceipt={kind:'browser-completion-marker',version:1,folder:name,files:copied,marker:'CHOPPER-COMPLETE.json'};
    return {output:parent.name+'/'+name,publication};
  }catch(error){observe(phase==='export'?{export:{status:'failed',files:copied}}:{marker:{status:'failed'}});throw error;}
}
