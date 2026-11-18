import {inspectAbandonedWorkspaces} from './cleanup';

export function configureCleanupControls(container:HTMLElement){
  const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent='Clear temporary data';button.hidden=true;
  button.title='Remove leftover browser workspaces from interrupted jobs. Active jobs and source/exported files are preserved.';
  const status=document.createElement('small');status.setAttribute('role','status');
  container.append(button);container.after(status);status.className='sr-only';container.hidden=true;
  let checking=false;
  async function refresh(remove=false,announce=false){
    if(checking)return;checking=true;button.disabled=true;
    try{
      const result=await inspectAbandonedWorkspaces(remove);
      container.hidden=button.hidden=result.remaining===0;
      status.className=result.remaining?'':'sr-only';
      status.textContent=result.remaining?`${result.remaining.toLocaleString()} unused workspace${result.remaining===1?'':'s'} remain${result.remaining===1?'s':''}.${remove?' Cleanup could not remove all data. Try again.':''}`:announce?`Cleared ${result.removed.toLocaleString()} abandoned workspace${result.removed===1?'':'s'}.`:'';
    }catch{
      // Unknown storage availability is not evidence of abandoned data.
      if(!button.hidden)status.textContent='Could not check temporary storage. Try again.';
    }finally{checking=false;button.disabled=false;}
  }
  button.onclick=()=>void refresh(true,true);
  window.addEventListener('focus',()=>void refresh());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refresh();});
  void refresh(true);
}
