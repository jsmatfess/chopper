import {StageCompletions} from './stages';
import {PhysicalHistory} from './physical-history';
import {ObservationDelivery} from './execution-history';
import {WASI, File as MemoryFile, ConsoleStdout} from '@bjorn3/browser_wasi_shim';
import {DiskBridge, DiskDirectory, DiskFile, RootFd} from './fs';
import {exportResults} from './export';
import type {Job} from '../app';
const scope=globalThis as unknown as {onmessage:(e:MessageEvent)=>void;postMessage:(v:unknown)=>void};
let root:DiskDirectory;
let bridge:DiskBridge;
let instance:WebAssembly.Instance;
let last:Record<string,unknown>={};
let inputPath='';
let observations:ObservationDelivery|null=null;
let physicalHistory=new PhysicalHistory();
let stages=new StageCompletions();
let physicalLastSent=0;
function collectPhysical(force=false){if(!observations||(!physicalHistory.summaries.size&&!physicalHistory.unavailable))return;const now=performance.now();if(!force&&physicalLastSent&&now-physicalLastSent<100)return;physicalLastSent=now;try{observations.update({physical:physicalHistory.snapshot(),unavailable:physicalHistory.unavailable||observations.snapshot().unavailable});}catch{observations.update({unavailable:true});}}
const encoder=new TextEncoder();
function accountExport(bytes:number,start:number){
  if(!bridge.profiling)return;
  bridge.record('destination_write',bytes,start);
  bridge.call('account_export',{length:bytes});
}
function invoke(name:string){last={};(instance.exports[name] as ()=>number)();if(last.error)throw new Error(String(last.error));return last;}
scope.onmessage=async({data})=>{
  const {id,type}=data;
  try {
    let result:unknown;
    if(type==='init'){
      bridge=new DiskBridge(data.port,data.shared);bridge.onActivity=()=>observations?.flush();root=new DiskDirectory(bridge);
      root.contents.set('tmp',new DiskDirectory(bridge));
      const wasi=new WASI(['chopper-browser'],['TMPDIR=/tmp',`CHOPPER_DISK_AVAILABLE=${data.available}`],[
        new MemoryFile([]).path_open(0,0n,0).fd_obj,
        ConsoleStdout.lineBuffered(line=>{const message=JSON.parse(line);if(message.physical?.kind==='stage_complete'){if(observations){stages.accept(message.physical);observations.update({physical:physicalHistory.snapshot(),completedStages:stages.snapshot(),unavailable:stages.unavailable||observations.snapshot().unavailable});}}else if(message.physical){if(observations){try{const prior=physicalHistory.summaries.get(message.physical.id);const transition=!prior||prior.status!==message.physical.status||prior.last_attempt!==message.physical.attempt;physicalHistory.accept(message.physical);observations.recordPhysical(message.physical);collectPhysical(transition);}catch{observations.update({unavailable:true});}}}else if(message.observation){try{observations?.update(message.observation);}catch{observations=null;}}else if(message.progress)scope.postMessage(message);else last=message;}),
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
      instance=(await WebAssembly.instantiateStreaming(fetch('/engine.wasm'),{wasi_snapshot_preview1:wasi.wasiImport})).instance;
      wasi.initialize(instance as WebAssembly.Instance & {exports:{memory:WebAssembly.Memory}});
      result=invoke('chopper_defaults');
    } else if(type==='run-direct'||type==='columns'||type==='preview'||type==='sniff'||type==='profile'){
      physicalHistory=new PhysicalHistory();stages=new StageCompletions();physicalLastSent=0;
      observations=type==='run-direct'&&data.observationCredit?new ObservationDelivery(data.observationRun,new Int32Array(data.observationCredit),message=>scope.postMessage(message)):null;
      bridge.profiling=!!data.profiling;bridge.metrics={};
      if(inputPath)root.contents.delete(inputPath);
      inputPath='input'+((data.file.name as string).match(/\.[^.]+$/)?.[0]||'.csv');
      root.contents.set(inputPath,new DiskFile(bridge,data.file));
      const job:Job={...data.job,input:'/'+inputPath,output:'/results',resources:{...data.job.resources,temp_dir:'/tmp'}};
      root.contents.set('observe',new MemoryFile(new Uint8Array([observations?1:0]),{readonly:true}));
      root.contents.set('job.json',new MemoryFile(encoder.encode(JSON.stringify(job)),{readonly:true}));
      if(data.resetProfile)invoke('chopper_clear_profile');
      result=invoke(type==='profile'?'chopper_analyze':type==='columns'?'chopper_columns':type==='preview'?'chopper_preview':type==='sniff'?'chopper_sniff':'chopper_run');
    }
    if(type==='run-direct'){
      const analysis=(result as {analysis:unknown}).analysis;
      if(bridge.profiling)scope.postMessage({profile:{phase:'execute',metrics:bridge.metrics}});
      bridge.metrics={};
      observations?.update({physical:physicalHistory.snapshot(),processingComplete:true,unavailable:physicalHistory.unavailable||observations.snapshot().unavailable});
      result=await exportResults(root.contents.get('results') as DiskDirectory,data.output,data.folder,{
        observe:observations?observation=>observations?.update(observation):undefined,
        postMessage:message=>scope.postMessage(message),profiling:()=>bridge.profiling,accountExport,
      });
      result={...(result as object),analysis};
    } else if(!['init','columns','preview','sniff','profile'].includes(type))throw new Error('Unknown engine request');
    if(bridge?.profiling)scope.postMessage({profile:{phase:type==='run-direct'?'export':type,metrics:bridge.metrics}});
    collectPhysical(true);
    scope.postMessage({id,result,observationFinal:observations?.snapshot(),observationRun:data.observationRun});
    observations=null;
  }catch(e){collectPhysical(true);scope.postMessage({id,error:e instanceof Error?e.message:String(e),observationFinal:observations?.snapshot(),observationRun:data.observationRun});observations=null;}
};
