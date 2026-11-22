// One slot per direction. The storage worker also owns one ordinary block
// for FileSystemWritableFileStream and one transient Blob read of window size.
export const SOURCE_WINDOW = 256 * 1024;
export const DESTINATION_BLOCK = 1024 * 1024;
export const STREAMING_IO_BYTES = 2 * (SOURCE_WINDOW + DESTINATION_BLOCK) + 24;

export function waitForStorage(control:Int32Array,deadline:number):boolean {
  // A notify can arrive after its completion was already observed.
  while(Atomics.load(control,0)===0){
    const remaining=deadline-performance.now();
    if(remaining<=0||Atomics.wait(control,0,0,remaining)==='timed-out')
      return Atomics.load(control,0)!==0;
  }
  return true;
}
