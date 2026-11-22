import {WASI} from '@bjorn3/browser_wasi_shim';
import {serialCompressionImports} from './compression';

type Codec = {
  memory: WebAssembly.Memory;
  chopper_compression_input(): number;
  chopper_compression_output(): number;
  chopper_compression_encode(bytes: number): number;
};

async function loadCodec(module: WebAssembly.Module): Promise<Codec> {
  const wasi = new WASI([], [], []);
  const instance = await WebAssembly.instantiate(module, {
    wasi_snapshot_preview1: wasi.wasiImport,
    chopper_compression: serialCompressionImports,
  }) as WebAssembly.Instance & {exports: Codec};
  wasi.initialize(instance);
  return instance.exports;
}

let codec: Codec | undefined;
export async function initCompression(module: WebAssembly.Module) {
  try {
    codec = await loadCodec(module);
    postMessage('compression-ready');
  } catch {
    postMessage('compression-failed');
  }
}

export function compressBlock(data: {
  shared: SharedArrayBuffer;
  size: number;
  capacity: number;
}) {
  const {shared, size, capacity} = data;
  const status = new Int32Array(shared, 0, 1);
  let written = -1;
  try {
    const wasm = codec;
    if (!wasm) return;
    const ptr = wasm.chopper_compression_input();
    new Uint8Array(wasm.memory.buffer, ptr, size).set(new Uint8Array(shared, 4, size));
    const compressed = wasm.chopper_compression_encode(size);
    if (compressed > 0 && compressed <= shared.byteLength - 4 - capacity) {
      const ptr = wasm.chopper_compression_output();
      new Uint8Array(shared, 4 + capacity, compressed).set(new Uint8Array(wasm.memory.buffer, ptr, compressed));
      written = compressed;
    }
  } catch {
    // The engine still owns the input and can encode it locally.
  } finally {
    Atomics.store(status, 0, written);
    Atomics.notify(status, 0);
  }
}
