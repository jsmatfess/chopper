// Bench-only: keep the current parsed window plus one outstanding read.
export function sourcePrefetchBridge(source) {
  const anchor='  private sourceOffset=0;';
  if(!source.includes(anchor))throw new Error('Missing source refill anchor');
  const refill='      const prefetched=this.takePrefetched(offset,batch);';
  if(!source.includes(refill))throw new Error('Missing synchronous source read anchor');
  return source.replace(anchor,`${anchor}
  private lookahead?:{shared:SharedArrayBuffer;offset:number;length:number};
  private takeLookahead(offset:number,length:number):Uint8Array|undefined {
    const pending=this.lookahead;
    if(!pending||pending.offset!==offset||pending.length!==length)return;
    const control=new Int32Array(pending.shared,0,2);
    const start=performance.now();
    const deadline=start+120000;
    while(Atomics.load(control,0)===0){
      const timeout=deadline-performance.now();
      if(timeout<=0||Atomics.wait(control,0,0,timeout)==='timed-out')
        throw new Error('Browser source prefetch timed out.');
    }
    pending.offset=-1;
    this.bridge.record('source_prefetch_wait',length,start);
    if(Atomics.load(control,0)!==1||control[1]!==length)return;
    return new Uint8Array(pending.shared,8,length).slice();
  }
  private scheduleLookahead(offset:number) {
    if(!this.source||offset>=this.size)return;
    const state=this.lookahead??={shared:new SharedArrayBuffer(8+256*1024),offset:-1,length:0};
    const control=new Int32Array(state.shared,0,2);
    if(state.offset>=0&&Atomics.load(control,0)===0)return;
    const start=performance.now();
    state.offset=offset;
    state.length=Math.min(256*1024,this.size-offset);
    Atomics.store(control,0,0);
    this.bridge.port.postMessage({op:'source_prefetch',shared:state.shared,blob:this.source.slice(offset,offset+state.length)});
    this.bridge.record('source_prefetch_request',state.length,start);
  }`).replace(refill,'      const prefetched=this.takeLookahead(offset,batch);')
    .replace('        if(this.bridge.prefetchSource&&bytes.length)this.prefetch(offset+bytes.length);',
      '        if(bytes.length)this.scheduleLookahead(offset+bytes.length);');
}

export function sourcePrefetchStorage(source) {
  const anchors=['let queue=Promise.resolve();','      port.onmessage=({data:m})=>{','      await queue;'];
  if(anchors.some(anchor=>!source.includes(anchor)))throw new Error('Missing source prefetch storage anchor');
  return source.replace(anchors[0],`${anchors[0]}
let sourceRead=Promise.resolve();
let retiring=false;`).replace(anchors[1],`      port.onmessage=({data:m})=>{
        if(retiring)return;
        if(m.op==='source_prefetch'){
          sourceRead=sourceRead.then(async()=>{
            const control=new Int32Array(m.shared,0,2);
            const slot=new Uint8Array(m.shared,8);
            try{
              const data=new Uint8Array(await m.blob.arrayBuffer());
              slot.set(data);
              Atomics.store(control,1,data.length);
              Atomics.store(control,0,1);
            }catch{
              Atomics.store(control,0,-1);
            }
            Atomics.notify(control,0);
          });
          return;
        }`).replace(anchors[2],`      retiring=true;
      await Promise.all([queue,sourceRead]);`);
}
