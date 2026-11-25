import {serialCompressionImports} from '../src/browser/compression';
// Dedicated test reactor. The production worker has no resource-injection API.
import {WASI, File as MemoryFile, ConsoleStdout, wasi} from '@bjorn3/browser_wasi_shim';
import {DiskBridge, DiskDirectory, DiskFile, RootFd} from '../src/browser/fs';
import {exportResults} from '../src/browser/export';
import type {Observation} from '../src/browser/execution-history';

const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message);};
const markerName='CHOPPER-COMPLETE.json';
// TypeScript's DOM library omits the directory's standard async iterator API.
const directoryNames=(directory:FileSystemDirectoryHandle)=>(directory as FileSystemDirectoryHandle&{keys():AsyncIterableIterator<string>}).keys();

// Delegate every operation to real OPFS handles. Only the second write to one
// large CSV is rejected, after its first chunk reached the real writable.
type ExportFault='write'|'close'|'marker_write'|'marker_close';
function observedDestination(parent:FileSystemDirectoryHandle,targetName:string|null,fault:ExportFault='write'){
  const state={injected_write_rejections:0,successful_target_writes_before_failure:0,abort_calls:0,closed_files:0,marker_opened_after_files_closed:false,marker_open_calls:0};
  const bind=(target:any,key:PropertyKey)=>{const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;};
  const handle=new Proxy(parent,{get(target,key){
    if(key!=='getDirectoryHandle')return bind(target,key);
    return async(name:string,options?:FileSystemGetDirectoryOptions)=>{
      const directory=await target.getDirectoryHandle(name,options);
      if(!options?.create)return directory;
      return new Proxy(directory,{get(target,key){
        if(key!=='getFileHandle')return bind(target,key);
        return async(name:string,options?:FileSystemGetFileOptions)=>{
          if(name===markerName){state.marker_open_calls++;state.marker_opened_after_files_closed=state.closed_files===6;}
          const file=await target.getFileHandle(name,options);
          return new Proxy(file,{get(target,key){
            if(key!=='createWritable')return bind(target,key);
            return async(options?:FileSystemCreateWritableOptions)=>{
              const writer=await target.createWritable(options);
              let targetWrites=0;
              const selected=name===(fault.startsWith('marker_')?markerName:targetName);
              return new Proxy(writer,{get(target,key){
                if(key==='write')return async(data:FileSystemWriteChunkType)=>{
                  if(selected&&((fault==='write'&&++targetWrites===2)||fault==='marker_write')){state.injected_write_rejections++;throw new DOMException('Injected destination write rejection','QuotaExceededError');}
                  await target.write(data);
                  if(selected)state.successful_target_writes_before_failure++;
                };
                if(key==='abort')return async(reason?:unknown)=>{if(selected)state.abort_calls++;await target.abort(reason);};
                if(key==='close')return async()=>{
                  if(selected&&(fault==='close'||fault==='marker_close'))throw new DOMException('Injected destination close rejection','UnknownError');
                  await target.close();if(name!==markerName)state.closed_files++;
                };
                return bind(target,key);
              }});
            };
          }});
        };
      }});
    };
  }});
  return {handle,state};
}

async function browserExportContract(root:DiskDirectory,parent:FileSystemDirectoryHandle,publication:any){
  const results=root.contents.get('results');
  assert(results instanceof DiskDirectory&&publication?.retained_for_browser_export===true,'Missing verified retained browser result');
  const source=results as DiskDirectory;
  let lastObservation:Observation={};
  const callbacks={observe:(observation:Observation)=>{lastObservation={...lastObservation,...observation};},postMessage:(_:unknown)=>{},profiling:()=>false,accountExport:(_:number,_start:number)=>{}};
  let report:any,failure:unknown;
  const cleanupErrors:unknown[]=[];
  let removedSourceFiles=0;
  try{
    assert(parent?.kind==='directory','Missing isolated OPFS export directory');
    for await(const _ of directoryNames(parent))throw new Error('Export test directory is not empty');
    const files=[...source.contents].map(([name,node])=>{
      assert(node instanceof DiskFile&&node.refs===0&&!node.source,'Retained result has unexpected file ownership');
      return {name,node:node as DiskFile};
    });
    assert(files.length===6,'Expected manifest and five retained CSVs');
    const published=publication.cases.find((item:any)=>item.mode==='published');
    assert(published?.retry_entries===1&&published.output_files===5&&published.output_csv_bytes===5120904,'Retained output did not follow admission retry');
    const complete=observedDestination(parent,null);
    await exportResults(source,complete.handle,'complete',callbacks);
    assert(lastObservation.export?.status==='completed'&&lastObservation.export.files===6&&lastObservation.marker?.status==='completed','Export observation did not confirm closed files and marker');
    const destination=await parent.getDirectoryHandle('complete');
    const successFiles:{name:string;bytes:number;sha256:string}[]=[];
    let csvFiles=0,csvBytes=0;
    for(const {name,node} of files){
      const file=await(await destination.getFileHandle(name)).getFile();
      assert(file.size===node.size,'Export changed file size: '+name);
      for(let offset=0;offset<node.size;){
        const expected=node.read(offset,1024*1024);
        assert(expected.length>0,'Retained result was truncated');
        const actual=new Uint8Array(await file.slice(offset,offset+expected.length).arrayBuffer());
        assert(actual.length===expected.length&&actual.every((value,index)=>value===expected[index]),'Export changed exact source bytes: '+name);
        offset+=expected.length;
      }
      // Verification is restricted to this small fixture; hashing never buffers
      // an arbitrary user output or changes the production export path.
      assert(file.size<=2*1024*1024,'Export verification fixture exceeded its per-file bound');
      const bytes=await file.arrayBuffer();
      const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('');
      successFiles.push({name,bytes:file.size,sha256});
      if(name.endsWith('.csv')){
        csvFiles++;csvBytes+=file.size;
        const prefix=new Uint8Array(bytes,0,2);
        assert(file.size<=published.byte_cap&&prefix[0]===0xff&&prefix[1]===0xfe,'Export violated CSV cap or BOM');
      }
    }
    assert(csvFiles===5&&csvBytes===5120904,'Export lost or duplicated CSVs');
    const marker=JSON.parse(await(await(await destination.getFileHandle(markerName)).getFile()).text());
    assert(marker.complete===true&&marker.files===6&&marker.engine==='chopper-browser'&&marker.version===1,'Invalid browser completion marker');
    assert(complete.state.closed_files===6&&complete.state.marker_opened_after_files_closed&&complete.state.marker_open_calls===1,'Marker was opened before all result writers closed');
    let destinationFiles=0;for await(const _ of directoryNames(destination))destinationFiles++;
    assert(destinationFiles===7,'Export produced unexpected destination entries');
    const target=files.find(file=>file.name.endsWith('.csv')&&file.node.size>1024*1024);
    assert(target,'Fixture has no multi-chunk CSV');
    const rejected=observedDestination(parent,target!.name);
    lastObservation={};
    let exportFailure:unknown;
    try{await exportResults(source,rejected.handle,'failed',callbacks);}catch(error){exportFailure=error;}
    assert(exportFailure instanceof DOMException&&exportFailure.name==='QuotaExceededError','Mid-copy rejection did not propagate');
    assert(lastObservation.export?.status==='failed'&&!lastObservation.marker,'Export failure attribution was lost');
    const absent=async(name:string)=>{
      try{await parent.getDirectoryHandle(name);return false;}
      catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')return true;throw error;}
    };
    const markerAbsent=await absent('failed');
    assert(markerAbsent&&rejected.state.marker_open_calls===0,'Failed export acquired a completion marker');
    assert(rejected.state.injected_write_rejections===1&&rejected.state.successful_target_writes_before_failure===1&&rejected.state.abort_calls===1,'Mid-copy rejection did not abort the real writable');
    assert(rejected.state.closed_files>0,'Mid-copy fixture did not retain an earlier closed file');
    const terminalFaults=[];
    for(const fault of ['close','marker_write','marker_close'] as const){
      const observed=observedDestination(parent,target!.name,fault);lastObservation={};
      let failure:unknown;
      try{await exportResults(source,observed.handle,fault,callbacks);}catch(error){failure=error;}
      assert(failure instanceof DOMException&&failure.name===(fault==='marker_write'?'QuotaExceededError':'UnknownError'),'Destination fault was lost: '+fault);
      assert(await absent(fault),'Failed export folder was not removed: '+fault);
      assert(fault==='close'?lastObservation.export?.status==='failed':lastObservation.marker?.status==='failed','Destination failure was not attributed to its physical step');
      assert(observed.state.abort_calls===1,'Failed destination writable was not aborted: '+fault);
      assert(observed.state.marker_open_calls===(fault==='close'?0:1),'Unexpected marker acquisition: '+fault);
      if(fault!=='close')assert(observed.state.closed_files===6&&observed.state.marker_opened_after_files_closed,'Marker fault preceded result close: '+fault);
      terminalFaults.push({fault,...observed.state,error_name:(failure as DOMException).name,completion_marker_bytes:0});
    }
    // A second export to the same destination must reject before modifying the
    // previously completed result or sending an export-start notification.
    let collision:unknown,collisionMessages=0,collisionStarts=0;
    try{await exportResults(source,parent,'complete',{...callbacks,postMessage:()=>{collisionMessages++;},observe:observation=>{if(observation.export?.status==='active')collisionStarts++;callbacks.observe(observation);}});}catch(error){collision=error;}
    assert(collision instanceof Error&&collision.message==='Result folder already exists. Analyze again.'&&collisionMessages===0&&collisionStarts===0,'Existing result was not rejected before export');
    assert(await(await(await destination.getFileHandle(markerName)).getFile()).text()===JSON.stringify(marker)+'\n','Existing result marker was modified');
    report={contract:'retained-parent-browser-export-contract-v1',source:'verified-wasi-retained-parent-retry',destination_context:'same-origin-opfs',source_files:files.length,csv_files:csvFiles,csv_bytes:csvBytes,byte_cap:published.byte_cap,exact_source_bytes:true,complete_marker:marker,marker_after_result_writers_closed:true,success_files:successFiles,failure:{...rejected.state,partial_directory_present:false,completion_marker_absent:true},terminal_faults:terminalFaults,existing_destination_rejected:true};
  }catch(error){failure=error;}
  finally{
    if(parent){
      for(const name of ['complete','failed','close','marker_write','marker_close'])try{await parent.removeEntry(name,{recursive:true});}catch(error){if(!(error instanceof DOMException&&error.name==='NotFoundError'))cleanupErrors.push(error);}
      try{for await(const _ of directoryNames(parent))throw new Error('Export destination children survived cleanup');}catch(error){cleanupErrors.push(error);}
    }
    for(const node of source.contents.values()){
      try{assert(node instanceof DiskFile&&node.refs===0&&!node.source,'Retained export source still has open owners');(node as DiskFile).unlink();removedSourceFiles++;}catch(error){cleanupErrors.push(error);}
    }
    source.contents.clear();root.contents.delete('results');
  }
  if(failure||cleanupErrors.length)throw new Error([...(failure?[failure]:[]),...cleanupErrors.map(error=>'Export cleanup: '+String(error))].map(String).join('\n'));
  assert(removedSourceFiles===6,'Retained export source cleanup missed files');
  return {...report,destination_folders_removed:true,retained_source_files_removed:true};
}

const scope=globalThis as unknown as {onmessage:(e:MessageEvent)=>void;postMessage:(v:unknown)=>void};
function inspectionContract(
  root:DiskDirectory,
  instance:WebAssembly.Instance,
  stdin:ReturnType<MemoryFile['path_open']>['fd_obj'],
  reply:()=>Record<string,unknown>,
){
  const invoke=(entry:string)=>{
    const run=instance.exports[entry];
    if(typeof run!=='function')throw new Error('Missing test reactor export '+entry);
    return run() as number;
  };
  const reserved=()=>invoke('chopper_test_inspection_reserved_bytes');
  const baseline=reserved();
  const encoder=new TextEncoder();
  const job=(output:string)=>JSON.stringify({input:'/input.csv',output});
  const exact=job('x'.repeat(8200));
  const expectedReads=[[8192,8192],[8192,42],[8192,0]];
  let paused:number[]=[];
  const readStdin=stdin.fd_read;
  stdin.fd_read=()=>{
    paused.push(reserved());
    return {ret:0,data:new Uint8Array()};
  };
  root.contents.set('input.csv',new MemoryFile(encoder.encode('id,value\n'+'1,a\n'.repeat(513)),{readonly:true}));
  const inspect=(entry:string,wire:string,failSecondRead=false)=>{
    const reads:number[][]=[];
    const source=new MemoryFile(encoder.encode(wire),{readonly:true});
    const open=source.path_open.bind(source);
    source.path_open=(...args)=>{
      const result=open(...args);
      const fd=result.fd_obj;
      const read=fd.fd_read.bind(fd);
      fd.fd_read=size=>{
        const chunk=failSecondRead&&reads.length===1?{ret:wasi.ERRNO_IO,data:new Uint8Array()}:read(size);
        reads.push([size,chunk.data.length]);
        return chunk;
      };
      return result;
    };
    root.contents.set('job.json',source);
    try{return {status:invoke(entry),result:reply(),reads};}
    finally{root.contents.delete('job.json');}
  };
  const calls=['chopper_analyze','chopper_preview','chopper_sniff','chopper_formula_scan'];
  try{
    const malformed='{"input":"/input.csv","output":]';
    const legacyError=inspect('chopper_run',malformed);
    assert(legacyError.status===1&&typeof legacyError.result.error==='string','Invalid legacy error fixture');
    for(const entry of calls){
      const rejected=inspect(entry,malformed);
      assert(rejected.status===1&&rejected.result.error===legacyError.result.error,'WASI error or position changed in '+entry);
      assert(JSON.stringify(rejected.reads)===JSON.stringify(legacyError.reads),'Malformed source read-ahead changed in '+entry);
    }
    const legacyIo=inspect('chopper_run',exact,true);
    const previewIo=inspect('chopper_preview',exact,true);
    assert(legacyIo.status===1&&previewIo.status===1&&typeof legacyIo.result.error==='string'&&
      previewIo.result.error===legacyIo.result.error&&JSON.stringify(previewIo.reads)===JSON.stringify([[8192,8192],[8192,0]])&&
      JSON.stringify(previewIo.reads)===JSON.stringify(legacyIo.reads)&&reserved()===baseline,'WASI source I/O error or second read changed');
    paused=[];
    const borrow=inspect('chopper_formula_scan',job(''));
    assert(borrow.status===0&&paused.length===1&&reserved()===baseline,'Formula pause control failed');
    const shortPause=paused[0];
    paused=[];
    const valid=calls.map(entry=>{
      const attempt=inspect(entry,exact);
      assert(attempt.status===0&&!attempt.result.error,'Inspection failed in '+entry+': '+attempt.result.error);
      assert(JSON.stringify(attempt.reads)===JSON.stringify(expectedReads),'Buffered source read sizes changed in '+entry);
      if(entry==='chopper_analyze')invoke('chopper_clear_profile');
      assert(reserved()===baseline,'Inspection retained a grant after returning from '+entry);
      return attempt.result;
    });
    assert(valid[0].rows===513&&valid[1].columns===2&&(valid[2].settings as {delimiter?:string})?.delimiter===','&&
      Array.isArray(valid[3].rows)&&valid[3].rows.length===512&&valid[3].done===false,'Inspection response changed');
    assert(paused.length===1&&paused[0]-shortPause===8200,'Formula pause lost the retained Job charge');
    const virtual=[1024*1024-1,1024*1024+1].map(bytes=>{
      const wire=job('x'.repeat(bytes-job('').length));
      const {status,result,reads}=inspect('chopper_preview',wire);
      const expected=Array.from({length:Math.ceil(bytes/8192)+1},(_,i)=>[8192,Math.max(0,Math.min(8192,bytes-i*8192))]);
      assert(status===0&&result.columns===2&&JSON.stringify(reads)===JSON.stringify(expected),'Virtual Job lost buffered reads or hit a file size cap');
      assert(reserved()===baseline,'Virtual Job retained a grant');
      return {bytes,source_reads:reads.length};
    });
    return {calls,source_reads:expectedReads,malformed_error:legacyError.result.error,source_io_error:legacyIo.result.error,formula_pause_job_bytes:paused[0]-shortPause,virtual};
  }finally{
    root.contents.delete('input.csv');
    stdin.fd_read=readStdin;
  }
}

scope.onmessage=async({data})=>{
  const diagnostics:string[]=[];
  try{
    const bridge=new DiskBridge(data.port,data.shared),root=new DiskDirectory(bridge);
    root.contents.set('tmp',new DiskDirectory(bridge));
    let result:Record<string,unknown>={};
    const stdin=new MemoryFile([]).path_open(0,0n,0).fd_obj;
    const wasi=new WASI(['chopper-resource-contracts'],['TMPDIR=/tmp',`CHOPPER_DISK_AVAILABLE=${data.available}`],[
      stdin,
      ConsoleStdout.lineBuffered(line=>{result=JSON.parse(line);}),
      ConsoleStdout.lineBuffered(line=>{diagnostics.push(line);scope.postMessage({diagnostic:line});}),
      new RootFd(root)
    ]);
    const instance=(await WebAssembly.instantiateStreaming(fetch(new URLSearchParams(location.search).has('shuffle-partition')?'/engine-resource-tests-shuffle-partition.wasm':'/engine-resource-tests.wasm'),{wasi_snapshot_preview1:wasi.wasiImport,chopper_compression:serialCompressionImports})).instance;
    wasi.initialize(instance as WebAssembly.Instance & {exports:{memory:WebAssembly.Memory}});
    const contract=instance.exports.chopper_resource_contracts;
    if(typeof contract!=='function')throw new Error('Resource-contract test export is missing');
    const status=contract();
    if(status!==0||result.error)throw new Error(String(result.error||'Resource contract failed'));
    const contracts=result;
    contracts.inspection_job_adapter=inspectionContract(root,instance,stdin,()=>result);
    const publication=(contracts.shuffle_partition as any)?.publication;
    const browserExport=publication?await browserExportContract(root,data.exportDirectory,publication):undefined;
    scope.postMessage({result:contracts,diagnostics,browserExport});
  }catch(error){scope.postMessage({error:[error instanceof Error?error.message:String(error),...diagnostics].join('\n')});}
};
