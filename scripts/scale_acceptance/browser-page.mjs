// Harness-only bridge. Bundle with the frozen production browser client outside
// ui/dist, then install using that client's browserApi and executionHistory getter.
// This file is NOT a production integration receipt.
export async function observeStorageCapacity() {
  const sampled_unix = Date.now() / 1000;
  const estimate = await navigator.storage.estimate();
  const fact = key => {
    const value = estimate[key];
    return {state: value === undefined ? 'absent' : Number.isFinite(value) ? 'measured' : 'invalid',
      value: Number.isFinite(value) ? value : value === undefined ? null : String(value).slice(0, 128)};
  };
  const quota = fact('quota'), usage = fact('usage');
  const persisted = await navigator.storage.persisted?.() ?? null;
  let persistence_permission = null, persistence_error = null;
  try {persistence_permission = (await navigator.permissions.query({name: 'persistent-storage'})).state;}
  catch (error) {persistence_error = String(error).slice(0, 512);}
  return {sampled_unix, quota, usage, persisted, persistence_permission, persistence_error,
    persistence_request: 'none by capacity observer',
    secure_context: isSecureContext, cross_origin_isolated: crossOriginIsolated, origin: location.origin,
    // Preserve the existing admission calculation; raw states remain distinct.
    usable_bytes: Math.floor(Math.max(0, (estimate.quota || 0) - (estimate.usage || 0)) * 0.8)};
}

export function installPageAdapter(api, history) {
  let parent, folder, capacity, capacityPending;
  const originalOpen = window.showOpenFilePicker;
  const originalDirectory = window.showDirectoryPicker;
  window.scaleAcceptance = {
    async start(job, selector = '#fixture') {
      const file = document.querySelector(selector)?.files?.[0];
      if (!file) throw new Error('Select the declared local File');
      if (!crossOriginIsolated || !isSecureContext) throw new Error('Secure isolated production origin required');
      const root = await navigator.storage.getDirectory();
      parent = await root.getDirectoryHandle('scale-acceptance-' + crypto.randomUUID(), {create: true});
      window.showOpenFilePicker = async () => [{getFile: async () => file}];
      window.showDirectoryPicker = async () => parent;
      try {
        const defaults = await api('defaults');
        await api('pick-path', {mode: 'input'});
        await api('pick-path', {mode: 'output'});
        const config = {...defaults, ...job, input: file.name, output: 'results',
          resources: {...defaults.resources, ...job.resources, temp_dir: null}};
        await api('run-direct', config); // No Analyze/Prepare.
      } finally {
        window.showOpenFilePicker = originalOpen;
        window.showDirectoryPicker = originalDirectory;
      }
    },
    capacity() {
      if (!capacityPending) capacityPending = (async () => {
        return capacity = await observeStorageCapacity();
      })().finally(() => {capacityPending = null;});
      return capacityPending;
    },
    async sample(includeCapacity = true) {
      const state = await api('state');
      const observed = includeCapacity ? await this.capacity() : capacity;
      const graph = history();
      // Same conservative 80% origin estimate used by the production client.
      let snapshot = graph ? {unavailable: graph.unavailable, eventsOmitted: graph.eventsOmitted,
        steps: graph.steps.slice(0, 1156), events: graph.events.slice(0, 8192)} : null;
      if (snapshot && new TextEncoder().encode(JSON.stringify(snapshot)).length > 512 * 1024)
        snapshot = {unavailable: true, truncated: true};
      return {secure_context: isSecureContext, cross_origin_isolated: crossOriginIsolated,
        origin: location.origin, ...observed,
        status: state.status, error: state.error ? String(state.error).slice(0, 4096) : null,
        output: state.output ? String(state.output).slice(0, 4096) : null,
        progress: {phase: String(state.progress?.phase || '').slice(0, 4096), rows: state.progress?.rows,
          temp_bytes: state.progress?.temp_bytes}, state_sampled_unix: Date.now() / 1000,
        graph: snapshot};
    },
    async list() {
      const state = await api('state');
      if (state.status !== 'complete' || state.error || !state.output) throw new Error('Run not successfully complete');
      folder = await parent.getDirectoryHandle(state.output.split('/').at(-1));
      const files = [];
      for await (const [name, handle] of folder.entries()) {
        if (files.length >= 4098 || handle.kind !== 'file') throw new Error('Unexpected export entry/count');
        if (!/^(?:(?:region-r[0-7]-allocation-(?:treatment|control)-)?part-[0-9]{8}\.csv|manifest\.jsonl|CHOPPER-COMPLETE\.json)$/.test(name))
          throw new Error('Unsafe export name');
        const file = await handle.getFile();
        files.push({name, size: file.size});
      }
      if (new TextEncoder().encode(JSON.stringify(files)).length > 1024 * 1024) throw new Error('Unbounded inventory');
      return files;
    },
    async slice(name, offset, length) {
      if (!folder || !Number.isSafeInteger(offset) || offset < 0 ||
          !Number.isSafeInteger(length) || length < 1 || length > 512 * 1024) throw new Error('Invalid bounded slice');
      const file = await (await folder.getFileHandle(name)).getFile();
      const bytes = new Uint8Array(await file.slice(offset, offset + length).arrayBuffer());
      // Avoid an argument list/string proportional to a complete output file.
      let binary = '';
      for (let start = 0; start < bytes.length; start += 8192)
        binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
      return btoa(binary); // <=699052 ASCII bytes, below 1 MiB including framing.
    },
    async cancel() { await api('cancel', {}); },
    async incomplete() {
      const entries = [], workspaces = [];
      for await (const [name] of parent.entries()) {
        if (entries.length >= 16) throw new Error('Incomplete output census bound');
        entries.push(name);
      }
      const root = await navigator.storage.getDirectory();
      let workspace;
      try {workspace = await root.getDirectoryHandle('chopper-workspaces');}
      catch (error) {if (error.name !== 'NotFoundError') throw error;}
      if (workspace) for await (const [name] of workspace.entries()) {
        if (workspaces.length >= 16) throw new Error('Workspace census bound');
        workspaces.push(name);
      }
      const locks = (await navigator.locks.query()).held.filter(lock => lock.name.startsWith('chopper-')).map(lock => lock.name);
      return {entries: entries.sort(), workspaces: workspaces.sort(), locks: locks.sort()};
    }
  };
}


// Reopen one already committed OPFS export; no engine API or Run is exposed.
export async function installRecoveredExport(output) {
  const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
  if (typeof output !== 'string' || !new RegExp('^scale-acceptance-' + uuid + '/chopper-results-' + uuid + '$').test(output))
    throw new Error('Exact recorded completed export path required');
  const [parentName, folderName] = output.split('/');
  const root = await navigator.storage.getDirectory();
  const parent = await root.getDirectoryHandle(parentName, {create: false});
  const folder = await parent.getDirectoryHandle(folderName, {create: false});
  const safe = name => /^(?:(?:region-r[0-7]-allocation-(?:treatment|control)-)?part-[0-9]{8}\.csv|manifest\.jsonl|CHOPPER-COMPLETE\.json)$/.test(name);
  window.scaleAcceptance = {
    async list() {
      const files = [];
      for await (const [name, handle] of folder.entries()) {
        if (files.length >= 4098 || handle.kind !== 'file' || !safe(name)) throw new Error('Unexpected completed export entry/count');
        const file = await handle.getFile();
        files.push({name, size: file.size});
      }
      if (new TextEncoder().encode(JSON.stringify(files)).length > 1024 * 1024) throw new Error('Unbounded export inventory');
      return files;
    },
    async slice(name, offset, length) {
      if (!safe(name) || !Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(length) ||
          length < 1 || length > 512 * 1024) throw new Error('Invalid bounded export slice');
      const file = await (await folder.getFileHandle(name, {create: false})).getFile();
      if (offset + length > file.size) throw new Error('Completed export changed/truncated');
      const bytes = new Uint8Array(await file.slice(offset, offset + length).arrayBuffer());
      let binary = '';
      for (let start = 0; start < bytes.length; start += 8192)
        binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
      return btoa(binary);
    },
  };
}
