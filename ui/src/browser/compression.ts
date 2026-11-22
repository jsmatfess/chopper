type Exports = WebAssembly.Instance['exports'];

export const serialCompressionImports = {
  worker_count: () => 0,
  submit: () => 0,
  collect: () => 0,
  shutdown: () => {},
};

type Slot = {
  shared: SharedArrayBuffer;
  status: Int32Array<SharedArrayBuffer>;
  input: Uint8Array<SharedArrayBuffer>;
  output: Uint8Array<SharedArrayBuffer>;
};

export class CompressionWorkers {
  private slots: (Slot | undefined)[] = [];
  private workers: Worker[] = [];
  private module?: WebAssembly.Module;
  private exports?: Exports;
  private count = 0;

  init(module: WebAssembly.Module, exports: Exports) {
    this.module = module;
    this.exports = exports;
  }

  async begin(requestedWorkers: number) {
    if (!crossOriginIsolated || typeof SharedArrayBuffer !== 'function' || !this.module) return;
    const count = Math.min(requestedWorkers || 4, 4, navigator.hardwareConcurrency - 1);
    if (count < 2) return;
    try {
      // Start the nested workers while the engine can still deliver events.
      const ready = [];
      for (let i = 0; i < count; i++) {
        const worker = new Worker(new URL('/engine-worker.js', location.origin), {type: 'module'});
        this.workers.push(worker);
        ready.push(this.startWorker(worker, this.module));
      }
      await Promise.all(ready);
      this.count = count;
    } catch {
      this.close();
    }
  }

  private startWorker(worker: Worker, module: WebAssembly.Module): Promise<void> {
    return new Promise((resolve, reject) => {
      const abort = AbortSignal.timeout(3000);
      abort.addEventListener('abort', () => reject(abort.reason), {once:true});
      worker.addEventListener('error', reject, {once:true,signal:abort});
      worker.addEventListener('message', ({data}) => {
        if (data === 'compression-ready') resolve();
        else reject(new Error('Compression worker initialization failed'));
      }, {once:true,signal:abort});
      worker.postMessage({type:'compression-init', module});
    });
  }

  close() {
    this.count = 0;
    for (const worker of this.workers) worker.terminate();
    this.workers = [];
    this.slots = [];
  }

  private addSlot(): Slot {
    const exports = this.exports!;
    const inputCapacity = (exports.chopper_compression_input_capacity as () => number)();
    const outputCapacity = (exports.chopper_compression_output_capacity as () => number)();
    const shared = new SharedArrayBuffer(4 + inputCapacity + outputCapacity);
    const status = new Int32Array(shared, 0, 1);
    const input = new Uint8Array(shared, 4, inputCapacity);
    const output = new Uint8Array(shared, 4 + inputCapacity, outputCapacity);
    return {shared, status, input, output};
  }

  readonly imports = {
    shutdown: () => this.close(),
    worker_count: () => this.count,
    submit: (index: number, inputPtr: number, size: number) => {
      if (index >= this.count || !this.exports || !this.module) return 0;
      try {
        const slot = this.slots[index] ??= this.addSlot();
        const memory = (this.exports.memory as WebAssembly.Memory).buffer;
        if (size <= 0 || size > slot.input.length) return 0;
        slot.input.set(new Uint8Array(memory, inputPtr, size));
        Atomics.store(slot.status, 0, 0);
        this.workers[index].postMessage({type:'compress-block', shared: slot.shared, size, capacity: slot.input.length});
        return 1;
      } catch {
        return 0;
      }
    },
    collect: (index: number, outputPtr: number, capacity: number) => {
      const slot = this.slots[index];
      if (!slot || !this.exports) return 0;
      // The engine is itself a worker. The codec worker writes the status
      // directly, so no event on the blocked engine worker is needed.
      Atomics.wait(slot.status, 0, 0, 5000);
      const written = Atomics.load(slot.status, 0);
      if (written <= 0 || written > capacity || written > slot.output.length) {
        this.close();
        return 0;
      }
      const memory = (this.exports.memory as WebAssembly.Memory).buffer;
      new Uint8Array(memory, outputPtr, written).set(slot.output.subarray(0, written));
      return written;
    },
  };
}
