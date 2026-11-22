import {browserApi as api,enableBrowserProfiling,browserDiagnostics} from '../src/browser/client';
import type {Job, State} from '../src/app';
Object.assign(window,{benchmarkProfile:async(config:Partial<Job>)=>{
  const file=new File([await(await fetch('/benchmark.csv')).arrayBuffer()],'benchmark.csv');
  Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>file}]});
  const defaults=await api<Job>('defaults');
  await api('pick-path',{mode:'input'});
  const run=async()=>{
    const start=performance.now();
    await api('profile',{...defaults,...config,input:file.name});
    const deadline=start+300000;
    while(performance.now()<deadline){
      const state=await api<State>('state');
      if(state.status==='profiled')return {profile:state.profile,elapsed_seconds:(performance.now()-start)/1000};
      if(state.status==='failed')throw new Error(state.error!);
      await new Promise(r=>setTimeout(r,10));
    }
    throw new Error('Profile benchmark timed out');
  };
  return {fresh:await run(),cached:await run()};
}});
Object.assign(window,{benchmark:async(config:Partial<Job>,verifySimple=false)=>{
  enableBrowserProfiling();
  const root=await navigator.storage.getDirectory();
  const name='benchmark-'+crypto.randomUUID();
  const destination=await root.getDirectoryHandle(name,{create:true});
  const file=new File([await(await fetch('/benchmark.csv')).arrayBuffer()],'benchmark.csv');
  Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>file}],showDirectoryPicker:async()=>destination});
  const defaults=await api<Job>('defaults');
  await api('pick-path',{mode:'input'});await api('pick-path',{mode:'output'});
  const wait=async(status:string)=>{const deadline=performance.now()+300000;while(performance.now()<deadline){const state=await api<State>('state');if(state.status===status)return state;if(state.status==='failed')throw new Error(state.error!);await new Promise(r=>setTimeout(r,10));}throw new Error('Benchmark timed out');};
  try{
    const start=performance.now();
    await api('run-direct',{...defaults,...config,input:file.name,output:'results'});
    const done=await wait('complete'),finished=performance.now();
    const folder=await destination.getDirectoryHandle(done.output!.split('/').at(-1)!);
    const manifest=await (await (await folder.getFileHandle('manifest.jsonl')).getFile()).text();
    const hashes:Record<string,string>={};
    const sourceRecords=verifySimple?(await file.text()).trimEnd().split('\n'):null;
    const seen=sourceRecords?new Uint8Array(sourceRecords.length-1):null;
    let destinationBytes=0;
    for await(const [name,handle] of (folder as any).entries()){
      const file=await handle.getFile();destinationBytes+=file.size;
      if(name==='CHOPPER-COMPLETE.json'||name==='manifest.jsonl')continue;
      const bytes=name.endsWith('.gz')?await new Response(file.stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer():await file.arrayBuffer();
      hashes[name]=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      if(sourceRecords&&seen){
        const records=new TextDecoder(config.output_csv?.encoding||'utf-8').decode(bytes).trimEnd().split('\n').map(row=>row.replace(/\r$/,''));
        if(records.shift()!==sourceRecords[0])throw new Error('Fixture header changed');
        for(const record of records){const id=Number(record.split(',')[0]);if(!Number.isInteger(id)||id<0||id>=seen.length||seen[id]||(record!==sourceRecords[id+1]&&JSON.stringify(record.split(',').map(v=>v==='""'?'':v))!==JSON.stringify(sourceRecords[id+1].split(',').map(v=>v==='""'?'':v))))throw new Error('Fixture fields/IDs changed');seen[id]=1;}
      }
    }
    if(seen&&!seen.every(Boolean))throw new Error('Fixture IDs lost');
    const storage=browserDiagnostics.storage as {profiled_destination_bytes:number;workspace_bytes_after_cleanup:number;peak_open_handles:number}|undefined;
    if(!storage||storage.profiled_destination_bytes!==destinationBytes||storage.workspace_bytes_after_cleanup!==0||storage.peak_open_handles>64)throw new Error('Browser storage/export accounting mismatch');
    return {conservation_verified:!!seen,diagnostics:structuredClone(browserDiagnostics),analysis:done.analysis,manifest,timing_scope:'complete Run including publication/export and cleanup',analysis_wall_seconds:null,execution_seconds:(finished-start)/1000,elapsed_seconds:(finished-start)/1000,hashes};
  }finally{await api('cancel',{});await root.removeEntry(name,{recursive:true});}
}});
