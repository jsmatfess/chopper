import {browserApi as api} from '../src/browser/client';
import type {Job, State} from '../src/app';

declare global {
  interface Window {
    compressionBenchmark(job: Partial<Job>): Promise<unknown>;
  }
}

window.compressionBenchmark = async job => {
  const input = document.querySelector<HTMLInputElement>('#fixture')?.files?.[0];
  if (!input) throw new Error('Select the benchmark fixture');
  const root = await navigator.storage.getDirectory();
  const name = 'compression-bench-' + crypto.randomUUID();
  const parent = await root.getDirectoryHandle(name, {create:true});
  Object.assign(window, {
    showOpenFilePicker: async () => [{getFile: async () => input}],
    showDirectoryPicker: async () => parent,
  });
  const defaults = await api<Job>('defaults');
  await api('pick-path', {mode:'input'});
  await api('pick-path', {mode:'output'});
  try {
    const start = performance.now();
    await api('run-direct', {
      ...defaults, ...job, input:input.name, output:'results',
      resources:{...defaults.resources, ...job.resources},
      limits:{...defaults.limits, ...job.limits},
    });
    let state: State;
    while (true) {
      state = await api<State>('state');
      if (state.status === 'complete' && !state.error) break;
      if (state.status === 'failed' || state.error) throw new Error(state.error || 'Run failed');
      if (performance.now() - start > 420_000) throw new Error('Run exceeded the benchmark deadline');
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    const seconds = (performance.now() - start) / 1000;
    if (!state.output || !state.analysis) throw new Error('Run did not report completed output');
    const result = await parent.getDirectoryHandle(state.output.split('/').at(-1)!);
    const marker = JSON.parse(await (await (await result.getFileHandle('CHOPPER-COMPLETE.json')).getFile()).text());
    let files = 0;
    const entries = result as unknown as {entries(): AsyncIterable<[string, FileSystemHandle]>};
    for await (const [fileName, handle] of entries.entries()) {
      if (handle.kind !== 'file') throw new Error('Unexpected directory in result');
      const file = await (handle as FileSystemFileHandle).getFile();
      // Streaming host extraction and independent verification are outside Run timing.
      const response = await fetch('/result/' + encodeURIComponent(fileName), {method:'PUT', body:file});
      if (!response.ok) throw new Error('Host extraction failed: ' + fileName);
      if (fileName !== 'CHOPPER-COMPLETE.json') files++;
    }
    if (!marker.complete || marker.files !== files || marker.engine !== 'chopper-browser') {
      throw new Error('Completion marker disagrees with exported files');
    }
    return {seconds, analysis:state.analysis, hardware_concurrency:navigator.hardwareConcurrency,
      cross_origin_isolated:crossOriginIsolated, marker};
  } finally {
    await api('cancel', {});
    await root.removeEntry(name, {recursive:true});
  }
};
