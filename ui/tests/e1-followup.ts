// E1 follow-up only: one invocation spans analyze, verification and disposal.
import {browserApi as api,enableBrowserProfiling,browserDiagnostics} from '../src/browser/client';
import type {Job,State} from '../src/app';
import {assert,equal,metadata,header,canonical} from './e1-followup-verifier.mjs';
import {records,disposeVerified,attemptDeadline} from './e1-followup-record.mjs';
const retained=records();
const clientIdentity=crypto.randomUUID();
const mode=new URLSearchParams(location.search).get('mode');
assert(mode==='FULL'||mode==='MINIMAL','explicit instrumentation mode required');
const digest=async(bytes:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
const decode=(bytes:ArrayBuffer)=>new TextDecoder('utf-8',{fatal:true}).decode(bytes);
async function inventory(directory:FileSystemDirectoryHandle,prefix=''):Promise<any[]>{
  const files:any[]=[];
  for await(const [name,h] of (directory as any).entries()){
    if(h.kind==='directory')files.push(...await inventory(h,prefix+name+'/'));
    else {const f=await h.getFile();files.push({path:prefix+name,bytes:f.size,sha256:await digest(await f.arrayBuffer())});}
  }
  return files.sort((a,b)=>a.path.localeCompare(b.path));
}
async function names(directory:FileSystemDirectoryHandle){const result=[];for await(const [name,handle] of (directory as any).entries())result.push({name,kind:handle.kind});return result.sort((a,b)=>a.name.localeCompare(b.name));}
async function workspaces(root:FileSystemDirectoryHandle){try{return await names(await root.getDirectoryHandle('chopper-workspaces'));}catch(e){if(e instanceof DOMException&&e.name==='NotFoundError')return [];throw e;}}
const samples:any[]=[];
if(mode==='FULL'){
  const NativeWorker=window.Worker;
  window.Worker=class extends NativeWorker {constructor(url:string|URL,options?:WorkerOptions){super(url,options);this.addEventListener('message',({data})=>{if(data.e1Space)samples.push(data.e1Space);});}};
}
async function run(spec:{shape:'columns'|'rare_wide';variant:'baseline'|'candidate';attempt:string;fixture:string;rows:number;tiny_payload_bytes?:number;cap?:number;admitted?:boolean;expected_parity?:string},bound:any){
  let config:Job|undefined,analysis:any,start:number|undefined,finished:number|undefined;
  const call=<T=any>(name:string,value?:any):Promise<T>=>bound.run(()=>api<T>(name,value));
  const scopes:any={polls:{ready:{count:0,api_ms:0},complete:{count:0,api_ms:0}}};
  async function wait(status:'ready'|'complete'){
    for(;;){const before=performance.now(),s=await call<State>('state');scopes.polls[status].count++;scopes.polls[status].api_ms+=performance.now()-before;
      if(s.status===status){assert(!s.error,'terminal error: '+s.error);return s;}
      if(s.status==='failed')throw new Error(s.error!);
      await bound.run(()=>new Promise(r=>setTimeout(r,10)));}
  }
  const root=await navigator.storage.getDirectory();
  const tiny=spec.rows<=128&&spec.rows>0&&Number.isSafeInteger(spec.rows);
  assert(tiny||(spec.admitted===true&&spec.rows===100000&&!spec.tiny_payload_bytes),'full-size jobs require separate admission');
  const parent=await root.getDirectoryHandle(tiny?'e1-followup-r02-tiny-selftest':'e1-followup-r02-admitted',{create:true});
  try{await parent.getDirectoryHandle(spec.attempt);throw new Error('Attempt destination already exists');}catch(e){if(!(e instanceof DOMException&&e.name==='NotFoundError'))throw e;}
  const parentBefore=await names(parent),destination=await parent.getDirectoryHandle(spec.attempt,{create:true});
  const before=await inventory(destination);samples.length=0;
  const wrapperStarted=new Date().toISOString();
  const pending:any=retained.retain(spec.attempt,{ok:false,type:'attempt-in-progress',...spec,mode,client_identity:clientIdentity,disposal:{state:'not-started'},destination_retained:true,wrapper_started:wrapperStarted,secondary_errors:[]});
  try{
    const response=await fetch('/'+spec.fixture);assert(response.ok,'fixture fetch failed');
    const file=new File([await response.arrayBuffer()],'benchmark.csv');
    Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>file}],showDirectoryPicker:async()=>destination});
    const defaults=await call<Job>('defaults');
    config={...defaults,input:file.name,output:'results',seed:'external-comparison-v1',compression:'none',full_shuffle_policy:'seeded_v1',full_shuffle_rng:'blake3_counter_v1',full_shuffle_algorithm:'adaptive_v1',
      input_csv:{encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false},
      output_csv:{encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false},
      limits:{rows:null,bytes:spec.cap??null,compressed_bytes:null},resources:{...defaults.resources,memory_mb:32,workers:1,max_record_bytes:2097152},
      operations:[{type:'shuffle',strategy:'uniform'},...(spec.shape==='rare_wide'?[{type:'balanced' as const,files:4}]:[])]};
    if(spec.cap)config.operations=[{type:'shuffle',strategy:'uniform'}];
    await call('pick-path',{mode:'input'});await call('pick-path',{mode:'output'});if(mode==='FULL')enableBrowserProfiling();
    start=performance.now();pending.primary_started_epoch_ms=performance.timeOrigin+start;await call('analyze',config);const ready=await wait('ready'),analyzed=performance.now();analysis=ready.analysis;
    await call('run',{});const done=await wait('complete');finished=performance.now();pending.primary_finished_epoch_ms=performance.timeOrigin+finished;
    scopes.analysis_wall_seconds=(analyzed-start)/1000;scopes.execution_seconds=(finished-analyzed)/1000;
    const verificationStart=performance.now();
    const folder=await destination.getDirectoryHandle(done.output!.split('/').at(-1)!);
    const manifest=decode(await(await(await folder.getFileHandle('manifest.jsonl')).getFile()).arrayBuffer());
    const verified=metadata(manifest,config,analysis,spec.shape,spec.rows);
    const exported=await inventory(folder);
    const marker=JSON.parse(decode(await(await(await folder.getFileHandle('CHOPPER-COMPLETE.json')).getFile()).arrayBuffer()));
    equal(Object.keys(marker).sort(),['complete','engine','files','version'],'marker schema mismatch');
    assert(marker.complete===true&&marker.engine==='chopper-browser'&&marker.version===1&&marker.files===exported.length-1,'completion marker invalid');
    equal(exported.map(x=>x.path).sort(),[...verified.outputs.map((x:any)=>x.path),'manifest.jsonl','CHOPPER-COMPLETE.json'].sort(),'unexpected export files');
    const seen=new Uint8Array(spec.rows),hashes:Record<string,string>={},memberships:Record<string,number[]>={};
    const tinyPayload=spec.tiny_payload_bytes?'x'.repeat(spec.tiny_payload_bytes):null;
    for(const entry of verified.outputs){
      const f=await(await folder.getFileHandle(entry.path)).getFile(),bytes=await f.arrayBuffer();
      assert(f.size===entry.csv_bytes,'manifest CSV byte mismatch');hashes[entry.path]=await digest(bytes);
      const text=decode(bytes);assert(text.endsWith('\n'),'missing final LF');const records=text.slice(0,-1).split('\n');assert(records.shift()===header.join(','),'CSV header mismatch');
      assert(records.length===entry.rows,'CSV quota mismatch');memberships[entry.path]=[];
      for(const record of records){const fields=record.split(','),id=Number(fields[0]);
        assert(Number.isSafeInteger(id)&&String(id)===fields[0]&&id>=0&&id<spec.rows&&!seen[id],'ID conservation failure');
        const payload=tinyPayload??(spec.shape==='rare_wide'&&id===0?'x'.repeat(1800000):'duplicate payload');
        assert(fields.length===33&&fields[1]===payload,'payload failure');for(let k=0;k<31;k++)assert(fields[k+2]===String((id+k)%10),'field failure');
        seen[id]=1;memberships[entry.path].push(id);
      }
    }
    assert(seen.every(Boolean),'missing ID');
    const d=analysis.diagnostics;assert(d.sort_runs>0,'no external sort');
    if(spec.variant==='candidate')assert(d.compact_spill_files>0&&d.compact_spill_blocks>0&&d.compact_spill_rows>=spec.rows&&d.compact_spill_fallbacks===0,'candidate blocks absent/fallback');
    else assert(d.compact_spill_files===0&&d.compact_spill_blocks===0&&d.compact_spill_fallbacks===0,'baseline feature mismatch');
    const workspaceAfter=await workspaces(root);assert(workspaceAfter.length===0,'workspace retained after complete');
    if(mode==='FULL'){const storage=browserDiagnostics.storage as any;assert(storage&&storage.workspace_bytes_after_cleanup===0&&storage.peak_open_handles<=64&&storage.profiled_destination_bytes===exported.reduce((n,f)=>n+f.bytes,0),'profile accounting mismatch');assert(samples.length>0,'FULL sampler absent');}
    else {assert(samples.length===0&&Object.keys(browserDiagnostics).length===0,'MINIMAL instrumentation present');}
    // Retain all verified results in memory before destroying the successful destination.
    const result=Object.assign(pending,{ok:true,type:tiny?'tiny-harness-selftest':'admitted-full-job',...spec,mode,config,analysis,manifest,hashes,memberships,marker,before,after:await inventory(destination),workspace_after:workspaceAfter,
      parity:canonical({logical:verified.logical,outputs:verified.outputs,hashes,memberships,config:verified.job.config,algorithm_version:verified.job.algorithm_version,schema_version:verified.job.schema_version,application_version:verified.job.application_version}),
      elapsed_seconds:(finished-start)/1000,diagnostics:mode==='FULL'?structuredClone(browserDiagnostics):null,space_samples:mode==='FULL'?structuredClone(samples):null,
      cpu_seconds:null,rss_bytes:null,allocator_bytes:null,physical_io_bytes:null,wrapper_started:wrapperStarted});
    if(spec.expected_parity)assert(JSON.stringify(result.parity)===spec.expected_parity,'exact seeded CSV/order/metadata parity mismatch');
    scopes.verification_seconds=(performance.now()-verificationStart)/1000;const disposalStart=performance.now();
    await disposeVerified(result,{dispose:()=>bound.run(()=>parent.removeEntry(spec.attempt,{recursive:true})),inventory:()=>bound.run(()=>names(parent)),workspace:()=>bound.run(()=>workspaces(root)),check:(parentAfter:any,spaces:any)=>{equal(parentAfter,parentBefore,'post-disposal inventory changed');assert(spaces.length===0,'workspace reappeared');}});
    const outerFinished=performance.now();scopes.disposal_and_inventory_seconds=(outerFinished-disposalStart)/1000;
    return Object.assign(result,{scopes,wrapper_finished:new Date().toISOString()});
  }catch(e){
    if(spec.cap===1000000&&String(e).includes('one row plus header exceeds output byte limit')){
      await call('cancel',{});const after=await inventory(destination),workspaceAfter=await workspaces(root);
      assert(after.length===0&&workspaceAfter.length===0,'cap rejection retained output/workspace');
      const verified=Object.assign(pending,{ok:true,type:'expected-cap-rejection',error:String(e),config,before,after,workspace_after:workspaceAfter});
      await disposeVerified(verified,{dispose:()=>bound.run(()=>parent.removeEntry(spec.attempt,{recursive:true})),inventory:()=>bound.run(()=>names(parent)),workspace:()=>bound.run(()=>workspaces(root)),check:(post:any,spaces:any)=>{equal(post,parentBefore,'cap disposal changed parent');assert(spaces.length===0,'cap workspace reappeared');}});
      return Object.assign(verified,{wrapper_finished:new Date().toISOString()});
    }
    Object.assign(pending,{ok:false,type:'followup-job-failure',error:String(e),config,analysis,elapsed_seconds:start!==undefined&&finished!==undefined?(finished-start)/1000:null,scopes,space_samples:mode==='FULL'?samples:null,diagnostics:mode==='FULL'?structuredClone(browserDiagnostics):null,wrapper_finished:new Date().toISOString()});
    for(const [stage,action] of [['inventory',()=>bound.run(()=>inventory(destination))],['workspace',()=>bound.run(()=>workspaces(root))]] as const)try{pending[stage]=await action();}catch(secondary){pending.secondary_errors.push({stage,error:String(secondary)});}
    return pending;
  }
}
Object.assign(window,{e1FollowupIdentity:()=>clientIdentity,e1FollowupRetrieve:(id:string)=>retained.get(id),e1FollowupAcknowledge:(id:string)=>retained.acknowledge(id),e1FollowupRun:async(spec:any)=>{
  // One bound starts at invocation, including setup; it never resets at ready.
  const bound=attemptDeadline(300000);
  try{return await bound.run(()=>run(spec,bound));}catch(error){const record=retained.get(spec.attempt);if(record){record.ok=false;record.error=String(error);record.wrapper_finished=new Date().toISOString();}throw error;}
}});
