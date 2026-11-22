import {renderExecutionHistory,type ExecutionHistory} from './execution-history';
import {BrowserLifecycle} from './session';
import {configureCleanupControls} from './cleanup-controls';
export let executionHistory:ExecutionHistory|null=null;
type PickerWindow=Window & {
  showOpenFilePicker(options?:unknown):Promise<FileSystemFileHandle[]>;
  showDirectoryPicker(options?:unknown):Promise<FileSystemDirectoryHandle>;
};
function supported(){
  if(!crossOriginIsolated||typeof SharedArrayBuffer==='undefined')throw new Error('Browser processing needs cross-origin isolation. Use the provided local server or the hosted HTTPS site.');
  if(!('showOpenFilePicker' in window)||!('showDirectoryPicker' in window)||!navigator.storage?.getDirectory||!navigator.locks)throw new Error('Browser processing currently requires desktop Chrome or Edge with file and folder access enabled.');
}
const lifecycle=new BrowserLifecycle({
  supported,
  lock:(name,hold)=>navigator.locks.request(name,hold),
  worker:path=>new Worker(path,{type:'module'}),channel:()=>new MessageChannel(),
  shared:bytes=>new SharedArrayBuffer(bytes),uuid:()=>crypto.randomUUID(),
  timeout:(callback,ms)=>setTimeout(callback,ms),clearTimeout:id=>clearTimeout(id),
  diagnostic:message=>console.warn(message),
  historyChanged:history=>{executionHistory=history;renderExecutionHistory(history);},
});
export const browserDiagnostics=lifecycle.diagnostics;
export function enableBrowserProfiling(){lifecycle.enableProfiling();}
export function invalidateBrowserDraft(source:string){lifecycle.invalidateDraft(source);}
export async function browserApi<T>(path:string,data?:any):Promise<T>{
  if(path==='pick-path'){
    supported();
    try{
      if(data.mode==='input'){
        const [handle]=await(window as unknown as PickerWindow).showOpenFilePicker({types:[{description:'CSV and compressed files',accept:{'text/csv':['.csv','.tsv','.txt'], 'application/octet-stream':['.gz','.gzip','.zip']}}]});
        const input=await handle.getFile();const control=document.getElementById('input') as HTMLInputElement|null;if(control){control.dataset.fileName=input.name;control.dataset.fileBytes=String(input.size);}lifecycle.selectInput(input);showTemporaryEstimate(input);return {path:input.name} as T;
      }
      const output=await(window as unknown as PickerWindow).showDirectoryPicker({mode:'readwrite'});
      lifecycle.selectOutput(output);return {path:output.name} as T;
    }catch(e){if(e instanceof DOMException&&e.name==='AbortError')return {path:null} as T;throw e;}
  }
  return await lifecycle.execute(path,data) as T;
}
export function temporarySpaceEstimate(file:{size:number;name:string}){
  const gib=(bytes:number)=>(bytes/1024**3).toLocaleString('en-US',{maximumFractionDigits:1,minimumFractionDigits:1})+' GiB';
  if(/\.(gz|gzip|zip)$/i.test(file.name))return 'Temporary storage can greatly exceed the compressed file size. No default temporary-space limit; available browser storage still applies.';
  return `Allow roughly ${gib(file.size*2)}–${gib(file.size*8)} of temporary storage for sorting or grouping. This is a rough guide, not an upper bound; pipelines and row shape can use more. No default temporary-space limit; available browser storage still applies.`;
}
function showTemporaryEstimate(file:File){
  const label=document.getElementById('input')?.closest('label');if(!label)return;
  let note=document.getElementById('temporary-space-estimate');
  if(!note){note=document.createElement('small');note.id='temporary-space-estimate';label.append(note);}
  note.textContent=temporarySpaceEstimate(file);
}
export function configureBrowserUI(){
  for(const id of ['input','output']){const el=document.getElementById(id) as HTMLInputElement;el.readOnly=true;el.placeholder='Choose with Browse';}
  (document.getElementById('memory') as HTMLInputElement).max='2048';
  const workers=document.getElementById('workers') as HTMLInputElement;
  document.getElementById('workers-label')!.textContent='Compression workers (0 = automatic)';
  const workerHelp=document.createElement('small');
  workerHelp.id='workers-help';
  workerHelp.textContent='Use 1 for serial compression. Auto uses up to four workers for gzip and ZIP.';
  workers.setAttribute('aria-describedby',workerHelp.id);
  workers.closest('label')!.append(workerHelp);
  const temporary=document.getElementById('temp-dir') as HTMLInputElement;
  temporary.disabled=true;temporary.setAttribute('aria-describedby','temp-dir-help');
  const help=document.createElement('small');help.id='temp-dir-help';help.textContent='Browser-managed storage is used automatically. This directory setting does not apply.';
  temporary.closest('label')!.append(help);
  configureCleanupControls(document.querySelector('.footer-cleanup')!);
  window.addEventListener('beforeunload',e=>{if(['profiling','running'].includes(lifecycle.snapshot().status)){e.preventDefault();e.returnValue='';}});
}
