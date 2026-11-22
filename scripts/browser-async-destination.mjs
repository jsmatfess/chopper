import {readFile} from 'node:fs/promises';
import {build} from '../ui/node_modules/esbuild/lib/main.js';

// Bench-only worker substitutions. One write may be outstanding per engine.
// The destination acknowledgement is separate from the temporary-storage RPC.
function replace(source, needle, replacement) {
  if (!source.includes(needle)) throw new Error('Missing async-write fixture anchor: ' + needle);
  return source.replace(needle, replacement);
}

export function asyncDestinationBridge(source) {
  const patched=replace(source, '  call(op: string,', `  private writeShared?:SharedArrayBuffer;
  private submittedWrite?:{length:number;started:number;deadline:number};
  private drainDestinationWrite(){
    const pending=this.submittedWrite;
    if(!pending)return;
    const shared=this.writeShared!;
    const control=new Int32Array(shared,0,4);
    const started=this.profiling?performance.now():0;
    while(Atomics.load(control,0)===0){
      const remaining=pending.deadline-performance.now();
      if(remaining<=0||Atomics.wait(control,0,0,remaining)==='timed-out')
        throw new Error('Browser destination write timed out.');
    }
    this.submittedWrite=undefined;
    if(Atomics.load(control,0)===-1)
      throw new Error(new TextDecoder().decode(new Uint8Array(shared,16).slice(0,control[1])));
    if(control[1]!==pending.length)throw new Error('Browser destination write returned a partial count.');
    this.record('destination_write',pending.length,pending.started);
    this.record('destination_write_drain',pending.length,started);
    this.onActivity?.();
  }
  call(op: string,`);
  return replace(patched,
    '    const start=this.profiling?performance.now():0;\n    if(data)',
    `    if(op.startsWith('destination_')){
      this.drainDestinationWrite();
      if(op==='destination_write'&&data){
        const shared=this.writeShared??=new SharedArrayBuffer(16+this.bytes.length);
        const control=new Int32Array(shared,0,4);
        const started=performance.now();
        new Uint8Array(shared,16).set(data);
        Atomics.store(control,0,0);
        this.submittedWrite={length:data.length,started,deadline:started+120000};
        this.port.postMessage({...args,op:'destination_write',writeShared:shared});
        return data.length;
      }
    }
    const start=this.profiling?performance.now():0;
    if(data)`);
}

export function asyncDestinationStorage(source) {
  let patched=replace(source,'let queue=Promise.resolve();',`let queue=Promise.resolve();
let destinationWrite=Promise.resolve();
let retiring=false;`);
  const dispatch='      port.onmessage=({data:m})=>{';
  patched=replace(patched,dispatch,`${dispatch}
        if(retiring)return;
        if(m.writeShared){
          destinationWrite=destinationWrite.then(async()=>{
            const writeControl=new Int32Array(m.writeShared,0,4);
            const writeBytes=new Uint8Array(m.writeShared,16);
            try {
              const n=await destinationOperation(m,writeBytes);
              Atomics.store(writeControl,1,n);Atomics.store(writeControl,0,1);
            } catch(error){
              const message=new TextEncoder().encode(String(error));
              writeBytes.set(message.subarray(0,writeBytes.length));
              Atomics.store(writeControl,1,Math.min(message.length,writeBytes.length));
              Atomics.store(writeControl,0,-1);
            }
            Atomics.notify(writeControl,0);
          });
          return;
        }`);
  return replace(patched,'      await queue;','      retiring=true;\n      await Promise.all([queue,destinationWrite]);');
}


export function batchDestinationStorage(source){
  let patched=replace(source,'const writers=',`const fixtureBlock=new Uint8Array(1024*1024);
let pending=0, pendingId, position;
async function flush(){
  if(!pending)return;
  await writers.get(pendingId).write({type:'write',position,data:fixtureBlock.subarray(0,pending)});
  pending=0;
}
const writers=`);
  patched=replace(patched,"  const writer=writers.get(m.id);","  if(m.op!=='destination_write')await flush();\n  const writer=writers.get(m.id);");
  return replace(patched,"      await writer.write({type:'write',position:m.offset,data:bytes.slice(0,m.length) as Uint8Array<ArrayBuffer>});",`      if(pending&&(pendingId!==m.id||position+pending!==m.offset||pending+m.length>fixtureBlock.length))await flush();
      if(!pending){pendingId=m.id;position=m.offset;}
      fixtureBlock.set(bytes.subarray(0,m.length),pending);
      pending+=m.length;`);
}

export async function compileDestinationWorker(name, transform, bridgeTransform=asyncDestinationBridge) {
  const directory='ui/src/browser';
  const path=directory+'/'+name+'.ts';
  const source=await readFile(path,'utf8');
  const patched=transform(source);
  if(patched===source)throw new Error('Benchmark variant did not modify '+path);
  const plugins=[{name:'async-bridge-fixture',setup(build){
    build.onResolve({filter:/^\.\/fs-async-fixture$/},()=>({path:'fs',namespace:'async-fixture'}));
    build.onLoad({filter:/^fs$/,namespace:'async-fixture'},async()=>({
      contents:bridgeTransform(await readFile(directory+'/fs.ts','utf8')),
      resolveDir:directory,loader:'ts',
    }));
  }}];
  const result=await build({plugins,stdin:{contents:patched,resolveDir:directory,sourcefile:name+'.ts',loader:'ts'},
    bundle:true,format:'esm',minify:true,write:false});
  return result.outputFiles[0].text;
}

export const disableStreamingOverlap=source=>replace(
  source,'const streamingOverlapEnabled=true;','const streamingOverlapEnabled=false;');
export const compileSynchronousDestinationEngine=()=>compileDestinationWorker('engine-worker',disableStreamingOverlap);
export const compileAsyncDestinationEngine=()=>compileDestinationWorker(
  'engine-worker',source=>disableStreamingOverlap(source).replace("from './fs'", "from './fs-async-fixture'"));
