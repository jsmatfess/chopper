import { browserApi as api, browserDiagnostics, enableBrowserProfiling } from '../src/browser/client';
import type { State, Job } from '../src/app';

let root: FileSystemDirectoryHandle;
let destination: FileSystemDirectoryHandle;
let job: Job;
let lastState: State;
const inventory = async (dir: FileSystemDirectoryHandle) => {
    const names: string[] = [];
    for await (const name of (dir as any).keys()) names.push(name);
    return names.sort();
};
function check(condition: unknown, reason: string) {
    if (!condition) throw new Error(reason);
}
async function workspaces() {
    return inventory(await root.getDirectoryHandle('chopper-workspaces'));
}
async function selectDestination() {
    destination = await root.getDirectoryHandle('quota-probe-' + crypto.randomUUID(), { create: true });
    const picked = await api<{ path: string | null }>('pick-path', { mode: 'output' });
    check(picked.path === destination.name, 'Production client did not select the OPFS directory');
    return destination.name;
}
const hash = async (bytes: ArrayBuffer) => Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
    byte => byte.toString(16).padStart(2, '0'),
).join('');
async function terminal(): Promise<State> {
    const deadline = performance.now() + 12000;
    while (performance.now() < deadline) {
        const state = await api<State>('state');
        if (state.status === 'failed' || state.status === 'complete') return state;
        await new Promise(resolve => setTimeout(resolve, 20));
    }
    throw new Error('Production Run did not reach a terminal state');
}
Object.assign(window, { quotaProbe: {
    async prepare(csv: string, cap: number) {
        enableBrowserProfiling();
        root = await navigator.storage.getDirectory();
        const input = new File([csv], 'input.csv');
        // Only the picker entry points are substituted. They return a real
        // File and a real OPFS handle to the production browser client.
        Object.assign(window, {showOpenFilePicker: async () => [{getFile: async () => input}],
            showDirectoryPicker: async () => destination});
        const defaults = await api<Job>('defaults');
        await api('pick-path', { mode: 'input' });
        const selected = await selectDestination();
        job = {
            ...defaults, input: input.name, output: 'results', operations: [],
            resources: { ...defaults.resources, memory_mb: 256, workers: 1, temp_dir: null },
            limits: { rows: null, bytes: cap, compressed_bytes: null },
        };
        return selected;
    },
    selectDestination,
    async removeSelectedDestination() {
        await root.removeEntry(destination.name);
        return inventory(root);
    },
    async rootEntries() {
        return inventory(root);
    },
    async run() {
        const dispatched = await api<{ dispatched: boolean }>('run-direct', job);
        check(dispatched.dispatched, 'Product did not dispatch Run');
        lastState = await terminal();
        const deadline = performance.now() + 15000;
        for (;;) {
            const workspaceNames = await workspaces();
            const destinationExists = (await inventory(root)).includes(destination.name);
            const after = { workspaces: workspaceNames, destination: destinationExists ? await inventory(destination) : null };
            const storage = browserDiagnostics.storage as {
                workspace_bytes_after_cleanup?: number;
                profiled_destination_bytes?: number;
            } | undefined;
            if ((!workspaceNames.length && (lastState.status === 'complete' || !after.destination?.length) &&
                storage?.workspace_bytes_after_cleanup === 0) || performance.now() >= deadline) {
                lastState = await api<State>('state');
                return { status: lastState.status, error: lastState.error, output: lastState.output, publication: lastState.publication,
                    after, workspaceBytes: storage?.workspace_bytes_after_cleanup,
                    destinationBytes: storage?.profiled_destination_bytes };
            }
            await new Promise(resolve => setTimeout(resolve, 25));
        }
    },
    async verify(rows: number, payload: string, cap: number) {
        const folder = await destination.getDirectoryHandle(lastState.output!.split('/').at(-1)!);
        const file = async (name: string) => (await folder.getFileHandle(name)).getFile();
        const marked = await (await file('CHOPPER-COMPLETE.json')).arrayBuffer();
        const markedText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(marked);
        const marker = JSON.parse(markedText);
        const manifestBytes = await (await file('manifest.jsonl')).arrayBuffer();
        const manifestText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(manifestBytes);
        check(manifestText.endsWith('\n'), 'Manifest lacks terminal LF');
        const [description, ...outputs] = manifestText.slice(0, -1).split('\n').map(row => JSON.parse(row));
        check(description.type === 'job' && description.schema_version === 1 &&
            description.analysis.rows === rows && description.config.limits.bytes === cap &&
            description.analysis.output_files === outputs.length &&
            description.config.operations.length === 0 &&
            description.analysis.workers === 1, 'Manifest job mismatch');
        check(marker.complete === true && marker.files === outputs.length + 1 &&
            marker.engine === 'chopper-browser' && marker.version === 1, 'Invalid completion marker');
        check(markedText === JSON.stringify({ complete: true, files: marker.files,
            engine: 'chopper-browser', version: 1 }) + '\n', 'Unexpected marker bytes');
        const expected = ['manifest.jsonl', 'CHOPPER-COMPLETE.json'];
        let id = 0, total = 0;
        const csv = [];
        for (const entry of outputs) {
            check(entry.type === 'output' && /^[\w.-]+\.csv$/.test(entry.path) &&
                !expected.includes(entry.path) &&
                Array.isArray(entry.lineage) && entry.lineage.length === 0 &&
                entry.compressed_target_exceeded === false, 'Unexpected manifest member');
            const body = await (await file(entry.path)).arrayBuffer();
            check(body.byteLength === entry.csv_bytes && body.byteLength === entry.stored_bytes &&
                body.byteLength <= cap, 'CSV byte cap or manifest size mismatch');
            const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(body);
            check(text.endsWith('\n'), 'Missing terminal LF');
            const [header, ...records] = text.slice(0, -1).split('\n');
            check(header === 'id,key,payload' && records.length === entry.rows, 'CSV header or row count mismatch');
            for (const record of records) {
                check(id < rows && record === `${id},${id % 7},${payload}`, 'Field, order or ID mismatch');
                id++;
            }
            expected.push(entry.path);
            total += body.byteLength;
            csv.push({ name: entry.path, bytes: body.byteLength, rows: entry.rows, sha256: await hash(body) });
        }
        check(JSON.stringify(await inventory(folder)) === JSON.stringify(expected.sort()), 'Export inventory differs from manifest');
        check(id === rows && description.analysis.output_csv_bytes === total, 'Output count or byte total mismatch');
        check(!(await workspaces()).length, 'Workspace after verification');
        return { marker, csv, rows: id, total, manifest_sha256: await hash(manifestBytes),
            marker_sha256: await hash(marked), folder: folder.name };
    },
    async dispose() {
        await api('cancel', {});
        await root.removeEntry(destination.name, { recursive: true });
        return { workspaces: await workspaces(), ownedDestination: (await inventory(root)).includes(destination.name) };
    },
}});
