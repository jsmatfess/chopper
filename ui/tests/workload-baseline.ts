import {browserApi as api} from '../src/browser/client';
import type {Job,State} from '../src/app';

declare global {
  interface Window {
    workloadBaseline:(job:Job)=>Promise<unknown>;
  }
}

window.workloadBaseline=async(job:Job)=>{
  const input=(document.querySelector('#fixture') as HTMLInputElement).files?.[0];
  if(!input)throw new Error('Select the declared local fixture first');
  const root=await navigator.storage.getDirectory();
  const parent=await root.getDirectoryHandle('workload-baseline-'+crypto.randomUUID(),{create:true});
  Object.assign(window,{
    showOpenFilePicker:async()=>[{getFile:async()=>input}],
    showDirectoryPicker:async()=>parent
  });
  const setup=performance.now();
  const defaults=await api<Job>('defaults');
  await api('pick-path',{mode:'input'});
  await api('pick-path',{mode:'output'});
  const configuration={...defaults,...job,input:input.name,output:'results',
    resources:{...defaults.resources,...job.resources,temp_dir:null}};
  const setupSeconds=(performance.now()-setup)/1000;
  const start=performance.now();
  // Run directly: explicit analyze/Prepare would measure a different workflow.
  await api('run-direct',configuration);
  let done:State;
  while(true){
    done=await api<State>('state');
    if(done.status==='complete'){
      if(done.error)throw new Error(done.error);
      break;
    }
    if(done.status==='failed')throw new Error(done.error||'Browser Run failed');
    if(performance.now()-start>120000)throw new Error('Browser baseline timed out');
    await new Promise(resolve=>setTimeout(resolve,10));
  }
  const elapsed=(performance.now()-start)/1000;
  const folder=await parent.getDirectoryHandle(done.output!.split('/').at(-1)!);
  // Host extraction/independent verification occurs after the measured completion.
  const files:{name:string;base64:string}[]=[];
  for await(const [name,handle] of (folder as any).entries()){
    const file=await handle.getFile();
    const base64=await new Promise<string>((resolve,reject)=>{
      const reader=new FileReader();reader.onerror=()=>reject(reader.error);
      reader.onload=()=>resolve(String(reader.result).split(',')[1]);
      reader.readAsDataURL(file);
    });
    files.push({name,base64});
  }
  const marker=files.find(file=>file.name==='CHOPPER-COMPLETE.json');
  if(!marker)throw new Error('Browser output missing completion marker');
  await api('cancel',{});
  return {elapsed_seconds:elapsed,setup_seconds:setupSeconds,files,
    analysis:done.analysis,output:done.output,
    timing_scope:'Run-direct through completed OPFS export; setup/extraction/verification excluded',
    destination:'OPFS-backed picker; not native File System Access output performance',
    input_mode:'Playwright-selected local File'};
};
