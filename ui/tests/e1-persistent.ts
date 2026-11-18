// Bounded E1 experiment only. Failed destinations and the profile are retained.
import {browserApi as api,enableBrowserProfiling,browserDiagnostics} from '../src/browser/client';
import type {Job,State} from '../src/app';
const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message);};
const digest=async(bytes:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
function decisionAuditBytes(d:any):number {
  const a=d.shuffle_partition_decisions;if(a===undefined)return 0;
  assert(a.version===1&&a.policy==='experiment_gate_v1'&&a.capacity===16,'unsupported decision audit');
  assert(a.selector===null&&a.calibration===null,'unsupported decision selector');
  assert(typeof a.initialized==='boolean'&&typeof a.collection_denied==='boolean','invalid audit state');
  assert(Number.isSafeInteger(a.reserved_bytes)&&a.reserved_bytes>=0,'invalid audit reservation');
  assert(Array.isArray(a.records)&&a.records.length<=a.capacity,'invalid bounded audit records');
  assert(Number.isSafeInteger(a.omitted_attempts)&&a.omitted_attempts>=0&&a.completed_attempts===a.records.length+a.omitted_attempts,'invalid audit counts');
  assert(a.initialized&&!a.collection_denied?a.reserved_bytes>0:a.reserved_bytes===0&&a.records.length===0,'audit owner/state mismatch');return a.reserved_bytes;
}
function retainedOwners(d:any){
  const owners=['temporary_path_reserved_bytes','directory_path_reserved_bytes','input_header_reserved_bytes','prepared_job_reserved_bytes','analysis_preview_reserved_bytes','column_values_reserved_bytes','stage_stats_reserved_bytes','analysis_text_reserved_bytes','analysis_warnings_reserved_bytes','analysis_timings_reserved_bytes','analysis_diagnostics_reserved_bytes'];
  assert(d.workspace_reserved_bytes===owners.reduce((n,key)=>n+(d[key]??0),0)+decisionAuditBytes(d),'retained ownership equation failed');
}
async function inventory(directory:FileSystemDirectoryHandle,prefix=''):Promise<any[]>{
  const files:any[]=[];
  for await(const [name,h] of (directory as any).entries()){
    if(h.kind==='directory')files.push(...await inventory(h,prefix+name+'/'));
    else {const f=await h.getFile();files.push({path:prefix+name,bytes:f.size,sha256:await digest(await f.arrayBuffer())});}
  }
  return files.sort((a,b)=>a.path.localeCompare(b.path));
}
const samples:any[]=[];
const NativeWorker=window.Worker;
// The storage-worker build posts throttled snapshots of its existing logical
// size ledger. No new sync handle or filesystem scan competes with the engine.
window.Worker=class extends NativeWorker {
  constructor(url:string|URL,options?:WorkerOptions){super(url,options);this.addEventListener('message',({data})=>{if(data.e1Space)samples.push(data.e1Space);});}
};
async function wait(status:string){const deadline=performance.now()+300000;for(;;){const s=await api<State>('state');if(s.status===status){assert(!s.error,'terminal error: '+s.error);return s;}if(s.status==='failed')throw new Error(s.error!);assert(performance.now()<deadline,'E1 timed out');await new Promise(r=>setTimeout(r,10));}}
Object.assign(window,{e1Run:async(shape:'columns'|'rare_wide',attempt:string,rejectWide=false)=>{
  let config:Job|undefined,elapsed:number|undefined,analysis:any;
  const root=await navigator.storage.getDirectory();
  const parent=await root.getDirectoryHandle('e1-persistent-20261024T151800Z',{create:true});
  // Refuse reuse of an attempt even if a prior run only created its directory.
  try {await parent.getDirectoryHandle(attempt);throw new Error('Attempt destination already exists');}
  catch(e){if(!(e instanceof DOMException&&e.name==='NotFoundError'))throw e;}
  const destination=await parent.getDirectoryHandle(attempt,{create:true});
  const before=await inventory(destination);
  samples.length=0;
  try {
    const file=new File([await(await fetch('/'+shape+'.csv')).arrayBuffer()],'benchmark.csv');
    Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>file}],showDirectoryPicker:async()=>destination});
    const defaults=await api<Job>('defaults');
    config={...defaults,input:file.name,output:'results',seed:'external-comparison-v1',compression:'none',full_shuffle_policy:'seeded_v1',full_shuffle_rng:'blake3_counter_v1',full_shuffle_algorithm:'adaptive_v1',
      input_csv:{encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false},
      output_csv:{encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false},
      limits:{rows:null,bytes:null,compressed_bytes:null},resources:{...defaults.resources,memory_mb:32,workers:1,max_record_bytes:2097152},
      operations:[{type:'shuffle',strategy:'uniform'},...(shape==='rare_wide'?[{type:'balanced' as const,files:4}]:[])]};
    if(rejectWide){config.operations=[{type:'shuffle',strategy:'uniform'}];config.limits.bytes=1000000;}
    await api('pick-path',{mode:'input'});await api('pick-path',{mode:'output'});enableBrowserProfiling();
    const start=performance.now();await api('analyze',config);const ready=await wait('ready'),analyzed=performance.now();analysis=ready.analysis;
    await api('run',{});const done=await wait('complete'),finished=performance.now();elapsed=(finished-start)/1000;
    // All remaining work is outside elapsed. Complete already awaited stop().
    assert(analysis.rows===100000&&analysis.workers===1,'input count/workers mismatch');retainedOwners(analysis.diagnostics);
    const folder=await destination.getDirectoryHandle(done.output!.split('/').at(-1)!);
    const manifest=await(await(await folder.getFileHandle('manifest.jsonl')).getFile()).text();
    const entries=manifest.trim().split('\n').map(line=>JSON.parse(line));
    const outputs=entries.filter(e=>e.type==='output');
    assert(outputs.length===(shape==='columns'?1:4),'output count mismatch');
    const exported=await inventory(folder);
    const marker=JSON.parse(await(await(await folder.getFileHandle('CHOPPER-COMPLETE.json')).getFile()).text());
    assert(marker.complete===true&&marker.engine==='chopper-browser'&&marker.version===1&&marker.files===exported.length-1,'completion marker invalid');
    assert(exported.length===outputs.length+2,'unexpected export files');
    const expectedHeader=['id','payload',...Array.from({length:31},(_,k)=>'c'+k)].join(',');
    const seen=new Uint8Array(100000);const hashes:Record<string,string>={};let total=0;
    for(const entry of outputs){
      const f=await(await folder.getFileHandle(entry.path)).getFile();const bytes=await f.arrayBuffer();
      assert(f.size===entry.csv_bytes,'manifest CSV bytes mismatch');hashes[entry.path]=await digest(bytes);total+=f.size;
      const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);assert(text.endsWith('\n'),'missing final LF');
      const records=text.slice(0,-1).split('\n');assert(records.shift()===expectedHeader,'header mismatch');
      assert(records.length===entry.rows&&entry.rows===(shape==='columns'?100000:25000),'manifest count/balanced quota mismatch');
      for(const record of records){
        const fields=record.split(','),id=Number(fields[0]);
        assert(Number.isSafeInteger(id)&&String(id)===fields[0]&&id>=0&&id<100000&&!seen[id],'ID conservation failure');
        assert(fields.length===33&&fields[1]===(shape==='rare_wide'&&id===0?'x'.repeat(1800000):'duplicate payload'),'payload failure');
        for(let k=0;k<31;k++)assert(fields[k+2]===String((id+k)%10),'field failure');seen[id]=1;
      }
    }
    assert(seen.every(Boolean)&&total===analysis.output_csv_bytes&&outputs.length===analysis.output_files,'output total mismatch');
    const storage=browserDiagnostics.storage as any;
    assert(storage&&storage.workspace_bytes_after_cleanup===0&&storage.peak_open_handles<=64&&storage.profiled_destination_bytes===exported.reduce((n,f)=>n+f.bytes,0),'workspace/export accounting mismatch');
    const workspaces=await root.getDirectoryHandle('chopper-workspaces');const remaining=[];for await(const [name] of (workspaces as any).entries())remaining.push(name);
    assert(remaining.length===0,'workspace directory retained after complete');
    return {ok:true,attempt,shape,config,analysis,manifest,hashes,marker,before,after:await inventory(destination),workspace_after:remaining,
      elapsed_seconds:elapsed,analysis_wall_seconds:(analyzed-start)/1000,execution_seconds:(finished-analyzed)/1000,
      diagnostics:structuredClone(browserDiagnostics),space_samples:samples,cpu_seconds:null,rss_bytes:null,allocator_bytes:null,physical_io_bytes:null};
  }catch(e){
    if(rejectWide&&String(e).includes('one row plus header exceeds output byte limit')){
      // Complete failure cleanup before inspecting its workspace or allowing retry.
      await api('cancel',{});const after=await inventory(destination);
      const workspaces=await root.getDirectoryHandle('chopper-workspaces');const remaining=[];for await(const [name] of (workspaces as any).entries())remaining.push(name);
      assert(after.length===0&&remaining.length===0,'wide rejection left output/workspace');
      return {ok:true,expected_rejection:String(e),attempt,shape,config,before,after,workspace_after:remaining};
    }
    return {ok:false,error:String(e),attempt,shape,config,analysis,elapsed_seconds:elapsed,space_samples:samples,diagnostics:structuredClone(browserDiagnostics),after:await inventory(destination)};
  }
},e1Dispose:async(attempt:string)=>{
  const root=await navigator.storage.getDirectory();const parent=await root.getDirectoryHandle('e1-persistent-20261024T151800Z');await parent.removeEntry(attempt,{recursive:true});return await inventory(parent);
}});
