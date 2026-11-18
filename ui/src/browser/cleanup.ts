// Hold the same workspace lock as engine/storage owners through inspection and
// deletion. ifAvailable skips live tabs/workers without waiting for their jobs.
export async function inspectAbandonedWorkspaces(remove=false){
  let root:FileSystemDirectoryHandle;
  try{root=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-workspaces');}
  catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')return {removed:0,remaining:0};throw error;}
  let removed=0,remaining=0;
  for await(const [name,entry] of (root as unknown as {entries():AsyncIterable<[string,FileSystemHandle]>}).entries()){
    if(entry.kind!=='directory'||!/^[0-9a-f-]{36}$/.test(name))continue;
    await navigator.locks.request('chopper-'+name,{ifAvailable:true},async lock=>{
      if(!lock)return;
      try{
        // Another cleaner may have removed a directory yielded before we locked it.
        await root.getDirectoryHandle(name);
        if(remove){try{await root.removeEntry(name,{recursive:true});removed++;}
          catch(error){if(!(error instanceof DOMException&&error.name==='NotFoundError'))remaining++;}}
        else remaining++;
      }catch(error){if(!(error instanceof DOMException&&error.name==='NotFoundError'))throw error;}
    });
  }
  return {removed,remaining};
}
export async function clearAbandonedWorkspaces(){return (await inspectAbandonedWorkspaces(true)).removed;}
