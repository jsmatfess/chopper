import {browserApi as api, browserDiagnostics, enableBrowserProfiling} from '../src/browser/client';
import type {Job, State} from '../src/app';

declare global {
  interface Window {
    scaleObservation?: (active: boolean) => Promise<unknown>;
  }
}

type ScaleCase = {job: Partial<Job>; rows: number; profile: boolean; skewed: boolean};

async function waitFor(status: string, deadline: number) {
  let nextQuotaCheck = performance.now();
  while (performance.now() < deadline) {
    if (performance.now() >= nextQuotaCheck) {
      const {quota, usage} = await navigator.storage.estimate();
      if ((quota ?? 0) - (usage ?? 0) < 2 * 2**30) throw new Error('Stopped at the 2 GiB OPFS free-space floor');
      nextQuotaCheck = performance.now() + 1000;
    }
    const state = await api<State>('state');
    if (state.status === 'failed' || state.error) throw new Error(state.error || 'Run failed');
    if (state.status === status) return state;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Scale benchmark step timed out');
}

async function verify(folder: FileSystemDirectoryHandle, rows: number, job: Job, skewed: boolean) {
  async function text(name: string) {
    return (await (await folder.getFileHandle(name)).getFile()).text();
  }
  const manifest = (await text('manifest.jsonl')).trimEnd().split('\n').map(line => JSON.parse(line));
  const outputs = manifest.filter(entry => entry.type === 'output');
  const receipt = JSON.parse(await text('CHOPPER-COMPLETE.json'));
  if (receipt.complete !== true || receipt.version !== 1 || receipt.engine !== 'chopper-browser'
      || receipt.files !== outputs.length + 1) throw new Error('Unexpected completion marker');
  let entries = 0;
  for await (const entry of (folder as FileSystemDirectoryHandle & {values():AsyncIterable<FileSystemHandle>}).values()) {
    if (entry.kind !== 'file') throw new Error('Unexpected result entry');
    entries++;
  }
  if (entries !== outputs.length + 2) throw new Error('Manifest and output inventory differ');
  const seen = new Uint8Array(Math.ceil(rows / 8));
  const payload = 'x'.repeat(1012);
  const partitioned = job.operations.some(op => op.type === 'partition');
  const ordered = !job.operations.some(op => op.type === 'shuffle');
  const lastByKey = new Map<number,number>();
  let total = 0;
  for (const item of outputs) {
    const file = await (await folder.getFileHandle(item.path)).getFile();
    // Verify one capped output file at a time.
    if (file.size !== item.csv_bytes || file.size > 8*1024*1024) throw new Error('Output byte cap or manifest mismatch');
    const lines = (await file.text()).trimEnd().split('\n');
    if (lines.shift() !== 'id,key,payload' || lines.length !== item.rows) throw new Error('Unexpected output header or row count');
    let group: number | undefined;
    for (const line of lines) {
      const id = Number(line.slice(0, 8)), key = Number(line[9]);
      const expected = skewed ? (id % 16 === 0 ? 1 + Math.floor(id / 16) % 7 : 0) : id % 8;
      if (line.length !== 1023 || line[8] !== ',' || line[10] !== ',' ||
          !Number.isInteger(id) || id < 0 || id >= rows || key !== expected ||
          line.slice(11) !== payload || (seen[id >> 3] & (1 << (id & 7)))) throw new Error('Incorrect or repeated output row');
      if (ordered && !partitioned && total !== id) throw new Error('Streaming output changed record order');
      if (ordered && partitioned) {
        if ((lastByKey.get(key) ?? -1) >= id) throw new Error('Partition output changed per-key order');
        lastByKey.set(key,id);
      }
      if (partitioned) {
        group ??= key;
        if (group !== key) throw new Error('Mixed partition keys in one output file');
      }
      seen[id >> 3] |= 1 << (id & 7);
      total++;
    }
  }
  if (total !== rows) throw new Error('Output rows missing');
  return outputs.length;
}

async function scaleRun({job, rows, profile, skewed}: ScaleCase) {
  const input = document.querySelector<HTMLInputElement>('#fixture')?.files?.[0];
  if (!input) throw new Error('A file-backed fixture is required');
  const root = await navigator.storage.getDirectory();
  const ownedName = 'auto-scale-' + crypto.randomUUID();
  const parent = await root.getDirectoryHandle(ownedName,{create:true});
  Object.assign(window,{
    showOpenFilePicker: async()=>[{getFile:async()=>input}],
    showDirectoryPicker: async()=>parent
  });
  try {
    const defaults = await api<Job>('defaults');
    await api('pick-path',{mode:'input'});
    await api('pick-path',{mode:'output'});
    const submitted = {...defaults,...job,input:input.name,output:'results',
      resources:{...defaults.resources,...job.resources,temp_dir:null}};
    const previewStart = performance.now();
    const preview = await api<{columns:number;preview:string[][]}>('preview',submitted);
    const previewSeconds = (performance.now()-previewStart)/1000;
    await window.scaleObservation?.(true);
    const start = performance.now(), deadline = start + 600_000;
    enableBrowserProfiling();
    if (profile) {
      await api('profile',submitted);
      await waitFor('profiled',deadline);
    }
    const runStart = performance.now();
    await api('run-direct',submitted);
    const done = await waitFor('complete',deadline);
    const finished = performance.now();
    const browser_processes = await window.scaleObservation?.(false);
    const storage = browserDiagnostics.storage as {workspace_bytes_after_cleanup:number} | undefined;
    if (storage?.workspace_bytes_after_cleanup !== 0) throw new Error('Workspace cleanup incomplete');
    const folder = await parent.getDirectoryHandle(done.output!.split('/').at(-1)!);
    const outputFiles = await verify(folder,rows,submitted,skewed);
    const analysis = done.analysis!;
    return {
      bytes:input.size, rows, outputFiles, verified:true,
      preview:{columns:preview.columns,rows:preview.preview.length,seconds:previewSeconds},
      elapsed_seconds:(finished-start)/1000, run_seconds:(finished-runStart)/1000,
      analyze_seconds:(runStart-start)/1000, memory_budget_bytes:analysis.memory_budget_bytes,
      diagnostics:analysis.diagnostics, auto_plan:analysis.auto_plan, storage, browser_processes,
      storage_calls:{execute:browserDiagnostics.execute,export:browserDiagnostics.export}
    };
  } finally {
    try { await api('cancel',{}); }
    finally { await root.removeEntry(ownedName,{recursive:true}); }
  }
}

Object.assign(window,{scaleRun});
