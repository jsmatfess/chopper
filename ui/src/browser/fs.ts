import {Directory, OpenDirectory, Fd, Inode, wasi} from '@bjorn3/browser_wasi_shim';
import {DESTINATION_BLOCK,SOURCE_WINDOW,waitForStorage} from './streaming-io';

// Only metadata lives in this tree. File contents always live on disk or in the selected File.
export class DiskBridge {
  profiling = false;
  onActivity?:(operation?:string)=>void;
  metrics: Record<string,{calls:number;bytes:number;seconds:number}> = {};
  record(op:string,bytes:number,start:number){
    if(!this.profiling)return;
    const metric=this.metrics[op]??={calls:0,bytes:0,seconds:0};
    metric.calls++;metric.bytes+=bytes;metric.seconds+=(performance.now()-start)/1000;
  }
  control: Int32Array;
  bytes: Uint8Array;
  constructor(public port: MessagePort, shared: SharedArrayBuffer) {
    this.control = new Int32Array(shared, 0, 4);
    this.bytes = new Uint8Array(shared, 16);
  }
  prefetchSource=false;
  overlapDestination=false;
  private pendingWrite?:{
    shared:SharedArrayBuffer;control:Int32Array;bytes:Uint8Array;
    length:number;started:number;
  };
  private drainWrite(){
    const pending=this.pendingWrite;
    if(!pending?.length)return;
    const start=this.profiling?performance.now():0;
    if(!waitForStorage(pending.control,pending.started+120000))
      throw new Error('Browser destination write timed out.');
    if(Atomics.load(pending.control,0)===-1)
      throw new Error(new TextDecoder().decode(pending.bytes.slice(0,pending.control[1])));
    if(pending.control[1]!==pending.length)throw new Error('Browser destination write returned a partial count.');
    this.record('destination_write',pending.length,pending.started);
    this.record('destination_write_drain',pending.length,start);
    pending.length=0;
    this.onActivity?.();
  }
  private submitWrite(args:Record<string,unknown>,data:Uint8Array){
    if(!this.pendingWrite){
      const shared=new SharedArrayBuffer(16+DESTINATION_BLOCK);
      this.pendingWrite={shared,control:new Int32Array(shared,0,4),bytes:new Uint8Array(shared,16),length:0,started:0};
    }
    const pending=this.pendingWrite;
    pending.bytes.set(data);
    Atomics.store(pending.control,0,0);
    pending.length=data.length;
    pending.started=performance.now();
    this.port.postMessage({...args,op:'stream_write',slot:pending.shared});
    return data.length;
  }
  call(op: string, args: Record<string, unknown> = {}, data?: Uint8Array): number {
    if(this.overlapDestination&&op.startsWith('destination_')){
      this.drainWrite();
      if(op==='destination_write'&&data?.length)return this.submitWrite(args,data);
    }
    const start=this.profiling?performance.now():0;
    if(data) this.bytes.set(data);
    Atomics.store(this.control, 0, 0);
    this.port.postMessage({op,...args});
    if(!waitForStorage(this.control,performance.now()+120000))
      throw new Error('Browser storage timed out.');
    if(Atomics.load(this.control, 0)===-1) {
      // Chromium's TextDecoder requires an ordinary buffer, including on errors.
      throw new Error(new TextDecoder().decode(this.bytes.slice(0,this.control[1])));
    }
    this.record(op,this.control[1],start);
    if(this.profiling)for(const [name,index] of [['handle_open',2],['handle_eviction',3]] as const){
      const metric=this.metrics[name]??={calls:0,bytes:0,seconds:0};
      metric.calls+=Atomics.load(this.control,index);
    }
    this.onActivity?.(op);
    return this.control[1];
  }
}
let nextId=0;
export class DiskFile extends Inode {
  id=String(++nextId); size=0; refs=0; linked=true;
  private sourceCache=new Uint8Array(0);
  private sourceOffset=0;
  private prefetched?:{shared:SharedArrayBuffer;control:Int32Array;offset:number;length:number};
  private takePrefetched(offset:number,length:number){
    const pending=this.prefetched;
    if(!pending||pending.offset!==offset||pending.length!==length)return;
    const start=performance.now();
    // Speculation cannot replace a current read, including a stalled prefetch.
    const ready=waitForStorage(pending.control,start+5000);
    this.bridge.record('source_prefetch_wait',length,start);
    if(ready)pending.offset=-1;
    if(!ready||Atomics.load(pending.control,0)!==1||pending.control[1]!==length){
      this.bridge.record('source_prefetch_fallback',length,start);
      return;
    }
    return new Uint8Array(pending.shared,8,length).slice();
  }
  private prefetch(offset:number){
    if(!this.source||offset>=this.size)return;
    if(!this.prefetched){
      const shared=new SharedArrayBuffer(8+SOURCE_WINDOW);
      this.prefetched={shared,control:new Int32Array(shared,0,2),offset:-1,length:0};
    }
    const pending=this.prefetched;
    if(pending.offset>=0&&Atomics.load(pending.control,0)===0)return;
    const start=this.bridge.profiling?performance.now():0;
    pending.offset=offset;
    pending.length=Math.min(SOURCE_WINDOW,this.size-offset);
    Atomics.store(pending.control,0,0);
    this.bridge.port.postMessage({op:'stream_prefetch',slot:pending.shared,blob:this.source.slice(offset,offset+pending.length)});
    this.bridge.record('source_prefetch_request',pending.length,start);
  }
  constructor(public bridge:DiskBridge, public source?:File,private destinationName?:string) {
    super();
    if(source)this.size=source.size;
    else this.call('create');
  }
  private call(op:string,args:Record<string,unknown>={},data?:Uint8Array){
    return this.bridge.call(this.destinationName?'destination_'+op:op,{id:this.id,name:this.destinationName,...args},data);
  }
  sync(){if(!this.source)this.call('flush');}
  close(){this.refs--;if(this.destinationName&&!this.refs)this.call('close');this.release();}
  stat(){return new wasi.Filestat(this.ino,wasi.FILETYPE_REGULAR_FILE,BigInt(this.size));}
  path_open(oflags:number,rights:bigint,flags:number){
    if(this.source && ((oflags&wasi.OFLAGS_TRUNC)||(rights&BigInt(wasi.RIGHTS_FD_WRITE)))) return {ret:wasi.ERRNO_PERM,fd_obj:null};
    if(oflags&wasi.OFLAGS_TRUNC)this.truncate(0);
    const fd=new DiskFd(this);if(flags&wasi.FDFLAGS_APPEND)fd.position=this.size;
    return {ret:0,fd_obj:fd};
  }
  read(offset:number,length:number):Uint8Array {
    length=Math.min(length,this.bridge.bytes.length,Math.max(0,this.size-offset));
    if(!length)return new Uint8Array();
    if(this.source) {
      // Share one bounded window across descriptors; offsets remain descriptor-local.
      if(offset>=this.sourceOffset&&offset+length<=this.sourceOffset+this.sourceCache.length)
        return this.sourceCache.subarray(offset-this.sourceOffset,offset-this.sourceOffset+length);
      this.sourceCache=new Uint8Array(0);
      const batch=Math.min(Math.max(length,SOURCE_WINDOW),this.size-offset);
      const Reader=(globalThis as unknown as {FileReaderSync:new()=>{readAsArrayBuffer(blob:Blob):ArrayBuffer}}).FileReaderSync;
      const start=this.bridge.profiling?performance.now():0;
      const prefetched=this.takePrefetched(offset,batch);
      const bytes=prefetched??new Uint8Array(new Reader().readAsArrayBuffer(this.source.slice(offset,offset+batch)));
      if(!prefetched)this.bridge.record('source_read',bytes.length,start);
      if(bytes.length<=SOURCE_WINDOW){
        this.sourceCache=bytes;this.sourceOffset=offset;
        if(this.bridge.prefetchSource&&bytes.length)this.prefetch(offset+bytes.length);
      }
      return bytes.subarray(0,length);
    }
    const n=this.call('read',{offset,length});
    return this.bridge.bytes.slice(0,n);
  }
  write(offset:number,data:Uint8Array):number {
    if(this.source)throw new Error('Input is read-only.');
    const part=data.subarray(0,this.bridge.bytes.length);
    const n=this.call('write',{offset,length:part.length},part);
    this.size=Math.max(this.size,offset+n);return n;
  }
  truncate(size:number){if(this.source)throw new Error('Input is read-only.');this.call('truncate',{size});this.size=size;}
  unlink(){this.linked=false;this.release();}
  release(){if(!this.refs)this.sourceCache=new Uint8Array(0);if(!this.source&&!this.linked&&!this.refs)this.call('delete');}
}
class DiskFd extends Fd {
  position=0;
  constructor(public file:DiskFile){super();file.refs++;}
  fd_close(){this.file.close();return 0;}
  fd_fdstat_get(){return {ret:0,fdstat:new wasi.Fdstat(wasi.FILETYPE_REGULAR_FILE,0)};}
  fd_filestat_get(){return {ret:0,filestat:this.file.stat()};}
  fd_filestat_set_size(size:bigint){this.file.truncate(Number(size));return 0;}
  fd_sync(){this.file.sync();return 0;}
  fd_tell(){return {ret:0,offset:BigInt(this.position)};}
  fd_seek(offset:bigint,whence:number){
    const base=whence===wasi.WHENCE_SET?0:whence===wasi.WHENCE_CUR?this.position:whence===wasi.WHENCE_END?this.file.size:NaN;
    const pos=base+Number(offset);if(!Number.isSafeInteger(pos)||pos<0)return {ret:wasi.ERRNO_INVAL,offset:0n};
    this.position=pos;return this.fd_tell();
  }
  fd_read(size:number){const result=this.fd_pread(size,BigInt(this.position));this.position+=result.data.length;return result;}
  fd_pread(size:number,offset:bigint){return {ret:0,data:this.file.read(Number(offset),size)};}
  fd_write(data:Uint8Array){const result=this.fd_pwrite(data,BigInt(this.position));this.position+=result.nwritten;return result;}
  fd_pwrite(data:Uint8Array,offset:bigint){return {ret:0,nwritten:this.file.write(Number(offset),data)};}
}
class DiskDirectoryFd extends OpenDirectory {
  path_unlink_file(path:string){
    const entry=this.path_lookup(path,0).inode_obj;
    const result=super.path_unlink_file(path);
    if(result===0&&entry instanceof DiskFile)entry.unlink();return result;
  }
}
export class DiskDirectory extends Directory {
  directPublication=false;
  constructor(public bridge:DiskBridge,private destinationStage=false){super(new Map());}
  path_open(){return {ret:0,fd_obj:new DiskDirectoryFd(this)};}
  create_entry_for_path(path:string,isDir:boolean){
    const result=super.create_entry_for_path(path,isDir);
    if(result.ret!==0)return result;
    const parts=path.split('/').filter(p=>p&&p!=='.');const name=parts.pop()!;
    let parent:Directory=this;for(const part of parts)parent=parent.contents.get(part) as Directory;
    const directory=parent as DiskDirectory;
    // Context::staging_directory creates this sibling before renaming it to /results.
    const entry=isDir?new DiskDirectory(this.bridge,directory.directPublication&&name.startsWith('.chopper-staging-'))
      :new DiskFile(this.bridge,undefined,directory.destinationStage?name:undefined);
    parent.contents.set(name,entry);return {ret:0,entry};
  }
}
export class RootFd extends DiskDirectoryFd {
  fd_prestat_get(){return {ret:0,prestat:wasi.Prestat.dir('/')};}
}
