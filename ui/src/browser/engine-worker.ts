import {StageCompletions} from './stages';
import {PhysicalHistory} from './physical-history';
import {ObservationDelivery} from './execution-history';
import {WASI, File as MemoryFile, ConsoleStdout} from '@bjorn3/browser_wasi_shim';
import {DiskBridge, DiskDirectory, DiskFile, RootFd} from './fs';
import {exportResults} from './export';
import {publicationResult} from './publication';
import {CompressionWorkers} from './compression';
import {compressBlock,initCompression} from './compression-worker';
import type {Job} from '../app';
const streamingOverlapEnabled=true;
const scope=globalThis as unknown as {onmessage:(e:MessageEvent)=>void;postMessage:(v:unknown)=>void};
let root:DiskDirectory;
let bridge:DiskBridge;
let instance:WebAssembly.Instance;
const compression=new CompressionWorkers();
let last:Record<string,unknown>={};
let inputPath='';
let observations:ObservationDelivery|null=null;
let physicalHistory=new PhysicalHistory();
let stages=new StageCompletions();
let physicalLastSent=0;
function collectPhysical(force=false){if(!observations||(!physicalHistory.summaries.size&&!physicalHistory.unavailable))return;const now=performance.now();if(!force&&physicalLastSent&&now-physicalLastSent<100)return;physicalLastSent=now;try{observations.update({physical:physicalHistory.snapshot(),unavailable:physicalHistory.unavailable||observations.unavailable});}catch{observations.update({unavailable:true});}}
const encoder=new TextEncoder();
function accountExport(bytes:number,start:number){
  if(!bridge.profiling)return;
  bridge.record('destination_write',bytes,start);
  bridge.call('account_export',{length:bytes});
}
function invoke(name:string){last={};(instance.exports[name] as ()=>number)();if(last.error)throw new Error(String(last.error));return last;}
scope.onmessage=async({data})=>{
  const {id,type}=data;
  if(type==='compression-init'){await initCompression(data.module);return;}
  if(type==='compress-block'){compressBlock(data);return;}
  try {
    let result:unknown, directDestination=false;
    if(type==='init'){
      bridge=new DiskBridge(data.port,data.shared);root=new DiskDirectory(bridge);
      root.contents.set('tmp',new DiskDirectory(bridge));
      const wasi=new WASI(['chopper-browser'],['TMPDIR=/tmp',`CHOPPER_DISK_AVAILABLE=${data.available}`],[
        new MemoryFile([]).path_open(0,0n,0).fd_obj,
        ConsoleStdout.lineBuffered(line=>{const message=JSON.parse(line);if(message.physical?.kind==='stage_complete'){if(observations){stages.accept(message.physical);observations.update({physical:physicalHistory.snapshot(),completedStages:stages.snapshot(),unavailable:stages.unavailable||observations.unavailable});}}else if(message.physical){if(observations){try{const prior=physicalHistory.summaries.get(message.physical.id);const transition=!prior||prior.status!==message.physical.status||prior.last_attempt!==message.physical.attempt;physicalHistory.accept(message.physical);observations.recordPhysical(message.physical);collectPhysical(transition);}catch{observations.update({unavailable:true});}}}else if(message.observation){try{observations?.update(message.observation);}catch{observations=null;}}else if(message.progress)scope.postMessage(message);else last=message;}),
        ConsoleStdout.lineBuffered(line=>scope.postMessage({diagnostic:line})),new RootFd(root)
      ]);
      // The upstream shim appends descriptors forever. Reuse closed slots for large fan-out jobs.
      const free:number[]=[];
      const close=wasi.wasiImport.fd_close,open=wasi.wasiImport.path_open;
      wasi.wasiImport.fd_close=(fd:number)=>{const result=close(fd);if(result===0)free.push(fd);return result;};
      wasi.wasiImport.path_open=(...args:any[])=>{
        const result=open(...args);
        if(result===0&&free.length){const fd=free.pop()!;wasi.fds[fd]=wasi.fds.pop()!;new DataView(wasi.inst.exports.memory.buffer).setUint32(args[8],fd,true);}
        return result;
      };
      const loaded=await WebAssembly.instantiateStreaming(fetch('/engine.wasm'),{
        wasi_snapshot_preview1:wasi.wasiImport,
        chopper_compression:compression.imports,
      });
      instance=loaded.instance;
      wasi.initialize(instance as WebAssembly.Instance & {exports:{memory:WebAssembly.Memory}});
      compression.init(loaded.module,instance.exports);
      result=invoke('chopper_defaults');
    } else if(type==='run-direct'||type==='columns'||type==='preview'||type==='sniff'||type==='profile'){
      physicalHistory=new PhysicalHistory();stages=new StageCompletions();physicalLastSent=0;
      observations=type==='run-direct'&&data.observationCredit?new ObservationDelivery(data.observationRun,new Int32Array(data.observationCredit),message=>scope.postMessage(message)):null;
      let destinationStarted=false;
      bridge.onActivity=observations?operation=>{
        if(operation==='destination_create'&&!destinationStarted){
          destinationStarted=true;
          observations?.update({export:{status:'active'}});
        }else observations?.flush();
      }:undefined;
      bridge.profiling=!!data.profiling;bridge.metrics={};
      if(inputPath)root.contents.delete(inputPath);
      inputPath='input'+((data.file.name as string).match(/\.[^.]+$/)?.[0]||'.csv');
      const plainCsv=streamingOverlapEnabled&&type==='run-direct'
        &&/\.csv$/i.test(data.file.name)&&data.job.compression==='none';
      const operations:Job['operations']|undefined=data.job?.operations;
      bridge.overlapDestination=plainCsv&&operations?.length===0;
      bridge.prefetchSource=bridge.overlapDestination
        ||(plainCsv&&operations?.length===1&&operations[0]?.type==='partition');
      root.contents.set(inputPath,new DiskFile(bridge,data.file));
      // ZIP reopens its manifest for archiving and needs the private filesystem.
      directDestination=type==='run-direct'&&['none','gzip'].includes(data.job.compression);
      if(directDestination){
        bridge.call('destination_init',{parent:data.output,folder:data.folder});
        root.directPublication=true;
      }
      const job:Job={...data.job,input:'/'+inputPath,output:'/results',resources:{...data.job.resources,temp_dir:'/tmp'}};
      root.contents.set('observe',new MemoryFile(new Uint8Array([observations?1:0]),{readonly:true}));
      root.contents.set('job.json',new MemoryFile(encoder.encode(JSON.stringify(job)),{readonly:true}));
      root.contents.delete('auto-observations.json');
      root.contents.delete('preview-observations.json');
      if(type==='run-direct'&&data.previewObservations){
        root.contents.set('preview-observations.json',new MemoryFile(encoder.encode(JSON.stringify(data.previewObservations)),{readonly:true}));
      }
      if(type==='run-direct'&&data.autoObservations){
        root.contents.set('auto-observations.json',new MemoryFile(encoder.encode(JSON.stringify(data.autoObservations)),{readonly:true}));
      }
      if(data.resetProfile)invoke('chopper_clear_profile');
      if(type==='run-direct'&&['gzip','zip'].includes(job.compression)
        &&job.resources.workers!==1&&data.file.size>=2*1024*1024){
        await compression.begin(job.resources.workers);
      }
      result=invoke(type==='profile'?'chopper_analyze':type==='columns'?'chopper_columns':type==='preview'?'chopper_preview':type==='sniff'?'chopper_sniff':'chopper_run');
      compression.close();
    }
    if(type==='run-direct'){
      const analysis=(result as {analysis:unknown}).analysis;
      if(bridge.profiling)scope.postMessage({profile:{phase:'execute',metrics:bridge.metrics}});
      bridge.metrics={};
      observations?.update({physical:physicalHistory.snapshot(),processingComplete:true,unavailable:physicalHistory.unavailable||observations.unavailable});
      if(directDestination){
        const published=root.contents.get('results') as DiskDirectory;
        const files=published.contents.size;
        observations?.update({export:{status:'completed',files},marker:{status:'active'}});
        try{
          if(bridge.call('destination_finish',{files})!==files)throw new Error('Destination file count disagrees with engine publication');
          observations?.update({marker:{status:'completed'}});
        }catch(error){observations?.update({marker:{status:'failed'}});throw error;}
        result=publicationResult(data.output,data.folder,files);
      }else{
        result=await exportResults(root.contents.get('results') as DiskDirectory,data.output,data.folder,{
          observe:observations?observation=>observations?.update(observation):undefined,
          postMessage:message=>scope.postMessage(message),profiling:()=>bridge.profiling,accountExport,
        });
      }
      result={...(result as object),analysis};
    } else if(!['init','columns','preview','sniff','profile'].includes(type))throw new Error('Unknown engine request');
    if(bridge?.profiling)scope.postMessage({profile:{phase:type==='run-direct'?'export':type,metrics:bridge.metrics}});
    collectPhysical(true);
    scope.postMessage({id,result,observationFinal:observations?.snapshot(),observationRun:data.observationRun});
    observations=null;
  }catch(e){compression.close();collectPhysical(true);scope.postMessage({id,error:e instanceof Error?e.message:String(e),observationFinal:observations?.snapshot(),observationRun:data.observationRun});observations=null;}
};
