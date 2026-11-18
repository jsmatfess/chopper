import {Directory, OpenDirectory, Fd, Inode, wasi} from '@bjorn3/browser_wasi_shim';

// Only metadata lives in this tree. File contents always live on disk or in the selected File.
export class DiskBridge {
  profiling = false;
  onActivity?:()=>void;
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
  call(op: string, args: Record<string, unknown> = {}, data?: Uint8Array): number {
    const start=this.profiling?performance.now():0;
    if(data) this.bytes.set(data);
    Atomics.store(this.control, 0, 0);
    this.port.postMessage({op,...args});
    // A previous completion can be observed before its notify, which may then
    // wake this request. Only the completion flag makes this response valid.
    const deadline=performance.now()+120000;
    while(Atomics.load(this.control,0)===0){
      const remaining=deadline-performance.now();
      if(remaining<=0||Atomics.wait(this.control,0,0,remaining)==='timed-out')
        throw new Error('Browser storage timed out.');
    }
    if(Atomics.load(this.control, 0)===-1) {
      // Chromium's TextDecoder requires an ordinary buffer, including on errors.
      throw new Error(new TextDecoder().decode(this.bytes.slice(0,this.control[1])));
    }
    this.record(op,this.control[1],start);
    if(this.profiling)for(const [name,index] of [['handle_open',2],['handle_eviction',3]] as const){
      const metric=this.metrics[name]??={calls:0,bytes:0,seconds:0};
      metric.calls+=Atomics.load(this.control,index);
    }
    this.onActivity?.();
    return this.control[1];
  }
}
let nextId=0;
export class DiskFile extends Inode {
  id=String(++nextId); size=0; refs=0; linked=true;
  private sourceCache=new Uint8Array(0);
  private sourceOffset=0;
  constructor(public bridge:DiskBridge, public source?:File) {super();if(source)this.size=source.size;else bridge.call('create',{id:this.id});}
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
      const batch=Math.min(Math.max(length,256*1024),this.size-offset);
      const Reader=(globalThis as unknown as {FileReaderSync:new()=>{readAsArrayBuffer(blob:Blob):ArrayBuffer}}).FileReaderSync;
      const start=this.bridge.profiling?performance.now():0;
      const bytes=new Uint8Array(new Reader().readAsArrayBuffer(this.source.slice(offset,offset+batch)));
      this.bridge.record('source_read',bytes.length,start);
      if(bytes.length<=256*1024){this.sourceCache=bytes;this.sourceOffset=offset;}
      return bytes.subarray(0,length);
    }
    const n=this.bridge.call('read',{id:this.id,offset,length});
    return this.bridge.bytes.slice(0,n);
  }
  write(offset:number,data:Uint8Array):number {
    if(this.source)throw new Error('Input is read-only.');
    const part=data.subarray(0,this.bridge.bytes.length);
    const n=this.bridge.call('write',{id:this.id,offset,length:part.length},part);
    this.size=Math.max(this.size,offset+n);return n;
  }
  truncate(size:number){if(this.source)throw new Error('Input is read-only.');this.bridge.call('truncate',{id:this.id,size});this.size=size;}
  unlink(){this.linked=false;this.release();}
  release(){if(!this.refs)this.sourceCache=new Uint8Array(0);if(!this.source&&!this.linked&&!this.refs)this.bridge.call('delete',{id:this.id});}
}
class DiskFd extends Fd {
  position=0;
  constructor(public file:DiskFile){super();file.refs++;}
  fd_close(){this.file.refs--;this.file.release();return 0;}
  fd_fdstat_get(){return {ret:0,fdstat:new wasi.Fdstat(wasi.FILETYPE_REGULAR_FILE,0)};}
  fd_filestat_get(){return {ret:0,filestat:this.file.stat()};}
  fd_filestat_set_size(size:bigint){this.file.truncate(Number(size));return 0;}
  fd_sync(){if(!this.file.source)this.file.bridge.call('flush',{id:this.file.id});return 0;}
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
  constructor(public bridge:DiskBridge){super(new Map());}
  path_open(){return {ret:0,fd_obj:new DiskDirectoryFd(this)};}
  create_entry_for_path(path:string,isDir:boolean){
    const result=super.create_entry_for_path(path,isDir);
    if(result.ret!==0)return result;
    const parts=path.split('/').filter(p=>p&&p!=='.');const name=parts.pop()!;
    let parent:Directory=this;for(const part of parts)parent=parent.contents.get(part) as Directory;
    const entry=isDir?new DiskDirectory(this.bridge):new DiskFile(this.bridge);
    parent.contents.set(name,entry);return {ret:0,entry};
  }
}
export class RootFd extends DiskDirectoryFd {
  fd_prestat_get(){return {ret:0,prestat:wasi.Prestat.dir('/')};}
}
