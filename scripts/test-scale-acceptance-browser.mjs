// Fake transport controls only. They do not establish production Run integration.
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {extract, SLICE_BYTES, TRANSFER_LIMIT} from './scale_acceptance/browser-export.mjs';
import {installPageAdapter} from './scale_acceptance/browser-page.mjs';

const root = await mkdtemp(join(process.argv[3] || tmpdir(), 'chopper-export-controls-'));
const csv = Buffer.alloc(SLICE_BYTES * 2 + 7, 'x');
const marker = Buffer.from(JSON.stringify({complete: true, files: 2, engine: 'chopper-browser', version: 1}));
const files = new Map([['part-00000001.csv', csv], ['manifest.jsonl', Buffer.from('{}\n')],
  ['CHOPPER-COMPLETE.json', marker]]);
let transfers = [];
function fakePage(mutation) {
  return {async evaluate(fn, args) {
    if (!args) {
      const inventory = [...files].map(([name, bytes]) => ({name, size: bytes.length}));
      if (mutation === 'unsafe') inventory[0].name = '../bad.csv';
      if (mutation === 'duplicate') inventory[0].name = inventory[1].name;
      if (mutation === 'missing-marker') return inventory.slice(0, 2);
      return inventory;
    }
    assert(args.length <= SLICE_BYTES);
    transfers.push(args.length);
    const raw = files.get(args.name).subarray(args.offset, args.offset + args.length);
    let encoded = raw.toString('base64');
    if (mutation === 'truncated') encoded = encoded.slice(0, -4);
    if (mutation === 'oversize') encoded = 'A'.repeat(TRANSFER_LIMIT + 1);
    return encoded;
  }};
}
let controls = 0;
try {
  await extract(fakePage(), join(root, 'good'));
  assert.deepEqual(await readFile(join(root, 'good', 'part-00000001.csv')), csv);
  await assert.rejects(extract(fakePage(), join(root, 'byte-denial'), undefined, {maxBytes: 16}), /byte ceiling/);
  controls++;
  assert(transfers.length >= 5 && Math.max(...transfers) <= SLICE_BYTES);
  controls++;
  for (const mutation of ['unsafe', 'duplicate', 'missing-marker', 'truncated', 'oversize']) {
    await assert.rejects(extract(fakePage(mutation), join(root, mutation)));
    controls++;
  }
  for (const value of [null, {complete: false}, {complete: true, files: 3, engine: 'chopper-browser', version: 1},
    {complete: 1, files: 2, engine: 'chopper-browser', version: 1},
    {complete: true, files: 2, engine: 'chopper-browser', version: 2},
    {complete: true, files: 2, engine: 'chopper-browser', version: 1, extra: true}]) {
    files.set('CHOPPER-COMPLETE.json', Buffer.from(JSON.stringify(value)));
    await assert.rejects(extract(fakePage(), join(root, 'marker-' + controls)));
    controls++;
  }
  // Exercise the page-side real Blob slicing code without claiming a browser Run.
  globalThis.window = {};
  globalThis.location = {origin: 'synthetic-control'};
  globalThis.document = {querySelector: () => ({files: []})};
  installPageAdapter(() => { throw new Error('No product API in self-check'); }, () => null);
  await assert.rejects(window.scaleAcceptance.slice('x', 0, SLICE_BYTES + 1));
  await assert.rejects(window.scaleAcceptance.start({}));
  controls += 2;
  const calls = [];
  const handles = {async getFileHandle(name) {return {getFile: async () => new Blob([files.get(name)])};},
    async *entries() {for (const [name, bytes] of files) yield [name, {kind: 'file', getFile: async () => new Blob([bytes])}];}};
  const parent = {getDirectoryHandle: async () => handles};
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {storage: {
    getDirectory: async () => ({getDirectoryHandle: async () => parent}),
    estimate: async () => ({quota: 1000, usage: 100})}}});
  globalThis.crossOriginIsolated = globalThis.isSecureContext = true;
  document.querySelector = () => ({files: [{name: 'selected.csv'}]});
  installPageAdapter(async (path) => {
    calls.push(path);
    if (path === 'defaults') return {resources: {}};
    if (path === 'state') return {status: 'complete', error: null, output: 'parent/results', progress: {rows: 1}};
    return {};
  }, () => null);
  await window.scaleAcceptance.start({resources: {}});
  assert.deepEqual(calls, ['defaults', 'pick-path', 'pick-path', 'run-direct']);
  assert.equal((await window.scaleAcceptance.list()).length, 3);
  const actual = await window.scaleAcceptance.slice('part-00000001.csv', SLICE_BYTES, SLICE_BYTES);
  assert(Buffer.byteLength(JSON.stringify(actual)) <= TRANSFER_LIMIT);
  assert.deepEqual(Buffer.from(actual, 'base64'), csv.subarray(SLICE_BYTES, SLICE_BYTES * 2));
  assert.equal((await window.scaleAcceptance.sample()).usable_bytes, 720);
  controls += 4;
  const result = {status: 'passed', controls, max_raw_transfer: Math.max(...transfers),
    scope: 'fake transport and page argument controls only; frozen production integration UNRUN'};
  if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(result, null, 2) + '\n', {flag: 'wx'});
  console.log(JSON.stringify(result));
} finally { await rm(root, {recursive: true, force: true}); }

// Keep new source-only driver safety controls in the existing Linux/Windows tooling gate.
await import('./scale_acceptance/browser-controls.mjs');
