export type PublicationReceipt={kind:'browser-completion-marker';version:1;folder:string;files:number;marker:'CHOPPER-COMPLETE.json'};
declare const verified:unique symbol;
export type VerifiedPublication=Readonly<{output:string;receipt:PublicationReceipt;[verified]:true}>;
// The worker creates this wire receipt only after exact marker readback. The
// session checks the destination binding before promoting a cloned response.
export function verifyPublication(result:unknown,folder:string,output:string):VerifiedPublication {
 const value=result as {output?:unknown;publication?:Partial<PublicationReceipt>};const receipt=value?.publication;
 if(value?.output!==output||!receipt||receipt.kind!=='browser-completion-marker'||receipt.version!==1||receipt.folder!==folder||receipt.marker!=='CHOPPER-COMPLETE.json'||!Number.isSafeInteger(receipt.files)||receipt.files!<1)throw new Error('Missing or invalid verified publication receipt');
 return Object.freeze({output,receipt:Object.freeze({kind:'browser-completion-marker',version:1,folder,files:receipt.files!,marker:'CHOPPER-COMPLETE.json'})}) as VerifiedPublication;
}

const markerName='CHOPPER-COMPLETE.json';

export class DestinationPublication {
  private directory?:FileSystemDirectoryHandle;
  private closed=0;
  private preserveMarker=false;

  constructor(private readonly parent:FileSystemDirectoryHandle,readonly name:string){}

  get closedFiles(){return this.closed;}

  async open(onCreate?:()=>void){
    if(!this.directory){
      try{await this.parent.getDirectoryHandle(this.name);throw new Error('Result folder already exists. Analyze again.');}
      catch(error){if(!(error instanceof DOMException&&error.name==='NotFoundError'))throw error;}
      this.directory=await this.parent.getDirectoryHandle(this.name,{create:true});
      onCreate?.();
    }
    return this.directory;
  }

  async removeFile(name:string){
    await this.directory?.removeEntry(name);
  }

  async closeFile(writer:FileSystemWritableFileStream){
    await writer.close();
    this.closed++;
  }

  async finish(expectedFiles:number,account:(bytes:number,start:number)=>void){
    if(!this.directory||this.closed!==expectedFiles)throw new Error('Destination files are still open or missing');
    const markerHandle=await this.directory.getFileHandle(markerName,{create:true});
    const marker=await markerHandle.createWritable();
    const text=JSON.stringify({complete:true,files:this.closed,engine:'chopper-browser',version:1})+'\n';
    const bytes=new TextEncoder().encode(text);
    try{
      const start=performance.now();
      await marker.write(bytes);
      account(bytes.length,start);
      await marker.close();
      this.preserveMarker=true;
    }catch(error){await marker.abort().catch(()=>{});throw error;}
    try{
      const file=await markerHandle.getFile();
      if(file.size===bytes.length&&await file.text()===text)return this.closed;
    }catch(error){
      if(error instanceof DOMException&&error.name==='NotFoundError')this.preserveMarker=false;
      throw new Error('Could not verify completion marker',{cause:error});
    }
    this.preserveMarker=false;
    throw new Error('Could not verify completion marker: content did not match');
  }

  async cleanup(){
    if(!this.directory)return undefined;
    if(!this.preserveMarker&&await removeIncompleteDestination(this.parent,this.name,this.directory,this.closed))return null;
    return this.name;
  }
}

async function removeIncompleteDestination(parent:FileSystemDirectoryHandle,name:string,owned:FileSystemDirectoryHandle,files:number){
  try{
    const current=await parent.getDirectoryHandle(name);
    if(!await owned.isSameEntry(current))return false;
    try{
      const marker=await(await current.getFileHandle(markerName)).getFile();
      if(marker.size<=256){
        const text=await marker.text();
        try{
          const record=JSON.parse(text);
          if(record?.complete===true&&record.engine==='chopper-browser'&&record.version===1&&record.files===files)return false;
        }catch{/* Incomplete marker. */}
      }
    }catch(error){if(!(error instanceof DOMException&&error.name==='NotFoundError'))throw error;}
    await parent.removeEntry(name,{recursive:true});
    return true;
  }catch(error){
    if(!(error instanceof DOMException&&error.name==='NotFoundError'))throw new Error(`Could not remove incomplete output ${parent.name}/${name}: ${error}`,{cause:error});
    return true;
  }
}

export function publicationResult(parent:FileSystemDirectoryHandle,name:string,files:number){
  const publication:PublicationReceipt={kind:'browser-completion-marker',version:1,folder:name,files,marker:markerName};
  return {output:parent.name+'/'+name,publication};
}
