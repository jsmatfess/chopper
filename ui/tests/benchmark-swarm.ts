// Isolated test driver. Collection and successful export removal are outside the clock.
import {browserApi as api, enableBrowserProfiling, browserDiagnostics} from '../src/browser/client';
import type {Job, State} from '../src/app';
let root: FileSystemDirectoryHandle, destination: FileSystemDirectoryHandle;
let ownedName = '', folder: FileSystemDirectoryHandle;
let files: {name: string; size: number}[] = [];
const check = (ok: unknown, message: string) => { if (!ok) throw new Error(message); };
Object.assign(window, {
  swarmRun: async (config: Partial<Job>, timeout: number) => {
    enableBrowserProfiling(); // Identical storage/RPC accounting overhead for both WASMs.
    root = await navigator.storage.getDirectory();
    ownedName = 'swarm-' + crypto.randomUUID();
    try { await root.getDirectoryHandle(ownedName); throw new Error('Existing owned destination'); }
    catch (e) { if (!(e instanceof DOMException && e.name === 'NotFoundError')) throw e; }
    destination = await root.getDirectoryHandle(ownedName, {create: true});
    const response = await fetch('/input.csv');
    check(response.ok, 'Fixture fetch failed');
    const input = new File([await response.arrayBuffer()], 'input.csv');
    Object.assign(window, {showOpenFilePicker: async () => [{getFile: async () => input}],
      showDirectoryPicker: async () => destination});
    const defaults = await api<Job>('defaults');
    await api('pick-path', {mode: 'input'}); await api('pick-path', {mode: 'output'});
    const submitted = {...defaults, ...config, input: input.name, output: 'results',
      resources: {...defaults.resources, ...config.resources, temp_dir: null}};
    Object.assign(window, {swarmSubmitted: submitted});
    const start = performance.now(), deadline = start + timeout * 1000;
    const wait = async (status: string) => {
      while (performance.now() < deadline) {
        const state = await api<State>('state');
        if (state.status === 'failed' || state.error) throw new Error(state.error || 'Job failed');
        if (state.status === status) return state;
        await new Promise(r => setTimeout(r, 10));
      }
      throw new Error('Swarm complete-job deadline exceeded');
    };
    await api('run-direct', submitted);
    const done = await wait('complete'), finished = performance.now();
    // complete includes marker close and session retirement/storage cleanup.
    folder = await destination.getDirectoryHandle(done.output!.split('/').at(-1)!);
    files = [];
    for await (const [name, handle] of (folder as any).entries()) {
      check(handle.kind === 'file', 'Unexpected export subdirectory');
      files.push({name, size: (await handle.getFile()).size});
    }
    check(files.some(f => f.name === 'CHOPPER-COMPLETE.json'), 'Completion marker missing');
    const bytes = files.reduce((sum, file) => sum + file.size, 0);
    const storage = browserDiagnostics.storage as any;
    check(storage && storage.workspace_bytes_after_cleanup === 0, 'Workspace cleanup incomplete');
    check(storage.profiled_destination_bytes === bytes, 'Actual export byte accounting mismatch');
    check(storage.peak_open_handles <= 64, 'Open-handle limit exceeded');
    const diagnostics = (done.analysis as any).diagnostics;
    const owners = ['temporary_path_reserved_bytes', 'directory_path_reserved_bytes', 'prepared_job_reserved_bytes',
      'input_header_reserved_bytes', 'analysis_preview_reserved_bytes', 'analysis_warnings_reserved_bytes',
      'analysis_timings_reserved_bytes', 'analysis_text_reserved_bytes', 'stage_stats_reserved_bytes',
      'column_values_reserved_bytes', 'analysis_diagnostics_reserved_bytes'];
    check(diagnostics && diagnostics.workspace_reserved_bytes === owners.reduce((n, k) => n + (diagnostics[k] ?? 0), 0),
      'Retained workspace owner sum mismatch');
    return {submitted, analysis: done.analysis, diagnostics: structuredClone(browserDiagnostics), files,
      export_bytes: bytes, owned_destination: ownedName, output: done.output,
      elapsed_seconds: (finished - start) / 1000, timing_scope: 'complete Run including publication/export and cleanup', analysis_wall_seconds: null,
      execution_seconds: (finished - start) / 1000};
  },
  swarmCollect: async (name: string, offset: number) => {
    check(files.some(f => f.name === name), 'Unlisted collection path');
    const file = await (await folder.getFileHandle(name)).getFile();
    const chunk = new Uint8Array(await file.slice(offset, offset + 1024 * 1024).arrayBuffer());
    let text = ''; for (const byte of chunk) text += String.fromCharCode(byte);
    return btoa(text);
  },
  swarmCleanup: async () => {
    await api('cancel', {});
    await root.removeEntry(ownedName, {recursive: true});
    try { await root.getDirectoryHandle(ownedName); throw new Error('Export cleanup incomplete'); }
    catch (e) { if (!(e instanceof DOMException && e.name === 'NotFoundError')) throw e; }
    return {removed_owned_destination: ownedName};
  },
  swarmFailure: async () => ({state: await api('state'), diagnostics: structuredClone(browserDiagnostics), owned_destination: ownedName}),
});
