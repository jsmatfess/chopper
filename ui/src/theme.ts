type Theme='system'|'light'|'dark';
const key='chopper-color-scheme';
const normalize=(value:string|null):Theme=>value==='light'||value==='dark'?value:'system';
export function configureTheme(){
 let meta=document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
 if(!meta){meta=document.createElement('meta');meta.name='color-scheme';document.head.append(meta);}
 const scheme=meta;
 const media=matchMedia('(prefers-color-scheme: dark)');
 const label=document.createElement('div');label.className='theme-control';
 label.innerHTML='<button type="button" aria-label="Switch color theme"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><g class="theme-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></g><path class="theme-moon" d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/></svg></button>';
 const button=label.querySelector('button')!;
 document.querySelector('.rail')!.append(label);
 let storage:Storage|undefined,choice:Theme='system';
 try{storage=localStorage;choice=normalize(storage.getItem(key));}catch{/* The theme remains usable when site storage is blocked. */}
 const resolved=()=>choice==='system'?(media.matches?'dark':'light'):choice;
 function render(){
  scheme.content=choice==='system'?'light dark':choice;
  button.dataset.choice=choice;button.dataset.resolved=resolved();
  const action=`Switch to ${resolved()==='dark'?'light':'dark'} theme`;
  button.setAttribute('aria-label',action);
  button.title=`${action} · Currently ${resolved()}${choice==='system'?' (system)':''}`;
 }
 button.addEventListener('click',()=>{
  const target=resolved()==='dark'?'light':'dark';
  choice=target===(media.matches?'dark':'light')?'system':target;render();
  try{if(choice==='system')storage?.removeItem(key);else storage?.setItem(key,choice);}catch{/* Current-tab selection still applies. */}
 });
 media.addEventListener('change',render);
 window.addEventListener('storage',event=>{
  if(event.storageArea&&event.storageArea!==storage)return;
  if(event.key===key||event.key===null){choice=normalize(event.newValue);render();}
 });
 render();
}
